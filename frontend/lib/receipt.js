/* Receipt reading — ports of logic verified against real GenLayer receipts.
 *
 * Dependency-free and pure so it can be unit-tested in Node against the raw receipts
 * committed under reports/raw/ and experiments/.
 *
 * Three facts drive everything here, each learned the hard way:
 *
 *  1. A contract revert still yields ACCEPTED / MAJORITY_AGREE -- the validators agree
 *     the call failed. Transaction status therefore says nothing about whether the call
 *     did what it was asked. The signal is on the leader receipt.
 *  2. LeaderTimeout and ValidatorsTimeout are not terminal: the appeal window is open
 *     and the transaction can still finalize. Rendering them as failure reports a
 *     failure that did not happen.
 *  3. Undetermined means consensus was not reached. For an adjudication that is the
 *     jury splitting, which is a finding, not an error.
 */

export const DECISIONS = ["ACCEPT", "REJECT", "PARTIAL", "INSUFFICIENT"];

/** Vote-type enum from gen_getTransactionReceipt. */
export const VOTE_ENUM = {
  0: "NotVoted", 1: "FinishedWithReturn", 2: "FinishedWithError",
  3: "Timeout", 4: "NondetDisagree", 5: "DeterministicViolation",
};

const IN_FLIGHT = new Set(["Pending", "Proposing", "Committing", "Revealing",
  "LeaderRevealing", "AppealCommitting", "AppealRevealing",
  "PENDING", "PROPOSING", "COMMITTING", "REVEALING", "LEADER_REVEALING"]);
const APPEALABLE = new Set(["LeaderTimeout", "ValidatorsTimeout",
  "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"]);
const SETTLED = new Set(["Accepted", "Finalized", "ACCEPTED", "FINALIZED"]);
const NO_CONSENSUS = new Set(["Undetermined", "UNDETERMINED"]);
const DEAD = new Set(["Canceled", "CANCELED"]);

export function statusName(receipt) {
  if (!receipt) return "";
  for (const k of ["status_name", "statusName"]) {
    if (receipt[k]) return String(receipt[k]);
  }
  return receipt.status === undefined ? "" : String(receipt.status);
}

export function resultName(receipt) {
  if (!receipt) return "";
  for (const k of ["result_name", "txExecutionResultName", "tx_execution_result_name"]) {
    if (receipt[k]) return String(receipt[k]);
  }
  return "";
}

/**
 * Classify a status for display. `kind` drives the UI; `terminal` decides whether to
 * keep polling. Note that `no_consensus` is terminal *and* a legitimate result.
 */
export function statusKind(name) {
  if (IN_FLIGHT.has(name)) return { kind: "in_flight", terminal: false };
  if (APPEALABLE.has(name)) return { kind: "appealable", terminal: false };
  if (NO_CONSENSUS.has(name)) return { kind: "no_consensus", terminal: true };
  if (DEAD.has(name)) return { kind: "canceled", terminal: true };
  if (SETTLED.has(name)) return { kind: "settled", terminal: true };
  return { kind: "unknown", terminal: false };
}

export function leaderReceipt(receipt) {
  const cd = (receipt && receipt.consensus_data) || {};
  let lr = cd.leader_receipt;
  if (Array.isArray(lr)) lr = lr.length ? lr[0] : {};
  return lr && typeof lr === "object" ? lr : {};
}

/** True when the contract reverted, even though consensus succeeded. */
export function executionFailed(receipt) {
  const lr = leaderReceipt(receipt);
  if (String(lr.execution_result || "").toUpperCase() === "ERROR") return true;
  const r = lr.result;
  return !!(r && typeof r === "object" && String(r.status || "") === "rollback");
}

/** The UserError text the contract raised, with our internal prefix stripped. */
export function revertMessage(receipt, { keepPrefix = false } = {}) {
  const lr = leaderReceipt(receipt);
  let msg = "";
  const r = lr.result;
  if (r && typeof r === "object" && typeof r.payload === "string" && r.payload) {
    msg = r.payload;
  } else {
    for (const k of ["error", "stderr"]) {
      if (lr[k]) { msg = String(lr[k]); break; }
    }
  }
  if (!keepPrefix) msg = msg.replace(/^\s*\[(EXPECTED|EXTERNAL|TRANSIENT|LLM_ERROR)\]\s*/, "");
  return msg;
}

function* walk(node) {
  if (Array.isArray(node)) {
    for (const v of node) yield* walk(v);
  } else if (node && typeof node === "object") {
    yield node;
    for (const v of Object.values(node)) yield* walk(v);
  }
}

/**
 * Pull the contract's returned payload out of a receipt.
 *
 * The return value nests differently across environments, so we look for any
 * `payload.readable` that parses into an object with the fields we expect rather than
 * hard-coding a path. `readable` is JSON-quoted and our payload is itself JSON, hence
 * the repeated parse.
 */
export function extractReturn(receipt, requiredKeys = ["decision", "status"]) {
  for (const node of walk(receipt)) {
    const readable = node.readable;
    if (typeof readable !== "string") continue;
    let val = readable;
    for (let i = 0; i < 3 && typeof val === "string"; i++) {
      try { val = JSON.parse(val); } catch { break; }
    }
    if (val && typeof val === "object" && requiredKeys.every((k) => k in val)) {
      return val;
    }
  }
  return null;
}

/** Studio-shaped votes: address -> "agree" | "disagree", with model attribution. */
export function studioVotes(receipt) {
  const cd = (receipt && receipt.consensus_data) || {};
  const votes = cd.votes || {};
  const models = {};
  for (const entry of cd.validators || []) {
    const nc = entry.node_config || {};
    const pm = nc.primary_model || {};
    models[String(nc.address || "")] = String(pm.model || nc.model || "?");
  }
  const lr = leaderReceipt(receipt);
  const lnc = lr.node_config || {};
  const lpm = lnc.primary_model || {};
  const leader = String(lnc.address || "");
  if (leader && !models[leader]) models[leader] = String(lpm.model || lnc.model || "?");
  return Object.entries(votes).sort().map(([address, vote]) => ({
    address, vote, model: models[address] || "?", leader: address === leader,
  }));
}

function b64bytes(s) {
  if (!s) return [];
  const bin = typeof atob === "function"
    ? atob(s)
    : Buffer.from(s, "base64").toString("binary");
  return Array.from(bin, (c) => c.charCodeAt(0));
}

/**
 * Node-API votes: roundData[].validatorVotes is base64, one byte per validator,
 * positionally aligned to roundValidators. Confirmed by E4 on real revealed votes.
 * Bradbury appends several entries all labelled round 0, so take the last one that
 * actually revealed -- the pre-reveal entry is all zeros and reads as "nobody
 * disagreed".
 */
export function nodeVotes(receipt) {
  const rounds = (receipt && receipt.roundData) || [];
  const revealed = rounds.filter((r) => Number(r.votesRevealed || 0) > 0);
  const chosen = revealed.length ? revealed[revealed.length - 1]
    : (rounds.length ? rounds[rounds.length - 1] : null);
  if (!chosen) return null;
  const bytes = b64bytes(chosen.validatorVotes);
  const validators = chosen.roundValidators || [];
  const aligned = bytes.length === validators.length && validators.length > 0;
  return {
    aligned,
    votesRevealed: chosen.votesRevealed,
    bytes,
    perValidator: aligned ? validators.map((address, i) => ({
      address, byte: bytes[i], name: VOTE_ENUM[bytes[i]] ?? `unknown(${bytes[i]})`,
    })) : [],
    nDisagree: bytes.filter((b) => b === 4).length,
    distinctResultHashes: new Set((chosen.validatorResultHash || []).filter(Boolean)).size,
  };
}

/** 1 - modal share over a decision list. 0 means unanimous; null means nothing valid. */
export function divergence(decisions) {
  const counts = {};
  for (const d of decisions) if (d) counts[d] = (counts[d] || 0) + 1;
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (!total) return null;
  return Number((1 - Math.max(...Object.values(counts)) / total).toFixed(4));
}
