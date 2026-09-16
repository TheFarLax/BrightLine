"""E9 -- prove the Studio Next deployment works, with real transactions.

Same gate E8 applies on stable Studio, run against chain 61997 under consensus v0.6 and
GenVM 0.3. Nothing here is mocked: every assertion below is a transaction that had to
reach a terminal consensus status on Studio Next.

  1. the probe's deterministic path         register_rule / register_probe, then read back
  2. the registry accepts a real attestation the v1 report, verbatim, worst K = 4
  3. the gate refuses a tolerance below K   "rule has 4 counterexamples, deal tolerates 3"
  4. the refused deal is still OPEN         the gate declines the transition, not the call
  5. a new deal at tolerance 4 locks        counterexamples_at_lock frozen at 4
  6. the gate refuses an untested rule      the other refusal path

    .venv-rc/bin/python scripts/verify_studio_next.py

Writes experiments/E9_studio_next/verification.json, including every transaction hash so
the run can be recomputed from the explorer.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import genlayer_py as g  # noqa: E402

from brightline.publish import report_to_attestation  # noqa: E402
from brightline.state import latest  # noqa: E402
from deploy_studio_next import (  # noqa: E402  (path set above, as in build_static.py)
    EXPLORER, NETWORK, RPC, assert_chain_id, chain, fund_if_needed,
)

OUT = ROOT / "experiments" / "E9_studio_next"
REPORT = ROOT / "reports" / "v1_ps_6ce467da9d20c1f2_studionet.json"
UNTESTED_RULE = "0x" + "ee" * 32
AMOUNT = 10**16          # 0.01 GEN, the same stake the dApp offers

log: dict = {"network": NETWORK, "chain_id": 61997, "rpc": RPC, "checks": [], "txs": {}}
passed = failed = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"\n        {detail}" if detail and not ok else ""))
    log["checks"].append({"name": name, "ok": bool(ok), "detail": detail})
    if ok:
        passed += 1
    else:
        failed += 1
    return ok


def leader_result(rec: dict) -> tuple[str, str]:
    """(status, payload) from the leader receipt. A revert lands as a receipt, not a
    raised exception, so the refusal paths have to be read out of consensus data."""
    leader = (rec.get("consensus_data") or {}).get("leader_receipt") or []
    res = (leader[0] if leader else {}).get("result") or {}
    return str(res.get("status", "")), str(res.get("payload", ""))


def send(c, acct, address: str, fn: str, args: list, value: int = 0) -> dict:
    fees = c.estimate_transaction_fees()
    tx = c.write_contract(address=address, function_name=fn, account=acct, args=args,
                          value=value, fees=fees)
    h = tx.hex() if isinstance(tx, (bytes, bytearray)) else str(tx)
    rec = c.wait_for_transaction_receipt(transaction_hash=h, wait_until="decided",
                                         interval=3000, retries=80)
    rec["_hash"] = h
    log["txs"].setdefault(fn, []).append(h)
    return rec


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    key = json.loads((ROOT / ".brightline" / "accounts.json").read_text())["default"]
    acct = g.create_account(key)
    c = g.create_client(chain=chain(), account=acct)
    print(f"network   {NETWORK}  chain {assert_chain_id(c)}  {RPC}")
    fund_if_needed(c, acct, floor=2 * 10**18)

    addr = {n: (latest(NETWORK, None, name=n) or {}).get("address") for n in
            ("probe", "registry", "escrow")}
    log["addresses"] = addr
    print(f"probe     {addr['probe']}\nregistry  {addr['registry']}\nescrow    {addr['escrow']}")
    if not all(addr.values()):
        raise SystemExit("run scripts/deploy_studio_next.py first")

    report = json.loads(REPORT.read_text())
    att = report_to_attestation(report)
    att["evidence_uri"] = "reports/v1_ps_6ce467da9d20c1f2_studionet.json"
    rule_hash = att["rule_hash"]
    worst = int(att["counterexamples"])
    log["rule_hash"], log["worst"] = rule_hash, worst
    print(f"\nrule      {rule_hash}\nworst K   {worst} of {att['probes']}")

    # ---------------------------------------------------------------- 1. probe writes
    print("\n1 · the probe contract's deterministic path")
    # `normalized` and `canonical` are the exact strings the ids hash over, which is
    # what makes the registration auditable: anyone can recompute both off the
    # committed artifacts. Same values brightline/run.py registers on studionet.
    rule_text = report["rule"]["normalized"]
    rec = send(c, acct, addr["probe"], "register_rule", [rule_hash, rule_text])
    status, payload = leader_result(rec)
    check("register_rule executed", status in ("return", "ok", ""), f"{status} {payload}")
    got = c.read_contract(address=addr["probe"], function_name="get_rule", args=[rule_hash])
    check("the rule reads back byte-identical", str(got) == rule_text,
          f"{str(got)[:80]!r} != {rule_text[:80]!r}")

    manifest = json.loads((ROOT / "probes" / f"{att['probe_set_id']}.json").read_text())
    probe0 = manifest["probes"][0]
    pid = probe0["probe_id"]
    rec = send(c, acct, addr["probe"], "register_probe", [pid, probe0["canonical"]])
    status, payload = leader_result(rec)
    check("register_probe executed", status in ("return", "ok", ""), f"{status} {payload}")
    got_p = c.read_contract(address=addr["probe"], function_name="get_probe", args=[pid])
    check("the probe scenario reads back byte-identical",
          str(got_p) == probe0["canonical"], f"{str(got_p)[:80]!r}")

    # -------------------------------------------------------------- 2. registry write
    print("\n2 · the registry accepts the real v1 attestation")
    rec = send(c, acct, addr["registry"], "publish", [
        att["report_hash"], att["rule_hash"], att["probe_set_id"],
        att["adversary_version"], att["network"], att["counterexamples"],
        att["probes"], att["measurable"], att["noise_floor_milli"],
        att["evidence_uri"], att["tx_hashes_json"]])
    status, payload = leader_result(rec)
    # Re-running this script re-sends the same attestation, and the registry is right to
    # refuse it: `report_hash` is unique by design. That rollback is the append-only
    # property holding, not a failure, so it counts as a pass and says which it was.
    republished = "already published" in payload
    check("publish executed" + (" (already on chain from an earlier run)" if republished else ""),
          status in ("return", "ok", "") or republished, f"{status} {payload}")
    tested = c.read_contract(address=addr["registry"], function_name="is_tested",
                             args=[rule_hash])
    check("registry reports the rule as tested", bool(tested), str(tested))
    on_chain_worst = int(c.read_contract(address=addr["registry"],
                                         function_name="worst_counterexamples",
                                         args=[rule_hash]))
    check(f"worst_counterexamples == {worst}", on_chain_worst == worst,
          f"chain says {on_chain_worst}")

    # ------------------------------------------------------------- 3/4. the refusal
    tight = worst - 1
    print(f"\n3 · the gate refuses a deal that tolerates only {tight}")
    deal_a = f"e9-tight-{int(time.time())}"
    send(c, acct, addr["escrow"], "open_deal",
         [deal_a, acct.address, rule_hash, tight])
    rec = send(c, acct, addr["escrow"], "lock", [deal_a], value=AMOUNT)
    status, payload = leader_result(rec)
    needle = f"rule has {worst} counterexamples, deal tolerates {tight}"
    check("lock was refused on chain", status not in ("return", "ok"), f"status={status}")
    check(f"refusal names both numbers: {needle!r}", needle in payload, payload[:220])
    state_a = json.loads(c.read_contract(address=addr["escrow"],
                                         function_name="get_deal", args=[deal_a]))
    check("the refused deal is still OPEN", state_a["state"] == "OPEN", str(state_a["state"]))
    check(f"its tolerance is still {tight}",
          int(state_a["max_counterexamples"]) == tight, str(state_a))

    # ------------------------------------------------------------------ 5. the lock
    print(f"\n4 · a new deal at tolerance {worst} locks")
    deal_b = f"e9-ok-{int(time.time())}"
    send(c, acct, addr["escrow"], "open_deal", [deal_b, acct.address, rule_hash, worst])
    rec = send(c, acct, addr["escrow"], "lock", [deal_b], value=AMOUNT)
    status, payload = leader_result(rec)
    check("lock executed", status in ("return", "ok", ""), f"{status} {payload}")
    locked = json.loads(c.read_contract(address=addr["escrow"],
                                        function_name="get_deal", args=[deal_b]))
    check("deal state is LOCKED", locked["state"] == "LOCKED", str(locked["state"]))
    check(f"counterexamples_at_lock == {worst}",
          int(locked["counterexamples_at_lock"]) == worst, str(locked))
    check("the locked amount is 0.01 GEN", int(locked["amount"]) == AMOUNT, str(locked["amount"]))
    still = json.loads(c.read_contract(address=addr["escrow"],
                                       function_name="get_deal", args=[deal_a]))
    check("the earlier refused deal is untouched and still OPEN",
          still["state"] == "OPEN", str(still["state"]))

    # -------------------------------------------------------- 6. the untested refusal
    print("\n5 · the gate refuses an untested rule")
    deal_c = f"e9-untested-{int(time.time())}"
    send(c, acct, addr["escrow"], "open_deal",
         [deal_c, acct.address, UNTESTED_RULE, 99])
    rec = send(c, acct, addr["escrow"], "lock", [deal_c], value=AMOUNT)
    status, payload = leader_result(rec)
    check("lock was refused for the untested rule", status not in ("return", "ok"),
          f"status={status}")
    check("refusal tells the payer to publish first",
          "no published brightline report" in payload.lower(), payload[:220])

    # ------------------------------------------------------- 6. the nondet adjudication
    # The consensus-critical path, and the only one that touches an LLM: one nondet
    # block, a leader decision, and a validator function that re-derives the answer and
    # compares the decision field alone. GenVM 0.3 renamed the primitive
    # (run_nondet_unsafe -> run_nondet); this is where that rename is proved harmless.
    print("\n6 · a real adjudication through the network's own committee")
    t0 = time.time()
    rec = send(c, acct, addr["probe"], "adjudicate", [rule_hash, pid])
    status, payload = leader_result(rec)
    elapsed = round(time.time() - t0, 1)
    exec_name = str(rec.get("txExecutionResultName")
                    or rec.get("tx_execution_result_name") or "")
    print(f"        {status or exec_name} in {elapsed}s")
    check("adjudicate reached a terminal consensus status",
          status in ("return", "ok", "") or exec_name.upper() in ("SUCCESS", "FINISHEDWITHRETURN"),
          f"{status} {exec_name} {payload[:160]}")
    raw = c.read_contract(address=addr["probe"], function_name="get_ruling",
                          args=[rule_hash, pid])
    ruling = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
    log["ruling"] = ruling
    print(f"        ruling {ruling}")
    check("the ruling stored a decision in the vocabulary",
          ruling.get("decision") in ("ACCEPT", "REJECT", "PARTIAL", "INSUFFICIENT"),
          str(ruling))
    log["adjudicate_seconds"] = elapsed

    log["passed"], log["failed"] = passed, failed
    log["explorer"] = {k: f"{EXPLORER}/address/{v}" for k, v in addr.items()}
    log["finished"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "verification.json").write_text(json.dumps(log, indent=2))
    print(f"\n{passed}/{passed + failed} live Studio Next checks passed")
    print(f"wrote {(OUT / 'verification.json').relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
