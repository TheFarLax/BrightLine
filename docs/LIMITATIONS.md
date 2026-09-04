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
- **LIVE** on Bradbury is the only network-truth arm, and it is currently
  **unmeasured**: the faucet requires GitHub OAuth plus a Cloudflare Turnstile
  challenge, so funding is a human step. Every claim in this repo is therefore a
  studionet claim until `scripts/e3_e4_bradbury.py` runs green.

## Known unresolved assumption

`roundData[].validatorVotes` is base64 whose layout is not documented. We infer one
byte per validator, positionally aligned to `roundValidators`, using the documented
vote enum where `4 == NondetDisagree`. **Nothing in the analyzer depends on this
yet.** E4 tests it; the fallback (transaction-level `NondetDisagree` as a 1-bit
signal plus distinct-`validatorResultHash` cardinality) is implemented.

## Not built on purpose

No EVM/ghost-contract path (`@gl.evm.contract_interface` is non-functional in
Studio). No live-web probes — probes are hermetic so that divergence cannot be
caused by two validators fetching different pages. No token, no governance, no
appeals UI, no on-chain scoring. The score is computed off-chain from public
receipts precisely so anyone can recompute it from the transaction hashes in the
report.

## The falsification condition still stands

If a calibration study cannot show that cross-model divergence separates loose rules
from tightened controls better than chance, the score gets dropped and the
counterexample generator ships alone. The current evidence is encouraging — noise
floor 0.0 against mean divergence 0.3125 on the v1 run — but one rule and eight
probes is not a study.
