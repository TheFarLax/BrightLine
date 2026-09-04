# Adversary v1.0.0

Published so that any counterparty can regenerate, audit, or attack a probe set
with the same instructions. The hash of this file is recorded in every probe-set
manifest and every report.

## Task

Given one natural-language resolution rule, produce N hermetic fact patterns whose
purpose is to find where the rule stops producing a reliable decision.

## Hard constraints

1. **Hermetic.** Each scenario is self-contained prose plus a flat list of facts.
   No URLs, no references to live systems, no instruction to look anything up. A
   probe that requires fetching evidence measures the internet, not the rule.
2. **Rule-agnostic wording.** Describe only what happened. Never quote the rule,
   never name a clause, never say "this is ambiguous because...". Probes must stay
   valid when the rule is rewritten, which is what makes the frozen-set regression
   test meaningful.
3. **Plausible, not absurd.** Every scenario must be something a reasonable
   counterparty could actually produce. Absurd hypotheticals inflate divergence and
   teach the drafter nothing.
4. **One pressure point per probe.** A scenario that varies four things at once
   cannot be attributed to a missing specification.
5. **No verdict hints.** Do not signal the "right" answer, and do not include a
   field that states an expected decision. The probe is an input, not a test with
   an answer key.

## Families and what each is probing

| family | pressure applied |
|---|---|
| `regression_after_fix` | the obligation is met on its face while causing a new problem elsewhere |
| `conflicting_evidence` | two credible sources of truth disagree and the rule orders neither |
| `late_evidence` | the facts arrive, but after whatever deadline the rule implies |
| `partial_completion` | some but not all of the obligation is discharged |
| `missing_confirmation` | no authority has spoken, and the rule assumes one has |
| `criteria_gap` | the rule's operative term has no definition that reaches these facts |

## Output shape

```json
{
  "family": "<one of the six>",
  "scenario": {
    "narrative": "<2-4 sentences of plain past-tense fact>",
    "facts": [{"k": "<snake_case_key>", "v": "<short value>"}],
    "evidence_available": ["<artifact>"],
    "evidence_absent": ["<artifact>"]
  }
}
```

`evidence_available` and `evidence_absent` are what makes the procedural families
legible: a rule that never says which artifact governs will split precisely when
the available set is ambiguous and the absent set matters.

## Anti-goal

Do not hunt for vague adjectives. Empirically, wording vagueness is a weak
predictor of whether an adjudicated agreement is actually disputed; the failure
modes that matter are procedural. Probe the procedure.
