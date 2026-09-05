"""Validator vote extraction, for both receipt shapes.

Studio-era receipts carry `consensus_data.votes` (address -> agree/disagree) plus
per-validator model attribution. Node-API receipts (Bradbury, Asimov) carry
`roundData[].validatorVotes`, a base64 blob of one byte per validator positionally
aligned to `roundValidators`, with values from the documented vote-type enum.

That alignment was an inference until E4 confirmed it on real revealed votes:
`byte_count == n_validators == votesRevealed`, every byte in the enum, and two
independent vectors observed -- `[1,1,1,1,1]` (unanimous) and `[1,1,1,1,3]` (one
Timeout, two distinct result hashes).
"""

from __future__ import annotations

import base64

# From gen_getTransactionReceipt's documented txExecutionResult enum.
VOTE_ENUM = {0: "NotVoted", 1: "FinishedWithReturn", 2: "FinishedWithError",
             3: "Timeout", 4: "NondetDisagree", 5: "DeterministicViolation"}

# What counts as this validator objecting to the leader's non-deterministic result.
DISAGREE_BYTES = {4}
# Votes that say nothing about interpretation: never counted either way.
INCONCLUSIVE_BYTES = {0, 2, 3, 5}


def informative_round(rounds: list[dict]) -> dict:
    """Pick the round entry that actually carries revealed votes.

    Bradbury appends several entries all labelled `round: 0`, one per attempt. The
    pre-reveal entry has all-zero vote bytes and would read as "nobody disagreed".
    """
    revealed = [r for r in rounds if int(r.get("votesRevealed") or 0) > 0]
    if revealed:
        return revealed[-1]
    return rounds[-1] if rounds else {}


def decode_round_votes(round_data: dict) -> dict:
    """Decode one round entry's vote blob. Never raises."""
    blob = round_data.get("validatorVotes") or ""
    validators = list(round_data.get("roundValidators") or [])
    out: dict = {
        "raw": blob,
        "n_validators": len(validators),
        "votes_revealed": round_data.get("votesRevealed"),
        "votes_committed": round_data.get("votesCommitted"),
        "leader_index": round_data.get("leaderIndex"),
    }
    try:
        decoded = base64.b64decode(blob) if blob else b""
    except Exception as exc:
        out["decode_error"] = repr(exc)[:200]
        return out

    out["decoded_bytes"] = list(decoded)
    out["byte_count"] = len(decoded)
    out["aligns_with_validator_count"] = (
        len(decoded) == len(validators) and len(validators) > 0)
    out["all_bytes_in_enum"] = all(b in VOTE_ENUM for b in decoded)
    if out["aligns_with_validator_count"]:
        out["per_validator"] = [
            {"address": validators[i], "byte": decoded[i],
             "name": VOTE_ENUM.get(decoded[i], f"unknown({decoded[i]})")}
            for i in range(len(decoded))
        ]
        hashes = [h for h in (round_data.get("validatorResultHash") or []) if h]
        out["distinct_result_hashes"] = len(set(hashes))
        out["n_disagree"] = sum(1 for b in decoded if b in DISAGREE_BYTES)
        out["n_inconclusive"] = sum(1 for b in decoded if b in INCONCLUSIVE_BYTES)
        counted = len(decoded) - out["n_inconclusive"]
        out["vote_divergence"] = (round(out["n_disagree"] / counted, 4)
                                  if counted > 0 else None)
    return out


def node_vote_summary(receipt: dict) -> dict:
    """Vote divergence for a node-API receipt, with the fallback signal attached."""
    rounds = receipt.get("roundData") or []
    chosen = informative_round(rounds)
    summary = decode_round_votes(chosen)
    summary["fallback"] = {
        "txExecutionResult": receipt.get("txExecutionResult"),
        "txExecutionResultName": receipt.get("txExecutionResultName"),
        "is_nondet_disagree": receipt.get("txExecutionResult") == 4,
    }
    summary["n_round_entries"] = len(rounds)
    summary["status_name"] = receipt.get("statusName")
    return summary
