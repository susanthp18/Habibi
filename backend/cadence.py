"""Retry — the loop that turns a no-answer into a second attempt.

Before ``call_attempts`` this could not exist. An unanswered dial left no row, so
there was nothing to count attempts against, nothing to back off from and
nothing to stop. A ring-out was a dead end.

The boundary this module must not cross
---------------------------------------
**Cadence may retry the same action. Only the treatment engine may change the
action.** A dialler that decided "three no-answers, send it to a human" would be
a second escalation ladder with no expected value, no propensity and no audit
trail — and it would quietly outvote the one that has all three.

So this module does exactly two things: it schedules another dial of the same
mission, and when the attempts run out it stops and says so. What happens next
to a case whose cadence is exhausted is ``treatment/followthrough.py``'s
decision, made with the outcome codes this loop produced.

The case, not the attempt
-------------------------
State lives in ``call_cadence_state``, keyed on (customer, objective, case_ref),
because the thing that persists across dials is the *case*. An attempt is one
dial and is finished when the carrier says so.

Three vetoes, all of which can only subtract
--------------------------------------------
1. ``stop_on`` — the outcome resolved the case, or ended it (opt-out, deceased,
   wrong number). Terminal regardless of attempt count.
2. ``max_attempts`` — the authored ceiling.
3. ``contact_policy.admit`` at dial time — the borrower's budget, consent and
   the statutory window, re-checked at the moment of the retry rather than when
   it was scheduled.

A retry never widens anything. It is a request to spend one more of an
allowance that something else grants.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

import flow_graph as fg
import outbound
from env_utils import env_int

logger = logging.getLogger(__name__)

STATE_OPEN = "open"
STATE_EXHAUSTED = "exhausted"
STATE_STOPPED = "stopped"
STATE_ESCALATED = "escalated"

#: How many due retries one worker iteration places. One, deliberately: the
#: worker loop is shared with bot turns, promise settlement and the treatment
#: loops, and a cadence burst that starved any of those would be a dialler
#: deciding it matters most.
BATCH = 1


def enabled() -> bool:
    from agent_core.platform_flags import campaign_runtime_enabled

    return campaign_runtime_enabled()


def max_backoff_hours() -> int:
    """Ceiling on a single wait, whatever the card says.

    A cadence with a 30-day backoff is not a cadence, it is a case somebody
    forgot about — and the ladder, not the dialler, should be deciding what
    happens to a borrower nobody has reached in a month.
    """
    return max(1, env_int("CADENCE_MAX_BACKOFF_HOURS", 168))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sid() -> str:
    return f"CDS-{uuid.uuid4().hex[:12].upper()}"


def backoff_for(attempt_no: int, curve: list[int] | None) -> timedelta:
    """Wait before attempt ``attempt_no + 1``.

    A curve shorter than the attempt count repeats its last value rather than
    falling off the end — ``[4, 24]`` on a three-attempt cadence means 4h then
    24h then 24h, which is what an author writing two numbers means.
    """
    steps = [h for h in (curve or []) if isinstance(h, int) and h > 0] or [4, 24, 72]
    idx = min(max(0, attempt_no - 1), len(steps) - 1)
    hours = min(steps[idx], max_backoff_hours())
    return timedelta(hours=hours)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def ensure_case(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    objective: str,
    case_ref: str = "",
    cadence: str = "default",
    max_attempts: int = 3,
    campaign_run_id: str | None = None,
    attempts: int = 0,
) -> dict[str, Any]:
    """Open (or return) the ladder for one case. Idempotent.

    ``attempts`` only ever raises the counter. The ladder is created lazily —
    at the first *outcome*, not the first dial — so the row has to be able to
    catch up to an attempt that already happened, and a later call with a
    stale count must not undo it.
    """
    row = conn.execute(
        text(
            """
            INSERT INTO call_cadence_state (
              id, tenant_id, customer_id, objective, case_ref, cadence,
              max_attempts, campaign_run_id, attempts, state, created_at, updated_at
            ) VALUES (
              :id, :tenant, :customer, :objective, :case_ref, :cadence,
              :max_attempts, :run, :attempts, 'open', now(), now()
            )
            ON CONFLICT (customer_id, objective, case_ref) DO UPDATE
              SET updated_at = now(),
                  attempts = GREATEST(call_cadence_state.attempts, EXCLUDED.attempts),
                  max_attempts = EXCLUDED.max_attempts
            RETURNING *
            """
        ),
        {
            "id": _sid(),
            "tenant": tenant_id,
            "customer": customer_id,
            "objective": objective,
            "case_ref": case_ref or "",
            "cadence": cadence,
            "max_attempts": max(1, int(max_attempts)),
            "run": campaign_run_id,
            "attempts": max(0, int(attempts)),
        },
    ).mappings().first()
    return dict(row)


def record_attempt(conn: Any, *, case_id: str, attempt_id: str) -> None:
    conn.execute(
        text(
            """
            UPDATE call_cadence_state
            SET attempts = attempts + 1,
                last_attempt_id = :attempt,
                next_attempt_at = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": case_id, "attempt": attempt_id},
    )


def on_outcome(
    conn: Any,
    *,
    attempt: dict[str, Any],
    connection: str,
    business: str | None,
    card_outbound: Any = None,
) -> str:
    """Decide what the ladder does next. Returns the resulting state.

    Called by the Closer, with the outcome it just wrote. This is the only place
    a retry is scheduled, so "what happens after a call" has one answer rather
    than one per caller.
    """
    case = conn.execute(
        text(
            """
            SELECT * FROM call_cadence_state
            WHERE customer_id = :cid AND objective = :objective AND case_ref = :ref
            FOR UPDATE
            """
        ),
        {
            "cid": attempt["customer_id"],
            "objective": attempt.get("objective") or "",
            "ref": _case_ref(attempt),
        },
    ).mappings().first()
    if case is None:
        return "no_case"
    if str(case["state"]) != STATE_OPEN:
        return str(case["state"])

    objective = str(attempt.get("objective") or "")
    cadence = (
        card_outbound.cadence_for(objective)
        if card_outbound is not None
        else _DefaultCadence()
    )

    # 1. Did the conversation end the case? Terminal beats everything, including
    #    an attempt budget with room left in it.
    if business and business in set(cadence.stop_on):
        _stop(conn, case["id"], STATE_STOPPED, f"outcome:{business}", business)
        return STATE_STOPPED

    # 2. Is this the kind of ending worth trying again? A refusal is not: the
    #    borrower answered and said no, and dialling them again in four hours is
    #    harassment dressed as persistence.
    if connection not in set(cadence.retry_on) and str(attempt.get("state")) not in set(
        cadence.retry_on
    ):
        _stop(conn, case["id"], STATE_STOPPED, f"not_retryable:{connection}", business)
        return STATE_STOPPED

    # 3. Attempts left?
    attempts = int(case["attempts"] or 0)
    if attempts >= int(case["max_attempts"] or 3):
        _stop(conn, case["id"], STATE_EXHAUSTED, "max_attempts", business)
        logger.info(
            "cadence exhausted · customer=%s · mission=%s · %s attempts",
            attempt["customer_id"],
            objective,
            attempts,
        )
        return STATE_EXHAUSTED

    nxt = _now() + backoff_for(attempts, list(cadence.backoff_hours))
    conn.execute(
        text(
            """
            UPDATE call_cadence_state
            SET next_attempt_at = :nxt, last_outcome = :outcome, updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": case["id"], "nxt": nxt, "outcome": business or connection},
    )
    return STATE_OPEN


class _DefaultCadence:
    """The conservative fallback when no card is resolvable at outcome time."""

    max_attempts = 3
    per_day = 1
    backoff_hours = (4, 24, 72)
    retry_on = ("no_answer", "busy", "voicemail_left", "voicemail_skipped")
    stop_on = (
        "ptp_captured",
        "ptp_recommitted",
        "paid_in_call",
        "dispute_raised",
        "opt_out_requested",
        "wrong_number",
        "deceased",
    )
    escalate_to = None


def _case_ref(attempt: dict[str, Any]) -> str:
    """The case an attempt belongs to.

    The decision id when the engine placed it — one decision is one case — and
    the campaign run otherwise. Empty for a one-off manual dial, which is
    correct: a colleague pressing "call now" has not opened a ladder.
    """
    return str(attempt.get("decision_id") or attempt.get("campaign_run_id") or "")


def _stop(conn: Any, case_id: str, state: str, reason: str, outcome: str | None) -> None:
    conn.execute(
        text(
            """
            UPDATE call_cadence_state
            SET state = :state, stopped_reason = :reason, last_outcome = :outcome,
                next_attempt_at = NULL, updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": case_id, "state": state, "reason": reason[:200], "outcome": outcome},
    )


# ---------------------------------------------------------------------------
# The retry worker
# ---------------------------------------------------------------------------


#: Campaign runs whose held ladders have already been logged. A pause lasts as
#: long as somebody leaves it on, and the worker polls every second and a half;
#: without this the hold would write the same line thousands of times. Bounded
#: by the number of runs, and discarded again the moment one resumes.
_PAUSE_LOGGED: set[str] = set()


def claim_due(conn: Any) -> dict[str, Any] | None:
    """The next due retry, with the status of the campaign that opened it.

    The join is a left join and paused runs are ordered last rather than
    filtered out, so that ``process_one`` can say *which* campaign is holding a
    firing — and so a paused campaign with a hundred due ladders cannot sit at
    the head of the queue and starve every other borrower's retry, which a
    plain ``ORDER BY next_attempt_at`` would do.
    """
    row = conn.execute(
        text(
            """
            SELECT s.*, c.phone_primary, c.phone_alt, c.tenant_id AS cust_tenant,
                   r.status AS run_status
            FROM call_cadence_state s
            JOIN customers c ON c.id = s.customer_id
            LEFT JOIN campaign_runs r ON r.id = s.campaign_run_id
            WHERE s.state = 'open'
              AND s.next_attempt_at IS NOT NULL
              AND s.next_attempt_at <= now()
            ORDER BY (r.status IS NOT DISTINCT FROM 'paused') ASC,
                     s.next_attempt_at ASC
            FOR UPDATE OF s SKIP LOCKED
            LIMIT 1
            """
        )
    ).mappings().first()
    return dict(row) if row else None


def process_one(engine: Engine) -> bool:
    """Place one due retry. Returns True if a case was claimed at all.

    The gate runs here, not when the retry was scheduled. A wait of four hours
    is four hours in which the borrower may have paid, opted out, or used up
    their contact budget on another channel — and a retry that trusted the
    schedule instead of asking again would be the one call that breaches.
    """
    if not enabled():
        return False

    import campaigns
    import contact_policy
    import db as dbmod
    import mission as mission_mod

    with engine.begin() as conn:
        case = claim_due(conn)
        if case is None:
            return False
        case_id = case["id"]

        # Pausing a campaign has to stop the ladders it already opened, not just
        # the list it has yet to work through. Before this, an operator who
        # pulled the handbrake still had second and third attempts going out for
        # days, because every ladder the run had opened kept its own clock.
        #
        # The queued rows are left exactly where they are. A pause is not a
        # cancellation: the borrower keeps their place in their own cadence, the
        # firing is simply held, and the first poll after the run resumes places
        # it. Read at firing time rather than at scheduling time, for the same
        # reason the contact gate is — the status that matters is the one now.
        run_id = str(case.get("campaign_run_id") or "")
        if str(case.get("run_status") or "") == campaigns.STATUS_PAUSED:
            if run_id not in _PAUSE_LOGGED:
                _PAUSE_LOGGED.add(run_id)
                logger.info(
                    "cadence retry held · campaign=%s is paused · case=%s",
                    run_id,
                    case_id,
                )
            return False
        _PAUSE_LOGGED.discard(run_id)

        # The ceiling, checked before the dial rather than after it.
        #
        # `on_outcome` is the ladder's arithmetic and it is correct, but it only
        # ever runs on an *outcome* — so a case whose counter is already at the
        # ceiling and which somehow still carries a `next_attempt_at` (a curve
        # re-queued by `_recover_stranded` on a row whose max_attempts was
        # lowered since, a ladder re-queued by hand, an authored ceiling edited
        # downwards mid-cadence) would be dialled one more time and only then
        # be told it had run out. That extra dial is a real call to a real
        # borrower, past a limit somebody authored specifically to stop it.
        #
        # `attempts` counts dials already spent, so the dial about to be placed
        # is number `attempts + 1`: there is room only while `attempts` is below
        # the ceiling. Same comparison `on_outcome` makes, and the same
        # mechanism — `_stop` to `exhausted` — so an operator sees one story.
        attempts_so_far = int(case["attempts"] or 0)
        ceiling = int(case["max_attempts"] or 3)
        if attempts_so_far >= ceiling:
            _stop(conn, case_id, STATE_EXHAUSTED, "max_attempts", None)
            logger.info(
                "cadence retry not placed · case=%s is exhausted · %s of %s attempts spent",
                case_id,
                attempts_so_far,
                ceiling,
            )
            return True

        objective = str(case["objective"])
        phone = case.get("phone_primary") or case.get("phone_alt")
        if not phone:
            _stop(conn, case_id, STATE_STOPPED, "no_phone_on_file", None)
            return True

        bot_id = dbmod.DEFAULT_BOT_ID
        card = mission_mod.card_for_bot(bot_id)
        built = mission_mod.build(
            conn,
            customer_id=case["customer_id"],
            objective=objective,
            card=card,
            bot_id=bot_id,
            campaign_run_id=case.get("campaign_run_id"),
            attempt_no=int(case["attempts"] or 0) + 1,
        )
        attempt = outbound.reserve(
            conn,
            customer_id=case["customer_id"],
            to_phone=phone,
            objective=objective,
            decision_id=case["case_ref"] if str(case["case_ref"] or "").startswith("TD-") else None,
            campaign_run_id=case.get("campaign_run_id"),
            bot_id=bot_id,
            tenant_id=case.get("cust_tenant"),
            phone_slot="primary" if case.get("phone_primary") else "alt",
            context={"source": "cadence", "caseId": case_id, "mission": built},
        )
        if attempt is None:
            _stop(conn, case_id, STATE_STOPPED, "customer_gone", None)
            return True

        decision = contact_policy.admit(
            conn,
            customer_id=case["customer_id"],
            channel="voice",
            purpose="outreach",
            # A cross-sell dial is a promotional use of a number collected to
            # service a loan, and needs its own consent basis. Every other
            # objective here is servicing. See flow_graph.PROMOTIONAL_OBJECTIVES.
            data_purpose=fg.data_purpose_for(objective),
            session_key=attempt["id"],
            source="cadence",
            related_id=attempt["id"],
            actor_kind="bot",
        )
        if not decision.allowed:
            outbound.suppress(conn, attempt["id"], decision.reason or "contact_policy")
            # A refusal is not a spent attempt. Push the ladder out and try
            # again rather than burning a retry the borrower never received —
            # otherwise a borrower who is simply asleep exhausts their own
            # cadence overnight.
            conn.execute(
                text(
                    """
                    UPDATE call_cadence_state
                    SET next_attempt_at = now() + interval '2 hours', updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": case_id},
            )
            logger.info("cadence retry deferred · %s · %s", case_id, decision.reason)
            return True

        record_attempt(conn, case_id=case_id, attempt_id=attempt["id"])

    # `place` documents that it never raises, and when it keeps that promise a
    # refused or failed dial is not this loop's problem: it leaves a suppressed
    # or failed attempt behind, the Closer picks that up, and `on_outcome`
    # decides the next rung with a real outcome and an audit trail.
    #
    # When it breaks the promise — a carrier client that fails to import, a
    # connection lost between the two transactions — the case is stranded for
    # good, and silently. `record_attempt` has already committed, so
    # `next_attempt_at` is NULL and `claim_due` will never see the row again;
    # the attempt is still `reserved`, which is the one state the Closer skips.
    # Nobody is dialled, nothing is exhausted, and no operator is told.
    try:
        result = outbound.place(engine, attempt, to_phone=phone)
    except Exception as exc:
        _recover_stranded(
            engine,
            case_id=case_id,
            attempt_id=attempt["id"],
            reason=str(exc),
            curve=_backoff_curve(card, objective),
        )
        return True
    logger.info(
        "cadence retry · case=%s · attempt=%s · placed=%s",
        case_id,
        attempt["id"],
        result.get("placed"),
    )
    return True


def _backoff_curve(card: Any, objective: str) -> list[int] | None:
    """The card's curve for this mission, or None for the conservative default."""
    card_outbound = getattr(card, "outbound", None)
    if card_outbound is None:
        return None
    try:
        return [int(h) for h in card_outbound.cadence_for(objective).backoff_hours]
    except Exception:  # pragma: no cover - a card that cannot answer is a default
        return None


def _recover_stranded(
    engine: Engine,
    *,
    case_id: str,
    attempt_id: str,
    reason: str,
    curve: list[int] | None = None,
) -> None:
    """Put a case back on the ladder after a placement that threw.

    Two rows are left dangling by such a throw and both are dealt with here, in
    a fresh transaction because the one that was open has already committed.

    The attempt is failed, which is what ``place`` itself does when the carrier
    raises: it is a dial that did not happen, and marking it moves it out of
    ``reserved`` and in front of the Closer.

    The ladder is put back on the clock at its own next step rather than
    retried immediately — the attempt counter has already moved, so re-queueing
    on the authored curve is the same wait the borrower would have had if the
    dial had rung out. A ladder with no attempts left is stopped instead, since
    re-queueing one that ``on_outcome`` would refuse to walk is just a slower
    strand.
    """
    try:
        with engine.begin() as conn:
            outbound.fail(conn, attempt_id, reason=f"place_raised: {reason}"[:400])
            case = conn.execute(
                text(
                    """
                    SELECT attempts, max_attempts FROM call_cadence_state
                    WHERE id = :id AND state = 'open'
                    FOR UPDATE
                    """
                ),
                {"id": case_id},
            ).mappings().first()
            if case is None:
                logger.warning(
                    "cadence placement failed and the ladder is no longer open · case=%s · %s",
                    case_id,
                    reason[:200],
                )
                return
            attempts = int(case["attempts"] or 0)
            if attempts >= int(case["max_attempts"] or 3):
                _stop(conn, case_id, STATE_EXHAUSTED, "place_failed:max_attempts", None)
                logger.error(
                    "cadence placement failed on the last attempt · case=%s · attempt=%s · %s",
                    case_id,
                    attempt_id,
                    reason[:200],
                )
                return
            nxt = _now() + backoff_for(attempts, curve)
            conn.execute(
                text(
                    """
                    UPDATE call_cadence_state
                    SET next_attempt_at = :nxt, updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": case_id, "nxt": nxt},
            )
            logger.error(
                "cadence placement failed · case=%s · attempt=%s · re-queued for %s · %s",
                case_id,
                attempt_id,
                nxt.isoformat(),
                reason[:200],
            )
    except Exception:
        # The recovery is bookkeeping on top of a failure that has already
        # happened. It must not replace the original exception with its own.
        logger.exception("cadence could not re-queue case %s after a failed placement", case_id)


def escalation_target(card_outbound: Any, objective: str) -> str | None:
    """Where an exhausted ladder hands off. Advisory — the engine still decides."""
    if card_outbound is None:
        return None
    return card_outbound.cadence_for(objective).escalate_to
