/* Cross-language rule-hash parity: JS must agree with brightline/spec.py exactly.
 *
 * A rule pasted in the browser and the same rule normalized by the CLI have to produce
 * the same on-chain identity. If they diverge, the frontend would register a rule the
 * CLI cannot find, or read state for a rule that is not the one on screen.
 *
 * The corpus is deliberately awkward: NBSP, tabs, newlines, combining marks, ligatures,
 * fullwidth forms, CJK, emoji, smart quotes. NFKC changes several of them, which is the
 * point -- a naive `trim()` implementation passes the easy cases and fails these.
 *
 *   node tests/frontend/hash_parity.mjs
 */

import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { normalizeRule, ruleHash, ruleProblems } from "../../frontend/lib/hash.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

const CORPUS = [
  "Pay the contributor if the contributor delivers a working fix.",
  "  leading and trailing whitespace  ",
  "collapse    multiple     spaces",
  "tabs\tand\tnewlines\nand\r\ncarriage returns",
  "non-breaking space",              // NFKC turns NBSP into a plain space
  "smart ’quotes’ and “double” quotes",
  "ﬁ ligature and ½ fraction",           // NFKC decomposes both
  "ＦＵＬＬＷＩＤＴＨ letters",             // NFKC folds to ASCII
  "combining áccent vs precomposed á",
  "CJK 支払いは修正が機能する場合に行われる",
  "emoji 🚀 and a zero-width​space",
  "Pay the bounty if the runner named in the listing reports zero failing checks.",
  "",                                     // empty
  "   ",                                  // whitespace only
  "a",                                    // single char
  "Ünïcödé accents and ß sharp s",
  "mixed  \tspacing\n\nblocks",
  "trailing period.",
  "Pay if the fix works",                 // no period; must differ from the above
  "x".repeat(500),
];

let pass = 0, fail = 0;
const check = (name, ok, detail = "") => {
  console.log(`  ${ok ? "PASS" : "FAIL"}  ${name}${ok || !detail ? "" : `\n        ${detail}`}`);
  ok ? pass++ : fail++;
};

// Ask Python for its own normalization and hash of the same strings.
const py = `
import json, sys
sys.path.insert(0, ${JSON.stringify(root)})
from brightline.spec import normalize_rule, sha
corpus = json.load(sys.stdin)
print(json.dumps([{"normalized": normalize_rule(t), "hash": sha(normalize_rule(t))}
                  for t in corpus]))
`;
const out = execFileSync(join(root, ".venv/bin/python"), ["-c", py],
  { input: JSON.stringify(CORPUS), encoding: "utf8", timeout: 120000 });
const expected = JSON.parse(out);

let mismatches = 0;
for (let i = 0; i < CORPUS.length; i++) {
  const jsNorm = normalizeRule(CORPUS[i]);
  const jsHash = await ruleHash(CORPUS[i]);
  const same = jsNorm === expected[i].normalized && jsHash === expected[i].hash;
  if (!same) {
    mismatches++;
    console.log(`  MISMATCH [${i}] ${JSON.stringify(CORPUS[i].slice(0, 40))}`);
    console.log(`      js  norm=${JSON.stringify(jsNorm.slice(0, 60))} hash=${jsHash.slice(0, 18)}`);
    console.log(`      py  norm=${JSON.stringify(expected[i].normalized.slice(0, 60))} hash=${expected[i].hash.slice(0, 18)}`);
  }
}
check(`all ${CORPUS.length} corpus strings hash identically in JS and Python`,
  mismatches === 0, `${mismatches} mismatch(es)`);

// The committed agreements are the strings that actually matter.
const agreements = execFileSync(join(root, ".venv/bin/python"), ["-c", `
import json, sys
sys.path.insert(0, ${JSON.stringify(root)})
from pathlib import Path
from brightline.spec import AgreementSpec
out = []
for p in sorted(Path(${JSON.stringify(root)}, "agreements").glob("*.yaml")):
    s = AgreementSpec.from_file(p)
    out.append({"file": p.name, "rule_text": s.rule_text, "hash": s.rule_hash})
print(json.dumps(out))
`], { encoding: "utf8", timeout: 120000 });

for (const a of JSON.parse(agreements)) {
  const jsHash = await ruleHash(a.rule_text);
  check(`committed agreement ${a.file} hashes identically`, jsHash === a.hash,
    `js ${jsHash} vs py ${a.hash}`);
}

// A hash from the browser must match what is already published on chain, or the
// settlement panel would look up a rule that does not exist.
const { readFileSync } = await import("node:fs");
const index = JSON.parse(readFileSync(join(root, "reports/index.json"), "utf8"));
const v1 = index.reports.find((r) => r.rule_label === "v1");
const v1text = JSON.parse(readFileSync(join(root, v1.path), "utf8")).rule.rule_text;
check("browser hash of the v1 rule matches the hash in the published report",
  (await ruleHash(v1text)) === v1.rule_hash,
  `js ${await ruleHash(v1text)} vs report ${v1.rule_hash}`);

// Guard rails.
check("empty and whitespace-only rules are rejected",
  ruleProblems("").length > 0 && ruleProblems("   ").length > 0);
check("over-long rules are rejected against the contract cap",
  ruleProblems("x".repeat(4001)).length > 0);
check("a normal rule has no problems", ruleProblems(CORPUS[0]).length === 0);
check("substantively different rules hash differently",
  (await ruleHash("Pay if the fix works.")) !== (await ruleHash("Pay if the fix works")));
check("cosmetically different rules hash identically",
  (await ruleHash("Pay  if the fix\tworks.")) === (await ruleHash(" Pay if the fix works. ")));

console.log(`\n${pass}/${pass + fail} hash parity checks passed`);
if (fail) process.exit(1);
