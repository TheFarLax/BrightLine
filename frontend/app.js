/* Viewer wiring: mount the wallet header, load artifacts, render.
 *
 * All rendering lives in lib/render.js so it can be tested without a DOM. This file
 * only does I/O and event plumbing.
 */

import { mountWallet, onWalletChange, walletState } from "./components/wallet.js";
import { mountSettlement, updateSettlementWallet } from "./components/settlement.js";
import { mountQuickCheck, updateQuickCheckWallet } from "./components/quickcheck.js";
import { mountRuleInput } from "./components/ruleinput.js";
import { esc, renderReport } from "./lib/render.js";

const $ = (sel) => document.querySelector(sel);

async function boot() {
  // The committed artifacts are readable with no chain and no wallet at all, so they
  // load first and nothing below is allowed to prevent that.
  let manifest;
  try {
    const res = await fetch("../reports/index.json");
    if (!res.ok) throw new Error(`index.json ${res.status}`);
    manifest = await res.json();
  } catch (e) {
    $("#app").removeAttribute("aria-busy");
    $("#app").innerHTML = `<div class="err"><b>No report index.</b>
      <span class="mono">${esc(String(e.message))}</span><br>
      The viewer reads committed artifacts from the repo root, so it has to be served
      from there:<br><code>python scripts/serve.py</code><br>
      then open <code>http://127.0.0.1:8800/frontend/</code></div>`;
    return;
  }

  // Tabs. The settlement panel is mounted lazily on first view so its chain reads do
  // not slow the reports page down.
  const mounted = new Set();
  // The selection flows Agreement -> Quick check / Settlement, so it lives here rather
  // than inside any one component.
  let selection = null;
  const tabs = [
    ["#tab-reports", "#panel-reports"],
    ["#tab-rule", "#panel-rule"],
    ["#tab-quick", "#panel-quick"],
    ["#tab-settle", "#panel-settle"],
  ];

  const probeSets = manifest.probe_sets || [];
  let manifestBodies = null;
  const loadProbeSets = async () => {
    if (manifestBodies) return manifestBodies;
    manifestBodies = [];
    for (const entry of probeSets) {
      try {
        manifestBodies.push({ ...entry, set: await (await fetch(`../${entry.path}`)).json() });
      } catch { /* a missing manifest is skipped, not fatal */ }
    }
    return manifestBodies;
  };
  const showTab = async (which, { focus = false } = {}) => {
    for (const [btn, panel] of tabs) {
      const on = btn === which;
      $(btn).setAttribute("aria-selected", String(on));
      // Roving tabindex: one stop in the tab order, arrow keys move within.
      $(btn).tabIndex = on ? 0 : -1;
      $(panel).hidden = !on;
    }
    if (focus) $(which).focus();
    if (mounted.has(which)) return;
    mounted.add(which);
    try {
      if (which === "#tab-settle") {
        await mountSettlement($("#panel-settle"),
          { wallet: walletState(), reports: manifest.reports });
      } else if (which === "#tab-rule") {
        const sets = await loadProbeSets();
        const first = manifest.reports[0];
        const body = first ? await (await fetch(`../${first.path}`)).json() : null;
        await mountRuleInput($("#panel-rule"), {
          manifests: sets, reports: manifest.reports,
          initialText: body?.rule?.rule_text || "",
          onSelect: (hash, label, set) => {
            selection = { hash, label, set };
            // Re-mount the quick check so it picks up the new selection.
            mounted.delete("#tab-quick");
            showTab("#tab-quick");
          },
        });
      } else if (which === "#tab-quick") {
        const sets = await loadProbeSets();
        const chosen = selection?.set
          || sets.find((m) => m.probe_set_id === "ps_6ce467da9d20c1f2")?.set
          || sets[0]?.set;
        const rule = selection?.hash || manifest.reports[0]?.rule_hash;
        await mountQuickCheck($("#panel-quick"), {
          wallet: walletState(), probeSet: chosen, ruleHash: rule,
          ruleLabel: selection?.label || manifest.reports[0]?.rule_label || "",
        });
      }
    } catch (e) {
      // Un-mount so the retry button is a real retry and not a no-op.
      mounted.delete(which);
      const panel = $(which.replace("#tab-", "#panel-"));
      panel.innerHTML = `<div class="err"><b>This panel could not load.</b>
        <div class="mono" style="margin:6px 0">${esc(String(e.message))}</div>
        Reports and the agreement tab need no chain; the chain-backed panels depend on
        the hosted RPC, which rate-limits under load.
        <div class="row" style="margin-top:10px">
          <button type="button" data-retry>Try again</button></div></div>`;
      const btn = panel.querySelector("[data-retry]");
      if (btn) btn.addEventListener("click", () => showTab(which));
    }
  };
  for (const [btn] of tabs) $(btn).addEventListener("click", () => showTab(btn));

  // Arrow-key navigation between tabs, per the WAI-ARIA tabs pattern.
  const order = tabs.map(([b]) => b);
  for (const btn of order) {
    $(btn).addEventListener("keydown", (e) => {
      const step = { ArrowRight: 1, ArrowLeft: -1, Home: -Infinity, End: Infinity }[e.key];
      if (step === undefined) return;
      e.preventDefault();
      const i = order.indexOf(btn);
      const next = step === -Infinity ? 0 : step === Infinity ? order.length - 1
        : (i + step + order.length) % order.length;
      showTab(order[next], { focus: true });
    });
  }

  // The flow strip is the same navigation, told as a pipeline.
  for (const b of document.querySelectorAll(".flow [data-goto]")) {
    b.addEventListener("click", () => {
      showTab(b.dataset.goto);
      $(b.dataset.goto.replace("#tab-", "#panel-")).scrollIntoView(
        { behavior: "smooth", block: "start" });
    });
  }

  // The wallet header owns network selection and proves the read client works before
  // any chain-backed panel is shown.
  //
  // It is deliberately *not* awaited here. Its first act is a live chain read, and the
  // reports are committed artifacts that need no network at all -- awaiting it would
  // hold the primary content behind a hosted RPC that rate-limits under load. The
  // listener is registered before the mount so the first state emission is not missed.
  onWalletChange((s) => {
    if (s.error) console.warn("[brightline]", s.error);
    // The settlement panel reads and writes through the wallet's clients, so it has
    // to follow network switches and connect/disconnect.
    updateSettlementWallet(s);
    updateQuickCheckWallet(s);
  });
  const walletReady = mountWallet($("#wallet")).catch((e) => {
    $("#wallet").removeAttribute("aria-busy");
    $("#wallet").innerHTML =
      `<div class="bar err-line">wallet header unavailable: ${esc(String(e.message))}` +
      ` — reports below still work</div>`;
  });

  // Theme choice persists: a reviewer who picks light mode should not lose it on the
  // next reload of a demo.
  const root = document.documentElement;
  const stored = (() => { try { return localStorage.getItem("bl-theme"); } catch { return null; } })();
  if (stored) root.setAttribute("data-theme", stored);
  $("#theme").addEventListener("click", () => {
    const now = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", now);
    try { localStorage.setItem("bl-theme", now); } catch { /* private mode */ }
  });

  const pick = $("#pick");
  if (!manifest.reports.length) {
    $("#app").removeAttribute("aria-busy");
    $("#app").innerHTML = `<div class="empty">No reports have been generated yet.
      Run <code>python -m brightline.run &lt;agreement&gt; &lt;probeset&gt;</code>,
      then reload.</div>`;
    return;
  }
  pick.innerHTML = manifest.reports.map((f, i) =>
    `<option value="${i}">${esc(f.label)} — ${esc(f.file)}</option>`).join("");

  // The re-test table is an enrichment of the baseline report, not a requirement:
  // a transport failure here must degrade to "no table", never to a blank page.
  const diff = manifest.retest
    ? await fetch(`../${manifest.retest}`).then((r) => r.json()).catch(() => null)
    : null;

  const load = async () => {
    const entry = manifest.reports[Number(pick.value) || 0];
    const app = $("#app");
    app.setAttribute("aria-busy", "true");
    app.innerHTML = `<div class="skel w40" style="height:20px"></div>
      <div class="skel tall"></div><div class="skel"></div><div class="skel w60"></div>`;
    try {
      const res = await fetch(`../${entry.path}`);
      if (!res.ok) throw new Error(`${entry.file} ${res.status}`);
      app.innerHTML = renderReport(await res.json(), entry.show_retest ? diff : null);
    } catch (e) {
      app.innerHTML = `<div class="err"><b>Could not load ${esc(entry.file)}.</b>
        <div class="mono" style="margin:6px 0">${esc(String(e.message))}</div>
        <div class="row"><button type="button" id="rp-retry">Try again</button></div></div>`;
      app.querySelector("#rp-retry").addEventListener("click", load);
    }
    app.removeAttribute("aria-busy");
  };
  pick.addEventListener("change", load);
  await load();
  await walletReady;
}

boot();
