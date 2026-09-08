/* Transaction status, using GenLayer's real semantics.
 *
 * Three things a naive tracker gets wrong, each verified against live studionet:
 *
 *  1. `ACCEPTED` / `FINALIZED` means the committee agreed on the receipt. It does not
 *     mean the call did what it was asked. A `gl.vm.UserError` produces a *finalized*
 *     transaction whose leader receipt says `execution_result: ERROR` and
 *     `result.status: "rollback"`, with the message in `result.payload`.
 *  2. `LeaderTimeout` / `ValidatorsTimeout` leave the appeal window open, so polling
 *     must continue rather than reporting failure.
 *  3. `Undetermined` is not an error. For an adjudication it means the jury split,
 *     which is the finding we are looking for.
 *
 * So an outcome here has three axes, not one: consensus status, execution result, and
 * (for a refusal) the contract's own human-readable reason.
 */

import {
  executionFailed, extractReturn, resultName, revertMessage, statusKind, statusName,
} from "../lib/receipt.js";
import { explorerTx } from "../lib/gl.js";

const POLL_MS = 3000;
const MAX_POLLS = 200;           // ~10 min; a busy studionet round can take minutes

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const short = (h) => (h ? `${h.slice(0, 10)}…${h.slice(-6)}` : "");

/** Human phrasing per outcome. Refusal is a *result*, so it is not styled as an error. */
const OUTCOME_TEXT = {
  submitting: "submitting…",
  pending: "waiting for consensus",
  done: "done",
  refused: "refused by the contract",
  no_consensus: "no consensus — validators split",
  canceled: "canceled",
  timeout: "still unresolved after polling stopped",
  error: "failed to submit",
};

export function createTxQueue(initialHost, { net } = {}) {
  const rows = [];
  let host = initialHost;
  let ticker = null;

  /** Seconds since submission. A consensus round takes tens of seconds, and a live
   *  demo with no elapsed time reads as "hung" long before it actually is. */
  const elapsed = (r) => {
    const end = r.endedAt ?? Date.now();
    return Math.max(0, Math.round((end - r.startedAt) / 1000));
  };

  function paint() {
    if (!rows.length) {
      host.innerHTML = `<p class="note">No transactions yet.</p>`;
      return;
    }
    host.innerHTML = rows.map((r, i) => {
      const link = r.hash && net
        ? (explorerTx(net, r.hash)
          ? `<a href="${esc(explorerTx(net, r.hash))}" target="_blank" rel="noopener"
               class="mono">${esc(short(r.hash))}</a>`
          : `<span class="mono">${esc(short(r.hash))}</span>`)
        : "";
      const copy = r.hash
        ? `<button type="button" class="txcopy" data-copy="${esc(r.hash)}">copy</button>`
        : "";
      const spinner = r.terminal ? "" : `<span class="spin" aria-hidden="true"></span>`;
      return `<div class="txrow" data-i="${i}">
        <div class="txmain">
          ${spinner}
          <span class="txlabel">${esc(r.label)}</span>
          <span class="txstatus mono">${esc(r.status || "—")}</span>
          <span class="txelapsed">${elapsed(r)}s</span>
          ${link}${copy}
        </div>
        <div class="txout ${esc(r.outcome || "pending")}">
          ${esc(OUTCOME_TEXT[r.outcome] || r.outcome || "")}
          ${r.detail ? `<div class="txdetail">${esc(r.detail)}</div>` : ""}
        </div>
      </div>`;
    }).join("");

    for (const b of host.querySelectorAll("[data-copy]")) {
      b.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(b.dataset.copy);
          b.textContent = "copied";
          setTimeout(() => { b.textContent = "copy"; }, 1200);
        } catch { b.textContent = "press ⌘C"; }
      });
    }

    // One timer for the whole queue, running only while something is in flight.
    const live = rows.some((r) => r.endedAt === null);
    if (live && !ticker) ticker = setInterval(paint, 1000);
    if (!live && ticker) { clearInterval(ticker); ticker = null; }
  }

  /**
   * Submit, then poll to a terminal state. Resolves with a structured outcome so the
   * caller can branch on `refused` versus `done` without re-reading the receipt.
   */
  async function track({ label, submit, client }) {
    const row = { label, hash: null, status: "", outcome: "submitting",
                  detail: "", terminal: false, startedAt: Date.now(), endedAt: null };
    // Stop the clock on every exit path, including the ones that are not `terminal`
    // in the consensus sense (submit error, poll exhaustion).
    const stop = () => { row.endedAt ??= Date.now(); };
    rows.push(row);
    paint();

    let hash;
    try {
      hash = await submit();
      hash = typeof hash === "string" ? hash : String(hash);
      row.hash = hash;
      row.outcome = "pending";
      paint();
    } catch (e) {
      row.outcome = "error";
      row.detail = e?.message ? String(e.message) : String(e);
      row.terminal = true;
      stop(); paint();
      return { ok: false, outcome: "error", error: row.detail, row };
    }

    let receipt = null;
    for (let i = 0; i < MAX_POLLS; i++) {
      try {
        receipt = await client.getTransaction({ hash });
      } catch {
        // Transient RPC failures are common on the hosted endpoint; keep polling.
        await new Promise((r) => setTimeout(r, POLL_MS));
        continue;
      }
      const name = statusName(receipt);
      row.status = name;
      const { terminal } = statusKind(name);
      paint();
      if (terminal) break;
      await new Promise((r) => setTimeout(r, POLL_MS));
    }

    if (!receipt) {
      row.outcome = "timeout";
      row.terminal = true;
      stop(); paint();
      return { ok: false, outcome: "timeout", row };
    }

    const kind = statusKind(statusName(receipt)).kind;
    row.terminal = statusKind(statusName(receipt)).terminal;

    if (kind === "no_consensus") {
      row.outcome = "no_consensus";
      row.detail = resultName(receipt) || "";
      stop(); paint();
      return { ok: false, outcome: "no_consensus", receipt, hash, row };
    }
    if (kind === "canceled") {
      row.outcome = "canceled";
      row.terminal = true;
      stop(); paint();
      return { ok: false, outcome: "canceled", receipt, hash, row };
    }
    if (!row.terminal) {
      row.outcome = "timeout";
      row.detail = `last status ${statusName(receipt)}`;
      stop(); paint();
      return { ok: false, outcome: "timeout", receipt, hash, row };
    }

    if (executionFailed(receipt)) {
      // The committee agreed; the contract refused. This is the gate working.
      row.outcome = "refused";
      row.detail = revertMessage(receipt);
      stop(); paint();
      return { ok: false, outcome: "refused", reason: row.detail, receipt, hash, row };
    }

    row.outcome = "done";
    const payload = extractReturn(receipt, ["state"]) || extractReturn(receipt);
    if (payload) row.detail = JSON.stringify(payload);
    stop(); paint();
    return { ok: true, outcome: "done", payload, receipt, hash, row };
  }

  paint();
  return {
    track, rows,
    clear: () => { rows.length = 0; paint(); },
    /**
     * Re-point the queue at a fresh DOM node after the owning panel repaints.
     *
     * The panels re-render wholesale, so without this the queue would be rebuilt on
     * every state change and the history of a demo would vanish the moment a
     * transaction settled -- exactly when a reviewer wants to look at it.
     */
    attach: (el, opts = {}) => {
      host = el;
      if (opts.net !== undefined) net = opts.net;
      paint();
    },
    // Repainting a detached host leaks an interval per re-mount, and these panels
    // re-mount on every wallet or network change.
    dispose: () => { if (ticker) { clearInterval(ticker); ticker = null; } },
  };
}
