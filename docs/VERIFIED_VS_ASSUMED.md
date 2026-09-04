# Verified vs. assumed

Every GenLayer-specific claim Brightline depends on, and its current status.
Updated as gates run. `[V]` verified in current official docs, `[E]` verified
empirically here, `[A]` still an assumption, `[X]` refuted.

## Contract surface

| Claim | Status | Evidence |
|---|---|---|
| Python contracts extend `gl.Contract`; storage is class-level annotations | `[V]` `[E]` | docs *Your First Contract*; contract deploys and stores |
| `TreeMap[K,V]`, `DynArray[T]`, `u8`/`u256`, `Address`, `@allow_storage @dataclass` | `[V]` `[E]` | docs *Contract Storage*; `genvm-lint validate` reports 9 methods / 6 view / 3 write |
| Calldata mappings support **`str` keys only** | `[V]` | docs *Contract Storage* |
| `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)` | `[V]` `[E]` | docs *Equivalence Principle*; used in `adjudicate` |
| Validator agreement for a raw `RunNondet` block is whatever `validator_fn` returns | `[V]` | GenVM impl-spec *Consensus Mechanics* |
| Compare decision fields only, ignore reasoning text | `[V]` `[E]` | docs *Pattern 1: Partial Field Matching* |
| `gl.nondet.exec_prompt(prompt, response_format="json")` | `[V]` `[E]` | docs *Prompt & Data Techniques* |
| `gl.message_raw["datetime"]`, tx-pinned deterministic clock | `[V]` `[E]` | docs *Transaction Context* |
| One nondet block per tx; `call_no` binds leader's i-th result to validator's i-th check | `[V]` | GenVM impl-spec |
| Runner must be pinned; `:latest` / `:test` rejected on all networks | `[V]` | `genlayer-dev:write-contract`; linter warns a newer runner exists |

## Consensus and receipts

| Claim | Status | Evidence |
|---|---|---|
| Leader proposes, validators recompute, majority accepts, appeals escalate | `[V]` | docs *Optimistic Democracy* |
| A split adjudication **writes no state** | `[E]` | E1: 3–2 split → `UNDETERMINED` / `MAJORITY_DISAGREE`, `get_ruling` returned `{}` |
| A validator's own answer is **never published**; only its vote | `[V]` `[E]` | impl-spec; E1 receipt showed all five `result` fields carrying the *leader's* value |
| Studionet receipt exposes `consensus_data.votes` (address → agree/disagree) | `[E]` | E1 receipt |
| Studionet receipt exposes per-validator `node_config.primary_model.model` | `[E]` | E1 receipt: gemini-3-flash, kimi, gemma, gpt-5-4, glm |
| Bradbury receipt exposes `roundData[]` with `roundValidators`, `validatorVotes`, `validatorVotesHash`, `validatorResultHash` | `[V]` `[E]` | docs `gen_getTransactionReceipt`; confirmed present on a live Bradbury query |
| `txExecutionResult == 4` is `NondetDisagree` | `[V]` | docs `gen_getTransactionReceipt` |
| `validatorVotes` is one byte per validator, aligned to `roundValidators`, values from the vote enum | `[A]` | Inferred from the documented example (5 validators, 5 entries, `"AAAAAAA="` → five zero bytes, `votesRevealed: 0`, `0 == NotVoted`). **E4 tests this. Blocked on funding.** Fallback recorded in `scripts/e3_e4_bradbury.py` |
| `Undetermined` is the rotation-exhaustion state, not the first sign of a split | `[V]` `[E]` | docs status table; E1 rotated 3 times before landing there |
| `consensus_max_rotations` is settable per transaction | `[V]` `[E]` | `genlayer-py` signature; used with `rotations=0` |

## Panel channel (the instrument)

| Claim | Status | Evidence |
|---|---|---|
| `sim_config` can pin per-validator `provider` / `model` / `config{temperature}` | `[V]` `[E]` | `SimValidatorConfig`; six models pinned successfully |
| Studionet exposes 63 provider/model combos incl. frontier models | `[E]` | `sim_getProvidersAndModels` |
| `leader_only=True` + one pinned validator yields that model's decision | `[E]` | E2a: 6/7 models returned a decision |
| A single-validator run also yields **within-model self-consistency for free** — the leader runs the validator path and votes on its own re-sampled answer | `[V]` `[E]` | docs *Transaction Execution* ("It also executes the validator path"); one vote observed per run |
| Contract must return the full result object, not just a decision | `[E]` | Split runs store nothing, so the receipt has to be self-sufficient |

## RPC and environment

| Claim | Status | Evidence |
|---|---|---|
| Bradbury RPC `https://rpc-bradbury.genlayer.com`, chain id 4221 | `[V]` `[E]` | docs *Networks*; `eth_chainId` → `0x107d` |
| Studionet RPC `https://studio.genlayer.com/api`, chain id 61999 | `[V]` `[E]` | docs *Networks*; `eth_chainId` → `0xf22f` |
| Public Bradbury RPC 403s the default `python-requests` User-Agent (Cloudflare) | `[E]` | Any explicit UA passes; this masquerades as "method not found" across every `gen_*` call |
| `gen_call` accepts `leader_results` and returns `nondetDisagreementCallNo` | `[V]` on the node API, `[X]` on Studionet | Studionet `gen_call` returns **no `eqOutputs`** and no such field, so validator-mode replay is unusable there. E2b therefore FAILED on studionet by design, not by bug |
| `gen_getTransactionLifecycle` | `[X]` on Bradbury | documented, but the node answers `-32601 method not found` |
| Bradbury faucet is automatable | `[X]` | `/api/claim` requires GitHub OAuth **and** Cloudflare Turnstile |
| Local Studio available | `[X]` | no Docker on this host; Studionet used instead |
| EVM / ghost-contract path testable in Studio | `[X]` | docs: "`@gl.evm.contract_interface` calls are not functional in Studio" — correctly out of scope |

## Gate status

| Gate | Result |
|---|---|
| **E1** contract deploys, registers, adjudicates | **PASS** — and the first adjudication produced a real 3–2 split |
| **E2a** panel channel yields per-model decisions | **PASS** — 6 usable observations, self-split rate 0.0 |
| **E2b** `gen_call` validator-mode replay | **FAIL on studionet** (RPC shape lacks `eqOutputs`); untested on Bradbury pending funding. Superseded by E2a, which is higher-resolution |
| **E3** real Bradbury transaction | **BLOCKED** on faucet funding (human step) |
| **E4** `validatorVotes` decode | **BLOCKED** on E3. Inference not assumed anywhere in the analyzer; fallback implemented |
| **E5** frozen probe reuse across rule versions | **PASS** — V2 measured against V1's probe ids |
| **E6** calibration study | not started |
| **E7** rewrite reduces counterexamples | in progress (V2 frozen + fresh arms) |

## genlayer-py 0.16.3 vs. Bradbury (found while running E3)

| Behaviour | Status | Detail |
|---|---|---|
| `client.read_contract` on Bradbury | `[X]` broken | Node API returns `gen_call` `result` as the documented **object** (`data`, `eqOutputs`, `status`, …); the SDK does `"0x" + enc_result` and raises `TypeError`. Studio-era endpoints return a hex string. Fixed in `Chain.read`, which builds the request with the SDK's own RLP helpers and normalizes both response shapes |
| `client.get_transaction` / `wait_for_transaction_receipt` on Bradbury | `[X]` broken | Bradbury reports transaction **status 14**, which is absent from the SDK's `TRANSACTION_STATUS_NUMBER_TO_NAME` (docs describe 14 values, 0–13). Raises `KeyError: '14'`. Workaround: poll `gen_getTransactionStatus` and fetch `gen_getTransactionReceipt` over raw RPC |
| `client.write_contract` on Bradbury | `[X]` reverts | The EVM-layer transaction to the consensus contract reverts (`tx_receipt.status != 1`). `_prepare_transaction` attaches only EVM gas (`maxFeePerGas`/`maxPriorityFeePerGas`) and 0.16.3 exposes no `fees` argument, so no GenLayer consensus fee deposit is sent. genlayer-js does (`fees: {distribution, feeValue}`), and the CLI exposes `estimate-fees` + `write --fees/--fee-value`. Deploys succeed; writes do not |
| Bradbury deploy + view reads | `[E]` working | `BrightlineProbe` deployed at `0xebd5A75F832985C3e3ddeFe2f60c7B7eA97C3880`; `ruling_count` and `get_rule` read correctly through the fixed path |
