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
| `validatorVotes` is one byte per validator, aligned to `roundValidators`, values from the vote enum | `[E]` **confirmed** | E4 on Bradbury: `votes_revealed: 5`, `byte_count: 5`, `n_validators: 5`, aligned, every byte in the enum. Two independent vectors seen — `[1,1,1,1,1]` (unanimous, 1 distinct result hash) and `[1,1,1,1,3]` (one Timeout, 2 distinct hashes) — so the decode resolves non-uniform vectors, not just zero padding |
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
| **E3** real Bradbury transaction | **PASS** — `adjudicate` with `rotations=0` reached `Accepted` / `FinishedWithReturn` in 34.7s; decision recovered from `debug_trace_transaction` `return_data` |
| **E4** `validatorVotes` decode | **PASS** — inference confirmed on real revealed votes (see above); the fallback path stays implemented but is no longer load-bearing |
| **E5** frozen probe reuse across rule versions | **PASS** — V2 measured against V1's probe ids |
| **E6** calibration study | **DOES NOT PASS** — C1/C2/C4 pass, C3 fails, C5 not evaluable as written (A1 unmeasurable), C6 fails. Branches applied in `experiments/E6_calibration/final.json` |
| **E8** registry → report → escrow | **PASS** on studionet — report published and read back, gate allows a compliant deal and refuses both a below-tolerance deal and an untested rule, deal stays `OPEN` on refusal |
| **E7** rewrite reduces counterexamples | **MIXED, and reported as such** — `reports/retest.json`. Frozen arm: K unchanged at 4/8, mean divergence 0.3125 → 0.225, 2 counterexamples closed and 2 newly opened, inconclusive 0.0 → 0.0833. Fresh arm (`ps_4a8062c5562c47a4`, written against v2): 2/8, mean 0.0625. The rewrite generalized; it did not eliminate the frozen counterexamples, and the honest headline is "fewer, not gone" |

## genlayer-py 0.16.3 vs. Bradbury (found while running E3)

| Behaviour | Status | Detail |
|---|---|---|
| `client.read_contract` on Bradbury | `[X]` broken | Node API returns `gen_call` `result` as the documented **object** (`data`, `eqOutputs`, `status`, …); the SDK does `"0x" + enc_result` and raises `TypeError`. Studio-era endpoints return a hex string. Fixed in `Chain.read`, which builds the request with the SDK's own RLP helpers and normalizes both response shapes |
| `client.get_transaction` / `wait_for_transaction_receipt` on Bradbury | `[X]` broken | Bradbury reports transaction **status 14**, which is absent from the SDK's `TRANSACTION_STATUS_NUMBER_TO_NAME` (docs describe 14 values, 0–13). Raises `KeyError: '14'`. Workaround: poll `gen_getTransactionStatus` and fetch `gen_getTransactionReceipt` over raw RPC |
| `client.write_contract` on Bradbury | `[X]` broken, worked around | The EVM-layer transaction to the consensus contract reverts (`tx_receipt.status != 1`). `_prepare_transaction` attaches only EVM gas (`maxFeePerGas`/`maxPriorityFeePerGas`) and 0.16.3 exposes no `fees` argument, so no GenLayer consensus fee deposit is sent. genlayer-js does (`fees: {distribution, feeValue}`), and the CLI exposes `estimate-fees` + `write --fees/--fee-value`. Root cause is **gas, not fees**: `_prepare_transaction` assigns `gas` straight from `eth_estimateGas` and the submission reverts, while the identical calldata sent with headroom succeeds (~912k used against a ~964k estimate). Fee accounting is reported `null` on Bradbury, so the payable deposit is irrelevant there. `NodeWriteMixin._node_write` encodes with the SDK's helpers, submits with 1.6× headroom, recovers the tx id from the `NewTransaction` event, and polls over raw RPC |
| Bradbury deploy + view reads | `[E]` working | `BrightlineProbe` deployed at `0xebd5A75F832985C3e3ddeFe2f60c7B7eA97C3880`; `ruling_count` and `get_rule` read correctly through the fixed path |

## Further Bradbury findings (E3/E4)

| Claim | Status | Evidence |
|---|---|---|
| `LeaderTimeout` / `ValidatorsTimeout` are terminal | `[X]` refuted | A transaction observed at `LeaderTimeout` went on to `Finalized` with `FinishedWithReturn`. Both statuses leave the appeal window open, so treating them as terminal reports a false failure. `TERMINAL_STATUSES` now excludes them |
| `roundData[0]` is the round to read | `[X]` refuted | Bradbury appends several entries all labelled `round: 0`, one per attempt. The pre-reveal entry has all-zero vote bytes (`NotVoted`) and would read as "nobody disagreed". Use the last entry with `votesRevealed > 0` |
| Fee accounting is active on Bradbury | `[X]` refuted | `gen_getTransactionReceipt.fees` is `null`, which the docs define as fee accounting disabled or FeeManager unavailable. A zero deposit on the payable `addTransaction` is accepted |
| `debug_trace_transaction` works on Bradbury and carries the return value | `[E]` | Returns `eq_outputs`, `return_data`, `stdout`, `stderr`, `genvm_log`, `result_code`. `return_data` calldata-decodes to the contract's full result object |
| `gen_call` with `leader_results` on Bradbury | `[A]` untested | Now reachable (the 403 was the User-Agent), but unnecessary: the PANEL channel supersedes it and `sim_config` is Studio-only anyway |

## Contract-level reverts (found while running E8)

| Claim | Status | Evidence |
|---|---|---|
| A reverted contract call shows up as a failed transaction | `[X]` refuted | A `gl.vm.UserError` still yields `ACCEPTED` / `MAJORITY_AGREE` — the validators agree the call failed. The signal is on the leader receipt: `execution_result == "ERROR"` with `result.status == "rollback"`, and `result.payload` carries the UserError text verbatim. `execution_failed()` / `revert_message()` in `brightline/panel.py` |
| Direct mode can test two interacting contracts | `[X]` refuted | `ImportError: only one contract is allowed`. Cross-contract gate tests skip by design; the gate is verified against real consensus by `scripts/e8_registry_escrow.py` |
| `sim_config` works on a public testnet | `[X]` | Studio-only. The PANEL channel cannot run on Bradbury, which is why the LIVE arm yields votes rather than a decision distribution — and why C6 had nothing to correlate |

## Frontend / genlayer-js (steps 0-4)

| Claim | Status | Evidence |
|---|---|---|
| genlayer-js supports an account-free read client and a provider-backed write client | `[V]` `[E]` | docs *genlayer-js*; `ClientConfig { account?, provider? }` in 1.1.8; live `ruling_count` read in a real Chromium with no wallet present |
| Wallet signing requires MetaMask **plus the `npm:genlayer-wallet-plugin` Snap** | `[V]` `[E]` | `client.connect()` emits `eth_requestAccounts` → `eth_chainId` → `wallet_getSnaps` → `wallet_requestSnaps`, recorded automatically against a mock EIP-1193 provider (`tests/frontend/browser_test.mjs` case B prints the sequence). The real MetaMask + Snap install/approval/signing flow was walked **manually by the maintainer** on studionet and works; it cannot be automated here (no browser extension or display on this host), so the automated evidence stops at the RPC sequence |
| `wallet_addEthereumChain` / `wallet_switchEthereumChain` are issued by `connect()` | `[V]` in the bundle, `[A]` in practice | Both strings are present in genlayer-js 1.1.8, but neither fired in testing because the mock returned a matching `eth_chainId`. The switch path is unexercised |
| genlayer-js `readContract` works against studionet | `[E]` | `is_tested`, `worst_counterexamples`, `summary_for_rule`, `get_deal`, `ruling_count` all read correctly |
| genlayer-js `writeContract` works against studionet, including payable value | `[E]` | 22/22 live settlement checks: publish, open_deal, lock (0.01 GEN), release |
| genlayer-js `writeContract` works against Bradbury | `[A]` **untested** | genlayer-py needed an explicit gas limit there; `wallet_writes` stays false for Bradbury and the UI says why |
| A contract revert is invisible in the transaction status via genlayer-js too | `[E]` | Both a refused `lock` and a duplicate `publish` came back `FINALIZED` / `MAJORITY_AGREE` with `execution_result: ERROR`, `result.status: "rollback"`, and the `UserError` text in `result.payload` |
| The JS and Python attestation projections agree | `[E]` | `tests/unit/test_js_parity.py` — byte-identical across all three committed reports, including Python's `", "` list separator in `tx_hashes_json` |

## Steps 5-6 findings

| Claim | Status | Evidence |
|---|---|---|
| genlayer-js can pin validator models via `simConfig` | `[X]` **refuted** | `writeContract` has no `simConfig` parameter in 1.1.8 and the string appears nowhere in the bundle. Passing one is silently ignored: requesting kimi / gemini-3-flash / qwen produced grok / gemini / gpt-5.4. **The browser therefore cannot reproduce the PANEL channel at all** — cross-model pinning is CLI-only, because genlayer-py forwards `sim_config` as a second `eth_sendRawTransaction` param |
| A browser quick check can measure cross-model divergence | `[X]` refuted, by the above | What it measures instead is run-to-run stability of the live committee. Labelled as such in the UI, and it is not a Split Score |
| The receipt names which model actually answered | `[E]` | `consensus_data.leader_receipt.node_config.primary_model.model`. Live runs showed `openai/gpt-5.4`, `policy:prd-minimax`, `policy:prd-sonnet`, `policy:prd-gpt-5-4` — the network's own choices |
| Loading genlayer-js from a CDN is safe for a demo | `[X]` refuted | Its published ESM imports `viem` as a bare specifier, so a CDN load fans out into dozens of requests. esm.sh closed one mid-fetch during testing and the wallet path died. Now vendored into `frontend/vendor/` by `scripts/vendor_sdk.mjs` |
| The SDK and its chains can be bundled separately | `[X]` refuted | Two bundles means two copies of viem, and a chain object from one is not what the other expects — the client silently fails to reach the network. One entry re-exporting both |
| Studionet answers every browser read | `[X]` refuted | Under load it intermittently returns a rate-limited response with no `Access-Control-Allow-Origin`, which the browser reports as CORS. Reads now retry with backoff, and an unreadable publication check renders as unknown rather than as "not published" |
| Browser rule hashing matches the CLI | `[E]` | `tests/frontend/hash_parity.mjs` — 20 awkward strings (NBSP, combining marks, ligatures, fullwidth, CJK, emoji, smart quotes), both committed agreements, and the hash inside the published v1 report |
| Probe ids can be recomputed in JS | `[A]` **deliberately not attempted** | Python's canonical JSON and `JSON.stringify` disagree on key ordering and escaping. Ids are read from the content-addressed manifest, which refuses to load if edited |

## Studio Next, chain 61997 (the migration)

Full write-up, with the diagnosis behind each row: [STUDIO_NEXT.md](STUDIO_NEXT.md).

| Claim | Status | Evidence |
|---|---|---|
| "Studio Next" is a real network at chain 61997 | `[E]` | `eth_chainId` → `0xf22d` on both `studio-next.genlayer.com/api` and `studio-dev.genlayer.com/api`; `ping` → `OK`; `sim_getProvidersAndModels` and `eth_blockNumber` both answer |
| Those two hostnames are one chain, not two | `[E]` | One `sim_fundAccount` call, then the same balance (`0x56bc75e2d63100000`) read back from both hosts for the same address |
| The 61999 addresses can be reused on 61997 | `[X]` **refuted** | Separate chain, separate state. `get_balance` on the deploy account was 0 there, and the old contract addresses hold no code. All three redeployed |
| genlayer-py 0.16.3 can transact on 61997 | `[X]` **refuted** | It encodes the flat six-arg `addTransaction`; 61997's consensus contract takes one packed tuple plus `deploySalted`. Different selector → EVM revert with no reason string. Fixed by 0.19.0rc2 |
| A v0.6 transaction can omit fees | `[X]` **refuted** | `FeesDistributionMissing` on deploy, then `FeeValueMustBeNonZero(1)` from the JS path. Fee policy is `enabled: true`; a quote is ~0.1 GEN. Both SDKs now quote before sending |
| The documented production runner works on 61997 | `[X]` **refuted** | `py-genlayer:1jb45aa8…`, the runner in GenLayer's own docs and in every published measurement here, returns `invalid_contract runner malformed`. So does every other `name:hash` pair in the local v0.3.0-rc7 archive. 61997 wants `py-genlayer:5jycge4q8k…` |
| The contracts compile unchanged under GenVM 0.3 | `[X]` **refuted** | `NameError: allow_storage`, then `gl` absent from the wildcard export, then `gl.Contract` / `gl.contract_interface` gone. Five names moved; `brightline/genvm03.py` maps them |
| `gl.public.*`, `gl.vm.UserError/Return/Result`, `gl.message.*`, `gl.storage.inmem_allocate`, `gl.nondet.exec_prompt` survive 0.3 | `[E]` | Probed attribute by attribute against the live 61997 runner through `gen_getContractSchemaForCode`, not assumed |
| The ported source is the same contract | `[E]` | Same method set from `gen_getContractSchemaForCode` on 61997 as the original gives on 61999, all three contracts. `tests/unit/test_genvm03.py` (22 checks) pins the diff to the documented rewrites and asserts the refusal strings and decision vocabulary are byte-identical |
| The escrow on 61997 gates on the 61997 registry | `[E]` | `registry_address()` read back off chain → `0xBFE7D9f4…4100E1`, the registry deployed in the same run |
| The gate behaves identically on 61997 | `[E]` | 20/20 live, `scripts/verify_studio_next.py`: the refusal *"rule has 4 counterexamples, deal tolerates 3"* with the deal still `OPEN` at tolerance 3, a new deal at 4 locking with `counterexamples_at_lock = 4`, and the untested-rule refusal |
| The nondet path survives the `run_nondet_unsafe` → `run_nondet` rename | `[E]` | One real committee adjudication on 61997: 76 s, `REJECT`, confidence 85, reason coherent, decision inside the vocabulary |
| genlayer-js 2.0.0-rc.1 can read stable Studio | `[X]` **refuted** | `gen_call` against 61999 → `execution failed`, for reads as well as writes, in the vendored bundle against the real registry. One vendored SDK serves one Studio generation; 61999 is marked `usable: false` with the reason |
| 2.0.0-rc.1 restores model pinning to the browser | `[X]` refuted | The string `simConfig` occurs nowhere in the bundle; `writeContract` takes `fees` where the Python SDK takes `sim_config`. Three live 61997 runs drew `policy:dev-gpt-5-4`, `openai/gpt-5.4`, `policy:dev-gpt-oss` — the network's choices, as before |
| The explorer shows the deployed contracts | `[E]` | `explorer-studio-dev.genlayer.com` renders all three address pages (contract label, address, creator, deploy tx, balance, full transaction history) and all three deploy transactions as `FINALIZED` / `Deploy`. 27/27 render checks |
| The explorer shows a method schema | `[X]` refuted | Its METHOD column reads `(constructor)` for every GenVM call and there is no ABI view. Method-level verification comes from the node instead: `gen_getContractSchema` reports the expected method set for all three |
| The published measurements were re-taken on 61997 | `[A]` **no** | 4/8, mean divergence 0.3125, noise floor 0.0, the re-test table and the E6 verdict remain studionet measurements over 48 pinned-model transactions, and stay labelled that way. 61997 carries the live artifact, not a new measurement |
