"""The Closer — what the call actually produced, written down properly.

Post-call processing used to be ``capture.build_template_summary()``, which
returns ``"voice session | primary=hardship | customer_turns=7 | ptp=no |
upsell=no"``, and ``disposition_from_flags()``, which picks one of four values
from three booleans. That is a receipt, not a record of a conversation, and
nothing downstream can learn from it.

This module turns one finished attempt into one ``call_outcomes`` row.

Two axes, not one list
----------------------
``connection`` answers "did the phone connect", ``business`` answers "did the
conversation work". The old single field conflated them, which is why a
no-answer and a refusal were the same kind of thing to every consumer. Splitting
them is what makes one retryable and the other not, and it lets reach and
persuasion be improved by different work.

Deterministic first, model second
---------------------------------
Everything that can be read from a row is read from a row: a promise written
during the call, a dispute filed, a tool that ran, the sentiment trajectory, the
guardrail flags. The LLM is asked only for the things that genuinely require
reading the conversation — a business outcome the tools did not already prove, a
non-payment reason nobody captured, and the prose summary — and each of those is
validated against a closed vocabulary before it is accepted.

The summary carries the same fence ``rerank.py`` applies to rationales: a
sentence containing a number the model was not given is rejected, and the
template is written instead with ``summary_source='template'`` so a reader can
tell the two apart rather than trusting both equally.

Where it runs
-------------
``bot_worker``, off a claim query, never on the audio path. The queue is the
``call_attempts`` table itself — ``closed_at IS NULL`` means "this attempt still
owes an outcome" — so there is no second job table to keep in step with the
first. A grace period after ``ended_at`` lets ``CrmSink`` finish draining the
transcript it writes asynchronously; closing a call before its last turn landed
would produce a confident summary of a truncated conversation.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

import outbound
from env_utils import env_int

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary — mirrors the CHECK constraints in sql/21_outbound.sql
# ---------------------------------------------------------------------------

BUSINESS_OUTCOMES: frozenset[str] = frozenset(
    {
        "ptp_captured",
        "ptp_recommitted",
        "paid_in_call",
        "part_payment_agreed",
        "plan_agreed",
        "dispute_raised",
        "hardship_declared",
        "refused",
        "callback_requested",
        "wrong_number",
        "deceased",
        "opt_out_requested",
        "escalated",
        "no_resolution",
        "abandoned_by_customer",
    }
)

NONPAYMENT_REASONS: frozenset[str] = frozenset(
    {
        "salary_timing",
        "income_loss",
        "medical",
        "mandate_broken",
        "disputes_amount",
        "competing_obligation",
        "forgot",
        "unwilling",
        "not_stated",
    }
)

#: What closes each mission. Until the Outbound tab lands these are the
#: defaults; ``CardObjective.success`` overrides them per published card, which
#: is the point of authoring missions rather than hardcoding them.
SUCCESS_BY_OBJECTIVE: dict[str, frozenset[str]] = {
    "pre_due_reminder": frozenset({"ptp_captured", "paid_in_call"}),
    "bounce_cure": frozenset({"ptp_captured", "paid_in_call", "part_payment_agreed"}),
    "dpd_reminder": frozenset({"ptp_captured", "paid_in_call", "part_payment_agreed", "plan_agreed"}),
    "broken_ptp_chase": frozenset({"ptp_recommitted", "paid_in_call", "part_payment_agreed"}),
    "hardship_intake": frozenset({"hardship_declared", "plan_agreed"}),
    "mandate_reregistration": frozenset({"plan_agreed", "paid_in_call"}),
    "document_chase": frozenset({"no_resolution"}),
    "callback_honour": frozenset({"ptp_captured", "paid_in_call", "plan_agreed"}),
    "manual_outbound": frozenset({"ptp_captured", "paid_in_call"}),
}

#: Attempt state → connection axis. ``canceled`` is our own hang-up before the
#: far end answered; from the borrower's side that is indistinguishable from a
#: ring-out, and inventing a tenth connection value for it would split a metric
#: nobody wants split. ``provider_status`` keeps the distinction for anyone who
#: needs it.
_CONNECTION_BY_STATE: dict[str, str] = {
    outbound.STATE_SUPPRESSED: "suppressed",
    outbound.STATE_NO_ANSWER: "no_answer",
    outbound.STATE_CANCELED: "no_answer",
    outbound.STATE_BUSY: "busy",
    outbound.STATE_REJECTED: "rejected",
    outbound.STATE_FAILED: "failed",
    outbound.STATE_INVALID_NUMBER: "invalid_number",
    outbound.STATE_VOICEMAIL_LEFT: "voicemail",
    outbound.STATE_VOICEMAIL_SKIPPED: "voicemail",
}

#: Precedence when several signals are true at once. A payment beats a promise
#: beats a dispute beats silence — the same ordering ``followthrough.py`` already
#: uses for attribution, restated here so the two cannot disagree about which
#: outcome a call had.
_BUSINESS_PRECEDENCE: tuple[str, ...] = (
    "paid_in_call",
    "ptp_recommitted",
    "ptp_captured",
    "part_payment_agreed",
    "plan_agreed",
    "deceased",
    "wrong_number",
    "opt_out_requested",
    "dispute_raised",
    "hardship_declared",
    "callback_requested",
    "escalated",
    "refused",
    "abandoned_by_customer",
    "no_resolution",
)

_TRANSCRIPT_TURNS = 60


def grace_seconds() -> int:
    """How long after a call ends before it is closed.

    ``CrmSink`` drains transcript, sentiment and per-turn analysis on a
    background queue, so a call closed the instant its media stopped would be
    summarised from a conversation missing its last few turns — and the summary
    would look just as confident.
    """
    return max(0, env_int("CLOSER_GRACE_SECONDS", 45))


def llm_enabled() -> bool:
    """Model enrichment on top of the deterministic outcome.

    Off leaves a complete, valid row: every field the model fills has a
    deterministic fallback, which is the property that makes this safe to run
    against a saturated or missing Azure deployment.
    """
    return (os.getenv("CLOSER_LLM_ENABLED") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oid() -> str:
    return f"CO-{uuid.uuid4().hex[:12].upper()}"


def _obligation_id() -> str:
    return f"OB-{uuid.uuid4().hex[:12].upper()}"


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------


def claim_one(conn: Any) -> dict[str, Any] | None:
    """One finished attempt that still owes an outcome, locked for this worker."""
    row = conn.execute(
        text(
            """
            SELECT * FROM call_attempts
            WHERE closed_at IS NULL
              AND state <> 'reserved'
              AND (
                    state = 'suppressed'
                 OR (ended_at IS NOT NULL
                     AND ended_at <= now() - make_interval(secs => :grace))
              )
            ORDER BY COALESCE(ended_at, reserved_at) ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
            """
        ),
        {"grace": grace_seconds()},
    ).mappings().first()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Deterministic evidence
# ---------------------------------------------------------------------------


def _tool_calls(conn: Any, interaction_id: str | None) -> list[dict[str, Any]]:
    if not interaction_id:
        return []
    rows = conn.execute(
        text(
            """
            SELECT tool_name, args, result_ok, created_at
            FROM bot_tool_calls
            WHERE interaction_id = :ix
            ORDER BY created_at ASC
            """
        ),
        {"ix": interaction_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _promise(conn: Any, interaction_id: str | None) -> dict[str, Any] | None:
    if not interaction_id:
        return None
    row = conn.execute(
        text(
            """
            SELECT id, amount, promised_at, status
            FROM promises WHERE interaction_id = :ix
            ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"ix": interaction_id},
    ).mappings().first()
    return dict(row) if row else None


def _dispute(conn: Any, interaction_id: str | None) -> str | None:
    if not interaction_id:
        return None
    return conn.execute(
        text("SELECT id FROM disputes WHERE interaction_id = :ix ORDER BY created_at DESC LIMIT 1"),
        {"ix": interaction_id},
    ).scalar()


def _handoff(conn: Any, interaction_id: str | None) -> bool:
    if not interaction_id:
        return False
    return bool(
        conn.execute(
            text("SELECT 1 FROM interaction_handoffs WHERE interaction_id = :ix LIMIT 1"),
            {"ix": interaction_id},
        ).scalar()
    )


def _flags(conn: Any, interaction_id: str | None) -> list[dict[str, Any]]:
    if not interaction_id:
        return []
    rows = conn.execute(
        text(
            "SELECT flag, severity FROM interaction_flags WHERE interaction_id = :ix "
            "ORDER BY created_at ASC"
        ),
        {"ix": interaction_id},
    ).mappings().all()
    return [{"flag": r["flag"], "severity": r["severity"]} for r in rows]


def _sentiment_bounds(conn: Any, interaction_id: str | None) -> tuple[float | None, float | None]:
    if not interaction_id:
        return None, None
    rows = conn.execute(
        text(
            "SELECT score FROM interaction_sentiment WHERE interaction_id = :ix "
            "ORDER BY at_sec ASC"
        ),
        {"ix": interaction_id},
    ).scalars().all()
    if not rows:
        return None, None
    return float(rows[0]), float(rows[-1])


def _interaction(conn: Any, interaction_id: str | None) -> dict[str, Any] | None:
    if not interaction_id:
        return None
    row = conn.execute(
        text(
            """
            SELECT id, customer_id, primary_intent, query_resolved, upsell_presented,
                   ptp_captured, duration_sec, avg_sentiment, summary
            FROM interactions WHERE id = :ix
            """
        ),
        {"ix": interaction_id},
    ).mappings().first()
    return dict(row) if row else None


def _optout_during(conn: Any, customer_id: str, since: Any) -> bool:
    """Did the borrower opt out while we had them on the phone?

    Read from ``optout_events`` rather than inferred from words, because an
    opt-out that is only in a transcript is an opt-out nothing enforces.
    """
    if since is None:
        return False
    # optout_events hangs off consent_records, not off customers directly —
    # one consent row per borrower, many opt-out events against it.
    return bool(
        conn.execute(
            text(
                """
                SELECT 1
                FROM optout_events e
                JOIN consent_records r ON r.id = e.consent_id
                WHERE r.customer_id = :cid AND e.occurred_at >= :since
                LIMIT 1
                """
            ),
            {"cid": customer_id, "since": since},
        ).scalar()
    )


# ---------------------------------------------------------------------------
# Outcome assembly
# ---------------------------------------------------------------------------


def _connection_for(attempt: dict[str, Any], interaction: dict[str, Any] | None) -> str:
    state = str(attempt.get("state") or "")
    mapped = _CONNECTION_BY_STATE.get(state)
    if mapped:
        return mapped
    # Everything left connected in some form. Order matters: a machine that
    # answered is a voicemail whatever else happened, and a confirmed wrong
    # party is a wrong party even though a human spoke.
    if attempt.get("right_party") is False:
        return "wrong_party"
    if attempt.get("answered_by") == "machine":
        return "voicemail"
    if attempt.get("answered_by") == "ivr" and interaction is None:
        return "ivr_only"
    if attempt.get("answered_at") is None and interaction is None:
        return "no_answer"
    return "connected"


def _deterministic_business(
    *,
    attempt: dict[str, Any],
    interaction: dict[str, Any] | None,
    promise: dict[str, Any] | None,
    dispute_id: str | None,
    tools: list[dict[str, Any]],
    handoff: bool,
    opted_out: bool,
) -> set[str]:
    """Outcomes proved by a row somewhere. The model cannot remove these."""
    found: set[str] = set()
    names = {str(t["tool_name"]) for t in tools if t.get("result_ok")}
    objective = str(attempt.get("objective") or "")

    if promise:
        # The same tool writes both; which one it is depends on the mission. A
        # broken-PTP chase that gets a promise has re-committed one, and
        # reporting that as a fresh capture would overstate acquisition and
        # understate the recovery of a broken case.
        found.add("ptp_recommitted" if objective == "broken_ptp_chase" else "ptp_captured")
    if dispute_id or "flag_dispute" in names:
        found.add("dispute_raised")
    if opted_out:
        found.add("opt_out_requested")
    if "request_callback" in names:
        found.add("callback_requested")
    if handoff or "escalate_to_human" in names:
        found.add("escalated")
    if interaction and str(interaction.get("primary_intent") or "") == "hardship":
        found.add("hardship_declared")
    for call in tools:
        if str(call.get("tool_name")) != "capture_nonpayment_reason":
            continue
        args = _args(call)
        if str(args.get("reason") or "") in {"income_loss", "medical"}:
            found.add("hardship_declared")
        if str(args.get("reason") or "") == "unwilling":
            found.add("refused")
        if str(args.get("reason") or "") == "disputes_amount":
            found.add("dispute_raised")
    return found


def _args(call: dict[str, Any]) -> dict[str, Any]:
    raw = call.get("args")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _nonpayment_reason(tools: list[dict[str, Any]]) -> str | None:
    for call in reversed(tools):
        if str(call.get("tool_name")) != "capture_nonpayment_reason":
            continue
        reason = str(_args(call).get("reason") or "")
        if reason in NONPAYMENT_REASONS:
            return reason
    return None


def _commitment(promise: dict[str, Any] | None, tools: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Amount and date from the row; confidence and verbatim from the tool call.

    A PTP today is amount plus date. Whether the borrower proposed the number or
    merely agreed to ours is not recorded anywhere, and broken-PTP rates differ
    sharply between the two — so the fields the tool was given are kept even
    though the promises table has nowhere to put them.
    """
    if not promise:
        return None
    out: dict[str, Any] = {
        "promiseId": promise.get("id"),
        "amountInr": float(promise["amount"]) if promise.get("amount") is not None else None,
        "date": promise["promised_at"].isoformat() if promise.get("promised_at") else None,
        "status": promise.get("status"),
        "confidence": None,
        "verbatim": None,
        "whoseNumber": None,
    }
    for call in tools:
        if str(call.get("tool_name")) != "create_promise_to_pay":
            continue
        args = _args(call)
        out["confidence"] = args.get("confidence")
        out["verbatim"] = args.get("verbatim")
        out["whoseNumber"] = args.get("whoseNumber") or args.get("whose_number")
    return out


def _template_summary(
    *, connection: str, business: str | None, objective: str, reason: str | None, turns: int | None
) -> str:
    bits = [f"{objective or 'outbound'} · {connection}"]
    if business:
        bits.append(business.replace("_", " "))
    if reason:
        bits.append(f"reason: {reason.replace('_', ' ')}")
    if turns:
        bits.append(f"{turns}s on the call")
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# The number fence
# ---------------------------------------------------------------------------

_NUM = re.compile(r"\d+")


def _numbers_in(value: str) -> set[str]:
    return set(_NUM.findall(value or ""))


def numbers_are_grounded(candidate: str, allowed: set[str]) -> bool:
    """Reject a summary containing a figure the model was not given.

    The same fence ``rerank.py`` puts on rationales, for the same reason: an
    LLM that invents a rupee amount in a collections record has fabricated
    evidence, and it will look exactly as authoritative as the true ones. Digits
    inside a longer token still count — "4,200" is checked as 4 and 200, so the
    allowed set is built from the same tokenisation.
    """
    return _numbers_in(candidate) <= allowed


# ---------------------------------------------------------------------------
# LLM enrichment
# ---------------------------------------------------------------------------

_SYSTEM = """You are closing out one completed collections call for an Indian retail
bank. You are given the transcript and the facts the system already recorded.

Return a strict JSON object with exactly these keys:
  "business"   — one of the allowed outcome codes, or null if none applies
  "reason"     — one of the allowed non-payment reason codes, or null
  "objections" — array of short lowercase snake_case objection codes the borrower
                 raised (e.g. "amount_disputed", "needs_time", "already_paid").
                 Empty array if none.
  "unanswered" — array of questions the borrower asked that the agent did not
                 answer. Verbatim, short, no account numbers. Empty if none.
  "summary"    — two sentences, plain English, describing what happened and what
                 was agreed.

Rules that matter:
- Use ONLY codes from the lists given. Never invent one.
- The summary must contain NO numbers at all — no amounts, no dates, no digits.
  Refer to "the instalment", "the agreed date". A summary with a figure in it is
  rejected and thrown away.
- Never quote account numbers, phone digits or amounts anywhere.
- Calls may be in English, Hindi or a mix. Report what was communicated.
- If the borrower did not say why they have not paid, "reason" is null. Do not
  guess a reason from the account state."""


def _enrich(
    *,
    interaction_id: str,
    objective: str,
    deterministic: set[str],
) -> dict[str, Any] | None:
    """Ask the model for what only the conversation can say. None on any doubt."""
    import azure_openai
    import transcript_view

    transcript = transcript_view.fenced_transcript(interaction_id, limit=_TRANSCRIPT_TURNS)
    if not transcript:
        return None

    known = ", ".join(sorted(deterministic)) or "none recorded"
    prompt = (
        f"{_SYSTEM}\n\n"
        f"Mission: {objective}\n"
        f"Allowed outcome codes: {', '.join(sorted(BUSINESS_OUTCOMES))}\n"
        f"Allowed reason codes: {', '.join(sorted(NONPAYMENT_REASONS))}\n"
        f"Already proved by system records (do not contradict): {known}"
    )
    try:
        result = azure_openai.chat_with_tools(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": transcript},
            ],
            tools=None,
            tool_choice=None,
            temperature=0.0,
            max_completion_tokens=700,
            profile=azure_openai.PROFILE_ANALYSIS,
        )
    except Exception:
        # Including AzureBusyError: a saturated analysis deployment must not
        # stall the queue, and the deterministic outcome is already complete.
        logger.debug("closer enrichment failed ix=%s", interaction_id, exc_info=True)
        return None

    content = str(result.get("content") or "").strip()
    if not content:
        return None
    # Models wrap JSON in fences more often than they should.
    content = re.sub(r"^```(?:json)?|```$", "", content, flags=re.MULTILINE).strip()
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        logger.debug("closer enrichment returned non-JSON ix=%s", interaction_id)
        return None
    if not isinstance(payload, dict):
        return None
    payload["_model"] = result.get("model")
    return payload


def _clean_list(value: Any, *, limit: int = 6, max_len: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value[:limit]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:max_len])
    return out


# ---------------------------------------------------------------------------
# Post-call actions
# ---------------------------------------------------------------------------


def _record_obligations(
    conn: Any, *, attempt: dict[str, Any], tools: list[dict[str, Any]]
) -> list[str]:
    """Turn promises *we* made into rows somebody has to honour.

    Only tool-proved obligations are written. An obligation inferred from
    transcript prose would be a commitment the institution did not verifiably
    make, and a missed-obligation metric built on guesses is worse than none.
    """
    applied: list[str] = []
    for call in tools:
        name = str(call.get("tool_name"))
        args = _args(call)
        kind: str | None = None
        due: Any = None
        detail: dict[str, Any] = {}
        if name == "request_callback" and call.get("result_ok"):
            kind = "callback"
            due = args.get("preferredAt") or args.get("preferred_at") or args.get("at")
            detail = {"reason": args.get("reason"), "toleranceMinutes": args.get("toleranceMinutes")}
        elif name == "request_documents" and call.get("result_ok"):
            kind = "document"
            detail = {"document": args.get("document"), "delivery": args.get("delivery")}
        if not kind:
            continue
        due_at = _parse_dt(due) or (attempt.get("ended_at") or _now())
        obligation_id = _obligation_id()
        conn.execute(
            text(
                """
                INSERT INTO agent_obligations (
                  id, tenant_id, customer_id, interaction_id, attempt_id,
                  kind, due_at, detail, state, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :customer, :ix, :attempt,
                  :kind, :due_at, CAST(:detail AS jsonb), 'open', now(), now()
                )
                """
            ),
            {
                "id": obligation_id,
                "tenant": attempt["tenant_id"],
                "customer": attempt["customer_id"],
                "ix": attempt.get("interaction_id"),
                "attempt": attempt["id"],
                "kind": kind,
                "due_at": due_at,
                "detail": json.dumps(detail, default=str),
            },
        )
        applied.append(f"obligation:{kind}:{obligation_id}")
    return applied


def _post_call_policy(bot_id: Any) -> Any:
    """This card's ``CardPostCall``, or the schema defaults.

    Defaults rather than None on every failure path: the fallback for "we could
    not read the card" has to be the behaviour of a card that says nothing,
    which is written follow-up on, obligations on, QA always. Failing closed
    here would silently stop sending borrowers the record of what they agreed —
    a change nobody authored, caused by a lookup error.
    """
    from agent_core.cards.schema import CardPostCall

    try:
        import mission as mission_mod

        card = mission_mod.card_for_bot(bot_id)
        outbound_cfg = getattr(card, "outbound", None) if card is not None else None
        policy = getattr(outbound_cfg, "post_call", None)
        return policy if policy is not None else CardPostCall()
    except Exception:
        logger.debug("post-call policy lookup failed for bot %s", bot_id, exc_info=True)
        return CardPostCall()


def _apply_card_rules(
    conn: Any,
    attempt: dict[str, Any],
    business: str | None,
    reason: str | None,
    promise: dict[str, Any] | None,
    tools: list[dict[str, Any]],
    post_call: Any,
) -> list[str]:
    """Run ``CardPostCall.on_outcome`` for this outcome. Never raises."""
    if not business:
        return []
    try:
        import post_call_actions

        rules = getattr(post_call, "on_outcome", None) or []
        if not rules:
            return []
        return post_call_actions.apply(
            conn,
            attempt=attempt,
            business=business,
            nonpayment_reason=reason,
            commitment=_commitment(promise, tools) if promise else None,
            rules=rules,
            obligation_due_at=_requested_callback_at(tools),
            # The switch above the rules, not a rule of its own. A tenant that
            # must not send written records turns it off once rather than
            # editing every rule that happens to confirm something.
            written_followup=bool(getattr(post_call, "written_followup", True)),
        )
    except Exception:
        logger.exception("post-call rules failed for attempt %s", attempt["id"])
        return ["card_rules:failed"]


def _requested_callback_at(tools: list[dict[str, Any]]) -> datetime | None:
    """When the borrower asked to be called back, if they did.

    ``schedule_mission`` needs the time *they* named — scheduling a callback for
    tomorrow morning when they said Tuesday evening is not honouring it.
    """
    for call in tools:
        if str(call.get("tool_name")) != "request_callback":
            continue
        args = _args(call)
        return _parse_dt(args.get("preferredAt") or args.get("preferred_at") or args.get("at"))
    return None


def _advance_cadence(
    conn: Any, attempt: dict[str, Any], connection: str, business: str | None
) -> list[str]:
    """Hand the outcome to the retry ladder. Never raises.

    The ladder is opened here rather than at dial time, and lazily: a case only
    needs one the moment it has an outcome to react to, and creating one for
    every manual "call now" would fill the table with ladders nobody is walking.

    Bookkeeping, so a failure is logged and swallowed. A cadence that cannot be
    advanced means a retry that does not happen — bad, and much better than an
    outcome that fails to be written because the retry logic threw.
    """
    import cadence

    if not cadence.enabled():
        return []
    case_ref = cadence._case_ref(attempt)
    if not case_ref:
        # A one-off dial with no decision and no campaign behind it. Somebody
        # pressed a button; that is not a ladder.
        return []
    try:
        import mission as mission_mod

        objective = str(attempt.get("objective") or "")
        card = mission_mod.card_for_bot(attempt.get("bot_id"))
        card_outbound = getattr(card, "outbound", None) if card is not None else None
        spec = card_outbound.cadence_for(objective) if card_outbound else None
        cadence.ensure_case(
            conn,
            tenant_id=attempt["tenant_id"],
            customer_id=attempt["customer_id"],
            objective=objective,
            case_ref=case_ref,
            cadence=getattr(spec, "name", "default"),
            max_attempts=getattr(spec, "max_attempts", 3),
            campaign_run_id=attempt.get("campaign_run_id"),
            attempts=int(attempt.get("attempt_no") or 1),
        )
        state = cadence.on_outcome(
            conn,
            attempt=attempt,
            connection=connection,
            business=business,
            card_outbound=card_outbound,
        )
        return [f"cadence:{state}"]
    except Exception:
        logger.exception("cadence advance failed for attempt %s", attempt["id"])
        return []


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _retire_phone_slot(conn: Any, attempt: dict[str, Any]) -> list[str]:
    """A number the carrier says is not a number stops being dialled.

    The cheapest form of skip-tracing there is, and until now it did not exist:
    an invalid number was retried on the next tick exactly like a busy one. The
    slot is recorded on the attempt context rather than mutating ``customers``,
    because deciding a borrower's phone is dead is a data-quality change that
    should be reviewed, not applied by a worker at 2am.
    """
    if str(attempt.get("state")) != outbound.STATE_INVALID_NUMBER:
        return []
    conn.execute(
        text(
            """
            UPDATE call_attempts
            SET context = context || CAST(:patch AS jsonb), updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": attempt["id"], "patch": json.dumps({"phoneSlotDead": True})},
    )
    return [f"phone_slot_flagged:{attempt.get('phone_slot')}"]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def gather(conn: Any, attempt: dict[str, Any]) -> dict[str, Any]:
    """Everything the outcome can be read off a row. No model, no network.

    Separated from the write so the LLM call in :func:`process_one` happens
    between two short transactions rather than inside one long one — holding a
    pooled connection and a row lock across several seconds of analysis latency
    is the pattern ``qa_autoscore`` is explicit about avoiding.
    """
    interaction_id = attempt.get("interaction_id")
    interaction = _interaction(conn, interaction_id)
    tools = _tool_calls(conn, interaction_id)
    promise = _promise(conn, interaction_id)
    dispute_id = _dispute(conn, interaction_id)
    handoff = _handoff(conn, interaction_id)
    flags = _flags(conn, interaction_id)
    s_start, s_end = _sentiment_bounds(conn, interaction_id)
    opted_out = _optout_during(conn, attempt["customer_id"], attempt.get("placed_at"))

    connection = _connection_for(attempt, interaction)
    deterministic = (
        _deterministic_business(
            attempt=attempt,
            interaction=interaction,
            promise=promise,
            dispute_id=dispute_id,
            tools=tools,
            handoff=handoff,
            opted_out=opted_out,
        )
        if connection == "connected"
        else set()
    )
    if connection == "wrong_party":
        deterministic.add("wrong_number")

    return {
        "interaction_id": interaction_id,
        "interaction": interaction,
        "tools": tools,
        "promise": promise,
        "handoff": handoff,
        "flags": flags,
        "sentiment": (s_start, s_end),
        "connection": connection,
        "deterministic": deterministic,
        "reason": _nonpayment_reason(tools),
    }


def enrich_for(attempt: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any] | None:
    """The model's contribution, or None. Safe to call with no transaction open."""
    interaction_id = evidence.get("interaction_id")
    if evidence["connection"] != "connected" or not interaction_id or not llm_enabled():
        return None
    return _enrich(
        interaction_id=str(interaction_id),
        objective=str(attempt.get("objective") or ""),
        deterministic=evidence["deterministic"],
    )


_UNSET = object()


def close_one(
    conn: Any,
    attempt: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
    enrichment: Any = _UNSET,
) -> dict[str, Any]:
    """Build and persist the outcome for one attempt. Returns the row written.

    Pass ``evidence`` and ``enrichment`` to keep the model off this
    transaction; omit them and it does the whole job inline, which is what a
    test or a one-off backfill wants.
    """
    if evidence is None:
        evidence = gather(conn, attempt)
    interaction_id = evidence["interaction_id"]
    tools = evidence["tools"]
    promise = evidence["promise"]
    handoff = evidence["handoff"]
    flags = evidence["flags"]
    s_start, s_end = evidence["sentiment"]
    connection = evidence["connection"]
    deterministic = set(evidence["deterministic"])
    reason = evidence["reason"]
    objective = str(attempt.get("objective") or "")

    objections: list[str] = []
    unanswered: list[str] = []
    summary: str | None = None
    summary_source = "template"
    summary_model: str | None = None

    if enrichment is _UNSET:
        enrichment = enrich_for(attempt, evidence)
    if enrichment:
        candidate = str(enrichment.get("business") or "")
        # The model may *add* an outcome the tools did not prove; it may never
        # remove one. A refusal the agent recorded is a fact, and a model that
        # softens it is editing the record.
        if candidate in BUSINESS_OUTCOMES:
            deterministic.add(candidate)
        model_reason = str(enrichment.get("reason") or "")
        if reason is None and model_reason in NONPAYMENT_REASONS:
            reason = model_reason
        objections = _clean_list(enrichment.get("objections"), limit=6, max_len=64)
        unanswered = _clean_list(enrichment.get("unanswered"), limit=5, max_len=200)
        proposed = str(enrichment.get("summary") or "").strip()
        # The fence: the summary was told to contain no digits at all, so the
        # allowed set is empty and any number in it fails.
        if proposed and numbers_are_grounded(proposed, set()):
            summary = proposed[:2000]
            summary_source = "llm"
            summary_model = enrichment.get("_model")
        elif proposed:
            logger.info(
                "closer: rejected ungrounded summary for %s (contained digits)",
                interaction_id,
            )

    business = next((b for b in _BUSINESS_PRECEDENCE if b in deterministic), None)
    if business is None and connection == "connected":
        business = "no_resolution"

    success = SUCCESS_BY_OBJECTIVE.get(objective, frozenset({"ptp_captured", "paid_in_call"}))
    objective_met = bool(business and business in success)

    escalation = "none"
    if handoff:
        escalation = "transferred"
    elif "escalated" in deterministic:
        escalation = "requested"
    elif any(f["flag"] == "auto-escalate" for f in flags):
        escalation = "auto"

    if summary is None:
        summary = _template_summary(
            connection=connection,
            business=business,
            objective=objective,
            reason=reason,
            turns=int(attempt["talk_sec"]) if attempt.get("talk_sec") else None,
        )

    # The card's after-call policy. `on_outcome` has been honoured since G-OB6
    # landed, but the three switches beside it — written_followup, obligations,
    # qa — were validated, versioned, publishable and read by nothing, which is
    # the failure this module's own docstring calls worse than an unimplemented
    # feature: the operator gets a diff in the change log and no change in
    # behaviour.
    post_call = _post_call_policy(attempt.get("bot_id"))

    actions = (
        _record_obligations(conn, attempt=attempt, tools=tools)
        if post_call.obligations
        else ["obligations:off_by_card"]
    )
    actions.extend(_retire_phone_slot(conn, attempt))
    # The card's authored rules. Until now `CardPostCall.on_outcome` was a
    # validated, versioned, publishable list that did nothing: G-OB6 checked
    # every verb was real and this function ignored the whole thing. An operator
    # could edit a rule, publish a version, see the diff in the change log, and
    # watch the behaviour not move.
    actions.extend(
        _apply_card_rules(conn, attempt, business, reason, promise, tools, post_call)
    )
    actions.extend(_advance_cadence(conn, attempt, connection, business))
    try:
        import campaigns

        campaigns.on_attempt_closed(conn, attempt, business)
    except Exception:
        logger.exception("campaign target close failed for %s", attempt["id"])

    outcome_id = _oid()
    conn.execute(
        text(
            """
            INSERT INTO call_outcomes (
              id, attempt_id, tenant_id, customer_id, interaction_id, mission_id,
              decision_id, objective, connection, business, objective_met,
              nonpayment_reason, commitment, objections, unanswered_questions,
              sentiment_start, sentiment_end, escalation, compliance_flags,
              next_action_hint, summary, summary_source, summary_model,
              actions_applied, created_at
            ) VALUES (
              :id, :attempt_id, :tenant, :customer, :ix, :mission,
              :decision, :objective, :connection, :business, :met,
              :reason, CAST(:commitment AS jsonb), CAST(:objections AS jsonb),
              CAST(:unanswered AS jsonb), :s_start, :s_end, :escalation,
              CAST(:flags AS jsonb), :hint, :summary, :summary_source, :summary_model,
              CAST(:actions AS jsonb), now()
            )
            ON CONFLICT (attempt_id) DO NOTHING
            """
        ),
        {
            "id": outcome_id,
            "attempt_id": attempt["id"],
            "tenant": attempt["tenant_id"],
            "customer": attempt["customer_id"],
            "ix": interaction_id,
            "mission": attempt.get("mission_id"),
            "decision": attempt.get("decision_id"),
            "objective": objective or None,
            "connection": connection,
            "business": business,
            "met": objective_met,
            "reason": reason,
            "commitment": json.dumps(_commitment(promise, tools), default=str)
            if promise
            else None,
            "objections": json.dumps(objections),
            "unanswered": json.dumps(unanswered),
            "s_start": s_start,
            "s_end": s_end,
            "escalation": escalation,
            "flags": json.dumps(flags),
            "hint": _next_action_hint(connection, business, reason),
            "summary": summary,
            "summary_source": summary_source,
            "summary_model": summary_model,
            "actions": json.dumps(actions),
        },
    )
    conn.execute(
        text("UPDATE call_attempts SET closed_at = now(), updated_at = now() WHERE id = :id"),
        {"id": attempt["id"]},
    )
    return {
        "outcomeId": outcome_id,
        "attemptId": attempt["id"],
        "connection": connection,
        "business": business,
        "objectiveMet": objective_met,
        "nonpaymentReason": reason,
        "summarySource": summary_source,
        "actions": actions,
    }


def _next_action_hint(connection: str, business: str | None, reason: str | None) -> str | None:
    """Advisory to the engine. Never binding — the ladder decides, not the call.

    ``forgot`` is the one that pays for this whole field: it says the call we
    just made was worth less than an SMS, and it is the label an uplift model
    needs to learn not to dial the next borrower like this one.
    """
    if business in {"opt_out_requested", "deceased", "wrong_number"}:
        return "stop_contact"
    if business == "dispute_raised":
        return "hold_until_dispute_resolved"
    if reason in {"income_loss", "medical"}:
        return "hardship_review"
    if reason == "salary_timing":
        return "emi_date_change"
    if reason == "mandate_broken":
        return "mandate_reregistration"
    if reason == "forgot":
        return "cheapest_digital_next_time"
    if connection in {"no_answer", "busy"}:
        return "retry_different_hour"
    if connection == "invalid_number":
        return "try_alternate_number"
    return None


def process_one(engine: Engine) -> bool:
    """Close one attempt. Returns True if one was claimed at all.

    Three phases, and the split is the point: claim and read inside a short
    transaction, run the model with **no** transaction open, then write. An LLM
    call inside ``engine.begin()`` holds a pooled connection and a row lock for
    the whole of its latency, which is exactly what ``qa_autoscore`` documents
    as the thing not to do.
    """
    with engine.begin() as conn:
        attempt = claim_one(conn)
        if attempt is None:
            return False
        try:
            evidence = gather(conn, attempt)
        except Exception:
            logger.exception("closer could not read attempt %s", attempt["id"])
            _abandon(conn, attempt["id"])
            return True
        # Claimed means owned. Stamping now is what keeps a second worker off
        # this attempt while the model runs outside the transaction; the write
        # below is idempotent on (attempt_id) either way.
        conn.execute(
            text("UPDATE call_attempts SET closed_at = now(), updated_at = now() WHERE id = :id"),
            {"id": attempt["id"]},
        )

    enrichment = None
    try:
        enrichment = enrich_for(attempt, evidence)
    except Exception:
        # Already swallowed inside _enrich; belt and braces, because a failure
        # here would lose an outcome that is otherwise fully determined.
        logger.debug("closer enrichment raised", exc_info=True)

    with engine.begin() as conn:
        try:
            result = close_one(conn, attempt, evidence=evidence, enrichment=enrichment)
        except Exception:
            logger.exception("closer failed for attempt %s", attempt["id"])
            # The attempt is already closed. Its state is still the record; the
            # missing outcome is visible as a gap rather than as an attempt that
            # retries forever and starves everything behind it.
            _abandon(conn, attempt["id"])
            return True
    logger.info(
        "closed attempt %s · %s/%s · met=%s",
        result["attemptId"],
        result["connection"],
        result["business"],
        result["objectiveMet"],
    )
    return True


def _abandon(conn: Any, attempt_id: str) -> None:
    conn.execute(
        text(
            "UPDATE call_attempts SET closed_at = COALESCE(closed_at, now()), "
            "provider_error = COALESCE(provider_error, 'closer_failed'), "
            "updated_at = now() WHERE id = :id"
        ),
        {"id": attempt_id},
    )
