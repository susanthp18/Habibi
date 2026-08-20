"""One sentence a human can act on, generated deterministically.

Every decision — including every silence — carries a line written here. It goes
on the work queue, into the decision log, and in front of whoever has to defend
the contact later.

Deterministic on purpose. The LLM re-ranker may replace this sentence when it
is switched on and its output survives the invention check, but the default
path must produce something correct without a network call, because the
sentence is also the audit artefact: "we did not ring this borrower on the 4th
because they were on a hardship hold" has to be true whether or not a model was
reachable that day.
"""

from __future__ import annotations

from datetime import datetime

from agent_core.treatment import actions as A
from agent_core.treatment.features import AccountFeatures, Trigger, zone
from agent_core.treatment.policy import CONTACT_PREFIX, HOLD_PREFIX
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


def _inr(amount: float) -> str:
    return f"{amount:,.0f}"


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
    stake = f"₹{_inr(features.exposure)} at stake" if features.exposure > 0 else "no balance due"
    dpd = f"{features.dpd} DPD" if features.dpd else features.bucket
    return f"{phrase}, {dpd}, {stake}"


def humanise(reason: str | None) -> str:
    """Turn a stable reason code into something a supervisor reads."""
    if not reason:
        return "no reason recorded"
    if reason.startswith(HOLD_PREFIX):
        return f"{reason[len(HOLD_PREFIX):]} hold is active"
    if reason.startswith(CONTACT_PREFIX):
        code = reason[len(CONTACT_PREFIX) :]
        return _CONTACT_PHRASE.get(code, code.replace("_", " "))
    return _SUPPRESSION_PHRASE.get(reason, reason.replace("_", " "))


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
        f"₹{chosen.cost:,.2f} to try — net ₹{_inr(chosen.expected_value)}"
    )
    if chosen.timing_rationale and chosen.timing_rationale not in {
        "no contact planned",
        "next feasible moment",
    }:
        return f"{lead}: {detail}. Timed for {chosen.timing_rationale}."
    return f"{lead}: {detail}."
