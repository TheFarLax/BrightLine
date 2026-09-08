# Limitations

Written before the results, kept honest after them.

## Decidability is not fairness

Brightline measures whether a resolution rule produces a stable decision when
independent models apply it to hard facts. It says nothing about whether the deal is
good. *"Contributor forfeits all payment for any deviation"* would score close to
perfect. `agreements/bounty_working_fix_v2.yaml` is deliberately harsher than v1 in
places, because tightening a rule for decidability and improving it for the
contributor are different projects. If anyone ever cites a Brightline report as a
trust badge, that is a misuse.

## What the Split Score is not

- **Not a probability of dispute.** A study of UMA-resolved Polymarket markets
  covering roughly $1B of disputed volume found rule-text quality to be a
  near-chance predictor of whether a market was actually disputed; the authors
  attribute disputes mainly to evolving facts, conflicting reports and slow
  confirmation. We do not claim to predict disputes. We probe the procedure those
  findings point at.
- **Not a prediction of human litigation.** There is published evidence that LLMs
  reproduce human annotator disagreement poorly. Brightline predicts what
  *GenLayer's* panel does, which is the adjudicator that matters here, and nothing
  about a court.
- **Not a property of a sentence.** It is a property of
  `(rule, probe set, adversary version, model panel, network, contract, runner,
  epoch)`. Every report carries that tuple and two reports are only comparable when
  it matches. `brightline.diff` refuses to compare quietly and prints the mismatch.

## The adversary is part of the measurement

A stronger adversary finds more counterexamples in the same rule. So "4 of 8 split"
means *adversary v1 found four counterexamples in eight attempts*, not "this rule is
50% undecidable". Three consequences:

1. The adversary prompt is published (`prompts/adversary_v1.md`) and its hash is in
   every manifest and report.
2. Probe sets are content-addressed and immutable; `ProbeSet.load` refuses a manifest
   whose contents no longer hash to its stated id.
3. The re-test loop always runs a **fresh** probe set alongside the frozen one.
   Without that arm, a rule can be tuned to pass a corpus it has already seen and
   the number becomes theatre.

## Panel composition is a choice, and it is visible

Six models, all reached through one gateway on one network. `x-ai/grok-4` is
excluded because on studionet it returns `CANCELED` / `NO_MAJORITY` with no leader
receipt, costing minutes per probe and contributing no observation — recorded in
`PANEL_EXCLUDED` rather than silently dropped. A different panel will produce
different numbers. The panel list is in every report.

## Measurement channels and what each cannot see

- **PANEL** (`leader_only` + one pinned model) gives the decision distribution but
  is not a settlement path. It is an instrument, not the protocol.
- **CONSENSUS** (a real round) is what settlement uses, but a validator's own answer
  is never published — only its vote. A split therefore tells you the jury divided
  and not into what, and stores no state at all.
- **LIVE** on Bradbury is the only network-truth arm. It has since run
  (`scripts/e3_e4_bradbury.py`, E3/E4 both PASS): a real transaction reached
  `Accepted` / `FinishedWithReturn`, and validator vote bytes were decoded off a live
  receipt. But it yields **votes, not decisions** — `sim_config` is Studio-only, so the
  panel channel cannot run there at all. Every *measurement* in this repo is therefore
  still a studionet measurement; what Bradbury establishes is that the contract path
  and the receipt reading are real on a public network, not that the numbers transfer.
  In the E6 transfer arm the live committee was unanimous on all five measurable
  domains, so transfer is **unevaluated rather than demonstrated**.

## An assumption that was resolved, and how

`roundData[].validatorVotes` is base64 whose layout is not documented. We inferred one
byte per validator, positionally aligned to `roundValidators`, using the documented
vote enum. E4 confirmed it against real revealed votes on Bradbury — five bytes for
five validators, every byte in the enum, and two independent vectors including a
non-uniform one (`[1,1,1,1,3]`, one Timeout), so the decode resolves real vectors and
not just zero padding. The fallback (transaction-level `NondetDisagree` as a 1-bit
signal plus distinct-`validatorResultHash` cardinality) stays implemented but is no
longer load-bearing.

A second Bradbury reading was wrong and is worth recording: `roundData[0]` is *not*
the round to read. Bradbury appends several entries all labelled `round: 0`, and the
pre-reveal entry has all-zero vote bytes — it would read as "nobody disagreed". The
analyzer takes the last entry with `votesRevealed > 0`.

## Not built on purpose

No EVM/ghost-contract path (`@gl.evm.contract_interface` is non-functional in
Studio). No live-web probes — probes are hermetic so that divergence cannot be
caused by two validators fetching different pages. No token, no governance, no
appeals UI, no on-chain scoring. The score is computed off-chain from public
receipts precisely so anyone can recompute it from the transaction hashes in the
report.

## The falsification condition was tested, and it bit

The pre-registered condition: if a calibration study cannot show that cross-model
divergence separates loose rules from tightened controls better than chance, the score
gets dropped and the counterexample generator ships alone.

E6 ran, and **the study does not pass** (`experiments/E6_calibration/final.json`, full
write-up in [RESULTS.md](RESULTS.md)). C3 — the matched-pair criterion, the one that
would license "this draft is clearer than that draft" — failed at 3 of 6 pairs
directional, Wilcoxon p = 0.844. The pre-registration permits one disclosed corpus
revision before a re-run; it had already been spent, so the pair corpus does **not**
get rewritten and retried, even though the length confound is an obvious candidate fix
and a re-run would probably look better.

So the branch fired as written:

- **Split Score is not validated for ranking two drafts of the same clause.**
  Brightline must not be presented as a tool that tells you which rewrite is better.
- It **is** supported as a discriminator between forced-answer rules and
  judgment-requiring rules: controls 0.0333 against loose 0.2167 and pathological
  0.2333, AUC 0.787 with a bootstrap CI excluding chance.
- The mechanical floor is empirically zero: repetition 0.0, paraphrase 0.0, 323
  self-consistency observations without one failure.
- The score is labelled a **studionet lab instrument** wherever it appears, and it is
  never a gating input. `GatedEscrow.lock()` reads report existence and the worst
  published counterexample count, and nothing else.
- The counterexample generator was unaffected by every branch above and ships
  regardless. It never depended on the score being calibrated.

## What the dApp cannot do

- **It cannot run the panel.** genlayer-js 1.1.8 has no `simConfig` on `writeContract`
  and passing one is silently ignored — verified by requesting three specific models
  and getting three others. The browser cannot pin a validator model, so cross-model
  divergence is CLI-only. The Quick check tab measures run-to-run stability of the live
  committee and says so on screen.
- **Settlement records entitlement; it does not move value.** External messages are
  finalization-only and non-functional in Studio, so a payout that cannot execute here
  would be theatre.
- **Wallet writes are studionet-only.** genlayer-py needed an explicit gas limit to
  land a write on Bradbury and genlayer-js is unverified there, so `wallet_writes` is
  false for it and the header states the reason instead of failing at signing time.
- **Studionet rate-limits browser reads under load**, returning a response with no
  CORS header. Reads retry with backoff and an unreadable publication check renders as
  unknown rather than as "not published" — claiming the latter would invite a duplicate
  publish the contract would refuse.
