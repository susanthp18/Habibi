"""Document requests: list, create, patch, delivery attempts (WP-036 peel).

Peeled from ``db.py``. Call sites stay ``db.*`` via a bottom-of-file
re-export. Reach the engine through :func:`_db`, never ``from db_core import
engine``: the ``db_tx`` fixture wraps ``db.engine``, and a name bound from
``db_core`` bypasses that proxy.
"""

from __future__ import annotations

from sqlalchemy import text
from typing import Any


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


def _document_events(conn: Any, document_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """activity_events grouped by document_request id, for the Documents timeline."""
    _mod = _db()
    _doc_event_tone = _mod._doc_event_tone
    _rows = _mod._rows
    if not document_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.at, ae.label, ae.tone, ae.kind, ae.note,
                       u.name AS actor
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'document_request' AND ae.entity_id = ANY(:ids)
                ORDER BY ae.at
                """
            ),
            {"ids": document_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(
            {
                "at": r["at"],
                "label": r["label"],
                "actor": r["actor"],
                "tone": r["tone"] or _doc_event_tone(r["kind"], r["note"]),
            }
        )
    return grouped

def list_documents(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Document Fulfilment Desk feed (richer than the Customer 360 contract)."""
    _mod = _db()
    _account_tail = _mod._account_tail
    _doc_channel = _mod._doc_channel
    _doc_delivery_target = _mod._doc_delivery_target
    _doc_requested_via = _mod._doc_requested_via
    _doc_template_screen = _mod._doc_template_screen
    _doc_type_screen = _mod._doc_type_screen
    _rows = _mod._rows
    _sql = _mod._sql
    _tenant = _mod._tenant
    _vis_params = _mod._vis_params
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    engine = _mod.engine
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT dr.id, dr.customer_id, c.name AS customer_name, dr.account_id,
                           dr.doc_type, dr.period, dr.requested_via, dr.delivery_channel,
                           dr.delivery_target, dr.status, dr.template_id, dr.generated_at,
                           dr.sent_at, dr.failed_reason, dr.size_kb, dr.attempts,
                           dr.created_at, dr.interaction_id, dr.source,
                           c.phone_primary, c.email,
                           u.name AS assignee,
                           i.channel AS interaction_channel, i.handler_kind,
                           f.generated_at AS file_generated_at,
                           f.size_bytes AS file_size_bytes,
                           da.sent_at AS delivery_sent_at
                    FROM document_requests dr
                    JOIN customers c ON c.id = dr.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN users u ON u.id = dr.assignee_user_id
                    LEFT JOIN interactions i ON i.id = dr.interaction_id
                    LEFT JOIN LATERAL (
                      SELECT generated_at, size_bytes
                      FROM document_files
                      WHERE request_id = dr.id
                      ORDER BY generated_at DESC NULLS LAST, created_at DESC
                      LIMIT 1
                    ) f ON true
                    LEFT JOIN LATERAL (
                      SELECT sent_at
                      FROM document_delivery_attempts
                      WHERE request_id = dr.id AND status IN ('sent', 'delivered')
                      ORDER BY sent_at DESC NULLS LAST, created_at DESC
                      LIMIT 1
                    ) da ON true
                    ORDER BY dr.created_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
            )
        )
        ids = [r["id"] for r in rows]
        events = _document_events(conn, ids)
        result: list[dict[str, Any]] = []
        for r in rows:
            doc_type = _doc_type_screen(r["doc_type"])
            channel = _doc_channel(r["delivery_channel"])
            requested_at = r["created_at"]
            generated_at = r["generated_at"] or r["file_generated_at"]
            sent_at = r["sent_at"] or r["delivery_sent_at"]
            size_kb = r["size_kb"]
            if size_kb is None and r["file_size_bytes"] is not None:
                try:
                    size_kb = max(1, int(round(int(r["file_size_bytes"]) / 1024)))
                except (TypeError, ValueError):
                    size_kb = None
            evts = events.get(r["id"]) or [
                {"at": requested_at, "label": "Document requested", "actor": None, "tone": "info"}
            ]
            result.append(
                {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountId": r["account_id"] or "",
                    "accountTail": _account_tail(r["account_id"]) or "",
                    "docType": doc_type,
                    "period": r["period"],
                    "requestedVia": _doc_requested_via(
                        r["requested_via"],
                        r["handler_kind"],
                        r["interaction_channel"],
                        bool(r["interaction_id"]),
                    ),
                    "source": r.get("source") or "crm",
                    "requestedAt": requested_at,
                    "deliveryChannel": channel,
                    "deliveryTarget": _doc_delivery_target(
                        channel, r["delivery_target"], r["phone_primary"], r["email"]
                    ),
                    "status": r["status"],
                    "templateId": _doc_template_screen(r["template_id"], doc_type),
                    "generatedAt": generated_at,
                    "sentAt": sent_at,
                    "failedReason": r["failed_reason"],
                    "sizeKb": size_kb,
                    "attempts": int(r["attempts"] or 0),
                    "assignee": r["assignee"] or "Unassigned",
                    "events": evts,
                }
            )
        return result

def create_document_request(
    payload: dict[str, Any], idempotency_key: str | None = None
) -> dict[str, Any]:
    _mod = _db()
    _DEFAULT_TEMPLATE_FOR_DOC = _mod._DEFAULT_TEMPLATE_FOR_DOC
    _activity = _mod._activity
    _actor_user_id = _mod._actor_user_id
    _doc_channel = _mod._doc_channel
    _doc_delivery_target = _mod._doc_delivery_target
    _doc_type_screen = _mod._doc_type_screen
    _document_by_id = _mod._document_by_id
    _ensure_customer = _mod._ensure_customer
    _first_account_id = _mod._first_account_id
    _id = _mod._id
    _idempotent_response = _mod._idempotent_response
    _one = _mod._one
    _store_idempotent_response = _mod._store_idempotent_response
    engine = _mod.engine
    endpoint = "POST /documents"
    with engine.begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        document_id = _id("DOC")
        doc_type = _doc_type_screen(payload.get("docType"))
        channel = _doc_channel(payload.get("deliveryChannel"))
        customer = _one(
            conn.execute(
                text("SELECT phone_primary, email FROM customers WHERE id = :id"),
                {"id": customer_id},
            )
        ) or {}
        delivery_target = payload.get("deliveryTarget") or _doc_delivery_target(
            channel, None, customer.get("phone_primary"), customer.get("email")
        )
        # Present key wins (including explicit null → Unassigned). Omitted → acting user.
        if "assigneeUserId" in payload:
            assignee = payload["assigneeUserId"]
            if assignee is not None and not conn.execute(
                text("SELECT 1 FROM users WHERE id = :id"), {"id": assignee}
            ).fetchone():
                raise KeyError(f"user_not_found: {assignee}")
        else:
            assignee = _actor_user_id()

        template_id = payload.get("templateId") or _DEFAULT_TEMPLATE_FOR_DOC.get(doc_type)
        if template_id:
            _ensure_document_template(conn, template_id, doc_type)

        requested_via = payload.get("requestedVia") or "agent"
        if requested_via not in {
            "bot_voice",
            "bot_chat",
            "agent",
            "mcp",
            "clerk",
            "vision",
            "inbox",
        }:
            requested_via = "agent"
        source = payload.get("source") or {
            "vision": "vision",
            "inbox": "vision",
            "mcp": "mcp",
            "clerk": "clerk",
        }.get(requested_via, "crm")
        if source not in {"crm", "vision", "clerk", "mcp"}:
            source = "crm"

        conn.execute(
            text(
                """
                INSERT INTO document_requests
                  (id, customer_id, account_id, interaction_id, assignee_user_id,
                   doc_type, period, requested_via, template_id,
                   delivery_channel, delivery_target, status, attempts, priority, sla_due_at,
                   source)
                VALUES
                  (:id, :customer_id, :account_id, :interaction_id, :assignee_user_id,
                   :doc_type, :period, :requested_via, :template_id,
                   :delivery_channel, :delivery_target, 'requested', 0, 'normal', now() + interval '1 day',
                   :source)
                """
            ),
            {
                "id": document_id,
                "customer_id": customer_id,
                "account_id": payload.get("accountId") or _first_account_id(conn, customer_id),
                "interaction_id": payload.get("interactionId"),
                "assignee_user_id": assignee,
                "doc_type": doc_type,
                "period": payload.get("period"),
                "requested_via": requested_via,
                "template_id": template_id,
                "delivery_channel": channel,
                "delivery_target": delivery_target,
                "source": source,
            },
        )
        # Optional file metadata — server owns storage_ref; never trust a client path.
        if payload.get("filename") or payload.get("mimeType"):
            _ensure_document_file(
                conn,
                document_id,
                filename=payload.get("filename"),
                mime_type=payload.get("mimeType"),
            )
        label = f"Document requested · {doc_type}"
        _activity(conn, "document_request", document_id, "document_requested", label, doc_type, customer_id)
        response = _document_by_id(conn, document_id)
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response

def patch_document_request(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write."""
    _mod = _db()
    _activity = _mod._activity
    _assert_tenant_owns = _mod._assert_tenant_owns
    _doc_channel = _mod._doc_channel
    _doc_delivery_target = _mod._doc_delivery_target
    _doc_type_screen = _mod._doc_type_screen
    _document_by_id = _mod._document_by_id
    _one = _mod._one
    _user_name = _mod._user_name
    engine = _mod.engine
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "document_requests", document_id)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT customer_id, status, attempts, delivery_channel, delivery_target, doc_type
                    FROM document_requests WHERE id = :id
                    """
                ),
                {"id": document_id},
            )
        )
        if row is None:
            raise KeyError("document_not_found")

        if "assigneeUserId" in payload and payload["assigneeUserId"] is not None:
            if not conn.execute(
                text("SELECT 1 FROM users WHERE id = :id"), {"id": payload["assigneeUserId"]}
            ).fetchone():
                raise KeyError(f"user_not_found: {payload['assigneeUserId']}")

        if "templateId" in payload and payload["templateId"]:
            _ensure_document_template(
                conn, payload["templateId"], _doc_type_screen(row["doc_type"])
            )

        updates: list[str] = []
        params: dict[str, Any] = {"id": document_id}
        mapping = {
            "status": "status",
            "assigneeUserId": "assignee_user_id",
            "deliveryChannel": "delivery_channel",
            "deliveryTarget": "delivery_target",
            "templateId": "template_id",
            "period": "period",
            "generatedAt": "generated_at",
            "sentAt": "sent_at",
            "failedReason": "failed_reason",
            "sizeKb": "size_kb",
            "attempts": "attempts",
        }
        for key, column in mapping.items():
            if key in payload:
                updates.append(f"{column} = :{column}")
                params[column] = payload[key]

        # Status transitions that imply timestamps when the client didn't send them.
        status = payload.get("status") if "status" in payload else None
        if status == "generating":
            if "generatedAt" not in payload:
                updates.append("generated_at = COALESCE(generated_at, now())")
            if "failedReason" not in payload:
                updates.append("failed_reason = NULL")
            if "attempts" not in payload:
                updates.append("attempts = attempts + 1")
            _ensure_document_file(conn, document_id)
        elif status == "sent":
            if "sentAt" not in payload:
                updates.append("sent_at = COALESCE(sent_at, now())")
            if "generatedAt" not in payload:
                updates.append("generated_at = COALESCE(generated_at, now())")
            if "failedReason" not in payload:
                updates.append("failed_reason = NULL")
            _ensure_document_file(conn, document_id, size_kb=payload.get("sizeKb"))
        elif status == "failed":
            pass
        elif status == "requested":
            if "failedReason" not in payload:
                updates.append("failed_reason = NULL")

        if "deliveryChannel" in payload and payload["deliveryChannel"] and "deliveryTarget" not in payload:
            channel = _doc_channel(payload["deliveryChannel"])
            customer = _one(
                conn.execute(
                    text("SELECT phone_primary, email FROM customers WHERE id = :id"),
                    {"id": row["customer_id"]},
                )
            ) or {}
            updates.append("delivery_target = :delivery_target")
            params["delivery_target"] = _doc_delivery_target(
                channel, None, customer.get("phone_primary"), customer.get("email")
            )

        if updates:
            conn.execute(
                text(f"UPDATE document_requests SET {', '.join(updates)}, updated_at = now() WHERE id = :id"),
                params,
            )

        note = (payload.get("note") or "").strip() or None
        if "assigneeUserId" in payload and payload["assigneeUserId"] is None:
            label = "Document unassigned"
        elif payload.get("assigneeUserId"):
            label = f"Assigned to {_user_name(conn, payload['assigneeUserId']) or payload['assigneeUserId']}"
        elif payload.get("deliveryChannel"):
            label = f"Channel → {payload['deliveryChannel']}"
        elif payload.get("templateId"):
            label = f"Template set · {payload['templateId']}"
        elif status == "generating":
            label = "Generation started"
        elif status == "sent":
            label = "Document delivered"
        elif status == "failed":
            label = f"Failed · {payload.get('failedReason') or 'Delivery failed'}"
        elif status == "requested":
            label = "Retry queued" if row["status"] == "failed" else "Status → Requested"
        elif status:
            label = f"Status → {status}"
        else:
            label = "Document request updated"
        _activity(
            conn,
            "document_request",
            document_id,
            "document_updated",
            label,
            note or status,
            row["customer_id"],
        )
        return _document_by_id(conn, document_id)

def add_document_delivery_attempt(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _activity = _mod._activity
    _assert_tenant_owns = _mod._assert_tenant_owns
    _id = _mod._id
    _one = _mod._one
    engine = _mod.engine
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "document_requests", document_id)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT customer_id, delivery_channel, delivery_target, attempts
                    FROM document_requests WHERE id = :id
                    """
                ),
                {"id": document_id},
            )
        )
        if row is None:
            raise KeyError("document_not_found")
        import contact_policy

        attempt_id = _id("DLV")
        channel = contact_policy.normalize_channel(row["delivery_channel"] or "whatsapp")
        contact_policy.require_admit(
            conn,
            customer_id=row["customer_id"],
            channel=channel,
            purpose="outreach",
            session_key=document_id,
            source="doc_delivery",
            related_id=attempt_id,
            actor_kind="human",
            endpoint=row["delivery_target"],
        )
        next_attempt = int(row["attempts"] or 0) + 1
        status = payload.get("status") or "queued"
        conn.execute(
            text(
                """
                INSERT INTO document_delivery_attempts
                  (id, request_id, channel, target, provider, attempt_number, status, error, sent_at)
                VALUES
                  (:id, :request_id, :channel, :target, :provider, :attempt_number, :status, :error, now())
                """
            ),
            {
                "id": attempt_id,
                "request_id": document_id,
                "channel": row["delivery_channel"],
                "target": row["delivery_target"],
                "provider": payload.get("provider") or "manual",
                "attempt_number": next_attempt,
                "status": status,
                "error": payload.get("error") or payload.get("failedReason"),
            },
        )
        conn.execute(
            text("UPDATE document_requests SET attempts = :attempts, updated_at = now() WHERE id = :id"),
            {"attempts": next_attempt, "id": document_id},
        )
        _activity(
            conn,
            "document_request",
            document_id,
            "document_delivery_attempt",
            "Document delivery attempted",
            status,
            row["customer_id"],
        )
        return {"id": attempt_id, "status": status, "attemptNumber": next_attempt}

def _ensure_document_template(conn: Any, template_id: str, doc_type: str) -> None:
    _mod = _db()
    _tenant = _mod._tenant
    existing = conn.execute(
        text("SELECT 1 FROM document_templates WHERE id = :id"), {"id": template_id}
    ).fetchone()
    if existing:
        return
    conn.execute(
        text(
            """
            INSERT INTO document_templates (id, tenant_id, name, doc_type, preview_lines)
            VALUES (:id, :tenant_id, :name, :doc_type, '[]'::jsonb)
            """
        ),
        {"id": template_id, "tenant_id": _tenant(), "name": template_id, "doc_type": doc_type},
    )

def _ensure_document_file(
    conn: Any,
    document_id: str,
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    size_kb: int | None = None,
) -> None:
    """Create or refresh the generated file row. storage_ref is always server-owned."""
    _mod = _db()
    _one = _mod._one
    _tenant = _mod._tenant
    existing = _one(
        conn.execute(
            text("SELECT id FROM document_files WHERE request_id = :id ORDER BY created_at DESC LIMIT 1"),
            {"id": document_id},
        )
    )
    mime = mime_type or "application/pdf"
    if mime.startswith("image/"):
        ext = ".jpg" if "jpeg" in mime or mime.endswith("/jpg") else ".png" if "png" in mime else ".webp"
        storage_ref = f"minio://documents/{_tenant()}/{document_id}{ext}"
        fname = filename or f"{document_id}{ext}"
    else:
        storage_ref = f"minio://documents/{_tenant()}/{document_id}.pdf"
        fname = filename or f"{document_id}.pdf"
    size_bytes = int(size_kb * 1024) if size_kb is not None else None
    if existing:
        if size_bytes is not None:
            conn.execute(
                text(
                    """
                    UPDATE document_files
                    SET size_bytes = :size_bytes, generated_at = now()
                    WHERE id = :id
                    """
                ),
                {"size_bytes": size_bytes, "id": existing["id"]},
            )
        return
    conn.execute(
        text(
            """
            INSERT INTO document_files
              (id, request_id, storage_ref, filename, mime_type, size_bytes, generated_at)
            VALUES
              (:id, :request_id, :storage_ref, :filename, :mime_type, :size_bytes, now())
            """
        ),
        {
            "id": f"FILE-{document_id}",
            "request_id": document_id,
            "storage_ref": storage_ref,
            "filename": fname,
            "mime_type": mime,
            "size_bytes": size_bytes or 96000,
        },
    )

