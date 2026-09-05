"""Export the network + deployment config the browser needs.

The private key store in `.brightline/` never leaves this machine; only addresses and
public network parameters are exported. The viewer refuses to act on a network with no
recorded deployment, so this file is what decides which networks are usable at all.

`wallet_writes` is a deliberate, per-network switch rather than a UI guess:

* studionet -- the only network verified for wallet writes. `sim_config` (the pinned
  model panel) is Studio-only anyway, so it is also the only network where a live
  adjudication can run at all.
* testnet-bradbury -- writes work from the CLI only, through the gas-headroom path in
  `NodeWriteMixin`. genlayer-js has not been verified there, so the UI must not offer
  wallet writes until it is.

    python scripts/export_frontend_config.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import NETWORKS  # noqa: E402
from brightline.spec import sha  # noqa: E402
from brightline.state import latest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "networks.json"

CONTRACTS = {
    "probe": ROOT / "contracts" / "brightline_probe.py",
    "registry": ROOT / "contracts" / "brightline_registry.py",
    "escrow": ROOT / "contracts" / "gated_escrow.py",
}

# genlayer-js chain keys, which differ from our CLI network names.
JS_CHAIN = {
    "localnet": "localnet",
    "studionet": "studionet",
    "testnet-bradbury": "testnetBradbury",
    "testnet-asimov": "testnetAsimov",
}

EXPLORER_TX = {
    "studionet": "https://explorer-studio.genlayer.com/tx/",
    "testnet-bradbury": "https://explorer-bradbury.genlayer.com/tx/",
    "testnet-asimov": "https://explorer-asimov.genlayer.com/tx/",
}

# Wallet writes are only offered where they have actually been verified.
WALLET_WRITES = {"studionet": True, "localnet": True,
                 "testnet-bradbury": False, "testnet-asimov": False}

WALLET_NOTE = {
    "testnet-bradbury": ("CLI-only for now: genlayer-py needed an explicit gas limit "
                         "to land a write here and genlayer-js is unverified on this "
                         "network"),
    "testnet-asimov": "untested",
}

CHAIN_IDS = {"studionet": 61999, "testnet-bradbury": 4221,
             "testnet-asimov": 4221, "localnet": 61999}


def contract_addresses(network: str) -> dict:
    out: dict[str, dict | None] = {}
    for name, path in CONTRACTS.items():
        code_hash = sha(path.read_text())
        entry = latest(network, code_hash, name=name)
        stale = latest(network, None, name=name)
        if entry:
            out[name] = {"address": entry["address"], "code_hash": code_hash,
                         "runner": entry.get("runner", ""), "current": True}
        elif stale:
            # An address exists but was deployed from different source. Surfaced
            # rather than hidden: silently reusing it would make the UI read state
            # from a contract that is not the one in this repo.
            out[name] = {"address": stale["address"],
                         "code_hash": stale.get("code_hash", ""),
                         "runner": stale.get("runner", ""), "current": False}
        else:
            out[name] = None
    return out


def build() -> dict:
    networks = {}
    for name, meta in NETWORKS.items():
        addresses = contract_addresses(name)
        networks[name] = {
            "label": name,
            "js_chain": JS_CHAIN.get(name),
            "rpc": meta["rpc"],
            "chain_id": CHAIN_IDS.get(name),
            "api": meta.get("api", "studio"),
            "faucet": meta["faucet"],
            "explorer_tx": EXPLORER_TX.get(name),
            "wallet_writes": bool(WALLET_WRITES.get(name)),
            "wallet_note": WALLET_NOTE.get(name, ""),
            # sim_config drives the pinned-model panel and is Studio-only, so a live
            # adjudication can only run where this is true.
            "supports_sim_config": meta.get("api", "studio") == "studio",
            "contracts": addresses,
            "usable": all(addresses[k] and addresses[k]["current"]
                          for k in ("probe", "registry", "escrow")),
        }
    return {
        "schema": "brightline.networks/1",
        "default": "studionet",
        "networks": networks,
        "notes": {
            "wallet_snap": "npm:genlayer-wallet-plugin (MetaMask Snap)",
            "scope": ("Split Score is an experimental studionet lab instrument; it is "
                      "never a gating input. The escrow gates on published-report "
                      "existence plus the payer's worst-counterexample tolerance."),
        },
    }


def main() -> int:
    cfg = build()
    OUT.write_text(json.dumps(cfg, indent=2))
    print(f"wrote {OUT.relative_to(ROOT)}")
    for name, n in cfg["networks"].items():
        marks = []
        for key in ("probe", "registry", "escrow"):
            c = n["contracts"][key]
            marks.append(f"{key}={'-' if not c else c['address'][:10] + ('' if c['current'] else ' STALE')}")
        print(f"  {name:18s} usable={str(n['usable']):5s} "
              f"wallet_writes={str(n['wallet_writes']):5s} {' '.join(marks)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
