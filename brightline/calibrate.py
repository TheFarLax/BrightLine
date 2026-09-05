"""E6 calibration study.

Runs the corpus in `brightline/corpus.py` against the pre-registered criteria in
`experiments/PREREGISTRATION.md`. Nothing here reads those thresholds from anywhere
mutable -- they are duplicated as constants below so a diff shows if they ever move.

Scope note, stated plainly: with two probes per clause, arms A3 (six models on an
identical probe) and A4 (six models over distinct probes) are not separable in this
run. Per-probe divergence is A3; the clause mean over its two probes is A4. Criterion
5's attribution therefore compares cross-model divergence against the A0 floor and
against the A1/A2 subset run separately, and that limitation is recorded in the
output rather than papered over.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from brightline.chain import Chain
from brightline.corpus import DOMAIN_PROBES, clauses
from brightline.panel import PANEL_MODELS, run_panel
from brightline.run import ensure_deployed, runner_hash
from brightline.spec import AgreementSpec, Probe, ProbeSet, canonical, sha

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "E6_calibration"

# Pre-registered thresholds. Do not adjust after seeing results.
TAU = 0.20
C1_CONTROL_MARGIN = 0.05
C2_PATHO_MIN = 0.30
C3_PAIRS_MIN_DIRECTIONAL = 5
C3_ALPHA = 0.05
C4_AUC_MIN = 0.75


def domain_probes(domain: str) -> list[Probe]:
    return [Probe(index=i, family=fam, scenario=sc)
            for i, (fam, sc) in enumerate(DOMAIN_PROBES[domain])]


def wilcoxon_signed_rank_exact(deltas: list[float]) -> tuple[float, float]:
    """Exact two-sided Wilcoxon signed-rank p for small n. No scipy dependency.

    Zeros are dropped (standard Wilcoxon handling), which also shrinks n and is
    reported alongside the statistic.
    """
    nz = [d for d in deltas if d != 0]
    n = len(nz)
    if n == 0:
        return 0.0, 1.0
    ranks = {v: i + 1 for i, v in enumerate(sorted(nz, key=abs))}
    w_plus = sum(ranks[v] for v in nz if v > 0)
    # Enumerate every sign assignment; n is at most a handful here.
    from itertools import product
    absranks = [ranks[v] for v in nz]
    dist = [sum(r for r, s in zip(absranks, signs) if s)
            for signs in product((0, 1), repeat=n)]
    total = len(dist)
    lo = sum(1 for d in dist if d <= min(w_plus, sum(absranks) - w_plus))
    p = min(1.0, 2.0 * lo / total)
    return float(w_plus), p


def roc_auc(pos: list[float], neg: list[float]) -> float | None:
    """Mann-Whitney U / (n_pos * n_neg), ties counted as half."""
    if not pos or not neg:
        return None
    wins = sum((1.0 if p > n else 0.5 if p == n else 0.0) for p in pos for n in neg)
    return round(wins / (len(pos) * len(neg)), 4)


def bootstrap_auc_ci(pos: list[float], neg: list[float], iters: int = 2000,
                     seed: int = 7) -> tuple[float, float] | None:
    import random
    if not pos or not neg:
        return None
    rng = random.Random(seed)
    vals = []
    for _ in range(iters):
        p = [rng.choice(pos) for _ in pos]
        n = [rng.choice(neg) for _ in neg]
        a = roc_auc(p, n)
        if a is not None:
            vals.append(a)
    vals.sort()
    if not vals:
        return None
    return round(vals[int(0.025 * len(vals))], 4), round(vals[int(0.975 * len(vals)) - 1], 4)


def evaluate(records: list[dict], floor: float | None) -> dict:
    """Score the six pre-registered criteria."""
    by_stratum: dict[str, list[float]] = {}
    for r in records:
        if r["clause_divergence"] is not None:
            by_stratum.setdefault(r["stratum"], []).append(r["clause_divergence"])

    ctrl = by_stratum.get("control", [])
    patho = [r for r in records if r["stratum"] == "pathological"]
    loose = {r["pair"]: r for r in records if r["stratum"] == "pair_loose"}
    tight = {r["pair"]: r for r in records if r["stratum"] == "pair_tight"}

    floor_val = floor if floor is not None else 0.0

    # C1 -- controls at the floor
    c1_mean = round(statistics.fmean(ctrl), 4) if ctrl else None
    c1 = (c1_mean is not None and c1_mean <= floor_val + C1_CONTROL_MARGIN)

    # C2 -- pathological detected: high divergence OR unanimous INSUFFICIENT
    patho_detail = []
    for r in patho:
        div = r["clause_divergence"]
        insuf = r["unanimous_insufficient_probes"]
        detected = bool((div is not None and div >= C2_PATHO_MIN)
                        or insuf >= max(1, r["n_measurable_probes"] / 2))
        patho_detail.append({"id": r["id"], "divergence": div,
                             "unanimous_insufficient": insuf, "detected": detected})
    c2 = bool(patho_detail) and all(p["detected"] for p in patho_detail)

    # C3 -- matched pairs separate
    deltas, pair_rows = [], []
    for key in sorted(set(loose) & set(tight)):
        lv, tv = loose[key]["clause_divergence"], tight[key]["clause_divergence"]
        if lv is None or tv is None:
            pair_rows.append({"pair": key, "loose": lv, "tight": tv, "delta": None})
            continue
        d = round(lv - tv, 4)
        deltas.append(d)
        pair_rows.append({"pair": key, "loose": lv, "tight": tv, "delta": d})
    directional = sum(1 for d in deltas if d > 0)
    w, p = wilcoxon_signed_rank_exact(deltas) if deltas else (0.0, 1.0)
    c3 = directional >= C3_PAIRS_MIN_DIRECTIONAL and p < C3_ALPHA

    # C4 -- discriminability
    pos = [v for s in ("pair_loose", "pathological") for v in by_stratum.get(s, [])]
    neg = [v for s in ("pair_tight", "control") for v in by_stratum.get(s, [])]
    auc = roc_auc(pos, neg)
    ci = bootstrap_auc_ci(pos, neg)
    c4 = bool(auc is not None and auc >= C4_AUC_MIN and ci is not None and ci[0] > 0.5)

    strata_summary = {
        s: {"n": len(v), "mean": round(statistics.fmean(v), 4),
            "max": round(max(v), 4), "min": round(min(v), 4)}
        for s, v in sorted(by_stratum.items()) if v
    }
    inconc = {}
    for r in records:
        d = inconc.setdefault(r["stratum"], [0, 0])
        d[0] += r["n_inconclusive"]
        d[1] += r["n_observations"]
    inconclusive_by_stratum = {s: round(a / b, 4) if b else None
                               for s, (a, b) in sorted(inconc.items())}

    return {
        "noise_floor_A0": floor,
        "strata": strata_summary,
        "inconclusive_by_stratum": inconclusive_by_stratum,
        "criteria": {
            "C1_controls_at_floor": {"pass": c1, "control_mean": c1_mean,
                                     "budget": round(floor_val + C1_CONTROL_MARGIN, 4)},
            "C2_pathological_detected": {"pass": c2, "detail": patho_detail},
            "C3_pairs_separate": {"pass": c3, "directional": directional,
                                  "n_pairs": len(deltas), "wilcoxon_w": w,
                                  "p_two_sided": round(p, 4), "rows": pair_rows},
            "C4_discriminability": {"pass": c4, "auc": auc, "bootstrap_ci95": ci,
                                    "n_pos": len(pos), "n_neg": len(neg)},
            "C5_attribution": {"pass": None,
                               "note": "A1/A2 subset not run in this pass; A3 and A4 "
                                       "are not separable with two probes per clause. "
                                       "Cross-model divergence vs the A0 floor is "
                                       "reported instead."},
            "C6_transfer_A5": {"pass": None,
                               "note": "Bradbury arm not included in this pass."},
        },
        "verdict": _verdict(c1, c2, c3, c4),
    }


def _verdict(c1: bool, c2: bool, c3: bool, c4: bool) -> str:
    if not c1:
        return ("HALT -- criterion 1 failed: objective controls did not sit at the "
                "noise floor, so the instrument is broken and no number from it is "
                "interpretable.")
    if not c4:
        return ("DROP THE SCORE -- criterion 4 failed: divergence does not separate "
                "underspecified rules from specified ones well enough to report. Ship "
                "the counterexample generator alone, per the pre-registered branch.")
    if not c3:
        return ("DIRECTIONAL BUT UNDERPOWERED -- criterion 3 failed while 1 and 4 held. "
                "Per the pre-registered branch this indicts the corpus, not the "
                "instrument; one disclosed corpus revision is permitted.")
    if not c2:
        return ("INVESTIGATE -- criterion 2 failed: pathological rules were not "
                "detected. Check whether INSUFFICIENT is absorbing the signal before "
                "touching anything else.")
    return ("PASS on criteria 1-4: controls at the floor, pathological rules detected, "
            "matched pairs separate, and clause-level divergence discriminates. C5 and "
            "C6 remain unrun and the score stays labelled experimental.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="brightline.calibrate")
    ap.add_argument("--network", default="studionet")
    ap.add_argument("--strata", default=",".join(("control", "pathological",
                                                 "pair_loose", "pair_tight")))
    ap.add_argument("--limit", type=int, default=0, help="cap clauses, for smoke runs")
    args = ap.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    wanted = set(args.strata.split(","))
    todo = [c for c in clauses() if c["stratum"] in wanted]
    if args.limit:
        todo = todo[:args.limit]

    ch = Chain(args.network)
    if ch.meta["faucet"] == "sim" and ch.balance() == 0:
        ch.fund()
        time.sleep(3)
    addr, fresh = ensure_deployed(ch)
    print(f"contract   {addr}{' (new)' if fresh else ''}")
    print(f"clauses    {len(todo)}  panel {len(PANEL_MODELS)} models")
    print(f"est. runs  {sum(len(DOMAIN_PROBES[c['domain']]) for c in todo) * len(PANEL_MODELS)}")

    # Register every probe once, then every rule. Idempotent on-chain.
    registered: set[str] = set()
    for domain in sorted({c["domain"] for c in todo}):
        for probe in domain_probes(domain):
            if probe.probe_id in registered:
                continue
            if not ch.read(addr, "get_probe", [probe.probe_id]):
                ch.write(addr, "register_probe", [probe.probe_id, probe.canonical_scenario])
                print(f"  probe registered {domain}/{probe.index} {probe.probe_id[:12]}")
            registered.add(probe.probe_id)

    specs: dict[str, AgreementSpec] = {}
    for c in todo:
        spec = AgreementSpec(rule_text=c["rule_text"], label=c["id"], domain=c["domain"])
        specs[c["id"]] = spec
        if not ch.read(addr, "get_rule", [spec.rule_hash]):
            ch.write(addr, "register_rule", [spec.rule_hash, spec.normalized])
            print(f"  rule registered  {c['id']:28s} {spec.rule_hash[:12]}")

    raw_dir = OUT / "raw"
    records: list[dict] = []
    all_self_flags: list[bool] = []
    t0 = time.time()

    for n, c in enumerate(todo, 1):
        spec = specs[c["id"]]
        print(f"\n[{n}/{len(todo)}] {c['stratum']:14s} {c['id']}")
        per_probe, insuf, n_obs, n_inc = [], 0, 0, 0
        for probe in domain_probes(c["domain"]):
            res = run_panel(ch, addr, spec.rule_hash, probe.probe_id, PANEL_MODELS,
                            raw_dir=raw_dir)
            d = res.to_dict()
            n_obs += len(d["observations"])
            n_inc += d["n_inconclusive"]
            all_self_flags += [o["self_consistent"] for o in d["observations"]
                               if o["self_consistent"] is not None]
            if d["divergence"] is not None:
                per_probe.append(d["divergence"])
                if list(d["distribution"]) == ["INSUFFICIENT"]:
                    insuf += 1
            print(f"    probe {probe.index} [{probe.family}] div={d['divergence']} "
                  f"dist={d['distribution']} inconc={d['n_inconclusive']}")
            records.append({"clause_id": c["id"], "probe_id": probe.probe_id,
                            "probe_index": probe.index, "family": probe.family,
                            "detail": d})
        clause_div = round(statistics.fmean(per_probe), 4) if per_probe else None
        records[-1] = records[-1]  # keep list shape explicit
        print(f"    -> clause divergence {clause_div}")
        # Attach clause-level summary as its own record kind.
        records.append({"kind": "clause", "id": c["id"], "stratum": c["stratum"],
                        "domain": c["domain"], "pair": c["pair"],
                        "rule_hash": spec.rule_hash,
                        "clause_divergence": clause_div,
                        "n_measurable_probes": len(per_probe),
                        "unanimous_insufficient_probes": insuf,
                        "n_observations": n_obs, "n_inconclusive": n_inc})

    clause_records = [r for r in records if r.get("kind") == "clause"]
    floor = (round(sum(1 for f in all_self_flags if f is False) / len(all_self_flags), 4)
             if all_self_flags else None)
    scored = evaluate(clause_records, floor)
    out = {
        "schema": "brightline.calibration/1",
        "preregistration": "experiments/PREREGISTRATION.md",
        "provenance": {
            "network": args.network, "contract_address": addr,
            "runner_depends": runner_hash(),
            "panel_models": [p.model for p in PANEL_MODELS],
            "tau": TAU, "n_clauses": len(todo),
            "self_consistency_observations": len(all_self_flags),
            "wall_seconds": round(time.time() - t0, 1),
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        "results": scored,
        "clauses": clause_records,
        "probes": [r for r in records if r.get("kind") != "clause"],
    }
    (OUT / "result.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print("\n" + "=" * 72)
    print(json.dumps(scored["criteria"], indent=2)[:1800])
    print(f"\nnoise floor (A0): {floor}")
    print(f"strata: {json.dumps(scored['strata'])}")
    print(f"\nVERDICT: {scored['verdict']}")
    print(f"wrote {OUT / 'result.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
