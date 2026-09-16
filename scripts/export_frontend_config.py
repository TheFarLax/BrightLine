"""Export the network + deployment config the browser needs.

The private key store in `.brightline/` never leaves this machine; only addresses and
public network parameters are exported. The viewer refuses to act on a network with no
recorded deployment, so this file is what decides which networks are usable at all.

`wallet_writes` is a deliberate, per-network switch rather than a UI guess:

* studio-next -- chain 61997, the default and the network the dApp writes to. Verified
  end to end by scripts/verify_studio_next.py: 20 live checks, real transactions.
* studionet -- chain 61999, stable Studio. Every published measurement was taken here
  and its reports stay readable, but its contracts are the GenVM 0.2 build.
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
from brightline.genvm03 import runner_for, source_for  # noqa: E402
from brightline.spec import sha  # noqa: E402
from brightline.state import latest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "networks.json"

CONTRACTS = {
    "probe": ROOT / "contracts" / "brightline_probe.py",
    "registry": ROOT / "contracts" / "brightline_registry.py",
    "escrow": ROOT / "contracts" / "gated_escrow.py",
}

# The network the submission is verified on. Studio Next is where the contracts the
# dApp writes to live; stable Studio stays in the config because every published
# measurement was taken there and those reports still have to be readable.
DEFAULT_NETWORK = "studio-next"

# genlayer-js chain keys, which differ from our CLI network names. genlayer-js calls
# chain 61997 `studioDevnet`; Studio Next is the same chain under the name the network
# is deployed as.
JS_CHAIN = {
    "localnet": "localnet",
    "studionet": "studionet",
    "studio-next": "studioDevnet",
    "testnet-bradbury": "testnetBradbury",
    "testnet-asimov": "testnetAsimov",
}

EXPLORER_TX = {
    "studionet": "https://explorer-studio.genlayer.com/tx/",
    # genlayer-js leaves `blockExplorers` undefined for 61997 on the grounds that the
    # stable Studio explorer does not index it. A separate one does, and this URL was
    # checked against a real 61997 transaction rather than assumed.
    "studio-next": "https://explorer-studio-dev.genlayer.com/tx/",
    "testnet-bradbury": "https://explorer-bradbury.genlayer.com/tx/",
    "testnet-asimov": "https://explorer-asimov.genlayer.com/tx/",
}

EXPLORER_ADDRESS = {
    "studionet": "https://explorer-studio.genlayer.com/address/",
    "studio-next": "https://explorer-studio-dev.genlayer.com/address/",
    "testnet-bradbury": "https://explorer-bradbury.genlayer.com/address/",
}

# Which networks the *vendored browser SDK* can talk to at all.
#
# genlayer-js 2.0.0-rc.1 is required for Studio Next -- 1.x cannot even encode a
# consensus v0.6 transaction -- and that same build cannot read stable Studio: a
# `gen_call` against 61999 comes back `execution failed`, for reads as well as writes.
# Tested both ways round, in the vendored bundle, against the real registries.
#
# So this is not a preference, it is a constraint: one vendored SDK, one Studio
# generation. The dApp acts on Studio Next, and stable Studio stays in the config as a
# record of where the published measurements came from rather than as something the
# browser pretends it can query. Nothing is lost from the artifact: every report, every
# counterexample and every receipt renders with no chain access at all, and the CLI
# (genlayer-py 0.16.3, .venv) still reads and writes 61999 exactly as before.
SDK_READS = {"studio-next": True, "studionet": False, "localnet": False,
             "testnet-bradbury": False, "testnet-asimov": False}

# Wallet writes are only offered where they have actually been verified.
WALLET_WRITES = {"studio-next": True,
                 "studionet": False, "localnet": False,
                 "testnet-bradbury": False, "testnet-asimov": False}

WALLET_NOTE = {
    "studionet": ("stable Studio, chain 61999: where every published measurement was "
                  "taken. Its contracts are the GenVM 0.2 build, and the genlayer-js "
                  "2.0.0-rc.1 bundle this dApp needs for Studio Next cannot query it. "
                  "The reports and receipts below are that evidence and need no chain; "
                  "reproduce them from the CLI with --network studionet"),
    "testnet-bradbury": ("CLI-only for now: genlayer-py needed an explicit gas limit "
                         "to land a write here and genlayer-js is unverified on this "
                         "network"),
    "testnet-asimov": "untested",
}

CHAIN_IDS = {"studionet": 61999, "studio-next": 61997, "testnet-bradbury": 4221,
             "testnet-asimov": 4221, "localnet": 61999}


def contract_addresses(network: str) -> dict:
    out: dict[str, dict | None] = {}
    for name, path in CONTRACTS.items():
        # Hash the source as deployed on this network. Studio Next runs the GenVM 0.3
        # adaptation of the same contract, so hashing the file verbatim would mark a
        # correct deployment STALE and hide it from the UI.
        code_hash = sha(source_for(network, path))
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
            "explorer_address": EXPLORER_ADDRESS.get(name),
            "runner": runner_for(name),
            "wallet_writes": bool(WALLET_WRITES.get(name)),
            "wallet_note": WALLET_NOTE.get(name, ""),
            # sim_config drives the pinned-model panel and is Studio-only, so a live
            # adjudication can only run where this is true.
            "supports_sim_config": meta.get("api", "studio") == "studio",
            "contracts": addresses,
            # Deployed *and* reachable by the vendored SDK. A network the browser cannot
            # query is not usable in the browser, however healthy its contracts are.
            "deployed": all(addresses[k] and addresses[k]["current"]
                            for k in ("probe", "registry", "escrow")),
            "usable": bool(SDK_READS.get(name))
                      and all(addresses[k] and addresses[k]["current"]
                              for k in ("probe", "registry", "escrow")),
        }
    return {
        "schema": "brightline.networks/1",
        "default": DEFAULT_NETWORK,
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
