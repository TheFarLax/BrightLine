# Results — 2026-09-04, studionet

Every number here comes from real GenLayer transactions on studionet. Raw receipts
for every observation are in `reports/raw/`, transaction hashes are in the report
JSON, and the whole thing is recomputable from those hashes.

## The re-test loop

| arm | rule | probe set | counterexamples | mean divergence |
|---|---|---|---|---|
| baseline | v1 | frozen `ps_6ce467da9d20c1f2` | **4 / 8** | 0.3125 |
| regression | v2 | frozen (same probe ids) | **4 / 8** | 0.2250 |
| generalization | v2 | fresh `ps_4a8062c5562c47a4` | **2 / 8** | 0.0625 |

Noise floor was **0.0** on every run: across ~150 single-model adjudications, every
model that produced a decision reproduced that decision when it re-sampled and voted
on its own answer. So none of the divergence above is sampling noise.

## Per-probe, v1 → v2 on the frozen set

| probe | family | before | after | |
|---|---|---|---|---|
| #0 | regression_after_fix | 0.6667 | 0.5 | still split |
| #1 | conflicting_evidence | 0.5 | 0.4 | still split |
| #2 | conflicting_evidence | 0.1667 | 0.3333 | **OPENED** |
| #3 | late_evidence | 0.0 | 0.0 | clean |
| #4 | partial_completion | 0.5 | 0.0 | closed |
| #5 | partial_completion | 0.1667 | 0.4 | **OPENED** |
| #6 | missing_confirmation | 0.1667 | 0.1667 | clean |
| #7 | criteria_gap | 0.3333 | 0.0 | closed |

## What is worth noticing

**The three-way split.** On probe #0 — a fix that closes the reported defect and
reintroduces an older one — six frontier models produced *three* different decisions
under v1, all with confidence 75–90: ACCEPT (gpt-5.1, qwen3), INSUFFICIENT
(deepseek-v3.2, kimi-k2.5), REJECT (claude-sonnet-4.5, gemini-3-flash). Nobody is
malfunctioning. The rule never said whether collateral breakage counts.

**Tightening a rule can create ambiguity.** Two probes that were nearly clean under
v1 got *worse* under v2. Adding five numbered clauses added interactions between
them, and probes #2 and #5 land in those interactions. This is the single most useful
thing the tool produced, and it is not a result anyone would invent for a demo: it
says a rewrite needs re-testing, not just review.

**A rule can be decidably silent, and that is a good outcome.** v2 clause (5) says
that where a performance defect has no stated numeric threshold, the rule does not
determine an outcome. On probe #7 all six models returned INSUFFICIENT unanimously —
divergence 0.0. The panel agreed that the rule refuses to decide. That is strictly
better than four models guessing ACCEPT and two guessing INSUFFICIENT, which is what
v1 produced on the same facts.

**The rewrite generalized.** The fresh probe set was written against v2's own new
surface — what happens when the designated check suite contradicts itself, is
deleted mid-flight, or disagrees with a maintainer — and found 2/8 with mean
divergence 0.0625. Had the fresh set been *worse* than the frozen set, the frozen
improvement would have been farmed. This is why the fresh arm is not optional.

**Length costs reliability.** v1's inconclusive rate was 0.0; v2's was 0.27 before
top-up and 0.083 after. The residual failures are all one model (`kimi-k2.5`)
failing to emit parseable JSON against v2's ~1,500-character rule. That is a real
finding about long rules, recorded rather than smoothed away — and it is classified
as INCONCLUSIVE, never as disagreement.

## Gate status

| gate | result |
|---|---|
| E1 contract deploys, registers, adjudicates | **PASS** — first adjudication produced a real 3–2 split |
| E2a panel channel yields per-model decisions | **PASS** — 6 models, self-split rate 0.0 |
| E2b `gen_call` validator-mode replay | **FAIL on studionet** — that RPC returns no `eqOutputs`; superseded by E2a |
| E3 real Bradbury transaction | **BLOCKED** — faucet needs GitHub OAuth + Turnstile |
| E4 `validatorVotes` decode | **BLOCKED on E3** — inference unused anywhere; fallback implemented |
| E5 frozen probe reuse across rule versions | **PASS** — v2 measured against v1's probe ids |
| E7 rewrite changes counterexamples | **PASS, mixed** — 2 closed, 2 opened, mean fell, fresh set cleaner |
| E6 calibration study | not started |

## What these numbers are not

`4 / 8` means *adversary v1 found four counterexamples in eight attempts with this
six-model panel on studionet*. It is not a probability of dispute, not a prediction
about a human court, and not a statement that the agreement is fair. See
[LIMITATIONS.md](LIMITATIONS.md). One rule and eight probes is a demonstration that
the instrument resolves interpretive divergence from noise — it is not the
calibration study, which is still unrun.

---

# E6 calibration study — main run, 2026-09-05

Pre-registered at commit `28f7019`, **before any calibration data existed**. Thresholds
and failure branches in [../experiments/PREREGISTRATION.md](../experiments/PREREGISTRATION.md)
were not touched. 27 clauses × 2 probes × 6 models = 324 adjudications on studionet,
2h 52m wall, raw output in `experiments/E6_calibration/`.

## Strata

| stratum | n | mean divergence | min | max | inconclusive |
|---|---|---|---|---|---|
| `control` | 10 | **0.0333** | 0.0 | 0.0833 | 0.017 |
| `pair_tight` | 6 | 0.1861 | 0.0 | 0.3333 | 0.014 |
| `pair_loose` | 6 | 0.2167 | 0.0833 | 0.4667 | 0.028 |
| `pathological` | 5 | 0.2333 | 0.0833 | 0.5 | 0.017 |

**Noise floor (A0) = 0.0** over **323** self-consistency observations. Not one model,
anywhere in the corpus, failed to reproduce its own decision on a second sample. The
mechanical floor of this instrument is empirically zero.

## Criteria, as pre-registered

| # | criterion | threshold | observed | result |
|---|---|---|---|---|
| C1 | controls at the floor | ≤ floor + 0.05 = 0.05 | 0.0333 | **PASS** |
| C2 | pathological detected | div ≥ 0.30 **or** unanimous `INSUFFICIENT` on ≥ half its probes | 5 / 5 detected | **PASS** |
| C3 | matched pairs separate | ≥ 5 of 6 directional **and** Wilcoxon p < 0.05 | 3 of 6, W = 12.0, p = 0.844 | **FAIL** |
| C4 | discriminability | AUC ≥ 0.75, bootstrap CI excludes 0.5 | AUC 0.787, CI [0.585, 0.938] | **PASS** |
| C5 | attribution | residual > max(A1, A2, A3) | not evaluated in the main run | pending |
| C6 | transfer to Bradbury | Spearman ρ ≥ 0.6 | not evaluated in the main run | pending |

**The study does not pass.** The pre-registration requires all six criteria to hold.

**And no failure branch is invocable yet.** The branch for a C3 failure is written as
*"3 fails while 1, 2, 4, 5 pass"* — it is conditioned on C5, and C5 was never
evaluated, so it neither passed nor failed. Branch selection literally depends on a
criterion that does not yet have a value. Running C5 and C6 before invoking anything
is the only reading of the pre-registration that is faithful to it. Those arms are
running now; the branch will be applied to the completed set, not to a partial one.

## C3 in detail — and the confound I should have controlled

| pair | loose | tight | Δ (loose − tight) | direction |
|---|---|---|---|---|
| refund | 0.4667 | 0.2500 | +0.2167 | as predicted |
| milestone | 0.3333 | 0.0000 | +0.3333 | as predicted |
| sla | 0.1666 | 0.0000 | +0.1666 | as predicted |
| bounty | 0.1667 | 0.2500 | −0.0833 | **reversed** |
| content | 0.0833 | 0.2833 | −0.2000 | **reversed** |
| delivery | 0.0833 | 0.3333 | −0.2500 | **reversed** |

Three of six pairs went the wrong way. The obvious confound, which the corpus does not
control: the tight halves are **4.2× to 7.9× longer** than the loose halves (mean
6.2×). Specifying a procedure means adding clauses, and added clauses interact. So a
`Δ < 0` may say "this tight clause is longer and more conditional", not "this tight
clause is less decidable".

That is the same phenomenon the v1 → v2 re-test surfaced independently, where two
probes that were nearly clean under the short rule **newly opened** under the long
one. Two separate experiments now point at it, which makes it a finding about
rule-writing rather than a quirk: **added specificity adds surface, and the added
surface can diverge more than the vagueness it replaced.**

## What C4 is and is not

AUC 0.787 with a bootstrap CI excluding 0.5 clears the pre-registered bar. But the
separation it measures is substantially `control` (0.0333) against everything else,
not `loose` against `tight` — C3 shows the loose/tight contrast does not separate at
all. Read C4 as "the instrument distinguishes forced-answer rules from
judgment-requiring rules", which is real and useful, and **not** as "the instrument
ranks two drafts of the same clause". The second claim is the one that failed.

## C2 in detail

| clause | divergence | unanimous `INSUFFICIENT` probes | detected via |
|---|---|---|---|
| `patho_01_delivery` | 0.5 | 0 | divergence ≥ 0.30 |
| `patho_03_sla` | 0.25 | 1 | unanimous `INSUFFICIENT` |
| `patho_00_bounty` | 0.1666 | 1 | unanimous `INSUFFICIENT` |
| `patho_02_refund` | 0.1666 | 1 | unanimous `INSUFFICIENT` |
| `patho_04_content` | 0.0833 | 1 | unanimous `INSUFFICIENT` |

Note how C2 was actually satisfied: four of five pathological clauses were caught by
the panel **agreeing that the rule cannot decide**, not by the panel splitting. A
circular rule produces unanimous `INSUFFICIENT`, which is a low divergence number and
a correct detection. This is the clearest evidence so far that `INSUFFICIENT` had to
be in the decision vocabulary — without it those four clauses would have forced
invented verdicts and shown up as noise.

## C5 and C6 — the remaining arms

`A0` repeat (same model, same probe, 5×), `A2` paraphrase (same model, three
meaning-preserving rewrites of the probe, facts byte-identical) on three domains;
`A5` on Bradbury's own committee for all six pair domains.

| component | value | what it is |
|---|---|---|
| `A0` self-consistency, main run | **0.0** | 323 observations; no model failed to reproduce its own decision |
| `A0` repeat, direct | **0.0** | 5 repeats × 3 domains, all unanimous |
| `A1` temperature stress | **unmeasurable** | see below |
| `A2` prompt paraphrase | **0.0** | 3 paraphrases × 3 domains, all unanimous |
| `A3` cross-model, forced answer | 0.0333 | the control stratum: six models, answer forced by the clause |
| `A4` cross-model, adversarial (loose) | 0.2167 | what a report actually states |
| `A4` cross-model, adversarial (pathological) | 0.2333 | |

**`A1` is not measurable on studionet.** Every provider entry whose config exposes
`temperature` reports `is_model_available: false`; the entries that work (the
`openrouter` routes) expose an empty config with no temperature knob. So the
pre-registered C5 formula — `A4 − max(A1, A2, A3)` — **has no value**, and C5 is
reported as *not evaluable as written*, plus a clearly-labelled substituted version
with `A1` replaced by `A0`:

    residual = 0.2167 − max(0.0, 0.0, 0.0333) = 0.1834   > every mechanical component

Substituted C5 passes. The pre-registered C5 does not exist. Both are recorded.

The striking part is not the arithmetic. **Repetition and paraphrase both produced
exactly zero divergence.** Rewording a probe three ways, keeping the facts identical,
did not move a single decision on any of the three domains. Whatever the panel is
responding to, it is not prose surface.

**C6 fails, and not because the correlation was weak.** Bradbury's live committee
returned `vote_divergence = 0.0` on all five measurable domains — unanimous every
time, on the same clauses where the pinned panel diverged 0.083 to 0.467. With zero
variance on one axis there is no rank correlation to compute, so ρ is undefined and
the criterion cannot be met. Two readings, both worth stating: the network's own
committee may be more homogeneous than a deliberately diverse pinned panel, and a
vote (agree/disagree with one leader) is a coarser instrument than a decision
distribution. `sim_config` is Studio-only, so the live arm cannot be made to yield a
distribution — this is a ceiling on the method, not a bug in the run.

## Verdict, with the pre-registered branches applied as written

| # | criterion | result |
|---|---|---|
| C1 | controls at the floor | **PASS** (0.0333 ≤ 0.05) |
| C2 | pathological detected | **PASS** (5/5) |
| C3 | matched pairs separate | **FAIL** (3/6 directional, p = 0.844) |
| C4 | discriminability | **PASS** (AUC 0.787, CI [0.585, 0.938]) |
| C5 | attribution | **not evaluable as pre-registered**; substituted version passes (residual 0.1834) |
| C6 | transfer | **FAIL** (ρ undefined; live committee unanimous everywhere) |

**The study does not pass.** All six were required.

Two branches fire:

1. **"6 fails → keep the score as a studionet lab instrument only, and say so wherever
   it appears."** Applied. Every Split Score in this repo is labelled a studionet
   number, and the README and reports say so.
2. **"3 fails while 1, 2, 4, 5 pass → the corpus is at fault, not the instrument. One
   disclosed corpus revision is permitted, then a re-run. Only one."** Its
   precondition is met only under the *substituted* C5 — and it is **not applied**,
   because the pre-registration permits exactly one disclosed corpus revision and one
   was already spent on the control set before the study ran. The allowance is
   exhausted. The pair corpus does not get rewritten and re-run, even though the
   length confound is an obvious candidate fix and even though a re-run would probably
   look better. That is what pre-registration is for.

### What stands

- **Split Score is not validated for ranking two drafts of the same clause.** C3
  failed and cannot be retried under this pre-registration. Brightline must not be
  presented as a tool that tells you which of two rewrites is better.
- **Split Score is supported as a discriminator between forced-answer rules and
  judgment-requiring rules.** Controls 0.0333 against loose 0.2167 and pathological
  0.2333, AUC 0.787 with a CI excluding chance.
- **The mechanical floor is empirically zero.** Repetition 0.0, paraphrase 0.0, 323
  self-consistency observations without a single failure. When this instrument reports
  divergence, it is not reporting noise. That was the load-bearing question and it has
  a clean answer.
- **Transfer to a live committee is unevaluated, not demonstrated.**
- **The counterexample generator is unaffected by every branch above and ships
  regardless.** It never depended on the score being calibrated.
