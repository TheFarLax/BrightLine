# Brightline

**An agreement fuzzer, run by the network that will later judge the agreement.**

A software fuzzer feeds a program hard inputs until something breaks. Brightline does
that to a resolution rule: it generates adversarial fact patterns, sends each one
through GenLayer as a real adjudication, and reports the exact scenarios where
independent models do not reach the same decision.

The output that matters is not a score. It is a sentence: *here is the case where you
don't get paid.*

## The first real result

Rule under test — the unimproved version a bounty program would actually write:

> Pay the contributor if the contributor delivers a working fix.

Eight hermetic probes, six frontier models pinned one per run, 48 real GenLayer
adjudications on studionet:

```
4 of 8 probes split the panel        mean divergence 0.3125
noise floor 0.0                     inconclusive 0.0
```

The worst one is worth reading in full ([reports/](reports/)):

> *The contributor submitted a change that closes the reported defect. After the
> change was merged, a defect that had been closed five weeks earlier began
> reproducing again in the same module.*

- **ACCEPT** — gpt-5.1 (86), qwen3-235b (85)
- **INSUFFICIENT** — deepseek-v3.2 (75), kimi-k2.5 (90)
- **REJECT** — claude-sonnet-4.5 (90), gemini-3-flash (90)

Three different answers, six confident models, one sentence of contract. Nobody is
malfunctioning — the rule never said whether collateral breakage counts.

Four other probes converged unanimously, which is the point: the instrument
discriminates within the same rule and the same probe set.

## Why this needs GenLayer

You can ask a private model whether your agreement looks clear. That model is not the
one that will decide your case, so its answer binds nobody and your counterparty has
no reason to accept it. On GenLayer the validator network **is** the adjudication
mechanism, so the opinion can come from the future adjudicator, before money is at
risk, with the transaction hashes published so anyone can recompute the result.

## How it is measured

Two protocol facts shape the whole design, both confirmed empirically here:

1. **A split adjudication writes no state.** When validators disagree the transaction
   rotates leaders and ends `UNDETERMINED`. The interesting cases store nothing, so
   the contract returns its full result object and the analyzer reads receipts.
2. **A validator's own answer is never published — only its boolean vote.** So a
   consensus round tells you the jury divided but not into what.

Hence the **panel channel**: one pinned model per run with `leader_only`, which yields
that model's actual decision. It also yields the noise floor for free — the leader
executes the validator path too, so it re-samples and votes on its own answer.
`self-ok` on every row means the model reproduced its own decision; a `SELF-SPLIT`
row is sampling noise, not disagreement.

Contract-side: exactly one nondeterministic block per transaction, a four-value
decision vocabulary (`ACCEPT | REJECT | PARTIAL | INSUFFICIENT`), and a validator
function that re-derives the answer independently and compares **only** the decision
field. `INSUFFICIENT` is a first-class verdict — without it the model must invent a
ruling when the rule is silent, and we would be measuring hallucination instead of
decidability.

## The re-test loop

```
rule v1  →  probe set X (frozen)   →  4/8 split  →  counterexamples
                                          ↓
rule v2 written against those findings
                                          ↓
         →  probe set X (same ids)  →  regression:      did the counterexamples close?
         →  probe set Y (fresh)     →  generalization:  or did we learn the test?
```

The fresh arm is not optional. Without it a rule can be tuned to pass a corpus it has
already seen, and the number becomes theatre.

## Layout

```
contracts/brightline_probe.py   the only consensus-critical code
prompts/adversary_v1.md         published adversary instructions (hash in every report)
agreements/                     rules under test, v1 and v2
probes/ps_*.json                frozen, content-addressed probe manifests
brightline/                     spec · adversary · chain · panel · report · diff · run
scripts/e*.py                   the approval gates, each writing raw evidence
experiments/                    raw gate output, kept
reports/                        generated reports + every raw receipt
docs/VERIFIED_VS_ASSUMED.md     every GenLayer claim and its status
docs/LIMITATIONS.md             what this does not measure
```

## Running it

```bash
/usr/bin/python3.12 -m venv .venv && .venv/bin/pip install "genlayer-test[sim]" genlayer-py requests genvm-linter
.venv/bin/genvm-lint check contracts/brightline_probe.py

.venv/bin/python scripts/e1_smoke.py studionet          # contract works
.venv/bin/python scripts/e2_gate.py studionet           # panel channel works
.venv/bin/python -m brightline.run \
    agreements/bounty_working_fix_v1.yaml \
    probes/ps_6ce467da9d20c1f2.json --network studionet
.venv/bin/python -m brightline.diff \
    reports/v1_....json reports/v2_frozen_....json --fresh reports/v2_fresh_....json
```

Bradbury (network truth, `scripts/e3_e4_bradbury.py`) needs a funded account; the
faucet requires GitHub OAuth plus a Turnstile challenge, so that step is human.

## Honesty notes

Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before quoting any number. In short:
decidability is not fairness; the score is a property of the probe set and adversary,
not of a sentence; and every result here is a studionet result until the Bradbury arm
runs. GenLayer's own `gltest` already ships `.analyze()` for contract-level
consistency — Brightline points that idea outward, at rule level, with a real
validator draw, adversarial probes, counterexamples, and a citable artifact.
