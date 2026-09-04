"""E3 + E4 -- Bradbury network truth and the validatorVotes decode.

E3  a real transaction on the public testnet reaches Accepted/Finalized.
E4  the `roundData[].validatorVotes` base64 blob decodes as inferred: one byte per
    validator, positionally aligned to `roundValidators`, values from the vote-type
    enum where 4 == NondetDisagree.

E4 is an *inference* from the documented example (5 validators, 5 entries in
roundValidators, validatorVotes "AAAAAAA=" decoding to five zero bytes while
votesRevealed was 0 and 0 == NotVoted). It is not documented. This script confirms
or refutes it against a real receipt, and the documented fallback is recorded in the
result either way:

    fallback = transaction-level txExecutionResult == 4 (NondetDisagree) as a 1-bit
    per-probe signal, plus the cardinality of distinct validatorResultHash values as
    a coarse divergence proxy.

Requires a funded account on Bradbury. The faucet needs GitHub OAuth plus a
Cloudflare Turnstile challenge, so funding is a human step:

    https://testnet-faucet.genlayer.foundation/   ->  fund the address printed below
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import Chain  # noqa: E402
from brightline.panel import _result_name, _status_name, extract_return  # noqa: E402
from brightline.run import CONTRACT, ensure_deployed, ensure_registered  # noqa: E402
from brightline.spec import AgreementSpec, ProbeSet  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "experiments" / "E3_E4_bradbury"

VOTE_ENUM = {0: "NotVoted", 1: "FinishedWithReturn", 2: "FinishedWithError",
             3: "Timeout", 4: "NondetDisagree", 5: "DeterministicViolation"}


def decode_votes(round_data: dict) -> dict:
    """Test the one load-bearing inference about the receipt format."""
    blob = round_data.get("validatorVotes") or ""
    validators = round_data.get("roundValidators") or []
    out: dict = {
        "raw": blob,
        "n_validators": len(validators),
        "votes_revealed": round_data.get("votesRevealed"),
        "votes_committed": round_data.get("votesCommitted"),
    }
    try:
        decoded = base64.b64decode(blob) if blob else b""
    except Exception as exc:
        out["decode_error"] = repr(exc)
        return out
    out["decoded_bytes"] = list(decoded)
    out["byte_count"] = len(decoded)
    out["aligns_with_validator_count"] = (
        len(decoded) == len(validators) and len(validators) > 0
    )
    out["all_bytes_in_enum"] = all(b in VOTE_ENUM for b in decoded)
    if out["aligns_with_validator_count"]:
        out["per_validator"] = [
            {"address": validators[i], "byte": decoded[i],
             "name": VOTE_ENUM.get(decoded[i], f"unknown({decoded[i]})")}
            for i in range(len(decoded))
        ]
        out["n_nondet_disagree"] = sum(1 for b in decoded if b == 4)
    return out


def fallback_signal(receipt: dict) -> dict:
    """The documented path that needs no inference."""
    rd = (receipt.get("roundData") or [{}])[0]
    hashes = [h for h in (rd.get("validatorResultHash") or []) if h]
    return {
        "txExecutionResult": receipt.get("txExecutionResult"),
        "txExecutionResultName": receipt.get("txExecutionResultName"),
        "is_nondet_disagree": receipt.get("txExecutionResult") == 4,
        "distinct_result_hashes": len(set(hashes)),
        "result_hash_count": len(hashes),
    }


def main(network: str = "testnet-bradbury") -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    ch = Chain(network)
    log: dict = {"network": network, "address": ch.address(),
                 "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    print(f"account   {ch.address()}")
    bal = ch.balance()
    log["balance"] = str(bal)
    print(f"balance   {bal}")
    if bal == 0:
        print("\nBLOCKED: no funds on this network.")
        print("The faucet requires GitHub OAuth + Cloudflare Turnstile, so this is a")
        print("human step. Fund this address and re-run:")
        print(f"\n    https://testnet-faucet.genlayer.foundation/")
        print(f"    {ch.address()}\n")
        log["gate_e3_pass"] = False
        log["gate_e4_pass"] = None
        log["blocked_on"] = "faucet funding (GitHub OAuth + Turnstile)"
        (OUT / "result.json").write_text(json.dumps(log, indent=2))
        return 3

    # Capability check before spending anything.
    for method, params in (("gen_dbg_ping", []),
                           ("gen_getTransactionReceipt", [{"txId": "0x" + "00" * 32}])):
        ok, _ = ch.rpc_supports(method, params)
        log.setdefault("rpc", {})[method] = ok
        print(f"rpc       {method}: {'ok' if ok else 'ABSENT'}")

    spec = AgreementSpec.from_file(
        Path(__file__).resolve().parent.parent / "agreements" / "bounty_working_fix_v1.yaml")
    ps = ProbeSet.load(sorted((Path(__file__).resolve().parent.parent / "probes").glob("*.json"))[0])
    # The conflicting-evidence probe is the one that split the studionet panel, so it
    # is the best candidate for producing a real NondetDisagree on-chain.
    probe = next(p for p in ps.probes if p.family == "conflicting_evidence")
    log["rule_hash"], log["probe_id"] = spec.rule_hash, probe.probe_id

    addr, fresh = ensure_deployed(ch)
    log["contract_address"] = addr
    print(f"contract  {addr}{' (new)' if fresh else ''}")
    ensure_registered(ch, addr, spec, ps)

    print("\nadjudicating with rotations=0 so a split is not masked by rotation ...")
    t0 = time.time()
    rec = ch.write(addr, "adjudicate", [spec.rule_hash, probe.probe_id],
                   rotations=0, retries=90)
    tx = str(rec.get("hash") or rec.get("tx_id") or "")
    log["e3"] = {"tx": tx, "status": _status_name(rec), "result": _result_name(rec),
                 "seconds": round(time.time() - t0, 1),
                 "payload": extract_return(rec),
                 "explorer": ch.explorer(tx)}
    print(f"  tx {tx}\n  status={log['e3']['status']} result={log['e3']['result']} "
          f"({log['e3']['seconds']}s)")
    (OUT / "receipt_sdk.json").write_text(json.dumps(rec, indent=2, default=str))
    log["gate_e3_pass"] = bool(tx) and log["e3"]["status"].upper() not in ("", "CANCELED")

    node = ch.node_receipt(tx)
    if node is None:
        log["gate_e4_pass"] = False
        log["e4"] = {"error": "gen_getTransactionReceipt unavailable on this endpoint"}
    else:
        (OUT / "receipt_node.json").write_text(json.dumps(node, indent=2, default=str))
        rounds = node.get("roundData") or []
        log["e4"] = {
            "numOfInitialValidators": node.get("numOfInitialValidators"),
            "initialRotations": node.get("initialRotations"),
            "statusName": node.get("statusName"),
            "epoch": node.get("epoch"),
            "n_rounds": len(rounds),
            "fallback": fallback_signal(node),
            "rounds": [decode_votes(r) for r in rounds],
        }
        first = log["e4"]["rounds"][0] if log["e4"]["rounds"] else {}
        log["gate_e4_pass"] = bool(first.get("aligns_with_validator_count")
                                   and first.get("all_bytes_in_enum"))
        print(f"\n  E4 decode: bytes={first.get('byte_count')} "
              f"validators={first.get('n_validators')} "
              f"aligned={first.get('aligns_with_validator_count')} "
              f"enum_ok={first.get('all_bytes_in_enum')}")
        for pv in (first.get("per_validator") or []):
            print(f"    {pv['address'][:12]} byte={pv['byte']} {pv['name']}")
        print(f"  fallback : {log['e4']['fallback']}")

    (OUT / "result.json").write_text(json.dumps(log, indent=2, default=str))
    print(f"\nE3 GATE: {'PASS' if log.get('gate_e3_pass') else 'FAIL'}")
    print(f"E4 GATE: {'PASS' if log.get('gate_e4_pass') else 'FAIL (use fallback)'}")
    print(f"evidence: {OUT}")
    return 0 if log.get("gate_e3_pass") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "testnet-bradbury"))
