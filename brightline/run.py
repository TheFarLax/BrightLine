"""Run a probe set against a rule on the PANEL channel and write a report artifact.

Usage:
    python -m brightline.run agreements/bounty_working_fix_v1.yaml probes/ps_xxx.json
    python -m brightline.run <spec> <probeset> --network studionet --tau 0.20
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from brightline.chain import Chain
from brightline.panel import PANEL_MODELS, run_panel
from brightline.report import build_report, render_markdown
from brightline.spec import AgreementSpec, ProbeSet, sha
from brightline.state import latest, save_deployment

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "brightline_probe.py"
REPORTS = ROOT / "reports"


def runner_hash() -> str:
    """The pinned GenVM runner from the contract's first-line Depends header."""
    first = CONTRACT.read_text().splitlines()[0]
    start = first.find("py-genlayer:")
    return first[start:].strip(' "}') if start >= 0 else "unknown"


def ensure_deployed(ch: Chain) -> tuple[str, bool]:
    code_hash = sha(CONTRACT.read_text())
    existing = latest(ch.network, code_hash)
    if existing:
        return existing["address"], False
    addr, tx = ch.deploy(CONTRACT)
    save_deployment(ch.network, addr, tx, code_hash, runner_hash())
    return addr, True


def ensure_registered(ch: Chain, addr: str, spec: AgreementSpec,
                      ps: ProbeSet) -> dict:
    """Register rule and probes. Idempotent on-chain, so re-runs are cheap."""
    txs: dict[str, str] = {}
    if not ch.read(addr, "get_rule", [spec.rule_hash]):
        rec = ch.write(addr, "register_rule", [spec.rule_hash, spec.normalized])
        txs["rule"] = str(rec.get("hash", ""))
        print(f"  registered rule   {spec.rule_hash[:14]}")
    else:
        print(f"  rule present      {spec.rule_hash[:14]}")
    for probe in ps.probes:
        if ch.read(addr, "get_probe", [probe.probe_id]):
            continue
        rec = ch.write(addr, "register_probe", [probe.probe_id, probe.canonical_scenario])
        txs[f"probe_{probe.index}"] = str(rec.get("hash", ""))
        print(f"  registered probe  #{probe.index} {probe.probe_id[:14]}")
    return txs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="brightline.run")
    ap.add_argument("spec")
    ap.add_argument("probeset")
    ap.add_argument("--network", default="studionet")
    ap.add_argument("--tau", type=float, default=0.20,
                    help="per-probe divergence at or above which a probe counts as split")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    spec = AgreementSpec.from_file(args.spec)
    ps = ProbeSet.load(args.probeset)
    problems = ps.validate()
    if problems:
        print("probe set is invalid:")
        for p in problems:
            print("  -", p)
        return 2

    print(f"rule       {spec.label}  {spec.rule_hash[:18]}")
    print(f"probe set  {ps.probe_set_id}  n={len(ps.probes)}  {ps.family_counts()}")
    print(f"network    {args.network}")

    ch = Chain(args.network)
    if ch.meta["faucet"] == "sim" and ch.balance() == 0:
        ch.fund()
        time.sleep(3)
    addr, fresh = ensure_deployed(ch)
    print(f"contract   {addr}{' (new)' if fresh else ''}")
    ensure_registered(ch, addr, spec, ps)

    raw_dir = REPORTS / "raw" / f"{spec.label}_{ps.probe_set_id}"
    results = []
    t_start = time.time()
    for probe in ps.probes:
        print(f"\nprobe #{probe.index} [{probe.family}] {probe.probe_id[:14]}")
        res = run_panel(ch, addr, spec.rule_hash, probe.probe_id, PANEL_MODELS,
                        raw_dir=raw_dir)
        d = res.to_dict()
        d.update(index=probe.index, family=probe.family)
        results.append(d)
        print(f"    -> dist={d['distribution']} div={d['divergence']} "
              f"self_split={d['self_split_rate']} inconc={d['n_inconclusive']}")

    report = build_report(spec=spec, probe_set=ps, probe_results=results,
                         network=args.network, contract_address=addr,
                         runner=runner_hash(), tau=args.tau,
                         models=[p.model for p in PANEL_MODELS],
                         seconds=round(time.time() - t_start, 1))

    REPORTS.mkdir(parents=True, exist_ok=True)
    stem = args.out or f"{spec.label}_{ps.probe_set_id}_{args.network}"
    (REPORTS / f"{stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    (REPORTS / f"{stem}.md").write_text(render_markdown(report))
    print(f"\n{'=' * 72}")
    print(render_markdown(report))
    print(f"{'=' * 72}\nwrote reports/{stem}.json and reports/{stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
