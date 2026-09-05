/* Headless render check for the viewer.
 *
 * There is no browser on this host, so "render it and look at it" becomes: execute
 * the real render path against the real report artifacts with a minimal DOM stub,
 * then assert on the HTML it produces. Catches the failures a syntax check cannot --
 * wrong field names, undefined reads, empty sections.
 *
 *   node tests/frontend/render_check.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const read = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));

const index = read("reports/index.json");
const report = read(index.reports[0].path);
const retest = read(index.retest);

// Minimal DOM: the app only ever sets innerHTML and attaches listeners.
const nodes = {};
const makeNode = (id) => (nodes[id] = {
  innerHTML: "", value: "", addEventListener() {},
  setAttribute() {}, getAttribute: () => null,
});
["#app", "#pick", "#theme"].forEach(makeNode);

const ctx = {
  document: {
    querySelector: (sel) => nodes[sel] ?? makeNode(sel),
    documentElement: { setAttribute() {}, getAttribute: () => null },
  },
  fetch: async (url) => {
    const path = url.replace(/^\.\.\//, "");
    return { json: async () => read(path) };
  },
  console,
  setTimeout,
};
vm.createContext(ctx);
vm.runInContext(readFileSync(join(root, "frontend/app.js"), "utf8"), ctx);

// boot() is async; let its microtasks drain.
await new Promise((r) => setTimeout(r, 50));

const html = nodes["#app"].innerHTML;
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

let failed = 0;
for (const [name, ok] of checks) {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) failed++;
}
console.log(`\n${checks.length - failed}/${checks.length} render checks passed ` +
            `(${html.length} bytes of HTML)`);
assert.equal(failed, 0, `${failed} render check(s) failed`);
