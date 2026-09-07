/* Settlement: registry reads, report publication, and the escrow gate.
 *
 * The gate is the product surface, so what it checks is deliberately narrow and fixed
 * by the E6 verdict: a published report must exist for the rule, and the *worst*
 * counterexample count across every competing report must be within the tolerance the
 * payer chose before opening the deal. No Split Score is read, stored, or displayed as
 * a gating input anywhere in this file.
 *
 * Refusal is a designed state, not an error toast. The two refusal paths -- tolerance
 * below the worst finding, and no report at all -- are the clearest demonstration the
 * product has, and both leave the deal OPEN so the user can adjust and retry.
 */

import { lockPreview, publishArgs, reportToAttestation } from "../lib/attest.js";
import { read, write } from "../lib/gl.js";
import { createTxQueue } from "./tx.js";

const UNTESTED_RULE = `0x${"ee".repeat(32)}`;
const DEFAULT_AMOUNT_WEI = 10n ** 16n;          // 0.01 GEN

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const short = (a) => (a ? `${a.slice(0, 10)}…${a.slice(-6)}` : "—");

const state = {
  wallet: null,          // { net, reader, writer, address, status }
  reports: [],           // committed report artifacts
  ruleHash: null,
  ruleLabel: "",
  registry: { tested: false, worst: 0, summary: null, published: {} },   // published: hash -> true/false/null
  deal: null,            // last deal read from chain
  dealId: null,
  tolerance: 0,
  busy: false,
  note: "",
};

let host = null;
let txq = null;

function contracts() {
  return state.wallet?.net?.contracts || {};
}

function canWrite() {
  return state.wallet?.status === "connected" && state.wallet?.net?.wallet_writes;
}

function writeBlockedReason() {
  if (!state.wallet?.net?.wallet_writes) {
    return `wallet writes are off on ${state.wallet?.net?.label ?? "this network"}` +
      (state.wallet?.net?.wallet_note ? ` — ${state.wallet.net.wallet_note}` : "");
  }
  if (state.wallet?.status !== "connected") return "connect a wallet to sign";
  return "";
}

// ------------------------------------------------------------------- chain reads
async function refreshRegistry() {
  const reg = contracts().registry;
  if (!reg || !state.wallet?.reader || !state.ruleHash) return;
  const client = state.wallet.reader;
  try {
    const [tested, worst, summaryRaw] = await Promise.all([
      read(client, reg.address, "is_tested", [state.ruleHash]),
      read(client, reg.address, "worst_counterexamples", [state.ruleHash]),
      read(client, reg.address, "summary_for_rule", [state.ruleHash]),
    ]);
    state.registry.tested = Boolean(tested);
    state.registry.worst = Number(worst);
    state.registry.summary = JSON.parse(summaryRaw || "{}");
  } catch (e) {
    state.note = `registry read failed: ${e.message}`;
  }

  // Which committed reports are already on chain, so the publish list is honest. This
  // only drives a badge, so a failed probe is recorded as unknown rather than as "not
  // published" -- claiming the latter would invite a duplicate publish the contract
  // would then refuse.
  for (const r of state.reports) {
    if (state.registry.published[r.report_hash] !== undefined) continue;
    try {
      const stored = await read(client, reg.address, "get_report", [r.report_hash]);
      state.registry.published[r.report_hash] = Boolean(JSON.parse(stored || "{}").rule_hash);
    } catch {
      state.registry.published[r.report_hash] = null;   // unknown
    }
  }
}

async function refreshDeal() {
  const esc_ = contracts().escrow;
  if (!esc_ || !state.wallet?.reader || !state.dealId) return;
  try {
    const raw = await read(state.wallet.reader, esc_.address, "get_deal", [state.dealId]);
    const parsed = JSON.parse(raw || "{}");
    state.deal = parsed.deal_id ? parsed : null;
  } catch (e) {
    state.note = `deal read failed: ${e.message}`;
  }
}

// ---------------------------------------------------------------------- actions
async function doPublish(reportEntry) {
  const reg = contracts().registry;
  // Bodies are fetched on demand: the attestation needs every adjudication tx hash,
  // which is most of the file, and no other screen needs it.
  if (!reportEntry.report) {
    try {
      reportEntry.report = await (await fetch(`../${reportEntry.path}`)).json();
    } catch (e) {
      state.note = `could not load ${reportEntry.file}: ${e.message}`;
      paint();
      return;
    }
  }
  const att = reportToAttestation(reportEntry.report);
  att.evidence_uri = `reports/${reportEntry.file}`;
  state.busy = true; paint();
  const res = await txq.track({
    label: `publish ${reportEntry.file} (K=${att.counterexamples}/${att.probes})`,
    client: state.wallet.writer,
    submit: () => write(state.wallet.writer, reg.address, "publish", publishArgs(att)),
  });
  state.busy = false;
  if (res.outcome === "refused") {
    // Most likely already published: the registry refuses a duplicate report_hash.
    state.note = `publish refused: ${res.reason}`;
  }
  await refreshRegistry();
  paint();
}

async function doOpenDeal() {
  const escrow = contracts().escrow;
  state.dealId = `deal-${Date.now()}`;
  const payee = state.wallet.address;
  state.busy = true; paint();
  const res = await txq.track({
    label: `open_deal ${state.dealId} · tolerance ${state.tolerance}`,
    client: state.wallet.writer,
    submit: () => write(state.wallet.writer, escrow.address, "open_deal",
                        [state.dealId, payee, state.ruleHash, state.tolerance]),
  });
  state.busy = false;
  if (!res.ok) state.note = `open_deal ${res.outcome}: ${res.reason || res.error || ""}`;
  await refreshDeal();
  paint();
}

async function doLock() {
  const escrow = contracts().escrow;
  state.busy = true; paint();
  const res = await txq.track({
    label: `lock ${state.dealId}`,
    client: state.wallet.writer,
    submit: () => write(state.wallet.writer, escrow.address, "lock", [state.dealId],
                        { value: DEFAULT_AMOUNT_WEI }),
  });
  state.busy = false;
  // A refusal is the gate working. Keep it as a first-class result, and note that the
  // deal is still OPEN so the user can raise the tolerance and try again.
  if (res.outcome === "refused") state.note = "";
  await refreshDeal();
  paint();
}

async function doSettle(kind) {
  const escrow = contracts().escrow;
  state.busy = true; paint();
  const res = await txq.track({
    label: `${kind} ${state.dealId}`,
    client: state.wallet.writer,
    submit: () => write(state.wallet.writer, escrow.address, kind, [state.dealId]),
  });
  state.busy = false;
  if (!res.ok) state.note = `${kind} ${res.outcome}: ${res.reason || res.error || ""}`;
  await refreshDeal();
  paint();
}

// ----------------------------------------------------------------------- render
function ruleOptions() {
  const seen = new Map();
  for (const r of state.reports) {
    if (!seen.has(r.rule_hash)) seen.set(r.rule_hash, r.rule_label);
  }
  const opts = [...seen].map(([hash, label]) =>
    `<option value="${esc(hash)}"${hash === state.ruleHash ? " selected" : ""}>
       ${esc(label)} · ${esc(hash.slice(0, 18))}</option>`);
  // A deliberately untested rule, so the "no report" refusal is one click away.
  opts.push(`<option value="${UNTESTED_RULE}"${state.ruleHash === UNTESTED_RULE ? " selected" : ""}>
    (untested rule — demonstrates the no-report refusal)</option>`);
  return opts.join("");
}

function registryCard() {
  const s = state.registry.summary;
  const rows = (s?.rows || []).map((row) => `<tr>
      <td class="mono">${esc(row.probe_set_id)}</td>
      <td class="num">${row.k} / ${row.n}</td>
      <td class="mono">${esc(row.adversary_version)}</td>
      <td class="mono">${esc(row.network)}</td>
      <td class="mono">${esc(String(row.report_hash).slice(0, 14))}</td>
    </tr>`).join("");
  return `<div class="card">
    <h3>Registry</h3>
    <div class="tiles">
      ${tile("tested", state.registry.tested ? "yes" : "no",
             "has any report been published for this rule")}
      ${tile("worst counterexamples", state.registry.worst,
             "maximum across competing reports")}
      ${tile("reports on chain", s?.reports ?? 0, "anyone may add one")}
    </div>
    ${rows ? `<table style="margin-top:12px"><thead><tr>
        <th>probe set</th><th>K / N</th><th>adversary</th><th>network</th><th>report</th>
      </tr></thead><tbody>${rows}</tbody></table>` : `<p class="note"
        style="margin-top:10px">No reports published for this rule yet.</p>`}
    <p class="note">Worst-of, not latest-of: a rule is as bad as its most successful
    attacker made it look, so publishing until a flattering run appears buys nothing.</p>
  </div>`;
}

function tile(k, v, note) {
  return `<div class="tile"><div class="k">${esc(k)}</div>
    <div class="v">${esc(v)}</div>
    ${note ? `<div class="n">${esc(note)}</div>` : ""}</div>`;
}

function publishCard() {
  const items = state.reports.map((r, i) => {
    const done = state.registry.published[r.report_hash];   // true / false / null=unknown
    return `<div class="camp">
      <span class="dot"></span>
      <span class="lab">${esc(r.rule_label)} ${r.K}/${r.N}</span>
      <span class="who mono">${esc(r.file)}</span>
      ${done === true ? `<span class="pill">on chain</span>`
        : done === null ? `<span class="pill" title="could not read the registry">?</span>`
        : `<button type="button" data-pub="${i}" ${canWrite() ? "" : "disabled"}>Publish</button>`}
    </div>`;
  }).join("");
  return `<div class="card">
    <h3>Publish a report</h3>
    <p class="note">What gets attested: rule, probe set, adversary version, K of N,
    measured noise floor, and the adjudication transaction hashes. No Split Score —
    E6 scoped it to a studionet lab instrument, so it is never a gating input.</p>
    ${items}
    ${canWrite() ? "" : `<p class="note">${esc(writeBlockedReason())}</p>`}
  </div>`;
}

function dealCard() {
  const preview = lockPreview({
    tested: state.registry.tested, worst: state.registry.worst,
    tolerance: state.tolerance,
  });
  const d = state.deal;
  const locked = d?.state === "LOCKED";
  const openAfterRefusal = d?.state === "OPEN";

  const stateBlock = !d ? "" : locked
    ? `<div class="card ok-card">
        <h3>LOCKED</h3>
        <p>${esc(d.amount)} wei escrowed against
           <span class="mono">${esc(short(d.rule_hash))}</span>.</p>
        <p class="note">Counterexamples at lock: <b>${d.counterexamples_at_lock}</b> ·
           tolerated: <b>${d.max_counterexamples}</b></p>
        <p class="note">The registry summary relied on at lock time is frozen into the
           deal, so a later report cannot rewrite what the parties agreed to.</p>
        <div class="prov"><div>${esc(d.summary_at_lock || "")}</div></div>
        <div class="row" style="margin-top:12px">
          <button type="button" data-settle="release" ${canWrite() ? "" : "disabled"}>Release</button>
          <button type="button" data-settle="refund" ${canWrite() ? "" : "disabled"}>Refund</button>
        </div>
        <p class="note">Settlement records the entitled party; it does not move value.
        External messages are finalization-only and non-functional in Studio, so a
        payout that cannot run here would be theatre.</p>
      </div>`
    : openAfterRefusal
      ? `<div class="card refused-card">
          <h3>Refused — deal still OPEN</h3>
          <p class="note">The gate declined the state transition, not just the call.
          Raise the tolerance or publish a better report, then lock again.</p>
          <p class="note">tolerance <b>${d.max_counterexamples}</b> ·
             worst published <b>${state.registry.worst}</b></p>
        </div>`
      : "";

  return `<div class="card">
    <h3>Escrow deal</h3>
    <div class="row">
      <label class="note">payee</label>
      <span class="mono">${esc(short(state.wallet?.address) )}</span>
      <label class="note">tolerance</label>
      <button type="button" data-tol="-1">−</button>
      <span class="mono" id="tol-val"><b>${state.tolerance}</b></span>
      <button type="button" data-tol="1">+</button>
      <span class="note">counterexamples the payer will accept</span>
    </div>
    <p class="${preview.allowed ? "note" : "note warn"}">
      ${preview.allowed ? "Expected to lock" : "Expected refusal"}: ${esc(preview.reason)}.
      <span class="note">The contract remains the authority — this is a preview.</span>
    </p>
    <div class="row">
      <button type="button" id="d-open" ${canWrite() && !state.busy ? "" : "disabled"}>
        1 · Open deal</button>
      <button type="button" id="d-lock"
        ${canWrite() && !state.busy && state.dealId ? "" : "disabled"}>
        2 · Lock 0.01 GEN</button>
      <span class="note mono">${esc(state.dealId || "no deal yet")}</span>
    </div>
    ${canWrite() ? "" : `<p class="note">${esc(writeBlockedReason())}</p>`}
    ${stateBlock}
  </div>`;
}

function paint() {
  if (!host) return;
  host.innerHTML = `
    <h2>Settlement</h2>
    <p>The escrow refuses to lock funds against a rule nobody has tested, or against
    findings worse than the payer accepted. Those are the only two gating inputs.</p>
    <div class="card">
      <div class="row">
        <label class="note">rule</label>
        <select id="s-rule">${ruleOptions()}</select>
        <button type="button" id="s-refresh">Refresh from chain</button>
      </div>
    </div>
    ${registryCard()}
    ${publishCard()}
    ${dealCard()}
    <h2>Transactions</h2>
    <div id="txq"></div>
    ${state.note ? `<p class="note warn">${esc(state.note)}</p>` : ""}`;

  txq = createTxQueue(host.querySelector("#txq"), { net: state.wallet?.net });
  bind();
}

function bind() {
  const q = (s) => host.querySelector(s);

  q("#s-rule").addEventListener("change", async (e) => {
    state.ruleHash = e.target.value;
    const match = state.reports.find((r) => r.rule_hash === state.ruleHash);
    state.ruleLabel = match?.rule_label || "untested";
    state.deal = null;
    state.dealId = null;
    state.note = "";
    paint();
    await refreshRegistry();
    // Default the stepper to the worst finding: the smallest tolerance that locks.
    state.tolerance = state.registry.worst;
    paint();
  });

  q("#s-refresh").addEventListener("click", async () => {
    state.note = "";
    await refreshRegistry();
    await refreshDeal();
    paint();
  });

  for (const btn of host.querySelectorAll("[data-tol]")) {
    btn.addEventListener("click", () => {
      const delta = Number(btn.dataset.tol);
      state.tolerance = Math.max(0, state.tolerance + delta);
      paint();
    });
  }

  for (const btn of host.querySelectorAll("[data-pub]")) {
    btn.addEventListener("click", () => doPublish(state.reports[Number(btn.dataset.pub)]));
  }

  const open = q("#d-open");
  if (open) open.addEventListener("click", doOpenDeal);
  const lock = q("#d-lock");
  if (lock) lock.addEventListener("click", doLock);

  for (const btn of host.querySelectorAll("[data-settle]")) {
    btn.addEventListener("click", () => doSettle(btn.dataset.settle));
  }
}

/**
 * Mount the settlement panel.
 *
 * `reports` are the committed artifacts (already fetched by the viewer) so this
 * component needs no fetching of its own and works unchanged in read-only mode: every
 * read still runs, every write button is disabled with a stated reason.
 */
export async function mountSettlement(el, { wallet, reports }) {
  host = el;
  state.wallet = wallet;
  state.reports = reports;
  if (!state.ruleHash) {
    state.ruleHash = reports[0]?.rule_hash || UNTESTED_RULE;
    state.ruleLabel = reports[0]?.rule_label || "untested";
  }
  paint();
  await refreshRegistry();
  state.tolerance = state.registry.worst;
  paint();
}

export function updateSettlementWallet(wallet) {
  state.wallet = wallet;
  if (host) paint();
}
