"""Unit tests for the parts that must be deterministic: identity, metrics, decoding."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from brightline.adversary import generate, prompt_hash  # noqa: E402
from brightline.panel import (  # noqa: E402
    AGREE,
    DISAGREE,
    INCONCLUSIVE,
    Observation,
    ProbeResult,
    extract_return,
)
from brightline.spec import (  # noqa: E402
    AgreementSpec,
    Probe,
    ProbeSet,
    canonical,
    normalize_rule,
    sha,
)


# ------------------------------------------------------------------------ identity
def test_normalize_collapses_cosmetic_differences():
    a = "Pay the  contributor if the contributor delivers a working fix."
    b = "Pay the contributor if the contributor delivers a working fix.  "
    assert normalize_rule(a) == normalize_rule(b)
    assert sha(normalize_rule(a)) == sha(normalize_rule(b))


def test_normalize_preserves_substantive_differences():
    a = AgreementSpec(rule_text="Pay if the fix works.")
    b = AgreementSpec(rule_text="Pay if the fix works and checks pass.")
    assert a.rule_hash != b.rule_hash


def test_probe_id_is_content_addressed():
    sc = {"narrative": "x", "facts": [{"k": "a", "v": "1"}]}
    assert Probe(0, "criteria_gap", sc).probe_id == Probe(7, "late_evidence", sc).probe_id


def test_canonical_json_is_key_order_stable():
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})


def test_probe_set_id_depends_only_on_membership():
    s1 = {"narrative": "one", "facts": []}
    s2 = {"narrative": "two", "facts": []}
    a = ProbeSet(probes=[Probe(0, "criteria_gap", s1), Probe(1, "late_evidence", s2)])
    b = ProbeSet(probes=[Probe(0, "late_evidence", s2), Probe(1, "criteria_gap", s1)])
    assert a.probe_set_id == b.probe_set_id


def test_manifest_roundtrip_and_tamper_detection(tmp_path):
    spec = AgreementSpec(rule_text="Pay if the fix works.")
    ps = generate(spec)
    path = ps.save(tmp_path)
    assert ProbeSet.load(path).probe_set_id == ps.probe_set_id

    edited = path.read_text().replace("reported defect", "REPORTED DEFECT", 1)
    path.write_text(edited)
    with pytest.raises(ValueError):
        ProbeSet.load(path)


def test_authored_probe_set_is_valid_and_hermetic():
    spec = AgreementSpec.from_file(
        Path(__file__).resolve().parents[2] / "agreements" / "bounty_working_fix_v1.yaml")
    ps = generate(spec)
    assert ps.validate() == []
    assert len(ps.probes) == 8
    assert prompt_hash().startswith("0x")


def test_probe_set_validate_rejects_urls_and_unknown_family():
    bad = ProbeSet(probes=[Probe(0, "not_a_family",
                                 {"narrative": "see https://example.com", "facts": []})])
    problems = " ".join(bad.validate())
    assert "unknown family" in problems
    assert "hermetic" in problems


# ------------------------------------------------------------------------- metrics
def _obs(decision: str, self_ok: bool | None = True) -> Observation:
    return Observation(label=decision, model="m", kind=AGREE, decision=decision,
                       status="OK", self_consistent=self_ok)


def test_divergence_is_one_minus_modal_share():
    r = ProbeResult("p", "r", "PANEL", [_obs("ACCEPT"), _obs("ACCEPT"), _obs("REJECT")])
    assert r.divergence() == pytest.approx(1 / 3, abs=1e-4)


def test_unanimous_panel_has_zero_divergence():
    r = ProbeResult("p", "r", "PANEL", [_obs("ACCEPT")] * 4)
    assert r.divergence() == 0.0


def test_inconclusive_is_excluded_from_both_sides():
    r = ProbeResult("p", "r", "PANEL", [
        _obs("ACCEPT"), _obs("ACCEPT"),
        Observation(label="x", model="m", kind=INCONCLUSIVE, note="backend cancelled"),
    ])
    assert r.divergence() == 0.0          # not 1/3
    assert len(r.valid) == 2
    assert len(r.inconclusive) == 1


def test_no_valid_observations_reports_none_not_agreement():
    r = ProbeResult("p", "r", "PANEL",
                    [Observation(label="x", model="m", kind=INCONCLUSIVE)])
    assert r.divergence() is None
    assert r.to_dict()["net_divergence"] is None


def test_self_split_rate_is_the_noise_floor():
    r = ProbeResult("p", "r", "PANEL", [
        _obs("ACCEPT", True), _obs("ACCEPT", True),
        _obs("REJECT", False), _obs("REJECT", None),
    ])
    assert r.self_split_rate() == pytest.approx(1 / 3, abs=1e-4)


def test_vote_divergence_counts_only_votes():
    r = ProbeResult("p", "r", "CONSENSUS", [
        Observation(label="l", model="m", kind=AGREE),
        Observation(label="v1", model="m", kind=DISAGREE),
        Observation(label="v2", model="m", kind=DISAGREE),
        Observation(label="v3", model="m", kind=INCONCLUSIVE),
    ])
    assert r.vote_divergence() == pytest.approx(2 / 3, abs=1e-4)


# ------------------------------------------------------------------------ receipts
def test_extract_return_unwraps_nested_json_quoting():
    receipt = {"consensus_data": {"leader_receipt": [{"result": {"payload": {
        "readable": '"{\\"decision\\": \\"REJECT\\", \\"status\\": \\"OK\\"}"'}}}]}}
    assert extract_return(receipt) == {"decision": "REJECT", "status": "OK"}


def test_extract_return_none_when_no_payload():
    assert extract_return({"consensus_data": {"leader_receipt": []}}) is None


def test_validator_votes_decode_inference_shape():
    """The E4 inference, exercised against the documented example blob."""
    decoded = base64.b64decode("AAAAAAA=")
    assert len(decoded) == 5                       # one byte per validator
    assert all(b == 0 for b in decoded)            # 0 == NotVoted
