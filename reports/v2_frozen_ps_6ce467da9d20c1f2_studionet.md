# Brightline report — Bounty payout on a working fix (tightened)

**4 of 8 probes split the panel** (threshold τ = 0.2, panel of 6 models)

    rule            v2  0xaf58b67a93782d1c
    "Pay the contributor the full bounty if all of the following hold. (1) The designated check suite named in the bounty listing reports every check passing on the contributor's final commit; that suite is the sole authority on whether the fix works, and no other runner, local result, or opinion overrides it. (2) The suite reports no check failing that was passing on the parent commit; a newly failing check anywhere in the suite defeats payment even if the reported defect is closed. (3) Every reproduction path recorded on the issue at the time the bounty was posted no longer reproduces the defect. If some but not all recorded reproduction paths are resolved, pay the contributor that fraction of the bounty, rounded down to the nearest whole unit. (4) The contributor's final commit was pushed before the cutoff stated in the listing; the cutoff binds the push, not the completion of the check suite, and delay caused by neither party does not defeat payment. (5) Where the reported defect is that an operation is too slow, the listing's stated numeric threshold governs; if the listing states no threshold, this rule does not determine an outcome. If the designated check suite has not reported within fourteen days of the push, and no maintainer has stated a position, pay the full bounty."

| metric | value | what it means |
|---|---|---|
| counterexamples | **4 / 8** | probes where the panel did not converge |
| mean divergence | 0.225 | 1 − modal share, averaged over measurable probes |
| max divergence | 0.5 | worst single probe |
| noise floor | 0.0 | same-model self-disagreement, measured on every run |
| net | 0.225 | divergence above the noise floor |
| unanimous INSUFFICIENT | 1 | rule decidably silent, panel agreed on that |
| inconclusive | 0.0833 | infrastructure failures, excluded from both sides |

## Counterexamples

### probe #0 · regression_after_fix · divergence 0.5

> The contributor submitted a change that closes the reported defect. After the change was merged, a defect that had been closed five weeks earlier began reproducing again in the same module. No other behaviour changed.

- **INSUFFICIENT** — gpt-5.1 (84), kimi-k2.5 (95), qwen3-235b-a22b-2507 (90)
- **REJECT** — claude-sonnet-4.5 (95), gemini-3-flash-preview (95), deepseek-v3.2 (85)

  _The rule makes payment contingent on specific conditions about the designated check suite and recorded reproduction paths at the time the bounty was posted; the facts provided do not state anything about the check suite’s status or which reproduction paths were recorded then, nor how many, so applying the rule would require supplying those missing sources of truth._

  Missing specification (advisory, derived off-chain):
  - whether collateral breakage counts against performance
  - the scope boundary of the obligation

### probe #1 · conflicting_evidence · divergence 0.4

> The change closes the reported defect. Automated checks on the project's primary runner report every check passing. Automated checks on the project's secondary runner report one failure, in a module the change did not touch. The maintainer has not commented.

- **ACCEPT** — gpt-5.1 (94), gemini-3-flash-preview (100)
- **INSUFFICIENT** — claude-sonnet-4.5 (95), deepseek-v3.2 (80), qwen3-235b-a22b-2507 (90)

  _The rule makes the designated check suite the sole authority and requires that it report every check passing with no newly failing checks; the primary runner (the designated suite) passes entirely, and failures on the secondary runner are irrelevant by the rule’s own terms. The defect is closed and the commit was pushed before the cutoff, and there is no contrary maintainer position._

  Missing specification (advisory, derived off-chain):
  - which source of truth is authoritative
  - the tie-break when two authorities disagree

### probe #5 · partial_completion · divergence 0.4

> The contributor's change makes the defect stop reproducing, but does so by disabling the feature in which the defect occurred. The feature was in use by other parts of the project. No replacement was provided.

- **ACCEPT** — gpt-5.1 (86), gemini-3-flash-preview (100), deepseek-v3.2 (90)
- **INSUFFICIENT** — claude-sonnet-4.5 (95), qwen3-235b-a22b-2507 (75)

  _All automated checks pass and there is no evidence of any newly failing checks, and the facts state that the defect no longer reproduces, which satisfies conditions (1)-(4); the rule does not disqualify fixes that disable the feature or require a replacement feature._

  Missing specification (advisory, derived off-chain):
  - what fraction of performance earns what fraction of payment
  - whether partial performance is a distinct outcome or a failure

### probe #2 · conflicting_evidence · divergence 0.3333

> The contributor's change closes the reported defect. One maintainer wrote that the approach is correct and approved it. A second maintainer wrote that the approach is wrong and requested changes. Automated checks all pass. Neither maintainer withdrew their position.

- **ACCEPT** — gemini-3-flash-preview (100), qwen3-235b-a22b-2507 (95)
- **INSUFFICIENT** — gpt-5.1 (84), claude-sonnet-4.5 (85), deepseek-v3.2 (85), kimi-k2.5 (95)

  _The rule states that the designated check suite is the 'sole authority on whether the fix works' and that 'no other runner, local result, or opinion overrides it'. Since the automated checks passed and the defect is closed, the conflicting maintainer opinions are irrelevant under the authoritative rule text._

  Missing specification (advisory, derived off-chain):
  - which source of truth is authoritative
  - the tie-break when two authorities disagree

## Provenance

```
network                  studionet
contract_address         0x0cC3f4684fBd89dB74331A702d09a67DCc6585f7
runner_depends           py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6
rule_hash                0xaf58b67a93782d1cc0653d9ba70cab0eee9f39b2e79f9321fbd76099bb201562
probe_set_id             ps_6ce467da9d20c1f2
adversary_version        adv-v1.0.0
adversary_prompt_hash    0x08391c62bcae8c4105b4dadabb5af678c7607bdf56d06648d0ab2d4ebd5aa1a8
probe_generator          authored
channel                  PANEL
panel_size               6
wall_seconds             2416.5
generated_at             2026-09-04T10:17:41Z
report_hash              0x648cb01c665b18ca06ec3a6b705b5f4b17f8c036df39fdb8332d3ee7ccf9f7ef
```

_Split Score is an experimental measurement of panel divergence over a fixed probe set. It is not a probability that a dispute will occur, not a prediction of how a human court would rule, and not a judgment about whether the agreement is fair. Decidability is not fairness: a rule can be trivially easy to adjudicate and still be one-sided._