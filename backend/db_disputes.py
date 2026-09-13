"""Disputes: the desk's list, the 360's contracts, and the writes (create, patch, note, evidence). Carved out of db.py."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.clock import utc_now
from db_core import (
    DEFAULT_DETAIL_LIMIT,
    _account_tail,
    _activity,
    _actor_user_id,
    _as_utc,
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
    assert_transition,
    clamp_list_limit,
    clamp_offset,
)


# A dispute is at risk once less than a quarter of its filing→due window is
# left, and breached the moment it passes due.
DISPUTE_SLA_WARN_FRACTION = 0.25


_DISPUTE_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"under_review", "awaiting_customer", "resolved", "rejected"}),
    "under_review": frozenset({"awaiting_customer", "resolved", "rejected"}),
    "awaiting_customer": frozenset({"under_review", "resolved", "rejected"}),
    "rejected": frozenset({"under_review"}),
}


def _db():
    """The ``db`` module object, resolved at call time: tests route
    ``db.engine`` through a savepoint proxy, and the proxy must be the one
    the writes below open their transactions on."""
    import db as d

    return d


def _dispute_sla_countdown(seconds: float) -> str:
    """Minutes-precise countdown: '0h 29m left', '0h 40m over'."""
    total = abs(int(seconds))
    hours, rem = divmod(total, 3600)
    return f"{hours}h {rem // 60}m {'over' if seconds < 0 else 'left'}"


def _dispute_sla(
    sla_due_at: Any,
    captured_at: Any,
    status: str | None,
) -> tuple[str, str, int]:
    """Compute (sla, slaLabel, slaMinutes) for one dispute.

    This is the only place a dispute SLA is turned into something a screen can
    render. It used to be computed twice — here in hours ("23h left", no tone)
    for the Customer 360 tab, and again in the client (disputes-seed.slaInfo)
    in hours-and-minutes with a tone for the board — so the same dispute read
    "0h 29m left / at risk" on one screen and "0h left / no colour" on the
    other. The client copy is gone; both screens render these fields.

    Shape mirrors :func:`_work_item_sla` — tone first, then the display string
    — so "the SLA of a thing" means the same fields across the API.
    ``slaMinutes`` is signed: positive is time remaining, negative is overdue.
    """
    if status in {"resolved", "rejected"}:
        return "done", "Closed", 0
    due = _as_utc(sla_due_at)
    if due is None:
        return "ok", "Open", 0
    remaining = (due - utc_now()).total_seconds()
    label = _dispute_sla_countdown(remaining)
    minutes = int(remaining / 60)
    if remaining < 0:
        return "breach", label, minutes
    captured = _as_utc(captured_at)
    window = (due - captured).total_seconds() if captured else 0.0
    if window > 0 and remaining < window * DISPUTE_SLA_WARN_FRACTION:
        return "warn", label, minutes
    return "ok", label, minutes


def _dispute_contracts(conn: Any, customer_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT d.id, d.type, d.disputed_amount, d.transcript_snippet, d.status,
                       d.sla_due_at, d.created_at, u.name AS assignee
                FROM disputes d
                LEFT JOIN users u ON u.id = d.assignee_user_id
                WHERE d.customer_id = :customer_id
                ORDER BY d.created_at DESC
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "limit": DEFAULT_DETAIL_LIMIT},
        )
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        sla, sla_label, sla_minutes = _dispute_sla(
            r["sla_due_at"], r["created_at"], r["status"]
        )
        out.append(
            {
                "id": r["id"],
                "type": r["type"],
                "amount": r["disputed_amount"],
                "transcriptSnippet": r["transcript_snippet"] or "",
                "status": r["status"],
                "sla": sla,
                "slaLabel": sla_label,
                "slaMinutes": sla_minutes,
                "filedAt": r["created_at"],
                "assignee": r["assignee"],
            }
        )
    return out


def _dispute_source_screen(source: str | None, interaction_channel: str | None) -> str:
    """Map DB source (+ optional interaction channel) to the disputes-screen enum."""
    if source in {"bot_voice", "bot_chat", "agent"}:
        return source
    # Seeder stores plain "bot"; derive voice vs chat from the linked interaction.
    if source == "bot" and interaction_channel in {"chat", "whatsapp", "sms", "email"}:
        return "bot_chat"
    if source == "bot":
        return "bot_voice"
    if interaction_channel in {"chat", "whatsapp", "sms", "email"}:
        return "bot_chat"
    return "bot_voice"


def _evidence_kind(filename: str, mime_type: str | None) -> str:
    """filename/mime → screen Evidence.kind heuristic."""
    name = (filename or "").lower()
    mime = (mime_type or "").lower()
    if mime.startswith("audio/") or name.endswith((".mp3", ".wav", ".m4a", ".ogg")):
        return "audio"
    if mime.startswith("image/") or name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "screenshot"
    if "statement" in name:
        return "statement"
    if "receipt" in name or "payment" in name:
        return "receipt"
    return "other"


def _dispute_event_tone(kind: str | None, note: str | None) -> str | None:
    if kind in {"dispute_created", "evidence_added", "note_added"}:
        return "info"
    if kind == "dispute_updated":
        if note == "resolved":
            return "success"
        if note == "rejected":
            return "danger"
        return "info"
    return None


def _dispute_events(conn: Any, dispute_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """activity_events grouped by dispute id, for the disputes-screen timeline."""
    if not dispute_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.at, ae.label, ae.tone, ae.kind, ae.note,
                       u.name AS actor
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'dispute' AND ae.entity_id = ANY(:ids)
                ORDER BY ae.at
                """
            ),
            {"ids": dispute_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(
            {
                "at": r["at"],
                "label": r["label"],
                "actor": r["actor"],
                "tone": r["tone"] or _dispute_event_tone(r["kind"], r["note"]),
            }
        )
    return grouped


def _dispute_evidence(conn: Any, dispute_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not dispute_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT e.id, e.dispute_id, e.filename, e.mime_type, e.created_at,
                       u.name AS uploaded_by
                FROM dispute_evidence e
                LEFT JOIN users u ON u.id = e.uploaded_by_user_id
                WHERE e.dispute_id = ANY(:ids)
                ORDER BY e.created_at DESC
                """
            ),
            {"ids": dispute_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["dispute_id"], []).append(
            {
                "id": r["id"],
                "name": r["filename"],
                "kind": _evidence_kind(r["filename"], r["mime_type"]),
                "uploadedAt": r["created_at"],
                "uploadedBy": r["uploaded_by"] or "System",
            }
        )
    return grouped


def list_disputes(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Disputes & Exceptions queue feed (richer than the Customer 360 contract)."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with _db().engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT d.id, d.customer_id, c.name AS customer_name, d.account_id,
                           d.type, d.disputed_amount, d.source, d.transcript_snippet,
                           d.interaction_id, d.created_at, d.sla_due_at, d.status,
                           d.priority, d.resolution_code, d.resolution_notes,
                           u.name AS assignee, i.channel AS interaction_channel
                    FROM disputes d
                    JOIN customers c ON c.id = d.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN users u ON u.id = d.assignee_user_id
                    LEFT JOIN interactions i ON i.id = d.interaction_id
                    ORDER BY d.created_at DESC, d.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
            )
        )
        ids = [r["id"] for r in rows]
        events = _dispute_events(conn, ids)
        evidence = _dispute_evidence(conn, ids)
        result = []
        for r in rows:
            captured = r["created_at"]
            due = r["sla_due_at"] or captured
            # Tone is computed from the real due date, not the capturedAt
            # fallback above: a dispute with no due date is "Open", the same
            # answer the Customer 360 tab gives, not instantly breached.
            sla, sla_label, sla_minutes = _dispute_sla(
                r["sla_due_at"], captured, r["status"]
            )
            evts = events.get(r["id"]) or [
                {"at": captured, "label": "Dispute captured", "actor": None, "tone": "info"}
            ]
            result.append(
                {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountId": r["account_id"],
                    "accountTail": _account_tail(r["account_id"]) or "",
                    "type": r["type"],
                    "disputedAmount": r["disputed_amount"] or 0.0,
                    "source": _dispute_source_screen(r["source"], r["interaction_channel"]),
                    "transcriptSnippet": r["transcript_snippet"] or "",
                    "originConversationId": r["interaction_id"],
                    "capturedAt": captured,
                    "slaDueAt": due,
                    "sla": sla,
                    "slaLabel": sla_label,
                    "slaMinutes": sla_minutes,
                    "status": r["status"],
                    "assignee": r["assignee"] or "Unassigned",
                    "priority": r["priority"] or "normal",
                    "evidence": evidence.get(r["id"]) or [],
                    "events": evts,
                    "resolutionCode": r["resolution_code"],
                    "resolutionNotes": r["resolution_notes"],
                }
            )
        return result


def _dispute_by_id(conn: Any, dispute_id: str) -> dict[str, Any]:
    row = _one(conn.execute(text("SELECT customer_id FROM disputes WHERE id = :id"), {"id": dispute_id}))
    if row is None:
        raise KeyError("dispute_not_found")
    for item in _dispute_contracts(conn, row["customer_id"]):
        if item["id"] == dispute_id:
            return item
    raise KeyError("dispute_not_found")


def create_dispute(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = "POST /disputes"
    with _db().engine.begin() as conn:
        return _create_dispute(conn, payload, idempotency_key, endpoint)


def _create_dispute(
    conn: Any,
    payload: dict[str, Any],
    idempotency_key: str | None,
    endpoint: str,
) -> dict[str, Any]:
    """Connection-scoped body of :func:`create_dispute` — see _create_promise."""
    cached = _idempotent_response(conn, idempotency_key, endpoint)
    if cached:
        return cached
    customer_id = payload["customerId"]
    _ensure_customer(conn, customer_id)
    dispute_id = _id("DSP")
    conn.execute(
        text(
            """
            INSERT INTO disputes
              (id, customer_id, account_id, interaction_id, assignee_user_id, type,
               disputed_amount, source, status, priority, transcript_snippet, sla_due_at)
            VALUES
              (:id, :customer_id, :account_id, :interaction_id, :assignee_user_id, :type,
               :amount, 'agent', 'new', :priority, :transcript_snippet, now() + interval '2 days')
            """
        ),
        {
            "id": dispute_id,
            "customer_id": customer_id,
            "account_id": payload.get("accountId") or _first_account_id(conn, customer_id),
            "interaction_id": payload.get("interactionId"),
            "assignee_user_id": payload.get("assigneeUserId") or _actor_user_id(),
            "type": payload["type"],
            "amount": payload.get("amount"),
            "priority": payload.get("priority") or "normal",
            "transcript_snippet": payload.get("transcriptSnippet"),
        },
    )
    _activity(conn, "dispute", dispute_id, "dispute_created", "Dispute raised", payload.get("transcriptSnippet"), customer_id)
    response = _dispute_by_id(conn, dispute_id)
    _store_idempotent_response(conn, idempotency_key, endpoint, response)
    return response


# A dispute's status is a state machine. `resolved` is terminal -- a resolved
# fee waiver has a ledger row behind it -- and `rejected` reopens only into
# review (an appeal), never straight back to new.


def patch_dispute(dispute_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write,
    so an explicit None clears the column (used to unassign)."""
    with _db().engine.begin() as conn:
        _assert_tenant_owns(conn, "disputes", dispute_id)
        row = _one(conn.execute(text("SELECT customer_id, assignee_user_id, status FROM disputes WHERE id = :id"), {"id": dispute_id}))
        if row is None:
            raise KeyError("dispute_not_found")
        assert_transition("dispute", row["status"], payload.get("status"), _DISPUTE_TRANSITIONS)
        if payload.get("assigneeUserId") is not None:
            assignee = payload["assigneeUserId"]
            if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": assignee}).fetchone():
                raise KeyError(f"user_not_found: {assignee}")
        updates = []
        params: dict[str, Any] = {"id": dispute_id}
        mapping = {
            "status": "status",
            "assigneeUserId": "assignee_user_id",
            "resolutionCode": "resolution_code",
            "resolutionNotes": "resolution_notes",
        }
        for key, column in mapping.items():
            if key in payload:  # present == intentional (None clears)
                updates.append(f"{column} = :{column}")
                params[column] = payload[key]

        status = payload.get("status")
        resolution = payload.get("resolutionCode")
        if status == "resolved" and resolution == "valid_waive_fee":
            # Post before the status write. A failure must not leave
            # resolved/valid_waive_fee on a dispute whose fee was not waived;
            # the open transaction rolls the whole patch back either way.
            from agent_core.authority import enact as authority_enact

            authority_enact.post_waiver_for_dispute(conn, dispute_id=dispute_id)
        if updates:
            conn.execute(text(f"UPDATE disputes SET {', '.join(updates)} WHERE id = :id"), params)
        if "assigneeUserId" in payload and payload["assigneeUserId"] is None:
            label, note = "Dispute unassigned", None
        elif payload.get("assigneeUserId"):
            label = "Dispute reassigned"
            note = _user_name(conn, payload["assigneeUserId"])
        elif status:
            label, note = "Dispute updated", status
        else:
            label, note = "Dispute updated", None
        _activity(conn, "dispute", dispute_id, "dispute_updated", label, note, row["customer_id"])
        return _dispute_by_id(conn, dispute_id)


def add_dispute_note(dispute_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Free-text note on a dispute. activity_events IS the timeline store, so the
    note is a first-class timeline entry rather than a separate table."""
    with _db().engine.begin() as conn:
        _assert_tenant_owns(conn, "disputes", dispute_id)
        row = _one(conn.execute(text("SELECT customer_id FROM disputes WHERE id = :id"), {"id": dispute_id}))
        if row is None:
            raise KeyError("dispute_not_found")
        text_value = (payload.get("text") or "").strip()
        if not text_value:
            raise ValueError("note text is required")
        _activity(conn, "dispute", dispute_id, "note_added", text_value, None, row["customer_id"])
        return {"id": dispute_id, "text": text_value}


def add_dispute_evidence(dispute_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with _db().engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id FROM disputes WHERE id = :id"), {"id": dispute_id}))
        if row is None:
            raise KeyError("dispute_not_found")
        evidence_id = _id("EVD")
        conn.execute(
            text(
                """
                INSERT INTO dispute_evidence
                  (id, dispute_id, storage_ref, filename, mime_type, size_bytes, hash, uploaded_by_user_id)
                VALUES
                  (:id, :dispute_id, :storage_ref, :filename, :mime_type, :size_bytes, :hash, :uploaded_by_user_id)
                """
            ),
            {
                "id": evidence_id,
                "dispute_id": dispute_id,
                # Storage layout is the server's concern — clients don't dictate paths.
                "storage_ref": payload.get("storageRef")
                or f"minio://dispute-evidence/{_tenant()}/{dispute_id}/{payload['filename']}",
                "filename": payload["filename"],
                "mime_type": payload["mimeType"],
                "size_bytes": payload.get("sizeBytes"),
                "hash": payload.get("hash"),
                "uploaded_by_user_id": _actor_user_id(),
            },
        )
        _activity(conn, "dispute", dispute_id, "evidence_added", "Evidence added", payload["filename"], row["customer_id"])
        return {"id": evidence_id, **payload}
