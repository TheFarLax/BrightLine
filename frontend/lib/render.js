/* Pure rendering for the Brightline viewer.
 *
 * No imports, no DOM access, no fetch: every function here maps report JSON to an HTML
 * string. That keeps it directly testable in Node against the committed artifacts,
 * which is the only way to "look at the output" on a host with no browser.
 *
 * Encoding choices, per the data-viz method:
 *  - K/N and the noise floor are single headline numbers, so they are stat tiles, not
 *    charts.
 *  - Divergence is a magnitude, so bars use one sequential hue. Identity comes from
 *    row labels and direct value labels, never from colour alone, so no legend is
 *    needed and no status colour is borrowed for "split".
 *  - The tau threshold is a neutral 1px reference rule, not a second hue.
 */

export const fmt = (v, d = 4) => (v === null || v === undefined ? "n/a" : Number(v).toFixed(d));
export const pct = (v) => (v === null || v === undefined ? 0 : Math.max(0, Math.min(1, v)) * 100);

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function tile(k, v, note) {
  return `<div class="tile"><div class="k">${esc(k)}</div>
    <div class="v">${esc(v)}</div>
    ${note ? `<div class="n">${esc(note)}</div>` : ""}</div>`;
}

/** Horizontal bar with a direct value label and an optional threshold rule. */
export function bar(value, tau) {
  const rule = tau === undefined ? ""
    : `<span class="tau" style="left:${pct(tau)}%"></span>`;
  return `<div class="track">${rule}
    <div class="fill" style="width:${pct(value)}%"></div></div>`;
}

export function metricTiles(r) {
  const m = r.metrics;
  return `<div class="tiles">
    ${tile("counterexamples", `${m.K} / ${m.N}`, `probes where the panel split (τ ${m.tau})`)}
    ${tile("noise floor", fmt(m.noise_floor), "same-model self-disagreement")}
    ${tile("mean divergence", fmt(m.split_mean), `max ${fmt(m.split_max)}`)}
    ${tile("unanimous INSUFFICIENT", m.unanimous_insufficient, "rule decidably silent")}
    ${tile("inconclusive", fmt(m.inconclusive_rate), "excluded from both sides")}
  </div>`;
}

export function probeTable(r) {
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

export function findings(r) {
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

export function retest(d) {
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

export function provenance(r) {
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

/** Full report body as HTML. Returns a string so callers own where it lands. */
export function renderReport(r, diff) {
  return `
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

