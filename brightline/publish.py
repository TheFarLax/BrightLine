"""Publish a Brightline report to BrightlineRegistry, on-chain.

What gets attested is deliberately narrow: the rule tested, the probe set and
adversary version used, how many counterexamples were found out of how many probes,
the measured noise floor, and the transaction hashes that prove it. Anyone can
recompute the finding from those hashes.

What does **not** get attested is a Split Score. The E6 calibration study failed its
matched-pair criterion (`docs/RESULTS.md`), so the score is not validated for ranking
two drafts of the same clause and is scoped to a studionet lab instrument. Putting it
on-chain where another contract could gate on it would be exactly the unsupported
claim the pre-registration told us not to make.

Registration is permissionless: a counterparty who re-runs the probes with their own
adversary can publish a competing report about the same rule, and
`worst_counterexamples` takes the maximum across all of them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from brightline.chain import Chain
from brightline.state import latest, save_deployment
from brightline.spec import sha

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_SRC = ROOT / "contracts" / "brightline_registry.py"
ESCROW_SRC = ROOT / "contracts" / "gated_escrow.py"

# The registry stores the floor as an integer per-mille so an exact 0.0 stays exact.
FLOOR_SCALE = 1000


def ensure_contract(ch: Chain, source: Path, name: str,
                    args: list[Any] | None = None) -> tuple[str, bool]:
    code_hash = sha(source.read_text())
    existing = latest(ch.network, code_hash, name=name)
    if existing:
        return existing["address"], False
    tx = ch.client.deploy_contract(code=source.read_text(), account=ch.account,
                                   args=args or [])
    tx_hash = tx.hex() if isinstance(tx, (bytes, bytearray)) else str(tx)
    from genlayer_py.types.transactions import TransactionStatus
    receipt = ch.client.wait_for_transaction_receipt(
        transaction_hash=tx_hash, status=TransactionStatus.ACCEPTED,
        interval=3000, retries=40)
    addr = str(receipt.get("recipient") or receipt.get("contract_address") or "")
    runner = source.read_text().splitlines()[0]
    save_deployment(ch.network, addr, tx_hash, code_hash,
                    runner=runner[runner.find("py-genlayer:"):].strip(' "}'),
                    name=name, extra={"ctor_args": [str(a) for a in (args or [])]})
    return addr, True


def report_to_attestation(report: dict) -> dict:
    """Extract exactly the fields the registry accepts, and nothing else."""
    m, p = report["metrics"], report["provenance"]
    tx_hashes = sorted({o["tx"] for probe in report.get("probes", [])
                        for o in probe.get("observations", []) if o.get("tx")})
    floor = m.get("noise_floor")
    return {
        "report_hash": report["report_hash"],
        "rule_hash": report["rule"]["rule_hash"],
        "probe_set_id": p["probe_set_id"],
        "adversary_version": p["adversary_version"] or "unknown",
        "network": p["network"],
        "counterexamples": int(m["K"]),
        "probes": int(m["N"]),
        "measurable": int(m["N_measurable"]),
        "noise_floor_milli": int(round((floor or 0.0) * FLOOR_SCALE)),
        "evidence_uri": "",          # filled by the caller
        "tx_hashes_json": json.dumps(tx_hashes),
        "_tx_count": len(tx_hashes),
    }


def publish(ch: Chain, registry: str, attestation: dict) -> dict:
    args = [attestation["report_hash"], attestation["rule_hash"],
            attestation["probe_set_id"], attestation["adversary_version"],
            attestation["network"], attestation["counterexamples"],
            attestation["probes"], attestation["measurable"],
            attestation["noise_floor_milli"], attestation["evidence_uri"],
            attestation["tx_hashes_json"]]
    rec = ch.write(registry, "publish", args)
    return {"tx": str(rec.get("hash", "")), "status": str(rec.get("status_name")
                                                          or rec.get("status", ""))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="brightline.publish")
    ap.add_argument("report", help="reports/*.json produced by brightline.run")
    ap.add_argument("--network", default=None,
                    help="defaults to the network recorded in the report")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    path = Path(args.report)
    report = json.loads(path.read_text())
    att = report_to_attestation(report)
    att["evidence_uri"] = f"reports/{path.name}"
    network = args.network or report["provenance"]["network"]

    print(f"report      {path.name}")
    print(f"rule        {att['rule_hash'][:18]}  ({report['rule']['label']})")
    print(f"probe set   {att['probe_set_id']}  adversary {att['adversary_version']}")
    print(f"finding     {att['counterexamples']} / {att['probes']} counterexamples "
          f"({att['measurable']} measurable)")
    print(f"noise floor {att['noise_floor_milli']} / 1000")
    print(f"evidence    {att['_tx_count']} adjudication transactions")
    print(f"report hash {att['report_hash'][:18]}")
    if args.dry_run:
        print("\ndry run; nothing published")
        return 0

    ch = Chain(network)
    if ch.meta["faucet"] == "sim" and ch.balance() == 0:
        ch.fund()
    registry, fresh = ensure_contract(ch, REGISTRY_SRC, "registry")
    print(f"registry    {registry}{' (new)' if fresh else ''}")

    if json.loads(ch.read(registry, "get_report", [att["report_hash"]]) or "{}"):
        print("already published; nothing to do")
    else:
        out = publish(ch, registry, att)
        print(f"published   tx={out['tx']} status={out['status']}")

    stored = json.loads(ch.read(registry, "get_report", [att["report_hash"]]))
    worst = int(ch.read(registry, "worst_counterexamples", [att["rule_hash"]]))
    tested = ch.read(registry, "is_tested", [att["rule_hash"]])
    print(f"\nread back   K={stored.get('counterexamples')} N={stored.get('probes')} "
          f"floor={stored.get('noise_floor_milli')}/1000 publisher={stored.get('publisher')}")
    print(f"rule state  tested={tested}  worst_counterexamples={worst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
