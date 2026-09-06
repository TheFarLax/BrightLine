"""Cross-language parity: the browser must publish the same facts as the CLI.

The frontend projects a report into a registry attestation in JS; `brightline.publish`
does it in Python. If those diverge, the same report published from the two paths would
assert different things on-chain -- including `tx_hashes_json`, where Python's default
`", "` separator and JS's `JSON.stringify` disagree unless matched deliberately.

Skipped rather than failed when node is unavailable, so the Python suite stays runnable
on a machine without it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from brightline.publish import report_to_attestation  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
REPORTS = sorted((ROOT / "reports").glob("v*_studionet.json"))

# str.format would eat every brace in the JS, so this uses a plain token instead.
NODE_SNIPPET = """
import { readFileSync } from "node:fs";
import { reportToAttestation, publishArgs, lockPreview }
  from "__ROOT__/frontend/lib/attest.js";
const report = JSON.parse(readFileSync(process.argv[2], "utf8"));
const att = reportToAttestation(report);
process.stdout.write(JSON.stringify({
  att, args: publishArgs(att),
  preview_allow: lockPreview({ tested: true, worst: att.counterexamples,
                               tolerance: att.counterexamples }),
  preview_refuse: lockPreview({ tested: true, worst: att.counterexamples,
                                tolerance: att.counterexamples - 1 }),
  preview_untested: lockPreview({ tested: false, worst: 0, tolerance: 99 }),
}));
"""


def _node_attestation(report_path: Path, tmp_path: Path) -> dict:
    script = tmp_path / "att.mjs"
    script.write_text(NODE_SNIPPET.replace("__ROOT__", ROOT.as_posix()))
    out = subprocess.run(["node", str(script), str(report_path)],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr[:600]
    return json.loads(out.stdout)


pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node not available for JS parity")


@pytest.mark.parametrize("report_path", REPORTS, ids=lambda p: p.stem)
def test_js_attestation_matches_python(report_path, tmp_path):
    report = json.loads(report_path.read_text())
    py = report_to_attestation(report)
    py["tx_count"] = py.pop("_tx_count")
    js = _node_attestation(report_path, tmp_path)["att"]
    assert js == py, f"projection diverged: { {k: (js.get(k), py.get(k)) for k in set(js) | set(py) if js.get(k) != py.get(k)} }"


@pytest.mark.parametrize("report_path", REPORTS[:1], ids=lambda p: p.stem)
def test_publish_args_are_in_abi_order(report_path, tmp_path):
    """The registry takes 11 positional args; order is not something to get wrong."""
    js = _node_attestation(report_path, tmp_path)
    args = js["args"]
    assert len(args) == 11
    att = js["att"]
    assert args[0] == att["report_hash"]
    assert args[1] == att["rule_hash"]
    assert args[5] == att["counterexamples"]
    assert args[6] == att["probes"]
    assert args[10] == att["tx_hashes_json"]


@pytest.mark.parametrize("report_path", REPORTS[:1], ids=lambda p: p.stem)
def test_lock_preview_mirrors_the_contract_gate(report_path, tmp_path):
    js = _node_attestation(report_path, tmp_path)
    assert js["preview_allow"]["allowed"] is True
    assert js["preview_refuse"]["allowed"] is False
    assert "exceeds tolerance" in js["preview_refuse"]["reason"]
    assert js["preview_untested"]["allowed"] is False
    assert "no published report" in js["preview_untested"]["reason"]


def test_attestation_still_carries_no_score(tmp_path):
    """Guard the E6 boundary from the JS side too, not just the Python side."""
    js = _node_attestation(REPORTS[0], tmp_path)["att"]
    forbidden = ("split", "score", "divergence", "auc", "mean")
    for key in js:
        assert not any(f in key.lower() for f in forbidden), key
