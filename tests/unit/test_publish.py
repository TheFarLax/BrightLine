"""Unit tests for the report -> attestation projection and revert detection.

The projection is the boundary where a report becomes something a contract can gate
on, so what it *drops* matters as much as what it keeps: no Split Score, no mean
divergence, no per-model detail.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from brightline.panel import execution_failed, revert_message  # noqa: E402
from brightline.publish import report_to_attestation  # noqa: E402

REPORT = Path(__file__).resolve().parents[2] / "reports" / \
    "v1_ps_6ce467da9d20c1f2_studionet.json"


def _report() -> dict:
    return json.loads(REPORT.read_text())


def test_attestation_carries_the_raw_finding():
    att = report_to_attestation(_report())
    assert att["counterexamples"] == 4
    assert att["probes"] == 8
    assert att["measurable"] == 8
    assert att["adversary_version"] == "adv-v1.0.0"
    assert att["probe_set_id"] == "ps_6ce467da9d20c1f2"
    assert att["rule_hash"].startswith("0x")
    assert att["report_hash"].startswith("0x")


def test_attestation_carries_no_score():
    """E6 scoped Split Score to a studionet lab instrument, so it must not reach a
    surface another contract could gate on."""
    att = report_to_attestation(_report())
    forbidden = ("split", "score", "divergence", "auc", "mean")
    for key in att:
        assert not any(f in key.lower() for f in forbidden), key


def test_noise_floor_is_scaled_to_integer_permille():
    att = report_to_attestation(_report())
    assert att["noise_floor_milli"] == 0        # measured 0.0, must stay exact
    assert isinstance(att["noise_floor_milli"], int)


def test_evidence_is_the_transaction_hashes():
    att = report_to_attestation(_report())
    hashes = json.loads(att["tx_hashes_json"])
    assert len(hashes) == att["_tx_count"] > 0
    assert hashes == sorted(set(hashes))       # deduped and ordered
    assert all(h.startswith("0x") for h in hashes)


def test_counterexamples_never_exceed_probes():
    att = report_to_attestation(_report())
    assert 0 <= att["counterexamples"] <= att["probes"]


# ------------------------------------------------------------- revert detection
def _receipt(status: str, payload: str, exec_result: str = "SUCCESS") -> dict:
    return {"consensus_data": {"leader_receipt": [
        {"execution_result": exec_result,
         "result": {"status": status, "payload": payload}}]}}


def test_rollback_is_detected_even_though_consensus_succeeded():
    rec = _receipt("rollback", "[EXPECTED] rule has 4 counterexamples", "ERROR")
    assert execution_failed(rec) is True
    assert "4 counterexamples" in revert_message(rec)


def test_successful_call_is_not_a_failure():
    rec = _receipt("return", '"{\\"state\\": \\"LOCKED\\"}"')
    assert execution_failed(rec) is False


def test_error_execution_result_alone_is_enough():
    rec = {"consensus_data": {"leader_receipt": [{"execution_result": "ERROR"}]}}
    assert execution_failed(rec) is True


def test_revert_message_falls_back_to_stderr():
    rec = {"consensus_data": {"leader_receipt": [
        {"execution_result": "ERROR", "stderr": "boom"}]}}
    assert revert_message(rec) == "boom"


def test_missing_receipt_shapes_do_not_raise():
    assert execution_failed({}) is False
    assert revert_message({}) == ""
