# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""GatedEscrow -- an escrow that refuses to lock funds against an untested rule.

Deterministic. Reads BrightlineRegistry synchronously via `view()`; the registry is
the only external dependency and it holds no LLM logic either.

What the gate checks, and why it is not a score:

The E6 calibration study failed its matched-pair criterion, so Split Score is not
validated for ranking two drafts of the same clause. Gating on a score threshold
would therefore be gating on a number the evidence does not support. The gate checks
two things that survive every branch of the pre-registration:

  1. the rule has been tested at all -- some report exists, naming a probe set and
     an adversary version, with adjudication transactions behind it; and
  2. the worst published counterexample count is at or below the tolerance the payer
     chose *before* opening the deal.

Counterexamples are a raw finding -- "adversary v1 found K of N" -- not a calibrated
quantity. The payer picks the tolerance; the contract only enforces the choice and
records what was known at lock time so neither side can later claim surprise.

Honest scope: this is an interface demonstration. Both sides of the handshake were
written here, and it is not evidence that an external escrow provider would adopt it.
"""

from genlayer import *

import json
import typing
from dataclasses import dataclass

ERROR_EXPECTED = "[EXPECTED]"

STATE_OPEN = "OPEN"
STATE_LOCKED = "LOCKED"
STATE_RELEASED = "RELEASED"
STATE_REFUNDED = "REFUNDED"


@gl.contract_interface
class Registry:
    class View:
        def is_tested(self, rule_hash: str) -> bool: ...
        def worst_counterexamples(self, rule_hash: str) -> u32: ...
        def summary_for_rule(self, rule_hash: str) -> str: ...

    class Write:
        pass


@allow_storage
@dataclass
class Deal:
    payer: Address
    payee: Address
    rule_hash: str
    max_counterexamples: u32
    amount: u256
    state: str
    # What the registry said at the moment funds locked. Frozen on purpose: a later
    # report cannot rewrite what the parties relied on.
    locked_counterexamples: u32
    locked_summary: str
    ts_opened: str
    ts_locked: str


class GatedEscrow(gl.Contract):
    owner: Address
    registry: Address
    deals: TreeMap[str, Deal]
    deal_ids: DynArray[str]

    def __init__(self, registry: Address) -> None:
        self.owner = gl.message.sender_address
        self.registry = registry

    # ------------------------------------------------------------------------ deals
    @gl.public.write
    def open_deal(self, deal_id: str, payee: str, rule_hash: str,
                  max_counterexamples: int) -> None:
        if len(deal_id) == 0 or len(deal_id) > 128:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} deal_id length out of range")
        if deal_id in self.deals:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} deal_id already exists")
        if max_counterexamples < 0:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} max_counterexamples must be >= 0")
        self.deals[deal_id] = Deal(
            payer=gl.message.sender_address, payee=Address(payee),
            rule_hash=rule_hash, max_counterexamples=u32(max_counterexamples),
            amount=u256(0), state=STATE_OPEN,
            locked_counterexamples=u32(0), locked_summary="",
            ts_opened=gl.message_raw["datetime"], ts_locked="",
        )
        self.deal_ids.append(deal_id)

    @gl.public.write.payable
    def lock(self, deal_id: str) -> str:
        """Escrow the sent value, but only if the rule has been tested and passes the
        payer's own tolerance. This is the whole point of the contract."""
        if deal_id not in self.deals:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} unknown deal_id")
        deal = self.deals[deal_id]
        if deal.state != STATE_OPEN:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} deal is not open")
        if gl.message.sender_address != deal.payer:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only the payer may lock")
        value = gl.message.value
        if value == 0:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} nothing sent to escrow")

        registry = Registry(self.registry)
        if not registry.view().is_tested(deal.rule_hash):
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} rule has no published Brightline report; "
                f"run the probes and publish before locking funds")
        found = int(registry.view().worst_counterexamples(deal.rule_hash))
        allowed = int(deal.max_counterexamples)
        if found > allowed:
            raise gl.vm.UserError(
                f"{ERROR_EXPECTED} rule has {found} counterexamples, deal tolerates "
                f"{allowed}; tighten the rule or raise the tolerance deliberately")

        deal.amount = u256(int(value))
        deal.state = STATE_LOCKED
        deal.locked_counterexamples = u32(found)
        deal.locked_summary = registry.view().summary_for_rule(deal.rule_hash)
        deal.ts_locked = gl.message_raw["datetime"]
        self.deals[deal_id] = deal
        return json.dumps({"deal_id": deal_id, "state": STATE_LOCKED,
                           "amount": int(value), "counterexamples_at_lock": found,
                           "tolerated": allowed}, sort_keys=True)

    @gl.public.write
    def release(self, deal_id: str) -> None:
        deal = self._locked(deal_id)
        if gl.message.sender_address != deal.payer:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only the payer may release")
        deal.state = STATE_RELEASED
        self.deals[deal_id] = deal
        gl.advanced.emit_raw_transfer(deal.payee, u256(int(deal.amount)))

    @gl.public.write
    def refund(self, deal_id: str) -> None:
        deal = self._locked(deal_id)
        if gl.message.sender_address != deal.payee:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} only the payee may refund")
        deal.state = STATE_REFUNDED
        self.deals[deal_id] = deal
        gl.advanced.emit_raw_transfer(deal.payer, u256(int(deal.amount)))

    def _locked(self, deal_id: str) -> Deal:
        if deal_id not in self.deals:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} unknown deal_id")
        deal = self.deals[deal_id]
        if deal.state != STATE_LOCKED:
            raise gl.vm.UserError(f"{ERROR_EXPECTED} deal is not locked")
        return deal

    # ------------------------------------------------------------------------ reads
    @gl.public.view
    def get_deal(self, deal_id: str) -> str:
        if deal_id not in self.deals:
            return "{}"
        d = self.deals[deal_id]
        return json.dumps({
            "deal_id": deal_id, "payer": d.payer.as_hex, "payee": d.payee.as_hex,
            "rule_hash": d.rule_hash, "state": d.state, "amount": int(d.amount),
            "max_counterexamples": int(d.max_counterexamples),
            "counterexamples_at_lock": int(d.locked_counterexamples),
            "summary_at_lock": d.locked_summary,
            "ts_opened": d.ts_opened, "ts_locked": d.ts_locked,
        }, sort_keys=True)

    @gl.public.view
    def deal_count(self) -> u256:
        return u256(len(self.deal_ids))

    @gl.public.view
    def registry_address(self) -> str:
        return self.registry.as_hex
