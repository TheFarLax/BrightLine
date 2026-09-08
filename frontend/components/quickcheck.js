/* Quick Check — one probe, adjudicated live by the network's own committee.
 *
 * IMPORTANT SCOPE NOTE, and the reason this is not a browser panel run:
 *
 * genlayer-js 1.1.8 has no `simConfig` parameter on `writeContract`. Passing one is
 * silently ignored — verified on studionet by requesting three different models and
 * watching the network pick three unrelated ones (kimi -> grok, gemini-3-flash ->
 * gemini, qwen -> gpt-5.4). So the browser cannot pin a model, which means it cannot
 * reproduce the PANEL channel at all. Only the Python CLI can, because genlayer-py
 * forwards `sim_config` on the RPC call.
 *
 * Rather than fake a panel, Quick Check does the thing the browser can do honestly:
 * run the SAME probe N times against the live committee and show what comes back. That
 * measures a real and different quantity — run-to-run stability of the network's own
 * adjudication — and it is labelled as such everywhere it appears.
 *
 * This is a demonstration, never a settlement input. Its numbers are not a Split Score,
 * are not written on-chain, and are not read by any gate.
 */

import { divergence, extractReturn, statusName } from "../lib/receipt.js";
import { read, write } from "../lib/gl.js";
import { createTxQueue } from "./tx.js";

const DECISIONS = ["ACCEPT", "REJECT", "PARTIAL", "INSUFFICIENT"];
const DEFAULT_RUNS = 3;
const MAX_RUNS = 6;

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const state = {
  wallet: null,
  probeSet: null,
  probeIndex: 0,
  ruleHash: null,
  ruleLabel: "",
  runs: DEFAULT_RUNS,
  observations: [],     // { n, decision, status, kind, confidence, reason, model, tx }
  running: false,
  registered: null,     // null unknown, true/false once checked
  note: "",
};

let host = null;
let txq = null;

function net() { return state.wallet?.net; }
function probeContract() { return net()?.contracts?.probe; }

function canRun() {
  return Boolean(state.wallet?.status === "connected" && net()?.wallet_writes
                 && state.registered === true && !state.running);
}

function blockedReason() {
  if (!net()?.wallet_writes) {
    return `live adjudication is unavailable on ${net()?.label ?? "this network"}`
      + (net()?.wallet_note ? ` — ${net().wallet_note}` : "");
  }
  if (state.wallet?.status !== "connected") return "connect a wallet to sign";
  if (state.registered === false) {
    return "this rule or probe is not registered on chain yet — register it with the CLI"
      + " (python -m brightline.run …) or pick a probe set that is";
  }
  if (state.running) return "a run is in progress";
  return "";
}

/** Both the rule text and the scenario must already be on chain to adjudicate. */
async function checkRegistered() {
  const c = probeContract();
  const probe = currentProbe();
  if (!c || !state.wallet?.reader || !probe) { state.registered = null; return; }
  try {
    const [rule, scenario] = await Promise.all([
      read(state.wallet.reader, c.address, "get_rule", [state.ruleHash]),
      read(state.wallet.reader, c.address, "get_probe", [probe.probe_id]),
    ]);
    state.registered = Boolean(rule) && Boolean(scenario);
  } catch (e) {
    state.registered = null;
    state.note = `registration check failed: ${e.message}`;
  }
}

function currentProbe() {
  return state.probeSet?.probes?.[state.probeIndex] || null;
}

function distribution() {
  const out = {};
  for (const o of state.observations) {
    if (o.kind === "INCONCLUSIVE" || !o.decision) continue;
    out[o.decision] = (out[o.decision] || 0) + 1;
  }
  return out;
}

function valid() {
  return state.observations.filter((o) => o.kind !== "INCONCLUSIVE" && o.decision);
}

// -------------------------------------------------------------------- the run loop
async function runOnce(n) {
  const c = probeContract();
  const probe = currentProbe();
  const res = await txq.track({
    label: `adjudicate · run ${n} of ${state.runs}`,
    client: state.wallet.writer,
    submit: () => write(state.wallet.writer, c.address, "adjudicate",
                        [state.ruleHash, probe.probe_id]),
  });

  const obs = { n, decision: "", status: "", kind: "INCONCLUSIVE",
                confidence: 0, reason: "", model: "", tx: res.hash || "" };

  if (res.outcome === "no_consensus") {
    // The committee could not agree. That is a finding about this probe, not a bug,
    // and it is exactly the case the CLI's PANEL channel exists to resolve into a
    // decision distribution. Here we can only record that it happened.
    obs.kind = "NO_CONSENSUS";
    obs.reason = "validators did not converge (Undetermined) — no state was written";
  } else if (!res.ok) {
    obs.reason = res.reason || res.error || `run ${res.outcome}`;
  } else {
    const payload = res.payload && "decision" in res.payload
      ? res.payload : extractReturn(res.receipt);
    if (payload && payload.status === "OK" && DECISIONS.includes(payload.decision)) {
      obs.kind = "OK";
      obs.decision = payload.decision;
      obs.confidence = Number(payload.confidence || 0);
      obs.reason = String(payload.reason || "");
    } else {
      obs.reason = payload ? `model produced no parseable decision (${payload.status})`
                           : "no usable return payload";
    }
    // Which model the network actually used, recovered from the receipt. This is the
    // network's choice, not ours -- see the scope note at the top of this file.
    try {
      const cd = res.receipt?.consensus_data || {};
      let lr = cd.leader_receipt;
      if (Array.isArray(lr)) lr = lr[0];
      const nc = lr?.node_config || {};
      obs.model = String((nc.primary_model || {}).model || nc.model || "");
    } catch { /* model attribution is a nicety, never a requirement */ }
  }

  state.observations.push(obs);
  paint();
}

async function runAll() {
  state.running = true;
  state.observations = [];
  state.note = "";
  txq.clear();
  paint();
  for (let n = 1; n <= state.runs; n++) {
    try {
      await runOnce(n);
    } catch (e) {
      // Studionet degrades; a failed run is recorded and the sweep continues rather
      // than throwing the whole thing away.
      state.observations.push({ n, decision: "", status: "", kind: "INCONCLUSIVE",
                                confidence: 0, reason: `run failed: ${e.message}`,
                                model: "", tx: "" });
      paint();
    }
  }
  state.running = false;
  paint();
}

// ------------------------------------------------------------------------- render
function tile(k, v, note) {
  return `<div class="tile"><div class="k">${esc(k)}</div>
    <div class="v">${esc(v)}</div>
    ${note ? `<div class="n">${esc(note)}</div>` : ""}</div>`;
}

function scenarioCard() {
  const p = currentProbe();
  if (!p) return `<p class="note">No probe selected.</p>`;
  const facts = (p.scenario.facts || []).map((f) =>
    `<li><span class="mono">${esc(f.k)}</span>: ${esc(f.v)}</li>`).join("");
  const absent = (p.scenario.evidence_absent || []).map((x) =>
    `<span class="pill">${esc(x)}</span>`).join(" ");
  return `<div class="card">
    <h3>probe #${p.index} · ${esc(p.family)}</h3>
    <div class="scen">${esc(p.scenario.narrative)}</div>
    <ul class="missing">${facts}</ul>
    ${absent ? `<p class="note">evidence absent: ${absent}</p>` : ""}
    <p class="note mono">probe_id ${esc(p.probe_id)}</p>
  </div>`;
}

function resultsCard() {
  if (!state.observations.length) return "";
  const dist = distribution();
  const v = valid();
  const div = divergence(v.map((o) => o.decision));
  const inconc = state.observations.filter((o) => o.kind !== "OK").length;

  const bars = DECISIONS.map((d) => {
    const count = dist[d] || 0;
    const width = v.length ? (count / v.length) * 100 : 0;
    return `<tr>
      <td>${esc(d)}</td>
      <td class="bar-cell"><div class="track">
        <div class="fill" style="width:${width}%"></div></div></td>
      <td class="num">${count}</td>
    </tr>`;
  }).join("");

  const rows = state.observations.map((o) => {
    const link = o.tx && net()?.explorer_tx
      ? `<a href="${esc(net().explorer_tx + o.tx)}" target="_blank" rel="noopener"
           class="mono">${esc(o.tx.slice(0, 10))}…</a>` : "";
    return `<tr>
      <td class="num">${o.n}</td>
      <td><b>${esc(o.decision || o.kind)}</b></td>
      <td class="num">${o.confidence || ""}</td>
      <td class="mono">${esc((o.model || "").split("/").pop())}</td>
      <td>${link}</td>
      <td class="note">${esc(o.reason.slice(0, 120))}</td>
    </tr>`;
  }).join("");

  return `<div class="card">
    <h3>Result</h3>
    <div class="tiles">
      ${tile("runs", `${v.length} / ${state.observations.length}`, "usable / attempted")}
      ${tile("run-to-run divergence", div === null ? "n/a" : div.toFixed(3),
             "1 − modal share across runs")}
      ${tile("excluded", inconc, "inconclusive or no-consensus")}
    </div>
    <div class="table-scroll" style="margin-top:14px"><table><thead><tr>
      <th>decision</th><th>share</th><th>n</th></tr></thead>
      <tbody>${bars}</tbody></table></div>
    <div class="table-scroll" style="margin-top:14px"><table><thead><tr>
      <th>run</th><th>outcome</th><th>conf</th><th>model used</th><th>tx</th><th>note</th>
    </tr></thead><tbody>${rows}</tbody></table></div>
    <p class="note warn">This measures run-to-run stability of the live committee. It is
    <b>not</b> a Split Score and not a cross-model panel: the browser cannot pin a model
    (genlayer-js ignores <span class="mono">simConfig</span>), so model choice is the
    network's. Cross-model divergence comes only from the CLI. Nothing here is written
    on chain or read by any gate.</p>
  </div>`;
}

function paint() {
  if (!host) return;
  const p = currentProbe();
  const probeOpts = (state.probeSet?.probes || []).map((x, i) =>
    `<option value="${i}"${i === state.probeIndex ? " selected" : ""}>
       #${x.index} · ${esc(x.family)}</option>`).join("");
  const supported = Boolean(net()?.supports_sim_config);

  host.innerHTML = `
    <h2>Quick check</h2>
    <p>Adjudicate one frozen probe live, ${state.runs} times, against the network's own
    committee. A demonstration that real adjudication is happening — not a settlement
    input, and not the panel run.</p>
    <div class="scope">
      <b>Scope.</b> This measures <b>run-to-run stability of the live committee</b>. It is
      <b>not a Split Score</b> and not a cross-model panel: genlayer-js ignores
      <span class="mono">simConfig</span>, so the browser cannot pin a model and the
      network chooses it. Cross-model divergence comes only from the Python CLI. Nothing
      here is written on chain or read by any gate.
    </div>
    ${!supported ? `<div class="err">Live adjudication needs a Studio-type network.
      ${esc(net()?.label ?? "this network")} does not support it.</div>` : `
    <div class="card">
      <div class="row">
        <label class="note">rule</label>
        <span class="mono">${esc(state.ruleLabel)} · ${esc((state.ruleHash || "").slice(0, 18))}</span>
      </div>
      <div class="row">
        <label class="note">probe</label>
        <select id="q-probe">${probeOpts}</select>
        <label class="note">runs</label>
        <button type="button" data-runs="-1">−</button>
        <span class="mono"><b>${state.runs}</b></span>
        <button type="button" data-runs="1">+</button>
        <button type="button" id="q-run" ${canRun() ? "" : "disabled"}>
          ${state.running ? "running…" : "Run live adjudication"}</button>
        ${state.observations.length && !state.running
          ? `<button type="button" id="q-again">Run again</button>` : ""}
      </div>
      ${canRun() ? "" : `<p class="note">${esc(blockedReason())}</p>`}
      <p class="note">Each run is one signed transaction and takes roughly 10–60 s.
      Registration stays a CLI step so the browser never needs the 48-transaction sweep.</p>
    </div>
    ${scenarioCard()}
    ${resultsCard()}
    <h2>Transactions</h2>
    <div id="q-txq"></div>`}
    ${state.note ? `<p class="note warn">${esc(state.note)}</p>` : ""}`;

  // Survives a repaint: the run loop repaints after every observation, and a queue
  // rebuilt each time would drop the earlier runs' hashes mid-demo.
  const txHost = host.querySelector("#q-txq");
  if (txHost) {
    if (txq) txq.attach(txHost, { net: net() });
    else txq = createTxQueue(txHost, { net: net() });
  }
  bind();
}

function bind() {
  const sel = host.querySelector("#q-probe");
  if (sel) sel.addEventListener("change", async (e) => {
    state.probeIndex = Number(e.target.value);
    state.observations = [];
    state.registered = null;
    paint();
    await checkRegistered();
    paint();
  });
  for (const btn of host.querySelectorAll("[data-runs]")) {
    btn.addEventListener("click", () => {
      state.runs = Math.min(MAX_RUNS, Math.max(1, state.runs + Number(btn.dataset.runs)));
      paint();
    });
  }
  for (const id of ["#q-run", "#q-again"]) {
    const b = host.querySelector(id);
    if (b) b.addEventListener("click", runAll);
  }
}

export async function mountQuickCheck(el, { wallet, probeSet, ruleHash, ruleLabel }) {
  if (txq) txq.dispose();
  txq = null;
  host = el;
  state.wallet = wallet;
  state.probeSet = probeSet;
  state.ruleHash = ruleHash;
  state.ruleLabel = ruleLabel || "";
  state.probeIndex = 0;
  state.observations = [];
  paint();
  await checkRegistered();
  paint();
}

export function updateQuickCheckWallet(wallet) {
  state.wallet = wallet;
  if (host) paint();
}
