"""E6 calibration corpus.

Four strata, and one design rule that does the heavy lifting: **both halves of a
matched pair are measured on the same probe ids**. The deal is held constant and only
the resolution procedure changes, so probe difficulty cannot explain a difference
between a pair's halves.

Each domain carries two hermetic probes. Controls and pathological clauses reuse the
probes of the domain they belong to, so divergence is comparable across strata.
"""

from __future__ import annotations

# ------------------------------------------------------------------ probes by domain
# Two per domain: one conflicting-source pressure, one partial/late pressure.
DOMAIN_PROBES: dict[str, list[tuple[str, dict]]] = {
    "bounty": [
        ("conflicting_evidence", {
            "narrative": "The submitted work closes the reported issue. The project's "
                         "first automated runner reports all checks green. A second "
                         "runner reports one failure in an unrelated area. No human "
                         "has commented.",
            "facts": [{"k": "issue_closed", "v": "yes"},
                      {"k": "runner_one", "v": "pass"},
                      {"k": "runner_two", "v": "fail (unrelated)"},
                      {"k": "human_comment", "v": "none"}],
            "evidence_available": ["diff", "runner_one_log", "runner_two_log"],
            "evidence_absent": ["human_statement"]}),
        ("partial_completion", {
            "narrative": "Two reproduction paths were listed on the issue. The work "
                         "resolves the first. The second still reproduces. Automated "
                         "checks pass.",
            "facts": [{"k": "paths_listed", "v": "2"},
                      {"k": "paths_resolved", "v": "1"},
                      {"k": "checks", "v": "pass"}],
            "evidence_available": ["diff", "both_repro_logs"],
            "evidence_absent": ["scope_ruling"]}),
    ],
    "delivery": [
        ("conflicting_evidence", {
            "narrative": "The carrier's tracking page shows the parcel delivered on the "
                         "14th. The recipient states nothing arrived. The carrier's "
                         "photograph shows a doorway that the recipient says is not "
                         "theirs.",
            "facts": [{"k": "tracking_status", "v": "delivered 14th"},
                      {"k": "recipient_statement", "v": "not received"},
                      {"k": "photo_matches_address", "v": "disputed"}],
            "evidence_available": ["tracking_record", "delivery_photo", "recipient_statement"],
            "evidence_absent": ["signature"]}),
        ("late_evidence", {
            "narrative": "The parcel was handed to the carrier two days before the "
                         "promised date. The carrier's own scan records it as arriving "
                         "at the destination facility three days after that date, "
                         "because of a hub closure neither party caused.",
            "facts": [{"k": "handover", "v": "2 days early"},
                      {"k": "arrival_scan", "v": "3 days late"},
                      {"k": "cause", "v": "hub closure"}],
            "evidence_available": ["handover_scan", "arrival_scan", "closure_notice"],
            "evidence_absent": []}),
    ],
    "refund": [
        ("conflicting_evidence", {
            "narrative": "The buyer reports the item does not work. The seller's own "
                         "test of an identical unit works. The buyer's photograph shows "
                         "the item powered on but displaying an error.",
            "facts": [{"k": "buyer_report", "v": "does not work"},
                      {"k": "seller_test_identical_unit", "v": "works"},
                      {"k": "buyer_photo", "v": "powers on, shows error"}],
            "evidence_available": ["buyer_photo", "seller_test_log"],
            "evidence_absent": ["inspection_of_the_actual_unit"]}),
        ("partial_completion", {
            "narrative": "The order contained four items. Three arrived undamaged. The "
                         "fourth arrived with a cracked casing but is functional.",
            "facts": [{"k": "items_ordered", "v": "4"},
                      {"k": "items_undamaged", "v": "3"},
                      {"k": "fourth_item", "v": "cracked casing, functional"}],
            "evidence_available": ["photos_all_items"],
            "evidence_absent": []}),
    ],
    "sla": [
        ("conflicting_evidence", {
            "narrative": "The provider's status page records no outage for the month. "
                         "The customer's own monitoring recorded 41 minutes during "
                         "which requests returned errors. Both sets of records cover "
                         "the same period.",
            "facts": [{"k": "provider_status_page", "v": "no outage"},
                      {"k": "customer_monitoring", "v": "41 min of errors"},
                      {"k": "periods_overlap", "v": "yes"}],
            "evidence_available": ["status_page_history", "customer_monitor_export"],
            "evidence_absent": ["agreed_measurement_source"]}),
        ("partial_completion", {
            "narrative": "During the month the service answered every request, but 8% "
                         "of responses took longer than the response time the customer "
                         "was quoted when signing up.",
            "facts": [{"k": "availability", "v": "100%"},
                      {"k": "responses_over_quoted_latency", "v": "8%"}],
            "evidence_available": ["latency_histogram"],
            "evidence_absent": ["latency_term_in_agreement"]}),
    ],
    "content": [
        ("conflicting_evidence", {
            "narrative": "One reviewer classified the submission as original. A second "
                         "reviewer found a passage of forty words matching an older "
                         "public document. The submitter says the passage is a common "
                         "phrasing of a standard definition.",
            "facts": [{"k": "reviewer_one", "v": "original"},
                      {"k": "reviewer_two", "v": "40-word match found"},
                      {"k": "submitter_position", "v": "standard definition"}],
            "evidence_available": ["submission", "matching_passage", "reviewer_notes"],
            "evidence_absent": ["originality_threshold"]}),
        ("late_evidence", {
            "narrative": "The submission was uploaded eleven minutes before the "
                         "deadline. The platform's processing queue stamped it as "
                         "received nine minutes after the deadline. The file was not "
                         "modified after upload.",
            "facts": [{"k": "upload_time", "v": "11 min before"},
                      {"k": "platform_receipt_stamp", "v": "9 min after"},
                      {"k": "modified_after_upload", "v": "no"}],
            "evidence_available": ["upload_log", "queue_stamp", "file_hash"],
            "evidence_absent": []}),
    ],
    "milestone": [
        ("conflicting_evidence", {
            "narrative": "The contractor states the milestone is complete. The client's "
                         "technical reviewer signed off. The client's finance reviewer "
                         "refused, citing a deliverable not listed in the milestone "
                         "description but discussed in a meeting.",
            "facts": [{"k": "contractor_position", "v": "complete"},
                      {"k": "technical_reviewer", "v": "signed off"},
                      {"k": "finance_reviewer", "v": "refused"},
                      {"k": "disputed_item_in_written_scope", "v": "no"}],
            "evidence_available": ["milestone_description", "both_reviews", "meeting_notes"],
            "evidence_absent": ["tie_break_authority"]}),
        ("missing_confirmation", {
            "narrative": "The contractor delivered every item in the written milestone "
                         "description and requested sign-off. Twenty-three days have "
                         "passed with no response of any kind from the client.",
            "facts": [{"k": "items_delivered", "v": "all listed"},
                      {"k": "signoff_requested", "v": "yes"},
                      {"k": "days_silent", "v": "23"}],
            "evidence_available": ["delivery_record", "request_log"],
            "evidence_absent": ["any_client_response"]}),
    ],
}


# ------------------------------------------------------------------ matched pairs
# Same commercial intent in both halves. The tight half names the authority, the
# tie-break, the deadline effect, and what partial performance earns. Nothing else
# differs -- in particular the tight half is not more generous, only more decidable.
PAIRS: dict[str, tuple[str, str]] = {
    "bounty": (
        "Pay the bounty if the contributor delivers working code.",
        "Pay the bounty if the runner named in the listing reports every check passing "
        "on the contributor's final commit. That runner is the sole authority; no other "
        "runner, local result, or comment overrides it. If the listed reproduction paths "
        "are only partly resolved, pay the same fraction of the bounty, rounded down. "
        "If the named runner has not reported within seven days, pay in full.",
    ),
    "delivery": (
        "Refund the buyer if the parcel was not delivered.",
        "Refund the buyer unless the carrier's tracking record shows a delivery scan at "
        "the address on the order. That record is the sole authority on delivery; "
        "photographs and statements from either party do not override it. A scan at a "
        "different address is not delivery. If no scan of any kind exists, refund.",
    ),
    "refund": (
        "Refund the buyer if the item is defective.",
        "Refund the buyer if the item, as shipped to this buyer, fails the "
        "manufacturer's published power-on self test. That test on the buyer's actual "
        "unit is the sole authority; tests on other units of the same model do not "
        "count. Cosmetic damage that does not cause the test to fail is not a defect "
        "for this purpose and earns no refund.",
    ),
    "sla": (
        "Credit the customer if the service was unavailable for too long in the month.",
        "Credit the customer 10% of the monthly fee for each full 30 minutes in the "
        "month during which the provider's status page records a degraded or failed "
        "state, capped at 100%. The provider's status page is the sole authority; "
        "customer-side monitoring does not count. Response latency is outside this term "
        "and earns no credit.",
    ),
    "content": (
        "Pay the contributor if the submission is original work.",
        "Pay the contributor unless the platform's similarity check, run on the file as "
        "uploaded, reports a contiguous match of 25 words or more against its corpus. "
        "That check is the sole authority. The deadline binds the upload timestamp, not "
        "the platform's processing stamp. A match of fewer than 25 words is not "
        "disqualifying regardless of reviewer opinion.",
    ),
    "milestone": (
        "Release the milestone payment when the milestone is complete.",
        "Release the milestone payment when every item in the written milestone "
        "description has been delivered. The written description is the sole scope; "
        "items discussed elsewhere are outside it. Where reviewers disagree, the "
        "technical reviewer's decision governs. If no reviewer has responded within "
        "fourteen days of a sign-off request, release the payment.",
    ),
}

# --------------------------------------------------------------------- controls
# Objectively decidable: one named source, one numeric threshold, no interpretation
# left over. These must land at the noise floor or the instrument is broken.
CONTROLS: list[tuple[str, str]] = [
    # Revision 1 (disclosed): the first control set named an authority -- "the runner
    # named in the listing" -- that the probes never identify, so it was undecidable
    # against its own probes and split the panel 4-2. Found on a one-clause smoke run
    # before any full-corpus result existed. Controls now key off fact values the
    # probes actually record, state the default when a fact is absent, and declare
    # everything else irrelevant. Each is forced on both probes of its domain.
    ("bounty", "Decide only from the fact recorded as `checks`. If `checks` is recorded "
               "as pass, ACCEPT. If it is recorded as anything else, REJECT. If it is "
               "not recorded at all, REJECT. No other fact, runner, comment, count, or "
               "consideration is an input."),
    ("bounty", "Decide only from the fact recorded as `runner_two`. If `runner_two` is "
               "recorded and its value begins with the word fail, REJECT. In every other "
               "case, including when `runner_two` is not recorded at all, ACCEPT. No "
               "other fact or consideration is an input."),
    ("delivery", "Decide only from the fact recorded as `tracking_status`. If it is "
                 "recorded and contains the word delivered, REJECT the refund. "
                 "Otherwise, including when it is not recorded at all, ACCEPT the "
                 "refund. No photograph, statement, or other fact is an input."),
    ("delivery", "Decide only from the fact recorded as `arrival_scan`. If it is "
                 "recorded and describes arrival after the promised date, ACCEPT. "
                 "Otherwise, including when it is not recorded at all, REJECT. No other "
                 "fact or cause is an input."),
    ("refund", "Decide only from the two facts recorded as `items_ordered` and "
               "`items_undamaged`. If both are recorded and `items_undamaged` is lower "
               "than `items_ordered`, ACCEPT. Otherwise, including when either is not "
               "recorded at all, REJECT. No other fact is an input."),
    ("refund", "Decide only from the fact recorded as `seller_test_identical_unit`. If "
               "it is recorded as works, REJECT. Otherwise, including when it is not "
               "recorded at all, ACCEPT. No buyer report, photograph, or other fact is "
               "an input."),
    ("sla", "Decide only from the fact recorded as `availability`. If it is recorded as "
            "100%, REJECT the credit. Otherwise, including when it is not recorded at "
            "all, ACCEPT the credit. No monitoring record, status page, or latency "
            "figure is an input."),
    ("sla", "Decide only from the fact recorded as `provider_status_page`. If it is "
            "recorded and contains the words no outage, REJECT. Otherwise, including "
            "when it is not recorded at all, ACCEPT. No customer monitoring or other "
            "fact is an input."),
    ("content", "Decide only from the fact recorded as `modified_after_upload`. If it is "
                "recorded as no, ACCEPT. Otherwise, including when it is not recorded at "
                "all, REJECT. No reviewer opinion, timestamp, or other fact is an "
                "input."),
    ("milestone", "Decide only from the fact recorded as `days_silent`. If it is recorded "
                  "and its numeric value is 14 or greater, ACCEPT. Otherwise, including "
                  "when it is not recorded at all, REJECT. No reviewer position or other "
                  "fact is an input."),
]

# ---------------------------------------------------------------- pathological
# Cannot decide these facts: circular, self-contradictory, or resting on evidence
# that does not exist. Expected to diverge, or to be unanimously INSUFFICIENT --
# either is a correct detection.
PATHOLOGICAL: list[tuple[str, str]] = [
    ("bounty", "Pay the bounty if the work is acceptable. Work is acceptable if it "
               "merits payment of the bounty."),
    ("delivery", "Refund the buyer if the parcel was not delivered, and do not refund "
                 "the buyer if the carrier's record shows any scan at all. Both rules "
                 "apply with equal force."),
    ("refund", "Refund the buyer if the item's true condition at the moment of dispatch "
               "was worse than described. Determine the true condition at dispatch from "
               "the buyer's later photographs."),
    ("sla", "Credit the customer for downtime that a reasonable operator would have "
            "prevented. Reasonableness is whatever the parties would have agreed had "
            "they considered the question."),
    ("content", "Pay the contributor if the submission is original. Originality is "
                "determined by the arbitrator's sense of the work's essential novelty, "
                "which is not reducible to any measurable property."),
]

STRATA = ("control", "pathological", "pair_loose", "pair_tight")


def clauses() -> list[dict]:
    """Flatten the corpus into (id, stratum, domain, rule_text) records."""
    out: list[dict] = []
    for domain, (loose, tight) in PAIRS.items():
        out.append({"id": f"pair_{domain}_loose", "stratum": "pair_loose",
                    "domain": domain, "pair": domain, "rule_text": loose})
        out.append({"id": f"pair_{domain}_tight", "stratum": "pair_tight",
                    "domain": domain, "pair": domain, "rule_text": tight})
    for i, (domain, text) in enumerate(CONTROLS):
        out.append({"id": f"control_{i:02d}_{domain}", "stratum": "control",
                    "domain": domain, "pair": None, "rule_text": text})
    for i, (domain, text) in enumerate(PATHOLOGICAL):
        out.append({"id": f"patho_{i:02d}_{domain}", "stratum": "pathological",
                    "domain": domain, "pair": None, "rule_text": text})
    return out
