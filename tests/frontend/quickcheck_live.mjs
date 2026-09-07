/* Live verification of the quick-check run loop, on real studionet.
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
import { studionet } from "genlayer-js/chains";
import { readFileSync } from "node:fs";
import { divergence, extractReturn, statusKind, statusName, executionFailed }
  from "../../frontend/lib/receipt.js";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const R = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));
const cfg = R("frontend/networks.json").networks.studionet;
const probeAddr = cfg.contracts.probe.address;
const rule = R("reports/index.json").reports[0].rule_hash;
const set = R("probes/ps_6ce467da9d20c1f2.json");
const probe = set.probes[1];                        // conflicting_evidence
const k = R(".brightline/accounts.json").default;
const client = createClient({ chain: studionet, account: createAccount(k.startsWith("0x")?k:`0x${k}`) });

let pass=0, fail=0;
const check=(n,ok,d="")=>{console.log(`  ${ok?"PASS":"FAIL"}  ${n}${ok||!d?"":`\n        ${d}`}`);ok?pass++:fail++;};

// Registration precondition, exactly as the component checks it.
const [r, sc] = await Promise.all([
  client.readContract({ address: probeAddr, functionName: "get_rule", args: [rule] }),
  client.readContract({ address: probeAddr, functionName: "get_probe", args: [probe.probe_id] }),
]);
check("rule and probe are registered on chain", Boolean(r) && Boolean(sc));

const obs = [];
for (let n = 1; n <= 3; n++) {
  const h = String(await client.writeContract({ address: probeAddr,
    functionName: "adjudicate", args: [rule, probe.probe_id], value: 0n }));
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
