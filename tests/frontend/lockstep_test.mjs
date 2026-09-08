/* The settlement panel's decisions around the escrow write.
 *
 * The write itself needs a human: MetaMask's Snap approval cannot be automated, and
 * settlement_live.mjs already drives the real contract with a local dev key. What is
 * left untested by both is the reasoning the panel does *between* those transactions --
 * which tolerance the next lock is judged against, whether a refusal has actually
 * happened, whether locking is still possible. That reasoning is what turned a working
 * contract into a demo that appeared to stall, so it gets its own test.
 *
 *   node tests/frontend/lockstep_test.mjs
 */

import assert from "node:assert/strict";

import { lockStep, lockPreview } from "../../frontend/lib/attest.js";

// The real numbers from the deployed v1 report, so the cases below are the demo.
const WORST = 4;
const REG = { tested: true, worst: WORST };

const deal = (state, max, extra = {}) => ({
  deal_id: "d", state, max_counterexamples: max, ...extra,
});

let pass = 0, fail = 0;
function check(name, fn) {
  try { fn(); console.log(`  PASS  ${name}`); pass++; }
  catch (e) { console.log(`  FAIL  ${name}\n        ${e.message}`); fail++; }
}

// ------------------------------------------------------- before any deal exists
check("no deal: the stepper is what the preview judges", () => {
  const s = lockStep({ deal: null, tolerance: 3, ...REG });
  assert.equal(s.effectiveTolerance, 3);
  assert.equal(s.dealTolerance, null);
  assert.equal(s.preview.allowed, false);
  assert.equal(s.drifted, false);
});

check("no deal: tolerance at the worst finding is expected to lock", () => {
  const s = lockStep({ deal: null, tolerance: WORST, ...REG });
  assert.equal(s.preview.allowed, true);
  assert.match(s.preview.reason, /within tolerance 4/);
});

check("no deal: locking is not pre-emptively blocked", () => {
  assert.equal(lockStep({ deal: null, tolerance: WORST, ...REG }).canLock, true);
});

check("untested rule: refused regardless of how high the tolerance goes", () => {
  const s = lockStep({ deal: null, tolerance: 99, tested: false, worst: 0 });
  assert.equal(s.preview.allowed, false);
  assert.match(s.preview.reason, /no published report/);
});

// ----------------------------------------------- step 5-8: opened tight, refused
check("freshly opened deal is not reported as a refusal", () => {
  // OPEN is also the state of a deal nobody has tried to lock yet. Keying the refusal
  // card off the state alone announced a rejection that had not happened.
  const s = lockStep({ deal: deal("OPEN", 3), tolerance: 3, lastLock: null, ...REG });
  assert.equal(s.showRefusal, false);
});

check("after a refusal the panel says so", () => {
  const s = lockStep({ deal: deal("OPEN", 3), tolerance: 3, lastLock: "refused", ...REG });
  assert.equal(s.showRefusal, true);
  assert.equal(s.canLock, true, "the deal is still OPEN, so lock remains callable");
});

// --------------------------------------- step 9: raising the stepper, deal unchanged
check("raising the stepper does not change what the open deal promises", () => {
  const s = lockStep({ deal: deal("OPEN", 3), tolerance: 4, lastLock: "refused", ...REG });
  assert.equal(s.dealTolerance, 3, "the frozen tolerance is still 3");
  assert.equal(s.effectiveTolerance, 3, "and 3 is what the next lock is judged against");
  assert.equal(s.drifted, true, "so the panel must warn that the two disagree");
  assert.equal(s.preview.allowed, false,
    "predicting a lock here would make the contract's refusal look like a bug");
});

check("the drift warning clears once a new deal carries the raised tolerance", () => {
  const s = lockStep({ deal: deal("OPEN", 4), tolerance: 4, lastLock: null, ...REG });
  assert.equal(s.drifted, false);
  assert.equal(s.showRefusal, false);
  assert.equal(s.effectiveTolerance, 4);
  assert.equal(s.preview.allowed, true);
});

// ------------------------------------------------------ step 10-11: locked, terminal
check("a LOCKED deal cannot be locked again", () => {
  const s = lockStep({ deal: deal("LOCKED", 4), tolerance: 4, lastLock: "ok", ...REG });
  assert.equal(s.canLock, false);
  assert.equal(s.showRefusal, false);
  assert.equal(s.dealTolerance, null, "a closed deal has no live tolerance to judge");
});

for (const terminal of ["RELEASED", "REFUNDED"]) {
  check(`a ${terminal} deal cannot be locked`, () => {
    assert.equal(lockStep({ deal: deal(terminal, 4), tolerance: 4, ...REG }).canLock, false);
  });
}

// ------------------------------------------------------------------ gate integrity
check("no Split Score reaches the gate decision", () => {
  // Passing a flattering score must not change the answer: the gate reads exactly two
  // registry facts, and E6 scoped the score out of every production surface.
  const base = lockStep({ deal: null, tolerance: 3, ...REG });
  const spiked = lockStep({ deal: null, tolerance: 3, ...REG, split_score: 0, score: 0 });
  assert.deepEqual(spiked.preview, base.preview);
});

check("worst-of is honoured: the gate uses the registry's worst, not the stepper", () => {
  // Tolerance 10 with a worst of 4 locks; tolerance 10 with a worst of 11 does not.
  assert.equal(lockStep({ deal: null, tolerance: 10, tested: true, worst: 4 })
    .preview.allowed, true);
  assert.equal(lockStep({ deal: null, tolerance: 10, tested: true, worst: 11 })
    .preview.allowed, false);
});

check("lockStep's preview is lockPreview's, unmodified", () => {
  const s = lockStep({ deal: deal("OPEN", 2), tolerance: 9, ...REG });
  assert.deepEqual(s.preview, lockPreview({ ...REG, tolerance: 2 }));
});

console.log(`\n${pass}/${pass + fail} lockStep checks passed`);
process.exit(fail ? 1 : 0);
