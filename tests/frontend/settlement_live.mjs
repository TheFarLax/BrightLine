/* Live verification of the settlement flow through the JS stack, on real studionet.
 *
 * This exercises exactly what the browser exercises -- genlayer-js writeContract, the
 * attestation projection, ABI arg order, and the revert-detection helpers in
 * lib/receipt.js -- against the deployed contracts. The one piece it substitutes is the
 * signer: a local dev key instead of the MetaMask Snap, because a Snap needs a human.
 *
 * So: everything below is verified. The Snap approval is not, and is not claimed to be.
 *
 *   node tests/frontend/settlement_live.mjs
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { createClient, createAccount } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

import { publishArgs, reportToAttestation, lockPreview } from "../../frontend/lib/attest.js";
import { executionFailed, revertMessage, statusKind, statusName } from "../../frontend/lib/receipt.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));

const UNTESTED = `0x${"ee".repeat(32)}`;
const AMOUNT = 10n ** 16n;

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
  ok ? pass++ : fail++;
};

async function settle(client, hash, { max = 120 } = {}) {
  for (let i = 0; i < max; i++) {
    let t;
    try { t = await client.getTransaction({ hash }); } catch { t = null; }
    if (t && statusKind(statusName(t)).terminal) return t;
    await new Promise((r) => setTimeout(r, 3000));
  }
  throw new Error(`transaction ${hash} never reached a terminal status`);
}

async function main() {
  const cfg = read("frontend/networks.json").networks.studionet;
  const registry = cfg.contracts.registry.address;
  const escrow = cfg.contracts.escrow.address;
  const key = read(".brightline/accounts.json").default;
  const account = createAccount(key.startsWith("0x") ? key : `0x${key}`);
  const client = createClient({ chain: studionet, account });

  console.log(`registry ${registry}\nescrow   ${escrow}\naccount  ${account.address}\n`);

  const index = read("reports/index.json");
  const entry = index.reports.find((r) => r.rule_label === "v1");
  const rule = entry.rule_hash;

  // ---------------------------------------------------------------- registry reads
  const tested = await client.readContract(
    { address: registry, functionName: "is_tested", args: [rule] });
  const worst = Number(await client.readContract(
    { address: registry, functionName: "worst_counterexamples", args: [rule] }));
  const summary = JSON.parse(await client.readContract(
    { address: registry, functionName: "summary_for_rule", args: [rule] }));

  check("registry: is_tested true for the published rule", tested === true);
  check("registry: worst_counterexamples matches the report", worst === entry.K,
    `chain ${worst} vs report ${entry.K}`);
  check("registry: summary lists at least one report", (summary.reports || 0) >= 1);

  // ------------------------------------------------- attestation projection + args
  const report = read(entry.path);
  const att = reportToAttestation(report);
  att.evidence_uri = `reports/${entry.file}`;
  check("attestation: report_hash already on chain (idempotent publish path)",
    (summary.rows || []).some((r) => r.report_hash === att.report_hash),
    `rows: ${JSON.stringify((summary.rows || []).map((r) => r.report_hash))}`);
  check("attestation: publishArgs has 11 positional args", publishArgs(att).length === 11);

  // A duplicate publish must be refused by the contract, not silently accepted.
  const dupHash = await client.writeContract({
    address: registry, functionName: "publish", args: publishArgs(att), value: 0n });
  const dupTx = await settle(client, String(dupHash));
  check("registry: duplicate report_hash is refused", executionFailed(dupTx),
    `status ${statusName(dupTx)}`);
  check("registry: refusal names the reason",
    /already published/i.test(revertMessage(dupTx)), revertMessage(dupTx));

  const stamp = Date.now();

  // ------------------------------------------------ case 1: tolerance >= worst -> lock
  {
    const id = `js-ok-${stamp}`;
    check("preview: tolerance == worst is expected to lock",
      lockPreview({ tested, worst, tolerance: worst }).allowed === true);
    await settle(client, String(await client.writeContract({
      address: escrow, functionName: "open_deal",
      args: [id, account.address, rule, worst], value: 0n })));
    const lockTx = await settle(client, String(await client.writeContract({
      address: escrow, functionName: "lock", args: [id], value: AMOUNT })));
    check("escrow: lock succeeds within tolerance", !executionFailed(lockTx),
      revertMessage(lockTx));
    const deal = JSON.parse(await client.readContract(
      { address: escrow, functionName: "get_deal", args: [id] }));
    check("escrow: deal state is LOCKED", deal.state === "LOCKED", deal.state);
    check("escrow: counterexamples frozen into the deal",
      deal.counterexamples_at_lock === worst,
      `${deal.counterexamples_at_lock} vs ${worst}`);
    check("escrow: registry summary frozen into the deal",
      (JSON.parse(deal.summary_at_lock || "{}").reports || 0) >= 1);

    const relTx = await settle(client, String(await client.writeContract({
      address: escrow, functionName: "release", args: [id], value: 0n })));
    check("escrow: release records settlement", !executionFailed(relTx),
      revertMessage(relTx));
    const after = JSON.parse(await client.readContract(
      { address: escrow, functionName: "get_deal", args: [id] }));
    check("escrow: deal state is RELEASED", after.state === "RELEASED", after.state);
  }

  // -------------------------------------- case 2: tolerance < worst -> refusal, OPEN
  {
    const id = `js-tight-${stamp}`;
    const tol = Math.max(0, worst - 1);
    check("preview: tolerance below worst predicts refusal",
      lockPreview({ tested, worst, tolerance: tol }).allowed === false);
    await settle(client, String(await client.writeContract({
      address: escrow, functionName: "open_deal",
      args: [id, account.address, rule, tol], value: 0n })));
    const lockTx = await settle(client, String(await client.writeContract({
      address: escrow, functionName: "lock", args: [id], value: AMOUNT })));
    check("escrow: lock refused below tolerance", executionFailed(lockTx),
      `status ${statusName(lockTx)}`);
    const msg = revertMessage(lockTx);
    check("escrow: refusal names both numbers",
      msg.includes(String(worst)) && msg.includes(String(tol)), msg);
    const deal = JSON.parse(await client.readContract(
      { address: escrow, functionName: "get_deal", args: [id] }));
    check("escrow: deal stays OPEN after refusal", deal.state === "OPEN", deal.state);
  }

  // ------------------------------------------- case 3: untested rule -> refusal, OPEN
  {
    const id = `js-untested-${stamp}`;
    check("preview: untested rule predicts refusal",
      lockPreview({ tested: false, worst: 0, tolerance: 99 }).allowed === false);
    await settle(client, String(await client.writeContract({
      address: escrow, functionName: "open_deal",
      args: [id, account.address, UNTESTED, 99], value: 0n })));
    const lockTx = await settle(client, String(await client.writeContract({
      address: escrow, functionName: "lock", args: [id], value: AMOUNT })));
    check("escrow: lock refused for an untested rule", executionFailed(lockTx),
      `status ${statusName(lockTx)}`);
    check("escrow: refusal tells the payer to test first",
      /no published Brightline report/i.test(revertMessage(lockTx)),
      revertMessage(lockTx));
    const deal = JSON.parse(await client.readContract(
      { address: escrow, functionName: "get_deal", args: [id] }));
    check("escrow: untested deal stays OPEN", deal.state === "OPEN", deal.state);
  }

  // ------------------------------------------------ case 4: the public demo journey
  //
  // Cases 1 and 2 prove the two outcomes in isolation. This walks them as one continuous
  // sequence, because that is what a visitor does and because it pins the property the
  // UI has to respect: a refusal is *not* recoverable by editing the deal. `open_deal`
  // freezes `max_counterexamples` and the contract exposes no setter, so the second
  // attempt must be a second deal. If a future change added a setter, this test is where
  // the anti-gaming property would be seen to die.
  {
    const tight = Math.max(0, worst - 1);
    const tightId = `js-demo-tight-${stamp}`;
    const okId = `js-demo-ok-${stamp}`;

    await settle(client, String(await client.writeContract({
      address: escrow, functionName: "open_deal",
      args: [tightId, account.address, rule, tight], value: 0n })));
    const refused = await settle(client, String(await client.writeContract({
      address: escrow, functionName: "lock", args: [tightId], value: AMOUNT })));
    check("demo: lock at tolerance below worst is refused", executionFailed(refused),
      `status ${statusName(refused)}`);
    check("demo: refusal is the message the walkthrough quotes",
      new RegExp(`rule has ${worst} counterexamples, deal tolerates ${tight}`)
        .test(revertMessage(refused)), revertMessage(refused));

    // The gate is not editable in place: same deal, raised expectations, same answer.
    const stillTight = JSON.parse(await client.readContract(
      { address: escrow, functionName: "get_deal", args: [tightId] }));
    check("demo: the refused deal keeps its original tolerance",
      Number(stillTight.max_counterexamples) === tight && stillTight.state === "OPEN",
      `${stillTight.max_counterexamples} / ${stillTight.state}`);

    // Recovery is a new deal at the raised tolerance -- the flow the panel now guides.
    await settle(client, String(await client.writeContract({
      address: escrow, functionName: "open_deal",
      args: [okId, account.address, rule, worst], value: 0n })));
    const okTx = await settle(client, String(await client.writeContract({
      address: escrow, functionName: "lock", args: [okId], value: AMOUNT })));
    check("demo: a new deal at the raised tolerance locks", !executionFailed(okTx),
      revertMessage(okTx));
    const locked = JSON.parse(await client.readContract(
      { address: escrow, functionName: "get_deal", args: [okId] }));
    check("demo: state is LOCKED", locked.state === "LOCKED", locked.state);
    check("demo: counterexamples_at_lock equals the worst published finding",
      Number(locked.counterexamples_at_lock) === worst,
      `${locked.counterexamples_at_lock} vs ${worst}`);
    check("demo: the escrowed amount is the 0.01 GEN the button sends",
      BigInt(locked.amount) === AMOUNT, `${locked.amount} vs ${AMOUNT}`);

    // The earlier refusal is untouched by the later success: two independent deals.
    const after = JSON.parse(await client.readContract(
      { address: escrow, functionName: "get_deal", args: [tightId] }));
    check("demo: the refused deal is still OPEN after the second one locked",
      after.state === "OPEN", after.state);
  }

  console.log(`\n${pass}/${pass + fail} live settlement checks passed`);
  if (fail) process.exit(1);
}

main().catch((e) => { console.error("harness error:", e.message); process.exit(1); });
