"""E6 finalisation: compute C5 and C6, then apply the pre-registered branches.

No thresholds are recomputed here and none are adjusted. This script only combines
the main run with the A0/A2/A5 arms and reads the branch table in
`experiments/PREREGISTRATION.md` as written.

Two honesty constraints are enforced in code rather than prose:

* C5's pre-registered formula needs A1 (raised temperature). No studionet model is
  both `is_model_available` and exposes a `temperature` config key, so A1 is
  unmeasurable here. The formula is therefore reported twice: as **not evaluable**
  for the pre-registered version, and as a clearly-labelled substituted version with
  A1 replaced by A0.
* The pre-registration allows exactly one disclosed corpus revision. One was already
  spent on the control set before the study ran, so the allowance is treated as
  exhausted and the C3 branch cannot be used to justify a pair rewrite and re-run.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import Chain  # noqa: E402
from brightline.votes import node_vote_summary  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "experiments" / "E6_calibration"
CORPUS_REVISIONS_SPENT = 1
CORPUS_REVISIONS_ALLOWED = 1
C6_RHO_MIN = 0.6


def spearman(xs: list[float], ys: list[float]) -> tuple[float | None, str]:
    if len(xs) != len(ys) or len(xs) < 3:
        return None, "fewer than 3 paired observations"
    if len(set(xs)) < 2:
        return None, "x has zero variance"
    if len(set(ys)) < 2:
        return None, ("y has zero variance -- every live-committee observation is "
                      "identical, so no rank correlation exists to compute")

    def rank(v: list[float]) -> list[float]:
        order = sorted(range(len(v)), key=lambda i: v[i])
        out = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = rank(xs), rank(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = (sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry)) ** 0.5
    return (round(num / den, 4), "ok") if den else (None, "degenerate ranks")


def backfill_a5(arms: dict) -> dict:
    """Re-read any A5 transaction left at a non-terminal status.

    `LeaderTimeout` leaves the appeal window open, so a transaction observed there can
    still finalise -- E3 established that. Treating the first reading as final would
    discard a real observation.
    """
    ch = Chain("testnet-bradbury")
    for entry in arms.get("A5", []):
        if entry.get("vote_divergence") is not None:
            continue
        tx = (entry.get("raw") or {}).get("tx")
        if not tx:
            continue
        ok, st = ch.rpc_supports("gen_getTransactionStatus", [{"txId": tx}])
        status = (st or {}).get("status") if ok else None
        receipt = ch.node_receipt(tx) or {}
        summary = node_vote_summary(receipt)
        entry["backfilled"] = {"status": status,
                               "vote_divergence": summary.get("vote_divergence"),
                               "n_disagree": summary.get("n_disagree"),
                               "decoded_bytes": summary.get("decoded_bytes")}
        if summary.get("vote_divergence") is not None:
            entry["vote_divergence"] = summary["vote_divergence"]
            entry["raw"]["status_name"] = status
        print(f"  backfilled {entry['domain']:10s} status={status} "
              f"vote_div={entry.get('vote_divergence')}")
    return arms


def main() -> int:
    main_run = json.loads((OUT / "result.json").read_text())
    arms = json.loads((OUT / "arms.json").read_text())
    print("backfilling non-terminal A5 transactions ...")
    arms = backfill_a5(arms)
    (OUT / "arms.json").write_text(json.dumps(arms, indent=2, default=str))

    res = main_run["results"]
    crit = res["criteria"]
    clauses = {c["id"]: c for c in main_run["clauses"]}

    # ---- components -------------------------------------------------------------
    a0_main = res["noise_floor_A0"]
    a0_rep = [x["divergence"] for x in arms.get("A0_repeat", [])
              if x["divergence"] is not None]
    a2 = [x["divergence"] for x in arms.get("A2", []) if x["divergence"] is not None]
    a3 = res["strata"]["control"]["mean"]          # 6 models, forced-answer probes
    a4_loose = res["strata"]["pair_loose"]["mean"]
    a4_patho = res["strata"]["pathological"]["mean"]

    components = {
        "A0_self_consistency_main_run": a0_main,
        "A0_repeat_same_model": (round(statistics.fmean(a0_rep), 4) if a0_rep else None),
        "A1_temperature_stress": None,
        "A1_unmeasurable_reason": arms.get("A1_reason"),
        "A2_prompt_paraphrase": (round(statistics.fmean(a2), 4) if a2 else None),
        "A3_cross_model_forced_answer": a3,
        "A4_cross_model_adversarial_loose": a4_loose,
        "A4_cross_model_adversarial_pathological": a4_patho,
    }
    mechanical = [v for v in (components["A0_repeat_same_model"],
                              components["A2_prompt_paraphrase"], a3) if v is not None]
    residual = round(a4_loose - max(mechanical), 4) if mechanical else None

    c5 = {
        "preregistered_evaluable": False,
        "preregistered_note": ("formula is A4 - max(A1, A2, A3); A1 is unmeasurable on "
                               "studionet, so the pre-registered criterion has no value"),
        "substituted": {
            "formula": "A4 - max(A0_repeat, A2, A3), with A1 replaced by A0",
            "residual": residual,
            "components": components,
            "pass": bool(residual is not None and all(residual > m for m in mechanical)),
        },
    }

    # ---- C6 ---------------------------------------------------------------------
    pairs = []
    for entry in arms.get("A5", []):
        clause = clauses.get(f"pair_{entry['domain']}_loose")
        if clause and clause["clause_divergence"] is not None \
                and entry.get("vote_divergence") is not None:
            pairs.append((entry["domain"], clause["clause_divergence"],
                          entry["vote_divergence"]))
    rho, why = spearman([p[1] for p in pairs], [p[2] for p in pairs])
    c6 = {
        "n_paired": len(pairs),
        "rows": [{"domain": d, "A4_panel_divergence": a, "A5_vote_divergence": b}
                 for d, a, b in pairs],
        "spearman_rho": rho,
        "note": why,
        "threshold": C6_RHO_MIN,
        "pass": bool(rho is not None and rho >= C6_RHO_MIN),
        "caveat": ("A4 is a decision distribution over six pinned models; A5 is the "
                   "share of a live committee objecting to one leader. sim_config is "
                   "Studio-only, so these are different quantities and the correlation "
                   "is weak evidence at best."),
    }

    # ---- branches, exactly as written -------------------------------------------
    passes = {"C1": crit["C1_controls_at_floor"]["pass"],
              "C2": crit["C2_pathological_detected"]["pass"],
              "C3": crit["C3_pairs_separate"]["pass"],
              "C4": crit["C4_discriminability"]["pass"],
              "C5_preregistered": None,
              "C5_substituted": c5["substituted"]["pass"],
              "C6": c6["pass"]}

    fired: list[dict] = []
    if not passes["C1"]:
        fired.append({"trigger": "1 fails",
                      "action": "HALT and diagnose before reporting any number"})
    if not passes["C4"]:
        fired.append({"trigger": "4 fails", "action": "DROP Split Score"})
    if not passes["C2"]:
        fired.append({"trigger": "2 fails",
                      "action": "investigate whether INSUFFICIENT absorbs the signal"})
    if not passes["C6"]:
        fired.append({"trigger": "6 fails",
                      "action": "keep the score as a studionet lab instrument only, "
                                "and say so wherever it appears"})
    if not passes["C3"]:
        precondition = (passes["C1"] and passes["C2"] and passes["C4"]
                        and bool(passes["C5_substituted"]))
        allowance_left = CORPUS_REVISIONS_ALLOWED - CORPUS_REVISIONS_SPENT
        fired.append({
            "trigger": "3 fails while 1, 2, 4, 5 pass",
            "precondition_met": precondition,
            "precondition_note": ("met only under the substituted C5; the "
                                  "pre-registered C5 has no value"),
            "action": "one disclosed corpus revision permitted, then a re-run",
            "allowance_remaining": allowance_left,
            "applied": False,
            "why_not_applied": (
                "the pre-registration permits exactly one disclosed corpus revision "
                "and one was already spent on the control set before the study ran "
                "('Corpus revision 1'). The allowance is exhausted, so the pair set "
                "may not be rewritten and re-run under this pre-registration."),
        })

    overall = all(v for k, v in passes.items()
                  if k in ("C1", "C2", "C3", "C4", "C6")) and bool(passes["C5_substituted"])
    out = {
        "schema": "brightline.calibration.final/1",
        "preregistration": "experiments/PREREGISTRATION.md",
        "criteria": passes,
        "C5": c5,
        "C6": c6,
        "branches_fired": fired,
        "study_passes": overall,
        "standing_conclusion": [
            "Split Score is NOT validated for ranking two drafts of the same clause: "
            "C3 failed (3 of 6 pairs directional, p = 0.844) and the corpus-revision "
            "allowance is exhausted, so it cannot be retried under this pre-registration.",
            "Split Score IS supported as a discriminator between forced-answer rules "
            f"and judgment-requiring rules: controls {a3} against loose {a4_loose} and "
            f"pathological {a4_patho}, AUC {crit['C4_discriminability']['auc']} "
            f"CI {crit['C4_discriminability']['bootstrap_ci95']}.",
            "The mechanical floor is empirically zero: within-model repetition and "
            "meaning-preserving paraphrase both produced 0.0 divergence, and no model "
            "in 323 self-consistency observations failed to reproduce its own decision.",
            "Per the C6 branch the score is labelled a studionet lab instrument. The "
            "live Bradbury committee agreed unanimously on every probe measured, so "
            "transfer is unevaluated rather than demonstrated.",
            "The counterexample generator is unaffected by every branch above and "
            "ships regardless.",
        ],
    }
    (OUT / "final.json").write_text(json.dumps(out, indent=2, default=str))
    print("\n" + "=" * 72)
    print(json.dumps({k: v for k, v in out.items() if k != "C6"}, indent=2)[:3000])
    print("\nC6:", json.dumps(c6, indent=2)[:900])
    print(f"\nSTUDY PASSES: {overall}")
    print(f"wrote {OUT / 'final.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
