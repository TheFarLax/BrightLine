/* Rule normalization and hashing in the browser.
 *
 * This must agree with `brightline/spec.py` byte for byte, or a rule hashed here would
 * be a different on-chain identity than the same rule hashed by the CLI. Python does:
 *
 *     unicodedata.normalize("NFKC", text)
 *     smart quotes -> ASCII
 *     re.sub(r"\s+", " ", ...)
 *     .strip()
 *     "0x" + sha256(utf-8).hexdigest()
 *
 * `tests/frontend/hash_parity.mjs` asserts equality against Python on a corpus of
 * awkward strings (CJK, combining marks, ligatures, NBSP, tabs, newlines, emoji).
 *
 * What this file deliberately does NOT do is compute a probe_id. Those are sha256 over
 * canonical JSON, and Python's `json.dumps(sort_keys=True, separators=(',',':'),
 * ensure_ascii=False)` and `JSON.stringify` disagree on key ordering for non-ASCII keys
 * and on escaping. Probe ids are read from the committed manifest, never recomputed.
 */

/** Python's `\s` in `re.sub(r"\s+", " ")` — ASCII whitespace only, not Unicode. */
const PY_WHITESPACE = /[ \t\n\r\f\v]+/g;

export function normalizeRule(text) {
  let out = String(text ?? "").normalize("NFKC");
  out = out.replace(/’/g, "'").replace(/“/g, '"').replace(/”/g, '"');
  out = out.replace(PY_WHITESPACE, " ");
  return out.trim();
}

export async function sha256Hex(text) {
  const bytes = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return `0x${[...new Uint8Array(digest)]
    .map((b) => b.toString(16).padStart(2, "0")).join("")}`;
}

/** The on-chain identity of a rule: sha256 of its normalized text. */
export async function ruleHash(text) {
  return sha256Hex(normalizeRule(text));
}

export const MAX_RULE_CHARS = 4000;      // must match the contract's cap

export function ruleProblems(text) {
  const norm = normalizeRule(text);
  const problems = [];
  if (!norm) problems.push("rule text is empty after normalization");
  if (norm.length > MAX_RULE_CHARS) {
    problems.push(`rule text is ${norm.length} chars; the contract caps it at ${MAX_RULE_CHARS}`);
  }
  return problems;
}
