/* Live verification of the quick-check run loop, on the live verification network.
 *
 * Runs the same sequence the browser component runs -- registration precondition, N
 * sequential adjudications, decision extraction, run-to-run divergence -- through the
 * same lib/receipt.js helpers. The only substitution is the signer: a local dev key
 * instead of the MetaMask Snap.
 *
 * It also documents the finding that shaped this feature: the `models used` line shows
 * the network choosing its own models, because genlayer-js ignores `simConfig`. That is
 * why the browser cannot reproduce the CLI's cross-model panel.
 *
 *   node tests/frontend/quickcheck_live.mjs
 */
import { createClient, createAccount } from "genlayer-js";
import * as chains from "genlayer-js/chains";
import { readFileSync } from "node:fs";
import { divergence, extractReturn, statusKind, statusName, executionFailed }
  from "../../frontend/lib/receipt.js";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const R = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));
const all = R("frontend/networks.json");
// Follows the config's verification network rather than pinning one.
const cfg = all.networks[all.default];
const probeAddr = cfg.contracts.probe.address;
const rule = R("reports/index.json").reports[0].rule_hash;
const set = R("probes/ps_6ce467da9d20c1f2.json");
const probe = set.probes[1];                        // conflicting_evidence
const k = R(".brightline/accounts.json").default;
// Same RPC override lib/gl.js applies -- see the note there.
const base = chains[cfg.js_chain];
if (base.id !== cfg.chain_id) throw new Error(`chain ${base.id} != config ${cfg.chain_id}`);
const chain = { ...base, rpcUrls: { default: { http: [cfg.rpc] } } };
/** Retry a call that failed for transport reasons, not contract reasons.
 *
 * Studio Next is a shared preview network and sheds load ("Server busy: all 8 execution
 * slots occupied"). lib/gl.js `read()` already retries browser reads with backoff for
 * the same reason, so the suite that claims to exercise the browser's path has to do it
 * too -- otherwise it reports someone else's congestion as a Brightline failure.
 * Contract-level refusals are not retried: they arrive as receipts, not throws.
 */
async function resilient(label, fn, attempts = 5) {
  let last;
  for (let i = 0; i < attempts; i++) {
    try { return await fn(); } catch (e) {
      last = e;
      const msg = String(e?.message || e);
      if (!/busy|fetch failed|timeout|ECONN|socket|slots occupied/i.test(msg)) throw e;
      const wait = 2000 * (i + 1);
      console.log(`  ..   ${label}: ${msg.split("\n")[0].slice(0, 80)} -- retry in ${wait}ms`);
      await new Promise((r) => setTimeout(r, wait));
    }
  }
  throw last;
}

/** Same fee quoting the browser does in lib/gl.js `write()`.
 *
 * Consensus v0.6 rejects a zero fee deposit (`FeeValueMustBeNonZero`) at the EVM layer,
 * and writeContract only prices a transaction when handed a distribution. Quoting here
 * keeps this suite exercising the same path the dApp takes rather than a cheaper one.
 */
async function sendWrite(client, params) {
  return resilient(`write ${params.functionName}`, async () => {
    const fees = typeof client.estimateTransactionFees === "function"
      ? await client.estimateTransactionFees() : undefined;
    return client.writeContract({ ...params, ...(fees ? { fees } : {}) });
  });
}

/** client.readContract, retried on the same transport conditions. */
function resilientRead(client, params) {
  return resilient(`read ${params.functionName}`, () => client.readContract(params));
}

const client = createClient({ chain, account: createAccount(k.startsWith("0x")?k:`0x${k}`) });

let pass=0, fail=0;
const check=(n,ok,d="")=>{console.log(`  ${ok?"PASS":"FAIL"}  ${n}${ok||!d?"":`\n        ${d}`}`);ok?pass++:fail++;};

// Registration precondition, exactly as the component checks it.
const [r, sc] = await Promise.all([
  resilientRead(client, { address: probeAddr, functionName: "get_rule", args: [rule] }),
  resilientRead(client, { address: probeAddr, functionName: "get_probe", args: [probe.probe_id] }),
]);
check("rule and probe are registered on chain", Boolean(r) && Boolean(sc));

/* Studionet occasionally answers a JSON-RPC call with an HTML gateway page, which the
 * SDK surfaces as an UnknownRpcError. The polling loop already tolerated that; the
 * submit did not, so one dropped `eth_getTransactionCount` aborted the whole process
 * before any assertion ran. Retry, then record the run as a transport failure -- it
 * contributes no observation, exactly like a run that came back inconclusive. */
async function submit() {
  let last;
  for (let a = 0; a < 3; a++) {
    try {
      return String(await sendWrite(client, { address: probeAddr,
        functionName: "adjudicate", args: [rule, probe.probe_id], value: 0n }));
    } catch (e) {
      last = e;
      await new Promise((x) => setTimeout(x, 4000 * (a + 1)));
    }
  }
  console.log(`        submit failed after 3 attempts: ${last?.shortMessage || last?.message}`);
  return null;
}

const obs = [];
for (let n = 1; n <= 3; n++) {
  const h = await submit();
  if (!h) { obs.push({ n, kind: "RPC_ERROR", decision: "", model: "" }); continue; }
  let t=null;
  for (let i=0;i<120;i++){ try{t=await client.getTransaction({hash:h});}catch{t=null;}
    if(t&&statusKind(statusName(t)).terminal)break; await new Promise(x=>setTimeout(x,3000)); }
  const kind = statusKind(statusName(t)).kind;
  if (kind === "no_consensus") { obs.push({n,kind:"NO_CONSENSUS",decision:"",model:""}); }
  else {
    const p = extractReturn(t);
    let lr=(t.consensus_data||{}).leader_receipt; if(Array.isArray(lr))lr=lr[0];
    const nc=lr?.node_config||{};
    obs.push({ n, kind: p?.status==="OK"?"OK":"INCONCLUSIVE", decision: p?.decision||"",
               conf: p?.confidence||0, model: (nc.primary_model||{}).model||nc.model||"?",
               status: statusName(t), tx: h });
  }
  console.log(`  run ${n}: ${obs[n-1].kind} ${obs[n-1].decision||""} (${obs[n-1].status||"n/a"}) model=${obs[n-1].model}`);
}

const valid = obs.filter(o=>o.kind==="OK"&&o.decision);
check("at least one run produced a usable decision", valid.length>=1, JSON.stringify(obs));
check("all decisions are in the vocabulary",
  valid.every(o=>["ACCEPT","REJECT","PARTIAL","INSUFFICIENT"].includes(o.decision)),
  JSON.stringify(valid.map(o=>o.decision)));
const div = divergence(valid.map(o=>o.decision));
check("run-to-run divergence computes", div!==null||valid.length===0, `div=${div}`);
console.log(`\n  distribution: ${JSON.stringify(valid.reduce((a,o)=>{a[o.decision]=(a[o.decision]||0)+1;return a;},{}))}`);
console.log(`  divergence  : ${div}`);
console.log(`  models used : ${JSON.stringify([...new Set(obs.map(o=>o.model))])}`);
console.log(`\n${pass}/${pass+fail} live quick-check assertions passed`);
if(fail)process.exit(1);
