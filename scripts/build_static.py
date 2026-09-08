"""Assemble `dist/` — everything the dApp needs, and nothing that must stay private.

The dApp has no build step: it is ES modules the browser loads directly. So this is a
copy, not a compile. The only real work is deciding what ships.

What ships is chosen by what the page actually fetches. Every path in the app is
relative to `frontend/` and reaches one level up (`../reports/index.json`,
`../probes/ps_*.json`, `../frontend/networks.json`), so `dist/` mirrors the repo's
layout instead of flattening it. That way the deployed site and `scripts/serve.py`
serve byte-identical URLs and there is no rewriting step to get wrong.

Deliberately excluded:
  .brightline/    local dev keys and deployment bookkeeping
  reports/raw/    5.4 MB of raw receipts -- evidence, kept in the repo, not a page asset
  experiments/    same
  node_modules/   the dApp has no runtime dependency; the SDK is vendored

Deliberately included even though no fetch touches them: the human-readable `.md`
reports and `docs/`. Every number on the page is a claim about a real transaction, and
a deployed page whose evidence lives somewhere else is a weaker artifact.

    python scripts/build_static.py            # -> dist/
    python scripts/build_static.py --out /tmp/x --serve 8899
"""

from __future__ import annotations

import argparse
import http.server
import shutil
import socketserver
import subprocess
import sys
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

REDIRECT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Brightline</title>
<meta http-equiv="refresh" content="0; url=frontend/">
<link rel="canonical" href="frontend/">
</head>
<body>
<p>Brightline — an agreement fuzzer, run by the network that will later judge the
agreement. <a href="frontend/">Open the dApp</a>.</p>
</body>
</html>
"""


def human(n: int) -> str:
    return f"{n / 1024:.0f}K" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f}M"


def copy_tree(src: Path, dst: Path, *, patterns: list[str] | None = None) -> list[Path]:
    """Copy `src` to `dst`. With `patterns`, take only *top-level* matching files.

    Top-level is the point. `reports/` holds three published artifacts beside a 5.4 MB
    `raw/` receipt archive, and neither `Path.match` nor `fnmatch` would keep them
    apart: both are happy to let `*.json` match `raw/v1_.../probe_00.json`.
    """
    written = []
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if patterns and not (rel.parent == Path(".")
                             and any(fnmatch(rel.name, p) for p in patterns)):
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        written.append(out)
    return written


def build(out: Path) -> Path:
    # Regenerate both machine-written inputs first, so a stale index or a network
    # config from an older deployment can never be what gets published.
    subprocess.run([sys.executable, str(ROOT / "scripts" / "export_frontend_config.py")],
                   check=True)
    from serve import build_index          # noqa: E402  (path set above)
    index = build_index()

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    groups = {
        # Verbatim: index.html, app.js, lib/, components/, vendor/, networks.json.
        "frontend": copy_tree(ROOT / "frontend", out / "frontend"),
        # reports/raw/ is excluded by the pattern: rglob would otherwise pull 5.4 MB
        # of receipts into a page asset bundle.
        "reports": copy_tree(ROOT / "reports", out / "reports", patterns=["*.json", "*.md"]),
        "probes": copy_tree(ROOT / "probes", out / "probes", patterns=["ps_*.json"]),
        "docs": copy_tree(ROOT / "docs", out / "docs", patterns=["*.md"]),
    }
    (out / "index.html").write_text(REDIRECT)

    print(f"\ndist -> {out}")
    total = 0
    for name, files in groups.items():
        size = sum(f.stat().st_size for f in files)
        total += size
        print(f"  {name:<10} {len(files):>3} file(s)  {human(size):>7}")
    print(f"  {'total':<10} {'':>3}          {human(total + len(REDIRECT)):>7}")
    print(f"\n  {len(index['reports'])} report(s), {len(index['probe_sets'])} probe set(s)")

    # A missing asset here is a blank panel in production, so check rather than trust.
    required = [
        "frontend/index.html", "frontend/app.js", "frontend/networks.json",
        "frontend/vendor/genlayer-js.js", "reports/index.json",
    ]
    required += [e["path"] for e in index["reports"]]
    required += [p["path"] for p in index["probe_sets"]]
    if index["retest"]:
        required.append(index["retest"])
    missing = [r for r in required if not (out / r).exists()]
    if missing:
        raise SystemExit(f"missing from dist: {missing}")

    # The one thing that must never ship.
    leaked = [p for p in out.rglob("*") if ".brightline" in p.parts or "raw" in p.parts]
    if leaked:
        raise SystemExit(f"private or oversized files leaked into dist: {leaked[:5]}")

    print(f"\n  {len(required)} required asset(s) present, nothing private included")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="build_static")
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--serve", type=int, metavar="PORT",
                    help="serve the built dist to check it before deploying")
    args = ap.parse_args()

    out = build(Path(args.out).resolve())
    if args.serve:
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=str(out), **kw)

        with socketserver.TCPServer(("127.0.0.1", args.serve), Handler) as httpd:
            print(f"\nserving dist: http://127.0.0.1:{args.serve}/")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nstopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
