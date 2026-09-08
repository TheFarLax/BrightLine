# Brightline

**An agreement fuzzer, run by the network that will later judge the agreement.**

A software fuzzer feeds a program hard inputs until something breaks. Brightline does
that to a resolution rule: it generates adversarial fact patterns, sends each one
through GenLayer as a real adjudication, and reports the exact scenarios where
independent models do not reach the same decision.

The output that matters is not a score. It is a sentence: *here is the case where you
don't get paid.*

**Try it:** `.venv/bin/python scripts/serve.py` → <http://127.0.0.1:8800/frontend/>.
The reports, the rule hasher and every chain read work with no wallet at all.
Six-minute walkthrough: [docs/DEMO.md](docs/DEMO.md).

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

What actually happened when v2 was written against v1's counterexamples
([reports/retest.json](reports/retest.json)):

```
frozen set   K 4/8 → 4/8      mean divergence 0.3125 → 0.225
                              2 counterexamples closed, 2 newly opened
fresh set    K 2/8            mean divergence 0.0625
```

Better, not fixed — and the tool says so. The rewrite generalized to a probe set aimed
at it, and it still leaves two of the original eight splitting the panel.

## Layout

```
contracts/brightline_probe.py   the only consensus-critical code
contracts/brightline_registry.py  attestations: rule, probe set, K of N, tx hashes
contracts/gated_escrow.py       refuses to lock funds against an untested rule
prompts/adversary_v1.md         published adversary instructions (hash in every report)
agreements/                     rules under test, v1 and v2
probes/ps_*.json                frozen, content-addressed probe manifests
brightline/                     spec · adversary · chain · panel · report · diff · run
scripts/e*.py                   the approval gates, each writing raw evidence
experiments/                    raw gate output, kept
reports/                        generated reports + every raw receipt
frontend/                       the dApp (no build step; genlayer-js vendored)
frontend/lib/                   gl.js (genlayer-js clients) · receipt.js · attest.js
                                · hash.js (rule hashing, parity-tested vs Python) · render.js
frontend/components/            wallet.js · tx.js · ruleinput.js · quickcheck.js · settlement.js
frontend/assets/                logo.svg (source) · logo.png (rendered by scripts/render_logo.mjs)
scripts/build_static.py         assembles dist/ for a static host
tests/                          unit · direct (gltest) · frontend (node + Chromium + live)
docs/VERIFIED_VS_ASSUMED.md     every GenLayer claim and its status
docs/LIMITATIONS.md             what this does not measure
docs/RESULTS.md                 the numbers, with provenance
docs/DEPLOY.md                  building and hosting the dApp
docs/DEMO.md                    the six-minute walkthrough
```

## Deployments

Every number in this repo was produced by these contracts. Addresses are also carried
inside each report's provenance block, and the frontend reads them from
[`frontend/networks.json`](frontend/networks.json) rather than from anything hardcoded.

**studionet** — the network all measurements ran on, and the one the dApp uses by
default. `sim_config` model pinning is Studio-only, which is what makes the panel
channel possible at all.

| Contract | Address | Deploy tx |
|---|---|---|
| `BrightlineProbe` — adjudication | [`0x0cC3f4684fBd89dB74331A702d09a67DCc6585f7`](https://explorer-studio.genlayer.com/address/0x0cC3f4684fBd89dB74331A702d09a67DCc6585f7) | `0x5be58be403f7fbaf109bac948f92b1e54f91060b50291a20332e3269ee878b20` |
| `BrightlineRegistry` — published reports | [`0x8a3476D6c84cea489d4Eb9A0be744fe403560196`](https://explorer-studio.genlayer.com/address/0x8a3476D6c84cea489d4Eb9A0be744fe403560196) | `0x590ffb3035a72ece029c9de98150546078b1c86c27ca02073a6db68c391ebbdb` |
| `GatedEscrow` — the money gate | [`0x3826C2374fBDBcb8a248e0523eF1f325b3F5A590`](https://explorer-studio.genlayer.com/address/0x3826C2374fBDBcb8a248e0523eF1f325b3F5A590) | `0xb6662bbcf603f3f67e61b8a04b5d7122a1ec59d9e83c43021fadeffc9e0cf13f` |

`GatedEscrow` is constructed against that registry address, so the gate cannot be
pointed at a friendlier one after the fact.

**testnet-bradbury** — network truth only. `BrightlineProbe` is deployed at
`0xebd5A75F832985C3e3ddeFe2f60c7B7eA97C3880` (deploy tx
`0x4eb2ff08616a7aea853208b4532eaac1ef4085399f891e7d5f44355fb4e84b9c`), and E3/E4 both
pass there: a real transaction reached `Accepted`/`FinishedWithReturn` and validator
vote bytes were decoded off a live receipt. No registry or escrow is deployed there, and
the dApp keeps wallet writes **off** for Bradbury — genlayer-py needed an explicit gas
limit to land a write and genlayer-js is unverified on that network. Every *measurement*
in this repo is a studionet measurement; what Bradbury establishes is that the contract
path and the receipt reading are real on a public network.

Redeploying regenerates `frontend/networks.json`:

```bash
.venv/bin/python scripts/export_frontend_config.py
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

Publish a report and exercise the escrow gate, then view it:

```bash
.venv/bin/python -m brightline.publish reports/v1_ps_6ce467da9d20c1f2_studionet.json
.venv/bin/python scripts/e8_registry_escrow.py studionet
.venv/bin/python scripts/serve.py            # http://127.0.0.1:8800/frontend/
```

The dApp has four tabs, and they are one pipeline — fix what is being tested, adjudicate
it live, read the counterexamples, gate the money:

- **Reports** — the committed artifacts, counterexamples included.
- **Agreement** — paste a rule and see its on-chain identity hashed in the browser;
  browse a frozen probe manifest, its family quotas, and every scenario. Probe ids come
  from the manifest and are never recomputed in JS.
- **Quick check** — adjudicate one probe live, N times, against the network's own
  committee. A demonstration that real adjudication happens. **Not** a cross-model panel:
  genlayer-js ignores `simConfig`, so the browser cannot pin a model and the network
  chooses it. Cross-model divergence comes only from the CLI.
- **Settlement** — live registry and escrow reads, and with a wallet: publish a report,
  open a deal, set a tolerance, lock. Both refusal paths are one click each — lower the
  tolerance below the worst published finding, or pick the untested rule. Refusals show
  the contract's own message and leave the deal `OPEN`.

Reports and Agreement need no chain at all, and every registry and escrow read runs
without a wallet too. Read-only is the default state, not a degraded one: only the
buttons that sign are disabled, each with the reason stated.

genlayer-js is vendored into `frontend/vendor/` (`node scripts/vendor_sdk.mjs`) so the
dApp has no runtime CDN dependency; a dropped CDN sub-request used to kill the wallet
path outright.

Wallet writes are studionet-only for now. Bradbury is CLI-only until genlayer-js is
verified there; the UI states that rather than failing silently.

### Deploying it

```bash
.venv/bin/python scripts/build_static.py      # -> dist/, about 965K
npm run test:dist                             # builds it, serves only it, drives it
```

The dApp is static: no server, no API key, nothing to keep running. `dist/` mirrors the
repo layout so the deployed URLs match `serve.py`'s exactly and there is no rewrite
step. Any static host works over HTTPS — MetaMask will not inject a provider otherwise.
Details, host requirements and the excluded-files rationale in
[docs/DEPLOY.md](docs/DEPLOY.md).

### Tests

| | |
|---|---|
| `.venv/bin/python -m pytest tests/unit tests/direct -q` | 66 pass, 3 skip by design |
| `npm run test:all` | 136 JS checks, incl. 68 in a real Chromium against live studionet and a 9-check smoke test of the deployable bundle |
| `npm run test:live` | 34 live studionet checks through the JS stack, real transactions |

The browser suite covers read-only mode, the wallet RPC sequence against a mock
EIP-1193 provider, both escrow refusal paths, rule hashing, the WAI-ARIA tab model, and
a 390×844 phone viewport. What it cannot cover is real MetaMask and the real
`npm:genlayer-wallet-plugin` Snap — those need a human to approve an install prompt.
That flow has been walked manually and works; the automated evidence for it is the RPC
sequence the suite prints.

Bradbury (network truth, `scripts/e3_e4_bradbury.py`) needs a funded account; the
faucet requires GitHub OAuth plus a Turnstile challenge, so that step is human.

## What the escrow gates on

Not a Split Score. The E6 calibration study failed its matched-pair criterion, so the
score is scoped to a studionet lab instrument and is never a production gating input.
`GatedEscrow.lock()` checks exactly two things: that a report exists for the rule at
all, and that the **worst** published counterexample count is within a tolerance the
payer fixed before opening the deal. `worst_counterexamples` takes the maximum across
competing reports, so publishing until a flattering run appears buys nothing — and a
counterparty can publish their own adversary's findings against the same rule.

The tolerance is fixed by `open_deal` and there is no setter. A refused lock leaves the
deal `OPEN`, but recovering from it means opening a *new* deal at a higher tolerance,
not editing the old one: a payer who could raise the bar after seeing the findings would
not be committing to anything. The dApp guides that second deal rather than offering a
retry that would only be refused again.

## Honesty notes

Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md) before quoting any number. In short:
decidability is not fairness; the score is a property of the probe set and adversary,
not of a sentence; and every result here is a studionet result until the Bradbury arm
runs. GenLayer's own `gltest` already ships `.analyze()` for contract-level
consistency — Brightline points that idea outward, at rule level, with a real
validator draw, adversarial probes, counterexamples, and a citable artifact.
