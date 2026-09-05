/* Brightline viewer.
 *
 * Reads the committed report artifacts and renders them. Deliberately dependency-free
 * and build-free: the reports are the product of on-chain runs, and a viewer that can
 * rot is worse than no viewer.
 *
 * Encoding choices, per the data-viz method:
 *  - K/N and the noise floor are single headline numbers, so they are stat tiles, not
 *    charts.
 *  - Divergence is a magnitude, so bars use one sequential hue. Identity comes from
 *    row labels and direct value labels, never from colour alone, so no legend is
 *    needed and no status colour is borrowed for "split".
 *  - The tau threshold is a neutral 1px reference rule, not a second hue.
 */

import { mountWallet, onWalletChange } from "./components/wallet.js";

const $ = (sel) => document.querySelector(sel);
const fmt = (v, d = 4) => (v === null || v === undefined ? "n/a" : Number(v).toFixed(d));
const pct = (v) => (v === null || v === undefined ? 0 : Math.max(0, Math.min(1, v)) * 100);

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function tile(k, v, note) {
  return `<div class="tile"><div class="k">${esc(k)}</div>
    <div class="v">${esc(v)}</div>
    ${note ? `<div class="n">${esc(note)}</div>` : ""}</div>`;
}

/** Horizontal bar with a direct value label and an optional threshold rule. */
function bar(value, tau) {
  const rule = tau === undefined ? ""
    : `<span class="tau" style="left:${pct(tau)}%"></span>`;
  return `<div class="track">${rule}
    <div class="fill" style="width:${pct(value)}%"></div></div>`;
}

function metricTiles(r) {
  const m = r.metrics;
  return `<div class="tiles">
    ${tile("counterexamples", `${m.K} / ${m.N}`, `probes where the panel split (τ ${m.tau})`)}
    ${tile("noise floor", fmt(m.noise_floor), "same-model self-disagreement")}
    ${tile("mean divergence", fmt(m.split_mean), `max ${fmt(m.split_max)}`)}
    ${tile("unanimous INSUFFICIENT", m.unanimous_insufficient, "rule decidably silent")}
    ${tile("inconclusive", fmt(m.inconclusive_rate), "excluded from both sides")}
  </div>`;
}

function probeTable(r) {
  const tau = r.metrics.tau;
  const rows = [...r.probes].sort((a, b) => a.index - b.index).map((p) => {
    const d = p.divergence;
    const dist = Object.entries(p.distribution || {})
      .map(([k, v]) => `${k} ${v}`).join(" · ") || "—";
    const state = d === null ? "unmeasurable" : d >= tau ? "split" : "converged";
    return `<tr>
      <td class="num">#${p.index}</td>
      <td>${esc(p.family)}</td>
      <td class="bar-cell">${bar(d, tau)}</td>
      <td class="num">${fmt(d, 3)}</td>
      <td>${esc(state)}</td>
      <td class="mono">${esc(dist)}</td>
    </tr>`;
  }).join("");
  return `<table>
    <thead><tr><th>probe</th><th>family</th>
      <th>divergence (bar), τ marked</th><th>value</th><th>state</th>
      <th>decisions</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function findings(r) {
  if (!r.findings.length) {
    return `<p>No probe reached the threshold in this run. That is a statement about
      this probe set and this panel, not a guarantee.</p>`;
  }
  return r.findings.map((f) => {
    const camps = Object.entries(f.camps).sort().map(([decision, members]) => {
      const who = members.map((c) =>
        `${esc(c.model.split("/").pop())} (${c.confidence})`).join(", ");
      return `<div class="camp"><span class="dot"></span>
        <span class="lab">${esc(decision)}</span>
        <span class="who">${who}</span></div>`;
    }).join("");
    const first = Object.entries(f.camps).sort()[0]?.[1]?.[0];
    const missing = (f.missing_specification || [])
      .map((x) => `<li>${esc(x)}</li>`).join("");
    return `<div class="card">
      <h3>probe #${f.index} · ${esc(f.family)} · divergence ${fmt(f.divergence, 3)}</h3>
      <div class="scen">${esc(f.scenario?.narrative || "")}</div>
      ${camps}
      ${first ? `<div class="why">${esc(first.reason)}</div>` : ""}
      ${missing ? `<p class="missing-h">Missing specification (advisory, derived
        off-chain):</p><ul class="missing">${missing}</ul>` : ""}
    </div>`;
  }).join("");
}

function retest(d) {
  if (!d) return "";
  const arms = [
    ["baseline", d.rule_before.label, "frozen", d.rule_before.K, d.rule_before.N,
      d.rule_before.split_mean],
    ["regression", d.rule_after.label, "frozen (same ids)", d.rule_after.K,
      d.rule_after.N, d.rule_after.split_mean],
  ];
  if (d.generalization) {
    arms.push(["generalization", d.rule_after.label,
      `fresh ${d.generalization.probe_set_fresh}`, d.generalization.K,
      d.generalization.N, d.generalization.split_mean]);
  }
  const rows = arms.map(([arm, rule, set, K, N, mean]) => `<tr>
      <td>${esc(arm)}</td><td class="mono">${esc(rule)}</td>
      <td class="mono">${esc(set)}</td>
      <td class="bar-cell">${bar(N ? K / N : 0)}</td>
      <td class="num">${K} / ${N}</td>
      <td class="num">${fmt(mean, 3)}</td></tr>`).join("");
  return `<h2>Re-test loop</h2>
    <p>The fresh arm is not optional: without it a rule can be tuned to pass a corpus
    it has already seen.</p>
    <table><thead><tr><th>arm</th><th>rule</th><th>probe set</th>
      <th>counterexamples (bar)</th><th>K / N</th><th>mean div</th></tr></thead>
      <tbody>${rows}</tbody></table>
    ${d.verdict ? `<p style="margin-top:12px"><b>Verdict.</b> ${esc(d.verdict)}</p>` : ""}`;
}

function provenance(r) {
  const p = r.provenance;
  const keys = ["network", "contract_address", "runner_depends", "rule_hash",
    "probe_set_id", "adversary_version", "adversary_prompt_hash", "probe_generator",
    "channel", "panel_size", "wall_seconds", "generated_at"];
  const lines = keys.map((k) =>
    `<div>${k.padEnd(24)}${esc(p[k])}</div>`).join("");
  return `<h2>Provenance</h2>
    <p>A report is a property of this tuple, not of a sentence. Two reports are only
    comparable when it matches.</p>
    <div class="prov">${lines}
      <div>${"report_hash".padEnd(24)}${esc(r.report_hash)}</div>
      <div>${"panel_models".padEnd(24)}${esc((p.panel_models || []).join(", "))}</div>
    </div>`;
}

function render(r, diff) {
  $("#app").innerHTML = `
    <h2>Rule under test</h2>
    <div class="card"><span class="mono">${esc(r.rule.label)} ·
      ${esc(r.rule.rule_hash.slice(0, 18))}</span>
      <div class="scen">${esc(r.rule.normalized)}</div></div>
    <h2>Findings</h2>
    ${metricTiles(r)}
    <h2>Per probe</h2>
    ${probeTable(r)}
    <h2>Counterexamples</h2>
    <p>The output that matters. Each card is a scenario where independent models did
    not reach the same decision, with the reason each camp gave.</p>
    ${findings(r)}
    ${retest(diff)}
    ${provenance(r)}`;
}

async function boot() {
  // The wallet header owns network selection and proves the read client works before
  // any report is rendered. A failure there must not stop the reports from loading:
  // the committed artifacts are readable with no chain and no wallet at all.
  try {
    await mountWallet($("#wallet"));
    onWalletChange((s) => {
      if (s.error) console.warn("[brightline]", s.error);
    });
  } catch (e) {
    $("#wallet").innerHTML =
      `<div class="bar err-line">wallet header unavailable: ${String(e.message)}` +
      ` — reports below still work</div>`;
  }

  const themeBtn = $("#theme");
  themeBtn.addEventListener("click", () => {
    const root = document.documentElement;
    const now = root.getAttribute("data-theme");
    root.setAttribute("data-theme", now === "dark" ? "light" : "dark");
  });

  let manifest;
  try {
    manifest = await (await fetch("../reports/index.json")).json();
  } catch (e) {
    $("#app").innerHTML = `<div class="err"><b>No report index.</b> Generate one and
      serve the repo root:<br><code>python scripts/serve.py</code><br>
      then open <code>http://127.0.0.1:8800/frontend/</code></div>`;
    return;
  }

  const pick = $("#pick");
  pick.innerHTML = manifest.reports.map((f, i) =>
    `<option value="${i}">${esc(f.label)} — ${esc(f.file)}</option>`).join("");

  const diff = manifest.retest
    ? await (await fetch(`../${manifest.retest}`)).json().catch(() => null)
    : null;

  const load = async () => {
    const entry = manifest.reports[Number(pick.value) || 0];
    const r = await (await fetch(`../${entry.path}`)).json();
    render(r, entry.show_retest ? diff : null);
  };
  pick.addEventListener("change", load);
  await load();
}

boot();
