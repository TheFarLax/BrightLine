/* Browser tests for the viewer, in a real Chromium.
 *
 * Covers what can be verified without a human:
 *
 *   A. read-only mode  -- no provider present. The page must load, import genlayer-js
 *      from the CDN, build a read client, and read live state off the real studionet
 *      deployment. A number on screen here proves the whole read path end to end.
 *   B. wallet path     -- a mock EIP-1193 provider is injected before page load. This
 *      exercises createClient({provider}) and client.connect() and records the exact
 *      RPC sequence genlayer-js emits, which is the integration contract.
 *
 * What it cannot cover: real MetaMask and the real `npm:genlayer-wallet-plugin` Snap.
 * Those need a human to approve an install prompt in a headed browser. The recorded
 * RPC sequence from case B is what a reviewer should compare against.
 *
 *   node tests/frontend/browser_test.mjs
 */

import { chromium } from "playwright";
import { spawn } from "node:child_process";
import net from "node:net";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const EXE = "/root/.cache/ms-playwright/chromium-1148/chrome-linux/chrome";
const PORT = 8811;
const URL = `http://127.0.0.1:${PORT}/frontend/`;
const ADDRESS = "0xCA71D5D065833919207316a62A61b599639500f0";

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
  ok ? pass++ : fail++;
};

/** Mock EIP-1193 provider. Records every method the SDK asks for. */
const MOCK_PROVIDER = (address) => `
window.__rpc = [];
window.ethereum = {
  isMetaMask: true,
  request: async ({ method, params }) => {
    window.__rpc.push(method);
    switch (method) {
      case "eth_requestAccounts":
      case "eth_accounts":            return ["${address}"];
      case "eth_chainId":             return "0xf22f";
      case "net_version":             return "61999";
      case "wallet_getSnaps":         return {};
      case "wallet_requestSnaps":     return { "npm:genlayer-wallet-plugin": { version: "0.0.0" } };
      case "wallet_addEthereumChain":
      case "wallet_switchEthereumChain": return null;
      case "wallet_invokeSnap":       return { address: "${address}" };
      default:
        window.__rpc.push("UNMOCKED:" + method);
        throw Object.assign(new Error("unmocked " + method), { code: 4200 });
    }
  },
  on: () => {}, removeListener: () => {},
};`;

async function withPage(browser, { provider = null, timeoutMs = 45000 } = {}) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e.message)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  // Record failed requests so a 404 names the resource instead of arriving as an
  // anonymous console error.
  page.on("requestfailed", (r) => errors.push(`requestfailed ${r.url()}`));
  page.on("response", (r) => {
    if (r.status() >= 400) errors.push(`http ${r.status()} ${r.url()}`);
  });
  if (provider) await page.addInitScript(provider);
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  return { ctx, page, errors };
}

async function main() {
  const server = spawn(join(root, ".venv/bin/python"),
    [join(root, "scripts/serve.py"), "--port", String(PORT)],
    { cwd: root, stdio: "ignore" });

  // Poll the port rather than sleeping: serve.py regenerates networks.json and the
  // report index first, so its start-up time is not fixed.
  const ready = await (async () => {
    for (let i = 0; i < 60; i++) {
      const ok = await new Promise((res) => {
        const s = net.connect(PORT, "127.0.0.1")
          .on("connect", () => { s.destroy(); res(true); })
          .on("error", () => res(false));
      });
      if (ok) return true;
      await new Promise((r) => setTimeout(r, 500));
    }
    return false;
  })();
  if (!ready) { server.kill(); throw new Error(`server never came up on ${PORT}`); }

  const browser = await chromium.launch({
    headless: true, executablePath: EXE,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });

  try {
    // ------------------------------------------------ A. read-only, no provider
    {
      const { ctx, page, errors } = await withPage(browser, { timeoutMs: 60000 });
      await page.waitForSelector("#wallet select#w-net", { timeout: 60000 });

      const nets = await page.$$eval("#w-net option", (o) => o.map((x) => x.value));
      check("read-only: network selector lists usable networks",
        nets.includes("studionet"), `saw ${JSON.stringify(nets)}`);

      const pill = await page.textContent("#wallet .pill").catch(() => "");
      check("read-only: shows a read-only badge, not an error",
        (pill || "").includes("read-only"), `pill was ${JSON.stringify(pill)}`);

      check("read-only: no Connect button without a provider",
        (await page.$("#w-connect")) === null);

      // The live read. Proves CDN import + createClient + readContract against the
      // real studionet deployment.
      await page.waitForFunction(
        () => /rulings on chain:\s*\d+/.test(document.querySelector("#wallet").innerText),
        null, { timeout: 40000 }).catch(() => {});
      const header = await page.innerText("#wallet");
      const m = header.match(/rulings on chain:\s*(\d+)/);
      check("read-only: live ruling_count read from studionet",
        !!m && Number(m[1]) > 0, `header was: ${header.replace(/\n/g, " | ")}`);

      const addrs = await page.$$eval("#wallet .bar.sub a", (a) => a.map((x) => x.textContent));
      check("read-only: all three contract addresses shown",
        addrs.length === 3 && addrs.every((t) => t && t.includes("…")),
        JSON.stringify(addrs));

      // Reports must still render with no wallet at all.
      await page.waitForSelector("#app .card", { timeout: 30000 });
      const cards = await page.$$eval("#app .card", (c) => c.length);
      check("read-only: report and counterexample cards render", cards >= 2, `${cards} cards`);
      const appText = await page.innerText("#app");
      check("read-only: counterexample decisions visible",
        appText.includes("ACCEPT") && appText.includes("INSUFFICIENT"));
      check("read-only: scope banner present",
        (await page.innerText(".scope")).includes("studionet lab instrument"));

      check("read-only: no uncaught page errors", errors.length === 0,
        errors.slice(0, 2).join(" ;; "));
      await ctx.close();
    }

    // -------------------------------------------- B. wallet path, mock provider
    {
      const { ctx, page, errors } = await withPage(browser,
        { provider: MOCK_PROVIDER(ADDRESS), timeoutMs: 60000 });
      await page.waitForSelector("#wallet select#w-net", { timeout: 60000 });

      const hasConnect = (await page.$("#w-connect")) !== null;
      check("wallet: Connect button appears when a provider exists", hasConnect);

      if (hasConnect) {
        await page.click("#w-connect");
        await page.waitForFunction(
          () => document.querySelector("#wallet .pill.ok") !== null ||
                document.querySelector("#wallet .err-line") !== null,
          null, { timeout: 40000 }).catch(() => {});

        const connected = (await page.$("#wallet .pill.ok")) !== null;
        const err = await page.textContent("#wallet .err-line").catch(() => null);
        check("wallet: connect() completed against the mock provider", connected,
          `error line: ${err}`);

        if (connected) {
          const pill = await page.textContent("#wallet .pill.ok");
          check("wallet: connected pill shows the account",
            pill.includes(ADDRESS.slice(0, 6)), pill);
          check("wallet: faucet offered on a sim-faucet network",
            (await page.$("#w-fund")) !== null);
        }

        const rpc = await page.evaluate(() => window.__rpc || []);
        const uniq = [...new Set(rpc)];
        console.log(`\n  RPC sequence genlayer-js emitted (${rpc.length} calls):`);
        for (const m of uniq) console.log(`      ${m}`);
        check("wallet: requested accounts", uniq.includes("eth_requestAccounts"));
        check("wallet: no unmocked RPC methods",
          !uniq.some((m) => m.startsWith("UNMOCKED:")),
          uniq.filter((m) => m.startsWith("UNMOCKED:")).join(", "));
      }

      check("wallet: no uncaught page errors", errors.length === 0,
        errors.slice(0, 2).join(" ;; "));
      await ctx.close();
    }
  } finally {
    await browser.close();
    server.kill();
  }

  console.log(`\n${pass}/${pass + fail} browser checks passed`);
  if (fail) process.exit(1);
}

main().catch((e) => { console.error("harness error:", e); process.exit(1); });
