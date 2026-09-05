/* Unit tests for the receipt layer, run against REAL committed receipts.
 *
 * The point of testing against real artifacts rather than fixtures: every one of these
 * behaviours was a bug first. A synthetic fixture would encode my assumption; these
 * files encode what studionet and Bradbury actually returned.
 *
 *   node tests/frontend/receipt_test.mjs
 */

import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import assert from "node:assert/strict";

import {
  divergence, executionFailed, extractReturn, leaderReceipt, nodeVotes,
  resultName, revertMessage, statusKind, statusName, studioVotes,
} from "../../frontend/lib/receipt.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const read = (p) => JSON.parse(readFileSync(join(root, p), "utf8"));

let pass = 0, fail = 0;
const check = (name, fn) => {
  try { fn(); console.log(`  PASS  ${name}`); pass++; }
  catch (e) { console.log(`  FAIL  ${name}\n        ${e.message}`); fail++; }
};

// ---------------------------------------------------------------- status handling
check("in-flight statuses are not terminal", () => {
  for (const s of ["Pending", "Proposing", "Committing", "Revealing", "LeaderRevealing"]) {
    assert.equal(statusKind(s).terminal, false, s);
    assert.equal(statusKind(s).kind, "in_flight", s);
  }
});

check("LeaderTimeout is appealable, not terminal, not failure", () => {
  // A Bradbury transaction observed at LeaderTimeout later Finalized with
  // FinishedWithReturn, so treating it as terminal reports a failure that did not
  // happen.
  const k = statusKind("LeaderTimeout");
  assert.equal(k.terminal, false);
  assert.equal(k.kind, "appealable");
  assert.equal(statusKind("ValidatorsTimeout").kind, "appealable");
});

check("Undetermined is terminal and a result, not an error", () => {
  const k = statusKind("Undetermined");
  assert.equal(k.terminal, true);
  assert.equal(k.kind, "no_consensus");
});

check("Accepted and Finalized are settled", () => {
  assert.equal(statusKind("Accepted").kind, "settled");
  assert.equal(statusKind("Finalized").kind, "settled");
});

// ------------------------------------------------------- real split (E1 receipt)
const e1 = read("experiments/E1_contract_smoke/receipt_adjudicate.json");

check("E1: reads the real 3-2 split as UNDETERMINED / MAJORITY_DISAGREE", () => {
  assert.equal(statusName(e1), "UNDETERMINED");
  assert.equal(resultName(e1), "MAJORITY_DISAGREE");
  assert.equal(statusKind(statusName(e1)).kind, "no_consensus");
});

check("E1: studioVotes recovers 5 votes with model attribution", () => {
  const votes = studioVotes(e1);
  assert.equal(votes.length, 5);
  assert.equal(votes.filter((v) => v.vote === "disagree").length, 3);
  assert.equal(votes.filter((v) => v.vote === "agree").length, 2);
  assert.ok(votes.some((v) => v.model.includes("gemini")), "expected a real model name");
  assert.equal(votes.filter((v) => v.leader).length, 1);
});

check("E1: a split is not an execution failure", () => {
  // The contract ran fine; the jury disagreed. Conflating the two would render every
  // interesting finding as a bug.
  assert.equal(executionFailed(e1), false);
});

// ------------------------------------------------- real panel receipts (studionet)
const panelDir = "reports/raw/v1_ps_6ce467da9d20c1f2";
const panelFiles = readdirSync(join(root, panelDir)).filter((f) => f.endsWith(".json"));

check("panel receipts exist to test against", () => {
  assert.ok(panelFiles.length >= 40, `only ${panelFiles.length} receipts`);
});

check("extractReturn recovers a decision from every accepted panel receipt", () => {
  let found = 0, missing = [];
  for (const f of panelFiles) {
    const rec = read(join(panelDir, f));
    if (statusKind(statusName(rec)).kind !== "settled") continue;
    const payload = extractReturn(rec);
    if (payload && payload.decision) found++;
    else missing.push(f);
  }
  assert.ok(found >= 40, `recovered ${found} decisions, missed ${missing.length}`);
  assert.deepEqual(missing, [], `missed: ${missing.slice(0, 3).join(", ")}`);
});

check("recovered decisions are all in the vocabulary", () => {
  const seen = new Set();
  for (const f of panelFiles) {
    const p = extractReturn(read(join(panelDir, f)));
    if (p && p.status === "OK") seen.add(p.decision);
  }
  for (const d of seen) {
    assert.ok(["ACCEPT", "REJECT", "PARTIAL", "INSUFFICIENT"].includes(d), d);
  }
  assert.ok(seen.size >= 2, `expected several distinct decisions, saw ${[...seen]}`);
});

check("single-validator panel runs expose exactly one vote (the noise floor)", () => {
  let single = 0;
  for (const f of panelFiles) {
    if (studioVotes(read(join(panelDir, f))).length === 1) single++;
  }
  assert.ok(single >= 40, `only ${single} receipts had one vote`);
});

// ----------------------------------------------------------- Bradbury node receipt
const node = read("experiments/E3_E4_bradbury/receipt_node.json");

check("Bradbury: nodeVotes decodes aligned, revealed votes", () => {
  const v = nodeVotes(node);
  assert.ok(v, "no round data");
  assert.equal(v.aligned, true);
  assert.equal(v.bytes.length, Number(v.votesRevealed));
  assert.ok(v.perValidator.every((p) => p.name && !p.name.startsWith("unknown")),
    "a vote byte fell outside the documented enum");
});

check("Bradbury: the informative round is chosen, not roundData[0]", () => {
  const rounds = node.roundData || [];
  if (rounds.length > 1) {
    const v = nodeVotes(node);
    assert.ok(Number(v.votesRevealed) > 0, "picked a pre-reveal round");
  }
  assert.ok(true);
});

// -------------------------------------------------------------- revert detection
check("revert is detected despite ACCEPTED consensus, with the message", () => {
  const rec = {
    status_name: "ACCEPTED", result_name: "MAJORITY_AGREE",
    consensus_data: { leader_receipt: [{ execution_result: "ERROR", result: {
      status: "rollback",
      payload: "[EXPECTED] rule has 4 counterexamples, deal tolerates 3; tighten the rule",
    } }] },
  };
  assert.equal(statusKind(statusName(rec)).kind, "settled");   // consensus succeeded
  assert.equal(executionFailed(rec), true);                     // the call did not
  const msg = revertMessage(rec);
  assert.ok(msg.startsWith("rule has 4 counterexamples"), msg);
  assert.ok(revertMessage(rec, { keepPrefix: true }).startsWith("[EXPECTED]"));
});

check("successful call is not a failure", () => {
  const rec = { consensus_data: { leader_receipt: [{ execution_result: "SUCCESS",
    result: { status: "return", payload: '{"state":"LOCKED"}' } }] } };
  assert.equal(executionFailed(rec), false);
});

check("malformed receipts do not throw", () => {
  for (const rec of [{}, null, { consensus_data: {} },
                     { consensus_data: { leader_receipt: [] } }]) {
    assert.equal(executionFailed(rec), false);
    assert.equal(revertMessage(rec), "");
    assert.equal(extractReturn(rec), null);
    assert.deepEqual(studioVotes(rec), []);
    assert.deepEqual(leaderReceipt(rec), {});
  }
  assert.equal(nodeVotes({}), null);
});

// ------------------------------------------------------------------- divergence
check("divergence matches the Python definition", () => {
  assert.equal(divergence(["ACCEPT", "ACCEPT", "ACCEPT"]), 0);
  assert.equal(divergence(["ACCEPT", "ACCEPT", "REJECT"]), 0.3333);
  assert.equal(divergence(["ACCEPT", "REJECT", "INSUFFICIENT"]), 0.6667);
  assert.equal(divergence([]), null);
});

check("divergence on a real probe matches the committed report", () => {
  const report = read("reports/v1_ps_6ce467da9d20c1f2_studionet.json");
  for (const probe of report.probes) {
    const decisions = probe.observations
      .filter((o) => o.kind !== "INCONCLUSIVE" && o.decision)
      .map((o) => o.decision);
    assert.equal(divergence(decisions), probe.divergence,
      `probe #${probe.index}: recomputed ${divergence(decisions)} vs stored ${probe.divergence}`);
  }
});

console.log(`\n${pass}/${pass + fail} receipt tests passed`);
if (fail) process.exit(1);
