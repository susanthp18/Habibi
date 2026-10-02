"""One sentence a human can act on, generated deterministically.

Every decision — including every silence — carries a line written here. It goes
on the work queue, into the decision log, and in front of whoever has to defend
the contact later.

Deterministic on purpose. An LLM may offer a plainer explanation beside it,
but never replaces it: the sentence is the audit artefact, and it has to be
correct without a network call: "we did not ring this borrower on the 4th
because they were on a hardship hold" has to be true whether or not a model was
reachable that day.
"""

from __future__ import annotations

from datetime import datetime

import money_inr
from agent_core.treatment import actions as A
from agent_core.treatment.features import AccountFeatures, Trigger, zone
from agent_core.treatment.policy import CONTACT_PREFIX, HOLD_PREFIX, SPEECH_PREFIX
from agent_core.treatment.scoring import ScoredAction

_TRIGGER_PHRASE = {
    "bounce": "EMI bounced",
    "broken_ptp": "promise broken",
    "pre_due": "instalment due shortly",
    "dpd_tick": "account ageing",
    "inbound": "borrower got in touch",
    "manual": "reviewed",
    "no_contact": "no contact in a while",
    "wrap_up": "call just ended",
}

_SUPPRESSION_PHRASE = {
    "no_eligible_action": "nothing is permitted right now",
    "below_value_floor": "every available attempt costs more than it is worth",
    "budget_reserved": "holding today's last contact slot for something better",
    "already_planned": "an identical action is already scheduled",
    "attempts_exhausted": "the ladder is exhausted — this needs a person's judgment",
    "retry_backoff": "the last attempt was too recent to try again",
    "all_actions_held": "this borrower is on hold",
    "all_channels_capped": "every channel is capped or closed",
    "shadow_mode": "shadow mode — decided, not enacted",
    "engine_off": "the treatment engine is switched off",
    "engine_error": "the engine could not complete a decision",
}

_CONTACT_PHRASE = {
    "outside_calling_hours": "outside RBI calling hours",
    "outside_allowed_window": "outside the consented contact window",
    "contact_windows_conflict": "never contactable: the consent and preferred windows do not overlap",
    "daily_cap": "at the daily contact cap",
    "weekly_cap": "at the weekly contact cap",
    "cooling_off": "inside the cooling-off window",
    "customer_dnd": "on DND",
    "channel_dnd": "channel is on DND",
    "channel_opted_out": "opted out of this channel",
    "channel_expired": "channel consent has expired",
    "no_customer": "no borrower record",
    "consent_unreadable": "consent could not be read",
}

#: Why an individual action was blocked before scoring. Stable codes from
#: ``policy`` and ``bank_boundary.freshness``, in words a supervisor can act on.
_VETO_PHRASE = {
    "bucket_disallows_action": "not allowed for this DPD bucket by policy",
    "account_not_delinquent": "the account is not overdue",
    "account_closed": "the account is closed",
    "no_phone_on_file": "no phone number on file",
    "no_channel_address": "no address on file for this channel",
    "digital_not_exhausted": "cheaper channels have not been tried enough yet",
    "field_not_proportionate": "a visit is not proportionate to the amount owed",
    "field_already_dispatched": "a field visit is already under way",
    "field_prerequisites_unmet": "a visit's prerequisites are not met",
    "legal_prerequisites_unmet": "a legal notice's prerequisites are not met",
    "legal_notice_already_served": "a legal notice was already served",
    "ladder_advance_too_far": "too big a step up the escalation ladder at once",
    "third_party_contact": "would contact a third party",
    "stale_snapshot": "today's account data has not been built yet",
    "nothing_owed": "nothing is owed",
    "no_mandate_on_file": "no auto-debit mandate on file",
    "mandate_not_active": "the auto-debit mandate is not active",
    "no_unpaid_cycle_to_present": "no unpaid instalment to present",
    "mandate_return_blocks_retry": "the last debit return rules out a retry",
    "mandate_presentation_limit": "the debit has been presented the maximum times",
    "mandate_retry_too_soon": "too soon to present the debit again",
    "emi_date_already_aligned": "the EMI date already follows the salary credit",
    "salary_timing_unknown": "salary timing is unknown",
    "technical_return_not_borrower_fault": "the last return was a bank-side technical failure",
    "self_service_plan_already_open": "a self-service plan is already open",
    "no_digital_surface_to_offer_on": "no app or portal to offer a plan on",
    "arrears_not_yet_worth_a_plan": "the arrears are too small for a plan",
    "ratio_ceiling": "the contact ratio for this borrower is at its ceiling",
    "control_arm": "held back: this borrower is in the comparison group",
    "freshness:resolver_unavailable": "bank data freshness could not be checked",
    "freshness:wait_only": "bank data feeds are stale, so only waiting is allowed",
    "freshness:non_contacting": "bank data feeds are stale, so no contact is allowed",
    "freshness:mandate_stale": "the bank's mandate feed is stale",
    "freshness:endpoint_stale": "the bank's contact-details feed is stale",
    "freshness:c8_feed_stale": "the bank's consent feed is stale or missing",
    "freshness:field_stale": "the bank's field-capacity feed is stale",
    "freshness:c10_absent": "no microfinance protection feed from the bank",
    "freshness:c7_reserved_cap": "the field capacity reserved by the bank is used up",
}

#: Speech-derived suppressions, in the borrower's favour by construction — each
#: one is a reason we did *not* act. The sentence says what they told us and
#: never quotes them: the decision log is retained for the regulator, and a
#: transcript line in it is a second copy of the customer record.
_SPEECH_PHRASE = {
    "consent_withdrawal": "the borrower asked us to stop contacting them",
    "dispute_claimed": "the borrower disputes this on a call",
    "hardship_claimed": "the borrower reported hardship on a call",
    "legal_threat": "the borrower raised a legal matter on a call",
}


def _inr(amount: float) -> str:
    """Whole rupees, symbol included.

    It used to return bare digits with Western grouping and leave the ₹ to each
    caller, which is how line 122 below ended up printing two different money
    formats inside one sentence — and that sentence is the decision log's
    explanation of why an action was taken.
    """
    return money_inr.inr(amount)


def _when(at: datetime | None, features: AccountFeatures, now: datetime) -> str:
    if at is None:
        return "at no scheduled time"
    delta = (at - now).total_seconds()
    if delta <= 90:
        return "now"
    local = at.astimezone(zone(features.timezone_name))
    if delta < 12 * 3600:
        return f"at {local:%H:%M}"
    return f"on {local:%d %b} at {local:%H:%M}"


def _context(features: AccountFeatures, trigger: Trigger, now: datetime) -> str:
    phrase = _TRIGGER_PHRASE.get(trigger.kind, trigger.kind.replace("_", " "))
    age = trigger.age_hours(now)
    if age is not None and age >= 1:
        phrase = f"{phrase} {int(age)}h ago" if age < 48 else f"{phrase} {int(age / 24)}d ago"
    stake = f"{_inr(features.exposure)} at stake" if features.exposure > 0 else "no balance due"
    dpd = f"{features.dpd} DPD" if features.dpd else features.bucket
    return f"{phrase}, {dpd}, {stake}"


def humanise(reason: str | None) -> str:
    """Turn a stable reason code into something a supervisor reads."""
    if not reason:
        return "no reason recorded"
    if reason.startswith(HOLD_PREFIX):
        return f"{reason[len(HOLD_PREFIX):]} hold is active"
    if reason.startswith(SPEECH_PREFIX):
        code = reason[len(SPEECH_PREFIX) :]
        return _SPEECH_PHRASE.get(code, f"{code.replace('_', ' ')} on a call")
    if reason.startswith(CONTACT_PREFIX):
        code = reason[len(CONTACT_PREFIX) :]
        return _CONTACT_PHRASE.get(code, code.replace("_", " "))
    if reason in _VETO_PHRASE:
        return _VETO_PHRASE[reason]
    if reason.startswith("policy:"):
        return f"blocked by policy rule {reason[len('policy:'):]}"
    return _SUPPRESSION_PHRASE.get(reason, reason.replace("_", " ").replace(":", ": "))


def rationale(
    *,
    features: AccountFeatures,
    trigger: Trigger,
    chosen: ScoredAction | None,
    suppressed: bool,
    reason: str | None,
    now: datetime,
) -> str:
    """The line that goes on the queue and in the audit log."""
    context = _context(features, trigger, now)

    if suppressed or chosen is None or chosen.action == A.WAIT:
        return f"{context}. Holding — {humanise(reason)}."

    when = _when(chosen.at, features, now)
    lead = f"{context}. {A.label(chosen.action).capitalize()} {when}"
    detail = (
        f"{chosen.p_reach:.0%} chance of reaching them, "
        f"{chosen.p_resolve:.0%} of curing if reached, "
        f"{money_inr.inr_compact(chosen.cost)} to try — net {_inr(chosen.expected_value)}"
    )
    if chosen.timing_rationale and chosen.timing_rationale not in {
        "no contact planned",
        "next feasible moment",
    }:
        return f"{lead}: {detail}. Timed for {chosen.timing_rationale}."
    return f"{lead}: {detail}."
