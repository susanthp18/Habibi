"""Authored post-call actions — the rules on the card, carried out.

``CardPostCall.on_outcome`` shipped as a validated, versioned, publishable list
that did nothing. G-OB6 checked every verb was real and the Closer then ignored
the whole thing and ran a hardcoded set instead. That is arguably worse than not
having the field: an operator edits a rule, publishes a version, sees the diff in
the change log, and the behaviour never moves.

This module is the missing half. One registry, one function per verb, and a
result string per action so ``call_outcomes.actions_applied`` records what was
actually done rather than what was configured.

Three rules the registry follows
--------------------------------
**Nothing here decides.** Every action is a consequence of an outcome the Closer
already determined. None of them re-opens the question of whether to contact
somebody, and the two that schedule future contact (``schedule_mission``,
``requeue``) go through the cadence, which goes through ``contact_policy`` at
dial time like everything else.

**An unknown verb is recorded, never silent.** G-OB6 makes an unpublishable
card impossible, but a card published before a verb was removed is possible, and
"the rule did nothing and nobody knew" is the failure this module exists to end.

**Failures are per-action.** One verb that raises must not lose the other four,
and must never lose the outcome row itself — the record of what happened on the
call matters more than the follow-up it triggers.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: ``place_hold(30d)`` → ("place_hold", "30d"). A verb may carry one argument;
#: anything richer belongs in a tool, not in a rule string.
_CALL_RE = re.compile(r"^\s*([a-z_]+)\s*(?:\(\s*([^)]*)\s*\))?\s*$")

_DURATION_RE = re.compile(r"^(\d+)\s*([dhm])$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(action: str) -> tuple[str, str | None]:
    match = _CALL_RE.match(action or "")
    if not match:
        return (action or "").strip(), None
    verb, arg = match.group(1), match.group(2)
    return verb, (arg.strip() or None) if arg is not None else None


def _duration(arg: str | None, default: timedelta) -> timedelta:
    match = _DURATION_RE.match((arg or "").strip())
    if not match:
        return default
    value, unit = int(match.group(1)), match.group(2)
    return {"d": timedelta(days=value), "h": timedelta(hours=value), "m": timedelta(minutes=value)}[
        unit
    ]


# ---------------------------------------------------------------------------
# The verbs
# ---------------------------------------------------------------------------


def _followup_without_promise(ctx: dict[str, Any]) -> str:
    """Write to the borrower about an outcome that produced no promise.

    The context each kind needs is published by the verb that produced it —
    ``place_hold`` sets ``hold_until``, ``flag_dispute`` sets ``dispute_ref`` —
    which is why rule order matters and why the defaults put the acting verb
    before ``confirm_written``. A kind whose context is missing declines to send
    rather than sending a message with a gap in it.
    """
    try:
        import written_followup

        attempt = ctx["attempt"]
        result = written_followup.for_outcome(
            ctx["conn"],
            customer_id=attempt["customer_id"],
            business=ctx.get("business"),
            account_id=attempt.get("account_id"),
            related_id=attempt.get("interaction_id") or attempt["id"],
            context={
                "holdUntil": ctx.get("hold_until"),
                "reference": ctx.get("dispute_ref"),
                "callbackAt": ctx.get("obligation_due_at"),
                            },
        )
        return f"confirm_written:{result.describe()}"
    except Exception:
        logger.exception("confirm_written fallback failed")
        return "confirm_written:failed"


def _confirm_written(ctx: dict[str, Any], arg: str | None) -> str:
    """Send the borrower a written record of what was agreed.

    Delegates to ``promise_fulfillment.fulfill`` where there is a promise —
    it already picks a channel the borrower has not opted out of, attaches a
    real pay link and never invents a URL. Where there is no promise there is
    nothing to confirm, and saying so is more useful than sending a message
    about nothing.
    """
    promise_id = (ctx.get("commitment") or {}).get("promiseId")
    if not promise_id:
        # Not every outcome worth writing about is a promise. A hardship hold, a
        # dispute reference and a callback time are all things the institution
        # just committed to, and until `written_followup` existed each of them
        # ended the call in silence.
        return _followup_without_promise(ctx)
    try:
        import promise_fulfillment

        result = promise_fulfillment.fulfill(ctx["conn"], str(promise_id))
        if getattr(result, "suppressed", False):
            return f"confirm_written:suppressed:{getattr(result, 'suppression_reason', '')}"
        return f"confirm_written:{getattr(result, 'confirm_channel', 'sent')}"
    except Exception:
        logger.exception("confirm_written failed")
        return "confirm_written:failed"


def _schedule_due_reminder(ctx: dict[str, Any], arg: str | None) -> str:
    """Already done by ``fulfill``; recorded so the rule is not a lie.

    ``promise_fulfillment.fulfill`` schedules the due-date reminder in the same
    call that sends the confirm. Duplicating it here would send two.
    """
    promise_id = (ctx.get("commitment") or {}).get("promiseId")
    return f"schedule_due_reminder:{'with_confirm' if promise_id else 'no_commitment'}"


def _place_hold(ctx: dict[str, Any], arg: str | None) -> str:
    """Stop collections activity on this borrower for a while.

    A hold is a row, not a routing rule — which is what makes a bot at 02:00
    bound by it exactly as a supervisor is.
    """
    window = _duration(arg, timedelta(days=30))
    kind = "hardship" if ctx.get("business") == "hardship_declared" else "dispute"
    try:
        ctx["conn"].execute(
            text(
                """
                INSERT INTO treatment_holds (
                  id, tenant_id, customer_id, kind, reason, source,
                  interaction_id, placed_by_user_id, expires_at
                ) VALUES (
                  :id, :tenant, :customer, :kind, :reason, 'bot',
                  :ix, NULL, now() + make_interval(days => :days)
                )
                ON CONFLICT (customer_id, COALESCE(account_id, ''), kind)
                WHERE released_at IS NULL
                DO NOTHING
                """
            ),
            {
                "id": f"TH-{uuid.uuid4().hex[:10].upper()}",
                "tenant": ctx["attempt"]["tenant_id"],
                "customer": ctx["attempt"]["customer_id"],
                "kind": kind,
                "reason": f"post-call rule after {ctx.get('business')}",
                "ix": ctx["attempt"].get("interaction_id"),
                "days": max(1, int(window.total_seconds() // 86_400)),
            },
        )
        days = max(1, int(window.total_seconds() // 86_400))
        # The follow-up has to be able to say *until when*, so the verb that
        # knows publishes it and the verb that writes reads it.
        #
        # Read back rather than computed. The INSERT above is ON CONFLICT DO
        # NOTHING, so where a hold was already open this wrote nothing and the
        # date that stands is the older one's. Publishing the date we would have
        # written is how the borrower gets told a deadline that no row in the
        # database agrees with - which is the precise failure `written_followup`
        # exists to refuse.
        expires = ctx["conn"].execute(
            text(
                """
                SELECT expires_at FROM treatment_holds
                WHERE customer_id = :customer AND kind = :kind AND released_at IS NULL
                ORDER BY expires_at DESC NULLS FIRST
                LIMIT 1
                """
            ),
            {"customer": ctx["attempt"]["customer_id"], "kind": kind},
        ).scalar()
        if expires is not None:
            ctx["hold_until"] = expires.date()
        return f"place_hold:{kind}:{days}d"
    except Exception:
        logger.exception("place_hold failed")
        return "place_hold:failed"


def _create_followup(ctx: dict[str, Any], arg: str | None) -> str:
    """Put it in front of a person, with the reason attached."""
    try:
        import db as dbmod

        followup_id = dbmod._id("FUP")
        ctx["conn"].execute(
            text(
                """
                INSERT INTO followups (
                  id, promise_id, lead_id, customer_id, assignee_user_id,
                  status, priority, due_at, note, channel
                ) VALUES (
                  :id, :promise_id, NULL, :customer, NULL,
                  'open', :priority, now() + interval '1 day', :note, 'voice'
                )
                """
            ),
            {
                "id": followup_id,
                # followups requires exactly one of promise_id / lead_id, so a
                # rule with no promise behind it is refused rather than faked.
                "promise_id": (ctx.get("commitment") or {}).get("promiseId"),
                "customer": ctx["attempt"]["customer_id"],
                "priority": "high" if ctx.get("business") == "hardship_declared" else "normal",
                "note": f"{arg or 'specialist'} review after {ctx.get('business')}"[:500],
            },
        )
        return f"create_followup:{followup_id}"
    except Exception:
        # The commonest cause is the promise_id/lead_id constraint above, and it
        # is a real refusal rather than a bug: there is nothing to attach to.
        logger.info("create_followup skipped", exc_info=True)
        return "create_followup:no_anchor"


def _suppress_upsell(ctx: dict[str, Any], arg: str | None) -> str:
    """No product talk to this borrower for a while, on any channel.

    Written as a hold rather than a note because a note is advice and a hold is
    enforced — the reco engine reads holds, and nobody reads notes at 02:00.
    """
    window = _duration(arg, timedelta(days=90))
    try:
        ctx["conn"].execute(
            text(
                """
                INSERT INTO treatment_holds (
                  id, tenant_id, customer_id, kind, reason, source,
                  interaction_id, placed_by_user_id, expires_at
                ) VALUES (
                  :id, :tenant, :customer, 'no_upsell', :reason, 'bot',
                  :ix, NULL, now() + make_interval(days => :days)
                )
                ON CONFLICT (customer_id, COALESCE(account_id, ''), kind)
                WHERE released_at IS NULL
                DO NOTHING
                """
            ),
            {
                "id": f"TH-{uuid.uuid4().hex[:10].upper()}",
                "tenant": ctx["attempt"]["tenant_id"],
                "customer": ctx["attempt"]["customer_id"],
                "reason": f"declared {ctx.get('nonpayment_reason') or ctx.get('business')}",
                "ix": ctx["attempt"].get("interaction_id"),
                "days": max(1, int(window.total_seconds() // 86_400)),
            },
        )
        return f"suppress_upsell:{int(window.total_seconds() // 86_400)}d"
    except Exception:
        # `no_upsell` may not be a permitted hold kind on this schema version.
        logger.info("suppress_upsell not applied", exc_info=True)
        return "suppress_upsell:unsupported_kind"


def _record_optout(ctx: dict[str, Any], arg: str | None) -> str:
    """Honour it now, not on the next tick.

    An opt-out written an hour late is an opt-out ignored — and unlike every
    other action here, the borrower has already been told it is done.
    """
    channel = (arg or "voice").strip() or "voice"
    try:
        import db as dbmod

        dbmod.opt_out(
            ctx["attempt"]["customer_id"],
            {"channel": channel, "source": "voice_agent", "note": "requested on an outbound call"},
        )
        return f"record_optout:{channel}"
    except Exception:
        logger.exception("record_optout FAILED — the borrower asked and we did not write it")
        return "record_optout:failed"


def _stop_cadence(ctx: dict[str, Any], arg: str | None) -> str:
    try:
        import cadence

        ctx["conn"].execute(
            text(
                """
                UPDATE call_cadence_state
                SET state = 'stopped', stopped_reason = :reason,
                    next_attempt_at = NULL, updated_at = now()
                WHERE customer_id = :cid AND state = 'open'
                """
            ),
            {"cid": ctx["attempt"]["customer_id"], "reason": f"rule:{ctx.get('business')}"},
        )
        del cadence  # imported for the module contract, not used directly here
        return "stop_cadence:all_open"
    except Exception:
        logger.exception("stop_cadence failed")
        return "stop_cadence:failed"


def _close_case(ctx: dict[str, Any], arg: str | None) -> str:
    return _stop_cadence(ctx, arg).replace("stop_cadence", "close_case")


def _schedule_mission(ctx: dict[str, Any], arg: str | None) -> str:
    """Open a ladder for a different mission — usually the callback they asked for.

    Goes through the cadence rather than dialling: the borrower named a time,
    and honouring it is still subject to the calling window and their consent at
    the moment it comes round.
    """
    objective = (arg or "callback_honour").strip()
    obligation_at = ctx.get("obligation_due_at") or (_now() + timedelta(days=1))
    try:
        import cadence

        case = cadence.ensure_case(
            ctx["conn"],
            tenant_id=ctx["attempt"]["tenant_id"],
            customer_id=ctx["attempt"]["customer_id"],
            objective=objective,
            case_ref=str(ctx["attempt"].get("decision_id") or ctx["attempt"]["id"]),
            max_attempts=2,
        )
        ctx["conn"].execute(
            text(
                "UPDATE call_cadence_state SET next_attempt_at = :at, updated_at = now() "
                "WHERE id = :id"
            ),
            {"id": case["id"], "at": obligation_at},
        )
        return f"schedule_mission:{objective}"
    except Exception:
        logger.exception("schedule_mission failed")
        return "schedule_mission:failed"


def _requeue(ctx: dict[str, Any], arg: str | None) -> str:
    """Start the ladder again — a new number is a new chance, not a spent one."""
    try:
        ctx["conn"].execute(
            text(
                """
                UPDATE call_cadence_state
                SET attempts = 0, state = 'open', stopped_reason = NULL,
                    next_attempt_at = now() + interval '1 day', updated_at = now()
                WHERE customer_id = :cid AND objective = :objective
                """
            ),
            {
                "cid": ctx["attempt"]["customer_id"],
                "objective": ctx["attempt"].get("objective") or "",
            },
        )
        return "requeue:ladder_reset"
    except Exception:
        logger.exception("requeue failed")
        return "requeue:failed"


def _mark_phone_dead(ctx: dict[str, Any], arg: str | None) -> str:
    """Flag the slot, do not mutate the customer.

    Deciding a borrower's phone number is dead is a data-quality change that
    should be reviewed, not applied by a worker at 2am on one wrong-number call.
    """
    try:
        ctx["conn"].execute(
            text(
                "UPDATE call_attempts SET context = context || CAST(:patch AS jsonb), "
                "updated_at = now() WHERE id = :id"
            ),
            {
                "id": ctx["attempt"]["id"],
                "patch": json.dumps({"phoneSlotDead": True, "slot": ctx["attempt"].get("phone_slot")}),
            },
        )
        return f"mark_phone_dead:{ctx['attempt'].get('phone_slot')}"
    except Exception:
        logger.exception("mark_phone_dead failed")
        return "mark_phone_dead:failed"


def _promote_alternate(ctx: dict[str, Any], arg: str | None) -> str:
    """Prefer the alternate number on the next attempt, if there is one."""
    try:
        has_alt = ctx["conn"].execute(
            text("SELECT phone_alt IS NOT NULL FROM customers WHERE id = :id"),
            {"id": ctx["attempt"]["customer_id"]},
        ).scalar()
        if not has_alt:
            return "promote_alternate:none_on_file"
        ctx["conn"].execute(
            text(
                "UPDATE call_attempts SET context = context || CAST(:patch AS jsonb), "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": ctx["attempt"]["id"], "patch": json.dumps({"preferSlot": "alt"})},
        )
        return "promote_alternate:alt"
    except Exception:
        logger.exception("promote_alternate failed")
        return "promote_alternate:failed"


def _flag_dispute(ctx: dict[str, Any], arg: str | None) -> str:
    """The tool already filed it during the call; this confirms rather than duplicates."""
    existing = ctx["conn"].execute(
        text("SELECT id FROM disputes WHERE interaction_id = :ix LIMIT 1"),
        {"ix": ctx["attempt"].get("interaction_id")},
    ).scalar()
    if existing:
        # The reference the borrower is told in writing must be the id of the
        # row a colleague will later open, not a number minted for the message.
        ctx["dispute_ref"] = str(existing)
    return f"flag_dispute:{'already_filed' if existing else 'none_filed_in_call'}"


def _notify(ctx: dict[str, Any], arg: str | None) -> str:
    """An activity row a human queue can see. Not a channel to the borrower."""
    try:
        import db as dbmod

        dbmod._activity(
            ctx["conn"],
            "interaction",
            ctx["attempt"].get("interaction_id") or ctx["attempt"]["id"],
            "post_call_notify",
            f"Post-call notify: {arg or 'queue'}",
            str(ctx.get("business") or ""),
            ctx["attempt"]["customer_id"],
        )
        return f"notify:{arg or 'queue'}"
    except Exception:
        logger.exception("notify failed")
        return "notify:failed"


def _advance_ladder(ctx: dict[str, Any], arg: str | None) -> str:
    """A marker, not an action.

    The ladder is ``treatment/followthrough.py``'s to advance, and it does so
    from the outcome this Closer just wrote. A rule that advanced it here would
    be a dialler making an escalation decision.
    """
    return "advance_ladder:deferred_to_followthrough"


REGISTRY: dict[str, Any] = {
    "confirm_written": _confirm_written,
    "schedule_due_reminder": _schedule_due_reminder,
    "close_case": _close_case,
    "place_hold": _place_hold,
    "create_followup": _create_followup,
    "suppress_upsell": _suppress_upsell,
    "flag_dispute": _flag_dispute,
    "notify": _notify,
    "schedule_mission": _schedule_mission,
    "mark_phone_dead": _mark_phone_dead,
    "promote_alternate": _promote_alternate,
    "requeue": _requeue,
    "record_optout": _record_optout,
    "stop_cadence": _stop_cadence,
    "advance_ladder": _advance_ladder,
}


#: Verbs that send the borrower something in writing, and are therefore what
#: ``CardPostCall.written_followup`` switches off. ``schedule_due_reminder`` is
#: deliberately not here: a reminder before the due date is a separate decision
#: from confirming what was just agreed, and a tenant that suppresses the
#: confirmation has not thereby asked to stop reminding people.
_WRITTEN_VERBS: frozenset[str] = frozenset({"confirm_written"})


def apply(
    conn: Any,
    *,
    attempt: dict[str, Any],
    business: str | None,
    nonpayment_reason: str | None,
    commitment: dict[str, Any] | None,
    rules: list[Any],
    obligation_due_at: datetime | None = None,
    written_followup: bool = True,
) -> list[str]:
    """Run the card's rules for this outcome. Returns what was actually done.

    Never raises. The outcome row is the record of what happened on the call and
    matters more than any follow-up it triggers, so a rule that explodes costs
    its own action and nothing else.

    ``written_followup`` is ``CardPostCall.written_followup`` — the switch above
    the rules. It defaults to True so every existing caller keeps the behaviour
    it has, and it suppresses the verb rather than the rule: a rule that says
    "on ptp_captured, confirm in writing and schedule the reminder" still
    schedules the reminder.
    """
    if not business:
        return []
    ctx = {
        "conn": conn,
        "attempt": attempt,
        "business": business,
        "nonpayment_reason": nonpayment_reason,
        "commitment": commitment or {},
        "obligation_due_at": obligation_due_at,
    }
    applied: list[str] = []
    for rule in rules or []:
        when = getattr(rule, "when", None) or (rule.get("when") if isinstance(rule, dict) else None)
        if when != business:
            continue
        actions = getattr(rule, "do", None)
        if actions is None and isinstance(rule, dict):
            actions = rule.get("do")
        for raw in actions or []:
            verb, arg = _parse(str(raw))
            if verb in _WRITTEN_VERBS and not written_followup:
                # Recorded, not silently skipped. "Nothing happened" and "the
                # card said not to" are different facts, and the action list is
                # what the audit trail shows for this call.
                applied.append(f"{verb}:off_by_card")
                continue
            fn = REGISTRY.get(verb)
            if fn is None:
                # G-OB6 makes this unpublishable, but a card published before a
                # verb was removed is possible — and "the rule did nothing and
                # nobody knew" is the failure this module exists to end.
                logger.warning("post-call rule names unknown action %r", verb)
                applied.append(f"{verb}:unknown_action")
                continue
            try:
                applied.append(str(fn(ctx, arg)))
            except Exception:
                logger.exception("post-call action %r failed", verb)
                applied.append(f"{verb}:failed")
    return applied
