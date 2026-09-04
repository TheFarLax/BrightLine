"""Re-test comparison: did a rewrite actually fix the rule, or just learn the test?

Two arms, and reporting only the first one would be dishonest:

REGRESSION      rule V2 against the *frozen* probe set V1 was measured on. Answers
                "did the specific counterexamples close?"
GENERALIZATION  rule V2 against a *freshly generated* probe set aimed at V2's own
                new surface. Answers "or did we tune the wording to pass a corpus
                we already had?"

A rewrite that closes the frozen set while the fresh set stays high has been
farmed. That is a finding, not a failure, and it prints as one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def _by_probe(report: dict) -> dict[str, dict]:
    return {p["probe_id"]: p for p in report.get("probes", [])}


def compare(before: dict, after_frozen: dict,
            after_fresh: dict | None = None) -> dict:
    tau = before["metrics"]["tau"]
    b, a = _by_probe(before), _by_probe(after_frozen)

    shared = [pid for pid in b if pid in a]
    rows = []
    for pid in sorted(shared, key=lambda p: b[p].get("index", 0)):
        bd, ad = b[pid].get("divergence"), a[pid].get("divergence")
        state = "unmeasurable"
        if bd is not None and ad is not None:
            was, now = bd >= tau, ad >= tau
            state = ("closed" if was and not now else
                     "opened" if now and not was else
                     "still split" if was and now else "clean")
        rows.append({
            "probe_id": pid,
            "index": b[pid].get("index"),
            "family": b[pid].get("family"),
            "before": bd,
            "after": ad,
            "before_dist": b[pid].get("distribution"),
            "after_dist": a[pid].get("distribution"),
            "state": state,
        })

    out: dict = {
        "schema": "brightline.diff/1",
        "probe_set_frozen": before["provenance"]["probe_set_id"],
        "rule_before": {"label": before["rule"]["label"],
                        "hash": before["rule"]["rule_hash"],
                        "K": before["metrics"]["K"], "N": before["metrics"]["N"],
                        "split_mean": before["metrics"]["split_mean"],
                        "inconclusive_rate": before["metrics"]["inconclusive_rate"]},
        "rule_after": {"label": after_frozen["rule"]["label"],
                       "hash": after_frozen["rule"]["rule_hash"],
                       "K": after_frozen["metrics"]["K"],
                       "N": after_frozen["metrics"]["N"],
                       "split_mean": after_frozen["metrics"]["split_mean"],
                       "inconclusive_rate": after_frozen["metrics"]["inconclusive_rate"]},
        "regression": {
            "closed": sum(1 for r in rows if r["state"] == "closed"),
            "opened": sum(1 for r in rows if r["state"] == "opened"),
            "still_split": sum(1 for r in rows if r["state"] == "still split"),
            "rows": rows,
        },
        "comparable": _comparable(before, after_frozen),
    }

    if after_fresh is not None:
        out["generalization"] = {
            "probe_set_fresh": after_fresh["provenance"]["probe_set_id"],
            "K": after_fresh["metrics"]["K"],
            "N": after_fresh["metrics"]["N"],
            "split_mean": after_fresh["metrics"]["split_mean"],
            "noise_floor": after_fresh["metrics"]["noise_floor"],
            "families_still_splitting": sorted({
                p.get("family") for p in after_fresh.get("probes", [])
                if (p.get("divergence") or 0) >= after_fresh["metrics"]["tau"]
            }),
        }
        out["verdict"] = _verdict(out)
    return out


def _comparable(a: dict, b: dict) -> dict:
    """Two reports are only comparable when the provenance tuple matches."""
    keys = ("network", "panel_models", "adversary_version", "runner_depends",
            "channel", "contract_address")
    mismatch = {k: [a["provenance"].get(k), b["provenance"].get(k)]
                for k in keys if a["provenance"].get(k) != b["provenance"].get(k)}
    return {"ok": not mismatch, "mismatched": mismatch}


def _verdict(out: dict) -> str:
    """State what changed on each axis. A verdict that reads only K throws away
    information: a rewrite can leave the number of split probes untouched while
    materially reducing how badly they split, and that is a different finding from
    no change at all."""
    gen = out["generalization"]
    before_k, after_k = out["rule_before"]["K"], out["rule_after"]["K"]
    b_mean, a_mean = out["rule_before"].get("split_mean"), out["rule_after"].get("split_mean")
    reg = out["regression"]

    parts: list[str] = []
    if after_k < before_k:
        parts.append(f"frozen counterexamples fell {before_k}->{after_k}")
    elif after_k > before_k:
        parts.append(f"frozen counterexamples ROSE {before_k}->{after_k}")
    else:
        parts.append(f"frozen counterexamples unchanged at {after_k}")

    if b_mean is not None and a_mean is not None:
        delta = round(a_mean - b_mean, 4)
        if delta < -0.01:
            parts.append(f"mean divergence fell {b_mean}->{a_mean}")
        elif delta > 0.01:
            parts.append(f"mean divergence rose {b_mean}->{a_mean}")
        else:
            parts.append(f"mean divergence flat at {a_mean}")

    if reg["closed"]:
        parts.append(f"{reg['closed']} probe(s) closed")
    if reg["opened"]:
        parts.append(f"{reg['opened']} newly opened")

    gen_txt = (f"the fresh set aimed at the new rule found {gen['K']}/{gen['N']} "
               f"(mean {gen['split_mean']})")
    if gen["K"] > after_k:
        gen_txt += " -- worse than the frozen set, so read the frozen gain as partly farmed"
    elif gen["K"] < after_k:
        gen_txt += " -- better than the frozen set, so the rewrite generalized"
    else:
        gen_txt += " -- the same as the frozen set"

    return "; ".join(parts) + ". " + gen_txt + "."


def render(diff: dict) -> str:
    lines: list[str] = []
    a = lines.append
    rb, ra = diff["rule_before"], diff["rule_after"]
    a("# Brightline re-test")
    a("")
    a(f"frozen probe set `{diff['probe_set_frozen']}`")
    a("")
    a("| arm | rule | probe set | counterexamples | mean divergence |")
    a("|---|---|---|---|---|")
    a(f"| baseline | {rb['label']} | frozen | **{rb['K']} / {rb['N']}** | {rb.get('split_mean')} |")
    a(f"| regression | {ra['label']} | frozen (same ids) | **{ra['K']} / {ra['N']}** | {ra.get('split_mean')} |")
    if "generalization" in diff:
        g = diff["generalization"]
        a(f"| generalization | {ra['label']} | fresh `{g['probe_set_fresh']}` | **{g['K']} / {g['N']}** | {g.get('split_mean')} |")
    a("")
    a(f"closed {diff['regression']['closed']} · "
      f"still split {diff['regression']['still_split']} · "
      f"newly opened {diff['regression']['opened']}")
    a("")
    a("| probe | family | before | after | |")
    a("|---|---|---|---|---|")
    mark = {"closed": "closed", "opened": "OPENED", "still split": "still split",
            "clean": "clean", "unmeasurable": "n/a"}
    for r in diff["regression"]["rows"]:
        a(f"| #{r['index']} | {r['family']} | {r['before']} | {r['after']} | "
          f"{mark[r['state']]} |")
    if "verdict" in diff:
        a("")
        a(f"**Verdict.** {diff['verdict']}")
    if not diff["comparable"]["ok"]:
        a("")
        a("> Reports are not strictly comparable; provenance differs: "
          f"`{diff['comparable']['mismatched']}`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="brightline.diff")
    ap.add_argument("before")
    ap.add_argument("after_frozen")
    ap.add_argument("--fresh", default=None)
    ap.add_argument("--out", default="reports/retest")
    args = ap.parse_args(argv)

    diff = compare(load(args.before), load(args.after_frozen),
                   load(args.fresh) if args.fresh else None)
    Path(f"{args.out}.json").write_text(json.dumps(diff, indent=2))
    text = render(diff)
    Path(f"{args.out}.md").write_text(text)
    print(text)
    print(f"\nwrote {args.out}.json and {args.out}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
