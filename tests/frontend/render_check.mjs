/* Render check for the viewer.
 *
 * There is no browser on this host, so "render it and look at it" becomes: run the
 * real render functions against the real report artifacts and assert on the HTML.
 * Catches what a syntax check cannot -- wrong field names, undefined reads, empty
 * sections. The browser test (browser_test.mjs) covers the wiring; this covers output.
 *
 *   node tests/frontend/render_check.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

import { renderReport } from "../../frontend/lib/render.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));

const index = read("reports/index.json");
const report = read(index.reports[0].path);
const retest = read(index.retest);

const html = renderReport(report, retest);

const checks = [
  ["rendered something", html.length > 3000],
  ["no literal undefined", !html.includes(">undefined<")],
  ["no NaN in output", !html.includes("NaN")],
  ["rule text present", html.includes("working fix")],
  ["K/N tile present", html.includes(`${report.metrics.K} / ${report.metrics.N}`)],
  ["noise floor tile", html.includes("noise floor")],
  ["per-probe rows", (html.match(/<tr>/g) || []).length >= report.probes.length],
  ["bars have widths", /style="width:\d/.test(html)],
  ["tau rule drawn", html.includes('class="tau"')],
  ["counterexample cards", (html.match(/class="card"/g) || []).length >= 1 +
    report.findings.length],
  ["decision camps labelled", html.includes("ACCEPT") && html.includes("INSUFFICIENT")],
  ["re-test arms present", html.includes("generalization") &&
    html.includes(retest.generalization.probe_set_fresh)],
  ["verdict rendered", html.includes("Verdict.")],
  ["provenance keys", html.includes("report_hash") && html.includes("adversary_prompt_hash")],
  ["panel models listed", html.includes("openai/gpt-5.1")],
];

// Every committed report must render without throwing, not just the first.
for (const entry of index.reports) {
  const r = read(entry.path);
  const out = renderReport(r, entry.show_retest ? retest : null);
  checks.push([`renders ${entry.file}`, out.length > 2000 && !out.includes(">undefined<")]);
}

let failed = 0;
for (const [name, ok] of checks) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failed++;
}
console.log(`\n${checks.length - failed}/${checks.length} render checks passed ` +
            `(${html.length} bytes of HTML)`);
assert.equal(failed, 0, `${failed} render check(s) failed`);
