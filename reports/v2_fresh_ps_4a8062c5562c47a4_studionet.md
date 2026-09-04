# Brightline report — Bounty payout on a working fix (tightened)

**2 of 8 probes split the panel** (threshold τ = 0.2, panel of 6 models)

    rule            v2  0xaf58b67a93782d1c
    "Pay the contributor the full bounty if all of the following hold. (1) The designated check suite named in the bounty listing reports every check passing on the contributor's final commit; that suite is the sole authority on whether the fix works, and no other runner, local result, or opinion overrides it. (2) The suite reports no check failing that was passing on the parent commit; a newly failing check anywhere in the suite defeats payment even if the reported defect is closed. (3) Every reproduction path recorded on the issue at the time the bounty was posted no longer reproduces the defect. If some but not all recorded reproduction paths are resolved, pay the contributor that fraction of the bounty, rounded down to the nearest whole unit. (4) The contributor's final commit was pushed before the cutoff stated in the listing; the cutoff binds the push, not the completion of the check suite, and delay caused by neither party does not defeat payment. (5) Where the reported defect is that an operation is too slow, the listing's stated numeric threshold governs; if the listing states no threshold, this rule does not determine an outcome. If the designated check suite has not reported within fourteen days of the push, and no maintainer has stated a position, pay the full bounty."

| metric | value | what it means |
|---|---|---|
| counterexamples | **2 / 8** | probes where the panel did not converge |
| mean divergence | 0.0625 | 1 − modal share, averaged over measurable probes |
| max divergence | 0.25 | worst single probe |
| noise floor | 0.0 | same-model self-disagreement, measured on every run |
| net | 0.0625 | divergence above the noise floor |
| unanimous INSUFFICIENT | 3 | rule decidably silent, panel agreed on that |
| inconclusive | 0.2083 | infrastructure failures, excluded from both sides |

## Counterexamples

### probe #3 · regression_after_fix · divergence 0.25

> On the parent commit the designated suite had one check already failing for unrelated reasons. On the contributor's final commit that check still fails and every other check passes. The reported defect is closed.

- **ACCEPT** — gpt-5.1 (92), deepseek-v3.2 (95), qwen3-235b-a22b-2507 (95)
- **REJECT** — gemini-3-flash-preview (100)

  _Condition (1) is satisfied because, aside from one check that was already failing on the parent commit, every check on the designated suite passes on the contributor's final commit, and condition (2) is satisfied because there are 0 newly failing checks compared to the parent commit; no other rule condition is triggered by the given facts._

  Missing specification (advisory, derived off-chain):
  - whether collateral breakage counts against performance
  - the scope boundary of the obligation

### probe #4 · late_evidence · divergence 0.25

> The contributor pushed a commit before the cutoff, then pushed a second commit ninety minutes after the cutoff that only reformatted whitespace. The designated suite passed on the second commit and was never run on the first.

- **INSUFFICIENT** — gpt-5.1 (93)
- **REJECT** — gemini-3-flash-preview (90), deepseek-v3.2 (100), qwen3-235b-a22b-2507 (95)

  _The rule requires that the contributor's final commit be pushed before the cutoff, but here the final commit—the one on which the designated suite ran—was pushed ninety minutes after the cutoff, and the rule provides no tie‑breaker or exception for a later whitespace-only commit._

  Missing specification (advisory, derived off-chain):
  - whether the deadline binds the act or the confirmation of the act
  - the effect of delay caused by neither party

## Provenance

```
network                  studionet
contract_address         0x0cC3f4684fBd89dB74331A702d09a67DCc6585f7
runner_depends           py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6
rule_hash                0xaf58b67a93782d1cc0653d9ba70cab0eee9f39b2e79f9321fbd76099bb201562
probe_set_id             ps_4a8062c5562c47a4
adversary_version        adv-v1.0.0
adversary_prompt_hash    0x08391c62bcae8c4105b4dadabb5af678c7607bdf56d06648d0ab2d4ebd5aa1a8
probe_generator          authored
channel                  PANEL
panel_size               6
wall_seconds             6584.6
generated_at             2026-09-04T10:46:05Z
report_hash              0xdd07536a1b8d293177a517c944919eb9d0d21eba715b1a4212f45007ac55b769
```

_Split Score is an experimental measurement of panel divergence over a fixed probe set. It is not a probability that a dispute will occur, not a prediction of how a human court would rule, and not a judgment about whether the agreement is fair. Decidability is not fairness: a rule can be trivially easy to adjudicate and still be one-sided._