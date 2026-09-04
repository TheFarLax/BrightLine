#!/usr/bin/env bash
# Brightline environment setup. Records the two non-obvious steps this host needed.
set -euo pipefail
cd "$(dirname "$0")/.."

# genlayer-test requires Python >= 3.12; the system default here is 3.10.
/usr/bin/python3.12 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "genlayer-test[sim]" genlayer-py requests pytest genvm-linter

# gltest direct mode picks the newest cached GenVM tarball. v0.6.0-rc0 ships a
# layout with no `runners/` entries, so direct-mode deploys fail with
# "No py-genlayer runners found in tarball". Keep only a tarball that carries the
# runners; v0.3.0-rc7 contains our pinned py-genlayer:1jb45aa8...
CACHE=/root/.cache/gltest-direct
if [ -f "$CACHE/genvm-universal-v0.6.0-rc0.tar.xz" ]; then
  mkdir -p "$CACHE/unsupported"
  mv "$CACHE/genvm-universal-v0.6.0-rc0.tar.xz" "$CACHE/unsupported/"
fi

.venv/bin/genvm-lint check contracts/brightline_probe.py
.venv/bin/python -m pytest tests/unit tests/direct -q
echo "ready"
