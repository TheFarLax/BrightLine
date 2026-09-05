"""Deployment bookkeeping so scripts and experiments share addresses per network.

Entries carry a contract `name` and the hash of the contract source they were
deployed from, so a stale address is never silently reused after the code changes.
Entries written before `name` existed are treated as the probe contract.
"""

from __future__ import annotations

import json
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / ".brightline" / "deployments.json"

DEFAULT_NAME = "probe"


def _load() -> dict:
    if not STATE.exists():
        return {}
    return json.loads(STATE.read_text())


def save_deployment(network: str, address: str, tx: str, code_hash: str,
                    runner: str = "", name: str = DEFAULT_NAME,
                    extra: dict | None = None) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    data = _load()
    entry = {"name": name, "address": address, "tx": tx,
             "code_hash": code_hash, "runner": runner}
    if extra:
        entry.update(extra)
    data.setdefault(network, []).append(entry)
    STATE.write_text(json.dumps(data, indent=2))


def latest(network: str, code_hash: str | None = None,
           name: str = DEFAULT_NAME) -> dict | None:
    """Most recent deployment of `name`, optionally requiring a matching source hash
    so we never reuse an address running older contract code."""
    for entry in reversed(_load().get(network, [])):
        if entry.get("name", DEFAULT_NAME) != name:
            continue
        if code_hash is None or entry.get("code_hash") == code_hash:
            return entry
    return None
