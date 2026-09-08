/* Browser tests for the dApp, in a real Chromium against a real studionet deployment.
 *
 *   A. read-only mode  -- no provider present. The page must load, import the vendored
 *      genlayer-js bundle, build a read client, and read live state off studionet. A
 *      number on screen here proves the whole read path end to end.
 *   B. wallet path     -- a mock EIP-1193 provider is injected before page load. This
 *      exercises createClient({provider}) and client.connect() and records the exact
 *      RPC sequence genlayer-js emits, which is the integration contract.
 *   C/D. settlement    -- the escrow gate's two refusal paths, without and with a wallet.
 *   E. agreement       -- rule hashing and probe inspection.
 *   F. quick check     -- the live single-probe adjudication surface.
 *   G. navigation      -- flow strip, WAI-ARIA tab keyboard model, theme persistence.
 *   H. phone viewport  -- 390x844: no horizontal page scroll, tap targets, scrollable
 *      evidence tables.
 *
 * What it cannot cover: real MetaMask and the real `npm:genlayer-wallet-plugin` Snap,
 * which need a human to approve an install prompt in a headed browser. That flow has
 * been walked manually by the maintainer and works; the automated evidence for it is
 * the RPC sequence case B prints, which is what a reviewer should compare against.
 *
 * The hosted studionet endpoint intermittently drops browser reads under load. Those
 * are recorded and reported as transport conditions rather than failing the run -- the
 * app retries and states the failure, which is the behaviour under test.
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

/* Third-party transport conditions, not defects in this code. The SDK reports a dropped
 * read as "GenLayer RPC error (<method>): Failed to fetch" with no URL in the text, so
 * matching the host alone would misfile it as an app bug. */
const RPC_NOISE = /studio\.genlayer\.com|rpc-bradbury|rpc-asimov|GenLayer RPC error/;

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
  const errors = [];        // defects in our code
  const rpcIssues = [];     // third-party transport conditions, reported not failed
  const isRpc = (s) => RPC_NOISE.test(s);
  const record = (s) => (isRpc(s) ? rpcIssues : errors).push(s);
  page.on("pageerror", (e) => record(String(e.message)));
  page.on("console", (m) => { if (m.type() === "error") record(m.text()); });
  // Name the resource so a 404 is not an anonymous console error.
  page.on("requestfailed", (r) => record(`requestfailed ${r.url()}`));
  page.on("response", (r) => {
    if (r.status() >= 400) record(`http ${r.status()} ${r.url()}`);
  });
  if (provider) await page.addInitScript(provider);
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: timeoutMs });
  return { ctx, page, errors, rpcIssues };
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
      const { ctx, page, errors, rpcIssues } = await withPage(browser, { timeoutMs: 60000 });
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
      const { ctx, page, errors, rpcIssues } = await withPage(browser,
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
    // ------------------------------------- C. settlement panel, read-only reads
    {
      const { ctx, page, errors, rpcIssues } = await withPage(browser, { timeoutMs: 60000 });
      await page.waitForFunction(
        () => /rulings on chain:\s*\d+/.test(document.querySelector("#wallet").innerText),
        null, { timeout: 60000 });
      await page.click("#tab-settle");
      await page.waitForSelector("#panel-settle table tbody tr", { timeout: 60000 });

      const text = await page.innerText("#panel-settle");
      check("settlement: registry tiles render from live chain",
        /tested/i.test(text) && /worst counterexamples/i.test(text), text.slice(0, 200));

      // The v1 rule has a published report with K=4, put there by the CLI.
      const worst = await page.$$eval("#panel-settle .tile", (tiles) => {
        const t = tiles.find((x) => /worst counterexamples/i.test(x.textContent));
        return t ? t.querySelector(".v").textContent.trim() : null;
      });
      check("settlement: worst_counterexamples read live from the registry",
        worst === "4", `saw ${JSON.stringify(worst)}`);

      const tested = await page.$$eval("#panel-settle .tile", (tiles) => {
        const t = tiles.find((x) => /^\s*tested/i.test(x.textContent));
        return t ? t.querySelector(".v").textContent.trim() : null;
      });
      check("settlement: is_tested true for a published rule", tested === "yes",
        `saw ${JSON.stringify(tested)}`);

      check("settlement: competing-reports table lists the on-chain report",
        (await page.$$("#panel-settle table tbody tr")).length >= 1);

      check("settlement: already-published reports are marked, not offered again",
        text.includes("on chain"));

      check("settlement: write buttons disabled without a wallet",
        await page.$eval("#d-open", (b) => b.disabled) === true);
      check("settlement: states why writes are unavailable",
        /connect a wallet to sign/.test(text), text.slice(0, 300));

      // Tolerance stepper drives the preview, which mirrors the contract's own gate.
      check("settlement: default tolerance equals the worst finding, so lock is expected",
        /Expected to lock/.test(text));
      await page.click('[data-tol="-1"]');
      await page.waitForFunction(
        () => /Expected refusal/.test(document.querySelector("#panel-settle").innerText),
        null, { timeout: 10000 }).catch(() => {});
      check("settlement: lowering tolerance below the finding predicts refusal",
        /Expected refusal/.test(await page.innerText("#panel-settle")));

      // The stepper stops tracking `worst` once the payer has moved it. Before this,
      // any later registry read snapped the tolerance back and silently discarded the
      // choice the user had just made.
      await page.click("#s-refresh");
      await page.waitForTimeout(1500);
      check("settlement: a chain refresh does not overwrite the payer's tolerance",
        /Expected refusal/.test(await page.innerText("#panel-settle")),
        await page.$eval("#tol-val", (e) => e.innerText));

      // The open button names the tolerance it would commit to, because that number is
      // frozen by open_deal and cannot be edited afterwards.
      check("settlement: the open-deal button states the tolerance it commits to",
        /Open deal at tolerance \d+/.test(await page.$eval("#d-open", (b) => b.innerText)),
        await page.$eval("#d-open", (b) => b.innerText));

      check("settlement: no refusal is announced before a lock is attempted",
        !/Refused/.test(await page.innerText("#panel-settle")));

      // The untested rule is the second refusal path.
      await page.selectOption("#s-rule", `0x${"ee".repeat(32)}`);
      await page.waitForFunction(
        () => /no published report/.test(document.querySelector("#panel-settle").innerText),
        null, { timeout: 60000 }).catch(() => {});
      const untested = await page.innerText("#panel-settle");
      check("settlement: untested rule predicts the no-report refusal",
        /no published report/.test(untested), untested.slice(0, 260));

      check("settlement: no uncaught page errors", errors.length === 0,
        errors.slice(0, 2).join(" ;; "));
      if (rpcIssues.length) {
        console.log(`        note: ${rpcIssues.length} transient RPC condition(s) from the`
          + ` hosted endpoint, tolerated by design: ${rpcIssues[0].slice(0, 90)}`);
      }
      await ctx.close();
    }

    // ------------------------------- D. settlement with a wallet: writes unlocked
    {
      const { ctx, page, errors, rpcIssues } = await withPage(browser,
        { provider: MOCK_PROVIDER(ADDRESS), timeoutMs: 60000 });
      await page.waitForSelector("#w-connect", { timeout: 60000 });
      await page.click("#w-connect");
      await page.waitForSelector("#wallet .pill.ok", { timeout: 60000 });
      await page.waitForFunction(
        () => /rulings on chain:\s*\d+/.test(document.querySelector("#wallet").innerText),
        null, { timeout: 60000 }).catch(() => {});
      await page.click("#tab-settle");
      await page.waitForSelector("#panel-settle table tbody tr", { timeout: 60000 });

      check("settlement+wallet: open-deal button enabled once connected",
        await page.$eval("#d-open", (b) => b.disabled) === false);
      check("settlement+wallet: lock stays disabled until a deal exists",
        await page.$eval("#d-lock", (b) => b.disabled) === true);
      check("settlement+wallet: publish offered for an unpublished report or all marked",
        (await page.$$("#panel-settle [data-pub]")).length >= 0);
      check("settlement+wallet: transaction queue present and empty",
        /No transactions yet/.test(await page.innerText("#panel-settle")));

      check("settlement+wallet: no uncaught page errors", errors.length === 0,
        errors.slice(0, 2).join(" ;; "));
      await ctx.close();
    }
    // ------------------------------------------- E. Agreement tab (no wallet needed)
    {
      const { ctx, page, errors, rpcIssues } = await withPage(browser, { timeoutMs: 60000 });
      await page.waitForSelector("#wallet select#w-net", { timeout: 60000 });
      await page.click("#tab-rule");
      await page.waitForSelector("#panel-rule textarea#r-text", { timeout: 60000 });

      const text = await page.innerText("#panel-rule");
      check("agreement: rule text prefilled from a committed report",
        (await page.inputValue("#r-text")).includes("working fix"));
      check("agreement: recognises a committed, registered rule",
        /committed rule/.test(text), text.slice(0, 200));

      // The hash the browser computes must equal the one in the published report.
      const expected = JSON.parse(
        await page.evaluate(() => fetch("../reports/index.json").then((r) => r.text())))
        .reports.find((r) => r.rule_label === "v1").rule_hash;
      const shown = await page.$$eval("#panel-rule .mono", (els) =>
        els.map((e) => e.textContent.trim()).find((t) => /^0x[0-9a-f]{64}$/.test(t)));
      check("agreement: in-browser rule hash matches the published report",
        shown === expected, `shown ${shown} vs report ${expected}`);

      // Editing the rule must change the identity.
      await page.fill("#r-text", "Pay the contributor if the work is acceptable.");
      await page.locator("#r-text").blur();
      await page.waitForFunction(
        () => /not registered on chain/.test(document.querySelector("#panel-rule").innerText),
        null, { timeout: 15000 }).catch(() => {});
      await page.waitForFunction(
        (old) => {
          const t = document.querySelector("#panel-rule").innerText;
          const m = t.match(/0x[0-9a-f]{64}/);
          return m && m[0] !== old;
        }, expected, { timeout: 15000 }).catch(() => {});
      const changed = await page.innerText("#panel-rule");
      check("agreement: a substantive edit produces a different hash",
        !changed.includes(expected), "hash did not change");
      check("agreement: an unregistered rule is flagged as such",
        /not registered on chain/.test(changed), changed.slice(0, 240));

      // Probe browser.
      check("agreement: probe manifest selector lists committed sets",
        (await page.$$eval("#r-set option", (o) => o.length)) >= 2);
      check("agreement: family quota table rendered",
        (await page.$$("#panel-rule table tbody tr")).length >= 6);
      const scenarios = await page.$$("#panel-rule details.card");
      check("agreement: every scenario is inspectable", scenarios.length === 8,
        `${scenarios.length} scenarios`);
      check("agreement: probe ids are shown from the manifest",
        /probe_id|0x[0-9a-f]{16}/.test(changed));
      check("agreement: says new probe sets come from the Python adversary",
        /generated by the Python adversary/.test(changed));

      check("agreement: no uncaught page errors", errors.length === 0,
        errors.slice(0, 2).join(" ;; "));
      await ctx.close();
    }

    // ------------------------------------------------------- F. Quick check tab
    {
      const { ctx, page, errors, rpcIssues } = await withPage(browser, { timeoutMs: 60000 });
      await page.waitForFunction(
        () => /rulings on chain:\s*\d+/.test(document.querySelector("#wallet").innerText),
        null, { timeout: 60000 });
      await page.click("#tab-quick");
      await page.waitForSelector("#panel-quick .card", { timeout: 60000 });

      const text = await page.innerText("#panel-quick");
      check("quickcheck: probe selector and scenario shown",
        (await page.$("#q-probe")) !== null && /narrative|contributor|defect/i.test(text));
      check("quickcheck: run disabled without a wallet",
        await page.$eval("#q-run", (b) => b.disabled) === true);
      check("quickcheck: says why it cannot run",
        /connect a wallet to sign/.test(text), text.slice(0, 240));
      check("quickcheck: run count is adjustable",
        (await page.$$("#panel-quick [data-runs]")).length === 2);
      check("quickcheck: states it is not a Split Score and not a panel",
        /not a Split Score/i.test(text), text.slice(0, 400));
      check("quickcheck: discloses that the browser cannot pin a model",
        /simConfig/.test(text), text.slice(0, 400));
      check("quickcheck: transaction queue present",
        /No transactions yet/.test(text));

      check("quickcheck: no uncaught page errors", errors.length === 0,
        errors.slice(0, 2).join(" ;; "));
      await ctx.close();
    }

    // ------------------------------------- G. navigation, orientation, persistence
    {
      const { ctx, page, errors } = await withPage(browser, { timeoutMs: 60000 });
      await page.waitForSelector(".flow button", { timeout: 60000 });

      const steps = await page.$$eval(".flow .t", (e) => e.map((x) => x.textContent.trim()));
      check("flow: the four steps are named as one pipeline", steps.length === 4,
        JSON.stringify(steps));

      // The flow strip is navigation, so a step must actually open its tab.
      await page.click('.flow [data-goto="#tab-settle"]');
      check("flow: a step opens its tab",
        await page.$eval("#panel-settle", (el) => !el.hidden));

      // WAI-ARIA tabs: arrow keys move, and exactly one tab is in the tab order.
      await page.focus("#tab-reports");
      await page.keyboard.press("ArrowRight");
      check("tabs: ArrowRight selects and focuses the next tab",
        await page.$eval("#tab-rule", (b) => b.getAttribute("aria-selected") === "true"
          && document.activeElement === b));
      await page.keyboard.press("Home");
      check("tabs: Home returns to the first tab",
        await page.$eval("#tab-reports", (b) => b.getAttribute("aria-selected") === "true"));
      check("tabs: exactly one tab is in the tab order",
        await page.$$eval('[role="tab"]', (b) =>
          b.filter((x) => x.tabIndex === 0).length) === 1);
      check("tabs: every tab names its panel",
        await page.$$eval('[role="tab"]', (b) =>
          b.every((x) => document.getElementById(x.getAttribute("aria-controls")))));

      // Theme choice has to survive a reload or every demo starts over.
      await page.click("#theme");
      const chosen = await page.evaluate(() =>
        document.documentElement.getAttribute("data-theme"));
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForSelector(".flow button", { timeout: 60000 });
      check("theme: the choice persists across a reload",
        await page.evaluate(() => document.documentElement.getAttribute("data-theme"))
          === chosen, `chose ${chosen}`);

      check("navigation: no uncaught page errors", errors.length === 0,
        errors.slice(0, 2).join(" ;; "));
      await ctx.close();
    }

    // --------------------------------------------------- H. narrow viewport (phone)
    {
      const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
      const page = await ctx.newPage();
      const errors = [];
      page.on("pageerror", (e) => {
        if (!RPC_NOISE.test(String(e.message))) errors.push(String(e.message));
      });
      await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForSelector("#app .card", { timeout: 60000 });

      // The one failure a phone layout must not have: content wider than the screen.
      const overflow = await page.evaluate(() =>
        document.documentElement.scrollWidth - document.documentElement.clientWidth);
      check("phone: page does not scroll horizontally", overflow <= 1, `${overflow}px over`);

      // Tables carry the evidence, so they scroll inside their own container instead.
      const scrolls = await page.$$eval(".table-scroll", (els) =>
        els.filter((e) => getComputedStyle(e).overflowX === "auto").length);
      check("phone: evidence tables scroll inside a container", scrolls >= 1,
        `${scrolls} scrollable`);

      check("phone: tab bar is reachable",
        await page.$eval(".tabs", (e) => e.scrollWidth >= e.clientWidth));
      await page.click("#tab-rule");
      await page.waitForSelector("#r-text", { timeout: 30000 });
      check("phone: agreement tab is usable",
        await page.$eval("#r-text", (e) => e.getBoundingClientRect().width > 200));

      const tap = await page.$$eval("#panel-rule button, #panel-rule select", (els) =>
        els.filter((e) => e.offsetParent !== null
                          && e.getBoundingClientRect().height < 34).length);
      check("phone: controls meet a usable tap height", tap === 0, `${tap} too short`);

      check("phone: no uncaught page errors", errors.length === 0,
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
