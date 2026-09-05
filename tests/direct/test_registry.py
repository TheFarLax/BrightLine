"""Direct-mode tests for BrightlineRegistry.

Deterministic contract, so these need no mocks. The behaviours that matter are the
ones that stop a report from being laundered into a better number: immutable report
hashes, coexisting competing reports, and `worst_counterexamples` taking the maximum
rather than the latest or the best.
"""

from __future__ import annotations

import json

CONTRACT = "contracts/brightline_registry.py"

RULE = "0x" + "aa" * 32
OTHER_RULE = "0x" + "cc" * 32


def _publish(c, report_hash: str, rule_hash: str = RULE, k: int = 4, n: int = 8,
             probe_set: str = "ps_1111", adversary: str = "adv-v1.0.0",
             network: str = "studionet", measurable: int = 8, floor_milli: int = 0):
    c.publish(report_hash, rule_hash, probe_set, adversary, network, k, n,
              measurable, floor_milli, "reports/x.json", json.dumps(["0xdead"]))


def test_publish_then_read_roundtrip(direct_deploy):
    c = direct_deploy(CONTRACT)
    _publish(c, "0x01", k=4, n=8)
    r = json.loads(c.get_report("0x01"))
    assert r["rule_hash"] == RULE
    assert r["counterexamples"] == 4 and r["probes"] == 8
    assert r["adversary_version"] == "adv-v1.0.0"
    assert r["noise_floor_milli"] == 0
    assert c.is_tested(RULE) is True
    assert int(c.report_count_for_rule(RULE)) == 1


def test_untested_rule_reads_empty(direct_deploy):
    c = direct_deploy(CONTRACT)
    assert c.get_report("0xmissing") == "{}"
    assert c.is_tested(RULE) is False
    assert int(c.worst_counterexamples(RULE)) == 0
    assert json.loads(c.summary_for_rule(RULE))["tested"] is False


def test_report_hash_is_immutable(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    _publish(c, "0x01", k=4)
    with direct_vm.expect_revert("already published"):
        _publish(c, "0x01", k=0)


def test_competing_reports_coexist(direct_deploy):
    c = direct_deploy(CONTRACT)
    _publish(c, "0x01", k=2, probe_set="ps_aaaa", adversary="adv-v1.0.0")
    _publish(c, "0x02", k=6, probe_set="ps_bbbb", adversary="adv-counterparty")
    assert int(c.report_count_for_rule(RULE)) == 2
    s = json.loads(c.summary_for_rule(RULE))
    assert s["reports"] == 2
    assert {row["adversary_version"] for row in s["rows"]} == {
        "adv-v1.0.0", "adv-counterparty"}


def test_worst_counterexamples_takes_the_maximum_not_the_latest(direct_deploy):
    c = direct_deploy(CONTRACT)
    _publish(c, "0x01", k=6, probe_set="ps_aaaa")
    _publish(c, "0x02", k=1, probe_set="ps_bbbb")   # a flattering later run
    assert int(c.worst_counterexamples(RULE)) == 6


def test_reports_are_scoped_per_rule(direct_deploy):
    c = direct_deploy(CONTRACT)
    _publish(c, "0x01", rule_hash=RULE, k=5)
    _publish(c, "0x02", rule_hash=OTHER_RULE, k=0)
    assert int(c.worst_counterexamples(RULE)) == 5
    assert int(c.worst_counterexamples(OTHER_RULE)) == 0
    assert c.is_tested(OTHER_RULE) is True


def test_counterexamples_cannot_exceed_probes(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("within 0..probes"):
        _publish(c, "0x01", k=9, n=8)


def test_zero_probes_rejected(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("within 0..probes"):
        _publish(c, "0x01", k=0, n=0)


def test_noise_floor_must_be_a_milli_fraction(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("noise_floor_milli"):
        _publish(c, "0x01", floor_milli=1001)


def test_empty_and_oversized_fields_rejected(direct_vm, direct_deploy):
    c = direct_deploy(CONTRACT)
    with direct_vm.expect_revert("length out of range"):
        _publish(c, "")
    with direct_vm.expect_revert("length out of range"):
        _publish(c, "0x01", probe_set="p" * 129)


def test_a_clean_report_is_still_a_report(direct_deploy):
    """Zero counterexamples must be publishable and must read as tested -- otherwise
    the gate could never open for a good rule."""
    c = direct_deploy(CONTRACT)
    _publish(c, "0x01", k=0, n=8)
    assert c.is_tested(RULE) is True
    assert int(c.worst_counterexamples(RULE)) == 0
