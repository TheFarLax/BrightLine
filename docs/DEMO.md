# Six-minute demo

One claim, proved on screen: **the network that will judge your agreement can tell you
today where it will disagree with itself — and refuse to release money until you fix
it.**

Everything below runs on the deployed dApp against live studionet. Nothing is mocked.

## Before you start

```bash
.venv/bin/python scripts/build_static.py --serve 8899     # or open the deployed URL
```

- MetaMask installed, `npm:genlayer-wallet-plugin` Snap already approved, account
  funded on studionet. Approving the Snap for the first time costs 30 seconds you do
  not have.
- The v1 report already published to the registry
  (`.venv/bin/python -m brightline.publish reports/v1_ps_6ce467da9d20c1f2_studionet.json`).
  Publishing is a write like any other; it is just not the interesting one.
- Reports tab open on **v1 · 4/8 counterexamples**, theme set, wallet connected.
- Second window on `reports/raw/` or the explorer, in case someone asks to see a
  receipt.

Timings that matter: a `lock` lands in about **10 seconds**; a live quick-check
adjudication takes roughly **20–60 seconds** on studionet. The full panel run is
**15 minutes to nearly two hours** — never demo it, cite it.

---

## 0:00 — 0:40 · The problem, in one sentence

> "This is a bounty agreement. One sentence: *pay the contributor if the contributor
> delivers a working fix.* Everyone reads that and thinks it is obvious."

Read the rule off the **Agreement** tab so it is on screen, not just in the air.

> "It is not obvious. And the way you find that out today is a dispute."

## 0:40 — 2:00 · The counterexample

Reports tab. Scroll to the first counterexample card. Read the scenario aloud:

> *"The contributor submitted a change that closes the reported defect. After the
> change was merged, a defect that had been closed five weeks earlier began reproducing
> again in the same module."*

Then the camps, straight off the card:

- **ACCEPT** — gpt-5.1, qwen3-235b
- **INSUFFICIENT** — deepseek-v3.2, kimi-k2.5
- **REJECT** — claude-sonnet-4.5, gemini-3-flash

> "Six frontier models, all confident, three different answers. Nobody is
> malfunctioning. The rule never said whether collateral breakage counts."

Point at the tiles: **4 of 8 probes split**, **noise floor 0.0**. Then the part that
makes it an instrument rather than a vibe:

> "Noise floor zero means every model reproduced its own answer when asked again. And
> four of the eight probes came back unanimous. So the tool discriminates *within* the
> same rule and the same probe set — it is not just declaring everything ambiguous."

## 2:00 — 2:45 · Why this has to be GenLayer

> "You could ask a private model whether your contract looks clear. That model is not
> the one that will decide your case, so its answer binds nobody and your counterparty
> has no reason to accept it."
>
> "Here the validator network **is** the adjudication mechanism. This is the future
> judge, giving its opinion before money is at risk, with every transaction hash
> published so anyone can recompute it."

One protocol fact, because it shaped the whole design:

> "A split adjudication writes no state — the transaction rotates leaders and ends
> `UNDETERMINED`. The interesting cases store nothing. So the contract returns its full
> result object and Brightline reads the receipts. Every number you just saw came from
> 48 real transactions."

## 2:45 — 3:30 · It is running now, not recorded

**Quick check** tab. Pick a probe, press Run. Start it, then keep talking — do not
watch the spinner.

> "That is a real adjudication being submitted right now, to the live committee. Watch
> the transaction go from submitting, to a hash, to finalized, with the model that
> actually answered named on the receipt."

Say the limitation before anyone asks:

> "This one is deliberately *not* the panel. genlayer-js can't pin a validator model,
> so the network picks. That means the browser measures run-to-run stability, and
> cross-model divergence only comes from the CLI. The UI says exactly that."

## 3:30 — 5:00 · The money gate

**Settlement** tab. This is the demo's centre of gravity.

1. Rule is v1. Registry reads live: **tested: yes · worst counterexamples: 4**.
   > "Worst-of, not latest-of. A rule is as bad as its most successful attacker made it
   > look, so publishing until a flattering run appears buys you nothing — and your
   > counterparty can publish their own adversary's findings against the same rule."
2. Set tolerance to **3**. The preview flips to *Expected refusal*.
3. **Open deal**, then **Lock 0.01 GEN**. Let it come back refused.
   > "That is the contract's own message, on chain: *rule has 4 counterexamples, deal
   > tolerates 3.* And notice the deal is still **OPEN** — the gate declined the state
   > transition, not the call. Nothing is stuck."
4. Raise tolerance to **4**. **Lock** again. It locks.
   > "Same rule, same evidence, different informed decision. The payer accepted four
   > known counterexamples, and the registry summary they relied on is frozen into the
   > deal so a later report can't rewrite what they agreed to."
5. If time allows, switch the rule selector to *(untested rule)* and lock once more:
   > "The other refusal: *no published Brightline report — run the probes and publish
   > before locking funds.*"

## 5:00 — 5:40 · The loop closes

Back to **Reports**, the re-test table.

> "Findings are only useful if rewriting the rule moves them. v2 was written against
> those counterexamples and re-measured two ways: the same frozen probe ids, and a
> fresh set aimed at the new rule."
>
> "Frozen: mean divergence 0.31 down to 0.22, two counterexamples closed — and two new
> ones opened. Fresh: 2 of 8. Better, not fixed. The fresh arm is not optional: without
> it you can tune a rule to pass a corpus it has already seen and the number becomes
> theatre."

## 5:40 — 6:00 · Close on the honest line

> "What this is not: it is not a probability of dispute, not a prediction of how a court
> would rule, and decidability is not fairness — a rule can be trivial to adjudicate and
> still be one-sided. We ran a calibration study to see whether the divergence number
> could rank two drafts of the same clause. **It failed.** So that score is scoped to a
> lab instrument and it is not what the escrow gates on."
>
> "The escrow gates on two things only: does a report exist, and is the worst finding
> inside the tolerance you fixed in advance."
>
> "The product isn't the score. It's the sentence: *here is the case where you don't get
> paid.*"

---

## Questions you will get

**"Isn't this just asking an LLM if my contract is clear?"** — No, twice. The panel is
six different frontier models, pinned one per transaction, so the disagreement is
between models rather than inside one. And it is the same network that will adjudicate
the real claim, so the answer binds something.

**"How do I know the models weren't just random?"** — Noise floor. Every panel run makes
the leader execute the validator path too, so it re-samples and votes on its own answer.
It is 0.0 across the reported runs: every model reproduced itself. The disagreement is
between models, not within them.

**"Could I game it by publishing a good report?"** — `worst_counterexamples` takes the
maximum across every published report for the rule, and anyone may publish. A flattering
run does not lower the worst.

**"Does the escrow actually pay out?"** — No, and it says so. Settlement records the
entitled party; it does not move value. External messages are finalization-only and
non-functional in Studio, so a payout that cannot run here would be theatre.

**"Why studionet and not a public testnet?"** — Model pinning (`sim_config`) is
Studio-only, and it is what makes the panel channel possible at all. The contract path
itself is verified on Bradbury: a real transaction, and the validator vote bytes
decoded off a live receipt. Wallet writes stay off for Bradbury in the UI until
genlayer-js is verified there, and the header states that rather than failing at
signing time.

**"What's the biggest limitation?"** — [docs/LIMITATIONS.md](LIMITATIONS.md). The
headline one: the score is a property of the probe set and the adversary, not of a
sentence, so two reports are only comparable when the provenance block matches. That is
why every report carries one.

## If something breaks live

- **A read shows `…` or an error** — studionet rate-limits browser reads under load. The
  app retries and states the failure; press **Refresh from chain**. Do not wait in
  silence, narrate it: transport, not consensus.
- **A quick-check transaction hangs** — move on and come back. `LeaderTimeout` is not
  terminal; the transaction can still finalize.
- **The wallet does not connect** — the whole read path works with no wallet at all.
  Reports, hashing, probes and every registry read still run. Say so and keep going;
  read-only is the default state, not a fallback.
