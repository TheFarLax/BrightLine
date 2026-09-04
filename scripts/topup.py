"""Top up a report: re-run only the observations that came back INCONCLUSIVE.

Studionet occasionally drops a window of requests, and an inconclusive observation
is a hole in coverage rather than a result. Leaving those holes in place makes two
reports incomparable -- one rule looks calmer only because fewer models answered.

This re-runs exactly the failed (probe, model) pairs, replaces those observations,
and rebuilds the report from the merged data. Successful observations are never
re-rolled, so this cannot be used to shop for a better number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import Chain, ValidatorPin  # noqa: E402
from brightline.panel import INCONCLUSIVE, Observation, ProbeResult, run_panel_one  # noqa: E402
from brightline.report import build_report, render_markdown  # noqa: E402
from brightline.spec import AgreementSpec, ProbeSet  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="topup")
    ap.add_argument("report", help="reports/*.json to top up in place")
    ap.add_argument("spec")
    ap.add_argument("probeset")
    ap.add_argument("--max-runs", type=int, default=40)
    args = ap.parse_args(argv)

    path = Path(args.report)
    report = json.loads(path.read_text())
    spec = AgreementSpec.from_file(args.spec)
    ps = ProbeSet.load(args.probeset)
    prov = report["provenance"]

    holes = [(p["index"], i, o) for p in report["probes"]
             for i, o in enumerate(p["observations"]) if o["kind"] == INCONCLUSIVE]
    print(f"report      {path.name}")
    print(f"holes       {len(holes)} inconclusive observations")
    if not holes:
        print("nothing to do")
        return 0
    if len(holes) > args.max_runs:
        print(f"refusing: {len(holes)} > --max-runs {args.max_runs}")
        return 2

    ch = Chain(prov["network"])
    addr = prov["contract_address"]
    raw_dir = ROOT / "reports" / "raw" / f"{spec.label}_{ps.probe_set_id}_topup"
    by_index = {p["index"]: p for p in report["probes"]}
    filled = 0

    for probe_index, obs_index, obs in holes:
        model = obs["model"]
        provider = "openrouter"  # panel models are all reached through this gateway
        probe = next(p for p in ps.probes if p.index == probe_index)
        print(f"  probe #{probe_index} {model:38s} ...", end=" ", flush=True)
        new = run_panel_one(ch, addr, spec.rule_hash, probe.probe_id,
                            ValidatorPin(provider, model), raw_dir=raw_dir)
        if new.kind == INCONCLUSIVE:
            print(f"still inconclusive ({new.note[:50]})")
            continue
        by_index[probe_index]["observations"][obs_index] = vars(new)
        filled += 1
        print(f"{new.decision} (conf {new.confidence})")

    print(f"\nfilled      {filled}/{len(holes)}")

    # Recompute per-probe statistics from the merged observations.
    rebuilt = []
    for p in sorted(report["probes"], key=lambda x: x["index"]):
        obs = [Observation(**o) for o in p["observations"]]
        pr = ProbeResult(probe_id=p["probe_id"], rule_hash=p["rule_hash"],
                         channel=p["channel"], observations=obs, raw=p.get("raw", {}))
        d = pr.to_dict()
        d.update(index=p["index"], family=p["family"])
        rebuilt.append(d)

    fresh = build_report(spec=spec, probe_set=ps, probe_results=rebuilt,
                         network=prov["network"], contract_address=addr,
                         runner=prov["runner_depends"], tau=report["metrics"]["tau"],
                         models=prov["panel_models"], seconds=prov["wall_seconds"])
    fresh["provenance"]["topped_up"] = {"holes": len(holes), "filled": filled}

    path.write_text(json.dumps(fresh, indent=2, ensure_ascii=False))
    path.with_suffix(".md").write_text(render_markdown(fresh))
    m = fresh["metrics"]
    print(f"K/N         {m['K']}/{m['N']}  mean={m['split_mean']}  "
          f"floor={m['noise_floor']}  inconclusive={m['inconclusive_rate']}")
    print(f"rewrote     {path} and {path.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
