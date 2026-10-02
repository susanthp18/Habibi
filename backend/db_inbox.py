"""Conversation Inbox: threads, suggestions, handover, and WhatsApp ingest.

Peeled from ``db.py`` (WP-036 peel 11). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy — the suite would stay
green while leaving committed rows behind.

Every cross-section helper this slice needs is already exported by ``db_core``,
so they are imported once at module level rather than re-fetched per function.
Only ``engine`` is resolved per call, through :func:`_engine`, because that is
the only one the test fixture swaps.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

import contact_window
import visibility
from db_core import (
    _IST,
    _activity,
    _actor_user_id,
    _as_utc,
    _assert_tenant_owns,
    _assert_tenant_owns_customer,
    _db,
    _id,
    _idempotent_response,
    _one,
    _rows,
    _store_idempotent_response,
    _tenant,
    _vis_params,
)
from agent_core.clock import utc_now
from db_whatsapp import REPLY_SLOT_SQL

logger = logging.getLogger(__name__)


def _engine():
    """The engine, resolved at call time.

    ``tests/conftest.py`` replaces ``db.engine`` with a savepoint proxy by
    setattr on the module object. Binding the name here at import time would
    take the real engine and silently escape that proxy.
    """
    return _db().engine


# Conversation Inbox
# ---------------------------------------------------------------------------


def _inbox_clock(value: Any) -> str:
    """Display clock matching the Inbox seed style: '3:41 PM'."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    local = value.astimezone(_IST)
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return f"{hour}:{local.minute:02d} {ampm}"


def _inbox_relative(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = utc_now() - value.astimezone(timezone.utc)
    mins = int(delta.total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 48:
        return f"{hours}h ago"
    days = hours // 24
    return f"{days}d ago"


def _inbox_sla(waiting_since: Any) -> str:
    """How long the customer has been waiting for an answer.

    Measured from their oldest unanswered message, whoever holds the thread.
    It was the age of their *last* message, so a thread an agent had already
    answered stayed breached; and every bot-held thread read "ok", so a bot
    that had stopped answering never surfaced.
    """
    since = _as_utc(waiting_since)
    if since is None:
        return "ok"
    age_h = (utc_now() - since).total_seconds() / 3600
    if age_h < 4:
        return "ok"
    if age_h < 24:
        return "warn"
    return "breach"


def _inbox_sentiment(label: str | None, avg: float | None) -> str:
    if label in {"positive", "neutral", "negative"}:
        return label
    if avg is None:
        return "neutral"
    if avg > 0.15:
        return "positive"
    if avg < -0.15:
        return "negative"
    return "neutral"


def _inbox_risk(risk: str | None) -> str:
    if not risk:
        return "Medium"
    title = risk[:1].upper() + risk[1:].lower()
    # `critical` is the book's highest band; the inbox vocabulary tops out at
    # High. It used to fall through to Medium -- the riskiest borrowers
    # rendered as the middle of the road.
    if title == "Critical":
        return "High"
    return title if title in {"High", "Medium", "Low"} else "Medium"


def _inbox_promise_status(status: str | None) -> str:
    mapping = {
        "kept": "Kept",
        "broken": "Broken",
        "partial": "Partial",
        "upcoming": "Pending",
        "due_today": "Pending",
        "pending": "Pending",
    }
    return mapping.get((status or "").lower(), "Pending")


def _inbox_channel(channel: str | None) -> str:
    if channel in {"whatsapp", "sms", "email", "voice", "chat"}:
        return channel
    return "whatsapp"


def _inbox_delivery(status: str | None, sender: str) -> str | None:
    """Map the stored delivery status onto what the bubble shows.

    ``sending`` used to collapse to None, which renders as no tick at all —
    byte-identical to a message with nothing to report. An agent reply that was
    queued and never posted therefore looked exactly like one that had gone
    out. It was: the WhatsApp outbound worker was not running, two replies sat
    in ``whatsapp_outbound_jobs`` for six minutes, the composer said nothing,
    and the agent kept typing at a customer who could not see them.

    "In flight" is a state the sender needs to see, so it now has its own.
    ``cancelled`` stays hidden: that message was deliberately withdrawn and was
    never going to arrive.
    """
    if sender not in {"bot", "agent"}:
        return None
    if status in {"sent", "delivered", "read", "failed"}:
        return status
    if status == "sending":
        return "pending"
    if status == "cancelled":
        return None
    # Anything else — NULL, empty, or a status a future writer invents — is
    # unknown, and unknown is not "delivered". There is no CHECK on the column,
    # so this fallback was asserting delivery for rows that had never been sent:
    # a seeded bot bubble wore the same tick as a message Meta confirmed.
    return None


#: Meta's customer-service window: free-form replies only within 24 hours of
#: the customer's last message, which opens and resets it.
_WHATSAPP_SERVICE_WINDOW = timedelta(hours=24)


def _reply_purpose(row: dict[str, Any]) -> tuple[str | None, datetime | None, str | None]:
    """``(gate purpose, when the WhatsApp service window closes, refusal)``
    for a reply on this thread. A refusal means no reply can be sent.

    One reading for the send and for the rail. The rail used to ask the gate
    about WhatsApp *outreach* on every thread while the send asked about this
    thread's channel *in session* -- two different questions, so the rail
    could refuse a reply the send would admit, and the reverse.

    ``last_inbound_at`` must be a message Meta delivered (it carries a wamid):
    only a real inbound opens the window. And the window is the number's that
    opened it: ``endpoint_slot`` is NULL once that number has left the
    customer's record (``db_whatsapp.REPLY_SLOT_SQL``), and a reply to whatever
    replaced it is outreach to a number that never wrote.
    """
    channel = row["channel"]
    if channel == "sms":
        return "outreach", None, None
    if channel != "whatsapp":
        # Email, web chat and voice have no outbound transport here: a reply
        # on one used to be stored as ``sent`` and go nowhere.
        return None, None, "channel_not_supported"
    at = _as_utc(row.get("last_inbound_at"))
    closes = at + _WHATSAPP_SERVICE_WINDOW if at else None
    if closes is None or utc_now() >= closes:
        return None, None, "whatsapp_window_closed"
    if not row.get("endpoint_slot"):
        return None, None, "whatsapp_endpoint_changed"
    return "in_session", closes, None


def _reply_verdict(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Whether an agent's reply on this thread would be admitted right now."""
    purpose, closes, reason = _reply_purpose(row)
    if purpose is not None:
        try:
            import contact_policy

            decision = contact_policy.evaluate(
                conn,
                customer_id=row["customer_id"],
                channel=row["channel"],
                purpose=purpose,
                session_key=row["id"],
                endpoint=_reply_endpoint(conn, row),
            )
            reason = None if decision.allowed else str(decision.reason or "refused")
        except Exception:
            # Fail closed, and say so: never a guess from the DND flag.
            logger.exception("contact policy unreadable for inbox thread %s", row["id"])
            reason = "policy_unavailable"
    return {
        "canReply": reason is None,
        "replyBlockedReason": reason,
        "replyWindowEndsAt": closes.isoformat() if closes else None,
    }


def _reply_endpoint(conn: Any, row: dict[str, Any]) -> str | None:
    """The number a reply goes to: the one the customer last wrote from."""
    import contact_policy

    phones = row if "phone_primary" in row else _one(
        conn.execute(
            text("SELECT phone_primary, phone_alt FROM customers WHERE id = :id"),
            {"id": row["customer_id"]},
        )
    )
    return contact_policy.chosen_phone(phones, slot=row.get("endpoint_slot"))


def _inbox_aging(dpd: int | None) -> str:
    days = int(dpd or 0)
    if days <= 0:
        return "Current"
    return f"{days} days overdue"


def _delivery_note(error: str | None, delivery: str | None) -> str | None:
    """Why a message did not go out, in words an agent can act on.

    The provider's text never reaches the screen: it can quote the number it
    was sent to. Meta's codes are mapped, anything else is named by kind.
    """
    if not error:
        return None
    import contact_policy

    code = re.search(r"code=(\d+)", error)
    known = {
        "131047": "Outside WhatsApp's 24-hour window",
        "131026": "This number can't receive WhatsApp messages",
        "131051": "WhatsApp doesn't support this message type",
        "130429": "WhatsApp rate limit — retrying",
        "131056": "WhatsApp rate limit for this customer — retrying",
    }
    if code and code.group(1) in known:
        return known[code.group(1)]
    reason = error.split(":", 1)[0].strip()
    if reason in contact_policy.CLOCK_REFUSALS:
        # Still queued, it waits for the hour the policy allows; failed, the
        # wait outlasted its retries and it will not go.
        return (
            "Held by contact policy until it is allowed"
            if delivery == "pending"
            else "Blocked by contact policy"
        )
    if reason.startswith(("channel_", "customer_dnd", "consent_", "suppressed", "endpoint_")):
        return "Blocked by contact policy"
    return "Rejected by the provider"


def _conversation_messages(
    conn: Any, conversation_ids: list[str], me_id: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Each thread's transcript, oldest first, with its handoff events.

    Every item carries ``at`` (ISO, UTC) beside the display clock, so a reader
    can tell yesterday from last month.

    Nothing that was attempted is hidden. A bot reply Meta rejected used to be
    dropped -- 22 of 61 bot messages at the time -- which deleted the evidence
    that the bot tried and failed from the only record of the thread, while an
    agent's failed message showed. Only ``cancelled`` stays out: withdrawn
    before sending, it was never going to arrive.

    A voice thread's turns live in ``interaction_transcript``; it renders
    those, read-only.
    """
    if not conversation_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT m.id, m.conversation_id, m.sender, m.body, m.delivery_status,
                       COALESCE(m.sent_at, m.created_at) AS at, j.error AS job_error
                FROM messages m
                LEFT JOIN LATERAL (
                  SELECT error FROM whatsapp_outbound_jobs j
                  WHERE j.message_id = m.id
                  ORDER BY j.updated_at DESC NULLS LAST
                  LIMIT 1
                ) j ON m.delivery_status IN ('failed', 'sending')
                WHERE m.conversation_id = ANY(:ids)
                  AND m.delivery_status IS DISTINCT FROM 'cancelled'
                UNION ALL
                SELECT t.id, cv.id, t.speaker, t.text, NULL::text,
                       i.started_at + make_interval(secs => COALESCE(t.at_sec, 0)), NULL::text
                FROM conversations cv
                JOIN interactions i ON i.id = cv.interaction_id
                JOIN interaction_transcript t ON t.interaction_id = i.id
                WHERE cv.id = ANY(:ids) AND cv.channel = 'voice'
                ORDER BY at, id
                """
            ),
            {"ids": conversation_ids},
        )
    )
    events = _rows(
        conn.execute(
            text(
                """
                SELECT e.id, e.entity_id, e.at, e.label, e.kind, e.note, e.actor_user_id,
                       u.name AS actor_name
                FROM activity_events e
                LEFT JOIN users u ON u.id = e.actor_user_id
                WHERE e.entity_type = 'conversation'
                  AND e.entity_id = ANY(:ids)
                  AND e.kind IN (
                    'conversation_takeover',
                    'conversation_escalated',
                    'conversation_return_to_bot'
                  )
                ORDER BY e.at, e.id
                """
            ),
            {"ids": conversation_ids},
        )
    )

    staged: dict[str, list[tuple[datetime, str, dict[str, Any]]]] = {
        cid: [] for cid in conversation_ids
    }
    floor = datetime.min.replace(tzinfo=timezone.utc)
    for r in rows:
        at = _as_utc(r["at"])
        stamp = {"time": _inbox_clock(at), "at": at.isoformat() if at else None}
        if r["sender"] == "system":
            item = {"id": r["id"], "kind": "system", "text": r["body"] or "", **stamp}
        else:
            sender = r["sender"] if r["sender"] in {"customer", "bot", "agent"} else "bot"
            delivery = _inbox_delivery(r["delivery_status"], sender)
            item = {
                "id": r["id"],
                "sender": sender,
                "text": r["body"] or "",
                **stamp,
                "delivery": delivery,
                "deliveryNote": _delivery_note(r.get("job_error"), delivery)
                if delivery in {"failed", "pending"}
                else None,
            }
        staged[r["conversation_id"]].append((at or floor, r["id"], item))

    for ev in events:
        cid = ev["entity_id"]
        if cid not in staged:
            continue
        who = "You" if me_id and ev.get("actor_user_id") == me_id else (ev.get("actor_name") or "An agent")
        kind = ev.get("kind")
        if kind == "conversation_takeover":
            text_value = f"{who} took over"
        elif kind == "conversation_return_to_bot":
            text_value = f"{who} returned it to the bot"
        else:
            note = (ev.get("note") or "").strip()
            label = ev["label"] or "Escalated to human"
            text_value = f"{label}: {note}" if note else label
        at = _as_utc(ev["at"])
        staged[cid].append(
            (
                at or floor,
                ev["id"],
                {
                    "id": ev["id"],
                    "kind": "system",
                    "text": text_value,
                    "time": _inbox_clock(at),
                    "at": at.isoformat() if at else None,
                },
            )
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for cid, items in staged.items():
        items.sort(key=lambda t: (t[0], t[1]))
        grouped[cid] = [item for _, _, item in items]
    return grouped


def _conversation_suggestions(conn: Any, conversation_id: str, interaction_id: str | None) -> list[str]:
    """The thread's knowledge-base passages, from its last search; else the
    passages linked to its interaction."""
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT conversation_id, suggestion_text
                FROM ai_response_suggestions
                WHERE (conversation_id = :cid OR (:iid <> '' AND interaction_id = :iid))
                  AND COALESCE(source, '') <> 'kb_draft'
                ORDER BY created_at DESC
                """
            ),
            {"cid": conversation_id, "iid": interaction_id or ""},
        )
    )
    mine: list[str] = []
    linked: list[str] = []
    for r in rows:
        text_value = (r["suggestion_text"] or "").strip()
        if text_value:
            (mine if r["conversation_id"] == conversation_id else linked).append(text_value)
    return (mine or linked)[:5]


def _next_emi(conn: Any, account_id: str | None) -> dict[str, Any]:
    """The oldest installment still owed: overdue before upcoming, and what is
    left of a partial. It used to be the loan's first installment ever, paid
    or not -- on month 14 of a loan, a receipt from last year."""
    emi = _one(
        conn.execute(
            text(
                """
                SELECT due_date, amount - COALESCE(paid_amount, 0) AS due, status
                FROM emi_installments
                WHERE account_id = :account_id
                  AND status IN ('overdue', 'partial', 'upcoming')
                ORDER BY due_date ASC NULLS LAST
                LIMIT 1
                """
            ),
            {"account_id": account_id},
        )
    ) if account_id else None
    if not emi:
        return {"nextEmiDate": None, "nextEmiAmount": None, "nextEmiOverdue": False}
    due_on = _as_utc(emi["due_date"])
    return {
        "nextEmiDate": due_on.astimezone(_IST).date().isoformat() if due_on else None,
        "nextEmiAmount": float(emi["due"] or 0),
        "nextEmiOverdue": emi["status"] == "overdue" or bool(due_on and due_on < utc_now()),
    }


def _thread_context(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """The borrower beside the thread. Outstanding, aging and the next EMI are
    the thread's own loan; promises, disputes and interactions span every loan
    of the customer, and the rail says which is which."""
    customer_id = row["customer_id"]
    promise = _one(
        conn.execute(
            text(
                """
                SELECT amount, promised_at, status
                FROM promises
                WHERE customer_id = :customer_id
                ORDER BY promised_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            ),
            {"customer_id": customer_id},
        )
    )
    disputes = _rows(
        conn.execute(
            text(
                """
                SELECT id, type, transcript_snippet, count(*) OVER () AS total
                FROM disputes
                WHERE customer_id = :customer_id
                  AND status NOT IN ('resolved', 'rejected')
                ORDER BY created_at DESC
                LIMIT 5
                """
            ),
            {"customer_id": customer_id},
        )
    )
    interactions = _rows(
        conn.execute(
            text(
                """
                SELECT id, channel, summary, started_at, sentiment_label, avg_sentiment
                FROM interactions
                WHERE customer_id = :customer_id
                ORDER BY started_at DESC NULLS LAST
                LIMIT 3
                """
            ),
            {"customer_id": customer_id},
        )
    )
    has_account = bool(row["account_id"])
    return {
        "riskLevel": _inbox_risk(row["risk"]),
        **_reply_verdict(conn, row),
        "contactWindow": row["preferred_window"] or contact_window.DEFAULT_WINDOW,
        "outstanding": float(row["outstanding"] or 0) if has_account else None,
        "outstandingAging": _inbox_aging(row["dpd"]) if has_account else "",
        **_next_emi(conn, row["account_id"]),
        "lastPromise": {
            "amount": float(promise["amount"] or 0),
            # The calendar day it falls due in India: a timestamptz, and the
            # UTC date of a midnight-IST promise is the day before.
            "date": _as_utc(promise["promised_at"]).astimezone(_IST).date().isoformat(),
            "status": _inbox_promise_status(promise["status"]),
        }
        if promise
        else None,
        "openDisputes": [
            {
                "id": d["id"],
                "summary": (d["transcript_snippet"] or d["type"] or "Open dispute").strip()[:80],
            }
            for d in disputes
        ],
        "openDisputesTotal": int(disputes[0]["total"]) if disputes else 0,
        "recentInteractions": [
            {
                "id": ix["id"],
                "kind": "chat" if ix["channel"] in {"whatsapp", "sms", "email", "chat"} else "call",
                "summary": (ix["summary"] or ix["channel"] or "Interaction").strip()[:80],
                "when": _inbox_relative(ix["started_at"]),
                "sentiment": _inbox_sentiment(ix["sentiment_label"], ix["avg_sentiment"]),
            }
            for ix in interactions
        ],
    }


#: A bot turn that has been pending longer than this is not "typing" — it is
#: stuck. Nothing composes a reply for a minute, so past that the indicator is
#: reporting a dead worker while telling the agent to keep waiting.
_TYPING_STALE_AFTER = "60 seconds"


def _bot_typing_by_conversation(conn: Any, conversation_ids: list[str]) -> dict[str, bool]:
    """True when the BOT is composing a reply for this conversation, right now.

    Bot work only, and bounded: an agent's own send in flight shows on its
    bubble (see _inbox_delivery), and a queue that has not moved for a minute
    is a worker problem an animated ellipsis must not report as "any moment
    now". A bot reply already written and in flight is its own pending bubble,
    so it is not counted here as well.
    """
    if not conversation_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                f"""
                SELECT conversation_id
                FROM bot_turn_jobs
                WHERE conversation_id = ANY(:ids)
                  AND status IN ('queued', 'running')
                  AND updated_at > now() - interval '{_TYPING_STALE_AFTER}'
                UNION
                SELECT conversation_id
                FROM whatsapp_outbound_jobs
                WHERE conversation_id = ANY(:ids)
                  AND status IN ('queued', 'running')
                  AND updated_at > now() - interval '{_TYPING_STALE_AFTER}'
                  AND source IS DISTINCT FROM 'inbox_reply'
                """
            ),
            {"ids": conversation_ids},
        )
    )
    return {r["conversation_id"]: True for r in rows}


def _serialize_summary(row: dict[str, Any], me_id: str, *, bot_typing: bool) -> dict[str, Any]:
    """One row of the list: who, where, what was said last, how long the
    customer has been waiting. No transcript -- the open thread reads that."""
    status = row["status"] if row["status"] in {"bot", "needs_human", "escalated", "assigned"} else "bot"
    channel = _inbox_channel(row["channel"])
    last_from = row.get("last_from") or "bot"
    if last_from not in {"customer", "bot", "agent"}:
        last_from = "bot"
    last_at = _as_utc(row.get("last_at")) or _as_utc(row["created_at"])
    updated = _as_utc(row.get("updated_at") or row.get("created_at"))
    preview = row.get("last_body") or ("Voice call" if channel == "voice" else "")
    return {
        "id": row["id"],
        "customer": row["customer_name"],
        "customerId": row["customer_id"],
        "accountId": row["account_id"] or "",
        "channel": channel,
        "status": status,
        "assignedUserId": row["assigned_user_id"],
        "isMine": row["assigned_user_id"] == me_id,
        "botTyping": bot_typing and status == "bot" and row.get("assigned_user_id") is None,
        "updatedAt": updated.isoformat() if updated else None,
        "lastAt": last_at.isoformat() if last_at else None,
        "awaitingReply": int(row.get("awaiting_n") or 0),
        "sla": _inbox_sla(row.get("awaiting_since")),
        "lastTime": _inbox_clock(last_at),
        "lastPreview": preview,
        "lastFrom": last_from,
        "sentiment": _inbox_sentiment(row["sentiment_label"], row["avg_sentiment"]),
        "handlerBotId": row.get("handler_bot_id"),
    }


def _serialize_thread(conn: Any, row: dict[str, Any], me_id: str) -> dict[str, Any]:
    """The open thread: its row, transcript, suggestions and customer context."""
    typing = _bot_typing_by_conversation(conn, [row["id"]])
    return {
        **_serialize_summary(row, me_id, bot_typing=bool(typing.get(row["id"]))),
        "messages": _conversation_messages(conn, [row["id"]], me_id).get(row["id"]) or [],
        "ragSuggestions": _conversation_suggestions(conn, row["id"], row.get("interaction_id")),
        "context": _thread_context(conn, row),
    }


#: The newest threads the list carries; the UI says when it is full. ponytail:
#: one bounded page plus server search -- cursor paging when an active book
#: outgrows it.
INBOX_LIST_LIMIT = 500


#: The list's views, each a predicate on the thread (``:me`` the caller).
#: Run on the server, so a view reaches threads older than the list's page;
#: ``conversation_counts`` counts each over the whole inbox.
_VIEW_SQL: dict[str, str] = {
    "mine": "cv.assigned_user_id = :me",
    "others": "cv.status = 'assigned' AND cv.assigned_user_id IS DISTINCT FROM :me",
    "needs_human": "cv.status = 'needs_human'",
    "escalated": "cv.status = 'escalated'",
    "bot": "cv.status = 'bot'",
    "assigned": "cv.status = 'assigned'",
}
INBOX_VIEWS = tuple(_VIEW_SQL)


def _inbox_scope() -> tuple[list[str], dict[str, Any]]:
    """Tenant-scoped and visibility-scoped like every other customer-facing
    read. `conversations` carries no tenant column of its own; the customer
    it belongs to does, and every row here is joined to that customer."""
    return (
        ["c.tenant_id = :tenant_id", visibility.predicate("c")],
        {"tenant_id": _tenant(), "me": _actor_user_id(), **_vis_params()},
    )


def _conversation_base_rows(
    conn: Any,
    conversation_id: str | None = None,
    *,
    updated_after: datetime | None = None,
    customer_id: str | None = None,
    q: str | None = None,
    view: str | None = None,
) -> list[dict[str, Any]]:
    clauses, params = _inbox_scope()
    if view:
        clauses.append(_VIEW_SQL[view])
    if conversation_id:
        clauses.append("cv.id = :conversation_id")
        params["conversation_id"] = conversation_id
    if customer_id:
        clauses.append("cv.customer_id = :customer_id")
        params["customer_id"] = customer_id
    if updated_after is not None:
        clauses.append("COALESCE(cv.updated_at, cv.created_at) > :updated_after")
        params["updated_after"] = updated_after
    if q and q.strip():
        # Every message of the thread, not only the last, and threads older
        # than the list's page.
        clauses.append(
            """(
              c.name ILIKE :q ESCAPE '!' OR a.id ILIKE :q ESCAPE '!' OR cv.id ILIKE :q ESCAPE '!'
              OR EXISTS (SELECT 1 FROM messages sm
                         WHERE sm.conversation_id = cv.id AND sm.body ILIKE :q ESCAPE '!')
            )"""
        )
        needle = q.strip().replace("!", "!!").replace("%", "!%").replace("_", "!_")
        params["q"] = f"%{needle}%"
    params["limit"] = INBOX_LIST_LIMIT
    return _rows(
        conn.execute(
            text(
                f"""
                SELECT
                  cv.id, cv.status, cv.channel, cv.assigned_user_id, cv.customer_id,
                  cv.interaction_id, cv.created_at, cv.updated_at,
                  c.name AS customer_name, c.risk, c.preferred_window,
                  a.id AS account_id, a.outstanding, a.dpd,
                  i.sentiment_label, i.avg_sentiment, i.handler_bot_id,
                  {REPLY_SLOT_SQL} AS endpoint_slot,
                  lm.sender AS last_from, lm.body AS last_body, lm.at AS last_at,
                  aw.n AS awaiting_n, aw.since AS awaiting_since,
                  (
                    -- Only a message Meta delivered opens WhatsApp's window.
                    SELECT MAX(COALESCE(m.sent_at, m.created_at)) FROM messages m
                    WHERE m.conversation_id = cv.id AND m.sender = 'customer'
                      AND m.provider_ref IS NOT NULL
                  ) AS last_inbound_at
                FROM conversations cv
                JOIN customers c ON c.id = cv.customer_id
                LEFT JOIN interactions i ON i.id = cv.interaction_id
                -- The thread's own loan: the one its interaction was opened on.
                -- It used to be the customer's first account -- for a third of
                -- the book, a different loan from the one being discussed.
                LEFT JOIN accounts a ON a.id = i.account_id
                LEFT JOIN LATERAL (
                  SELECT m.sender, m.body, COALESCE(m.sent_at, m.created_at) AS at
                  FROM messages m
                  WHERE m.conversation_id = cv.id AND m.sender <> 'system'
                    AND m.delivery_status IS DISTINCT FROM 'cancelled'
                  ORDER BY COALESCE(m.sent_at, m.created_at) DESC, m.id DESC
                  LIMIT 1
                ) lm ON true
                LEFT JOIN LATERAL (
                  -- The customer's messages since a reply that reached them.
                  -- Only one the provider took counts: a failed reply answered
                  -- nobody, and a queued one has not answered anyone yet -- with
                  -- the worker stopped it would never.
                  SELECT count(*) AS n, min(COALESCE(m.sent_at, m.created_at)) AS since
                  FROM messages m
                  WHERE m.conversation_id = cv.id AND m.sender = 'customer'
                    AND COALESCE(m.sent_at, m.created_at) > COALESCE((
                      SELECT max(COALESCE(r.sent_at, r.created_at)) FROM messages r
                      WHERE r.conversation_id = cv.id AND r.sender IN ('bot', 'agent')
                        AND r.delivery_status IN ('sent', 'delivered', 'read')
                    ), '-infinity'::timestamptz)
                ) aw ON true
                WHERE {' AND '.join(clauses)}
                ORDER BY COALESCE(lm.at, cv.created_at) DESC, cv.id
                LIMIT :limit
                """
            ),
            params,
        )
    )


def list_conversations(
    *,
    updated_after: datetime | str | None = None,
    customer_id: str | None = None,
    q: str | None = None,
    view: str | None = None,
) -> list[dict[str, Any]]:
    """The inbox list, newest activity first: summaries, no transcripts.

    ``updated_after`` returns only threads touched after that watermark (the
    delta poll); ``customer_id``, ``q`` and ``view`` search the whole inbox,
    not the page.
    """
    if view and view not in _VIEW_SQL:
        raise ValueError("invalid_view")
    after: datetime | None = None
    if updated_after is not None:
        if isinstance(updated_after, datetime):
            # Same UTC normalization as the parsed-string branch: comparing a
            # naive watermark against timestamptz makes Postgres reinterpret it
            # in the server TimeZone, silently shifting the delta window.
            after = (
                updated_after
                if updated_after.tzinfo
                else updated_after.replace(tzinfo=timezone.utc)
            )
        else:
            raw = str(updated_after).strip()
            if raw:
                try:
                    after = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError("invalid_updated_after") from exc
                if after.tzinfo is None:
                    after = after.replace(tzinfo=timezone.utc)
    me_id = _actor_user_id()
    with _engine().connect() as conn:
        rows = _conversation_base_rows(
            conn, updated_after=after, customer_id=customer_id, q=q, view=view
        )
        typing_by = _bot_typing_by_conversation(conn, [r["id"] for r in rows])
        return [
            _serialize_summary(r, me_id, bot_typing=bool(typing_by.get(r["id"]))) for r in rows
        ]


def conversation_counts() -> dict[str, int]:
    """How many threads each view holds, across the whole inbox -- not the
    list's page, whose counts stopped at its 500 rows."""
    clauses, params = _inbox_scope()
    counts = ",\n".join(f"count(*) FILTER (WHERE {sql}) AS {name}" for name, sql in _VIEW_SQL.items())
    with _engine().connect() as conn:
        row = _one(
            conn.execute(
                text(
                    f"""
                    SELECT count(*) AS total, {counts}
                    FROM conversations cv
                    JOIN customers c ON c.id = cv.customer_id
                    WHERE {' AND '.join(clauses)}
                    """
                ),
                params,
            )
        ) or {}
    return {"all": int(row.get("total") or 0), **{v: int(row.get(v) or 0) for v in _VIEW_SQL}}


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    me_id = _actor_user_id()
    with _engine().connect() as conn:
        rows = _conversation_base_rows(conn, conversation_id)
        return _serialize_thread(conn, rows[0], me_id) if rows else None


def conversation_interaction_id(conversation_id: str, customer_id: str) -> str | None:
    """The interaction a visible thread of this customer runs on, else None."""
    with _engine().connect() as conn:
        row = _one(
            conn.execute(
                text(
                    f"""
                    SELECT cv.interaction_id
                    FROM conversations cv
                    JOIN customers c ON c.id = cv.customer_id
                    WHERE cv.id = :id AND cv.customer_id = :cid
                      AND c.tenant_id = :tenant_id AND {visibility.predicate("c")}
                    """
                ),
                {"id": conversation_id, "cid": customer_id, "tenant_id": _tenant(), **_vis_params()},
            )
        )
    return (row or {}).get("interaction_id")


def list_canned_responses() -> list[dict[str, Any]]:
    with _engine().connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, label, body
                    FROM canned_responses
                    WHERE tenant_id = :tenant_id AND enabled = true
                    ORDER BY label
                    """
                ),
                {"tenant_id": _tenant()},
            )
        )
        return [{"id": r["id"], "label": r["label"], "text": r["body"]} for r in rows]


#: Sentinel: the caller did not say whose thread it believed it was taking.
_UNSTATED = object()


def _lock_conversation(conn: Any, conversation_id: str) -> dict[str, Any]:
    _assert_tenant_owns(conn, "conversations", conversation_id)
    row = _one(
        conn.execute(
            text(
                """
                SELECT id, customer_id, interaction_id, channel, status, assigned_user_id, bot_state
                FROM conversations WHERE id = :id
                FOR UPDATE
                """
            ),
            {"id": conversation_id},
        )
    )
    if row is None:
        raise KeyError("conversation_not_found")
    return row


def _hand_interaction(conn: Any, row: dict[str, Any], user_id: str | None) -> None:
    """Move the thread's interaction -- and any handoff open on it -- to a
    person, or back to the bot that answers the channel.

    The Inbox used to move only the conversation. The interaction stayed with
    the bot, so Floor Command, the Handoff Hub and every human-vs-bot report
    went on saying the bot was handling a thread a person had taken, and the
    bot's escalation sat in the Hub unclaimed.
    """
    if not row.get("interaction_id"):
        return
    if user_id is not None:
        conn.execute(
            text(
                """
                UPDATE interactions
                SET handler_kind = 'human', handler_user_id = :uid, handler_bot_id = NULL,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": row["interaction_id"], "uid": user_id},
        )
        conn.execute(
            text(
                """
                UPDATE interaction_handoffs
                SET to_user_id = :uid, accepted_at = COALESCE(accepted_at, now())
                WHERE interaction_id = :id AND completed_at IS NULL
                """
            ),
            {"id": row["interaction_id"], "uid": user_id},
        )
        return
    import db_whatsapp

    conn.execute(
        text(
            """
            UPDATE interactions
            SET handler_kind = 'bot', handler_bot_id = :bot, handler_user_id = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": row["interaction_id"], "bot": db_whatsapp.whatsapp_bot_id(conn)},
    )
    conn.execute(
        text(
            """
            UPDATE interaction_handoffs SET completed_at = now()
            WHERE interaction_id = :id AND completed_at IS NULL
            """
        ),
        {"id": row["interaction_id"]},
    )


def _assign_conversation(conn: Any, row: dict[str, Any], user_id: str, label: str) -> None:
    """Give a locked thread to a person: the conversation, its interaction and
    any open handoff, with the bot's pending turns cancelled so the person
    wins the race. The one way a thread changes hands, from the Inbox or from
    the Handoff Hub."""
    conn.execute(
        text(
            """
            UPDATE conversations
            SET status = 'assigned', assigned_user_id = :user_id, updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": row["id"], "user_id": user_id},
    )
    _hand_interaction(conn, row, user_id)
    conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'cancelled', error = 'takeover', locked_at = NULL,
                locked_by = NULL, updated_at = now()
            WHERE conversation_id = :id AND status IN ('queued', 'running')
            """
        ),
        {"id": row["id"]},
    )
    _activity(conn, "conversation", row["id"], "conversation_takeover", label, None, row["customer_id"])


def claim_interaction_thread(conn: Any, interaction_id: str, user_id: str) -> None:
    """The Handoff Hub claimed this interaction: its text thread, if it has
    one, is the claimant's too. The Hub used to move only the interaction, so
    the Inbox went on showing the thread unheld -- or someone else's -- and
    refused the claimant's reply."""
    row = _one(
        conn.execute(
            text(
                """
                SELECT id, customer_id, interaction_id, channel, status, assigned_user_id, bot_state
                FROM conversations WHERE interaction_id = :iid
                FOR UPDATE
                """
            ),
            {"iid": interaction_id},
        )
    )
    if row is None or row["assigned_user_id"] == user_id:
        return
    if row["assigned_user_id"] is not None:
        # Held in the Inbox; the Hub's own claim check refuses before this.
        raise ValueError("handoff_already_claimed")
    _assign_conversation(conn, row, user_id, "Took over from the Handoff Hub")


def takeover_conversation(conversation_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make the thread the caller's, from the bot, the queue or a colleague.

    Claiming a thread nobody holds is an agent's ordinary work. Taking one a
    colleague holds is a reassignment: it needs supervisor rights, and it is
    conditional -- ``expectedAssigneeId`` is whom the caller saw holding it,
    and if that changed in the meantime the takeover is refused rather than
    silently overwriting whoever got there first.
    """
    import authz

    me_id = _actor_user_id()
    expected = (payload or {}).get("expectedAssigneeId", _UNSTATED)
    with _engine().begin() as conn:
        row = _lock_conversation(conn, conversation_id)
        holder = row["assigned_user_id"]
        if holder != me_id:
            if expected is not _UNSTATED and holder != expected:
                raise ValueError("conversation_owner_changed")
            if holder is not None and not authz.has_permission(me_id, authz.SUPERVISOR_WRITE):
                raise PermissionError("reassign_requires_supervisor")
            _assign_conversation(
                conn, row, me_id, "Took over from a colleague" if holder else "Took over"
            )
    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    return result


def return_conversation_to_bot(conversation_id: str) -> dict[str, Any]:
    """The holder hands a WhatsApp thread back, so inbound turns enqueue bot jobs again.

    WhatsApp only: no bot answers the other channels, and a thread "returned"
    to one would wait for a reply that never comes.
    """
    me_id = _actor_user_id()
    with _engine().begin() as conn:
        row = _lock_conversation(conn, conversation_id)
        status = row["status"]
        assignee = row["assigned_user_id"]
        if row["channel"] != "whatsapp":
            raise ValueError("bot_does_not_answer_channel")
        # Owner can always release; any agent may release needs_human/escalated.
        if status == "assigned" and assignee not in (None, me_id):
            raise ValueError("return_to_bot_not_allowed")
        if status not in {"assigned", "needs_human", "escalated"}:
            raise ValueError("return_to_bot_not_allowed")

        # Drop stale session intent and mark a dialog reset so the next bot turn
        # does not treat pre-handoff EMI/PTP seed history as the current topic.
        raw_state = row.get("bot_state")
        state: dict[str, Any] = {}
        if isinstance(raw_state, dict):
            state = dict(raw_state)
        elif isinstance(raw_state, str) and raw_state.strip():
            try:
                parsed = json.loads(raw_state)
                if isinstance(parsed, dict):
                    state = parsed
            except json.JSONDecodeError:
                state = {}
        state.pop("last_intent", None)
        state.pop("last_trigger_message_id", None)
        state["dialog_reset_at"] = utc_now().isoformat()

        conn.execute(
            text(
                """
                UPDATE conversations
                SET status = 'bot',
                    assigned_user_id = NULL,
                    bot_state = CAST(:bot_state AS jsonb),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": conversation_id, "bot_state": json.dumps(state)},
        )
        _hand_interaction(conn, row, None)
        _activity(
            conn,
            "conversation",
            conversation_id,
            "conversation_return_to_bot",
            "Returned conversation to bot",
            None,
            row["customer_id"],
        )
    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    return result


#: What ``interaction_handoffs.reason`` may say for a bot-to-bot hop. The
#: CHECK admits these three; anything else is a human-escalation reason and
#: belongs to ``escalate_to_human``.
_FLEET_ROUTE_REASONS: frozenset[str] = frozenset(
    {"specialist_route", "specialist_return", "mission_entry"}
)


def handoff_to_agent(
    *,
    interaction_id: str,
    from_bot_id: str | None,
    target_bot_id: str,
    reason: str,
    payload: str | None = None,
    packet: dict[str, Any] | None = None,
    carry: str | None = None,
    turn_index: int | None = None,
    deployment_id: str | None = None,
    route_reason: str = "specialist_route",
    max_hops: int | None = None,
) -> dict[str, Any]:
    """Move a live bot-handled interaction to another first-party card.

    Writes ``transferred_from_bot_id`` / ``handler_bot_id``. Does not open a
    human handoff — that is ``escalate_to_human``. Calling this is the only
    way a transfer is recorded; transcript prose does not reach here.

    It also writes the hop's own ``interaction_handoffs`` row. Before this the
    only trace of a bot-to-bot transfer was two columns on ``interactions`` and
    an activity line, so "which specialist said this sentence" had no answer and
    the packet that crossed the boundary was recorded nowhere at all. The row is
    ``to_kind='bot'``; every analytics predicate that means *escalated to a
    human* filters on ``to_kind`` (``db_bot_analytics._ESCALATED_PRED``), so a
    hop does not inflate the containment figures.
    """
    target = (target_bot_id or "").strip()
    if not target:
        raise ValueError("target_bot_required")
    with _engine().begin() as conn:
        bot = _one(
            conn.execute(
                text("SELECT archived_at FROM bots WHERE id = :id AND tenant_id = :t"),
                {"id": target, "t": _tenant()},
            )
        )
        if bot is None:
            raise KeyError(f"bot_not_found:{target}")
        # "Stops taking traffic immediately" was enforced nowhere: a retired
        # card stayed a legal target for every card whose allowlist named it.
        if bot.get("archived_at") is not None:
            raise ValueError(f"target_bot_archived:{target}")
        ix = _one(
            conn.execute(
                text(
                    """
                    SELECT id, handler_kind, handler_bot_id, tenant_id
                    FROM interactions WHERE id = :id
                    """
                ),
                {"id": interaction_id},
            )
        )
        if ix is None:
            raise KeyError("interaction_not_found")
        if ix["handler_kind"] != "bot":
            raise ValueError("handoff_not_bot_handled")
        source = from_bot_id or ix["handler_bot_id"]
        if source == target:
            raise ValueError("handoff_same_bot")
        # The reason is a CHECK-constrained vocabulary. A bad value must not 500
        # a live call, so an unknown one degrades to the ordinary route rather
        # than aborting the transaction the caller is standing in.
        route = route_reason if route_reason in _FLEET_ROUTE_REASONS else "specialist_route"
        # The hop cap, counted here rather than on the mouth. One place serves
        # both channels — text had no cap at all — and a count survives a
        # reconnect, which an in-memory counter on a voice session does not.
        if max_hops is not None:
            hops = _one(
                conn.execute(
                    text(
                        """
                        SELECT count(*) AS n FROM interaction_handoffs
                         WHERE interaction_id = :id AND to_kind = 'bot'
                        """
                    ),
                    {"id": interaction_id},
                )
            )
            if int((hops or {}).get("n") or 0) >= int(max_hops):
                raise ValueError("hop_cap_reached")
        conn.execute(
            text(
                """
                UPDATE interactions
                SET transferred_from_bot_id = COALESCE(handler_bot_id, :from_bot),
                    handler_bot_id = :target,
                    handler_kind = 'bot',
                    handler_user_id = NULL,
                    updated_at = now()
                WHERE id = :id AND handler_kind = 'bot'
                """
            ),
            {"id": interaction_id, "from_bot": source, "target": target},
        )
        conn.execute(
            text(
                """
                INSERT INTO interaction_handoffs (
                  id, interaction_id, from_kind, from_bot_id,
                  to_kind, to_bot_id, reason, turn_index, deployment_id,
                  carry, packet, requested_at, created_at
                ) VALUES (
                  :id, :interaction_id, 'bot', :from_bot,
                  'bot', :to_bot, :route_reason, :turn_index, :deployment_id,
                  :carry, CAST(:packet AS jsonb), now(), now()
                )
                """
            ),
            {
                "id": f"ho-{uuid.uuid4().hex[:12]}",
                "interaction_id": interaction_id,
                "from_bot": source,
                "to_bot": target,
                "turn_index": turn_index,
                "deployment_id": deployment_id,
                "route_reason": route,
                "carry": carry,
                "packet": json.dumps(packet) if packet else None,
            },
        )
        _activity(
            conn,
            "interaction",
            interaction_id,
            "agent_handoff",
            f"Handed to {target}",
            (reason or "")[:240],
            None,
        )
    return {
        "ok": True,
        "fromBotId": source,
        "targetBotId": target,
        "reason": reason,
        "payload": payload,
        "interactionId": interaction_id,
    }


def list_bot_ids() -> set[str]:
    """Bot ids this tenant may name.

    Scoped because this set is G5's allowlist of legal handoff targets: an
    unscoped read let a card declare a handoff to another tenant's bot and pass
    the gate that exists to refuse exactly that. `mission.py` also walks it
    looking for mission owners, and neither caller has any business seeing
    another tenant's fleet. Archived cards are not on it either: a handoff to
    a retired card passed G5 and then went nowhere on the call.
    """
    with _engine().connect() as conn:
        return {
            r["id"]
            for r in _rows(
                conn.execute(
                    text("SELECT id FROM bots WHERE tenant_id = :t AND archived_at IS NULL"),
                    {"t": _tenant()},
                )
            )
        }


def get_latest_context_summary(interaction_id: str) -> dict[str, Any] | None:
    with _engine().connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT id, interaction_id, upto_turn, summary, model_profile, created_at
                    FROM context_summaries
                    WHERE interaction_id = :id
                    ORDER BY upto_turn DESC
                    LIMIT 1
                    """
                ),
                {"id": interaction_id},
            )
        )
        return dict(r) if r else None


def save_context_summary(
    *,
    interaction_id: str,
    upto_turn: int,
    summary: str,
    model_profile: str = "analysis",
) -> dict[str, Any]:
    sid = _id("CSUM")
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO context_summaries (
                  id, tenant_id, interaction_id, upto_turn, summary, model_profile
                ) VALUES (
                  :id, :tenant, :ix, :upto, :summary, :profile
                )
                ON CONFLICT (interaction_id, upto_turn) DO UPDATE
                  SET summary = EXCLUDED.summary,
                      model_profile = EXCLUDED.model_profile
                """
            ),
            {
                "id": sid,
                "tenant": _tenant(),
                "ix": interaction_id,
                "upto": int(upto_turn),
                "summary": summary,
                "profile": model_profile,
            },
        )
    row = get_latest_context_summary(interaction_id)
    assert row is not None
    return row


def escalate_conversation_to_human(conversation_id: str, *, reason: str = "escalated") -> dict[str, Any]:
    """Bot / routing path → needs_human. Cancels pending bot jobs."""
    with _engine().begin() as conn:
        _assert_tenant_owns(conn, "conversations", conversation_id)
        row = _one(
            conn.execute(
                text("SELECT id, customer_id, status FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
        )
        if row is None:
            raise KeyError("conversation_not_found")
        conn.execute(
            text(
                """
                UPDATE conversations
                SET status = 'needs_human',
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": conversation_id},
        )
        conn.execute(
            text(
                """
                UPDATE bot_turn_jobs
                SET status = 'cancelled',
                    error = :error,
                    locked_at = NULL,
                    locked_by = NULL,
                    updated_at = now()
                WHERE conversation_id = :id
                  AND status IN ('queued', 'running')
                """
            ),
            {"id": conversation_id, "error": f"escalated:{reason}"[:500]},
        )
        _activity(
            conn,
            "conversation",
            conversation_id,
            "conversation_escalated",
            "Escalated to human",
            reason[:240],
            row["customer_id"],
        )
    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    return result


def _sms_recipient(to_phone: str | None) -> str:
    """The number an agent's SMS goes to, or a refusal before anything is stored.

    Refused rather than queued to fail: with no provider nothing could ever
    send it, and an SMS the Inbox stored as ``sent`` without calling one was
    the bug this replaces.
    """
    import twilio_sms

    if not to_phone:
        raise ValueError("sms_missing_recipient")
    if not twilio_sms.configured():
        raise ValueError("sms_not_configured")
    return to_phone


def send_conversation_message(
    conversation_id: str, payload: dict[str, Any], idempotency_key: str | None = None
) -> dict[str, Any]:
    """An agent's reply on a thread they hold.

    One rule on every channel: the thread must be yours. SMS used to let an
    agent post into a thread a colleague held, while WhatsApp refused it. The
    reply leaves only on a channel with a transport (WhatsApp, SMS), to the
    number the customer wrote from, admitted by the gate under the same
    reading the rail shows (``_reply_purpose``).

    ``idempotency_key`` names one attempt at one reply: a resend after a lost
    response returns the message already queued instead of queueing another.
    """
    import contact_policy
    import whatsapp_outbound as wa_out

    text_value = (payload.get("text") or "").strip()
    if not text_value:
        raise ValueError("empty_message")
    me_id = _actor_user_id()
    endpoint_key = f"POST /conversations/{conversation_id}/messages"
    msg_id = _id("MSG")

    with _engine().begin() as conn:
        if _idempotent_response(conn, idempotency_key, endpoint_key):
            replayed = True
        else:
            replayed = False
            row = _one(
                conn.execute(
                    text(
                        f"""
                        SELECT cv.id, cv.customer_id, cv.status, cv.assigned_user_id, cv.channel,
                               c.phone_primary, c.phone_alt,
                               {REPLY_SLOT_SQL} AS endpoint_slot,
                               (
                                 SELECT MAX(COALESCE(m.sent_at, m.created_at))
                                 FROM messages m
                                 WHERE m.conversation_id = cv.id
                                   AND m.sender = 'customer'
                                   AND m.provider_ref IS NOT NULL
                               ) AS last_inbound_at
                        FROM conversations cv
                        JOIN customers c ON c.id = cv.customer_id
                        LEFT JOIN interactions i ON i.id = cv.interaction_id
                        WHERE cv.id = :id AND c.tenant_id = :tenant_id
                        FOR UPDATE OF cv
                        """
                    ),
                    {"id": conversation_id, "tenant_id": _tenant()},
                )
            )
            if row is None:
                raise KeyError("conversation_not_found")
            if row["assigned_user_id"] != me_id:
                raise ValueError("take_over_required")
            channel = row["channel"]
            purpose, _closes, refusal = _reply_purpose(row)
            if refusal:
                raise ValueError(refusal)
            endpoint = _reply_endpoint(conn, row)
            contact_policy.require_admit(
                conn,
                customer_id=row["customer_id"],
                channel=channel,
                purpose=purpose,
                session_key=conversation_id,
                source="inbox_reply",
                related_id=msg_id,
                actor_kind="human",
                actor_user_id=me_id,
                endpoint=endpoint,
            )
            if channel == "whatsapp":
                import whatsapp as wa

                to_phone = wa.normalize_phone(endpoint)
                if not to_phone:
                    raise ValueError("whatsapp_missing_recipient")
            else:
                to_phone = _sms_recipient(endpoint)
            # Queued, never "sent": the outbox worker posts after this commits,
            # and only the provider's answer moves the row off `sending`.
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                    VALUES (:id, :conversation_id, 'agent', :body, 'sending', NULL, :sent_at)
                    """
                ),
                {"id": msg_id, "conversation_id": conversation_id, "body": text_value, "sent_at": utc_now()},
            )
            wa_out.enqueue_agent_send(
                conn,
                message_id=msg_id,
                conversation_id=conversation_id,
                customer_id=row["customer_id"],
                to_phone=to_phone,
                body=text_value,
                purpose=purpose,
                source="inbox_reply",
            )
            conn.execute(
                text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
                {"id": conversation_id},
            )
            _activity(
                conn,
                "conversation",
                conversation_id,
                "message_sent",
                "Agent reply sent",
                text_value[:120],
                row["customer_id"],
            )
            _store_idempotent_response(conn, idempotency_key, endpoint_key, {"messageId": msg_id})

    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    if replayed:
        logger.info("inbox reply replayed conversation=%s", conversation_id)
    return result


def send_customer_outreach(
    customer_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Admit, create a thread if missing, then the inbox send path.

    WhatsApp first-touch uses purpose=outreach (no 24h session window). Both
    channels enqueue through ``whatsapp_outbound.enqueue_agent_send``; its
    worker sends an SMS thread's message through Twilio.
    """
    channel = str(payload.get("channel") or "").strip()
    text_value = (payload.get("text") or "").strip()
    if channel not in {"whatsapp", "sms"}:
        raise ValueError("unsupported_outreach_channel")
    if not text_value:
        raise ValueError("empty_message")

    endpoint = f"POST /customers/{customer_id}/outreach"
    me_id = _actor_user_id()
    now = utc_now()

    with _engine().begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        _assert_tenant_owns_customer(conn, customer_id)
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT cv.id, cv.customer_id, cv.status, cv.assigned_user_id, cv.channel,
                           c.phone_primary, c.phone_alt
                    FROM conversations cv
                    JOIN customers c ON c.id = cv.customer_id
                    WHERE cv.customer_id = :cid AND cv.channel = :channel
                    ORDER BY cv.updated_at DESC
                    LIMIT 1
                    """
                ),
                {"cid": customer_id, "channel": channel},
            )
        )
        created = False
        if existing is None:
            account = _one(
                conn.execute(
                    text(
                        """
                        SELECT id FROM accounts
                        WHERE customer_id = :cid
                        ORDER BY id
                        LIMIT 1
                        """
                    ),
                    {"cid": customer_id},
                )
            )
            phones = _one(
                conn.execute(
                    text(
                        "SELECT phone_primary, phone_alt FROM customers WHERE id = :cid"
                    ),
                    {"cid": customer_id},
                )
            )
            interaction_id = _id("IX")
            conversation_id = _id("CV")
            conn.execute(
                text(
                    """
                    INSERT INTO interactions
                      (id, tenant_id, customer_id, account_id, handler_kind, handler_user_id,
                       channel, direction, status, sentiment_label, avg_sentiment, started_at)
                    VALUES
                      (:id, :tenant_id, :customer_id, :account_id, 'human', :user_id,
                       :channel, 'outbound', 'active', 'neutral', 0, :started_at)
                    """
                ),
                {
                    "id": interaction_id,
                    "tenant_id": _tenant(),
                    "customer_id": customer_id,
                    "account_id": account["id"] if account else None,
                    "user_id": me_id,
                    "channel": channel,
                    "started_at": now,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO conversations
                      (id, interaction_id, customer_id, assigned_user_id, status, channel, created_at, updated_at)
                    VALUES
                      (:id, :interaction_id, :customer_id, :user_id, 'assigned', :channel, :now, :now)
                    """
                ),
                {
                    "id": conversation_id,
                    "interaction_id": interaction_id,
                    "customer_id": customer_id,
                    "user_id": me_id,
                    "channel": channel,
                    "now": now,
                },
            )
            existing = {
                "id": conversation_id,
                "customer_id": customer_id,
                "status": "assigned",
                "assigned_user_id": me_id,
                "channel": channel,
                "phone_primary": (phones or {}).get("phone_primary"),
                "phone_alt": (phones or {}).get("phone_alt"),
            }
            created = True

        conversation_id = existing["id"]
        msg_id = _id("MSG")
        import contact_policy

        contact_policy.require_admit(
            conn,
            customer_id=customer_id,
            channel=channel,
            purpose="outreach",
            session_key=conversation_id,
            source="customer_outreach",
            related_id=msg_id,
            actor_kind="human",
            actor_user_id=me_id,
            endpoint=contact_policy.chosen_phone(existing),
        )
        import whatsapp_outbound as wa_out

        if channel == "whatsapp":
            import whatsapp as wa

            to_phone = wa.normalize_phone(contact_policy.chosen_phone(existing))
            if not to_phone:
                raise ValueError("whatsapp_missing_recipient")
        else:
            to_phone = _sms_recipient(contact_policy.chosen_phone(existing))
        # Both channels leave through the outbox after commit; the worker's
        # provider answer is what moves the row off `sending`.
        conn.execute(
            text(
                """
                INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                VALUES (:id, :conversation_id, 'agent', :body, 'sending', NULL, :sent_at)
                """
            ),
            {
                "id": msg_id,
                "conversation_id": conversation_id,
                "body": text_value,
                "sent_at": now,
            },
        )
        wa_out.enqueue_agent_send(
            conn,
            message_id=msg_id,
            conversation_id=conversation_id,
            customer_id=customer_id,
            to_phone=to_phone,
            body=text_value,
            purpose="outreach",
            source="customer_outreach",
        )
        conn.execute(
            text(
                """
                UPDATE conversations
                SET status = 'assigned', assigned_user_id = :user_id, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": conversation_id, "user_id": me_id},
        )
        _activity(
            conn,
            "conversation",
            conversation_id,
            "message_sent",
            "Outreach sent",
            text_value[:120],
            customer_id,
        )
        result = {
            "conversationId": conversation_id,
            "messageId": msg_id,
            "channel": channel,
            "createdConversation": created,
        }
        _store_idempotent_response(conn, idempotency_key, endpoint, result)
        return result
