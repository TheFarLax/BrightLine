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
