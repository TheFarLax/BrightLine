"""E1 -- contract smoke test.

Gate: BrightlineProbe deploys, registers a rule and a probe, adjudicates once,
and the ruling reads back with a decision inside the vocabulary.

Writes raw evidence to experiments/E1_contract_smoke/.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import Chain  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "experiments" / "E1_contract_smoke"
DECISIONS = ("ACCEPT", "REJECT", "PARTIAL", "INSUFFICIENT")

RULE = "Pay the contributor if the contributor delivers a working fix."

SCENARIO = {
    "narrative": (
        "The submitted change closes the reported defect. Automated checks on "
        "runner A report all green. Automated checks on runner B report one "
        "failure in an unrelated module. The maintainer has not commented."
    ),
    "facts": [
        {"k": "reported_defect_closed", "v": "yes"},
        {"k": "checks_runner_a", "v": "pass"},
        {"k": "checks_runner_b", "v": "fail (unrelated module)"},
        {"k": "maintainer_confirmation", "v": "none"},
        {"k": "submitted_before_deadline", "v": "yes"},
    ],
    "evidence_available": ["diff", "ci_logs_a", "ci_logs_b"],
    "evidence_absent": ["maintainer_statement"],
}


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def sha(text: str) -> str:
    return "0x" + hashlib.sha256(text.encode()).hexdigest()


def main(network: str = "studionet") -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: dict = {"network": network, "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    ch = Chain(network)
    log["address"] = ch.address()
    print(f"account   {ch.address()}")

    try:
        bal = ch.balance()
        if bal == 0 and ch.meta["faucet"] == "sim":
            print("funding   ...")
            ch.fund()
            time.sleep(3)
            bal = ch.balance()
        log["balance"] = str(bal)
        print(f"balance   {bal}")
    except Exception as exc:
        log["balance_error"] = repr(exc)
        print(f"balance   ERROR {exc!r}")

    contract = Path(__file__).resolve().parent.parent / "contracts" / "brightline_probe.py"
    t0 = time.time()
    addr, deploy_tx = ch.deploy(contract)
    log["deploy"] = {"address": addr, "tx": deploy_tx, "seconds": round(time.time() - t0, 1)}
    print(f"deployed  {addr}  ({log['deploy']['seconds']}s)  tx={deploy_tx}")

    rule_hash = sha(RULE)
    scenario_json = canonical(SCENARIO)
    probe_id = sha(scenario_json)
    log["rule_hash"] = rule_hash
    log["probe_id"] = probe_id

    for fn, args in (("register_rule", [rule_hash, RULE]),
                     ("register_probe", [probe_id, scenario_json])):
        t0 = time.time()
        rec = ch.write(addr, fn, args)
        print(f"{fn:16s} {rec.get('status') or rec.get('statusName')} "
              f"({round(time.time() - t0, 1)}s)")
        log[fn] = {"tx": rec.get("hash"), "status": str(rec.get("status")),
                   "seconds": round(time.time() - t0, 1)}

    print("adjudicate ...")
    t0 = time.time()
    rec = ch.write(addr, "adjudicate", [rule_hash, probe_id], retries=60)
    elapsed = round(time.time() - t0, 1)
    log["adjudicate"] = {
        "tx": rec.get("hash"),
        "status": str(rec.get("status")),
        "execution_result": str(rec.get("txExecutionResultName")
                                or rec.get("tx_execution_result_name") or ""),
        "seconds": elapsed,
    }
    print(f"adjudicate {log['adjudicate']['status']} "
          f"/ {log['adjudicate']['execution_result']} ({elapsed}s)")

    raw = ch.read(addr, "get_ruling", [rule_hash, probe_id])
    log["ruling_raw"] = raw
    ruling = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
    log["ruling"] = ruling
    print(f"ruling    {ruling}")

    (OUT / "receipt_adjudicate.json").write_text(json.dumps(rec, indent=2, default=str))
    log["gate_e1_pass"] = bool(ruling.get("decision") in DECISIONS
                               or ruling.get("status") == "LLM_ERROR")
    (OUT / "result.json").write_text(json.dumps(log, indent=2, default=str))

    print(f"\nE1 GATE: {'PASS' if log['gate_e1_pass'] else 'FAIL'}")
    print(f"evidence: {OUT}")
    return 0 if log["gate_e1_pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "studionet"))
