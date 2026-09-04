"""Deployment bookkeeping so scripts and experiments share one address per network."""

from __future__ import annotations

import json
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / ".brightline" / "deployments.json"


def _load() -> dict:
    if not STATE.exists():
        return {}
    return json.loads(STATE.read_text())


def save_deployment(network: str, address: str, tx: str, code_hash: str,
                    runner: str = "") -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    data = _load()
    data.setdefault(network, []).append(
        {"address": address, "tx": tx, "code_hash": code_hash, "runner": runner}
    )
    STATE.write_text(json.dumps(data, indent=2))


def latest(network: str, code_hash: str | None = None) -> dict | None:
    """Most recent deployment, optionally requiring a matching contract code hash so
    we never silently reuse an address running older contract code."""
    entries = _load().get(network, [])
    for entry in reversed(entries):
        if code_hash is None or entry.get("code_hash") == code_hash:
            return entry
    return None
