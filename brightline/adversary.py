"""Adversary -- generates hermetic fact patterns that stress a resolution rule.

The adversary is deliberately *not* consensus-critical. Its output is committed to
the repo as a content-addressed manifest, and the instructions it was given are
published in `prompts/adversary_v1.md`. That is what makes a probe set auditable:
a counterparty can read the prompt, regenerate, and attack the same rule with a
set of their own choosing.

Two generation paths:

* `authored` (default, no credentials) -- the committed v1 corpus. Reproducible by
  construction because it ships with the repo and is hash-verified on load.
* `api` (opt-in) -- calls an OpenAI-compatible endpoint with the published prompt.
  Requires BRIGHTLINE_ADVERSARY_* environment variables to be set deliberately;
  nothing is sent anywhere unless the caller asks for this path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from brightline.spec import (
    DEFAULT_QUOTA,
    AgreementSpec,
    Probe,
    ProbeSet,
    sha,
)

VERSION = "adv-v1.0.0"
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "adversary_v1.md"


def prompt_hash() -> str:
    return sha(PROMPT_PATH.read_text())


# ---------------------------------------------------------------------------------
# Authored corpus for the bounty / "working fix" family of rules.
#
# Each scenario applies exactly one pressure and describes only facts. None of them
# mentions the rule, so the same set can be re-run against a rewritten rule -- the
# regression arm of the re-test loop depends on that.
# ---------------------------------------------------------------------------------
AUTHORED_WORKING_FIX: list[tuple[str, dict]] = [
    ("regression_after_fix", {
        "narrative": (
            "The contributor submitted a change that closes the reported defect. "
            "After the change was merged, a defect that had been closed five weeks "
            "earlier began reproducing again in the same module. No other behaviour "
            "changed."
        ),
        "facts": [
            {"k": "reported_defect_closed", "v": "yes"},
            {"k": "previously_closed_defect_reproducing", "v": "yes"},
            {"k": "same_module", "v": "yes"},
            {"k": "submitted_before_deadline", "v": "yes"},
        ],
        "evidence_available": ["diff", "issue_history", "reproduction_log"],
        "evidence_absent": [],
    }),
    ("conflicting_evidence", {
        "narrative": (
            "The change closes the reported defect. Automated checks on the "
            "project's primary runner report every check passing. Automated checks "
            "on the project's secondary runner report one failure, in a module the "
            "change did not touch. The maintainer has not commented."
        ),
        "facts": [
            {"k": "reported_defect_closed", "v": "yes"},
            {"k": "checks_primary_runner", "v": "pass"},
            {"k": "checks_secondary_runner", "v": "fail (untouched module)"},
            {"k": "maintainer_confirmation", "v": "none"},
            {"k": "submitted_before_deadline", "v": "yes"},
        ],
        "evidence_available": ["diff", "primary_runner_log", "secondary_runner_log"],
        "evidence_absent": ["maintainer_statement"],
    }),
    ("conflicting_evidence", {
        "narrative": (
            "The contributor's change closes the reported defect. One maintainer "
            "wrote that the approach is correct and approved it. A second maintainer "
            "wrote that the approach is wrong and requested changes. Automated checks "
            "all pass. Neither maintainer withdrew their position."
        ),
        "facts": [
            {"k": "reported_defect_closed", "v": "yes"},
            {"k": "maintainer_a_position", "v": "approved"},
            {"k": "maintainer_b_position", "v": "changes requested"},
            {"k": "automated_checks", "v": "pass"},
            {"k": "positions_withdrawn", "v": "no"},
        ],
        "evidence_available": ["diff", "review_comments", "check_logs"],
        "evidence_absent": ["tie_break_decision"],
    }),
    ("late_evidence", {
        "narrative": (
            "The contributor pushed the change eleven hours before the stated cutoff. "
            "The project's automated checks were queued behind unrelated work and "
            "reported all passing three hours after the cutoff. Nothing about the "
            "change was modified after the push."
        ),
        "facts": [
            {"k": "change_pushed_before_cutoff", "v": "yes (11h before)"},
            {"k": "checks_completed", "v": "3h after cutoff"},
            {"k": "checks_result", "v": "pass"},
            {"k": "change_modified_after_push", "v": "no"},
            {"k": "delay_cause", "v": "unrelated queue backlog"},
        ],
        "evidence_available": ["push_timestamp", "check_completion_timestamp", "check_logs"],
        "evidence_absent": [],
    }),
    ("partial_completion", {
        "narrative": (
            "The reported defect had two documented reproduction paths. The "
            "contributor's change eliminates the first path entirely. The second path "
            "still reproduces the defect. The contributor stated they consider the "
            "remaining path a separate issue."
        ),
        "facts": [
            {"k": "reproduction_paths_reported", "v": "2"},
            {"k": "paths_fixed", "v": "1"},
            {"k": "paths_still_reproducing", "v": "1"},
            {"k": "contributor_position", "v": "remaining path is a separate issue"},
            {"k": "automated_checks", "v": "pass"},
        ],
        "evidence_available": ["diff", "reproduction_logs_both_paths"],
        "evidence_absent": ["maintainer_ruling_on_scope"],
    }),
    ("partial_completion", {
        "narrative": (
            "The contributor's change makes the defect stop reproducing, but does so "
            "by disabling the feature in which the defect occurred. The feature was "
            "in use by other parts of the project. No replacement was provided."
        ),
        "facts": [
            {"k": "defect_reproduces", "v": "no"},
            {"k": "method", "v": "feature disabled"},
            {"k": "feature_in_use_elsewhere", "v": "yes"},
            {"k": "replacement_provided", "v": "no"},
            {"k": "automated_checks", "v": "pass"},
        ],
        "evidence_available": ["diff", "usage_search_results", "check_logs"],
        "evidence_absent": ["maintainer_statement"],
    }),
    ("missing_confirmation", {
        "narrative": (
            "The contributor submitted a change that appears to close the reported "
            "defect. The project has no automated checks. Nobody has reviewed or "
            "commented on the change in nineteen days. The contributor has asked "
            "twice for a review."
        ),
        "facts": [
            {"k": "change_submitted", "v": "yes"},
            {"k": "automated_checks_exist", "v": "no"},
            {"k": "days_without_review", "v": "19"},
            {"k": "review_requested_by_contributor", "v": "twice"},
            {"k": "defect_reproduces_locally", "v": "no"},
        ],
        "evidence_available": ["diff", "contributor_local_test_output"],
        "evidence_absent": ["any_maintainer_response", "automated_check_logs"],
    }),
    ("criteria_gap", {
        "narrative": (
            "The reported defect is that an operation is unacceptably slow. The "
            "contributor's change reduces the operation's runtime from 40 seconds to "
            "9 seconds. The original report did not state a target runtime. The "
            "operation still takes longer than comparable operations in the project."
        ),
        "facts": [
            {"k": "defect_type", "v": "performance"},
            {"k": "runtime_before", "v": "40s"},
            {"k": "runtime_after", "v": "9s"},
            {"k": "target_runtime_stated", "v": "no"},
            {"k": "slower_than_comparable_operations", "v": "yes"},
        ],
        "evidence_available": ["diff", "benchmark_before", "benchmark_after"],
        "evidence_absent": ["acceptance_threshold"],
    }),
]

CORPORA: dict[str, list[tuple[str, dict]]] = {
    "working_fix": AUTHORED_WORKING_FIX,
}


def generate(spec: AgreementSpec, corpus: str = "working_fix", n: int | None = None,
             salt: str = "0x01", quota: dict[str, int] | None = None) -> ProbeSet:
    """Build a probe set from the authored corpus.

    `generated_from` records everything needed to audit the set: which rule it was
    written against, which adversary version and prompt, and which model authored
    it. The set is then an independent object -- a later rule version is tested
    against these same probe ids.
    """
    if corpus not in CORPORA:
        raise SystemExit(f"unknown corpus {corpus!r}; have {list(CORPORA)}")
    items = CORPORA[corpus]
    if n is not None:
        items = items[:n]
    probes = [Probe(index=i, family=fam, scenario=sc)
              for i, (fam, sc) in enumerate(items)]
    ps = ProbeSet(
        probes=probes,
        quota=dict(quota or DEFAULT_QUOTA),
        generated_from={
            "rule_hash": spec.rule_hash,
            "rule_label": spec.label,
            "adversary_version": VERSION,
            "adversary_prompt_hash": prompt_hash(),
            "generator": "authored",
            "generator_model": "claude-opus-5",
            "corpus": corpus,
            "salt": salt,
            "seed": sha(spec.rule_hash + VERSION + prompt_hash() + salt),
        },
    )
    return ps


def api_available() -> bool:
    return bool(os.environ.get("BRIGHTLINE_ADVERSARY_API_KEY")
                and os.environ.get("BRIGHTLINE_ADVERSARY_BASE_URL"))


def generate_via_api(spec: AgreementSpec, n: int = 8) -> ProbeSet:
    """Opt-in generation against an OpenAI-compatible endpoint.

    Deliberately requires its own environment variables rather than reusing any
    credentials that happen to be present, so no request leaves the machine unless
    the operator configured this path on purpose.
    """
    if not api_available():
        raise SystemExit(
            "set BRIGHTLINE_ADVERSARY_API_KEY and BRIGHTLINE_ADVERSARY_BASE_URL "
            "to use the API adversary; the authored corpus needs no credentials"
        )
    import requests

    base = os.environ["BRIGHTLINE_ADVERSARY_BASE_URL"].rstrip("/")
    model = os.environ.get("BRIGHTLINE_ADVERSARY_MODEL", "gpt-4.1")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": PROMPT_PATH.read_text()},
            {"role": "user", "content": json.dumps(
                {"rule_text": spec.normalized, "n": n,
                 "families": list(DEFAULT_QUOTA)}, indent=2)},
        ],
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        f"{base}/chat/completions", json=body, timeout=180,
        headers={"Authorization": f"Bearer {os.environ['BRIGHTLINE_ADVERSARY_API_KEY']}",
                 "Content-Type": "application/json",
                 "User-Agent": "brightline/0.1"},
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    items = json.loads(content).get("probes", [])
    probes = [Probe(index=i, family=str(it["family"]), scenario=it["scenario"])
              for i, it in enumerate(items)]
    return ProbeSet(probes=probes, generated_from={
        "rule_hash": spec.rule_hash,
        "rule_label": spec.label,
        "adversary_version": VERSION,
        "adversary_prompt_hash": prompt_hash(),
        "generator": "api",
        "generator_model": model,
    })


# ---------------------------------------------------------------------------------
# Fresh corpus -- the generalization arm.
#
# Written against v2's *new* surface rather than v1's. If a rewritten rule only
# passes the frozen set it was written against, the score has been farmed; the only
# way to catch that is to attack the new rule with probes it has never seen. These
# deliberately aim at the seams a designated-authority clause creates: what if the
# authority is unavailable, self-contradictory, or was changed mid-flight.
# ---------------------------------------------------------------------------------
AUTHORED_WORKING_FIX_FRESH: list[tuple[str, dict]] = [
    ("conflicting_evidence", {
        "narrative": (
            "The designated check suite reported every check passing on the "
            "contributor's final commit. Four hours later the same suite was re-run "
            "on the identical commit by a maintainer and reported two checks failing. "
            "Nothing in the repository changed between the two runs."
        ),
        "facts": [
            {"k": "designated_suite_run_1", "v": "all pass"},
            {"k": "designated_suite_run_2_same_commit", "v": "2 failing"},
            {"k": "repository_changed_between_runs", "v": "no"},
            {"k": "which_run_is_authoritative_stated", "v": "no"},
        ],
        "evidence_available": ["suite_log_run_1", "suite_log_run_2", "commit_sha"],
        "evidence_absent": ["rule_on_repeated_runs"],
    }),
    ("missing_confirmation", {
        "narrative": (
            "The contributor pushed before the cutoff. The designated check suite was "
            "removed from the project six days later and replaced by a differently "
            "named suite. The new suite reports all checks passing. Eleven days have "
            "passed since the push and no maintainer has stated a position."
        ),
        "facts": [
            {"k": "pushed_before_cutoff", "v": "yes"},
            {"k": "designated_suite_still_exists", "v": "no"},
            {"k": "replacement_suite_result", "v": "all pass"},
            {"k": "days_since_push", "v": "11"},
            {"k": "maintainer_position", "v": "none"},
        ],
        "evidence_available": ["push_timestamp", "replacement_suite_log", "suite_removal_commit"],
        "evidence_absent": ["designated_suite_result", "maintainer_statement"],
    }),
    ("partial_completion", {
        "narrative": (
            "Three reproduction paths were recorded on the issue when the bounty was "
            "posted. The contributor resolved two of them. A fourth reproduction path "
            "was added to the issue by a third party after the bounty was posted, and "
            "it still reproduces."
        ),
        "facts": [
            {"k": "paths_recorded_at_posting", "v": "3"},
            {"k": "paths_resolved", "v": "2"},
            {"k": "path_added_after_posting", "v": "1, still reproducing"},
            {"k": "designated_suite", "v": "all pass"},
        ],
        "evidence_available": ["issue_history_with_timestamps", "suite_log"],
        "evidence_absent": [],
    }),
    ("regression_after_fix", {
        "narrative": (
            "On the parent commit the designated suite had one check already failing "
            "for unrelated reasons. On the contributor's final commit that check still "
            "fails and every other check passes. The reported defect is closed."
        ),
        "facts": [
            {"k": "parent_commit_failing_checks", "v": "1 (unrelated)"},
            {"k": "final_commit_failing_checks", "v": "same 1"},
            {"k": "newly_failing_checks", "v": "0"},
            {"k": "reported_defect_closed", "v": "yes"},
        ],
        "evidence_available": ["suite_log_parent", "suite_log_final"],
        "evidence_absent": [],
    }),
    ("late_evidence", {
        "narrative": (
            "The contributor pushed a commit before the cutoff, then pushed a second "
            "commit ninety minutes after the cutoff that only reformatted whitespace. "
            "The designated suite passed on the second commit and was never run on the "
            "first."
        ),
        "facts": [
            {"k": "first_push", "v": "before cutoff"},
            {"k": "second_push", "v": "90 min after cutoff"},
            {"k": "second_push_content", "v": "whitespace only"},
            {"k": "suite_ran_on", "v": "second commit only"},
            {"k": "suite_result", "v": "all pass"},
        ],
        "evidence_available": ["both_push_timestamps", "diff_between_commits", "suite_log"],
        "evidence_absent": ["suite_result_for_first_commit"],
    }),
    ("criteria_gap", {
        "narrative": (
            "The listing stated that the operation must complete in under ten seconds. "
            "The contributor's change brings it to 9.4 seconds on the project's "
            "reference machine and 12.1 seconds on the machine the reporter used. The "
            "listing did not say which machine the threshold applies to."
        ),
        "facts": [
            {"k": "stated_threshold", "v": "10s"},
            {"k": "runtime_reference_machine", "v": "9.4s"},
            {"k": "runtime_reporter_machine", "v": "12.1s"},
            {"k": "machine_specified_in_listing", "v": "no"},
        ],
        "evidence_available": ["listing_text", "benchmark_both_machines"],
        "evidence_absent": ["designated_measurement_environment"],
    }),
    ("conflicting_evidence", {
        "narrative": (
            "The designated check suite reports all checks passing. A maintainer wrote "
            "that the change is wrong, will be reverted, and should not be paid. The "
            "change has not been reverted. The reported defect no longer reproduces."
        ),
        "facts": [
            {"k": "designated_suite", "v": "all pass"},
            {"k": "maintainer_statement", "v": "wrong, will revert, do not pay"},
            {"k": "actually_reverted", "v": "no"},
            {"k": "defect_reproduces", "v": "no"},
        ],
        "evidence_available": ["suite_log", "maintainer_comment", "branch_history"],
        "evidence_absent": [],
    }),
    ("partial_completion", {
        "narrative": (
            "Two reproduction paths were recorded when the bounty was posted. The "
            "contributor's change resolves one path and makes the second path harder "
            "to trigger but still reachable under load. The designated suite passes."
        ),
        "facts": [
            {"k": "paths_recorded", "v": "2"},
            {"k": "paths_fully_resolved", "v": "1"},
            {"k": "second_path_status", "v": "still reachable under load"},
            {"k": "designated_suite", "v": "all pass"},
        ],
        "evidence_available": ["suite_log", "load_test_output"],
        "evidence_absent": ["definition_of_resolved"],
    }),
]

CORPORA["working_fix_fresh"] = AUTHORED_WORKING_FIX_FRESH
