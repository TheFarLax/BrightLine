/* Smoke test for the deployable bundle.
 *
 * `scripts/serve.py` serves the whole repository, so a page can load locally and still
 * be broken in production: an asset that was never copied into `dist/` is exactly the
 * kind of failure that only appears after deploying. This builds `dist/` into a temp
 * directory, serves *only* that directory over a plain static file server -- the same
 * contract a static host offers -- and checks that the app still reaches the chain.
 *
 * Any request that 404s fails the run. That is the whole point.
 *
 *   node tests/frontend/dist_smoke.mjs
 */

import { chromium } from "playwright";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { readFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, join, extname, normalize } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const EXE = "/root/.cache/ms-playwright/chromium-1148/chrome-linux/chrome";
const PORT = 8815;

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
  ok ? pass++ : fail++;
};

const TYPES = {
  ".html": "text/html", ".js": "text/javascript", ".json": "application/json",
  ".md": "text/plain", ".svg": "image/svg+xml",
};

/** Deliberately minimal: no rewriting, no fallbacks. A static host, and nothing more. */
function serveDir(dir, port) {
  const server = createServer(async (req, res) => {
    let p = normalize(decodeURIComponent(req.url.split("?")[0]));
    if (p.endsWith("/")) p += "index.html";
    try {
      const body = await readFile(join(dir, p));
      res.writeHead(200, { "content-type": TYPES[extname(p)] || "application/octet-stream" });
      res.end(body);
    } catch {
      res.writeHead(404, { "content-type": "text/plain" });
      res.end("not found");
    }
  });
  return new Promise((r) => server.listen(port, "127.0.0.1", () => r(server)));
}

async function main() {
  const out = await mkdtemp(join(tmpdir(), "bl-dist-"));
  const built = spawnSync(join(root, ".venv/bin/python"),
    [join(root, "scripts/build_static.py"), "--out", out], { cwd: root, encoding: "utf8" });
  check("build: scripts/build_static.py succeeds", built.status === 0,
    (built.stderr || built.stdout || "").slice(-400));
  if (built.status !== 0) { console.log(`\n${pass}/${pass + fail} checks passed`); process.exit(1); }

  const server = await serveDir(out, PORT);
  const browser = await chromium.launch({
    headless: true, executablePath: EXE,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage();
    const missing = [];
    page.on("response", (r) => { if (r.status() >= 400) missing.push(`${r.status()} ${r.url()}`); });

    // The root of the site must land on the app without anyone typing a subpath.
    await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: "domcontentloaded" });
    await page.waitForURL(/\/frontend\/$/, { timeout: 20000 }).catch(() => {});
    check("dist: the site root reaches the dApp",
      /\/frontend\/$/.test(page.url()), page.url());

    // A rendered report proves the index, the report body and the ES module graph all
    // shipped; a live registry number proves networks.json and the vendored SDK did.
    await page.waitForSelector("#app .card", { timeout: 60000 });
    check("dist: a report renders from the bundled artifacts",
      /counterexamples/.test(await page.innerText("#app")));
    check("dist: the vendored SDK loaded and read live studionet state",
      await page.waitForFunction(
        () => /rulings on chain:\s*\d+/.test(document.querySelector("#wallet").innerText),
        null, { timeout: 60000 }).then(() => true, () => false));

    // Every tab, because a panel that only mounts on click is exactly where a missing
    // asset hides.
    for (const [tab, sel] of [["#tab-rule", "#r-text"], ["#tab-quick", "#panel-quick .card"],
                              ["#tab-settle", "#panel-settle .card"]]) {
      await page.click(tab);
      const ok = await page.waitForSelector(sel, { timeout: 60000 }).then(() => true, () => false);
      check(`dist: ${tab.replace("#tab-", "")} panel mounts`, ok);
    }

    // Probe manifests are fetched lazily by the agreement tab.
    await page.click("#tab-rule");
    await page.waitForSelector("#panel-rule table", { timeout: 30000 }).catch(() => {});
    check("dist: probe manifests shipped",
      /ps_[0-9a-f]{8}/.test(await page.innerText("#panel-rule")));

    check("dist: no request 404s", missing.length === 0, missing.slice(0, 4).join(" ;; "));
  } finally {
    await browser.close();
    server.close();
    await rm(out, { recursive: true, force: true });
  }
  console.log(`\n${pass}/${pass + fail} dist checks passed`);
  process.exit(fail ? 1 : 0);
}

main().catch((e) => { console.error("harness error:", e); process.exit(1); });
