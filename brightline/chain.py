"""Network access for Brightline.

Wraps genlayer-py for signed operations and raw JSON-RPC for the two node methods
we need that the Python SDK does not surface: `gen_call` with `leader_results`
(validator-mode replay) and `gen_getTransactionReceipt` (per-round vote data).

Environments differ in RPC shape -- Studio-era endpoints take `transaction_hash`,
the node API takes `txId` -- so receipt access is capability-probed, never assumed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import genlayer_py as g
import requests
from genlayer_py.types.contracts import SimConfig, SimValidatorConfig
from genlayer_py.types.transactions import TransactionStatus

REPO = Path(__file__).resolve().parent.parent
KEYFILE = REPO / ".brightline" / "accounts.json"

NETWORKS: dict[str, dict[str, Any]] = {
    "localnet": {"chain": g.localnet, "rpc": "http://127.0.0.1:4000/api",
                 "faucet": "sim", "api": "studio"},
    "studionet": {"chain": g.studionet, "rpc": "https://studio.genlayer.com/api",
                  "faucet": "sim", "api": "studio"},
    "testnet-bradbury": {
        "chain": g.testnet_bradbury,
        "rpc": "https://rpc-bradbury.genlayer.com",
        "faucet": "external",
        "api": "node",
        "explorer_tx": "https://explorer-bradbury.genlayer.com/tx/",
    },
    "testnet-asimov": {
        "chain": g.testnet_asimov,
        "rpc": "https://rpc-asimov.genlayer.com",
        "faucet": "external",
        "api": "node",
        "explorer_tx": "https://explorer-asimov.genlayer.com/tx/",
    },
}

# Terminal consensus statuses from the documented v0.6 status table. Bradbury also
# reports status 14, which is outside the documented 0-13 range and unknown to
# genlayer-py 0.16.3 (`KeyError: '14'`), so status handling here is by name from
# `gen_getTransactionStatus` and never through the SDK's decoder.
#
# LeaderTimeout and ValidatorsTimeout are deliberately NOT terminal: the docs
# describe both as leaving the appeal window open, and a transaction observed at
# LeaderTimeout on Bradbury went on to Finalize with FinishedWithReturn. Treating
# them as terminal reports a false failure.
TERMINAL_STATUSES = {"Accepted", "Finalized", "Undetermined", "Canceled"}
APPEALABLE_STATUSES = {"LeaderTimeout", "ValidatorsTimeout"}


@dataclass
class ValidatorPin:
    """One pinned validator for a controlled run (calibration arms A0-A4)."""

    provider: str
    model: str
    temperature: float | None = None
    stake: int = 10
    plugin: str | None = None
    plugin_config: dict[str, Any] = field(default_factory=dict)

    def to_sim(self) -> SimValidatorConfig:
        cfg: dict[str, Any] = {}
        if self.temperature is not None:
            cfg["temperature"] = self.temperature
        out: dict[str, Any] = {
            "stake": self.stake,
            "provider": self.provider,
            "model": self.model,
            "config": cfg,
        }
        if self.plugin:
            out["plugin"] = self.plugin
        if self.plugin_config:
            out["plugin_config"] = self.plugin_config
        return out  # type: ignore[return-value]


def load_or_create_account(name: str = "default") -> Any:
    """Persist a dev key locally so runs are reproducible across invocations.

    Dev keys only. Never used for anything holding real value.
    """
    env = os.environ.get("BRIGHTLINE_PRIVATE_KEY")
    if env:
        return g.create_account(env)
    KEYFILE.parent.mkdir(parents=True, exist_ok=True)
    store = json.loads(KEYFILE.read_text()) if KEYFILE.exists() else {}
    if name not in store:
        store[name] = g.generate_private_key().hex() if isinstance(
            g.generate_private_key(), bytes
        ) else str(g.generate_private_key())
        KEYFILE.write_text(json.dumps(store, indent=2))
        KEYFILE.chmod(0o600)
    return g.create_account(store[name])


class NodeWriteMixin:
    """Write path for node-API networks (Bradbury, Asimov).

    genlayer-py 0.16.3 cannot complete a write here for two independent reasons:

    * `_prepare_transaction` sets `gas` from a raw `eth_estimateGas` result, and the
      submission reverted at the EVM layer in practice. Sending the identical
      calldata with an explicit, headroomed gas limit succeeds (status 1, ~912k gas
      used against a ~964k estimate), so the transaction is gas-bound, not
      fee-bound: `addTransaction` is payable but accepts a zero deposit on Bradbury.
    * `get_transaction` / `wait_for_transaction_receipt` raise `KeyError: '14'`
      because Bradbury reports a consensus status outside the SDK's map.

    So we encode and sign with the SDK's own helpers, submit with our own gas
    headroom, recover the GenLayer transaction id from the `NewTransaction` event,
    and then poll and fetch entirely over raw JSON-RPC.
    """

    GAS_HEADROOM = 1.6
    GAS_FLOOR = 1_500_000

    def _node_write(self, address: str, fn: str, args: list[Any],
                    rotations: int | None, value: int, timeout: int,
                    poll: float) -> dict:
        from genlayer_py.abi.calldata import encode as calldata_encode
        from genlayer_py.abi.transactions import serialize
        from genlayer_py.contracts.actions import _encode_add_transaction_data
        from genlayer_py.contracts.utils import make_calldata_object
        from web3.logs import DISCARD

        w3 = self.client.w3
        inner = serialize([
            calldata_encode(make_calldata_object(method=fn, args=args, kwargs=None)),
            b"\x00",
        ])
        max_rot = self.meta["chain"].default_consensus_max_rotations if rotations is None else rotations
        data = _encode_add_transaction_data(
            self.client, self.account, address, int(max_rot), inner, 0)

        cm = self.meta["chain"].consensus_main_contract["address"]
        base = {"from": self.address(), "to": cm, "data": data, "value": hex(value)}
        try:
            gas = int(int(w3.eth.estimate_gas(base)) * self.GAS_HEADROOM)
        except Exception:
            gas = self.GAS_FLOOR
        gas = max(gas, self.GAS_FLOOR)

        latest = w3.eth.get_block("latest")
        priority = w3.to_wei(2, "gwei")
        tx = {"from": self.address(), "to": cm, "data": data, "value": value,
              "nonce": self.client.get_current_nonce(self.address()),
              "chainId": self.meta["chain"].id, "gas": gas,
              "maxFeePerGas": int(latest["baseFeePerGas"]) + priority,
              "maxPriorityFeePerGas": priority}
        signed = self.account.sign_transaction(tx)
        # Bradbury answers -32005 "transaction gas rate limit exceeded" when the node
        # is at capacity and supplies retryAfterMs. Honour it rather than failing the
        # whole arm.
        import time as _t
        evm_hash = None
        for attempt in range(1, 7):
            try:
                evm_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                break
            except Exception as exc:
                msg = str(exc)
                if "-32005" not in msg and "rate limit" not in msg.lower():
                    raise
                wait = 2.0 * attempt
                for token in ("retryAfterMs\":", "retryAfterMs': "):
                    if token in msg:
                        try:
                            wait = max(wait, int("".join(
                                c for c in msg.split(token)[1][:8] if c.isdigit())) / 1000)
                        except Exception:
                            pass
                print(f"    rate limited, retry {attempt}/6 in {wait:.1f}s")
                _t.sleep(wait)
        if evm_hash is None:
            raise RuntimeError(f"{fn}: node stayed at capacity after 6 attempts")
        evm_receipt = w3.eth.wait_for_transaction_receipt(evm_hash, timeout=240)
        if evm_receipt.status != 1:
            raise RuntimeError(
                f"EVM submission reverted for {fn} "
                f"(gas={gas}, used={evm_receipt.gasUsed}, tx={evm_hash.hex()})")

        contract = w3.eth.contract(abi=self.meta["chain"].consensus_main_contract["abi"])
        events = contract.get_event_by_name("NewTransaction").process_receipt(
            evm_receipt, DISCARD)
        if not events:
            raise RuntimeError(f"{fn}: no NewTransaction event; not picked up by consensus")
        tx_id = w3.to_hex(events[0]["args"]["txId"])

        status, code = self.wait_status(tx_id, timeout=timeout, poll=poll)
        receipt = self.node_receipt(tx_id) or {}
        receipt.setdefault("hash", tx_id)
        receipt.setdefault("statusName", status)
        receipt.setdefault("status", code)
        receipt["evm_tx"] = evm_hash.hex()
        receipt["evm_gas_used"] = evm_receipt.gasUsed
        receipt["gas_limit_sent"] = gas
        return receipt

    def wait_status(self, tx_id: str, timeout: int = 600,
                    poll: float = 5.0) -> tuple[str, int | None]:
        """Poll `gen_getTransactionStatus` until a terminal consensus status.

        Deliberately not the SDK's waiter: this reports whatever name the node
        gives, including statuses the SDK's table does not know about.
        """
        import time as _time

        deadline = _time.time() + timeout
        last: tuple[str, int | None] = ("", None)
        while _time.time() < deadline:
            ok, payload = self.rpc_supports("gen_getTransactionStatus", [{"txId": tx_id}])
            if ok and isinstance(payload, dict):
                last = (str(payload.get("status", "")), payload.get("statusCode"))
                if last[0] in TERMINAL_STATUSES:
                    return last
            _time.sleep(poll)
        return last


class Chain(NodeWriteMixin):
    def __init__(self, network: str = "studionet", account: Any | None = None):
        if network not in NETWORKS:
            raise SystemExit(f"unknown network {network!r}; have {list(NETWORKS)}")
        self.network = network
        self.meta = NETWORKS[network]
        self.account = account or load_or_create_account()
        self.client = g.create_client(chain=self.meta["chain"], account=self.account)
        self.rpc_url = self.meta["rpc"]
        self._rpc_id = 0
        # The public testnet endpoint sits behind bot protection that rejects the
        # default python-requests User-Agent with a 403 interstitial. Any explicit
        # UA passes, so identify ourselves rather than looking like a scraper.
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "brightline/0.1 (agreement fuzzer; GenLayer Agent Tank)",
            "Content-Type": "application/json",
        })

    # ------------------------------------------------------------------ raw JSON-RPC
    def rpc(self, method: str, params: Any) -> dict:
        self._rpc_id += 1
        r = self._session.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "method": method, "params": params, "id": self._rpc_id},
            timeout=180,
        )
        r.raise_for_status()
        return r.json()

    def rpc_supports(self, method: str, params: Any) -> tuple[bool, Any]:
        """Probe a method. Returns (supported, payload). A -32601 means absent;
        any other error means present-but-misused, which still proves support."""
        try:
            out = self.rpc(method, params)
        except Exception as exc:  # network-level failure
            return False, {"transport_error": str(exc)}
        err = out.get("error")
        if err and err.get("code") == -32601:
            return False, err
        return True, out.get("result", err)

    # ---------------------------------------------------------------------- funding
    def address(self) -> str:
        return self.account.address

    def balance(self) -> int:
        return int(self.client.get_balance(self.account.address))

    def fund(self, amount_wei: int = 10**20) -> str | None:
        if self.meta["faucet"] != "sim":
            return None
        return self.client.fund_account(self.account.address, amount_wei).hex()

    # ------------------------------------------------------------------- deployment
    def deploy(self, contract_path: str | Path, sim: SimConfig | None = None,
               rotations: int | None = None) -> tuple[str, str]:
        code = Path(contract_path).read_text()
        tx = self.client.deploy_contract(
            code=code, account=self.account, args=[],
            consensus_max_rotations=rotations, sim_config=sim,
        )
        tx_hash = tx.hex() if isinstance(tx, (bytes, bytearray)) else str(tx)
        receipt = self.client.wait_for_transaction_receipt(
            transaction_hash=tx_hash, status=TransactionStatus.ACCEPTED,
            interval=3000, retries=40,
        )
        addr = receipt.get("recipient") or receipt.get("contract_address") or ""
        return str(addr), tx_hash

    # ------------------------------------------------------------------ interaction
    def write(self, address: str, fn: str, args: list[Any],
              sim: SimConfig | None = None, rotations: int | None = None,
              wait: TransactionStatus = TransactionStatus.ACCEPTED,
              retries: int = 40, leader_only: bool = False,
              value: int = 0, timeout: int = 900, poll: float = 5.0) -> dict:
        """Submit a write and wait for a terminal consensus status.

        Studio-era networks go through the SDK, which is where `sim_config` (the
        pinned-model panel) is supported. Node-API networks use `_node_write`, which
        exists because the SDK cannot complete a write against Bradbury -- see
        NodeWriteMixin for the two reasons.
        """
        if self.meta.get("api") == "node":
            if sim is not None or leader_only:
                raise RuntimeError(
                    "sim_config / leader_only are Studio-only; the PANEL channel "
                    "cannot run on a public testnet, which is why the LIVE arm "
                    "reports votes rather than a decision distribution")
            return self._node_write(address, fn, args, rotations, value, timeout, poll)

        tx = self.client.write_contract(
            address=address, function_name=fn, account=self.account, args=args,
            consensus_max_rotations=rotations, sim_config=sim, leader_only=leader_only,
            value=value,
        )
        tx_hash = tx.hex() if isinstance(tx, (bytes, bytearray)) else str(tx)
        receipt = self.client.wait_for_transaction_receipt(
            transaction_hash=tx_hash, status=wait, interval=3000,
            retries=retries, full_transaction=True,
        )
        if isinstance(receipt, dict):
            receipt.setdefault("hash", tx_hash)
        return receipt

    def read(self, address: str, fn: str, args: list[Any] | None = None,
             final: bool = False) -> Any:
        """Read a view method, tolerating both `gen_call` response shapes.

        Studio-era endpoints return `result` as a hex string. The node API returns
        the documented object (`data`, `eqOutputs`, `status`, `stdout`, ...), which
        makes genlayer-py's `read_contract` fail on `"0x" + enc_result`. Request
        encoding is identical either way -- RLP over `[calldata, b"\\x00"]` -- so we
        build it with the SDK's own helpers and only normalize the response.
        """
        from genlayer_py.abi.calldata import decode as calldata_decode
        from genlayer_py.abi.calldata import encode as calldata_encode
        from genlayer_py.abi.transactions import serialize
        from genlayer_py.contracts.utils import make_calldata_object
        from genlayer_py.types.transactions import TransactionHashVariant

        variant = (TransactionHashVariant.LATEST_FINAL if final
                   else TransactionHashVariant.LATEST_NONFINAL)
        payload = serialize([
            calldata_encode(make_calldata_object(method=fn, args=args or [], kwargs=None)),
            b"\x00",
        ])
        out = self.rpc("gen_call", [{
            "type": "read", "to": address, "from": self.address(),
            "data": payload, "transaction_hash_variant": variant.value,
        }])
        if out.get("error"):
            raise RuntimeError(f"gen_call read {fn} failed: {out['error']}")

        result = out.get("result")
        if isinstance(result, dict):
            status = result.get("status") or {}
            if status and status.get("code") not in (0, None):
                raise RuntimeError(
                    f"gen_call read {fn}: {status.get('message')} "
                    f"{result.get('stderr', '')}".strip())
            encoded = result.get("data")
        else:
            encoded = result
        if not encoded:
            return None

        hexstr = str(encoded)
        hexstr = hexstr[2:] if hexstr.startswith("0x") else hexstr
        return calldata_decode(bytes.fromhex(hexstr))

    def trace(self, tx_hash: str, round_: int = 0) -> dict:
        return self.client.debug_trace_transaction(transaction_hash=tx_hash, round=round_)

    def transaction(self, tx_hash: str) -> dict:
        return self.client.get_transaction(transaction_hash=tx_hash)

    def node_receipt(self, tx_hash: str) -> dict | None:
        """gen_getTransactionReceipt -- the node API surface carrying roundData.

        Absent on Studio-era endpoints; callers must handle None (that is the E4
        fallback path, not an error).
        """
        ok, payload = self.rpc_supports("gen_getTransactionReceipt", [{"txId": tx_hash}])
        if not ok:
            return None
        return payload if isinstance(payload, dict) else None

    def explorer(self, tx_hash: str) -> str:
        base = self.meta.get("explorer_tx")
        return f"{base}{tx_hash}" if base else tx_hash


def sim_config(validators: list[ValidatorPin] | None = None,
               genvm_datetime: str | None = None) -> SimConfig | None:
    """Build a SimConfig, or None when we want the network's own validator set."""
    if not validators and not genvm_datetime:
        return None
    out: dict[str, Any] = {}
    if validators:
        out["validators"] = [v.to_sim() for v in validators]
    if genvm_datetime:
        out["genvm_datetime"] = genvm_datetime
    return out  # type: ignore[return-value]
