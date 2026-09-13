"""The conversation as the text runtime reads and writes it: the row, the
message history, the bot's state on it, the policy gate a turn must pass, and
the outbound row a reply becomes. Carved out of bot_runtime, which is the turn.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

import bot_jobs
import db
from agent_core.clock import utc_now

logger = logging.getLogger(__name__)


def load_conversation(engine: Engine, conversation_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT cv.id, cv.customer_id, cv.interaction_id, cv.status,
                       cv.assigned_user_id, cv.channel, cv.bot_state,
                       c.name AS customer_name, c.phone_primary, c.phone_alt,
                       c.dnd, c.preferred_window, c.language,
                       a.id AS account_id, a.outstanding, a.dpd, a.minimum_due,
                       p.name AS product,
                       (
                         SELECT MAX(COALESCE(m.sent_at, m.created_at))
                         FROM messages m
                         WHERE m.conversation_id = cv.id
                           AND m.sender = 'customer'
                           AND m.provider_ref IS NOT NULL
                       ) AS last_customer_at
                FROM conversations cv
                JOIN customers c ON c.id = cv.customer_id
                LEFT JOIN LATERAL (
                  SELECT * FROM accounts a
                  WHERE a.customer_id = c.id
                  ORDER BY CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END, a.created_at, a.id
                  LIMIT 1
                ) a ON true
                LEFT JOIN products p ON p.id = a.product_id
                WHERE cv.id = :id
                """
            ),
            {"id": conversation_id},
        ).mappings().first()


def whatsapp_opted_in(engine: Engine, customer_id: str) -> bool | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT cc.status
                FROM consent_records cr
                JOIN channel_consents cc ON cc.consent_id = cr.id
                WHERE cr.customer_id = :cid
                  AND lower(cc.channel) IN ('whatsapp', 'wa')
                ORDER BY cc.captured_at DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
    if row is None:
        return None
    return (row.get("status") or "").lower() == "opted_in"


def within_24h(last_customer_at: Any) -> bool:
    if last_customer_at is None:
        return False
    if isinstance(last_customer_at, str):
        last_customer_at = datetime.fromisoformat(last_customer_at.replace("Z", "+00:00"))
    if getattr(last_customer_at, "tzinfo", None) is None:
        last_customer_at = last_customer_at.replace(tzinfo=timezone.utc)
    age = utc_now() - last_customer_at.astimezone(timezone.utc)
    return age <= timedelta(hours=24)


def policy_gate(engine: Engine, conv: dict[str, Any]) -> str | None:
    """Return abort reason or None if send is allowed."""
    if not bot_jobs.bot_runtime_enabled():
        return "bot_runtime_disabled"
    if conv.get("status") != "bot" or conv.get("assigned_user_id"):
        return "takeover_or_not_bot"
    if conv.get("channel") != "whatsapp":
        return "unsupported_channel"
    if conv.get("dnd"):
        return "customer_dnd"
    opted = whatsapp_opted_in(engine, conv["customer_id"])
    if opted is False:
        return "whatsapp_opted_out"
    if not within_24h(conv.get("last_customer_at")):
        return "whatsapp_window_closed"
    try:
        import contact_policy

        with engine.begin() as conn:
            decision = contact_policy.admit(
                conn,
                customer_id=conv.get("customer_id"),
                channel="whatsapp",
                purpose="in_session",
                session_key=conv.get("id"),
                source="bot_reply",
                related_id=conv.get("id"),
                actor_kind="bot",
                endpoint=conv.get("phone_primary"),
            )
        if not decision.allowed:
            return decision.reason or "contact_policy"
    except Exception:
        logger.exception("contact_policy bot gate failed conversation=%s", conv.get("id"))
    return None


def latest_customer_text(engine: Engine, conversation_id: str) -> tuple[str, str | None]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, body FROM messages
                WHERE conversation_id = :cid AND sender = 'customer'
                ORDER BY COALESCE(sent_at, created_at) DESC, id DESC
                LIMIT 1
                """
            ),
            {"cid": conversation_id},
        ).mappings().first()
    if not row:
        return "", None
    return (row.get("body") or "").strip(), row.get("id")


def message_sent_at(conn: Any, message_id: str | None) -> datetime | None:
    """When a message actually landed — for stamping its transcript offset."""
    if not message_id:
        return None
    row = conn.execute(
        text("SELECT COALESCE(sent_at, created_at) AS at FROM messages WHERE id = :id"),
        {"id": message_id},
    ).first()
    return row[0] if row else None


def message_history(
    engine: Engine,
    conversation_id: str,
    limit: int,
    *,
    since: datetime | None = None,
) -> list[dict[str, str]]:
    with engine.connect() as conn:
        # Fetch only the newest `limit` rows (avoids loading the whole thread each
        # turn — O(n²) over a long WhatsApp conversation), then restore chrono order.
        if since is not None:
            rows = conn.execute(
                text(
                    """
                    SELECT sender, body FROM messages
                    WHERE conversation_id = :cid
                      AND sender IN ('customer', 'bot', 'agent')
                      AND COALESCE(sent_at, created_at) >= :since
                    ORDER BY COALESCE(sent_at, created_at) DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"cid": conversation_id, "limit": limit, "since": since},
            ).mappings().all()
        else:
            rows = conn.execute(
                text(
                    """
                    SELECT sender, body FROM messages
                    WHERE conversation_id = :cid
                      AND sender IN ('customer', 'bot', 'agent')
                    ORDER BY COALESCE(sent_at, created_at) DESC, id DESC
                    LIMIT :limit
                    """
                ),
                {"cid": conversation_id, "limit": limit},
            ).mappings().all()
    rows = list(reversed(rows))
    history: list[dict[str, str]] = []
    for r in rows:
        body = (r.get("body") or "").strip()
        if not body:
            continue
        sender = r.get("sender")
        if sender == "customer":
            history.append({"role": "user", "content": body})
        else:
            history.append({"role": "assistant", "content": body})
    return history[-(limit):]


def parse_dialog_reset_at(state: dict[str, Any]) -> datetime | None:
    raw = state.get("dialog_reset_at")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def history_already_disclosed_recording(history: list[dict[str, str]]) -> bool:
    """Has any bot turn in this thread stated the recording disclosure?

    The detector is ``agent_core.guardrails.mentions_recording_disclosure`` --
    the same one the guardrail evaluator and the Studio lint run. This used to
    be a fourth copy (a tuple of four substrings) that disagreed with the
    other three about what counts as a disclosure.
    """
    from agent_core.guardrails import mentions_recording_disclosure

    return any(
        turn.get("role") == "assistant" and mentions_recording_disclosure(turn.get("content") or "")
        for turn in history
    )


def bot_state(conv: dict[str, Any]) -> dict[str, Any]:
    raw = conv.get("bot_state")
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def save_bot_state(engine: Engine, conversation_id: str, state: dict[str, Any]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE conversations
                SET bot_state = CAST(:state AS jsonb), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": conversation_id, "state": json.dumps(state)},
        )


def existing_outbound(engine: Engine, job_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        return conn.execute(
            text(
                """
                SELECT id, delivery_status, provider_ref, body
                FROM messages
                WHERE bot_turn_job_id = :job_id
                LIMIT 1
                """
            ),
            {"job_id": job_id},
        ).mappings().first()


def persist_outbound_sending(
    engine: Engine,
    *,
    conversation_id: str,
    job_id: str,
    body: str,
) -> str:
    msg_id = f"MSG-{uuid.uuid4().hex[:10].upper()}"
    now = utc_now()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO messages (
                  id, conversation_id, sender, body, delivery_status,
                  bot_turn_job_id, sent_at
                ) VALUES (
                  :id, :conversation_id, 'bot', :body, 'sending',
                  :bot_turn_job_id, :sent_at
                )
                """
            ),
            {
                "id": msg_id,
                "conversation_id": conversation_id,
                "body": body,
                "bot_turn_job_id": job_id,
                "sent_at": now,
            },
        )
        conn.execute(
            text(
                """
                UPDATE bot_turn_jobs
                SET outbound_message_id = :mid, updated_at = now()
                WHERE id = :job_id
                """
            ),
            {"mid": msg_id, "job_id": job_id},
        )
        conn.execute(
            text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
            {"id": conversation_id},
        )
    return msg_id


def finalize_outbound(
    engine: Engine,
    *,
    message_id: str,
    provider_ref: str | None,
    delivery_status: str,
    customer_id: str | None,
    conversation_id: str,
    body: str,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE messages
                SET provider_ref = COALESCE(:provider_ref, provider_ref),
                    delivery_status = :delivery_status
                WHERE id = :id
                """
            ),
            {
                "id": message_id,
                "provider_ref": provider_ref,
                "delivery_status": delivery_status,
            },
        )
        if delivery_status == "sent":
            db.record_activity(
                conn,
                "conversation",
                conversation_id,
                "bot_reply_sent",
                "Bot WhatsApp reply sent",
                body[:120],
                customer_id,
            )
