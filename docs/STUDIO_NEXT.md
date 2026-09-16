# Studio Next (chain 61997)

The dApp's verification network. Contracts deployed, seeded and verified there with real
transactions; the deployed site reads and writes 61997 and nothing else.

Stable Studio (61999) is still in the repo and still holds every published measurement.
Nothing was deleted. What changed is which network the *interactive* artifact talks to.

## Network

| | |
|---|---|
| name | Studio Next |
| chain id | **61997** (`0xf22d`) |
| RPC | `https://studio-next.genlayer.com/api` |
| GenVM | `v0.3.0-rc7` |
| consensus | v0.6, fee-quoted |
| explorer | <https://explorer-studio-dev.genlayer.com> |
| faucet | `sim_fundAccount` (Studio faucet, no GitHub OAuth) |

`studio-next.genlayer.com/api` and `studio-dev.genlayer.com/api` are two hostnames for
one chain, not two networks — both answer `eth_chainId` `0xf22d`, and a single faucet
call credited the same balance on both. genlayer-js names the second one
(`chains.studioDevnet`, "GenLayer Studio Devnet"); the deployment and the dApp pin the
first, so the endpoint the UI names is the endpoint it uses.

## Deployments

All three deployed fresh. The 61999 addresses are **not** reusable: 61997 is a separate
chain with a separate state trie, and the contracts there are a different GenVM build.

| Contract | Address | Deploy tx |
|---|---|---|
| `BrightlineProbe` | [`0x025AF20b0eCD703Ab079568c24861308F09bD77d`](https://explorer-studio-dev.genlayer.com/address/0x025AF20b0eCD703Ab079568c24861308F09bD77d) | [`0x29fceaa9…27207293`](https://explorer-studio-dev.genlayer.com/tx/0x29fceaa9d1103c2c1225c8c33e428d2d6ad6eb1bc2113a1806c57b1927207293) |
| `BrightlineRegistry` | [`0xBFE7D9f45241B7baD76f79A265e03703314100E1`](https://explorer-studio-dev.genlayer.com/address/0xBFE7D9f45241B7baD76f79A265e03703314100E1) | [`0xf305bbd4…f0fe8978`](https://explorer-studio-dev.genlayer.com/tx/0xf305bbd4b71987d12e5582e01079165ae62a3c4d0d309e75a8f3356cf0fe8978) |
| `GatedEscrow` | [`0x8467f1027A9657A90a26e9127aD24772837fC612`](https://explorer-studio-dev.genlayer.com/address/0x8467f1027A9657A90a26e9127aD24772837fC612) | [`0x0f0c3838…6a40dcf1`](https://explorer-studio-dev.genlayer.com/tx/0x0f0c38387657a422be54d81a8227d9a610a909efa46df07a526f3df76a40dcf1) |

`GatedEscrow` was constructed against *this* network's registry, and that is read back
off chain after deployment rather than trusted: `registry_address()` returns
`0xBFE7D9f45241B7baD76f79A265e03703314100E1`. The gate cannot be pointed at a
friendlier registry after the fact, and it is not pointed at the 61999 one.

The probe contract is seeded with the v1 rule and all eight probes of the frozen set
`ps_6ce467da9d20c1f2`, registered as the exact `normalized` / `canonical` strings the
rule hash and probe ids are computed over. `adjudicate` refuses a probe id it has never
seen, so a deployment with one probe registered would be a demo that fails on seven of
eight clicks.

```bash
.venv-rc/bin/python scripts/deploy_studio_next.py       # deploy + seed, idempotent
.venv-rc/bin/python scripts/deploy_studio_next.py --verify-only
.venv-rc/bin/python scripts/verify_studio_next.py       # 20 live checks
```

## Four incompatibilities, and what each one actually was

None of this was configuration. Each was found by a failing transaction and fixed at the
cause; the diagnosis is recorded because the error messages on their own are misleading.

**1. The consensus ABI changed.** genlayer-py 0.16.3 encodes
`addTransaction(address,address,uint256,uint256,bytes,uint256)`. Studio Next's consensus
contract — same address, `0xb7278A61aa25c888815aFC32Ad3cC52fF24fE575`, different build —
takes a single packed tuple plus a `deploySalted` entry point. Different selector, so
every transaction reverted at the EVM layer with no reason string, before GenVM ran.
Fixed by genlayer-py **0.19.0rc2**.

**2. Fees are mandatory.** With the right ABI, deployment still reverted:
`FeesDistributionMissing`. Consensus v0.6 requires a quoted fee distribution on every
transaction — about 0.1 GEN here (`enabled: true`, `genPerTimeUnit: 1`). The Python SDK
requires the quote explicitly (`fees=client.estimate_transaction_fees()`); genlayer-js
prices a transaction only when handed a distribution and otherwise sends zero, which the
contract rejects as `FeeValueMustBeNonZero`. Both paths now quote before sending.

**3. The runner moved.** `py-genlayer:1jb45aa8…` is the production runner in GenLayer's
own docs and is what every published measurement ran against. Studio Next rejects it:
`invalid_contract runner malformed`. So does every other `name:hash` pair in the local
v0.3.0-rc7 archive. The runner Studio Next accepts is
`py-genlayer:5jycge4q8k23462jtb0b9fyey1s9qz928sz2nbrd9mg4sxqg2qng`. A contract file pins
exactly one runner, and each network refuses the other's, so **no single source file can
deploy to both**.

**4. The contract SDK renamed things.** With the right runner, GenVM got far enough to
raise real Python errors. GenVM 0.3 moved five names our contracts use:

| GenVM 0.2 | GenVM 0.3 |
|---|---|
| `gl.Contract` | `gl.contract.Contract` |
| `@gl.contract_interface` | `@gl.contract.interface` |
| `gl.vm.run_nondet_unsafe` | `gl.vm.run_nondet` |
| `gl.message_raw["datetime"]` | `gl.message.datetime` |
| `allow_storage`, `gl`, `TreeMap`, `DynArray`, the int types — via `from genlayer import *` | explicit imports from `genlayer.storage` / `genlayer.types` |

`gl.public.*`, `gl.vm.UserError`, `gl.vm.Return`, `gl.vm.Result`, `gl.message.*`,
`gl.storage.inmem_allocate` and `gl.nondet.exec_prompt` are unchanged — checked
attribute by attribute against the live 61997 runner rather than assumed.

## How the same contract runs on both

`contracts/*.py` is untouched: byte-identical to the source every published number was
measured against. `brightline/genvm03.py` derives the Studio Next build from it at
deploy time — a runner swap, an import preamble, and four anchored substitutions.

That choice is deliberate. A second copy of each contract would let the audited 61999
version and the deployed 61997 version drift, and a version branch inside
consensus-critical code would put GenVM-version logic next to the decision logic. A
transform keeps the whole difference in one readable table.

What holds it honest:

- `tests/unit/test_genvm03.py` — 22 checks. Every changed line must match a documented
  rewrite, every removed line must be one of the 0.2 forms, no GenVM 0.2 name survives,
  the transform is idempotent, and the refusal messages plus the four-value decision
  vocabulary are byte-for-byte identical before and after.
- `gen_getContractSchemaForCode` against both chains: the ported source compiles on
  61997 with **the same method set** the original compiles with on 61999, for all three
  contracts.
- `scripts/verify_studio_next.py`: 20 live checks, real transactions.

One behavioural note, stated rather than buried: 0.2's `gl.message_raw["datetime"]` is a
string and 0.3's `gl.message.datetime` is a datetime, so the transform wraps it in
`str()`. Every use is a display timestamp on a stored record (`ts`, `ts_opened`,
`ts_locked`); none is parsed, compared or gated on.

## What was verified live, and what that proves

`scripts/verify_studio_next.py`, 20/20, every assertion a real transaction:

- `register_rule` / `register_probe`, then both read back **byte-identical**.
- the real v1 attestation published; `is_tested → true`, `worst_counterexamples → 4`.
- tolerance 3 against a rule with 4 counterexamples: refused on chain with
  *"rule has 4 counterexamples, deal tolerates 3"*, and the deal still `OPEN` at
  tolerance 3 afterwards.
- a new deal at tolerance 4 locks: `LOCKED`, `counterexamples_at_lock = 4`, amount
  0.01 GEN — and the refused deal is still `OPEN`, untouched.
- the untested rule refused with *"no published Brightline report"*.
- one real adjudication through the network's own committee, 76 s, `REJECT` with a
  reason, decision inside the vocabulary. This is the consensus-critical path, and it is
  where the `run_nondet_unsafe` → `run_nondet` rename is proved harmless.

Through the JS stack, against the same contracts:
`npm run test:live` → **34/34** (30 settlement + 4 quick check), real writes signed by a
local dev key rather than the Snap.

## The cost: one vendored SDK, one Studio generation

genlayer-js **2.0.0-rc.1** is required for Studio Next — 1.x cannot encode a v0.6
transaction at all. That same build **cannot read stable Studio**: a `gen_call` against
61999 returns `execution failed`, for reads as much as writes. Tested both directions in
the vendored bundle against the real registries.

So the dApp cannot serve both networks, and the config says so instead of offering tiles
that would fail. 61999 stays in `frontend/networks.json` with its addresses and
`deployed: true`, marked `usable: false`, carrying the reason.

Nothing is lost from the artifact:

- every report, counterexample, probe manifest and re-test table renders **with no chain
  access at all** — that has always been true and is why read-only is the default state;
- the 61999 contracts are live and unchanged, and the CLI still reads and writes them:
  `.venv/bin/python -m brightline.run … --network studionet`;
- `.brightline/deployments.json` keeps both networks' addresses under separate keys.

## Two toolchains, on purpose

| | `.venv` | `.venv-rc` |
|---|---|---|
| genlayer-py | 0.16.3 | 0.19.0rc2 |
| networks | studionet, Bradbury | Studio Next |
| used by | everything in `brightline/`, `scripts/e*.py`, pytest | `scripts/deploy_studio_next.py`, `scripts/verify_studio_next.py` |

0.19.0rc2 renames `TransactionStatus` out from under `brightline/chain.py` and would
break every existing script, and its Studio chain definitions assume v0.6 everywhere —
which is exactly why it cannot talk to 61999. Upgrading in place would have traded a
working 61999 toolchain for a working 61997 one. Two venvs keeps both.

```bash
/usr/bin/python3.12 -m venv .venv-rc && .venv-rc/bin/pip install "genlayer-py==0.19.0rc2"
```

`.venv-rc/` is gitignored, like `.venv/`.

## Known limits

- **Studio Next is a preview network and may reset.** If it does, re-run
  `deploy_studio_next.py`; the addresses above change and `export_frontend_config.py`
  regenerates the config. The published reports do not depend on it.
- **It sheds load.** `Server busy: all 8 execution slots occupied, retry later` and
  dropped fetches are routine. The dApp already retries reads with backoff; the live
  suites now do the same, and the browser suite files these as transport conditions
  rather than defects.
- **Still no model pinning from the browser.** genlayer-js 2.0.0-rc.1 contains no
  `simConfig` anywhere — `writeContract` takes `fees` where the Python SDK takes
  `sim_config`. So Quick Check remains run-to-run stability against the network's own
  committee, not a cross-model panel, exactly as before. Confirmed on 61997: three runs
  drew `policy:dev-gpt-5-4`, `openai/gpt-5.4`, `policy:dev-gpt-oss`.
- **The explorer shows contract information, not a method schema.** Address pages give
  the contract label, address, creator, deploy tx, balance and full transaction history
  with GenVM and consensus results; the METHOD column reads `(constructor)` for every
  GenVM call and there is no ABI view. Method-level verification therefore comes from
  the node, `gen_getContractSchema`, which reports the expected method set for all
  three contracts.
- **No measurement was re-run on 61997.** The published numbers — 4/8, mean divergence
  0.3125, noise floor 0.0, the re-test table, the E6 verdict — are studionet
  measurements taken with pinned models over 48 transactions, and they stay labelled
  that way. Reproducing them on Studio Next would require model pinning, which the
  panel channel gets from `sim_config` on the Python SDK; that has not been run here.
  What 61997 carries is the live interactive artifact, not a new measurement.
