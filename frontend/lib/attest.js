/* Report → registry attestation, mirroring brightline/publish.py exactly.
 *
 * Pure and dependency-free so parity with the Python projection can be asserted in a
 * test rather than assumed. Divergence here would mean the browser and the CLI publish
 * different facts about the same report.
 *
 * What this deliberately drops is as important as what it keeps: no Split Score, no
 * mean divergence, no AUC, no per-model detail. E6 scoped the score to a studionet lab
 * instrument, so it must never reach a surface another contract can gate on.
 */

/** The registry stores the floor as integer per-mille so an exact 0.0 stays exact. */
export const FLOOR_SCALE = 1000;

/**
 * Python writes `json.dumps(list)` with its default `", "` separator. Matching it byte
 * for byte keeps a browser-published attestation identical to a CLI-published one.
 */
function pyJsonList(items) {
  return `[${items.map((h) => JSON.stringify(h)).join(", ")}]`;
}

export function reportToAttestation(report) {
  const m = report.metrics;
  const p = report.provenance;

  const seen = new Set();
  for (const probe of report.probes || []) {
    for (const obs of probe.observations || []) {
      if (obs.tx) seen.add(obs.tx);
    }
  }
  const hashes = [...seen].sort();
  const floor = m.noise_floor;

  return {
    report_hash: report.report_hash,
    rule_hash: report.rule.rule_hash,
    probe_set_id: p.probe_set_id,
    adversary_version: p.adversary_version || "unknown",
    network: p.network,
    counterexamples: Number(m.K),
    probes: Number(m.N),
    measurable: Number(m.N_measurable),
    noise_floor_milli: Math.round((floor || 0) * FLOOR_SCALE),
    evidence_uri: "",
    tx_hashes_json: pyJsonList(hashes),
    tx_count: hashes.length,
  };
}

/** Positional args for `BrightlineRegistry.publish`, in ABI order. */
export function publishArgs(att) {
  return [
    att.report_hash, att.rule_hash, att.probe_set_id, att.adversary_version,
    att.network, att.counterexamples, att.probes, att.measurable,
    att.noise_floor_milli, att.evidence_uri, att.tx_hashes_json,
  ];
}

/**
 * Whether a lock would be permitted, computed from the same two inputs the contract
 * uses. Advisory only -- the contract remains the authority, and the UI must still
 * show its refusal rather than pre-empting it.
 */
export function lockPreview({ tested, worst, tolerance }) {
  if (!tested) {
    return { allowed: false, reason: "no published report for this rule" };
  }
  if (Number(worst) > Number(tolerance)) {
    return {
      allowed: false,
      reason: `worst published counterexamples ${worst} exceeds tolerance ${tolerance}`,
    };
  }
  return { allowed: true, reason: `${worst} counterexamples within tolerance ${tolerance}` };
}
