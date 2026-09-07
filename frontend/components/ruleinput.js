/* Rule input and probe browser — inspect exactly what will be tested.
 *
 * Two boundaries this component exists to keep visible:
 *
 *  1. A rule's on-chain identity is the sha256 of its NFKC- and whitespace-normalized
 *     text. Computing that here lets a user paste a rule and see its hash immediately,
 *     and `tests/frontend/hash_parity.mjs` proves the browser agrees with the CLI.
 *  2. Probe ids are NEVER recomputed in JS. They are sha256 over Python's canonical
 *     JSON, whose key ordering and escaping `JSON.stringify` does not reproduce. Ids
 *     come from the committed manifest, which is itself content-addressed and refuses
 *     to load if edited.
 *
 * Generating a new probe set stays a Python job. The adversary corpus is committed, its
 * prompt is published and hashed into every manifest, and a browser reimplementation
 * would fork the thing that makes a probe set auditable. This component says so rather
 * than offering a button that quietly does something weaker.
 */

import { MAX_RULE_CHARS, normalizeRule, ruleHash, ruleProblems } from "../lib/hash.js";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const state = {
  manifests: [],        // { file, path, set } committed probe manifests
  manifestIndex: 0,
  reports: [],
  text: "",
  hash: null,
  known: null,          // the committed report whose rule matches this hash, if any
  onSelect: null,       // (ruleHash, ruleLabel, probeSet) -> void
};

let host = null;

async function recompute() {
  const problems = ruleProblems(state.text);
  state.hash = problems.length ? null : await ruleHash(state.text);
  state.known = state.hash
    ? state.reports.find((r) => r.rule_hash === state.hash) || null
    : null;
  return problems;
}

function currentSet() {
  return state.manifests[state.manifestIndex]?.set || null;
}

function ruleCard(problems) {
  const norm = normalizeRule(state.text);
  const status = problems.length
    ? `<p class="note warn">${problems.map(esc).join(" · ")}</p>`
    : state.known
      ? `<p class="note">This is a <b>committed rule</b> (${esc(state.known.rule_label)}),
         already registered on chain with a published report — the settlement tab can
         gate on it.</p>`
      : `<p class="note warn">This rule is <b>not registered on chain</b>. Register it and
         run probes with the CLI before it can be tested or gated on:
         <span class="mono">python -m brightline.run &lt;agreement&gt; &lt;probeset&gt;</span></p>`;
  return `<div class="card">
    <h3>Rule under test</h3>
    <textarea id="r-text" rows="5" spellcheck="false"
      placeholder="Paste a resolution rule, e.g. Pay the contributor if the contributor delivers a working fix."
      >${esc(state.text)}</textarea>
    <div class="row" style="margin-top:8px">
      <span class="note">${norm.length} / ${MAX_RULE_CHARS} chars after normalization</span>
      <span class="grow"></span>
      <span class="note mono">${state.hash ? esc(state.hash) : "—"}</span>
    </div>
    ${norm && norm !== state.text
      ? `<p class="note">normalized: <span class="mono">${esc(norm.slice(0, 220))}</span></p>`
      : ""}
    ${status}
    <p class="note">The hash is sha256 of the NFKC- and whitespace-normalized text, so
    cosmetic edits keep the same identity and substantive ones do not. Computed here in
    the browser, and proven identical to the CLI by
    <span class="mono">tests/frontend/hash_parity.mjs</span>.</p>
  </div>`;
}

function probeSetCard() {
  const entry = state.manifests[state.manifestIndex];
  const set = currentSet();
  if (!set) return `<p class="note">No probe manifests found under probes/.</p>`;

  const opts = state.manifests.map((m, i) =>
    `<option value="${i}"${i === state.manifestIndex ? " selected" : ""}>
       ${esc(m.set.probe_set_id)} · ${m.set.n_probes} probes</option>`).join("");

  const quota = set.family_quota || {};
  const counts = set.family_counts || {};
  const families = Object.keys({ ...quota, ...counts }).sort().map((f) => {
    const have = counts[f] ?? 0;
    const want = quota[f] ?? 0;
    return `<tr><td>${esc(f)}</td><td class="num">${have}</td>
      <td class="num">${want}</td>
      <td>${have >= want ? "met" : "SHORT"}</td></tr>`;
  }).join("");

  const g = set.generated_from || {};
  const probes = (set.probes || []).map((p) => `<details class="card">
      <summary><b>#${p.index}</b> · ${esc(p.family)} ·
        <span class="mono">${esc(p.probe_id.slice(0, 18))}</span></summary>
      <div class="scen">${esc(p.scenario.narrative)}</div>
      <ul class="missing">${(p.scenario.facts || []).map((f) =>
        `<li><span class="mono">${esc(f.k)}</span>: ${esc(f.v)}</li>`).join("")}</ul>
      ${(p.scenario.evidence_absent || []).length
        ? `<p class="note">evidence absent: ${(p.scenario.evidence_absent || [])
            .map((x) => `<span class="pill">${esc(x)}</span>`).join(" ")}</p>` : ""}
    </details>`).join("");

  return `<div class="card">
    <h3>Probe set</h3>
    <div class="row">
      <label class="note">manifest</label>
      <select id="r-set">${opts}</select>
      <span class="note mono">${esc(entry.file)}</span>
    </div>
    <p class="note">Frozen and content-addressed: the manifest refuses to load if its
    contents no longer hash to its stated id. Probe ids come from the file and are never
    recomputed in the browser — Python's canonical JSON is the authority.</p>
    <div class="prov"><div>${["adversary_version", "adversary_prompt_hash", "generator",
      "generator_model", "corpus", "seed", "rule_hash"].map((k) =>
      `${k.padEnd(22)}${esc(g[k] ?? "—")}`).join("\n")}</div></div>
    <p class="note" style="margin-top:10px">Generated against rule
      <span class="mono">${esc((g.rule_hash || "").slice(0, 18))}</span>
      ${g.rule_hash === state.hash
        ? "— the rule above (this is the authored/frozen pairing)"
        : "— a <b>different</b> rule than the one above. Re-running a frozen set against a rewritten rule is the regression arm; it is deliberate, not a mismatch."}
    </p>
    <table style="margin-top:12px"><thead><tr>
      <th>family</th><th>probes</th><th>quota</th><th></th></tr></thead>
      <tbody>${families}</tbody></table>
    <h3 style="margin-top:18px">Scenarios (${(set.probes || []).length})</h3>
    <p class="note">Hermetic by construction: self-contained facts, no URLs, no live
    evidence. That is what makes divergence attributable to the rule.</p>
    ${probes}
    <p class="note">A <b>new</b> probe set is generated by the Python adversary, not here:
    the corpus is committed, the prompt is published and hashed into every manifest, and
    a browser reimplementation would fork the thing that makes a set auditable.</p>
  </div>`;
}

async function paint() {
  if (!host) return;
  const problems = await recompute();
  host.innerHTML = `
    <h2>Agreement</h2>
    <p>Inspect exactly what will be tested: the rule's on-chain identity, and every
    scenario in the frozen probe set.</p>
    ${ruleCard(problems)}
    ${probeSetCard()}
    <div class="row">
      <button type="button" id="r-use" ${state.hash && currentSet() ? "" : "disabled"}>
        Use this rule and probe set</button>
      <span class="note">sends the selection to the quick check and settlement tabs</span>
    </div>`;
  bind();
}

function bind() {
  const ta = host.querySelector("#r-text");
  if (ta) {
    let timer = null;
    ta.addEventListener("input", (e) => {
      state.text = e.target.value;
      // Debounced: hashing on every keystroke would repaint the textarea under the
      // cursor. Only the hash line needs to move, so update it in place.
      clearTimeout(timer);
      timer = setTimeout(async () => {
        await recompute();
        const line = host.querySelector(".row .mono");
        if (line) line.textContent = state.hash || "—";
      }, 250);
    });
    ta.addEventListener("blur", () => paint());
  }
  const sel = host.querySelector("#r-set");
  if (sel) sel.addEventListener("change", (e) => {
    state.manifestIndex = Number(e.target.value);
    paint();
  });
  const use = host.querySelector("#r-use");
  if (use) use.addEventListener("click", () => {
    if (state.onSelect && state.hash) {
      state.onSelect(state.hash, state.known?.rule_label || "custom", currentSet());
    }
  });
}

/**
 * Mount the agreement tab. `manifests` are pre-fetched committed probe files; nothing
 * here needs a wallet or a chain, so this tab works fully in read-only mode.
 */
export async function mountRuleInput(el, { manifests, reports, initialText, onSelect }) {
  host = el;
  state.manifests = manifests;
  state.reports = reports;
  state.text = initialText || "";
  state.onSelect = onSelect;
  state.manifestIndex = 0;
  await paint();
}
