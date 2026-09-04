"""Direct-mode contract tests -- in-process, mocked LLM, no network.

These exercise the parts of BrightlineProbe that must hold regardless of which
model answers: registration idempotency, input caps, the decision vocabulary, the
LLM_ERROR path, and the validator comparison rule.

The validator path is what makes or breaks the measurement, so it is tested
explicitly: same decision must agree, different decision must disagree, and both
sides failing to parse must agree (so the run records as INCONCLUSIVE rather than
masquerading as an interpretive split).
"""

from __future__ import annotations

import json

CONTRACT = "contracts/brightline_probe.py"

RULE_HASH = "0x" + "aa" * 32
PROBE_ID = "0x" + "bb" * 32
RULE = "Pay the contributor if the contributor delivers a working fix."
SCENARIO = json.dumps({"narrative": "The change closes the defect.", "facts": []},
                      sort_keys=True, separators=(",", ":"))


def _deployed(direct_deploy):
    c = direct_deploy(CONTRACT)
    c.register_rule(RULE_HASH, RULE)
    c.register_probe(PROBE_ID, SCENARIO)
    return c


# --------------------------------------------------------------------- registration
def test_registration_stores_canonical_text(direct_deploy):
    c = _deployed(direct_deploy)
    assert c.get_rule(RULE_HASH) == RULE
    assert c.get_probe(PROBE_ID) == SCENARIO


def test_registering_identical_text_is_idempotent(direct_deploy):
    c = _deployed(direct_deploy)
    c.register_rule(RULE_HASH, RULE)          # must not raise
    c.register_probe(PROBE_ID, SCENARIO)
    assert c.get_rule(RULE_HASH) == RULE


def test_rebinding_a_hash_to_different_text_reverts(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    with direct_vm.expect_revert("already bound"):
        c.register_rule(RULE_HASH, RULE + " And pay promptly.")


def test_empty_and_oversized_inputs_revert(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("out of range"):
        c.register_rule(RULE_HASH, "")
    with direct_vm.expect_revert("out of range"):
        c.register_probe(PROBE_ID, "x" * 6001)


def test_adjudicating_unknown_ids_reverts(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("unknown rule_hash"):
        c.adjudicate(RULE_HASH, PROBE_ID)


# ---------------------------------------------------------------------- adjudication
def test_adjudicate_stores_and_returns_full_result(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", json.dumps(
        {"decision": "REJECT", "confidence": 91, "reason": "no evidence of a fix"}))
    out = json.loads(c.adjudicate(RULE_HASH, PROBE_ID))
    assert out["decision"] == "REJECT"
    assert out["status"] == "OK"
    assert out["confidence"] == 91
    stored = json.loads(c.get_ruling(RULE_HASH, PROBE_ID))
    assert stored["decision"] == "REJECT"
    assert c.has_ruling(RULE_HASH, PROBE_ID) is True
    assert int(c.ruling_count()) == 1


def test_insufficient_is_a_first_class_verdict(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", json.dumps(
        {"decision": "INSUFFICIENT", "confidence": 80, "reason": "rule is silent"}))
    assert json.loads(c.adjudicate(RULE_HASH, PROBE_ID))["decision"] == "INSUFFICIENT"


def test_decision_outside_vocabulary_becomes_llm_error(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", json.dumps({"decision": "MAYBE", "confidence": 50}))
    out = json.loads(c.adjudicate(RULE_HASH, PROBE_ID))
    assert out["status"] == "LLM_ERROR"
    assert out["decision"] == ""


def test_unparseable_response_becomes_llm_error_not_a_crash(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", "I'm afraid I can't help with that.")
    assert json.loads(c.adjudicate(RULE_HASH, PROBE_ID))["status"] == "LLM_ERROR"


def test_alternate_key_names_and_sloppy_confidence_are_coerced(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", json.dumps(
        {"verdict": " accept ", "confidence": "88.4", "reason": "ok"}))
    out = json.loads(c.adjudicate(RULE_HASH, PROBE_ID))
    assert out["decision"] == "ACCEPT"
    assert out["confidence"] == 88


def test_confidence_is_clamped(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", json.dumps(
        {"decision": "ACCEPT", "confidence": 1000, "reason": "x"}))
    assert json.loads(c.adjudicate(RULE_HASH, PROBE_ID))["confidence"] == 100


# ------------------------------------------------------------------ validator rules
def test_validator_agrees_when_decision_matches(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", json.dumps(
        {"decision": "ACCEPT", "confidence": 90, "reason": "leader wording"}))
    c.adjudicate(RULE_HASH, PROBE_ID)
    direct_vm.clear_mocks()
    # Same decision, different reasoning and confidence: reasoning is deliberately
    # not compared, so this must still agree.
    direct_vm.mock_llm(r".*", json.dumps(
        {"decision": "ACCEPT", "confidence": 61, "reason": "entirely different words"}))
    assert direct_vm.run_validator() is True


def test_validator_disagrees_when_decision_differs(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", json.dumps({"decision": "ACCEPT", "confidence": 90}))
    c.adjudicate(RULE_HASH, PROBE_ID)
    direct_vm.clear_mocks()
    direct_vm.mock_llm(r".*", json.dumps({"decision": "REJECT", "confidence": 90}))
    assert direct_vm.run_validator() is False


def test_both_sides_unparseable_agree_so_the_run_records_inconclusive(
        direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", "garbage")
    c.adjudicate(RULE_HASH, PROBE_ID)
    direct_vm.clear_mocks()
    direct_vm.mock_llm(r".*", "different garbage")
    assert direct_vm.run_validator() is True


def test_status_mismatch_disagrees(direct_vm, direct_deploy):
    c = _deployed(direct_deploy)
    direct_vm.mock_llm(r".*", "garbage")
    c.adjudicate(RULE_HASH, PROBE_ID)
    direct_vm.clear_mocks()
    direct_vm.mock_llm(r".*", json.dumps({"decision": "ACCEPT", "confidence": 90}))
    assert direct_vm.run_validator() is False
