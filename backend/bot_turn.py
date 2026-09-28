"""What a WhatsApp bot turn is, and the steps every engine takes around it.

Shared by both text engines -- Voice Studio (``whatsapp_studio``) and the
legacy runtime (``bot_runtime``) -- and by the job runner (``bot_jobs``):
the turn record, outbound idempotency (never send twice for one job), the
inbound message's WhatsApp id, and the hand-off to a person.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.engine import Engine

import bot_conversation
import bot_jobs
import bot_turn_write
import db
import whatsapp as wa
from agent_core.sentiment import sentiment_label

logger = logging.getLogger(__name__)

_ESCALATE_NOTICE = "I'm connecting you to a colleague who can take this from here."


@dataclass
class Turn:
    """One WhatsApp turn as it moves through the phases below.

    What the job named, what the thread says, what the classifier found, what
    the model answered and what was sent. Filled in phase order by
    ``_prepare_turn`` / ``_understand_turn`` / ``_run_model`` / ``_tool_loop`` /
    ``_send_reply`` / ``_persist_turn``; a phase that ends the turn returns
    ``None`` or ``False`` and nothing after it runs. The bodies are what
    ``_handle_turn`` was, pinned by ``tests/test_text_turn_snapshot.py``.
    """

    job: dict[str, Any]
    job_id: str
    conversation_id: str
    reuse_outbound_id: str | None
    reuse_body: str | None
    conv: dict[str, Any]
    customer_text: str
    latest_msg_id: str | None
    state: dict[str, Any]
    turn_count: int
    bundle: dict[str, Any]
    guardrails: Any
    temperature: float
    max_completion_tokens: int
    # _understand_turn
    turn_started_at: datetime | None = None
    full_history: list[dict[str, Any]] = field(default_factory=list)
    turn_run_up: list[tuple[str, str]] = field(default_factory=list)
    understanding: Any = None
    intent: str = ""
    intent_scores: dict[str, float] | None = None
    sentiment: float = 0.0
    product_hint: str | None = None
    already_engaged: bool = False
    session_intent: str = ""
    # _run_model / _tool_loop
    final_text: str = ""
    flow_walker: Any = None
    # _send_reply
    fresh: dict[str, Any] = field(default_factory=dict)
    msg_id: str | None = None


def reuse_prior_outbound(engine: Engine, job: dict[str, Any]) -> tuple[str | None, str | None] | None:
    """Outbound idempotency: never Graph-send twice for the same job.

    Returns ``(reuse_outbound_id, reuse_body)`` -- both ``None`` for a fresh
    turn, the reserved row and its body when a prior attempt failed before
    reaching Meta -- or ``None`` when the job was closed here (already sent,
    stuck in ``sending``, or a prior definite/ambiguous send error)."""
    job_id = job["id"]

    existing = bot_conversation.existing_outbound(engine, job_id)
    if existing and (existing.get("delivery_status") or "") == "sent":
        with engine.begin() as conn:
            bot_jobs.mark_succeeded(conn, job_id, outbound_message_id=existing["id"])
        logger.info("bot_turn skip already-sent job=%s message=%s", job_id, existing["id"])
        return None

    reuse_outbound_id: str | None = None
    reuse_body: str | None = None
    prior_status = (existing.get("delivery_status") or "") if existing else ""
    if existing and prior_status == "sending":
        # Ambiguous: a prior attempt POSTed to Meta but crashed before recording
        # the outcome. WhatsApp Cloud API has no client idempotency key, so
        # re-sending could duplicate a message the customer already received.
        # Fail safe — do not auto-resend; cancel for manual reconciliation.
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "outbound_sending_unconfirmed")
        logger.warning(
            "bot_turn outbound stuck 'sending' — not auto-resending (possible duplicate) "
            "job=%s message=%s",
            job_id,
            existing["id"],
        )
        return None
    if existing and prior_status == "failed":
        prior_err = str(job.get("error") or "")
        if wa.is_definite_client_error(prior_err):
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(conn, job_id, f"outbound_client_error:{prior_err[:500]}")
            logger.warning(
                "bot_turn outbound prior client error — not re-POSTing job=%s message=%s err=%s",
                job_id,
                existing["id"],
                prior_err[:200],
            )
            return None
        if wa.is_ambiguous_transport_error(prior_err):
            # Read timeout / 429 / 5xx: Meta may already have accepted and
            # delivered the message. Cloud API has no client idempotency key, so
            # a retry can double-send to the customer. Park for reconciliation.
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(
                    conn, job_id, f"outbound_ambiguous_transport:{prior_err[:500]}"
                )
            logger.warning(
                "bot_turn outbound prior ambiguous transport error — not re-POSTing "
                "job=%s message=%s err=%s",
                job_id,
                existing["id"],
                prior_err[:200],
            )
            return None
        # A failed send definitely never reached Meta (connection refused / DNS
        # / config) — safe to reuse the
        # reserved row (do not INSERT another; UNIQUE(bot_turn_job_id) would fail).
        reuse_outbound_id = existing["id"]
        reuse_body = (existing.get("body") or "").strip() or None
        logger.info(
            "bot_turn retrying outbound job=%s message=%s prior_status=%s",
            job_id,
            reuse_outbound_id,
            prior_status,
        )
    return reuse_outbound_id, reuse_body


def inbound_wamid(engine: Engine, message_id: str | None) -> str | None:
    """Meta wamid on the inbound customer row, if the ingest stored one."""
    if not message_id:
        return None
    from sqlalchemy import text as sql_text

    with engine.connect() as conn:
        row = conn.execute(
            sql_text("SELECT provider_ref FROM messages WHERE id = :id"),
            {"id": message_id},
        ).first()
    if not row:
        return None
    ref = (row[0] or "").strip()
    return ref or None


def notify_then_escalate(
    engine: Engine,
    t: Turn | None = None,
    *,
    reason: str,
    conversation_id: str | None = None,
    job_id: str | None = None,
    mark_job: bool = True,
) -> None:
    """Send the connecting-you line while status is still bot, then escalate.

    ``escalate_conversation_to_human`` cancels running jobs and flips
    ``needs_human``, so a send after it would fail the policy gate. Dead-letter
    callers pass conversation_id/job_id without a Turn.
    """
    cid = conversation_id or (t.conversation_id if t is not None else "")
    jid = job_id or (t.job_id if t is not None else None)
    if t is not None:
        t.final_text = _ESCALATE_NOTICE
        try:
            bot_turn_write.send_reply(engine, t)
        except Exception:
            logger.exception("escalate notice send failed conversation=%s", cid)
    elif cid and jid:
        try:
            bot_turn_write.send_notice(
                engine, conversation_id=cid, job_id=jid, body=_ESCALATE_NOTICE
            )
        except Exception:
            logger.exception("escalate notice send failed conversation=%s", cid)
    if cid:
        db.escalate_conversation_to_human(cid, reason=reason)
    if t is not None:
        t.state.update(
            {
                "turn_count": t.turn_count,
                "last_intent": t.session_intent or t.intent,
                "last_sentiment": sentiment_label(t.sentiment),
                "escalated": True,
                "escalate_reason": reason,
            }
        )
        bot_conversation.save_bot_state(engine, t.conversation_id, t.state)
        if mark_job:
            with engine.begin() as conn:
                bot_jobs.mark_succeeded(conn, t.job_id, outbound_message_id=t.msg_id)
    elif mark_job and jid:
        with engine.begin() as conn:
            bot_jobs.mark_succeeded(conn, jid)
