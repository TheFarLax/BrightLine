/* Viewer wiring: mount the wallet header, load artifacts, render.
 *
 * All rendering lives in lib/render.js so it can be tested without a DOM. This file
 * only does I/O and event plumbing.
 */

import { mountWallet, onWalletChange } from "./components/wallet.js";
import { esc, renderReport } from "./lib/render.js";

const $ = (sel) => document.querySelector(sel);

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
    $("#app").innerHTML = renderReport(r, entry.show_retest ? diff : null);
  };
  pick.addEventListener("change", load);
  await load();
}

boot();
