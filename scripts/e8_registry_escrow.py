"""E8 -- registry to report to escrow, end to end on a real network.

Verifies the only gating inputs the E6 verdict supports:

  1. a published report exists for the rule, and
  2. the worst counterexample count across every published report is within the
     tolerance the payer fixed when opening the deal.

No Split Score anywhere. Three cases are exercised, and two of them must fail:

  PASS   tested rule, tolerance >= worst K   -> funds lock
  FAIL   tested rule, tolerance <  worst K   -> revert, naming both numbers
  FAIL   untested rule                       -> revert, telling the payer to test first
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import Chain  # noqa: E402
from brightline.panel import execution_failed, extract_return, revert_message  # noqa: E402
from brightline.publish import (  # noqa: E402
    ESCROW_SRC,
    REGISTRY_SRC,
    ensure_contract,
    publish,
    report_to_attestation,
)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "E8_registry_escrow"
UNTESTED_RULE = "0x" + "ee" * 32


def expect_revert(ch: Chain, escrow: str, deal_id: str, needle: str,
                  label: str, log: dict) -> bool:
    """A reverted call still lands as ACCEPTED, so check the leader receipt.

    Also asserts the deal stayed OPEN: the gate has to refuse the state transition,
    not merely emit an error.
    """
    try:
        rec = ch.write(escrow, "lock", [deal_id], value=10**16)
    except Exception as exc:
        log[label] = {"reverted": True, "matched": needle.lower() in str(exc).lower(),
                      "via": "exception", "error": str(exc)[:300]}
        print(f"  {label:30s} raised: {str(exc)[:100]}")
        return log[label]["matched"]

    failed = execution_failed(rec)
    message = revert_message(rec)
    state = json.loads(ch.read(escrow, "get_deal", [deal_id]))["state"]
    matched = failed and needle.lower() in message.lower() and state == "OPEN"
    log[label] = {"reverted": failed, "matched": matched, "message": message[:300],
                  "deal_state_after": state, "tx": str(rec.get("hash", ""))}
    print(f"  {label:30s} reverted={failed} state={state}")
    print(f"  {'':30s} {message[:150]}")
    if not matched:
        print(f"  {'':30s} EXPECTED a revert mentioning {needle!r} with state OPEN")
    return matched


def main(network: str = "studionet") -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: dict = {"network": network,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    ch = Chain(network)
    if ch.meta["faucet"] == "sim" and ch.balance() == 0:
        ch.fund()
        time.sleep(3)

    registry, fresh_r = ensure_contract(ch, REGISTRY_SRC, "registry")
    escrow, fresh_e = ensure_contract(ch, ESCROW_SRC, "escrow", args=[registry])
    log["registry"], log["escrow"] = registry, escrow
    print(f"registry {registry}{' (new)' if fresh_r else ''}")
    print(f"escrow   {escrow}{' (new)' if fresh_e else ''}")
    print(f"escrow's registry pointer: {ch.read(escrow, 'registry_address', [])}")

    # ---- publish every available report so competing reports coexist -------------
    reports = sorted((ROOT / "reports").glob("v*_studionet.json"))
    published = []
    for path in reports:
        report = json.loads(path.read_text())
        att = report_to_attestation(report)
        att["evidence_uri"] = f"reports/{path.name}"
        if json.loads(ch.read(registry, "get_report", [att["report_hash"]]) or "{}"):
            print(f"  already published  {path.name}  K={att['counterexamples']}")
        else:
            out = publish(ch, registry, att)
            print(f"  published          {path.name}  K={att['counterexamples']} "
                  f"tx={out['tx'][:18]}")
        published.append({"file": path.name, "rule_hash": att["rule_hash"],
                          "K": att["counterexamples"], "N": att["probes"],
                          "probe_set_id": att["probe_set_id"]})
    log["published"] = published

    # The v1 rule is the gate subject: 4 of 8 counterexamples.
    subject = next(p for p in published if p["file"].startswith("v1_"))
    rule = subject["rule_hash"]
    worst = int(ch.read(registry, "worst_counterexamples", [rule]))
    summary = json.loads(ch.read(registry, "summary_for_rule", [rule]))
    log["subject"] = {"rule_hash": rule, "worst_counterexamples": worst,
                      "reports": summary["reports"]}
    print(f"\nsubject rule {rule[:18]}  reports={summary['reports']}  worst K={worst}")
    for row in summary["rows"]:
        print(f"    {row['probe_set_id']}  K={row['k']}/{row['n']}  "
              f"adversary={row['adversary_version']}")

    stamp = int(time.time())
    ok = True

    # ---- case 1: tolerance >= worst K -> lock succeeds ---------------------------
    print("\ncase 1  tolerance >= worst K")
    deal_ok = f"deal-ok-{stamp}"
    ch.write(escrow, "open_deal", [deal_ok, ch.address(), rule, worst])
    rec = ch.write(escrow, "lock", [deal_ok], value=10**16)
    payload = extract_return(rec) or {}
    deal = json.loads(ch.read(escrow, "get_deal", [deal_ok]))
    log["case_lock_allowed"] = {"deal": deal, "lock_return": payload,
                                "tx": str(rec.get("hash", ""))}
    print(f"  state={deal['state']} amount={deal['amount']} "
          f"K_at_lock={deal['counterexamples_at_lock']} tolerated={deal['max_counterexamples']}")
    if deal["state"] != "LOCKED":
        ok = False
        print("  EXPECTED LOCKED -- gate rejected a compliant deal")

    # The summary the parties relied on is frozen into the deal.
    frozen = json.loads(deal["summary_at_lock"] or "{}")
    print(f"  frozen summary reports={frozen.get('reports')} (cannot be rewritten later)")

    # ---- case 2: tolerance < worst K -> revert -----------------------------------
    print("\ncase 2  tolerance < worst K")
    deal_tight = f"deal-tight-{stamp}"
    ch.write(escrow, "open_deal", [deal_tight, ch.address(), rule, max(0, worst - 1)])
    ok &= expect_revert(ch, escrow, deal_tight, "counterexamples",
                        "lock_below_tolerance", log)

    # ---- case 3: untested rule -> revert ----------------------------------------
    print("\ncase 3  untested rule")
    deal_untested = f"deal-untested-{stamp}"
    ch.write(escrow, "open_deal", [deal_untested, ch.address(), UNTESTED_RULE, 99])
    ok &= expect_revert(ch, escrow, deal_untested, "no published Brightline report",
                        "lock_untested_rule", log)

    # ---- settlement records the entitled party ----------------------------------
    print("\nsettlement")
    rec = ch.write(escrow, "release", [deal_ok])
    released = json.loads(ch.read(escrow, "get_deal", [deal_ok]))
    log["release"] = {"deal": released, "tx": str(rec.get("hash", ""))}
    print(f"  state={released['state']} entitled_amount={released['amount']}")
    ok &= released["state"] == "RELEASED"

    log["gate_e8_pass"] = bool(ok)
    (OUT / "result.json").write_text(json.dumps(log, indent=2, default=str))
    print(f"\nE8 GATE: {'PASS' if ok else 'FAIL'}")
    print(f"evidence: {OUT / 'result.json'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "studionet"))
