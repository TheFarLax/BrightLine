/* Viewer wiring: mount the wallet header, load artifacts, render.
 *
 * All rendering lives in lib/render.js so it can be tested without a DOM. This file
 * only does I/O and event plumbing.
 */

import { mountWallet, onWalletChange, walletState } from "./components/wallet.js";
import { mountSettlement, updateSettlementWallet } from "./components/settlement.js";
import { esc, renderReport } from "./lib/render.js";

const $ = (sel) => document.querySelector(sel);

async function boot() {
  // The committed artifacts are readable with no chain and no wallet at all, so they
  // load first and nothing below is allowed to prevent that.
  let manifest;
  try {
    manifest = await (await fetch("../reports/index.json")).json();
  } catch {
    $("#app").innerHTML = `<div class="err"><b>No report index.</b> Generate one and
      serve the repo root:<br><code>python scripts/serve.py</code><br>
      then open <code>http://127.0.0.1:8800/frontend/</code></div>`;
    return;
  }

  // Tabs. The settlement panel is mounted lazily on first view so its chain reads do
  // not slow the reports page down.
  let settleMounted = false;
  const tabs = [
    ["#tab-reports", "#panel-reports"],
    ["#tab-settle", "#panel-settle"],
  ];
  const showTab = async (which) => {
    for (const [btn, panel] of tabs) {
      const on = btn === which;
      $(btn).setAttribute("aria-selected", String(on));
      $(panel).hidden = !on;
    }
    if (which === "#tab-settle" && !settleMounted) {
      settleMounted = true;
      try {
        await mountSettlement($("#panel-settle"),
          { wallet: walletState(), reports: manifest.reports });
      } catch (e) {
        $("#panel-settle").innerHTML =
          `<div class="err">settlement panel failed: ${esc(String(e.message))}</div>`;
      }
    }
  };
  for (const [btn] of tabs) $(btn).addEventListener("click", () => showTab(btn));

  // The wallet header owns network selection and proves the read client works before
  // any chain-backed panel is shown. A failure here must not stop the reports.
  try {
    await mountWallet($("#wallet"));
    onWalletChange((s) => {
      if (s.error) console.warn("[brightline]", s.error);
      // The settlement panel reads and writes through the wallet's clients, so it has
      // to follow network switches and connect/disconnect.
      updateSettlementWallet(s);
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

  const pick = $("#pick");
  pick.innerHTML = manifest.reports.map((f, i) =>
    `<option value="${i}">${esc(f.label)} — ${esc(f.file)}</option>`).join("");

  const diff = manifest.retest
    ? await (await fetch(`../${manifest.retest}`)).json().catch(() => null)
    : null;

  const load = async () => {
    const entry = manifest.reports[Number(pick.value) || 0];
    const r = await (await fetch(`../${entry.path}`)).json();
    $("#app").innerHTML = renderReport(r, entry.show_retest ? diff : null);
  };
  pick.addEventListener("change", load);
  await load();
}

boot();
