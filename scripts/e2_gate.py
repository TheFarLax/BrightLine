"""E2 gate -- can we observe per-model decisions, and does gen_call replay work?

Two independent questions, both about whether Brightline can see *what* each
model decided rather than only that somebody objected:

E2a  PANEL channel: leader_only + one pinned validator model per run. If this
     works we get the real decision distribution across models.
E2b  gen_call with `leader_results` (documented validator-mode replay) plus
     `nondetDisagreementCallNo`. Cheaper and unbounded in panel size, but only
     tells us agree/disagree, not the validator's own answer.

Neither is assumed. Both are probed and the outcome is recorded either way.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import Chain  # noqa: E402
from brightline.panel import PANEL_MODELS, run_panel  # noqa: E402
from brightline.state import latest, save_deployment  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments" / "E2_panel_and_replay"
CONTRACT = ROOT / "contracts" / "brightline_probe.py"

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


def ensure_deployed(ch: Chain, code_hash: str) -> tuple[str, bool]:
    existing = latest(ch.network, code_hash)
    if existing:
        print(f"reusing   {existing['address']}")
        return existing["address"], False
    print("deploying ...")
    addr, tx = ch.deploy(CONTRACT)
    save_deployment(ch.network, addr, tx, code_hash)
    print(f"deployed  {addr}  tx={tx}")
    return addr, True


def probe_gen_call(ch: Chain, addr: str, rule_hash: str, probe_id: str) -> dict:
    """E2b. Encode calldata, run leader mode, then replay in validator mode."""
    out: dict = {"network": ch.network}
    try:
        from genlayer_py.abi.calldata import encode as calldata_encode
    except Exception as exc:
        out["calldata_encoder"] = f"unavailable: {exc!r}"
        return out

    try:
        payload = calldata_encode(
            {"method": "adjudicate", "args": [rule_hash, probe_id]}
        )
        data = "0x" + bytes(payload).hex()
        out["calldata_bytes"] = len(payload)
    except Exception as exc:
        out["calldata_encoder"] = f"encode failed: {exc!r}"
        return out

    base = {"from": ch.address(), "to": addr, "data": data, "type": "write"}
    ok, leader = ch.rpc_supports("gen_call", [base])
    out["leader_mode_supported"] = ok
    if not ok:
        out["leader_mode_error"] = leader
        return out
    if isinstance(leader, dict):
        eq = leader.get("eqOutputs") or []
        out["eq_outputs_count"] = len(eq)
        out["leader_status"] = leader.get("status")
        out["nondetDisagreementCallNo_field_present"] = (
            "nondetDisagreementCallNo" in leader
        )
        if eq:
            ok2, val = ch.rpc_supports("gen_call", [{**base, "leader_results": eq}])
            out["validator_mode_supported"] = ok2
            if isinstance(val, dict):
                out["validator_mode_disagreement_call_no"] = val.get(
                    "nondetDisagreementCallNo", "ABSENT"
                )
                out["validator_mode_eq_outputs_count"] = len(val.get("eqOutputs") or [])
                out["validator_mode_status"] = val.get("status")
            else:
                out["validator_mode_payload"] = str(val)[:400]
        else:
            out["note"] = "leader mode returned no eqOutputs; cannot replay"
    return out


def main(network: str = "studionet") -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: dict = {"network": network,
                 "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    ch = Chain(network)
    print(f"account   {ch.address()}")
    if ch.meta["faucet"] == "sim" and ch.balance() == 0:
        ch.fund()
        time.sleep(3)

    code_hash = sha(CONTRACT.read_text())
    log["contract_code_hash"] = code_hash
    addr, fresh = ensure_deployed(ch, code_hash)
    log["contract_address"] = addr

    rule_hash, scenario_json = sha(RULE), canonical(SCENARIO)
    probe_id = sha(scenario_json)
    log.update(rule_hash=rule_hash, probe_id=probe_id)

    if fresh:
        for fn, args in (("register_rule", [rule_hash, RULE]),
                         ("register_probe", [probe_id, scenario_json])):
            ch.write(addr, fn, args)
            print(f"{fn:16s} ok")

    print("\n--- E2a PANEL (leader_only, one pinned model per run) ---")
    panel = run_panel(ch, addr, rule_hash, probe_id, PANEL_MODELS,
                      raw_dir=OUT / "raw")
    log["panel"] = panel.to_dict()
    print(f"\n  distribution    : {panel.distribution()}")
    print(f"  divergence      : {panel.divergence()}")
    print(f"  self-split rate : {panel.self_split_rate()}   <- measured noise floor")
    print(f"  net divergence  : {log['panel']['net_divergence']}")
    print(f"  inconclusive    : {len(panel.inconclusive)}/{len(panel.observations)}")

    print("\n--- E2b gen_call replay ---")
    log["gen_call"] = probe_gen_call(ch, addr, rule_hash, probe_id)
    for k, v in log["gen_call"].items():
        print(f"  {k}: {str(v)[:120]}")

    e2a = len(panel.valid) >= 3
    e2b = bool(log["gen_call"].get("validator_mode_supported"))
    log["gate_e2a_panel_pass"] = e2a
    log["gate_e2b_replay_pass"] = e2b
    log["gate_e2_pass"] = e2a or e2b

    (OUT / f"result_{network}.json").write_text(json.dumps(log, indent=2, default=str))
    print(f"\nE2a PANEL  : {'PASS' if e2a else 'FAIL'}  ({len(panel.valid)} usable observations)")
    print(f"E2b REPLAY : {'PASS' if e2b else 'FAIL'}")
    print(f"E2 GATE    : {'PASS' if log['gate_e2_pass'] else 'FAIL'}")
    print(f"evidence   : {OUT}/result_{network}.json")
    return 0 if log["gate_e2_pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "studionet"))
