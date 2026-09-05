"""E6 remaining arms: A1 (sampling), A2 (prompt sensitivity), A5 (transfer).

Criterion 5 cannot be evaluated from the main run alone, and criterion 5 is what the
pre-registered branch selection depends on, so no branch may be invoked until these
exist.

Scope, stated rather than hidden:

* A1 and A2 run on three domains (bounty, delivery, refund), loose half, probe 0.
  Enough to size the mechanical components against A4; not a full-corpus arm.
* A3 is estimated from the **control stratum** of the main run. Controls are six
  models on an identical probe whose answer is forced by the clause, so divergence
  there is capability and instruction-following spread, not interpretation. That is
  the most faithful available reading of "6 models, identical probe".
* A5 uses Bradbury's own committee. `sim_config` is Studio-only, so the live arm
  yields validator *votes*, not a decision distribution -- a different quantity from
  panel divergence. The Spearman correlation is reported with that caveat attached.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brightline.chain import Chain, ValidatorPin  # noqa: E402
from brightline.corpus import PAIRS  # noqa: E402
from brightline.calibrate import OUT, domain_probes  # noqa: E402
from brightline.panel import (  # noqa: E402
    INCONCLUSIVE,
    ProbeResult,
    run_consensus,
    run_panel_one,
)
from brightline.run import ensure_deployed  # noqa: E402
from brightline.spec import AgreementSpec, canonical, sha  # noqa: E402

A12_DOMAINS = ("bounty", "delivery", "refund")
A5_DOMAINS = tuple(PAIRS)
TEMP_PIN = ("openai", "gpt-5.1")          # studionet entry whose config exposes temperature
REPEATS = 5

# Meaning-preserving rewrites of each domain's probe 0 narrative. Facts are byte
# identical; only the prose changes. Divergence across these is prompt sensitivity.
PARAPHRASES: dict[str, list[str]] = {
    "bounty": [
        "The work that was submitted closes the issue that was reported. On the "
        "project's first automated runner every check comes back green. On a second "
        "runner one check fails, in an area unrelated to the change. Nobody has left a "
        "comment.",
        "The reported issue is closed by the submitted work. Runner one reports all "
        "checks passing; runner two reports a single failure in an unrelated area. No "
        "human has said anything.",
        "Submitted work: closes the reported issue. First runner: all checks green. "
        "Second runner: one failing check, unrelated area. Human comment: none.",
    ],
    "delivery": [
        "According to the carrier's tracking page the parcel was delivered on the 14th. "
        "The recipient says nothing ever arrived. A photograph from the carrier shows a "
        "doorway which the recipient denies is theirs.",
        "The carrier's tracking records a delivery on the 14th. The recipient denies "
        "receiving anything. The carrier's photo shows a doorway the recipient says is "
        "not at their address.",
        "Carrier tracking: delivered, 14th. Recipient: nothing arrived. Carrier photo: a "
        "doorway the recipient disputes is theirs.",
    ],
    "refund": [
        "The buyer says the item does not work. The seller tested an identical unit of "
        "the same model and it worked. A photograph from the buyer shows the item "
        "powered on and displaying an error.",
        "According to the buyer the item is not working. The seller's test of another "
        "unit of the same model succeeded. The buyer's photograph shows the item on, "
        "with an error displayed.",
        "Buyer: item does not work. Seller: an identical unit passed testing. Buyer's "
        "photo: item powered on, error on screen.",
    ],
}


def divergence_of(observations: list) -> tuple[float | None, dict, int]:
    res = ProbeResult(probe_id="", rule_hash="", channel="PANEL",
                      observations=observations)
    return res.divergence(), res.distribution(), len(res.inconclusive)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                 "temp_model": "/".join(TEMP_PIN), "repeats": REPEATS,
                 "a12_domains": list(A12_DOMAINS)}

    ch = Chain("studionet")
    if ch.balance() == 0:
        ch.fund()
        time.sleep(3)
    addr, _ = ensure_deployed(ch)
    print(f"contract {addr}")
    raw = OUT / "raw_arms"

    # ------------------------------------------------------------------ A1 and A2
    a1_cold, a1_hot, a2 = [], [], []
    for domain in A12_DOMAINS:
        spec = AgreementSpec(rule_text=PAIRS[domain][0], label=f"pair_{domain}_loose",
                             domain=domain)
        probe = domain_probes(domain)[0]
        print(f"\n=== {domain} (loose) probe0 {probe.probe_id[:12]} ===")

        for temp, bucket, tag in ((0.0, a1_cold, "A1 temp=0.0"), (0.9, a1_hot, "A1 temp=0.9")):
            obs = []
            for i in range(REPEATS):
                o = run_panel_one(ch, addr, spec.rule_hash, probe.probe_id,
                                  ValidatorPin(TEMP_PIN[0], TEMP_PIN[1], temperature=temp),
                                  label=f"{tag} #{i}", raw_dir=raw)
                obs.append(o)
                print(f"  {tag} #{i}: {o.decision or o.kind}")
            div, dist, inc = divergence_of(obs)
            bucket.append({"domain": domain, "temperature": temp, "divergence": div,
                           "distribution": dist, "inconclusive": inc})
            print(f"  -> {tag} divergence {div} {dist}")

        # A2: same model, temp 0, three paraphrased narratives, identical facts.
        obs = []
        for i, narrative in enumerate(PARAPHRASES[domain]):
            scenario = dict(probe.scenario)
            scenario["narrative"] = narrative
            blob = canonical(scenario)
            pid = sha(blob)
            if not ch.read(addr, "get_probe", [pid]):
                ch.write(addr, "register_probe", [pid, blob])
            o = run_panel_one(ch, addr, spec.rule_hash, pid,
                              ValidatorPin(TEMP_PIN[0], TEMP_PIN[1], temperature=0.0),
                              label=f"A2 paraphrase #{i}", raw_dir=raw)
            obs.append(o)
            print(f"  A2 paraphrase #{i}: {o.decision or o.kind}")
        div, dist, inc = divergence_of(obs)
        a2.append({"domain": domain, "divergence": div, "distribution": dist,
                   "inconclusive": inc})
        print(f"  -> A2 divergence {div} {dist}")

    log["A1_cold"], log["A1_hot"], log["A2"] = a1_cold, a1_hot, a2
    (OUT / "arms.json").write_text(json.dumps(log, indent=2, default=str))

    # ---------------------------------------------------------------------- A5
    print("\n=== A5 transfer: Bradbury live committee ===")
    bc = Chain("testnet-bradbury")
    baddr, fresh = ensure_deployed(bc)
    print(f"bradbury contract {baddr}{' (new)' if fresh else ''}")
    a5 = []
    for domain in A5_DOMAINS:
        spec = AgreementSpec(rule_text=PAIRS[domain][0], label=f"pair_{domain}_loose",
                             domain=domain)
        probe = domain_probes(domain)[0]
        if not bc.read(baddr, "get_rule", [spec.rule_hash]):
            bc.write(baddr, "register_rule", [spec.rule_hash, spec.normalized])
        if not bc.read(baddr, "get_probe", [probe.probe_id]):
            bc.write(baddr, "register_probe", [probe.probe_id, probe.canonical_scenario])
        res = run_consensus(bc, baddr, spec.rule_hash, probe.probe_id, rotations=0)
        d = res.to_dict()
        a5.append({"domain": domain, "vote_divergence": d["vote_divergence"],
                   "raw": d["raw"]})
        print(f"  {domain:10s} vote_divergence={d['vote_divergence']} "
              f"status={d['raw'].get('status_name')} result={d['raw'].get('result_name')}")
    log["A5"] = a5
    (OUT / "arms.json").write_text(json.dumps(log, indent=2, default=str))
    print(f"\nwrote {OUT / 'arms.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
