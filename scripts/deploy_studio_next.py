"""Deploy the three Brightline contracts on Studio Next (chain 61997).

Runs under `.venv-rc` (genlayer-py 0.19.0rc2), not `.venv`. Studio Next is consensus
v0.6: `addTransaction` takes one packed tuple and reverts with `FeesDistributionMissing`
unless the transaction carries a fee quote. genlayer-py 0.16.3 -- the SDK every
published studionet measurement was produced with -- encodes the older flat six-argument
form, so its transactions revert at the EVM layer before GenVM ever sees them. 0.19.0rc2
speaks v0.6, and also renames `TransactionStatus` out from under `brightline/chain.py`,
which is why it lives in a second venv instead of replacing the first.

    .venv-rc/bin/python scripts/deploy_studio_next.py
    .venv-rc/bin/python scripts/deploy_studio_next.py --verify-only

Addresses land in `.brightline/deployments.json` under the `studio-next` key, beside the
untouched `studionet` entries, so `scripts/export_frontend_config.py` picks them up the
same way it always has and the old evidence stays exactly where it was.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import genlayer_py as g  # noqa: E402
from genlayer_py.chains import studio_devnet  # noqa: E402

from brightline.genvm03 import RUNNER_V03, to_genvm03  # noqa: E402
from brightline.spec import sha  # noqa: E402
from brightline.state import latest, save_deployment  # noqa: E402

NETWORK = "studio-next"
RPC = "https://studio-next.genlayer.com/api"
EXPLORER = "https://explorer-studio-dev.genlayer.com"

CONTRACTS = [
    ("probe", ROOT / "contracts" / "brightline_probe.py", []),
    ("registry", ROOT / "contracts" / "brightline_registry.py", []),
    # ctor arg filled in from the registry deployed in the same run: the gate must point
    # at this network's registry, never at the 61999 one.
    ("escrow", ROOT / "contracts" / "gated_escrow.py", ["<registry>"]),
]

OUT = ROOT / "experiments" / "E9_studio_next"


def chain():
    """studio_devnet with the Studio Next hostname.

    Same chain either way -- both hosts answer eth_chainId 0xf22d and share state, which
    this script re-checks below rather than trusting -- but the deployment is reported
    against the host the network is named for.
    """
    import dataclasses

    return dataclasses.replace(
        studio_devnet, name="GenLayer Studio Next",
        rpc_urls={"default": {"http": [RPC]}})


def client():
    key = json.loads((ROOT / ".brightline" / "accounts.json").read_text())["default"]
    acct = g.create_account(key)
    return g.create_client(chain=chain(), account=acct), acct


def assert_chain_id(c) -> int:
    """Refuse to touch anything unless the endpoint really is 61997.

    A wrong-network deployment that silently succeeds is the failure mode this whole
    task exists to avoid, so it is checked against the node rather than the config.
    """
    got = int(c.provider.make_request("eth_chainId", [])["result"], 16)
    if got != 61997:
        raise SystemExit(f"{RPC} reports chain {got}, not 61997 -- refusing to deploy")
    return got


def fund_if_needed(c, acct, floor: int = 5 * 10**18) -> None:
    bal = int(c.get_balance(acct.address))
    if bal >= floor:
        print(f"  balance {bal / 10**18:.2f} GEN")
        return
    print(f"  balance {bal / 10**18:.2f} GEN -- funding from the Studio faucet")
    c.provider.make_request("sim_fundAccount", [acct.address, 10**20])
    for _ in range(12):
        time.sleep(3)
        if int(c.get_balance(acct.address)) > bal:
            print(f"  balance {int(c.get_balance(acct.address)) / 10**18:.2f} GEN")
            return
    raise SystemExit("faucet did not credit the account")


def deploy_one(c, acct, name: str, path: Path, args: list) -> dict:
    source = to_genvm03(path.read_text())
    code_hash = sha(source)
    existing = latest(NETWORK, code_hash, name=name)
    if existing:
        print(f"  {name:<9} reusing {existing['address']} (same source hash)")
        return existing

    fees = c.estimate_transaction_fees()
    print(f"  {name:<9} deploying, fee quote {int(fees['feeValue']) / 10**18:.4f} GEN")
    tx = c.deploy_contract(code=source, account=acct, args=args, fees=fees)
    tx_hash = tx.hex() if isinstance(tx, (bytes, bytearray)) else str(tx)
    rec = c.wait_for_transaction_receipt(
        transaction_hash=tx_hash, wait_until="decided", interval=3000, retries=80)

    leader = (rec.get("consensus_data") or {}).get("leader_receipt") or []
    result = (leader[0] if leader else {}).get("result") or {}
    if result.get("status") not in (None, "return", "ok"):
        raise SystemExit(f"{name} deploy did not execute: {result.get('status')} "
                         f"{result.get('payload')}  tx={tx_hash}")
    address = rec.get("recipient") or rec.get("contract_address")
    if not address:
        raise SystemExit(f"{name} deploy returned no address; tx={tx_hash}")

    save_deployment(NETWORK, str(address), tx_hash, code_hash,
                    runner=RUNNER_V03, name=name,
                    extra={"ctor_args": args, "genvm": "v0.3", "consensus": "v0.6"})
    print(f"  {name:<9} {address}  tx={tx_hash}")
    return {"address": str(address), "tx": tx_hash}


def seed(c, acct, probe_addr: str) -> dict:
    """Register the rule and the whole frozen probe set on the fresh probe contract.

    Not optional. Quick Check offers every probe in the manifest, and `adjudicate`
    refuses a probe_id it has never seen -- so a deployment with one probe registered is
    a demo that fails on seven of eight clicks. Idempotent: a probe already on chain is
    skipped, so re-running costs nothing.

    The strings registered are `normalized` and `canonical`, the exact bytes the rule
    hash and probe ids are computed over, which is what lets anyone recompute the ids
    from the committed artifacts.
    """
    report = json.loads((ROOT / "reports" /
                         "v1_ps_6ce467da9d20c1f2_studionet.json").read_text())
    rule_hash = report["rule"]["rule_hash"]
    manifest = json.loads((ROOT / "probes" / "ps_6ce467da9d20c1f2.json").read_text())
    out: dict[str, str] = {}

    if not c.read_contract(address=probe_addr, function_name="get_rule",
                           args=[rule_hash]):
        rec = _send(c, acct, probe_addr, "register_rule",
                    [rule_hash, report["rule"]["normalized"]])
        out["rule"] = rec
        print(f"  rule      registered {rule_hash[:14]}")
    else:
        print(f"  rule      already on chain {rule_hash[:14]}")

    for p in manifest["probes"]:
        if c.read_contract(address=probe_addr, function_name="get_probe",
                           args=[p["probe_id"]]):
            continue
        out[f"probe_{p['index']}"] = _send(c, acct, probe_addr, "register_probe",
                                           [p["probe_id"], p["canonical"]])
        print(f"  probe #{p['index']}  registered {p['probe_id'][:14]}  ({p['family']})")
    return out


def _send(c, acct, address: str, fn: str, args: list) -> str:
    fees = c.estimate_transaction_fees()
    tx = c.write_contract(address=address, function_name=fn, account=acct, args=args,
                          fees=fees)
    h = tx.hex() if isinstance(tx, (bytes, bytearray)) else str(tx)
    c.wait_for_transaction_receipt(transaction_hash=h, wait_until="decided",
                                   interval=3000, retries=80)
    return h


def main() -> int:
    ap = argparse.ArgumentParser(prog="deploy_studio_next")
    ap.add_argument("--verify-only", action="store_true",
                    help="re-read the recorded deployment without sending anything")
    ap.add_argument("--seed-only", action="store_true",
                    help="register the rule and probe set on the recorded probe contract")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    c, acct = client()
    print(f"network   {NETWORK}  chain {assert_chain_id(c)}  {RPC}")
    print(f"account   {acct.address}")
    print(f"runner    {RUNNER_V03}")

    if args.verify_only:
        out = {}
        for name, _, _ in CONTRACTS:
            e = latest(NETWORK, None, name=name)
            out[name] = e["address"] if e else None
            print(f"  {name:<9} {out[name]}")
        return 0

    if args.seed_only:
        probe_addr = (latest(NETWORK, None, name="probe") or {}).get("address")
        if not probe_addr:
            raise SystemExit("no probe contract recorded for studio-next")
        fund_if_needed(c, acct, floor=2 * 10**18)
        print(f"\nseeding {probe_addr}")
        seed(c, acct, probe_addr)
        return 0

    fund_if_needed(c, acct)
    print("\ndeploying (GenVM 0.3 source, fee-quoted v0.6 transactions)")
    addresses: dict[str, str] = {}
    for name, path, ctor in CONTRACTS:
        ctor = [addresses["registry"] if a == "<registry>" else a for a in ctor]
        entry = deploy_one(c, acct, name, path, ctor)
        addresses[name] = entry["address"]

    # The gate has to be pointed at this network's registry. Read it back off chain
    # rather than trusting the constructor argument we passed.
    bound = c.read_contract(address=addresses["escrow"], function_name="registry_address",
                            args=[])
    print(f"\nescrow.registry_address() -> {bound}")
    if str(bound).lower() != addresses["registry"].lower():
        raise SystemExit(f"escrow is bound to {bound}, not {addresses['registry']}")
    print("  escrow is bound to this network's registry")

    print("\nseeding the probe contract with the rule and the frozen probe set")
    seed(c, acct, addresses["probe"])

    (OUT / "deployment.json").write_text(json.dumps({
        "network": NETWORK, "chain_id": 61997, "rpc": RPC,
        "runner": RUNNER_V03, "genvm": "v0.3.0-rc7", "consensus": "v0.6",
        "sdk": "genlayer-py 0.19.0rc2 (.venv-rc)",
        "addresses": addresses,
        "explorer": {k: f"{EXPLORER}/address/{v}" for k, v in addresses.items()},
        "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2))
    print(f"\nwrote {(OUT / 'deployment.json').relative_to(ROOT)}")
    for k, v in addresses.items():
        print(f"  {k:<9} {EXPLORER}/address/{v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
