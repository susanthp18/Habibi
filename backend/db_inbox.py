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
    MAX_LIST_LIMIT,
    _activity,
    _actor_user_id,
    _assert_tenant_owns,
    _db,
    _id,
    _jsonb,
    _one,
    _rows,
    _tenant,
    _vis_params,
    clamp_list_limit,
    clamp_offset,
)
from pg_errors import is_unique_violation as _is_unique_violation

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
    delta = datetime.now(timezone.utc) - value.astimezone(timezone.utc)
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


def _inbox_sla(last_customer_at: Any, status: str) -> str:
    """Derive SLA from age of last customer inbound. Seed rows often share one
    sent_at, so fall back gently rather than marking everything breach."""
    if status == "bot":
        return "ok"
    if last_customer_at is None:
        return "ok"
    if isinstance(last_customer_at, str):
        try:
            last_customer_at = datetime.fromisoformat(last_customer_at.replace("Z", "+00:00"))
        except ValueError:
            return "ok"
    if not isinstance(last_customer_at, datetime):
        return "ok"
    if last_customer_at.tzinfo is None:
        last_customer_at = last_customer_at.replace(tzinfo=timezone.utc)
    age_h = (datetime.now(timezone.utc) - last_customer_at.astimezone(timezone.utc)).total_seconds() / 3600
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
        return "whatsapp" if channel == "chat" else channel
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


def _inbox_contactable(
    conn: Any,
    customer_id: str,
    dnd: bool,
    preferred_window: str | None,
    channel: str = "whatsapp",
) -> bool:
    try:
        import contact_policy

        decision = contact_policy.evaluate(
            conn,
            customer_id=customer_id,
            channel=channel,
            purpose="outreach",
        )
        return bool(decision.allowed)
    except Exception:
        if dnd:
            return False
        return not contact_window.outside_preferred_window(
            datetime.now(_IST).isoformat(), preferred_window
        )


def _inbox_aging(dpd: int | None) -> str:
    days = int(dpd or 0)
    if days <= 0:
        return "Current"
    return f"{days} days overdue"


def _conversation_messages(conn: Any, conversation_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not conversation_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, conversation_id, sender, body, delivery_status, sent_at, created_at
                FROM messages
                WHERE conversation_id = ANY(:ids)
                ORDER BY COALESCE(sent_at, created_at), id
                """
            ),
            {"ids": conversation_ids},
        )
    )
    events = _rows(
        conn.execute(
            text(
                """
                SELECT id, entity_id, at, label, kind, note
                FROM activity_events
                WHERE entity_type = 'conversation'
                  AND entity_id = ANY(:ids)
                  AND kind IN (
                    'conversation_takeover',
                    'conversation_escalated',
                    'conversation_return_to_bot'
                  )
                ORDER BY at, id
                """
            ),
            {"ids": conversation_ids},
        )
    )

    def _ts(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)
        return datetime.min.replace(tzinfo=timezone.utc)

    staged: dict[str, list[tuple[datetime, str, dict[str, Any]]]] = {
        cid: [] for cid in conversation_ids
    }
    for r in rows:
        # Hide bot drafts that never made it to WhatsApp (sending/failed).
        if r["sender"] == "bot" and (r.get("delivery_status") or "") in {"sending", "failed", "cancelled"}:
            continue
        clock = _inbox_clock(r["sent_at"] or r["created_at"])
        sort_at = _ts(r["sent_at"] or r["created_at"])
        if r["sender"] == "system":
            item = {"id": r["id"], "kind": "system", "text": r["body"], "time": clock}
        else:
            sender = r["sender"] if r["sender"] in {"customer", "bot", "agent"} else "bot"
            item = {
                "id": r["id"],
                "sender": sender,
                "text": r["body"],
                "time": clock,
                "delivery": _inbox_delivery(r["delivery_status"], sender),
            }
        staged[r["conversation_id"]].append((sort_at, r["id"], item))

    for ev in events:
        cid = ev["entity_id"]
        if cid not in staged:
            continue
        label = ev["label"] or ev["kind"]
        note = (ev.get("note") or "").strip()
        if note and ev.get("kind") == "conversation_escalated":
            text_value = f"{label}: {note}"
        else:
            text_value = label
        if any(item.get("kind") == "system" and item.get("text") == text_value for _, _, item in staged[cid]):
            continue
        staged[cid].append(
            (
                _ts(ev["at"]),
                ev["id"],
                {
                    "id": ev["id"],
                    "kind": "system",
                    "text": text_value,
                    "time": _inbox_clock(ev["at"]),
                },
            )
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for cid, items in staged.items():
        items.sort(key=lambda t: (t[0], t[1]))
        grouped[cid] = [item for _, _, item in items]
    return grouped


def _conversation_suggestions(
    conn: Any, conversation_ids: list[str], interaction_ids: list[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, str]]:
    """Return snippet chips by conversation / interaction, plus optional kb_draft per conversation."""
    if not conversation_ids and not interaction_ids:
        return {}, {}, {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT conversation_id, interaction_id, suggestion_text, source
                FROM ai_response_suggestions
                WHERE conversation_id = ANY(:cids)
                   OR interaction_id = ANY(:iids)
                ORDER BY created_at DESC
                """
            ),
            {"cids": conversation_ids or [""], "iids": interaction_ids or [""]},
        )
    )
    by_conv: dict[str, list[str]] = {}
    by_ix: dict[str, list[str]] = {}
    drafts_by_conv: dict[str, str] = {}
    for r in rows:
        text_value = (r["suggestion_text"] or "").strip()
        if not text_value:
            continue
        source = (r.get("source") or "").strip().lower()
        if r["conversation_id"] and source == "kb_draft":
            # Newest draft wins (ORDER BY created_at DESC).
            drafts_by_conv.setdefault(r["conversation_id"], text_value)
            continue
        if r["conversation_id"]:
            by_conv.setdefault(r["conversation_id"], []).append(text_value)
        if r["interaction_id"]:
            by_ix.setdefault(r["interaction_id"], []).append(text_value)
    return by_conv, by_ix, drafts_by_conv


def _thread_context(conn: Any, customer_id: str, account_id: str | None, risk: str | None, dnd: bool, preferred_window: str | None, outstanding: float, dpd: int | None) -> dict[str, Any]:
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
                SELECT id, type, transcript_snippet
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
    emi = _one(
        conn.execute(
            text(
                """
                SELECT due_date, amount
                FROM emi_installments
                WHERE account_id = :account_id
                ORDER BY due_date ASC NULLS LAST
                LIMIT 1
                """
            ),
            {"account_id": account_id},
        )
    ) if account_id else None

    last_promise = None
    if promise:
        last_promise = {
            "amount": float(promise["amount"] or 0),
            "date": (promise["promised_at"] or "")[:10],
            "status": _inbox_promise_status(promise["status"]),
        }

    next_emi_date = ""
    next_emi_amount = 0.0
    if emi:
        next_emi_date = (emi["due_date"] or "")[:10] if isinstance(emi["due_date"], str) else (
            emi["due_date"].isoformat()[:10] if emi["due_date"] else ""
        )
        next_emi_amount = float(emi["amount"] or 0)

    return {
        "riskLevel": _inbox_risk(risk),
        "contactableNow": _inbox_contactable(conn, customer_id, bool(dnd), preferred_window),
        "contactWindow": preferred_window or contact_window.DEFAULT_WINDOW,
        "outstanding": float(outstanding or 0),
        "outstandingAging": _inbox_aging(dpd),
        "nextEmiDate": next_emi_date or "—",
        "nextEmiAmount": next_emi_amount,
        "lastPromise": last_promise,
        "openDisputes": [
            {
                "id": d["id"],
                "summary": (d["transcript_snippet"] or d["type"] or "Open dispute").strip()[:80],
            }
            for d in disputes
        ],
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
    """True when the BOT owes this conversation a reply, right now.

    Two things used to be conflated into this flag and neither belonged:

    * an *agent's* own outbound message sitting at ``sending``. The composer
      then displayed "Bot is typing…" back at the human who had just taken over
      and pressed Send — describing their own message as the bot's, and
      implying something was still coming;
    * a job with no upper age bound. When the WhatsApp worker is not running,
      queued rows never advance, so the indicator ran for as long as the
      process stayed down. It read as "any moment now" for six minutes.

    Narrowed to bot work, and bounded — a stale queue is a worker problem, and
    an animated ellipsis is the wrong way to report one.
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
                  -- Bot drafts only. An agent send in flight is shown on the
                  -- agent's own bubble (see _inbox_delivery), not as the bot
                  -- speaking.
                  AND source IS DISTINCT FROM 'inbox_reply'
                UNION
                SELECT conversation_id
                FROM messages
                WHERE conversation_id = ANY(:ids)
                  AND sender = 'bot'
                  AND delivery_status = 'sending'
                  AND COALESCE(sent_at, created_at) > now() - interval '{_TYPING_STALE_AFTER}'
                """
            ),
            {"ids": conversation_ids},
        )
    )
    return {r["conversation_id"]: True for r in rows}


def _serialize_conversation(
    conn: Any,
    row: dict[str, Any],
    messages: list[dict[str, Any]],
    suggestions: list[str],
    me_id: str,
    *,
    draft_answer: str | None = None,
    bot_typing: bool = False,
) -> dict[str, Any]:
    last_msg = None
    for item in reversed(messages):
        if item.get("kind") != "system":
            last_msg = item
            break
    last_from = (last_msg or {}).get("sender") or "bot"
    if last_from not in {"customer", "bot", "agent"}:
        last_from = "bot"
    last_preview = (last_msg or {}).get("text") or ""
    last_time = (last_msg or {}).get("time") or _inbox_clock(row["updated_at"] or row["created_at"])

    # Unread ≈ trailing customer turns since last agent/bot reply when not mine.
    unread = 0
    if not (row["assigned_user_id"] == me_id):
        for item in reversed(messages):
            if item.get("kind") == "system":
                continue
            if item.get("sender") == "customer":
                unread += 1
            else:
                break

    last_customer_at = row.get("last_customer_at")
    draft = (draft_answer or "").strip() or None
    pending = bool(bot_typing)
    typing = pending and (row.get("status") == "bot") and (row.get("assigned_user_id") is None)
    updated = row.get("updated_at") or row.get("created_at")
    if hasattr(updated, "isoformat"):
        updated_at = updated.isoformat()
    else:
        updated_at = str(updated) if updated else None
    return {
        "id": row["id"],
        "customer": row["customer_name"],
        "customerId": row["customer_id"],
        "accountId": row["account_id"] or "",
        "channel": _inbox_channel(row["channel"]),
        "status": row["status"] if row["status"] in {"bot", "needs_human", "escalated", "assigned"} else "bot",
        "assignedUserId": row["assigned_user_id"],
        "isMine": row["assigned_user_id"] == me_id,
        "botTyping": typing,
        "pendingOutbound": pending,
        "updatedAt": updated_at,
        "sla": _inbox_sla(last_customer_at, row["status"]),
        "unread": unread,
        "lastTime": last_time,
        "lastPreview": last_preview,
        "lastFrom": last_from,
        "sentiment": _inbox_sentiment(row["sentiment_label"], row["avg_sentiment"]),
        "ragSuggestions": suggestions[:5],
        "ragDraftAnswer": draft,
        "handlerBotId": row.get("handler_bot_id"),
        "messages": messages,
        "context": _thread_context(
            conn,
            row["customer_id"],
            row["account_id"],
            row["risk"],
            bool(row["dnd"]),
            row["preferred_window"],
            float(row["outstanding"] or 0),
            row["dpd"],
        ),
    }


def _conversation_base_rows(
    conn: Any,
    conversation_id: str | None = None,
    *,
    updated_after: datetime | None = None,
) -> list[dict[str, Any]]:
    # Tenant-scoped and visibility-scoped like every other customer-facing
    # read. `conversations` carries no tenant column of its own; the customer
    # it belongs to does, and every row here is joined to that customer. This
    # was the one list on the Inbox that answered for every tenant at once.
    clauses: list[str] = ["c.tenant_id = :tenant_id", visibility.predicate("c")]
    params: dict[str, Any] = {"tenant_id": _tenant(), **_vis_params()}
    if conversation_id:
        clauses.append("cv.id = :conversation_id")
        params["conversation_id"] = conversation_id
    if updated_after is not None:
        clauses.append("COALESCE(cv.updated_at, cv.created_at) > :updated_after")
        params["updated_after"] = updated_after
    where = f"WHERE {' AND '.join(clauses)}"
    params["limit"] = clamp_list_limit(None, MAX_LIST_LIMIT)
    return _rows(
        conn.execute(
            text(
                f"""
                SELECT
                  cv.id,
                  cv.status,
                  cv.channel,
                  cv.assigned_user_id,
                  cv.customer_id,
                  cv.interaction_id,
                  cv.created_at,
                  cv.updated_at,
                  c.name AS customer_name,
                  c.risk,
                  c.dnd,
                  c.preferred_window,
                  a.id AS account_id,
                  a.outstanding,
                  a.dpd,
                  i.sentiment_label,
                  i.avg_sentiment,
                  i.handler_bot_id,
                  (
                    SELECT MAX(COALESCE(m.sent_at, m.created_at))
                    FROM messages m
                    WHERE m.conversation_id = cv.id AND m.sender = 'customer'
                  ) AS last_customer_at
                FROM conversations cv
                JOIN customers c ON c.id = cv.customer_id
                LEFT JOIN interactions i ON i.id = cv.interaction_id
                LEFT JOIN LATERAL (
                  SELECT *
                  FROM accounts a
                  WHERE a.customer_id = c.id
                  ORDER BY
                    CASE WHEN a.id LIKE 'AC-%%' THEN 0 ELSE 1 END,
                    a.created_at,
                    a.id
                  LIMIT 1
                ) a ON true
                {where}
                ORDER BY COALESCE(cv.updated_at, cv.created_at) DESC, cv.id
                LIMIT :limit
                """
            ),
            params,
        )
    )


def list_conversations(*, updated_after: datetime | str | None = None) -> list[dict[str, Any]]:
    """Conversation Inbox feed — full Thread shape for the screen.

    When ``updated_after`` is set, only conversations touched after that watermark
    are returned (delta poll). Callers merge into the cached list by id.
    """
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
        rows = _conversation_base_rows(conn, updated_after=after)
        ids = [r["id"] for r in rows]
        interaction_ids = [r["interaction_id"] for r in rows if r["interaction_id"]]
        messages_by = _conversation_messages(conn, ids)
        by_conv, by_ix, drafts_by_conv = _conversation_suggestions(conn, ids, interaction_ids)
        typing_by = _bot_typing_by_conversation(conn, ids)
        result = []
        for r in rows:
            suggestions = list(by_conv.get(r["id"]) or [])
            if not suggestions and r["interaction_id"]:
                suggestions = list(by_ix.get(r["interaction_id"]) or [])
            # No hardcoded fallback — empty until refresh_conversation_suggestions / seed.
            result.append(
                _serialize_conversation(
                    conn,
                    r,
                    messages_by.get(r["id"]) or [],
                    suggestions,
                    me_id,
                    draft_answer=drafts_by_conv.get(r["id"]),
                    bot_typing=bool(typing_by.get(r["id"])),
                )
            )
        return result


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    me_id = _actor_user_id()
    with _engine().connect() as conn:
        rows = _conversation_base_rows(conn, conversation_id)
        if not rows:
            return None
        r = rows[0]
        messages = (_conversation_messages(conn, [conversation_id])).get(conversation_id) or []
        by_conv, by_ix, drafts_by_conv = _conversation_suggestions(
            conn, [conversation_id], [r["interaction_id"]] if r["interaction_id"] else []
        )
        suggestions = list(by_conv.get(conversation_id) or [])
        if not suggestions and r["interaction_id"]:
            suggestions = list(by_ix.get(r["interaction_id"]) or [])
        typing_by = _bot_typing_by_conversation(conn, [conversation_id])
        return _serialize_conversation(
            conn,
            r,
            messages,
            suggestions,
            me_id,
            draft_answer=drafts_by_conv.get(conversation_id),
            bot_typing=bool(typing_by.get(conversation_id)),
        )


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


# Inbox RAG: skip greetings / acks so "hi" does not dominate retrieval.
_INBOX_RAG_NOISE = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hola",
        "thanks",
        "thank you",
        "thankyou",
        "ok",
        "okay",
        "k",
        "yes",
        "no",
        "yep",
        "nope",
        "bye",
        "good morning",
        "good afternoon",
        "good evening",
        "gm",
        "status probe",
    }
)
# Cosine floor for Inbox chips. Empirically on-domain insurance hits land ~0.45–0.60
# when the query is clean; mixed history used to sit just under 0.50 and look "empty".
INBOX_RAG_MIN_SCORE = 0.38
_INBOX_RAG_MAX_TURN_CHARS = 220
_INBOX_RAG_TEST_MARKERS = (
    "inbound test",
    "status probe",
    "test message",
    "webhook test",
    "from phone",
)
_INBOX_RAG_COLLECTIONS_HINTS = (
    "emi",
    "payment",
    "loan",
    "outstanding",
    "overdue",
    "due date",
    "promise",
    "ptp",
    "dpd",
    "installment",
    "instalment",
    "settlement",
    "waiver",
    "late fee",
    "npa",
)


def _is_inbox_rag_noise(text_value: str) -> bool:
    t = " ".join((text_value or "").lower().split()).strip(".,!? ")
    if not t:
        return True
    if t in _INBOX_RAG_NOISE:
        return True
    # Very short acknowledgements / phatic noise.
    if len(t) <= 16 and t.rstrip(".!") in _INBOX_RAG_NOISE:
        return True
    # Dev / webhook probe lines that dilute embedding queries.
    if any(m in t for m in _INBOX_RAG_TEST_MARKERS):
        return True
    return False


def _looks_like_pasted_draft(text_value: str) -> bool:
    """Skip agent pastes of prior RAG/LLM output — they poison the next retrieve."""
    raw = text_value or ""
    t = raw.lower()
    markers = (
        "from the context",
        "provided context",
        "i don't have any information",
        "i can only confirm",
        "source: **faq",
        "source: faq",
    )
    if any(m in t for m in markers):
        return True
    # Long markdown-ish blobs are almost never a live chat turn.
    if len(raw) > 280 and ("**" in raw or raw.count("\n") >= 3):
        return True
    return False


def _clip_inbox_rag_turn(text_value: str) -> str:
    t = " ".join((text_value or "").split())
    if len(t) <= _INBOX_RAG_MAX_TURN_CHARS:
        return t
    return t[: _INBOX_RAG_MAX_TURN_CHARS - 1] + "…"


def _is_questionish(text_value: str) -> bool:
    t = (text_value or "").strip().lower()
    if not t:
        return False
    if "?" in t:
        return True
    return t.startswith(
        ("how ", "what ", "when ", "where ", "why ", "can ", "could ", "should ", "do ", "does ", "is ", "are ")
    )


def _looks_collections_topic(text_value: str) -> bool:
    t = (text_value or "").lower()
    return any(h in t for h in _INBOX_RAG_COLLECTIONS_HINTS)


def _conversation_rag_query(conn: Any, conversation_id: str) -> str:
    """Build retrieve query focused on the latest customer question.

    Keeps the embedding tight: prefer customer turns, at most one short
    supporting turn, skip bot/greetings/test probes/pasted drafts. Account
    product is appended only when the primary turn is collections-related —
    otherwise "Personal Loan" pulls insurance queries off-domain.
    """
    row = _one(
        conn.execute(
            text(
                """
                SELECT c.name AS customer_name, p.name AS product
                FROM conversations cv
                JOIN customers c ON c.id = cv.customer_id
                LEFT JOIN LATERAL (
                  SELECT pr.name
                  FROM accounts a
                  JOIN products pr ON pr.id = a.product_id
                  WHERE a.customer_id = cv.customer_id
                  ORDER BY a.updated_at DESC NULLS LAST, a.created_at DESC NULLS LAST
                  LIMIT 1
                ) p ON true
                WHERE cv.id = :id
                """
            ),
            {"id": conversation_id},
        )
    )
    if not row:
        raise KeyError("conversation_not_found")

    msgs = _rows(
        conn.execute(
            text(
                """
                SELECT body, sender
                FROM messages
                WHERE conversation_id = :id
                ORDER BY created_at DESC NULLS LAST, id DESC
                LIMIT 20
                """
            ),
            {"id": conversation_id},
        )
    )
    chronological = list(reversed(msgs))
    # Bot turns are long templates and pollute agent-assist retrieval.
    label_map = {"customer": "Customer", "agent": "Agent"}
    substantive: list[tuple[str, str]] = []  # (label, body)
    for m in chronological:
        body = (m.get("body") or "").strip()
        sender = (m.get("sender") or "").lower()
        if sender not in label_map or not body:
            continue
        if _is_inbox_rag_noise(body) or _looks_like_pasted_draft(body):
            continue
        substantive.append((label_map[sender], body))

    recent = substantive[-6:]
    if not recent:
        fallback: list[tuple[str, str]] = []
        for m in chronological:
            body = (m.get("body") or "").strip()
            sender = (m.get("sender") or "").lower()
            if sender not in label_map or not body:
                continue
            if _looks_like_pasted_draft(body):
                continue
            fallback.append((label_map[sender], body))
        recent = fallback[-3:]
    if not recent:
        raise ValueError("conversation_has_no_messages")

    # Primary: latest customer question → latest customer turn → latest agent
    # question → latest turn. Customer intent beats agent typing for retrieval.
    primary_idx = len(recent) - 1
    for i in range(len(recent) - 1, -1, -1):
        if recent[i][0] == "Customer" and _is_questionish(recent[i][1]):
            primary_idx = i
            break
    else:
        for i in range(len(recent) - 1, -1, -1):
            if recent[i][0] == "Customer":
                primary_idx = i
                break
        else:
            for i in range(len(recent) - 1, -1, -1):
                if _is_questionish(recent[i][1]):
                    primary_idx = i
                    break

    primary = recent[primary_idx]
    # At most one supporting turn — prefer another nearby customer line.
    support: tuple[str, str] | None = None
    for i in range(len(recent) - 1, -1, -1):
        if i == primary_idx:
            continue
        label, body = recent[i]
        if label == "Customer":
            support = (label, body)
            break
    if support is None:
        for i in range(len(recent) - 1, -1, -1):
            if i == primary_idx:
                continue
            support = recent[i]
            break

    parts = [f"{primary[0]}: {_clip_inbox_rag_turn(primary[1])}"]
    if support is not None:
        parts.append(f"{support[0]}: {_clip_inbox_rag_turn(support[1])}")

    product = (row.get("product") or "").strip()
    if product and _looks_collections_topic(primary[1]):
        parts.append(f"Account product: {product}.")
    return "\n".join(parts)


def _chip_from_result(item: dict[str, Any]) -> str:
    """Full KB snippet for Inbox tiles (Show more must have real text, not a 140-char stub)."""
    title = (item.get("docTitle") or "").strip()
    heading = (item.get("heading") or "").strip()
    snip = ((item.get("snippet") or "").strip())
    # Preserve newlines in policy wording; collapse only runs of spaces/tabs.
    if snip:
        snip = re.sub(r"[ \t]+", " ", snip)
        snip = re.sub(r"\n{3,}", "\n\n", snip).strip()
    if len(snip) > 2400:
        snip = snip[:2397].rstrip() + "…"
    head_bits = [p for p in (title, heading) if p]
    head = " — ".join(head_bits)
    if head and snip:
        return f"{head}\n\n{snip}"
    return snip or head or "KB suggestion"


def refresh_conversation_suggestions(
    conversation_id: str,
    *,
    top_k: int = 4,
    include_draft_answer: bool = False,
) -> dict[str, Any]:
    """Run shared kb_retrieve → persist ai_response_suggestions for Inbox chips.

    Optional draft uses the same grounded chat path as Test Retrieval
    (`include_draft_answer` → kb_retrieve); no second rewrite pipeline.
    Weak matches below INBOX_RAG_MIN_SCORE are dropped (empty chips > junk).
    """
    import kb_rate_limit
    import kb_retrieve

    with _engine().connect() as conn:
        try:
            query = _conversation_rag_query(conn, conversation_id)
        except ValueError as exc:
            if str(exc) != "conversation_has_no_messages":
                raise
            # Not a bad request. A conversation with nothing to retrieve
            # against is an ordinary state — a voice call escalated into the
            # inbox keeps its turns in interaction_transcript, not messages, so
            # every poll of that thread 400'd. There is nothing to suggest, and
            # "nothing to suggest" is an empty list.
            return {
                "conversationId": conversation_id,
                "ragSuggestions": [],
                "draftAnswer": None,
                "chatModel": None,
                "latencyMs": 0,
                "logId": None,
            }

    # Over-fetch then score-gate so we can fill top_k after filtering.
    fetch_k = max(top_k * 2, 8)
    q_l = (query or "").lower()
    prefer_policy = any(
        k in q_l
        for k in (
            "exclu",
            "invalid",
            "not covered",
            "policy",
            "cover",
            "benefit",
            "travel",
            "protect360",
            "wording",
        )
    )
    retrieval: dict[str, Any] | None = None
    try:
        retrieval = kb_retrieve.retrieve(
            query=query,
            top_k=fetch_k,
            include_draft_answer=include_draft_answer,
            source="inbox",
            prefer_policy=prefer_policy,
        )
    except kb_rate_limit.RateLimitExceeded:
        # Not an outage — backpressure, and the caller has a 429 for it. The
        # broad handler below exists so a retrieval outage degrades to the last
        # persisted chips rather than blanking the panel; catching the throttle
        # with it meant a rate-limited poll returned 200 with stale chips and
        # no way for the operator to tell they were stale.
        raise
    except Exception:
        logger.exception("inbox_rag_retrieve_failed conversation=%s", conversation_id)
        retrieval = None
    if retrieval is None:
        # Fall through to persisted-chips path below.
        chips = []
        draft = None
        passed = []
    else:
        chips = []
        passed = [
            item
            for item in (retrieval.get("results") or [])
            if float(item.get("score") or 0.0) >= INBOX_RAG_MIN_SCORE
        ]
        # Don't persist a draft grounded on weak / off-topic hits.
        draft = (retrieval.get("draftAnswer") or "").strip() or None
        if not passed:
            draft = None
        for item in passed:
            chip = _chip_from_result(item)
            if chip and chip not in chips:
                chips.append(chip)
            if len(chips) >= top_k:
                break

    # Only replace persisted chips when we have a fresh pass set. An empty
    # retrieval (score-gate miss / transient embed blip) must not wipe the last
    # good suggestions — that made Inbox look permanently empty under a stale
    # worker or noisy query.
    with _engine().begin() as conn:
        if chips or draft:
            conn.execute(
                text(
                    """
                    DELETE FROM ai_response_suggestions
                    WHERE conversation_id = :id
                      AND COALESCE(source, '') IN ('kb', 'kb_draft')
                    """
                ),
                {"id": conversation_id},
            )
            if draft:
                conn.execute(
                    text(
                        """
                        INSERT INTO ai_response_suggestions (
                          id, conversation_id, interaction_id, transcript_turn_id,
                          suggestion_text, source, accepted, accepted_by_user_id,
                          accepted_at, created_at
                        ) VALUES (
                          :id, :conversation_id, NULL, NULL,
                          :suggestion_text, 'kb_draft', false, NULL,
                          NULL, now()
                        )
                        """
                    ),
                    {
                        "id": f"sug-{conversation_id}-{uuid.uuid4().hex[:8]}-draft",
                        "conversation_id": conversation_id,
                        "suggestion_text": draft,
                    },
                )
            for i, text_value in enumerate(chips):
                conn.execute(
                    text(
                        """
                        INSERT INTO ai_response_suggestions (
                          id, conversation_id, interaction_id, transcript_turn_id,
                          suggestion_text, source, accepted, accepted_by_user_id,
                          accepted_at, created_at
                        ) VALUES (
                          :id, :conversation_id, NULL, NULL,
                          :suggestion_text, 'kb', false, NULL,
                          NULL, now()
                        )
                        """
                    ),
                    {
                        "id": f"sug-{conversation_id}-{uuid.uuid4().hex[:8]}-{i}",
                        "conversation_id": conversation_id,
                        "suggestion_text": text_value,
                    },
                )
        else:
            # Fall back to last persisted chips so the UI does not go blank.
            existing = _rows(
                conn.execute(
                    text(
                        """
                        SELECT suggestion_text
                        FROM ai_response_suggestions
                        WHERE conversation_id = :id
                          AND COALESCE(source, '') = 'kb'
                        ORDER BY created_at DESC
                        LIMIT 5
                        """
                    ),
                    {"id": conversation_id},
                )
            )
            chips = [str(r["suggestion_text"]).strip() for r in existing if r.get("suggestion_text")]

    meta: dict[str, Any] = retrieval or {}
    logger.info(
        "inbox_rag_refreshed conversation=%s chips=%s passed=%s draft=%s min_score=%s latency_ms=%s",
        conversation_id,
        len(chips),
        len(passed),
        bool(draft),
        INBOX_RAG_MIN_SCORE,
        meta.get("latencyMs"),
    )
    thread = get_conversation(conversation_id)
    if thread is None:
        raise KeyError(f"conversation {conversation_id} not found")
    return {
        "conversationId": conversation_id,
        "ragSuggestions": chips[:5],
        "draftAnswer": draft,
        "chatModel": meta.get("chatModel"),
        "latencyMs": meta.get("latencyMs"),
        "logId": meta.get("logId"),
        "thread": thread,
    }


def create_kb_snapshot(*, label: str | None = None) -> dict[str, Any]:
    """Freeze currently enabled indexed docs + enabled FAQs for sandbox readiness."""
    import json

    snap_id = f"kb-snapshot-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    label_text = (label or "").strip() or f"KB snapshot {datetime.now(timezone.utc).date().isoformat()}"
    with _engine().begin() as conn:
        docs = _rows(
            conn.execute(
                text(
                    """
                    SELECT id FROM kb_documents
                    WHERE enabled = true AND status = 'indexed'
                    ORDER BY id
                    """
                )
            )
        )
        faqs = _rows(
            conn.execute(
                text(
                    """
                    SELECT id FROM faq_pairs
                    WHERE enabled = true
                    ORDER BY id
                    """
                )
            )
        )
        doc_ids = [d["id"] for d in docs]
        faq_ids = [f["id"] for f in faqs]
        conn.execute(
            text(
                """
                INSERT INTO kb_snapshots
                  (id, tenant_id, label, document_ids, faq_ids, created_at)
                VALUES (:id, :tenant_id, :label, CAST(:document_ids AS jsonb),
                        CAST(:faq_ids AS jsonb), now())
                """
            ),
            {
                "id": snap_id,
                "tenant_id": _tenant(),
                "label": label_text,
                "document_ids": json.dumps(doc_ids),
                "faq_ids": json.dumps(faq_ids),
            },
        )
    return {
        "id": snap_id,
        "label": label_text,
        "documentIds": doc_ids,
        "faqIds": faq_ids,
        "documentCount": len(doc_ids),
        "faqCount": len(faq_ids),
    }


def list_kb_snapshots(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with _engine().connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, label, document_ids, faq_ids, created_at
                    FROM kb_snapshots
                    ORDER BY created_at DESC, id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip},
            )
        )
    out = []
    for r in rows:
        docs = r.get("document_ids") or []
        faqs = r.get("faq_ids") or []
        if isinstance(docs, str):
            import json

            docs = json.loads(docs)
        if isinstance(faqs, str):
            import json

            faqs = json.loads(faqs)
        created = r.get("created_at")
        if created is not None and hasattr(created, "isoformat"):
            created = created.isoformat()
        out.append(
            {
                "id": r["id"],
                "label": r.get("label") or r["id"],
                "documentIds": docs,
                "faqIds": faqs,
                "documentCount": len(docs),
                "faqCount": len(faqs),
                "createdAt": created,
            }
        )
    return out


def takeover_conversation(conversation_id: str) -> dict[str, Any]:
    me_id = _actor_user_id()
    with _engine().begin() as conn:
        _assert_tenant_owns(conn, "conversations", conversation_id)
        row = _one(
            conn.execute(
                text("SELECT id, customer_id, status, assigned_user_id FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
        )
        if row is None:
            raise KeyError("conversation_not_found")
        conn.execute(
            text(
                """
                UPDATE conversations
                SET status = 'assigned',
                    assigned_user_id = :user_id,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": conversation_id, "user_id": me_id},
        )
        # Cancel any queued/running bot turns so take-over wins the race.
        conn.execute(
            text(
                """
                UPDATE bot_turn_jobs
                SET status = 'cancelled',
                    error = 'takeover',
                    locked_at = NULL,
                    locked_by = NULL,
                    updated_at = now()
                WHERE conversation_id = :id
                  AND status IN ('queued', 'running')
                """
            ),
            {"id": conversation_id},
        )
        _activity(
            conn,
            "conversation",
            conversation_id,
            "conversation_takeover",
            "You took over from bot",
            None,
            row["customer_id"],
        )
    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    return result


def return_conversation_to_bot(conversation_id: str) -> dict[str, Any]:
    """Agent hands the thread back so inbound WhatsApp turns enqueue bot jobs again."""
    me_id = _actor_user_id()
    with _engine().begin() as conn:
        _assert_tenant_owns(conn, "conversations", conversation_id)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, customer_id, status, assigned_user_id, bot_state
                    FROM conversations WHERE id = :id
                    """
                ),
                {"id": conversation_id},
            )
        )
        if row is None:
            raise KeyError("conversation_not_found")
        status = row["status"]
        assignee = row["assigned_user_id"]
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
        state["dialog_reset_at"] = datetime.now(timezone.utc).isoformat()

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


def _latest_twin_gate_report() -> dict[str, Any] | None:
    """Newest twin run, shaped for compiler G11. None if the table is missing."""
    try:
        from agent_core.twin import latest_gate_report

        return latest_gate_report()
    except Exception:
        return None


def get_latest_eval_report(
    *,
    bot_id: str,
    kind: str,
    prompt_version_id: str | None = None,
) -> dict[str, Any] | None:
    """Newest report for this bot whose suite matches ``kind`` (regression/redteam).

    When ``prompt_version_id`` is set, only a report filed against that exact
    draft counts — a green suite on last week's published card must not open
    the gate for this week's unpublished one.
    """
    # Tenant-scoped like its sibling `list_eval_reports`. Bot ids are unique
    # across tenants in practice, so this is latent rather than live — but it is
    # the read three publish gates consult, and "latent" is not a property to
    # leave on the gate that decides whether a card may ship.
    clauses = ["r.tenant_id = :tenant", "r.bot_id = :bot", "s.kind = :kind"]
    params: dict[str, Any] = {"tenant": _tenant(), "bot": bot_id, "kind": kind}
    if prompt_version_id:
        clauses.append("r.prompt_version_id = :pv")
        params["pv"] = prompt_version_id
    with _engine().connect() as conn:
        r = _one(
            conn.execute(
                text(
                    f"""
                    SELECT r.id, r.status, r.summary, r.suite_id, r.bot_id,
                           r.prompt_version_id, r.created_at
                    FROM eval_reports r
                    JOIN eval_suites s ON s.id = r.suite_id
                    WHERE {" AND ".join(clauses)}
                    ORDER BY r.created_at DESC
                    LIMIT 1
                    """
                ),
                params,
            )
        )
        return dict(r) if r else None


def save_eval_report(
    *,
    suite_id: str,
    bot_id: str | None,
    status: str,
    summary: dict[str, Any],
    trials: list[dict[str, Any]] | None = None,
    prompt_version_id: str | None = None,
    origin: str = "manual",
) -> dict[str, Any]:
    rid = _id("EVR")
    origin = origin if origin in {"manual", "scheduled", "canary", "upgrade"} else "manual"
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eval_reports (
                  id, tenant_id, suite_id, bot_id, prompt_version_id, status, summary, origin
                ) VALUES (
                  :id, :tenant, :suite, :bot, :pv, :status, CAST(:summary AS jsonb), :origin
                )
                """
            ),
            {
                "id": rid,
                "tenant": _tenant(),
                "suite": suite_id,
                "bot": bot_id,
                "pv": prompt_version_id,
                "status": status,
                "summary": _jsonb(summary),
                "origin": origin,
            },
        )
        for trial in trials or []:
            tid = _id("EVT")
            conn.execute(
                text(
                    """
                    INSERT INTO eval_trials (
                      id, report_id, task_id, redteam_case_id, k, passed,
                      transcript, tool_calls, crm_outcomes, grader_verdicts
                    ) VALUES (
                      :id, :report, :task, :redteam, 1, :passed,
                      CAST(:transcript AS jsonb), CAST(:tools AS jsonb),
                      CAST(:crm AS jsonb), CAST(:verdicts AS jsonb)
                    )
                    """
                ),
                {
                    "id": tid,
                    "report": rid,
                    "task": trial.get("taskId")
                    if str(trial.get("taskId") or "").startswith("task-")
                    else None,
                    "redteam": trial.get("taskId")
                    if str(trial.get("taskId") or "").startswith("rt-")
                    else None,
                    "passed": bool(trial.get("passed")),
                    "transcript": _jsonb([]),
                    "tools": _jsonb([]),
                    "crm": _jsonb({}),
                    "verdicts": _jsonb(trial.get("verdict") or {}),
                },
            )
    return {"id": rid, "status": status, "summary": summary, "botId": bot_id, "suiteId": suite_id, "origin": origin}


#: `botId` value that asks for the reports filed against no card at all.
TENANT_WIDE_REPORTS = "__none__"


def list_eval_reports(
    *, kind: str | None = None, bot_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    clauses = ["r.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": _tenant(), "n": max(1, min(int(limit), 200))}
    if kind:
        clauses.append("s.kind = :kind")
        params["kind"] = kind
    if bot_id == TENANT_WIDE_REPORTS:
        # The scheduler files tenant-wide runs with no card. Filtering a
        # shared page of fifty client-side lost them the moment fifty newer
        # card-scoped reports existed.
        clauses.append("r.bot_id IS NULL")
    elif bot_id:
        clauses.append("r.bot_id = :bot_id")
        params["bot_id"] = bot_id
    where = " AND ".join(clauses)
    with _engine().connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT r.id, r.suite_id, r.bot_id, r.status, r.summary, r.created_at, r.origin,
                           s.kind, s.name AS suite_name
                    FROM eval_reports r
                    JOIN eval_suites s ON s.id = r.suite_id
                    WHERE {where}
                    ORDER BY r.created_at DESC
                    LIMIT :n
                    """
                ),
                params,
            )
        )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "suiteId": r["suite_id"],
                "suiteName": r.get("suite_name"),
                "kind": r.get("kind"),
                "botId": r.get("bot_id"),
                "status": r["status"],
                "summary": r.get("summary") or {},
                "origin": r.get("origin") or "manual",
                "createdAt": str(r["created_at"]) if r.get("created_at") else None,
            }
        )
    return out


def list_eval_suites(*, kind: str | None = None) -> list[dict[str, Any]]:
    clauses = ["tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": _tenant()}
    if kind:
        clauses.append("kind = :kind")
        params["kind"] = kind
    where = " AND ".join(clauses)
    with _engine().connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT id, kind, name, description, created_at
                    FROM eval_suites
                    WHERE {where}
                    ORDER BY kind, id
                    """
                ),
                params,
            )
        )
        return [dict(r) for r in rows]


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


def send_conversation_message(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    text_value = (payload.get("text") or "").strip()
    if not text_value:
        raise ValueError("empty_message")
    me_id = _actor_user_id()
    provider_ref: str | None = None
    delivery_status = "sent"
    msg_id = _id("MSG")
    now = datetime.now(timezone.utc)

    _LOCK_SQL = """
        SELECT cv.id, cv.customer_id, cv.status, cv.assigned_user_id, cv.channel,
               c.phone_primary, c.phone_alt,
               (
                 SELECT MAX(COALESCE(m.sent_at, m.created_at))
                 FROM messages m
                 WHERE m.conversation_id = cv.id
                   AND m.sender = 'customer'
                   -- Seed/demo rows have no Meta wamid; Meta's 24h window only
                   -- opens after a real inbound WhatsApp message.
                   AND m.provider_ref IS NOT NULL
               ) AS last_customer_at
        FROM conversations cv
        JOIN customers c ON c.id = cv.customer_id
        WHERE cv.id = :id
        FOR UPDATE OF cv
    """

    def _guards(row: dict[str, Any]) -> tuple[str, bool]:
        if row["status"] == "bot" and row["assigned_user_id"] != me_id:
            raise ValueError("bot_still_handling")
        channel = row["channel"]
        is_mine = row["assigned_user_id"] == me_id
        if channel == "whatsapp":
            if not is_mine:
                raise ValueError("take_over_required")
            last_customer_at = row["last_customer_at"]
            if isinstance(last_customer_at, str):
                last_customer_at = datetime.fromisoformat(last_customer_at.replace("Z", "+00:00"))
            if last_customer_at is None:
                raise ValueError("whatsapp_window_closed")
            if getattr(last_customer_at, "tzinfo", None) is None:
                last_customer_at = last_customer_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - last_customer_at.astimezone(timezone.utc)
            if age > timedelta(hours=24):
                raise ValueError("whatsapp_window_closed")
        return channel, is_mine

    def _finalize(conn: Any, row: dict[str, Any]) -> None:
        if row["assigned_user_id"] is None or row["assigned_user_id"] == me_id:
            conn.execute(
                text(
                    """
                    UPDATE conversations
                    SET status = 'assigned',
                        assigned_user_id = :user_id,
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": conversation_id, "user_id": me_id},
            )
        else:
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

    with _engine().begin() as conn:
        row = _one(conn.execute(text(_LOCK_SQL), {"id": conversation_id}))
        if row is None:
            raise KeyError("conversation_not_found")
        channel, _is_mine = _guards(row)

        if channel == "whatsapp":
            import contact_policy

            last_customer_at = row["last_customer_at"]
            if isinstance(last_customer_at, str):
                last_customer_at = datetime.fromisoformat(last_customer_at.replace("Z", "+00:00"))
            in_window = False
            if last_customer_at is not None:
                at = last_customer_at
                if getattr(at, "tzinfo", None) is None:
                    at = at.replace(tzinfo=timezone.utc)
                in_window = datetime.now(timezone.utc) - at.astimezone(timezone.utc) <= timedelta(hours=24)
            purpose = "in_session" if in_window else "outreach"
            actor = None
            try:
                import actor_context
                actor = actor_context.get_actor_user_id()
            except Exception:
                actor = me_id
            import whatsapp as wa
            import whatsapp_outbound as wa_out

            to_phone = wa.normalize_phone(contact_policy.chosen_phone(row))
            if not to_phone:
                raise ValueError("whatsapp_missing_recipient")
            contact_policy.require_admit(
                conn,
                customer_id=row["customer_id"],
                channel="whatsapp",
                purpose=purpose,
                session_key=conversation_id,
                source="inbox_reply",
                related_id=msg_id,
                actor_kind="human",
                actor_user_id=actor,
                endpoint=to_phone,
            )

            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                    VALUES (:id, :conversation_id, 'agent', :body, 'sending', NULL, :sent_at)
                    """
                ),
                {"id": msg_id, "conversation_id": conversation_id, "body": text_value, "sent_at": now},
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
            _finalize(conn, row)
        else:
            import contact_policy

            contact_policy.require_admit(
                conn,
                customer_id=row["customer_id"],
                channel=channel,
                purpose="outreach",
                session_key=conversation_id,
                source="inbox_reply",
                related_id=msg_id,
                actor_kind="human",
                actor_user_id=me_id,
                endpoint=contact_policy.chosen_phone(row),
            )
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                    VALUES (:id, :conversation_id, 'agent', :body, :delivery_status, :provider_ref, :sent_at)
                    """
                ),
                {
                    "id": msg_id,
                    "conversation_id": conversation_id,
                    "body": text_value,
                    "delivery_status": delivery_status,
                    "provider_ref": provider_ref,
                    "sent_at": now,
                },
            )
            _finalize(conn, row)

    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    return result


def _digits_phone_exact_sql() -> str:
    return """
      regexp_replace(COALESCE(c.phone_primary, ''), '[^0-9]', '', 'g') = :phone
      OR regexp_replace(COALESCE(c.phone_alt, ''), '[^0-9]', '', 'g') = :phone
    """


def _digits_phone_tail10_sql() -> str:
    """Legacy local-format fallback, restricted to a bare 10-digit national number.

    A plain last-10 comparison matched across country codes: a stored
    ``+91 98765 43210`` and an inbound ``+1 98765 43210`` share their last ten
    digits and resolved to the same customer. A bare "is a suffix of" test is
    no better — ``19876543210`` really is a suffix of ``919876543210``.

    The only shape this fallback exists for is a legacy row stored as the bare
    10-digit national number, so that is exactly what it allows: the shorter
    side must be 10 digits and must be the tail of the longer one. Anything
    with two different country codes has a shorter side of 11+ and cannot match.
    """
    return " OR ".join(_tail10_predicate(col) for col in ("c.phone_primary", "c.phone_alt"))


def _tail10_predicate(column: str) -> str:
    digits = f"regexp_replace(COALESCE({column}, ''), '[^0-9]', '', 'g')"
    return f"""
      (
        length({digits}) >= 10
        AND least(length({digits}), length(:phone)) = 10
        AND (
          {digits} = right(:phone, 10)
          OR :phone = right({digits}, 10)
        )
      )
    """


def _find_customer_by_phone(conn: Any, phone: str) -> dict[str, Any] | None:
    # Digits only: the tail fallback embeds :phone in a LIKE pattern, so a `%`
    # or `_` surviving from a caller that skipped normalisation would turn the
    # suffix match back into a wildcard scan.
    phone = re.sub(r"\D+", "", phone or "")
    if len(phone) < 10:
        return None
    exact = _rows(
        conn.execute(
            text(
                f"""
                SELECT id, name, phone_primary, phone_alt
                FROM customers c
                WHERE {_digits_phone_exact_sql()}
                ORDER BY c.updated_at DESC NULLS LAST, c.id
                LIMIT 3
                """
            ),
            {"phone": phone},
        )
    )
    if exact:
        if len(exact) > 1:
            logger.warning("exact phone match returned %s customers for …%s", len(exact), phone[-4:])
        return exact[0]
    # Demoted last-10 fallback — fail closed on ambiguous distinct customers.
    tails = _rows(
        conn.execute(
            text(
                f"""
                SELECT id, name, phone_primary, phone_alt
                FROM customers c
                WHERE {_digits_phone_tail10_sql()}
                ORDER BY c.updated_at DESC NULLS LAST, c.id
                LIMIT 3
                """
            ),
            {"phone": phone},
        )
    )
    if not tails:
        return None
    if len({r["id"] for r in tails}) > 1:
        logger.warning("ambiguous last-10 phone match for …%s — failing closed", phone[-4:])
        return None
    return tails[0]


def find_customer_by_phone(phone: str) -> dict[str, Any] | None:
    """Public wrapper — PSTN / WhatsApp caller identity resolution."""
    digits = re.sub(r"\D+", "", phone or "")
    if not digits:
        return None
    with _engine().connect() as conn:
        return _find_customer_by_phone(conn, digits)


def _ensure_whatsapp_customer(conn: Any, phone: str, profile_name: str | None) -> dict[str, Any]:
    existing = _find_customer_by_phone(conn, phone)
    if existing:
        return existing
    # Derive the ids from the FULL normalized number. Keying on the last 10 (or
    # 6) digits collided across country codes — +91 98765 43210 and +1 987 654
    # 3210 both produced cust-wa-9876543210 — and the DO UPDATE below then
    # overwrote the first person's phone and name with the second's, merging two
    # customers into one record.
    customer_id = f"cust-wa-{phone}" if phone else _id("cust-wa").lower()
    account_id = f"AC-WA-{phone}" if phone else _id("AC")
    name = (profile_name or f"WhatsApp {phone[-4:]}").strip() or f"WhatsApp {phone[-4:]}"
    conn.execute(
        text(
            """
            INSERT INTO customers
              (id, tenant_id, assigned_user_id, name, phone_primary, risk, preferred_window, dnd, segment)
            VALUES
              (:id, :tenant_id, NULL, :name, :phone, 'medium', '10:00-19:00 IST', false, 'retail')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": customer_id, "tenant_id": _tenant(), "name": name, "phone": phone},
    )
    # Prefer personal-loan if present, else any product.
    product = _one(conn.execute(text("SELECT id FROM products WHERE id = 'personal-loan'")))
    if product is None:
        product = _one(conn.execute(text("SELECT id FROM products ORDER BY id LIMIT 1")))
    if product is None:
        raise ValueError("no_products_seeded")
    conn.execute(
        text(
            """
            INSERT INTO accounts (id, customer_id, product_id, outstanding, dpd, status)
            VALUES (:id, :customer_id, :product_id, 0, 0, 'active')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": account_id, "customer_id": customer_id, "product_id": product["id"]},
    )
    found = _find_customer_by_phone(conn, phone)
    if found is None:
        raise ValueError("customer_create_failed")
    return found


def _open_whatsapp_conversation(conn: Any, customer_id: str) -> str:
    """Return an existing WhatsApp conversation for the customer, or create one (status=bot)."""
    row = _one(
        conn.execute(
            text(
                """
                SELECT id FROM conversations
                WHERE customer_id = :customer_id AND channel = 'whatsapp'
                ORDER BY COALESCE(updated_at, created_at) DESC, id
                LIMIT 1
                """
            ),
            {"customer_id": customer_id},
        )
    )
    if row:
        return row["id"]

    account = _one(
        conn.execute(
            text(
                """
                SELECT id FROM accounts
                WHERE customer_id = :customer_id
                ORDER BY created_at, id
                LIMIT 1
                """
            ),
            {"customer_id": customer_id},
        )
    )
    bot = _one(conn.execute(text("SELECT id FROM bots WHERE id = 'collectionsbot-v2-4'")))
    if bot is None:
        bot = _one(conn.execute(text("SELECT id FROM bots ORDER BY id LIMIT 1")))
    if bot is None:
        raise ValueError("no_bots_seeded")

    interaction_id = _id("IX")
    conversation_id = _id("CV")
    now = datetime.now(timezone.utc)
    conn.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, account_id, handler_kind, handler_bot_id,
               channel, direction, status, sentiment_label, avg_sentiment, started_at, source_payload)
            VALUES
              (:id, :tenant_id, :customer_id, :account_id, 'bot', :bot_id,
               'whatsapp', 'inbound', 'active', 'neutral', 0, :started_at, CAST(:payload AS jsonb))
            """
        ),
        {
            "id": interaction_id,
            "tenant_id": _tenant(),
            "customer_id": customer_id,
            "account_id": account["id"] if account else None,
            "bot_id": bot["id"],
            "started_at": now,
            "payload": "{}",
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO conversations
              (id, interaction_id, customer_id, assigned_user_id, status, channel, created_at, updated_at)
            VALUES
              (:id, :interaction_id, :customer_id, NULL, 'bot', 'whatsapp', :now, :now)
            """
        ),
        {
            "id": conversation_id,
            "interaction_id": interaction_id,
            "customer_id": customer_id,
            "now": now,
        },
    )
    return conversation_id


def touch_interaction_sentiment(
    conn: Any,
    interaction_id: str | None,
    text_value: str,
    *,
    score: float | None = None,
) -> None:
    """Public alias for _touch_interaction_sentiment (see record_activity)."""
    _touch_interaction_sentiment(conn, interaction_id, text_value, score=score)


def _touch_interaction_sentiment(
    conn: Any,
    interaction_id: str | None,
    text_value: str,
    *,
    score: float | None = None,
) -> None:
    """Blend latest customer-turn sentiment into the linked interaction (Inbox header).

    ``score`` lets a caller that has already classified the turn pass its result
    in rather than have the English lexicon re-derive one from the raw text —
    which on a Hindi or code-switched turn returns 0.00 regardless of what was
    said. The webhook ingest path deliberately does not pass it: it runs inside
    the inbound request transaction, where an Azure call risks provider
    redelivery, and bot_worker re-touches the same interaction moments later
    with the enriched score.
    """
    if not interaction_id:
        return
    from agent_core.sentiment import estimate_sentiment, sentiment_label

    score = estimate_sentiment(text_value) if score is None else float(score)
    row = _one(
        conn.execute(
            text("SELECT avg_sentiment FROM interactions WHERE id = :id"),
            {"id": interaction_id},
        )
    )
    if row is None:
        return
    prev = row.get("avg_sentiment")
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    blended = score if prev_f is None else round(0.35 * prev_f + 0.65 * score, 3)
    label = sentiment_label(blended)
    conn.execute(
        text(
            """
            UPDATE interactions
            SET avg_sentiment = :avg,
                sentiment_label = :label
            WHERE id = :id
            """
        ),
        {"id": interaction_id, "avg": blended, "label": label},
    )


def _ingest_inbound_whatsapp_message(
    conn: Any,
    *,
    wa_message_id: str,
    from_phone: str,
    body: str,
    profile_name: str | None,
    sent_at: datetime,
) -> dict[str, Any]:
    customer = _ensure_whatsapp_customer(conn, from_phone, profile_name)
    conversation_id = _open_whatsapp_conversation(conn, customer["id"])
    msg_id = _id("MSG")
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                    VALUES (:id, :conversation_id, 'customer', :body, 'delivered', :provider_ref, :sent_at)
                    """
                ),
                {
                    "id": msg_id,
                    "conversation_id": conversation_id,
                    "body": body or "",
                    "provider_ref": wa_message_id,
                    "sent_at": sent_at,
                },
            )
    except Exception as exc:
        # Unique provider_ref is the idempotency key — treat conflicts as
        # duplicates. Detect via SQLSTATE 23505, not driver message text: the
        # wording is psycopg-version- and locale-dependent, and substring
        # matching on "unique" also swallowed unrelated constraint failures.
        if not _is_unique_violation(exc):
            raise
        existing = _one(
            conn.execute(
                text("SELECT id, conversation_id FROM messages WHERE provider_ref = :ref"),
                {"ref": wa_message_id},
            )
        )
        if existing:
            return {
                "status": "duplicate",
                "messageId": existing["id"],
                "conversationId": existing["conversation_id"],
            }
        raise

    # Pref: inbound stays bot until take-over / escalate (do not flip to needs_human).
    conv_row = _one(
        conn.execute(
            text(
                """
                UPDATE conversations
                SET updated_at = now(),
                    status = CASE
                      WHEN assigned_user_id IS NOT NULL THEN status
                      WHEN status IN ('needs_human', 'escalated', 'assigned') THEN status
                      ELSE 'bot'
                    END
                WHERE id = :id
                RETURNING id, interaction_id, status, assigned_user_id
                """
            ),
            {"id": conversation_id},
        )
    )
    _activity(
        conn,
        "conversation",
        conversation_id,
        "whatsapp_inbound",
        "Inbound WhatsApp message",
        (body or "")[:120],
        customer["id"],
    )
    if conv_row and conv_row.get("interaction_id"):
        _touch_interaction_sentiment(conn, conv_row.get("interaction_id"), body or "")

    job_info = None
    if (
        conv_row
        and conv_row.get("status") == "bot"
        and not conv_row.get("assigned_user_id")
    ):
        try:
            import bot_jobs

            # Savepoint: an enqueue failure otherwise aborts the shared webhook
            # transaction, and the fallback _activity write below would then run
            # on a broken connection.
            with conn.begin_nested():
                job_info = bot_jobs.enqueue_bot_turn(
                    conn,
                    conversation_id=conversation_id,
                    customer_id=customer["id"],
                    trigger_message_id=msg_id,
                    trigger_provider_ref=wa_message_id,
                    interaction_id=conv_row.get("interaction_id"),
                    channel="whatsapp",
                )
        except Exception:
            # Never fail Meta webhook because the queue insert failed — log via activity.
            _activity(
                conn,
                "conversation",
                conversation_id,
                "bot_enqueue_failed",
                "Failed to enqueue bot turn",
                wa_message_id,
                customer["id"],
            )

    out: dict[str, Any] = {
        "status": "ok",
        "messageId": msg_id,
        "conversationId": conversation_id,
        "customerId": customer["id"],
    }
    if job_info:
        out["botJobId"] = job_info.get("id")
    return out


# Monotonic delivery lifecycle. Anything not listed (including NULL / "sending")
# ranks 0, so the first real callback always applies.
_DELIVERY_RANK = {"sent": 1, "delivered": 2, "read": 3}


def _apply_whatsapp_status(
    conn: Any,
    *,
    wa_message_id: str,
    status: str,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    mapping = {
        "sent": "sent",
        "delivered": "delivered",
        "read": "read",
        "failed": "failed",
    }
    delivery = mapping.get(status)
    if not delivery:
        return {"status": "ignored", "reason": "unknown_status"}
    row = _one(
        conn.execute(
            text(
                """
                SELECT m.id, m.delivery_status, cv.customer_id, c.tenant_id
                FROM messages m
                JOIN conversations cv ON cv.id = m.conversation_id
                LEFT JOIN customers c ON c.id = cv.customer_id
                WHERE m.provider_ref = :ref
                """
            ),
            {"ref": wa_message_id},
        )
    )
    if row is None:
        return {"status": "missing", "providerRef": wa_message_id}

    # The receipt is appended before the monotonic guard below, and deliberately.
    # That guard exists to stop a late "sent" dragging an already-read message
    # backwards *in the Inbox*, which is a display concern. The reach estimator
    # wants the opposite: every transition, in the order the provider reports
    # it, because "delivered at 09:02, read at 21:40" is the signal that says
    # when this borrower is actually reachable — and discarding the out-of-order
    # ones would systematically drop exactly the slow reads that carry it.
    if row.get("customer_id") and row.get("tenant_id"):
        import delivery_receipts

        delivery_receipts.record(
            conn,
            tenant_id=str(row["tenant_id"]),
            customer_id=str(row["customer_id"]),
            channel="whatsapp",
            provider="meta",
            provider_ref=wa_message_id,
            message_id=str(row["id"]),
            related_id=str(row["id"]),
            state=delivery,
            reason=(errors[0].get("title") if errors and isinstance(errors[0], dict) else None),
        )

    # Meta delivers sent / delivered / read callbacks asynchronously and they
    # arrive out of order often enough to matter: a late "sent" used to drag an
    # already-read message backwards in the Inbox. Only accept a status that
    # advances the lifecycle. "failed" is terminal and always wins.
    current = str(row["delivery_status"] or "")
    if delivery != "failed" and _DELIVERY_RANK.get(delivery, 0) <= _DELIVERY_RANK.get(current, 0):
        return {
            "status": "ignored",
            "reason": "out_of_order",
            "messageId": row["id"],
            "delivery": current,
        }
    conn.execute(
        text("UPDATE messages SET delivery_status = :delivery WHERE id = :id"),
        {"delivery": delivery, "id": row["id"]},
    )
    if delivery == "failed" and errors:
        # Persist Meta's reason on the outbound job so operators see 131047
        # (outside 24h window) instead of a silent "failed" tick.
        detail_bits: list[str] = []
        for err in errors[:3]:
            if not isinstance(err, dict):
                continue
            code = err.get("code")
            title = err.get("title") or err.get("message") or ""
            details = ""
            ed = err.get("error_data")
            if isinstance(ed, dict):
                details = str(ed.get("details") or "")
            bit = " ".join(
                p for p in (f"code={code}" if code is not None else "", str(title), details) if p
            ).strip()
            if bit:
                detail_bits.append(bit[:400])
        err_text = (" | ".join(detail_bits) or "whatsapp_delivery_failed")[:2000]
        logger.warning(
            "whatsapp delivery failed message=%s provider_ref=%s err=%s",
            row["id"],
            wa_message_id,
            err_text,
        )
        conn.execute(
            text(
                """
                UPDATE whatsapp_outbound_jobs
                SET error = :error, updated_at = now()
                WHERE message_id = :message_id
                """
            ),
            {"error": err_text, "message_id": row["id"]},
        )
    return {"status": "ok", "messageId": row["id"], "delivery": delivery}


def process_whatsapp_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle Meta WhatsApp Cloud API webhook POST body (messages + statuses)."""
    import whatsapp as wa

    results: list[dict[str, Any]] = []
    with _engine().begin() as conn:
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                contacts = {c.get("wa_id"): c for c in (value.get("contacts") or []) if c.get("wa_id")}

                for msg in value.get("messages") or []:
                    wa_id = msg.get("id")
                    from_phone = wa.normalize_phone(msg.get("from"))
                    if not wa_id or not from_phone:
                        results.append({"status": "skipped", "reason": "missing_id_or_from"})
                        continue
                    msg_type = msg.get("type") or "text"
                    body = ""
                    if msg_type == "text":
                        body = ((msg.get("text") or {}).get("body")) or ""
                    elif msg_type == "button":
                        body = ((msg.get("button") or {}).get("text")) or ""
                    elif msg_type == "interactive":
                        interactive = msg.get("interactive") or {}
                        body = (
                            ((interactive.get("button_reply") or {}).get("title"))
                            or ((interactive.get("list_reply") or {}).get("title"))
                            or ""
                        )
                    else:
                        body = f"[{msg_type} message]"
                    ts_raw = msg.get("timestamp")
                    try:
                        sent_at = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc) if ts_raw else datetime.now(timezone.utc)
                    except (TypeError, ValueError, OSError):
                        sent_at = datetime.now(timezone.utc)
                    contact = contacts.get(from_phone) or contacts.get(msg.get("from")) or {}
                    profile_name = ((contact.get("profile") or {}).get("name")) if isinstance(contact, dict) else None
                    # Savepoint per message: Meta batches several messages into
                    # one POST and does not support partial acknowledgement, so
                    # one bad item aborting the transaction would discard every
                    # sibling message and they would never be redelivered
                    # individually.
                    nested = conn.begin_nested()
                    try:
                        result = _ingest_inbound_whatsapp_message(
                            conn,
                            wa_message_id=wa_id,
                            from_phone=from_phone,
                            body=body,
                            profile_name=profile_name,
                            sent_at=sent_at,
                        )
                        nested.commit()
                    except Exception:
                        nested.rollback()
                        logger.exception(
                            "whatsapp inbound ingest failed wa_message_id=%s", wa_id
                        )
                        result = {"status": "error", "waMessageId": wa_id}
                    results.append(result)

                for st in value.get("statuses") or []:
                    wa_id = st.get("id")
                    status = st.get("status")
                    if not wa_id or not status:
                        continue
                    nested = conn.begin_nested()
                    try:
                        errs = st.get("errors") if isinstance(st.get("errors"), list) else None
                        result = _apply_whatsapp_status(
                            conn,
                            wa_message_id=wa_id,
                            status=status,
                            errors=errs,
                        )
                        nested.commit()
                    except Exception:
                        nested.rollback()
                        logger.exception(
                            "whatsapp status update failed wa_message_id=%s status=%s",
                            wa_id,
                            status,
                        )
                        result = {"status": "error", "waMessageId": wa_id}
                    results.append(result)

    return {"ok": True, "results": results}

