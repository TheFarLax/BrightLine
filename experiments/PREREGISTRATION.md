# E6 pre-registration

Written and committed **before the study runs**. Thresholds fixed here decide
whether Split Score ships or is dropped. Nothing below is adjusted after seeing
results; if the corpus turns out to be badly built, that is disclosed as a revision
with its own commit, once.

Commit of this file is the timestamp. Raw per-observation output lands in
`experiments/E6_calibration/`.

## The question

Does cross-model divergence on adversarial probes separate resolution rules that are
procedurally underspecified from rules that are not — by more than the mechanical
variance of the measurement itself?

If yes, Split Score is a usable instrument. If no, the counterexample generator ships
alone and the score does not.

## Corpus

| stratum | n | what it is | expected |
|---|---|---|---|
| `control` | 10 | objectively decidable rules: numeric thresholds, explicit sources, explicit tie-breaks | divergence at the noise floor |
| `pathological` | 5 | rules that cannot decide these facts: circular, self-contradictory, or resting on evidence that does not exist | high divergence **or** unanimous `INSUFFICIENT` |
| `pair_loose` | 6 | the underspecified half of a matched pair | higher than its twin |
| `pair_tight` | 6 | same commercial intent, procedure specified | lower than its twin |

Matched pairs hold the deal constant and vary only whether the resolution procedure
is pinned down. Both halves get the **same probe set**, so probe difficulty cannot
explain a difference between them.

Probes: 2 per clause, hermetic, adversary v1, drawn from a per-domain probe set so a
pair shares probe ids exactly. Panel: the 6 pinned models in `PANEL_MODELS`.

## Variance decomposition

Observed divergence is a sum of at least six things. Only the last is the product.

| arm | configuration | isolates |
|---|---|---|
| `A0` | 1 model, identical probe, repeated | harness + sampling floor |
| `A1` | 1 model, temperature raised, identical probe | sampling noise |
| `A2` | 1 model, 3 meaning-preserving paraphrases of the probe | prompt sensitivity |
| `A3` | 6 models, **identical** probe | cross-model capability spread |
| `A4` | 6 models, distinct adversarial probes | what a report actually states |
| `A5` | Bradbury live committee, subset | does the lab result transfer |

`A0` is obtained free on every panel run: a single-validator `leader_only` transaction
re-samples its own answer and votes on it, so `self_consistent` is recorded per
observation. `A1` and `A2` are run only on the models whose studionet config exposes
`temperature`.

## Pass criteria — all six must hold

1. **Controls sit at the floor.** mean divergence over `control` ≤ noise floor + 0.05.
2. **Pathological rules are detected.** each `pathological` clause either has mean
   divergence ≥ 0.30 or is unanimously `INSUFFICIENT` on ≥ half its probes.
3. **Matched pairs separate.** `Δ = mean_div(loose) − mean_div(tight)` > 0 for ≥ 5 of
   6 pairs, and the Wilcoxon signed-rank test over pairs gives p < 0.05.
   *(With n = 6 the smallest attainable two-sided p is 0.031, reached only when all
   six pairs move the same way. This is a deliberately tight bar for a small corpus;
   if it fails on 5-of-6 the finding is reported as directional-but-underpowered, not
   as a pass.)*
4. **Discriminability.** ROC AUC separating `loose` ∪ `pathological` from
   `tight` ∪ `control` at clause level ≥ 0.75, with a bootstrap 95% CI excluding 0.5.
5. **Attribution.** residual interpretive variance `A4 − max(A1, A2, A3)` is the
   largest single component. If `A3` — same probe, different models — dominates, we
   are measuring model capability, not rule decidability.
6. **Transfer.** Spearman ρ between `A4` and `A5` on the shared subset ≥ 0.6.

## Failure branches, decided now

- **4 or 5 fails** → drop Split Score. Ship the counterexample generator, report
  counterexample counts as raw findings with no calibrated interpretation, and publish
  the negative result in `docs/RESULTS.md`.
- **1 fails** → the instrument is broken, not merely weak. Halt and diagnose before
  reporting any number from it.
- **6 fails** → keep the score as a studionet lab instrument only, and say so
  wherever it appears.
- **3 fails while 1, 2, 4, 5 pass** → the corpus is at fault, not the instrument.
  One disclosed corpus revision is permitted, then a re-run. Only one.
- **2 fails** → investigate whether `INSUFFICIENT` is absorbing the signal before
  touching anything else.

## Declared in advance

- `INCONCLUSIVE` observations are excluded from both numerator and denominator, and
  the inconclusive rate is reported per stratum. A stratum whose inconclusive rate
  exceeds 0.25 after one top-up pass is reported as low-confidence.
- A clause with fewer than 3 valid observations on a probe contributes no divergence
  value for that probe.
- The panel excludes `x-ai/grok-4` for the reason recorded in `PANEL_EXCLUDED`.
- Studionet only for A0–A4. Every number is a studionet number unless labelled A5.
- Nothing here predicts human disputes or claims anything about fairness.

---

## Corpus revision 1 — disclosed, made before the study ran

A one-clause smoke run (control #0, bounty) split the panel 4–2 and would have
failed criterion 1. Diagnosis from the dissenting reasons: the control referenced
*"the runner named in the listing"*, and the probes never identify which runner that
is. Claude-sonnet-4.5 and kimi-k2.5 both returned `INSUFFICIENT` saying exactly that.
The clause was objective in the abstract and undecidable against its own probes, so
it was not a control.

All ten controls were rewritten to key off fact values the probes actually record,
with an explicit default when a fact is absent and an explicit irrelevance clause, so
each is forced on both probes of its domain. No full-corpus result had been produced
or observed at the time of this change; the only data seen was the single smoke clause
above, and its raw output is in `experiments/E6_calibration/`.

This is the one disclosed revision. Thresholds are unchanged. If the controls fail
again, that is a criterion-1 halt and the instrument — not the corpus — is the
suspect.
