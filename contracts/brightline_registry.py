# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""BrightlineRegistry -- attestations binding a report hash to its evidence.

Deterministic. No LLM, no web. The consensus-critical judgments already happened in
BrightlineProbe transactions; this contract only records that a given rule was tested
with a given probe set, what was found, and which transactions prove it.

What it deliberately does not store: a Split Score. The E6 calibration study failed
its matched-pair criterion, so the score is not validated for ranking two drafts of
the same clause and must not become a number other contracts gate on. What is
recorded is the raw finding -- counterexamples found out of probes attempted -- which
survives every branch of the pre-registration.
"""

from genlayer import *

import json
import typing
from dataclasses import dataclass

ERROR_EXPECTED = "[EXPECTED]"

MAX_ID_CHARS = 128
MAX_URI_CHARS = 512
MAX_TX_LIST_CHARS = 4096


@allow_storage
@dataclass
class Report:
    rule_hash: str
    probe_set_id: str
    adversary_version: str
    network: str
    counterexamples: u32          # K: probes where the panel did not converge
    probes: u32                   # N: probes attempted
    measurable: u32               # probes that yielded any usable observation
    noise_floor_milli: u32        # measured floor x1000, so 0.0 stays exact
    evidence_uri: str
    tx_hashes_json: str           # the adjudication transactions, verbatim
    publisher: Address
    ts: str


class BrightlineRegistry(gl.Contract):
    reports: TreeMap[str, Report]        # report_hash -> Report
    report_hashes: DynArray[str]         # every report, in publication order
    # Per-rule index kept flat rather than as TreeMap[str, DynArray[str]]: allocating
    # a nested storage generic requires gl.storage.inmem_allocate, and a flat
    # count + "rule#i" key pair avoids that machinery entirely.
    rule_report_count: TreeMap[str, u32]
    rule_report_at: TreeMap[str, str]    # f"{rule_hash}#{i}" -> report_hash

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------ publication
    # Permissionless: anyone may publish a report about any rule, including a
    # counterparty who re-ran the probes with their own adversary. Competing reports
    # about the same rule coexist rather than overwrite, which is the point -- a
    # single authoritative score would be exactly the thing E6 says we cannot claim.
    @gl.public.write
    def publish(self, report_hash: str, rule_hash: str, probe_set_id: str,
                adversary_version: str, network: str, counterexamples: int,
                probes: int, measurable: int, noise_floor_milli: int,
                evidence_uri: str, tx_hashes_json: str) -> None:
        for name, value, cap in (("report_hash", report_hash, MAX_ID_CHARS),
                                 ("rule_hash", rule_hash, MAX_ID_CHARS),
                                 ("probe_set_id", probe_set_id, MAX_ID_CHARS),
                                 ("adversary_version", adversary_version, MAX_ID_CHARS),
                                 ("network", network, MAX_ID_CHARS),
                                 ("evidence_uri", evidence_uri, MAX_URI_CHARS),
                                 ("tx_hashes_json", tx_hashes_json, MAX_TX_LIST_CHARS)):
            if len(value) == 0 or len(value) > cap:
                raise gl.vm.UserError(f"{ERROR_EXPECTED} {name} length out of range")

        if probes <= 0 or counterexamples < 0 or counterexamples > probes:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} counterexamples must be within 0..probes")
        if measurable < 0 or measurable > probes:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} measurable must be within 0..probes")
        if noise_floor_milli < 0 or noise_floor_milli > 1000:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} noise_floor_milli must be 0..1000")
        if report_hash in self.reports:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} report_hash already published")

        self.reports[report_hash] = Report(
            rule_hash=rule_hash, probe_set_id=probe_set_id,
            adversary_version=adversary_version, network=network,
            counterexamples=u32(counterexamples), probes=u32(probes),
            measurable=u32(measurable), noise_floor_milli=u32(noise_floor_milli),
            evidence_uri=evidence_uri, tx_hashes_json=tx_hashes_json,
            publisher=gl.message.sender_address,
            ts=gl.message_raw["datetime"],
        )
        self.report_hashes.append(report_hash)
        n = int(self.rule_report_count.get(rule_hash, u32(0)))
        self.rule_report_at[f"{rule_hash}#{n}"] = report_hash
        self.rule_report_count[rule_hash] = u32(n + 1)

    # ------------------------------------------------------------------------ reads
    @gl.public.view
    def get_report(self, report_hash: str) -> str:
        if report_hash not in self.reports:
            return "{}"
        r = self.reports[report_hash]
        return json.dumps({
            "report_hash": report_hash, "rule_hash": r.rule_hash,
            "probe_set_id": r.probe_set_id, "adversary_version": r.adversary_version,
            "network": r.network, "counterexamples": int(r.counterexamples),
            "probes": int(r.probes), "measurable": int(r.measurable),
            "noise_floor_milli": int(r.noise_floor_milli),
            "evidence_uri": r.evidence_uri, "tx_hashes_json": r.tx_hashes_json,
            "publisher": r.publisher.as_hex, "ts": r.ts,
        }, sort_keys=True)

    @gl.public.view
    def report_count_for_rule(self, rule_hash: str) -> u256:
        return u256(int(self.rule_report_count.get(rule_hash, u32(0))))

    @gl.public.view
    def is_tested(self, rule_hash: str) -> bool:
        """Has anyone published a report about this rule at all."""
        return int(self.rule_report_count.get(rule_hash, u32(0))) > 0

    @gl.public.view
    def worst_counterexamples(self, rule_hash: str) -> u32:
        """The highest counterexample count any published report found.

        Deliberately the worst rather than the latest or the best: a rule with two
        reports is as bad as its most successful attacker made it look, and taking
        the maximum removes the incentive to publish until a flattering run appears.
        """
        total = int(self.rule_report_count.get(rule_hash, u32(0)))
        worst = 0
        for i in range(total):
            h = self.rule_report_at[f"{rule_hash}#{i}"]
            k = int(self.reports[h].counterexamples)
            if k > worst:
                worst = k
        return u32(worst)

    @gl.public.view
    def summary_for_rule(self, rule_hash: str) -> str:
        total = int(self.rule_report_count.get(rule_hash, u32(0)))
        if total == 0:
            return json.dumps({"rule_hash": rule_hash, "tested": False,
                               "reports": 0}, sort_keys=True)
        rows = []
        for i in range(total):
            h = self.rule_report_at[f"{rule_hash}#{i}"]
            r = self.reports[h]
            rows.append({"report_hash": h, "k": int(r.counterexamples),
                         "n": int(r.probes), "probe_set_id": r.probe_set_id,
                         "adversary_version": r.adversary_version,
                         "network": r.network, "ts": r.ts})
        return json.dumps({"rule_hash": rule_hash, "tested": True,
                           "reports": len(rows), "rows": rows}, sort_keys=True)
