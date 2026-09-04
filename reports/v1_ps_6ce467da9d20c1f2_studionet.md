# Brightline report — Bounty payout on a working fix

**4 of 8 probes split the panel** (threshold τ = 0.2, panel of 6 models)

    rule            v1  0x70346ad83b062d8f
    "Pay the contributor if the contributor delivers a working fix."

| metric | value | what it means |
|---|---|---|
| counterexamples | **4 / 8** | probes where the panel did not converge |
| mean divergence | 0.3125 | 1 − modal share, averaged over measurable probes |
| max divergence | 0.6667 | worst single probe |
| noise floor | 0.0 | same-model self-disagreement, measured on every run |
| net | 0.3125 | divergence above the noise floor |
| unanimous INSUFFICIENT | 0 | rule decidably silent, panel agreed on that |
| inconclusive | 0.0 | infrastructure failures, excluded from both sides |

## Counterexamples

### probe #0 · regression_after_fix · divergence 0.6667

> The contributor submitted a change that closes the reported defect. After the change was merged, a defect that had been closed five weeks earlier began reproducing again in the same module. No other behaviour changed.

- **ACCEPT** — gpt-5.1 (86), qwen3-235b-a22b-2507 (85)
- **INSUFFICIENT** — deepseek-v3.2 (75), kimi-k2.5 (90)
- **REJECT** — claude-sonnet-4.5 (90), gemini-3-flash-preview (90)

  _The rule only requires that the contributor "delivers a working fix" for the reported defect, and the facts state that the submitted change closes the reported defect; the rule does not address regressions of previously closed defects or impose any additional conditions._

  Missing specification (advisory, derived off-chain):
  - whether collateral breakage counts against performance
  - the scope boundary of the obligation

### probe #1 · conflicting_evidence · divergence 0.5

> The change closes the reported defect. Automated checks on the project's primary runner report every check passing. Automated checks on the project's secondary runner report one failure, in a module the change did not touch. The maintainer has not commented.

- **ACCEPT** — gemini-3-flash-preview (100), kimi-k2.5 (95), qwen3-235b-a22b-2507 (85)
- **INSUFFICIENT** — gpt-5.1 (78), claude-sonnet-4.5 (85), deepseek-v3.2 (85)

  _The contributor delivered a fix that closes the reported defect and passes primary runner checks; the secondary runner failure occurred in an untouched module, indicating the fix itself is working._

  Missing specification (advisory, derived off-chain):
  - which source of truth is authoritative
  - the tie-break when two authorities disagree

### probe #4 · partial_completion · divergence 0.5

> The reported defect had two documented reproduction paths. The contributor's change eliminates the first path entirely. The second path still reproduces the defect. The contributor stated they consider the remaining path a separate issue.

- **INSUFFICIENT** — claude-sonnet-4.5 (85), deepseek-v3.2 (85), kimi-k2.5 (95)
- **REJECT** — gpt-5.1 (93), gemini-3-flash-preview (90), qwen3-235b-a22b-2507 (95)

  _The rule requires delivery of 'a working fix' but does not define whether a fix must resolve all reproduction paths of a reported defect or only some. With one path still reproducing the defect, whether the fix qualifies as 'working' cannot be determined from the rule text alone._

  Missing specification (advisory, derived off-chain):
  - what fraction of performance earns what fraction of payment
  - whether partial performance is a distinct outcome or a failure

### probe #7 · criteria_gap · divergence 0.3333

> The reported defect is that an operation is unacceptably slow. The contributor's change reduces the operation's runtime from 40 seconds to 9 seconds. The original report did not state a target runtime. The operation still takes longer than comparable operations in the project.

- **ACCEPT** — gpt-5.1 (94), gemini-3-flash-preview (100), deepseek-v3.2 (90), qwen3-235b-a22b-2507 (95)
- **INSUFFICIENT** — claude-sonnet-4.5 (85), kimi-k2.5 (90)

  _The rule requires payment if the contributor delivers a "working fix"; the change reduces runtime from 40s to 9s, addressing the reported performance defect, and there is no requirement that performance match comparable operations or meet a specific target._

  Missing specification (advisory, derived off-chain):
  - a measurable acceptance threshold for the operative term

## Provenance

```
network                  studionet
contract_address         0x0cC3f4684fBd89dB74331A702d09a67DCc6585f7
runner_depends           py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6
rule_hash                0x70346ad83b062d8fe939b908b9c6321186513aabb25919ef038958305dd0b8e2
probe_set_id             ps_6ce467da9d20c1f2
adversary_version        adv-v1.0.0
adversary_prompt_hash    0x08391c62bcae8c4105b4dadabb5af678c7607bdf56d06648d0ab2d4ebd5aa1a8
probe_generator          authored
channel                  PANEL
panel_size               6
wall_seconds             924.1
generated_at             2026-09-04T08:08:31Z
report_hash              0x3892c0c0aa6103bd62262bab7f1e2da7907602e1184e562f44ef18d904d366f6
```

_Split Score is an experimental measurement of panel divergence over a fixed probe set. It is not a probability that a dispute will occur, not a prediction of how a human court would rule, and not a judgment about whether the agreement is fair. Decidability is not fairness: a rule can be trivially easy to adjudicate and still be one-sided._