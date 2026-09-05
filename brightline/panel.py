"""Measurement channels.

Three ways to observe how a resolution rule behaves, in increasing fidelity to the
real network and decreasing resolution:

PANEL      one pinned model per run, leader_only. Yields the actual decision from
           each model, plus OK/LLM_ERROR status. Highest resolution: we see the
           decision distribution, not just whether someone objected.
CONSENSUS  a real leader/validator round with pinned validators. Yields the
           protocol's own agree/disagree votes. This is what settlement uses.
LIVE       a real round on a public testnet with the network's own committee.

The PANEL channel exists because of a hard protocol fact: a validator's own answer
is never published. Only its boolean vote is. So a CONSENSUS run tells us that the
jury split but not into what, and a split run stores no state at all -- the
interesting cases are exactly the ones that leave no ruling behind. PANEL recovers
the missing distribution by running each model as its own leader.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from brightline.chain import Chain, ValidatorPin, sim_config

DECISIONS = ("ACCEPT", "REJECT", "PARTIAL", "INSUFFICIENT")
STATUS_OK = "OK"
STATUS_LLM_ERROR = "LLM_ERROR"

# Classification of a single observation. INCONCLUSIVE never enters the
# disagreement numerator or its denominator -- infrastructure failure is not
# interpretive divergence, and conflating them is the easiest way to fake a signal.
AGREE = "AGREE"
DISAGREE = "DISAGREE"
INCONCLUSIVE = "INCONCLUSIVE"

# Curated from sim_getProvidersAndModels on studionet. Frontier-ish and diverse by
# vendor, which is what makes cross-model divergence meaningful rather than a
# comparison of two checkpoints of the same base model.
PANEL_MODELS: list[ValidatorPin] = [
    ValidatorPin("openrouter", "openai/gpt-5.1"),
    ValidatorPin("openrouter", "anthropic/claude-sonnet-4.5"),
    ValidatorPin("openrouter", "google/gemini-3-flash-preview"),
    ValidatorPin("openrouter", "deepseek/deepseek-v3.2"),
    ValidatorPin("openrouter", "moonshotai/kimi-k2.5"),
    ValidatorPin("openrouter", "qwen/qwen3-235b-a22b-2507"),
]

# Excluded from the default panel: on studionet this backend returns CANCELED /
# NO_MAJORITY with no leader receipt, burning ~7 minutes per probe across retries
# and contributing no observation. Kept here so the exclusion is a recorded
# decision rather than a silent omission.
PANEL_EXCLUDED: list[ValidatorPin] = [
    ValidatorPin("openrouter", "x-ai/grok-4"),
]

# Single model with an explicit temperature, for the noise-floor and sampling arms.
# gpt-5.1 is one of the studionet entries whose config surface includes temperature.
NOISE_MODEL = "openai/gpt-5.1"
NOISE_PROVIDER = "openai"


def _walk(obj: Any):
    """Yield every nested dict in a receipt so extraction survives shape drift."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def extract_return(receipt: dict) -> dict | None:
    """Pull the contract's returned payload out of a receipt.

    The receipt nests the return value differently across environments, so we look
    for any `payload.readable` that parses into our result object rather than
    hard-coding a path.
    """
    for node in _walk(receipt):
        readable = node.get("readable") if isinstance(node, dict) else None
        if not isinstance(readable, str):
            continue
        val: Any = readable
        for _ in range(3):  # readable is JSON-quoted, and our payload is JSON too
            if isinstance(val, str):
                try:
                    val = json.loads(val)
                except (ValueError, TypeError):
                    break
            else:
                break
        if isinstance(val, dict) and "decision" in val and "status" in val:
            return val
    return None


@dataclass
class Observation:
    """One model's answer, or one validator's vote."""

    label: str
    model: str
    kind: str                      # AGREE / DISAGREE / INCONCLUSIVE
    decision: str = ""
    status: str = ""
    confidence: int = 0
    reason: str = ""
    tx: str = ""
    tx_status: str = ""
    seconds: float = 0.0
    note: str = ""
    # True when a single-validator run reproduced its own decision on a second
    # sample, False when it did not, None when there was no single vote to read.
    self_consistent: bool | None = None
    attempts: int = 1


@dataclass
class ProbeResult:
    probe_id: str
    rule_hash: str
    channel: str
    observations: list[Observation] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    # ------------------------------------------------------------------ statistics
    @property
    def valid(self) -> list[Observation]:
        return [o for o in self.observations if o.kind != INCONCLUSIVE]

    @property
    def inconclusive(self) -> list[Observation]:
        return [o for o in self.observations if o.kind == INCONCLUSIVE]

    def distribution(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for o in self.valid:
            if o.decision:
                out[o.decision] = out.get(o.decision, 0) + 1
        return dict(sorted(out.items()))

    def divergence(self) -> float | None:
        """1 - (modal share). 0.0 means unanimous; 0.6 means the mode holds 40%.

        None when there is nothing valid to measure, which is reported as a health
        problem rather than silently scored as agreement.
        """
        dist = self.distribution()
        total = sum(dist.values())
        if total == 0:
            return None
        return round(1.0 - (max(dist.values()) / total), 4)

    def vote_divergence(self) -> float | None:
        """Share of validator votes that objected to the leader (CONSENSUS channel)."""
        votes = [o for o in self.observations if o.kind in (AGREE, DISAGREE)]
        if not votes:
            return None
        dis = sum(1 for o in votes if o.kind == DISAGREE)
        return round(dis / len(votes), 4)

    def self_split_rate(self) -> float | None:
        """Share of single-model runs that failed to reproduce their own decision.

        This is the measured noise floor for the probe: divergence that exists even
        without any cross-model comparison. Cross-model divergence is only evidence
        of interpretive disagreement to the extent it exceeds this.
        """
        flags = [o.self_consistent for o in self.observations
                 if o.self_consistent is not None]
        if not flags:
            return None
        return round(sum(1 for f in flags if f is False) / len(flags), 4)

    def to_dict(self) -> dict:
        return {
            "probe_id": self.probe_id,
            "rule_hash": self.rule_hash,
            "channel": self.channel,
            "distribution": self.distribution(),
            "divergence": self.divergence(),
            "vote_divergence": self.vote_divergence(),
            "self_split_rate": self.self_split_rate(),
            "net_divergence": (
                None if self.divergence() is None or self.self_split_rate() is None
                else round(self.divergence() - self.self_split_rate(), 4)
            ),
            "n_valid": len(self.valid),
            "n_inconclusive": len(self.inconclusive),
            "observations": [vars(o) for o in self.observations],
            "raw": self.raw,
        }


# ---------------------------------------------------------------------------- runs
_TX_INCONCLUSIVE = {"TIMEOUT", "VALIDATORS_TIMEOUT", "LEADER_TIMEOUT",
                    "FINISHED_WITH_ERROR", "ERROR"}


def _status_name(receipt: dict) -> str:
    for key in ("status_name", "statusName"):
        if receipt.get(key):
            return str(receipt[key])
    return str(receipt.get("status", ""))


def _result_name(receipt: dict) -> str:
    for key in ("result_name", "txExecutionResultName", "tx_execution_result_name"):
        if receipt.get(key):
            return str(receipt[key])
    return ""


def run_panel_one(ch: Chain, addr: str, rule_hash: str, probe_id: str,
                  pin: ValidatorPin, label: str | None = None,
                  attempts: int = 3, raw_dir: Path | None = None) -> Observation:
    """One model, alone, as its own leader. Gives us that model's actual decision.

    Two properties worth knowing about a single-validator `leader_only` run:

    * The leader also executes the validator path, so it re-samples its own answer
      and votes on it. One vote comes back: `agree` means the model reproduced its
      own decision on a second draw, `disagree` means it did not. That is a free
      per-run measurement of within-model sampling noise -- the noise floor arrives
      attached to every observation instead of needing a separate arm.
    * Transport hiccups against the hosted endpoint are common and are not model
      properties, so they are retried before being recorded as INCONCLUSIVE.
    """
    import time

    lab = label or f"{pin.model}@{pin.temperature if pin.temperature is not None else 'default'}"
    last_exc = ""
    t0 = time.time()

    for attempt in range(1, attempts + 1):
        rec: dict | None = None
        try:
            rec = ch.write(addr, "adjudicate", [rule_hash, probe_id],
                           sim=sim_config([pin]), leader_only=True, retries=60)
        except Exception as exc:
            last_exc = f"{type(exc).__name__}: {exc}"[:240]
            time.sleep(3 * attempt)
            continue

        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            safe = f"{pin.model.replace('/', '_')}_{probe_id[2:10]}_a{attempt}.json"
            (raw_dir / safe).write_text(json.dumps(rec, indent=2, default=str))

        elapsed = round(time.time() - t0, 1)
        payload = extract_return(rec) or {}
        tx = str(rec.get("hash") or rec.get("tx_id") or "")
        sname, rname = _status_name(rec), _result_name(rec)

        # Self-consistency: with one pinned validator there is exactly one vote, and
        # it is the model voting on its own re-sampled answer.
        votes = (rec.get("consensus_data") or {}).get("votes") or {}
        self_consistent: bool | None = None
        if len(votes) == 1:
            self_consistent = next(iter(votes.values())) == "agree"

        if not payload:
            # No leader receipt at all (backend cancelled / never executed) is
            # infrastructure, not an opinion. Retry, then give up honestly.
            if attempt < attempts:
                last_exc = f"no leader payload (status={sname}, result={rname})"
                time.sleep(3 * attempt)
                continue
            return Observation(label=lab, model=pin.model, kind=INCONCLUSIVE, tx=tx,
                               tx_status=sname, seconds=elapsed,
                               self_consistent=self_consistent, attempts=attempt,
                               note=f"no leader payload (status={sname}, result={rname})")

        status = str(payload.get("status", ""))
        if status != STATUS_OK:
            return Observation(label=lab, model=pin.model, kind=INCONCLUSIVE, tx=tx,
                               tx_status=sname, status=status, seconds=elapsed,
                               reason=str(payload.get("reason", ""))[:200],
                               self_consistent=self_consistent, attempts=attempt,
                               note="model produced no parseable decision")

        return Observation(label=lab, model=pin.model, kind=AGREE, tx=tx, tx_status=sname,
                           decision=str(payload.get("decision", "")), status=status,
                           confidence=int(payload.get("confidence", 0)),
                           reason=str(payload.get("reason", ""))[:400], seconds=elapsed,
                           self_consistent=self_consistent, attempts=attempt,
                           note=f"result={rname}")

    return Observation(label=lab, model=pin.model, kind=INCONCLUSIVE,
                       seconds=round(time.time() - t0, 1), attempts=attempts,
                       note=f"failed after {attempts} attempts: {last_exc}")


def run_panel(ch: Chain, addr: str, rule_hash: str, probe_id: str,
              pins: list[ValidatorPin], raw_dir: Path | None = None) -> ProbeResult:
    res = ProbeResult(probe_id=probe_id, rule_hash=rule_hash, channel="PANEL")
    for pin in pins:
        obs = run_panel_one(ch, addr, rule_hash, probe_id, pin, raw_dir=raw_dir)
        res.observations.append(obs)
        sc = {True: "self-ok", False: "SELF-SPLIT", None: "self-?"}[obs.self_consistent]
        tail = "" if obs.kind != INCONCLUSIVE else f"  ({obs.note[:64]})"
        print(f"    {obs.label:46s} {obs.decision or obs.kind:13s} "
              f"conf={obs.confidence:3d} {sc:10s} {obs.seconds:6.1f}s{tail}")
    return res


def run_consensus(ch: Chain, addr: str, rule_hash: str, probe_id: str,
                  pins: list[ValidatorPin] | None = None,
                  rotations: int | None = 0) -> ProbeResult:
    """A real consensus round. Votes are the protocol's own view of divergence.

    `rotations=0` keeps leader rotation from masking a split: with rotations the
    network retries under a new leader until someone's answer is acceptable, which
    is exactly the signal we are trying to observe.
    """
    import time

    res = ProbeResult(probe_id=probe_id, rule_hash=rule_hash, channel="CONSENSUS")
    t0 = time.time()
    try:
        rec = ch.write(addr, "adjudicate", [rule_hash, probe_id],
                       sim=sim_config(pins) if pins else None,
                       rotations=rotations, retries=90)
    except Exception as exc:
        res.raw = {"error": repr(exc)}
        res.observations.append(Observation(label="consensus", model="?",
                                           kind=INCONCLUSIVE, note=repr(exc)[:300]))
        return res

    elapsed = round(time.time() - t0, 1)
    cd = rec.get("consensus_data") or {}
    votes: dict[str, str] = cd.get("votes") or {}
    models: dict[str, str] = {}
    for entry in (cd.get("validators") or []):
        nc = entry.get("node_config") or {}
        pm = nc.get("primary_model") or {}
        models[str(nc.get("address", ""))] = str(pm.get("model") or nc.get("model") or "?")
    leader = cd.get("leader_receipt")
    leader = leader[0] if isinstance(leader, list) and leader else (leader or {})
    lnc = (leader.get("node_config") or {}) if isinstance(leader, dict) else {}
    lpm = lnc.get("primary_model") or {}
    leader_addr = str(lnc.get("address", ""))
    models.setdefault(leader_addr, str(lpm.get("model") or lnc.get("model") or "?"))

    payload = extract_return(rec) or {}
    res.raw = {
        "tx": str(rec.get("hash") or rec.get("tx_id") or ""),
        "status_name": _status_name(rec),
        "result_name": _result_name(rec),
        "rotation_count": rec.get("rotation_count"),
        "num_of_rounds": rec.get("num_of_rounds"),
        "num_of_initial_validators": rec.get("num_of_initial_validators"),
        "leader_address": leader_addr,
        "leader_model": models.get(leader_addr, "?"),
        "leader_payload": payload,
        "seconds": elapsed,
        "explorer": ch.explorer(str(rec.get("hash") or "")),
    }

    if not votes and ch.meta.get("api") == "node":
        # Node-API receipt: votes live in roundData[].validatorVotes, base64, one
        # byte per validator aligned to roundValidators (confirmed by E4).
        from brightline.votes import node_vote_summary

        summary = node_vote_summary(rec)
        res.raw["node_votes"] = summary
        for entry in (summary.get("per_validator") or []):
            byte = entry["byte"]
            kind = (DISAGREE if byte == 4 else AGREE if byte == 1 else INCONCLUSIVE)
            res.observations.append(Observation(
                label=f"validator:{entry['address'][:10]}", model="(network committee)",
                kind=kind, tx=res.raw["tx"], tx_status=res.raw["status_name"],
                seconds=elapsed, note=entry["name"]))
        return res

    for address, vote in sorted(votes.items()):
        role = "leader" if address == leader_addr else "validator"
        res.observations.append(Observation(
            label=f"{role}:{address[:10]}", model=models.get(address, "?"),
            kind=AGREE if vote == "agree" else DISAGREE,
            decision=str(payload.get("decision", "")) if role == "leader" else "",
            tx=res.raw["tx"], tx_status=res.raw["status_name"], seconds=elapsed,
            note=vote))
    return res
