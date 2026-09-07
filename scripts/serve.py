"""Serve the repo so the viewer can fetch reports, and regenerate the report index.

No build step and no framework: the reports are artifacts of on-chain runs, and the
viewer is a thin reader over them.

    python scripts/serve.py            # http://127.0.0.1:8800/frontend/
    python scripts/serve.py --index    # regenerate reports/index.json and exit
"""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def build_index() -> dict:
    """List the report artifacts, newest-looking first, with a friendly label."""
    entries = []
    for path in sorted(REPORTS.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        if data.get("schema") != "brightline.report/1":
            continue
        m, p = data["metrics"], data["provenance"]
        entries.append({
            "file": path.name,
            "path": f"reports/{path.name}",
            "label": (f"{data['rule']['label']} · {m['K']}/{m['N']} counterexamples "
                      f"· {p['probe_set_id']}"),
            "rule_label": data["rule"]["label"],
            "rule_hash": data["rule"]["rule_hash"],
            "report_hash": data["report_hash"],
            "probe_set_id": p["probe_set_id"],
            "adversary_version": p.get("adversary_version"),
            "K": m["K"], "N": m["N"],
            # The re-test table belongs on the baseline report, where the comparison
            # starts; showing it on every report would imply each one is a diff.
            "show_retest": data["rule"]["label"] == "v1",
        })
    # Probe manifests, so the agreement tab can show exactly what will be tested.
    probes = []
    for path in sorted((ROOT / "probes").glob("ps_*.json")):
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            continue
        probes.append({"file": path.name, "path": f"probes/{path.name}",
                       "probe_set_id": data.get("probe_set_id"),
                       "n_probes": data.get("n_probes"),
                       "rule_hash": (data.get("generated_from") or {}).get("rule_hash")})

    retest = "reports/retest.json" if (REPORTS / "retest.json").exists() else None
    index = {"schema": "brightline.index/1", "reports": entries,
             "probe_sets": probes, "retest": retest}
    (REPORTS / "index.json").write_text(json.dumps(index, indent=2))
    return index


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, fmt, *args):   # quieter console
        if "GET /reports" in (fmt % args) or "GET /frontend" in (fmt % args):
            super().log_message(fmt, *args)


def main() -> int:
    ap = argparse.ArgumentParser(prog="serve")
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--index", action="store_true", help="rebuild the index and exit")
    args = ap.parse_args()

    # Keep the browser's view of deployments in step with the CLI's record.
    import subprocess
    subprocess.run([sys.executable, str(ROOT / "scripts" / "export_frontend_config.py")],
                   check=False)

    index = build_index()
    print(f"indexed {len(index['reports'])} report(s), "
          f"{len(index['probe_sets'])} probe set(s)"
          f"{' + retest' if index['retest'] else ''}")
    for e in index["reports"]:
        print(f"  {e['label']}")
    if args.index:
        return 0

    with socketserver.TCPServer(("127.0.0.1", args.port), Handler) as httpd:
        print(f"\nviewer: http://127.0.0.1:{args.port}/frontend/")
        print("ctrl-c to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
