"""Policy gates applied after scoring.

Scoring answers "which is best?". Arbitration answers "should we say anything
at all?" — and it is allowed to answer no to a perfectly good offer. Keeping
the two apart is the point: the moment a compliance rule becomes a score
penalty, someone can tune it away while chasing conversion.

Every suppression returns a stable reason string. It is logged, counted and
alerted on, so "the engine went quiet" is always attributable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import text

from agent_core.reco.config import Policy
from agent_core.reco.features import CallSignals, CustomerFeatures
from agent_core.reco.scoring import ScoredOffer

logger = logging.getLogger(__name__)

SUPPRESS_DND = "dnd"
SUPPRESS_CONSENT = "channel_consent_closed"
SUPPRESS_NO_COMMITMENT = "no_commitment_yet"
SUPPRESS_SENTIMENT = "sentiment_below_floor"
SUPPRESS_ESCALATED = "escalated"
SUPPRESS_DISPUTE = "dispute_open_this_call"
SUPPRESS_HARDSHIP = "hardship_stated"
SUPPRESS_ALREADY_DECLINED = "declined_this_call"
SUPPRESS_CALL_CAP = "per_call_cap_reached"
SUPPRESS_CUSTOMER_CAP = "per_customer_cap_reached"
SUPPRESS_NO_CANDIDATES = "no_eligible_candidates"
SUPPRESS_BELOW_THRESHOLD = "below_score_threshold"

_CONSENT_BLOCKING = frozenset({"opted_out", "dnd", "expired"})


@dataclass(frozen=True)
class Arbitration:
    offers: list[ScoredOffer]
    suppressed: bool
    reason: str | None


def arbitrate(
    *,
    features: CustomerFeatures,
    signals: CallSignals,
    offers: Sequence[ScoredOffer],
    policy: Policy,
    channel: str,
) -> Arbitration:
    """Apply every gate in order of severity. First match wins and stops."""

    # --- absolute contact rules -------------------------------------------
    if features.dnd:
        return _no(SUPPRESS_DND)

    consent = features.consent_by_channel.get(channel)
    if consent in _CONSENT_BLOCKING:
        return _no(SUPPRESS_CONSENT)

    # --- conversation state ------------------------------------------------
    # Pitching to someone who is being escalated, disputing a charge, or has
    # just described losing their job is the fastest way to turn a complaint
    # into a regulatory one.
    if signals.escalation_flagged:
        return _no(SUPPRESS_ESCALATED)
    if signals.dispute_opened:
        return _no(SUPPRESS_DISPUTE)
    if signals.hardship_mentioned:
        return _no(SUPPRESS_HARDSHIP)
    if signals.offer_declined_this_call:
        return _no(SUPPRESS_ALREADY_DECLINED)

    if signals.sentiment_current < policy.sentiment_floor:
        return _no(SUPPRESS_SENTIMENT)

    # The ordering rule the voice graph used to enforce structurally: nothing
    # is offered until the caller has committed to something.
    if policy.require_commitment and not (
        signals.commitment_secured or signals.ptp_captured
    ):
        return _no(SUPPRESS_NO_COMMITMENT)

    # --- frequency ---------------------------------------------------------
    if signals.offers_presented_this_call >= policy.max_offers_per_call:
        return _no(SUPPRESS_CALL_CAP)
    if features.offers_last_30d >= policy.max_offers_per_customer_30d:
        return _no(SUPPRESS_CUSTOMER_CAP)

    # --- the offers themselves --------------------------------------------
    if not offers:
        return _no(SUPPRESS_NO_CANDIDATES)

    keep = [o for o in offers if o.score >= policy.min_score]
    if not keep:
        return _no(SUPPRESS_BELOW_THRESHOLD)

    return Arbitration(
        offers=list(keep[: max(1, policy.max_offers_returned)]),
        suppressed=False,
        reason=None,
    )


def _no(reason: str) -> Arbitration:
    return Arbitration(offers=[], suppressed=True, reason=reason)


def reserve_campaign_quota(conn: Any, campaign_id: str | None) -> bool:
    """Consume one unit of campaign quota, atomically.

    Returns False when the campaign just ran out — the conditional UPDATE is
    the check, so two concurrent calls cannot both take the last slot. Called
    at presentation time, not at scoring time: scoring happens for shadow rows
    too, and a shadow run must never burn real budget.
    """
    if not campaign_id:
        return True
    row = conn.execute(
        text(
            """
            UPDATE product_campaigns
            SET quota_used = quota_used + 1
            WHERE id = :id
              AND enabled IS TRUE
              AND (quota_total IS NULL OR quota_used < quota_total)
            RETURNING id
            """
        ),
        {"id": campaign_id},
    ).fetchone()
    return row is not None
