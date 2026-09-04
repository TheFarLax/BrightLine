# Brightline re-test

frozen probe set `ps_6ce467da9d20c1f2`

| arm | rule | probe set | counterexamples | mean divergence |
|---|---|---|---|---|
| baseline | v1 | frozen | **4 / 8** | 0.3125 |
| regression | v2 | frozen (same ids) | **4 / 8** | 0.225 |
| generalization | v2 | fresh `ps_4a8062c5562c47a4` | **2 / 8** | 0.0625 |

closed 2 · still split 2 · newly opened 2

| probe | family | before | after | |
|---|---|---|---|---|
| #0 | regression_after_fix | 0.6667 | 0.5 | still split |
| #1 | conflicting_evidence | 0.5 | 0.4 | still split |
| #2 | conflicting_evidence | 0.1667 | 0.3333 | OPENED |
| #3 | late_evidence | 0.0 | 0.0 | clean |
| #4 | partial_completion | 0.5 | 0.0 | closed |
| #5 | partial_completion | 0.1667 | 0.4 | OPENED |
| #6 | missing_confirmation | 0.1667 | 0.1667 | clean |
| #7 | criteria_gap | 0.3333 | 0.0 | closed |

**Verdict.** frozen counterexamples unchanged at 4; mean divergence fell 0.3125->0.225; 2 probe(s) closed; 2 newly opened. the fresh set aimed at the new rule found 2/8 (mean 0.0625) -- better than the frozen set, so the rewrite generalized.