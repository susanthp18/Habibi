"""Callbacks: list, create, patch, reminders (WP-036 peel).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import contact_window
from agent_core import clock
from sqlalchemy import text

import db_core
from db_core import (
    _account_tail,
    _activity,
    _assert_tenant_owns,
    _ensure_customer,
    _first_account_id,
    _id,
    _idempotent_response,
    _one,
    _rows,
    _sql,
    _store_idempotent_response,
    _tenant,
    _user_name,
    _vis_params,
    clamp_list_limit,
    clamp_offset,
)
from typing import Any
from agent_core.clock import utc_now


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


CB_REASONS = {
    "payment_discussion",
    "dispute_followup",
    "document_query",
    "hardship_review",
    "upsell_interest",
    "general",
}

CB_DISPOSITIONS = {"reached", "no_answer", "ptp_captured", "not_interested", "callback_again"}

def _callback_reason(reason: str | None) -> str:
    if reason in CB_REASONS:
        return reason  # type: ignore[return-value]
    return "general"

def _callback_disposition(disposition: str | None) -> str | None:
    return disposition if disposition in CB_DISPOSITIONS else None

def _callback_window(mins: int | None) -> int:
    if mins in {30, 60, 120}:
        return mins  # type: ignore[return-value]
    if mins is None or mins <= 45:
        return 30
    if mins <= 90:
        return 60
    return 120

def _callback_source(handler_kind: str | None, interaction_channel: str | None, has_interaction: bool) -> str:
    """Derive screen source from the origin interaction (callbacks have no source column)."""
    if not has_interaction or handler_kind == "human":
        return "agent"
    if interaction_channel in {"chat", "whatsapp", "sms", "email"}:
        return "bot_chat"
    return "bot_voice"

def _callback_reminder_channel(channel: str | None) -> str:
    if channel in {"whatsapp", "sms", "email"}:
        return channel  # type: ignore[return-value]
    return "whatsapp"

def _callback_reminder_status(status: str | None) -> str:
    if status in {"queued", "sent", "acknowledged"}:
        return status  # type: ignore[return-value]
    if status == "scheduled":
        return "queued"
    return "queued"

def _outside_preferred_window(scheduled_at: str, preferred_window: str | None) -> bool:
    """True when the scheduled IST hour falls outside HH:MM–HH:MM preferred window.

    The rule itself lives in :mod:`contact_window` because ``agent_core``'s
    code-mode script runs the same check and cannot import this module. It used
    to hold its own copy, and the copy's default bounds had drifted.
    """
    return contact_window.outside_preferred_window(scheduled_at, preferred_window)

def _callback_dnd_active(
    customer_dnd: bool,
    dnd_registry: bool,
    preferred_window: str | None,
    scheduled_at: str,
) -> bool:
    """Is this callback slot blocked — by either DND store, or by the window?

    Two stores record "do not disturb" and this read only ever consulted one.
    ``customers.dnd`` is the operator's own flag; ``consent_records.dnd_registry``
    is the national registry. ``contact_policy.admit`` ORs them and so does the
    consent screen, so a registry-flagged borrower was refused by the contact
    Gate and shown as callable on the callback board.

    ``dnd_registry`` is required rather than defaulted. A default of ``False``
    would let a caller that forgets to join ``consent_records`` keep exactly the
    behaviour this fixes, and nothing would fail.
    """
    return (
        bool(customer_dnd)
        or bool(dnd_registry)
        or _outside_preferred_window(scheduled_at, preferred_window)
    )

def _callback_event_tone(kind: str | None, note: str | None) -> str | None:
    if kind in {"callback_created", "callback_reminder_created"}:
        return "info"
    if kind == "callback_updated":
        if note == "completed":
            return "success"
        if note == "missed":
            return "danger"
        if note == "cancelled":
            return "warn"
        return "info"
    return None

def _callback_events(conn: Any, callback_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not callback_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.at, ae.label, ae.tone, ae.kind, ae.note,
                       u.name AS actor
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'callback' AND ae.entity_id = ANY(:ids)
                ORDER BY ae.at
                """
            ),
            {"ids": callback_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(
            {
                "at": r["at"],
                "label": r["label"],
                "actor": r["actor"],
                "tone": r["tone"] or _callback_event_tone(r["kind"], r["note"]),
            }
        )
    return grouped

def _callback_reminders(conn: Any, callback_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not callback_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT callback_id, channel, scheduled_at, sent_at, status, created_at
                FROM callback_reminders
                WHERE callback_id = ANY(:ids)
                ORDER BY COALESCE(sent_at, scheduled_at, created_at)
                """
            ),
            {"ids": callback_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["callback_id"], []).append(
            {
                "at": r["sent_at"] or r["scheduled_at"] or r["created_at"],
                "channel": _callback_reminder_channel(r["channel"]),
                "status": _callback_reminder_status(r["status"]),
            }
        )
    return grouped

def list_callbacks(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Callback & Scheduling Manager feed (richer than the Phase 3A write contract)."""
    engine = _db().engine
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT cb.id, cb.customer_id, c.name AS customer_name, cb.account_id,
                           cb.reason, cb.scheduled_at, cb.window_mins, cb.dnd_active,
                           cb.status, cb.disposition, cb.priority, cb.transcript_snippet,
                           cb.outcome_notes, cb.interaction_id, cb.created_at,
                           c.timezone AS customer_timezone, c.preferred_window,
                           c.dnd AS customer_dnd,
                           COALESCE(cr.dnd_registry, false) AS dnd_registry,
                           u.name AS assignee, t.name AS queue,
                           i.channel AS interaction_channel, i.handler_kind
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN consent_records cr ON cr.customer_id = cb.customer_id
                    LEFT JOIN users u ON u.id = cb.assignee_user_id
                    LEFT JOIN teams t ON t.id = cb.team_id
                    LEFT JOIN interactions i ON i.id = cb.interaction_id
                    ORDER BY cb.scheduled_at, cb.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
            )
        )
        ids = [r["id"] for r in rows]
        events = _callback_events(conn, ids)
        reminders = _callback_reminders(conn, ids)
        result = []
        for r in rows:
            preferred = r["preferred_window"] or contact_window.DEFAULT_WINDOW
            scheduled = r["scheduled_at"]
            customer_dnd = bool(r["customer_dnd"])
            dnd_registry = bool(r["dnd_registry"])
            dnd_active = _callback_dnd_active(customer_dnd, dnd_registry, preferred, scheduled)
            created = r["created_at"]
            evts = events.get(r["id"]) or [
                {"at": created, "label": "Callback scheduled", "actor": None, "tone": "info"}
            ]
            result.append(
                {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountId": r["account_id"] or "",
                    "accountTail": _account_tail(r["account_id"]) or "",
                    "reason": _callback_reason(r["reason"]),
                    "scheduledAt": scheduled,
                    "windowMins": _callback_window(r["window_mins"]),
                    "customerTimezone": r["customer_timezone"] or f"{clock.DEFAULT_TIMEZONE} (IST)",
                    "preferredWindow": preferred,
                    "customerDnd": customer_dnd,
                    "dndActive": dnd_active,
                    "source": _callback_source(
                        r["handler_kind"], r["interaction_channel"], bool(r["interaction_id"])
                    ),
                    "assignee": r["assignee"] or "Unassigned",
                    "queue": r["queue"] or "Unassigned",
                    "priority": r["priority"] or "normal",
                    "status": r["status"],
                    "reminders": reminders.get(r["id"]) or [],
                    "transcriptSnippet": r["transcript_snippet"] or "",
                    "originConversationId": r["interaction_id"],
                    "events": evts,
                    "createdAt": created,
                    "disposition": _callback_disposition(r["disposition"]),
                    "outcomeNotes": r["outcome_notes"],
                }
            )
        return result

def create_callback(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    engine = _db().engine
    endpoint = "POST /callbacks"
    with engine.begin() as conn:
        return _create_callback(conn, payload, idempotency_key, endpoint)

def _create_callback(
    conn: Any,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    endpoint: str = "POST /callbacks",
) -> dict[str, Any]:
    """Connection-scoped body of :func:`create_callback` — see _create_promise."""
    cached = _idempotent_response(conn, idempotency_key, endpoint)
    if cached:
        return cached
    customer_id = payload["customerId"]
    _ensure_customer(conn, customer_id)
    cust = _one(
        conn.execute(
            text(
                """
                SELECT c.dnd, c.preferred_window,
                       COALESCE(cr.dnd_registry, false) AS dnd_registry
                FROM customers c
                LEFT JOIN consent_records cr ON cr.customer_id = c.id
                WHERE c.id = :id
                """
            ),
            {"id": customer_id},
        )
    )
    reason = payload["reason"]
    if reason not in CB_REASONS:
        raise ValueError(f"invalid_reason: {reason}")

    assignee_user_id = payload.get("assigneeUserId")
    if assignee_user_id is not None:
        if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": assignee_user_id}).fetchone():
            raise KeyError(f"user_not_found: {assignee_user_id}")

    team_id = payload.get("teamId") or "retail-collections"
    if not conn.execute(text("SELECT 1 FROM teams WHERE id = :id"), {"id": team_id}).fetchone():
        raise KeyError(f"team_not_found: {team_id}")

    scheduled_at = payload["scheduledAt"]
    window_mins = _callback_window(payload.get("windowMins") or 30)
    dnd_active = _callback_dnd_active(
        bool(cust and cust["dnd"]),
        bool(cust and cust["dnd_registry"]),
        cust["preferred_window"] if cust else None,
        scheduled_at,
    )

    callback_id = _id("CB")
    conn.execute(
        text(
            """
            INSERT INTO callbacks
              (id, customer_id, account_id, interaction_id, assignee_user_id, team_id,
               reason, scheduled_at, window_mins, dnd_active, status, priority,
               transcript_snippet, sla_due_at)
            VALUES
              (:id, :customer_id, :account_id, :interaction_id, :assignee_user_id, :team_id,
               :reason, :scheduled_at, :window_mins, :dnd_active, 'scheduled', :priority,
               :transcript_snippet, :scheduled_at)
            """
        ),
        {
            "id": callback_id,
            "customer_id": customer_id,
            "account_id": payload.get("accountId") or _first_account_id(conn, customer_id),
            "interaction_id": payload.get("interactionId"),
            "assignee_user_id": assignee_user_id,
            "team_id": team_id,
            "reason": reason,
            "scheduled_at": scheduled_at,
            "window_mins": window_mins,
            "dnd_active": dnd_active,
            "priority": payload.get("priority") or "normal",
            "transcript_snippet": payload.get("transcriptSnippet"),
        },
    )
    _activity(conn, "callback", callback_id, "callback_created", "Callback scheduled", reason, customer_id)
    response = {"id": callback_id, "status": "scheduled"}
    _store_idempotent_response(conn, idempotency_key, endpoint, response)
    return response

# A callback's status is a state machine. `completed` is terminal; a missed or
# cancelled slot comes back only by being rescheduled.
_CALLBACK_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"reminded", "in_progress", "completed", "missed", "rescheduled", "cancelled"}),
    "reminded": frozenset({"in_progress", "completed", "missed", "rescheduled", "cancelled"}),
    "rescheduled": frozenset({"scheduled", "reminded", "in_progress", "completed", "missed", "cancelled"}),
    "in_progress": frozenset({"completed", "missed", "rescheduled"}),
    "missed": frozenset({"rescheduled", "completed", "cancelled"}),
    "cancelled": frozenset({"rescheduled"}),
}


def patch_callback(callback_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write,
    so an explicit None clears assignee_user_id (unassign)."""
    engine = _db().engine
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "callbacks", callback_id)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT cb.customer_id, cb.status, c.dnd AS customer_dnd, c.preferred_window,
                           COALESCE(cr.dnd_registry, false) AS dnd_registry
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                    LEFT JOIN consent_records cr ON cr.customer_id = cb.customer_id
                    WHERE cb.id = :id
                    """
                ),
                {"id": callback_id},
            )
        )
        if row is None:
            raise KeyError("callback_not_found")
        db_core.assert_transition("callback", row["status"], payload.get("status"), _CALLBACK_TRANSITIONS)

        if payload.get("assigneeUserId") is not None:
            assignee = payload["assigneeUserId"]
            if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": assignee}).fetchone():
                raise KeyError(f"user_not_found: {assignee}")
        if payload.get("teamId") is not None:
            team_id = payload["teamId"]
            if not conn.execute(text("SELECT 1 FROM teams WHERE id = :id"), {"id": team_id}).fetchone():
                raise KeyError(f"team_not_found: {team_id}")
        if payload.get("disposition") is not None and payload["disposition"] not in CB_DISPOSITIONS:
            raise ValueError(f"invalid_disposition: {payload['disposition']}")

        updates: list[str] = []
        params: dict[str, Any] = {"id": callback_id}
        mapping = {
            "scheduledAt": "scheduled_at",
            "assigneeUserId": "assignee_user_id",
            "teamId": "team_id",
            "status": "status",
            "disposition": "disposition",
            "priority": "priority",
            "outcomeNotes": "outcome_notes",
            "windowMins": "window_mins",
        }
        for key, column in mapping.items():
            if key in payload:  # present == intentional (None clears nullable cols)
                updates.append(f"{column} = :{column}")
                params[column] = payload[key]

        # Keep dnd_active honest when the slot moves.
        if "scheduledAt" in payload and payload["scheduledAt"] is not None:
            updates.append("dnd_active = :dnd_active")
            params["dnd_active"] = _callback_dnd_active(
                bool(row["customer_dnd"]),
                bool(row["dnd_registry"]),
                row["preferred_window"],
                payload["scheduledAt"],
            )

        if updates:
            conn.execute(text(f"UPDATE callbacks SET {', '.join(updates)} WHERE id = :id"), params)

        if "assigneeUserId" in payload and payload["assigneeUserId"] is None:
            label, note = "Callback unassigned", None
        elif payload.get("assigneeUserId"):
            label, note = "Callback reassigned", _user_name(conn, payload["assigneeUserId"])
        elif payload.get("teamId"):
            team = _one(conn.execute(text("SELECT name FROM teams WHERE id = :id"), {"id": payload["teamId"]}))
            label, note = "Callback queue updated", team["name"] if team else payload["teamId"]
        elif payload.get("status"):
            label, note = "Callback updated", payload["status"]
        elif payload.get("scheduledAt"):
            label, note = "Callback rescheduled", payload["scheduledAt"]
        else:
            label, note = "Callback updated", None
        _activity(conn, "callback", callback_id, "callback_updated", label, note, row["customer_id"])
        return {"id": callback_id, "status": payload.get("status")}

def add_callback_reminder(callback_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    engine = _db().engine
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "callbacks", callback_id)
        row = _one(
            conn.execute(
                text("SELECT customer_id, status FROM callbacks WHERE id = :id"),
                {"id": callback_id},
            )
        )
        if row is None:
            raise KeyError("callback_not_found")

        status = payload.get("status") or "queued"
        if status not in {"queued", "scheduled", "sent", "acknowledged"}:
            raise ValueError(f"invalid_reminder_status: {status}")
        # DB also allows 'scheduled'; treat UI 'queued' as queued.
        db_status = "scheduled" if status == "queued" else status
        sent_at = utc_now().isoformat() if db_status == "sent" else None

        reminder_id = _id("CBR")
        conn.execute(
            text(
                """
                INSERT INTO callback_reminders
                  (id, callback_id, channel, scheduled_at, sent_at, status)
                VALUES
                  (:id, :callback_id, :channel, :scheduled_at, :sent_at, :status)
                """
            ),
            {
                "id": reminder_id,
                "callback_id": callback_id,
                "channel": payload["channel"],
                "scheduled_at": payload.get("scheduledAt") or utc_now().isoformat(),
                "sent_at": sent_at,
                "status": db_status,
            },
        )
        # Sending a reminder advances scheduled → reminded.
        if db_status == "sent" and row["status"] == "scheduled":
            conn.execute(
                text("UPDATE callbacks SET status = 'reminded' WHERE id = :id"),
                {"id": callback_id},
            )
        label = "Callback reminder sent" if db_status == "sent" else "Callback reminder queued"
        _activity(conn, "callback", callback_id, "callback_reminder_created", label, payload["channel"], row["customer_id"])
        return {"id": reminder_id, "status": _callback_reminder_status(db_status)}

