"""The vetoes. Nothing here is negotiable by a score.

Every gate returns a stable reason string that is logged, counted and alerted
on, so "the engine went quiet" is always attributable — and so a compliance
reviewer can read this file without reading the scorer.

The split that matters: **scoring answers which, arbitration answers whether,
and this file answers may we at all.** A rule that lives here cannot be tuned
away while chasing recovery, which is exactly what happens the moment a
calling-hour restriction becomes a score penalty.

Channel-level vetoes are delegated to :mod:`contact_policy`, not reimplemented.
RBI 08:00–19:00, DND, channel opt-out, the daily and weekly caps and the
cooling-off window already have one definition that the dialler, the WhatsApp
drain, the PTP confirm and the document desk all share. A second copy here that
agreed with it on Tuesday is a second copy that disagrees with it in November.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from agent_core.treatment import actions as A
from agent_core.treatment.config import Policy
from agent_core.treatment.features import AccountFeatures, Trigger

logger = logging.getLogger(__name__)

# --- reasons ---------------------------------------------------------------
HOLD_PREFIX = "hold:"
CONTACT_PREFIX = "contact:"
BUCKET_DISALLOWS = "bucket_disallows_action"
ACCOUNT_NOT_DELINQUENT = "account_not_delinquent"
ACCOUNT_CLOSED = "account_closed"
NO_PHONE = "no_phone_on_file"
NO_CHANNEL_ADDRESS = "no_channel_address"
DIGITAL_NOT_EXHAUSTED = "digital_not_exhausted"
FIELD_NOT_PROPORTIONATE = "field_not_proportionate"
FIELD_ALREADY_DISPATCHED = "field_already_dispatched"
LEGAL_PREREQUISITES = "legal_prerequisites_unmet"
LEGAL_ALREADY_SERVED = "legal_notice_already_served"
LADDER_TOO_FAR = "ladder_advance_too_far"
THIRD_PARTY = "third_party_contact"
NO_EXPOSURE = "nothing_owed"

# The mandate family. Nothing caps a channel=None action, so these are the
# limits — and they are stated separately rather than collapsed into one
# "mandate_unavailable" because "we have no mandate", "the borrower cancelled
# it", "the bank account is closed" and "we have already tried twice this
# cycle" call for four different next actions.
NO_MANDATE = "no_mandate_on_file"
MANDATE_NOT_ACTIVE = "mandate_not_active"
MANDATE_NO_CYCLE = "no_unpaid_cycle_to_present"
MANDATE_RETURN_BLOCKS = "mandate_return_blocks_retry"
MANDATE_LIMIT_REACHED = "mandate_presentation_limit"
MANDATE_TOO_SOON = "mandate_retry_too_soon"
EMI_DATE_ALIGNED = "emi_date_already_aligned"
EMI_TIMING_UNKNOWN = "salary_timing_unknown"
TECHNICAL_RETURN = "technical_return_not_borrower_fault"

#: Holds that stop collections outreach outright. ``legal`` is deliberately not
#: in this set: once a matter is with legal the *statutory* clock is the only
#: thing that may still fire, which :func:`veto` expresses by allowing exactly
#: ``legal_notice`` through.
SILENCING_HOLDS = frozenset({"hardship", "complaint", "bereavement", "dispute"})

#: A dispute hold stops pressure about the disputed amount. It does not stop a
#: human from calling about the dispute itself — that is the specialist's job,
#: and blocking it would leave the borrower with an open dispute nobody rings
#: about.
DISPUTE_PERMITS = frozenset({A.WAIT, A.HUMAN_CALL})

#: Rupee floor below which sending someone to a door is not proportionate.
#: Below this a visit costs more than the instalment it chases, and RBI's
#: proportionality expectations are not a cost calculation the borrower asked
#: for.
FIELD_MIN_EXPOSURE = 5_000.0

#: Days of slack before a salary-versus-due-date gap is worth acting on. One
#: day is noise — a weekend, a bank holiday, a payroll run that slipped.
EMI_TIMING_TOLERANCE_DAYS = 1

#: Minimum gap between two presentations of the same mandate. A NACH debit
#: settles at T+1/T+2, so anything shorter is submitting a second request
#: before the first has returned.
MANDATE_RETRY_BACKOFF = timedelta(hours=48)


def active_holds(features: AccountFeatures) -> tuple[str, ...]:
    return features.holds


def _hold_veto(action: str, features: AccountFeatures) -> str | None:
    for kind in features.holds:
        if kind == "legal":
            # A matter with legal: statutory service only, nothing else.
            if action in {A.WAIT, A.LEGAL_NOTICE}:
                continue
            return f"{HOLD_PREFIX}legal"
        if kind == "dispute":
            if action in DISPUTE_PERMITS:
                continue
            return f"{HOLD_PREFIX}dispute"
        if kind in SILENCING_HOLDS:
            if action == A.WAIT:
                continue
            return f"{HOLD_PREFIX}{kind}"
    return None


def permits_third_party_contact(features: AccountFeatures) -> bool:
    """Whether a non-borrower number may be dialled. Always False today.

    RBI's 2022 circular forbids contacting family, friends or references
    without origination consent, and this schema has no table in which such a
    consent could be recorded — ``customers`` carries only the borrower's own
    ``phone_primary`` / ``phone_alt``. So the honest answer is that no
    third-party number can enter the system at all, and the gate exists to be
    the one place that changes when a references table lands rather than to
    filter a list that is already empty.
    """
    return False


def veto(
    conn: Any,
    *,
    action: str,
    features: AccountFeatures,
    trigger: Trigger,
    at: datetime,
    policy: Policy,
    last_rung: int,
) -> str | None:
    """May we take this action, at this instant? A reason, or None.

    ``at`` is the *planned* instant, not now: an action scheduled for tomorrow
    08:15 is checked against the calling window it will actually land in, which
    is what lets the engine plan rather than only react.
    """
    if action == A.WAIT:
        # Doing nothing is always permitted. If it were vetoable there would be
        # states with no legal action at all, and the engine would have to
        # invent one.
        return None

    spec = A.spec(action)

    held = _hold_veto(action, features)
    if held:
        return held

    if action not in A.bucket_policy(features.bucket).allowed:
        return BUCKET_DISALLOWS

    if features.account_status and features.account_status.lower() in {
        "closed",
        "settled",
        "written_off",
    }:
        return ACCOUNT_CLOSED

    if features.exposure <= 0:
        return NO_EXPOSURE

    # An account with nothing overdue and no live bounce is a pre-due reminder
    # at most. Anything above the digital rungs is dunning someone who is not
    # in arrears.
    delinquent = bool(
        (features.dpd or 0) > 0 or features.open_bounce_id or features.open_promise_id
    )
    if not delinquent and spec.rung > 1:
        return ACCOUNT_NOT_DELINQUENT

    if spec.requires_phone and not features.has_phone:
        return NO_PHONE
    if action == A.LEGAL_NOTICE and not (features.has_email or features.has_phone):
        return NO_CHANNEL_ADDRESS

    if spec.rung > last_rung + policy.max_rung_advance:
        # One rung at a time. Digital straight to a doorstep is how a
        # three-day-old miss ends up with someone at the door, and it is the
        # single most complained-about behaviour on a collections floor.
        return LADDER_TOO_FAR

    if action == A.FIELD_VISIT:
        reason = _field_veto(features, policy)
        if reason:
            return reason

    if action == A.LEGAL_NOTICE:
        reason = _legal_veto(features, at)
        if reason:
            return reason

    if action == A.REPRESENT_MANDATE:
        reason = _mandate_veto(conn, features, at=at)
        if reason:
            return reason

    if action == A.EMI_DATE_CHANGE:
        reason = _emi_date_veto(features)
        if reason:
            return reason

    if spec.channel:
        # A bank-side return is not the borrower's failure, and dunning them
        # for it is the collections equivalent of billing someone for our own
        # outage. Suppressed only while the fix is still in our hands: once
        # re-presentment is exhausted or blocked, the money is genuinely
        # outstanding and contact becomes legitimate again.
        if (features.bounce_reason or "").lower() == "technical" and _mandate_veto(
            conn, features, at=at
        ) is None:
            return TECHNICAL_RETURN

        reason = _contact_veto(
            conn, features=features, channel=spec.channel, at=at
        )
        if reason:
            return reason

    return None


def _mandate_veto(conn: Any, features: AccountFeatures, *, at: datetime) -> str | None:
    """May we present the standing instruction again, for this cycle?

    Nothing else bounds this action — it has no channel, so the frequency cap
    and the calling window both pass it straight through. That exemption is
    correct (a debit the borrower never notices is not a contact) and it is
    exactly why the limits have to be here instead. An action nothing caps is
    an action that will be taken until it stops working.
    """
    if not features.mandate_id:
        return NO_MANDATE
    if (features.mandate_status or "").lower() != "active":
        # Suspended, cancelled, expired or still pending registration. None of
        # them are fixed by presenting; a cancelled mandate needs a
        # re-registration flow and a pending one needs the rail.
        return MANDATE_NOT_ACTIVE
    if features.mandate_cycle is None:
        return MANDATE_NO_CYCLE

    reason = (features.mandate_last_return_reason or "").lower()
    permitted = _mandate_return_permits_retry(conn, features, at=at, return_reason=reason)
    if permitted is False:
        return MANDATE_RETURN_BLOCKS

    limit = _mandate_limit(conn, features, at=at)
    if features.mandate_attempts_this_cycle >= limit:
        return MANDATE_LIMIT_REACHED

    last = features.mandate_last_presented_at
    if last is not None and (at - last) < MANDATE_RETRY_BACKOFF:
        # A presentation takes a day or two to settle. Submitting another
        # before the first has returned debits the borrower twice for one EMI,
        # which is the single worst thing this action can do and the reason a
        # borrower revokes a mandate for good.
        return MANDATE_TOO_SOON

    return None


#: Which return codes may be re-presented at all, absent a published rule.
#:
#: The distinction is diagnostic rather than procedural. Insufficient funds is a
#: *timing* problem and re-presenting against the salary credit is the whole
#: point. A cancelled mandate is a *mandate* problem — no number of retries
#: creates authority the borrower withdrew. A closed account is a *data*
#: problem needing an alternate instrument. A technical return was never the
#: borrower's doing and should be retried immediately.
RETURN_PERMITS_RETRY: dict[str, bool] = {
    "insufficient_funds": True,
    "technical": True,
    "unknown": True,
    "mandate_expired": False,
    "account_closed": False,
    # No return yet: a mandate that has never failed is obviously presentable.
    "": True,
}


def _mandate_return_permits_retry(
    conn: Any, features: AccountFeatures, *, at: datetime, return_reason: str
) -> bool:
    from policy_rules import resolve

    published = resolve(
        conn, tenant_id=features.tenant_id, at=at
    ).mandate_return_permits_retry(return_reason or "unknown")
    if published is not None:
        return published
    return RETURN_PERMITS_RETRY.get(return_reason, True)


def _mandate_limit(conn: Any, features: AccountFeatures, *, at: datetime) -> int:
    """Presentations of one cycle permitted on one mandate.

    The default is a planning figure. The authoritative limit belongs to the
    rail and to the sponsor bank's agreement, which is why it is expressible as
    a policy rule — a number that differs per client must not be a constant in
    a scorer.
    """
    from policy_rules import resolve

    published = resolve(conn, tenant_id=features.tenant_id, at=at).mandate_presentation_limit()
    if published is not None:
        return max(1, published)
    return max(1, _env_int("TREATMENT_MANDATE_MAX_PRESENTATIONS", 3))


def _emi_date_veto(features: AccountFeatures) -> str | None:
    """Moving the due date is a cure only where timing is the actual problem.

    Self-enforcing against repetition, and deliberately so: a successful change
    moves the salary credit ahead of the due date, the gap goes non-positive,
    and this veto starts firing. No "already changed" flag to keep in sync, and
    no way for the engine to reschedule a borrower's life twice.
    """
    gap = features.salary_timing_gap_days
    if gap is None:
        return EMI_TIMING_UNKNOWN
    if gap <= EMI_TIMING_TOLERANCE_DAYS:
        return EMI_DATE_ALIGNED
    return None


def _env_int(name: str, default: int) -> int:
    import os

    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _field_veto(features: AccountFeatures, policy: Policy) -> str | None:
    if features.field_visits_90d > 0:
        return FIELD_ALREADY_DISPATCHED
    if features.digital_attempts_since_connect < policy.field_digital_exhaustion:
        # The roadmap's rule, and the economics behind it: ₹800–1,500 a visit
        # with the borrower absent 40–50% of the time. Digital first is not
        # politeness, it is arithmetic.
        return DIGITAL_NOT_EXHAUSTED
    if features.exposure < FIELD_MIN_EXPOSURE:
        return FIELD_NOT_PROPORTIONATE
    if not features.secured and features.bucket in {A.B_31_60}:
        # Field is for secured lending in the middle buckets. An unsecured
        # personal loan at 45 DPD gets a specialist on the phone, not a van.
        return FIELD_NOT_PROPORTIONATE
    return None


def _legal_veto(features: AccountFeatures, at: datetime) -> str | None:
    if features.legal_notice_at is not None:
        return LEGAL_ALREADY_SERVED
    # NI Act s.138 runs from the bounce and gives the drawer 15 days to pay
    # after service. Serving on day one converts a forgetful borrower into a
    # litigant, so the notice waits for the statutory position to be real: a
    # bounce that is genuinely unpaid, or an account already past 90.
    if features.bucket == A.B_90_PLUS:
        return None
    if features.open_bounce_id and (features.bounce_age_hours or 0) >= 24 * 21:
        return None
    return LEGAL_PREREQUISITES


def _contact_veto(
    conn: Any, *, features: AccountFeatures, channel: str, at: datetime
) -> str | None:
    """Delegate to the one contact policy. Fail closed on anything unexpected."""
    import contact_policy

    try:
        decision = contact_policy.evaluate(
            conn,
            customer_id=features.customer_id,
            channel=channel,
            purpose="outreach",
            now=at,
        )
    except Exception:
        logger.exception(
            "contact policy evaluation failed for %s/%s", features.customer_id, channel
        )
        return f"{CONTACT_PREFIX}{contact_policy.REASON_UNREADABLE}"
    if decision.allowed:
        return None
    return f"{CONTACT_PREFIX}{decision.reason or contact_policy.REASON_UNREADABLE}"


# ---------------------------------------------------------------------------
# Collection / upsell separation
# ---------------------------------------------------------------------------

#: Digital Lending Guidelines require a hard separation between collecting a
#: debt and selling a product. The offer engine already refuses to pitch during
#: hardship, a dispute or an escalation *stated on the call*; this closes the
#: half it could not see — a hold placed by a supervisor last Tuesday, or a
#: borrower the treatment ladder has escalated past the point where a cross-sell
#: is anything but tone-deaf.
UPSELL_BLOCKING_HOLDS = frozenset({"hardship", "complaint", "bereavement", "legal"})
UPSELL_BLOCKING_BUCKETS = frozenset({A.B_61_90, A.B_90_PLUS})


def suppresses_upsell(conn: Any, customer_id: str) -> str | None:
    """Reason an offer must not be made to this customer, or None.

    Read by ``reco.arbitration`` so there is one definition of the separation
    rather than two that drift. Never raises: an unreadable hold table must not
    take the offer path down, and it must not silently open it either — the
    caller treats an exception here as "suppress", which this function makes
    explicit by returning a reason.
    """
    from sqlalchemy import text

    try:
        kinds = conn.execute(
            text(
                """
                SELECT kind FROM treatment_holds
                WHERE customer_id = :cid
                  AND released_at IS NULL
                  AND starts_at <= now()
                  AND (expires_at IS NULL OR expires_at > now())
                """
            ),
            {"cid": customer_id},
        ).scalars().all()
    except Exception:
        logger.exception("treatment hold lookup failed for %s", customer_id)
        return "treatment_hold_unreadable"
    for kind in kinds:
        if kind in UPSELL_BLOCKING_HOLDS:
            return f"{HOLD_PREFIX}{kind}"
    return None


#: What a contact ledger row means in ladder terms. Keyed on
#: ``(channel, actor_kind)`` because a voice attempt by a bot and the same
#: attempt by a telecaller are different rungs of the same ladder.
_LEDGER_RUNG: dict[tuple[str, str], str] = {
    ("sms", "*"): A.SMS,
    ("email", "*"): A.SMS,
    ("whatsapp", "*"): A.WHATSAPP,
    ("chat", "*"): A.WHATSAPP,
    ("voice", "bot"): A.VOICE_BOT,
    ("voice", "system"): A.VOICE_BOT,
    ("voice", "human"): A.HUMAN_CALL,
    ("voice", "agency"): A.HUMAN_CALL,
    ("field", "*"): A.FIELD_VISIT,
}


def _ledger_rung(channel: str, actor_kind: str) -> int:
    action = _LEDGER_RUNG.get((channel, actor_kind)) or _LEDGER_RUNG.get((channel, "*"))
    return A.rung(action) if action else 0


def last_rung_used(
    conn: Any, customer_id: str, *, within: timedelta, bucket: str | None = None
) -> int:
    """Highest ladder rung this borrower has actually experienced recently.

    Read from ``contact_events`` — the cross-channel outbound ledger P6 already
    keeps — rather than from this engine's own history. That distinction is the
    whole point: a telecaller who rang yesterday and a bot that rang yesterday
    both mean the borrower has been called, and an escalation ladder that only
    remembers its own decisions would treat a heavily-worked account as
    untouched. It would also never escalate at all on a fresh install, because
    nothing it can enact is reachable from a rung it has never recorded.

    Recency matters: a field visit in March must not authorise a second one in
    August without the digital ladder being walked again.

    Denied attempts do not count. The borrower did not experience them, and
    counting a blocked dial as an escalation would let a DND flag advance the
    ladder.
    """
    from sqlalchemy import text

    floor = A.bucket_policy(bucket).ladder_floor if bucket else 0
    try:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT channel, actor_kind
                FROM contact_events
                WHERE customer_id = :cid
                  AND outcome = 'allowed'
                  AND direction = 'outbound'
                  AND occurred_at >= now() - CAST(:window AS interval)
                """
            ),
            {"cid": customer_id, "window": f"{int(within.total_seconds())} seconds"},
        ).mappings().all()
        served = conn.execute(
            text(
                """
                SELECT 1 FROM treatment_decisions
                WHERE customer_id = :cid AND chosen_action = 'legal_notice'
                  AND enacted IS TRUE
                  AND enacted_at >= now() - CAST(:window AS interval)
                LIMIT 1
                """
            ),
            {"cid": customer_id, "window": f"{int(within.total_seconds())} seconds"},
        ).fetchone()
    except Exception:
        logger.exception("ladder history lookup failed for %s", customer_id)
        # Fail closed to the bucket's own floor: unknown history can only
        # under-escalate from there, never past it.
        return floor
    observed = max(
        (_ledger_rung(str(r["channel"]), str(r["actor_kind"])) for r in rows), default=0
    )
    if served:
        observed = max(observed, A.rung(A.LEGAL_NOTICE))
    return max(observed, floor)
