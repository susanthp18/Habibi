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
    _assert_tenant_owns_customer,
    _db,
    _id,
    _idempotent_response,
    _one,
    _rows,
    _store_idempotent_response,
    _tenant,
    _vis_params,
    clamp_list_limit,
)
from agent_core.clock import utc_now

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
    age_h = (utc_now() - last_customer_at.astimezone(timezone.utc)).total_seconds() / 3600
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


def _inbox_contactable(conn: Any, customer_id: str, channel: str = "whatsapp") -> tuple[bool, str | None]:
    """The gate's verdict for this thread, and why when it is a refusal.

    When the gate itself cannot be read this is ``(False, "policy_unavailable")``
    and the failure is logged. It used to fall back to a DND flag and a window
    check -- a second, weaker copy of the gate that answered "contactable" for
    a borrower the real gate would have refused on frequency or consent.
    """
    try:
        import contact_policy

        decision = contact_policy.evaluate(
            conn,
            customer_id=customer_id,
            channel=channel,
            purpose="outreach",
        )
        return bool(decision.allowed), (None if decision.allowed else str(decision.reason or "refused"))
    except Exception:
        logger.exception("contact policy unreadable for inbox thread customer=%s", customer_id)
        return False, "policy_unavailable"


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

    contactable, contactable_reason = _inbox_contactable(conn, customer_id)
    return {
        "riskLevel": _inbox_risk(risk),
        "contactableNow": contactable,
        "contactableReason": contactable_reason,
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
    with_context: bool = True,
) -> dict[str, Any]:
    last_msg = None
    for item in reversed(messages):
        if item.get("kind") != "system":
            last_msg = item
            break
    last_from = (last_msg or {}).get("sender") or "bot"
    if last_from not in {"customer", "bot", "agent", "system"}:
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
    if isinstance(updated, datetime):
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
        # The context is four reads and a Gate evaluation per thread; the list
        # polls every few seconds, so only the thread detail carries it.
        "context": _thread_context(
            conn,
            row["customer_id"],
            row["account_id"],
            row["risk"],
            bool(row["dnd"]),
            row["preferred_window"],
            float(row["outstanding"] or 0),
            row["dpd"],
        )
        if with_context
        else None,
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
                    with_context=False,
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


def send_conversation_message(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    text_value = (payload.get("text") or "").strip()
    if not text_value:
        raise ValueError("empty_message")
    me_id = _actor_user_id()
    provider_ref: str | None = None
    delivery_status = "sent"
    msg_id = _id("MSG")
    now = utc_now()

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
            age = utc_now() - last_customer_at.astimezone(timezone.utc)
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
                in_window = utc_now() - at.astimezone(timezone.utc) <= timedelta(hours=24)
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


def send_customer_outreach(
    customer_id: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Admit, create a thread if missing, then the inbox send path.

    WhatsApp first-touch uses purpose=outreach (no 24h session window). The
    provider is still ``whatsapp_outbound.enqueue_agent_send``.
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
        if channel == "whatsapp":
            import whatsapp as wa
            import whatsapp_outbound as wa_out

            to_phone = wa.normalize_phone(contact_policy.chosen_phone(existing))
            if not to_phone:
                raise ValueError("whatsapp_missing_recipient")
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
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, sent_at)
                    VALUES (:id, :conversation_id, 'agent', :body, 'sent', :sent_at)
                    """
                ),
                {
                    "id": msg_id,
                    "conversation_id": conversation_id,
                    "body": text_value,
                    "sent_at": now,
                },
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
