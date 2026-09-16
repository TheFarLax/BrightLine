"""The GenVM 0.3 adapter, tested against the real contracts.

The Studio Next deployment is generated from `contracts/*.py` by
`brightline.genvm03.to_genvm03`, so what this module guarantees is what the 61997
contracts are. The properties that matter are not "the string got replaced" but:

  * the runner is swapped, and only the runner;
  * every GenVM 0.2 name the contracts actually use is ported, with none left behind;
  * the transform touches nothing else -- no decision logic, no error messages, no
    tolerance arithmetic, no `worst_counterexamples` behaviour;
  * it is idempotent, so a double application cannot corrupt a deployment.

The compile-level proof lives on the network -- `gen_getContractSchemaForCode` against
61997 returns the same method set as 61999 -- and the behavioural proof is
`scripts/verify_studio_next.py`. These are the cheap invariants that run in CI.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from brightline.genvm03 import (
    PREAMBLE,
    RUNNER_V02,
    RUNNER_V03,
    runner_for,
    source_for,
    to_genvm03,
)

ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS = sorted((ROOT / "contracts").glob("*.py"))

# Names GenVM 0.3 removed. None may survive the transform.
GONE_IN_V03 = ["gl.message_raw", "gl.contract_interface", "run_nondet_unsafe"]


@pytest.fixture(params=CONTRACTS, ids=lambda p: p.stem)
def pair(request) -> tuple[str, str]:
    original = request.param.read_text()
    return original, to_genvm03(original)


def test_contracts_are_still_pinned_to_the_v02_runner():
    """If this fails, the repo's own contracts moved and the adapter is stale."""
    for path in CONTRACTS:
        assert RUNNER_V02 in path.read_text(), f"{path.name} no longer pins {RUNNER_V02}"


def test_runner_is_swapped(pair):
    original, ported = pair
    assert RUNNER_V02 not in ported
    assert ported.count(RUNNER_V03) == 1


def test_no_removed_names_survive(pair):
    _, ported = pair
    assert [n for n in GONE_IN_V03 if n in ported] == []


def test_preamble_is_injected_once(pair):
    _, ported = pair
    assert ported.count(PREAMBLE) == 1
    # It has to land after the wildcard import, or the names it defines are shadowed.
    assert ported.index("from genlayer import *") < ported.index(PREAMBLE)


def test_idempotent(pair):
    _, ported = pair
    assert to_genvm03(ported) == ported


def test_only_the_expected_lines_change(pair):
    """Every changed line must be one of the documented compatibility rewrites.

    This is the real guard. A transform that quietly altered a threshold, an error
    string or a comparison would still compile and still deploy; what stops that is
    pinning the diff to a known shape rather than trusting the substitution table.
    """
    original, ported = pair
    # The shapes the transform is allowed to introduce...
    added_ok = re.compile(
        r"Depends|^import genlayer as gl$|^from genlayer\.storage import|"
        r"^from genlayer\.types import|gl\.contract\.Contract|gl\.contract\.interface|"
        r"gl\.vm\.run_nondet\b|str\(gl\.message\.datetime\)")
    # ...and the 0.2 shapes it is allowed to remove. Deliberately a different pattern:
    # matching removals against the post-transform names would pass vacuously.
    removed_ok = re.compile(
        r"Depends|gl\.Contract|gl\.contract_interface|gl\.vm\.run_nondet_unsafe|"
        r"gl\.message_raw\[")
    before, after = original.splitlines(), ported.splitlines()
    unexpected = [ln for ln in after if ln not in before and not added_ok.search(ln)]
    assert unexpected == [], f"transform added unrelated lines: {unexpected}"
    dropped = [ln for ln in before if ln not in after and not removed_ok.search(ln)]
    assert dropped == [], f"transform removed unrelated lines: {dropped}"


def test_consensus_critical_text_is_untouched(pair):
    """The gate's refusal messages and the decision vocabulary are byte-identical.

    These strings are the product: the escrow's refusal names both numbers, and the
    four-value vocabulary is what the validator compares on. A port that reworded either
    would change what the contract promises without changing what it computes.
    """
    original, ported = pair
    for needle in ("[EXPECTED]", "counterexamples, deal tolerates",
                   "no published Brightline report", "ACCEPT", "REJECT", "PARTIAL",
                   "INSUFFICIENT", "worst_counterexamples"):
        assert original.count(needle) == ported.count(needle), needle


def test_refuses_source_with_an_unknown_runner():
    with pytest.raises(ValueError, match="refusing to guess"):
        to_genvm03('# { "Depends": "py-genlayer:deadbeef" }\nfrom genlayer import *\n')


def test_refuses_source_with_no_wildcard_anchor():
    with pytest.raises(ValueError, match="0.3 preamble"):
        to_genvm03(f'# {{ "Depends": "{RUNNER_V02}" }}\nimport genlayer\n')


def test_source_for_leaves_other_networks_alone():
    path = CONTRACTS[0]
    assert source_for("studionet", path) == path.read_text()
    assert source_for("studio-next", path) == to_genvm03(path.read_text())
    assert runner_for("studionet") == RUNNER_V02
    assert runner_for("studio-next") == RUNNER_V03
