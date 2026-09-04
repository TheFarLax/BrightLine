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
    "localnet": {"chain": g.localnet, "rpc": "http://127.0.0.1:4000/api", "faucet": "sim"},
    "studionet": {"chain": g.studionet, "rpc": "https://studio.genlayer.com/api", "faucet": "sim"},
    "testnet-bradbury": {
        "chain": g.testnet_bradbury,
        "rpc": "https://rpc-bradbury.genlayer.com",
        "faucet": "external",
        "explorer_tx": "https://explorer-bradbury.genlayer.com/tx/",
    },
    "testnet-asimov": {
        "chain": g.testnet_asimov,
        "rpc": "https://rpc-asimov.genlayer.com",
        "faucet": "external",
        "explorer_tx": "https://explorer-asimov.genlayer.com/tx/",
    },
}


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


class Chain:
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
              retries: int = 40, leader_only: bool = False) -> dict:
        tx = self.client.write_contract(
            address=address, function_name=fn, account=self.account, args=args,
            consensus_max_rotations=rotations, sim_config=sim, leader_only=leader_only,
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
