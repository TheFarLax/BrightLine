"""Report artifacts: metrics, provenance, and the counterexample view.

Design commitments, all of them defensive:

* The headline is a **count of counterexamples**, not a decimal. "3 of 8 probes
  split the panel" is checkable; a score with three decimal places implies a
  precision this instrument does not have.
* Every report carries the full provenance tuple. A Split Score is a property of
  (rule, probe set, adversary version, model panel, network, contract, runner),
  not of a sentence, so two reports are only comparable when those match.
* `INCONCLUSIVE` observations are reported and excluded from both the numerator and
  the denominator. Infrastructure failure is not interpretive divergence.
* The measured noise floor (single-model self-consistency) is printed next to the
  divergence it is supposed to qualify, so nobody has to take the separation on
  trust.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from brightline.spec import AgreementSpec, ProbeSet, canonical

SCHEMA = "brightline.report/1"

DISCLAIMER = (
    "Split Score is an experimental measurement of panel divergence over a fixed "
    "probe set. It is not a probability that a dispute will occur, not a prediction "
    "of how a human court would rule, and not a judgment about whether the "
    "agreement is fair. Decidability is not fairness: a rule can be trivially easy "
    "to adjudicate and still be one-sided."
)


def build_report(spec: AgreementSpec, probe_set: ProbeSet,
                 probe_results: list[dict], network: str,
                 contract_address: str, runner: str, tau: float,
                 models: list[str], seconds: float) -> dict:
    valid = [r for r in probe_results if r.get("divergence") is not None]
    split = [r for r in valid if (r["divergence"] or 0) >= tau]
    floors = [r["self_split_rate"] for r in probe_results
              if r.get("self_split_rate") is not None]
    divs = [r["divergence"] for r in valid]

    unanimous_insufficient = [
        r for r in valid
        if list(r["distribution"]) == ["INSUFFICIENT"]
    ]

    n_obs = sum(len(r.get("observations", [])) for r in probe_results)
    n_inconc = sum(r.get("n_inconclusive", 0) for r in probe_results)

    metrics = {
        "K": len(split),
        "N": len(probe_results),
        "N_measurable": len(valid),
        "tau": tau,
        "split_mean": round(sum(divs) / len(divs), 4) if divs else None,
        "split_max": round(max(divs), 4) if divs else None,
        "noise_floor": round(sum(floors) / len(floors), 4) if floors else None,
        "net_mean": (
            round(sum(divs) / len(divs) - sum(floors) / len(floors), 4)
            if divs and floors else None
        ),
        "unanimous_insufficient": len(unanimous_insufficient),
        "inconclusive_rate": round(n_inconc / n_obs, 4) if n_obs else None,
    }

    provenance = {
        "network": network,
        "contract_address": contract_address,
        "runner_depends": runner,
        "rule_hash": spec.rule_hash,
        "rule_label": spec.label,
        "probe_set_id": probe_set.probe_set_id,
        "adversary_version": probe_set.generated_from.get("adversary_version"),
        "adversary_prompt_hash": probe_set.generated_from.get("adversary_prompt_hash"),
        "probe_generator": probe_set.generated_from.get("generator"),
        "panel_models": models,
        "panel_size": len(models),
        "channel": "PANEL",
        "wall_seconds": seconds,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "rule": spec.to_dict(),
        "provenance": provenance,
        "metrics": metrics,
        "findings": [_finding(r, probe_set, tau) for r in
                     sorted(valid, key=lambda r: -(r["divergence"] or 0))
                     if (r["divergence"] or 0) >= tau],
        "probes": probe_results,
        "disclaimer": DISCLAIMER,
    }
    report["report_hash"] = "0x" + hashlib.sha256(
        canonical({k: v for k, v in report.items() if k != "report_hash"}).encode()
    ).hexdigest()
    return report


def _finding(result: dict, probe_set: ProbeSet, tau: float) -> dict:
    probe = next((p for p in probe_set.probes if p.probe_id == result["probe_id"]), None)
    camps: dict[str, list[dict]] = {}
    for obs in result.get("observations", []):
        if obs.get("kind") == "INCONCLUSIVE" or not obs.get("decision"):
            continue
        camps.setdefault(obs["decision"], []).append(
            {"model": obs["model"], "confidence": obs["confidence"],
             "reason": obs["reason"], "tx": obs["tx"]}
        )
    return {
        "probe_id": result["probe_id"],
        "index": result.get("index"),
        "family": result.get("family"),
        "divergence": result["divergence"],
        "self_split_rate": result.get("self_split_rate"),
        "distribution": result["distribution"],
        "scenario": probe.scenario if probe else None,
        "camps": camps,
        "missing_specification": _missing_spec(result.get("family", "")),
    }


# What each family is evidence *of*. Advisory, derived off-chain from the family
# taxonomy -- not a consensus output, and labelled as such in the rendered report.
_MISSING = {
    "regression_after_fix": [
        "whether collateral breakage counts against performance",
        "the scope boundary of the obligation",
    ],
    "conflicting_evidence": [
        "which source of truth is authoritative",
        "the tie-break when two authorities disagree",
    ],
    "late_evidence": [
        "whether the deadline binds the act or the confirmation of the act",
        "the effect of delay caused by neither party",
    ],
    "partial_completion": [
        "what fraction of performance earns what fraction of payment",
        "whether partial performance is a distinct outcome or a failure",
    ],
    "missing_confirmation": [
        "the fallback when no authority speaks",
        "a time limit after which silence has an effect",
    ],
    "criteria_gap": [
        "a measurable acceptance threshold for the operative term",
    ],
}


def _missing_spec(family: str) -> list[str]:
    return _MISSING.get(family, [])


def render_markdown(report: dict) -> str:
    m, p = report["metrics"], report["provenance"]
    rule = report["rule"]
    lines: list[str] = []
    a = lines.append

    a(f"# Brightline report — {rule['title'] or rule['label']}")
    a("")
    a(f"**{m['K']} of {m['N']} probes split the panel** "
      f"(threshold τ = {m['tau']}, panel of {p['panel_size']} models)")
    a("")
    a(f"    rule            {rule['label']}  {rule['rule_hash'][:18]}")
    a(f"    \"{rule['normalized']}\"")
    a("")
    a("| metric | value | what it means |")
    a("|---|---|---|")
    a(f"| counterexamples | **{m['K']} / {m['N']}** | probes where the panel did not converge |")
    a(f"| mean divergence | {m['split_mean']} | 1 − modal share, averaged over measurable probes |")
    a(f"| max divergence | {m['split_max']} | worst single probe |")
    a(f"| noise floor | {m['noise_floor']} | same-model self-disagreement, measured on every run |")
    a(f"| net | {m['net_mean']} | divergence above the noise floor |")
    a(f"| unanimous INSUFFICIENT | {m['unanimous_insufficient']} | rule decidably silent, panel agreed on that |")
    a(f"| inconclusive | {m['inconclusive_rate']} | infrastructure failures, excluded from both sides |")
    a("")

    if report["findings"]:
        a("## Counterexamples")
        for f in report["findings"]:
            a("")
            a(f"### probe #{f['index']} · {f['family']} · divergence {f['divergence']}")
            a("")
            a(f"> {f['scenario']['narrative'] if f.get('scenario') else ''}")
            a("")
            for decision, members in sorted(f["camps"].items()):
                who = ", ".join(f"{c['model'].split('/')[-1]} ({c['confidence']})"
                                for c in members)
                a(f"- **{decision}** — {who}")
            if f["camps"]:
                first = sorted(f["camps"].items())[0][1][0]
                a("")
                a(f"  _{first['reason']}_")
            if f["missing_specification"]:
                a("")
                a("  Missing specification (advisory, derived off-chain):")
                for item in f["missing_specification"]:
                    a(f"  - {item}")
    else:
        a("## No counterexamples found")
        a("")
        a("Every measurable probe converged at or above the threshold. That is a "
          "statement about this probe set and this panel, not a guarantee.")

    a("")
    a("## Provenance")
    a("")
    a("```")
    for k in ("network", "contract_address", "runner_depends", "rule_hash",
              "probe_set_id", "adversary_version", "adversary_prompt_hash",
              "probe_generator", "channel", "panel_size", "wall_seconds",
              "generated_at"):
        a(f"{k:24s} {p.get(k)}")
    a(f"{'report_hash':24s} {report['report_hash']}")
    a("```")
    a("")
    a(f"_{report['disclaimer']}_")
    return "\n".join(lines)
