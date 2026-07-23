"""Postgres accessors plus API response serializers."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from schemas import (
    CallResponse,
    CustomerResponse,
    DashboardResponse,
    HandoffResponse,
    LeadResponse,
)

logger = logging.getLogger(__name__)


BASE = Path(__file__).parent
DEFAULT_DATABASE_URL = "postgresql+psycopg://collections:collections@localhost:5432/collections"


def _read_env_database_url() -> str | None:
    env_file = BASE / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "DATABASE_URL":
            return value
    return None


DATABASE_URL = os.getenv("DATABASE_URL") or _read_env_database_url() or DEFAULT_DATABASE_URL

# Tenant + acting user are config, not literals sprinkled through the SQL.
# Phase 5 replaces both: tenant from the request GUC (RLS), actor from the JWT.
TENANT_ID = os.getenv("TENANT_ID", "hdfc.retail")
ACTOR_USER_ID = os.getenv("ACTOR_USER_ID", "priya-nair")
engine: Engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def init_and_seed() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1 FROM tenants LIMIT 1"))


def _clean(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def _rows(result: Any) -> list[dict[str, Any]]:
    return [_clean(dict(row._mapping)) for row in result]


def _one(result: Any) -> dict[str, Any] | None:
    row = result.fetchone()
    return _clean(dict(row._mapping)) if row else None


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json", exclude_none=False)


def _duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    return f"{seconds // 60}m {seconds % 60}s"


def _short_product(product: str | None) -> str:
    if not product:
        return "Card"
    if "personal" in product.lower():
        return "Personal Loan"
    if "auto" in product.lower():
        return "Auto Loan"
    return "Card"


def _spark(seed: int, length: int = 14) -> list[int]:
    return [max(0, round(seed + ((i % 5) - 2) * (seed * 0.06))) for i in range(length)]


def _account_tail(account_id: str | None) -> str | None:
    return account_id[-4:] if account_id else None


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _actor_user_id() -> str:
    """The acting user. Config-driven until real auth lands (Phase 5 · OIDC),
    at which point this reads the validated JWT subject instead of the env."""
    return ACTOR_USER_ID


def get_current_user() -> dict[str, Any]:
    """Single source of truth for 'who am I' — the UI must not hardcode an identity
    that disagrees with the actor recorded on writes."""
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT u.id, u.name, u.status, t.name AS team
                    FROM users u
                    LEFT JOIN teams t ON t.id = u.team_id
                    WHERE u.id = :id
                    """
                ),
                {"id": _actor_user_id()},
            )
        )
        if row is None:
            raise KeyError(f"actor_not_found: {_actor_user_id()}")
        return {
            "id": row["id"],
            "name": row["name"],
            "kind": "human",
            "team": row["team"],
            "status": row["status"],
            "tenantId": TENANT_ID,
        }


_PRESENCE_STATUSES = frozenset({"available", "on_break", "wrap_up", "offline"})


def _map_presence_row(row: dict[str, Any]) -> dict[str, Any]:
    since = row.get("since_at")
    if hasattr(since, "isoformat"):
        since_at = since.isoformat()
    else:
        since_at = str(since or "")
    return {"status": row["status"], "sinceAt": since_at}


def get_agent_presence() -> dict[str, Any]:
    """Current actor's agent_presence row — upsert available if missing."""
    uid = _actor_user_id()
    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT status, since_at
                    FROM agent_presence
                    WHERE user_id = :uid
                    ORDER BY updated_at DESC NULLS LAST, id DESC
                    LIMIT 1
                    """
                ),
                {"uid": uid},
            )
        )
        if row is None:
            pid = f"presence-{uid}"
            conn.execute(
                text(
                    """
                    INSERT INTO agent_presence (id, user_id, status, since_at)
                    VALUES (:id, :uid, 'available', now())
                    ON CONFLICT (id) DO UPDATE
                      SET status = EXCLUDED.status,
                          since_at = EXCLUDED.since_at,
                          updated_at = now()
                    """
                ),
                {"id": pid, "uid": uid},
            )
            row = _one(
                conn.execute(
                    text("SELECT status, since_at FROM agent_presence WHERE id = :id"),
                    {"id": pid},
                )
            )
        assert row is not None
        return _map_presence_row(row)


def patch_agent_presence(status: str) -> dict[str, Any]:
    """Set presence status for the acting user; bumps since_at."""
    if status not in _PRESENCE_STATUSES:
        raise ValueError(f"invalid_presence_status: {status}")
    uid = _actor_user_id()
    pid = f"presence-{uid}"
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO agent_presence (id, user_id, status, since_at)
                VALUES (:id, :uid, :status, now())
                ON CONFLICT (id) DO UPDATE
                  SET status = EXCLUDED.status,
                      since_at = now(),
                      updated_at = now()
                """
            ),
            {"id": pid, "uid": uid, "status": status},
        )
        # Also update any alternate presence rows for this user (seed may differ).
        conn.execute(
            text(
                """
                UPDATE agent_presence
                SET status = :status, since_at = now(), updated_at = now()
                WHERE user_id = :uid AND id <> :id
                """
            ),
            {"uid": uid, "status": status, "id": pid},
        )
        row = _one(
            conn.execute(
                text("SELECT status, since_at FROM agent_presence WHERE id = :id"),
                {"id": pid},
            )
        )
    assert row is not None
    return _map_presence_row(row)


def _user_name(conn: Any, user_id: str | None) -> str | None:
    if not user_id:
        return None
    row = conn.execute(text("SELECT name FROM users WHERE id = :id"), {"id": user_id}).fetchone()
    return row[0] if row else None


def _first_account_id(conn: Any, customer_id: str) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT id
            FROM accounts
            WHERE customer_id = :customer_id
            ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
            LIMIT 1
            """
        ),
        {"customer_id": customer_id},
    ).fetchone()
    return row[0] if row else None


def _ensure_customer(conn: Any, customer_id: str) -> None:
    if not conn.execute(text("SELECT 1 FROM customers WHERE id = :id"), {"id": customer_id}).fetchone():
        raise KeyError("customer_not_found")


def _ensure_interaction(conn: Any, interaction_id: str) -> dict[str, Any]:
    row = _one(conn.execute(text("SELECT id, customer_id, account_id FROM interactions WHERE id = :id"), {"id": interaction_id}))
    if row is None:
        raise KeyError("interaction_not_found")
    return row


def _activity(conn: Any, entity_type: str, entity_id: str, kind: str, label: str, note: str | None = None, customer_id: str | None = None) -> None:
    conn.execute(
        text(
            """
            INSERT INTO activity_events
              (id, tenant_id, entity_type, entity_id, actor_kind, actor_user_id, kind, label, note)
            VALUES
              (:id, :tenant_id, :entity_type, :entity_id, 'human', :actor_user_id, :kind, :label, :note)
            """
        ),
        {
            "id": _id("ACT"),
            "tenant_id": TENANT_ID,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_user_id": _actor_user_id(),
            "kind": kind,
            "label": label,
            "note": note or customer_id,
        },
    )


def _idempotent_response(conn: Any, key: str | None, endpoint: str) -> dict[str, Any] | None:
    if not key:
        return None
    row = conn.execute(
        text("SELECT response FROM idempotency_keys WHERE key = :key AND endpoint = :endpoint"),
        {"key": key, "endpoint": endpoint},
    ).fetchone()
    return row[0] if row else None


def _store_idempotent_response(conn: Any, key: str | None, endpoint: str, response: dict[str, Any]) -> None:
    if not key:
        return
    conn.execute(
        text(
            """
            INSERT INTO idempotency_keys (key, endpoint, response)
            VALUES (:key, :endpoint, CAST(:response AS jsonb))
            ON CONFLICT (key) DO NOTHING
            """
        ),
        {"key": key, "endpoint": endpoint, "response": __import__("json").dumps(response)},
    )


def _ptp_status(status: str) -> str:
    return "upcoming" if status == "due_today" else status


def _reminder_status(status: str) -> str:
    return status if status in {"queued", "sent", "acknowledged", "off"} else "queued"


# Promises SCREEN vocabulary (off | scheduled | sent) vs the DB's fuller enum.
def _reminder_status_screen(status: str) -> str:
    if status in {"off", "scheduled", "sent"}:
        return status
    if status == "queued":
        return "scheduled"
    if status == "acknowledged":
        return "sent"
    return "off"  # failed / unknown


def _doc_channel(channel: str | None) -> str:
    if channel in {"whatsapp", "email", "sms"}:
        return channel
    return "email"


_DOC_TYPE_SCREEN = {
    "account_statement",
    "no_dues_certificate",
    "interest_certificate",
    "foreclosure_letter",
    "loan_schedule",
    "payment_receipt",
    "kyc_letter",
}

_DOC_TYPE_ALIASES = {
    "statement": "account_statement",
    "account statement": "account_statement",
    "6-month account statement": "account_statement",
    "6 month account statement": "account_statement",
    "no-dues certificate": "no_dues_certificate",
    "no dues certificate": "no_dues_certificate",
    "noc": "no_dues_certificate",
    "interest certificate": "interest_certificate",
    "foreclosure letter": "foreclosure_letter",
    "loan schedule": "loan_schedule",
    "repayment schedule": "loan_schedule",
    "payment receipt": "payment_receipt",
    "kyc letter": "kyc_letter",
    "kyc confirmation letter": "kyc_letter",
}

_TEMPLATE_SCREEN = {
    "template-statement": "T-STMT-6M",
    "template-noc": "T-NODUES",
}

_DEFAULT_TEMPLATE_FOR_DOC = {
    "account_statement": "T-STMT-6M",
    "no_dues_certificate": "T-NODUES",
    "interest_certificate": "T-INTCERT",
    "foreclosure_letter": "T-FORECLOSE",
    "loan_schedule": "T-SCHEDULE",
    "payment_receipt": "T-RECEIPT",
    "kyc_letter": "T-KYC",
}


def _doc_type_screen(raw: str | None) -> str:
    """Map free-text / legacy seed doc_type values onto the screen enum."""
    if not raw:
        return "account_statement"
    if raw in _DOC_TYPE_SCREEN:
        return raw
    key = raw.strip().lower()
    if key in _DOC_TYPE_ALIASES:
        return _DOC_TYPE_ALIASES[key]
    compact = key.replace("-", "_").replace(" ", "_")
    if compact in _DOC_TYPE_SCREEN:
        return compact
    if "statement" in key:
        return "account_statement"
    if "dues" in key or key == "noc":
        return "no_dues_certificate"
    if "interest" in key:
        return "interest_certificate"
    if "foreclos" in key:
        return "foreclosure_letter"
    if "schedule" in key or "amort" in key:
        return "loan_schedule"
    if "receipt" in key:
        return "payment_receipt"
    if "kyc" in key:
        return "kyc_letter"
    return "account_statement"


def _doc_template_screen(template_id: str | None, doc_type: str) -> str:
    if template_id and template_id in _TEMPLATE_SCREEN:
        return _TEMPLATE_SCREEN[template_id]
    if template_id:
        return template_id
    return _DEFAULT_TEMPLATE_FOR_DOC.get(doc_type, "T-STMT-6M")


def _doc_requested_via(
    requested_via: str | None,
    handler_kind: str | None,
    interaction_channel: str | None,
    has_interaction: bool,
) -> str:
    if requested_via in {"bot_voice", "bot_chat", "agent"}:
        return requested_via
    return _callback_source(handler_kind, interaction_channel, has_interaction)


def _mask_email(email: str) -> str:
    if "@" not in email:
        return email
    user, domain = email.split("@", 1)
    if not user:
        return email
    return f"{user[:2]}•••@{domain}"


def _doc_delivery_target(
    channel: str,
    stored: str | None,
    phone: str | None,
    email: str | None,
) -> str:
    if stored:
        return stored
    if channel == "email":
        return _mask_email(email) if email else ""
    return phone or ""


def _doc_event_tone(kind: str | None, note: str | None) -> str:
    if kind in {"document_delivery_attempt"} and note in {"sent", "delivered"}:
        return "success"
    if kind in {"document_delivery_attempt"} and note in {"failed", "bounced"}:
        return "danger"
    if note and any(x in note.lower() for x in ("fail", "error", "bounce")):
        return "danger"
    if note and any(x in note.lower() for x in ("sent", "deliver")):
        return "success"
    return "info"


def _consent_channel(channel: str) -> str | None:
    if channel == "voice":
        return "call"
    if channel in {"whatsapp", "sms", "email"}:
        return channel
    return None


def _sentiment_delta(score: float | None) -> str:
    if score is None:
        return "flat"
    if score > 0.15:
        return "up"
    if score < -0.15:
        return "down"
    return "flat"


def _sla_label(value: str | None) -> str:
    if not value:
        return "Open"
    try:
        due = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return "Open"
    now = datetime.now(timezone.utc)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    hours = round((due - now).total_seconds() / 3600)
    if hours < 0:
        return f"{abs(hours)}h overdue"
    if hours < 24:
        return f"{hours}h left"
    return f"{round(hours / 24)}d left"


def _base_customer_row(conn: Any, customer_id: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE c.id = :customer_id" if customer_id else ""
    params = {"customer_id": customer_id} if customer_id else {}
    return _rows(
        conn.execute(
            text(
                f"""
                SELECT
                  c.id,
                  c.name,
                  c.risk,
                  c.last_contact_at,
                  c.phone_primary,
                  c.phone_alt,
                  c.email,
                  c.address,
                  c.timezone,
                  c.language,
                  c.preferred_window,
                  c.dnd,
                  c.risk_score,
                  u.name AS assigned_to,
                  a.id AS account_id,
                  a.outstanding,
                  a.minimum_due,
                  a.opened_on,
                  a.apr,
                  a.sanctioned_amount,
                  a.bucket,
                  a.dpd,
                  p.name AS product
                FROM customers c
                LEFT JOIN users u ON u.id = c.assigned_user_id
                LEFT JOIN LATERAL (
                  SELECT *
                  FROM accounts a
                  WHERE a.customer_id = c.id
                  ORDER BY
                    CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END,
                    a.created_at,
                    a.id
                  LIMIT 1
                ) a ON true
                LEFT JOIN products p ON p.id = a.product_id
                {where}
                ORDER BY c.name
                """
            ),
            params,
        )
    )


def _customer_shell(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        # Customers without an accounts row must still serialize (list + PTP pickers).
        "accountId": row["account_id"] or "",
        "risk": row["risk"],
        "outstanding": float(row["outstanding"] or 0),
        "minimumDue": row["minimum_due"],
        "lastContact": row["last_contact_at"],
        "assignedTo": row["assigned_to"] or "Unassigned",
        "contact": {
            "phonePrimary": row["phone_primary"] or "",
            "phoneAlt": row["phone_alt"],
            "email": row["email"] or "",
            "address": row["address"] or "",
            "timezone": row["timezone"] or "Asia/Kolkata",
            "language": row["language"] or "English",
            "preferredWindow": row["preferred_window"] or "10:00-19:00 IST",
            "dnd": bool(row["dnd"]),
        },
        "account": {
            "product": row["product"] or "Credit Card",
            "openedOn": row["opened_on"],
            "apr": row["apr"],
            "sanctionedAmount": row["sanctioned_amount"],
            "bucket": row["bucket"],
            "dpd": int(row["dpd"] or 0),
            "riskScore": row["risk_score"],
        },
        "consent": [],
        "ledger": [],
        "emi": [],
        "interactions": [],
        "promises": [],
        "disputes": [],
        "documents": [],
        "notes": [],
    }


def _customer_contract(conn: Any, row: dict[str, Any], include_detail: bool) -> CustomerResponse:
    customer = _customer_shell(row)
    customer_id = row["id"]
    account_id = row["account_id"]

    if include_detail:
        consent = _rows(
            conn.execute(
                text(
                    """
                    SELECT cc.channel, cc.status, cc.source, cc.captured_at
                    FROM consent_records cr
                    JOIN channel_consents cc ON cc.consent_id = cr.id
                    WHERE cr.customer_id = :customer_id
                    ORDER BY cc.channel
                    """
                ),
                {"customer_id": customer_id},
            )
        )
        customer["consent"] = [
            {
                "channel": mapped,
                "optedIn": c["status"] == "opted_in",
                "source": c["source"] or "seed",
                "capturedAt": c["captured_at"],
            }
            for c in consent
            if (mapped := _consent_channel(c["channel"])) is not None
        ]
        if account_id:
            customer["ledger"] = _rows(
                conn.execute(
                    text(
                        """
                        SELECT id, posted_at AS date, description, type, amount, balance, invoice_id AS "invoiceId"
                        FROM ledger_entries
                        WHERE account_id = :account_id
                        ORDER BY posted_at DESC
                        """
                    ),
                    {"account_id": account_id},
                )
            )
            customer["emi"] = [
                {
                    "id": r["id"],
                    "index": r["installment_index"],
                    "dueDate": r["due_date"],
                    "amount": r["amount"],
                    "paidOn": r["paid_on"],
                    "paidAmount": r["paid_amount"],
                    "status": r["status"],
                    "balanceCarried": r["balance_carried"],
                }
                for r in _rows(
                    conn.execute(
                        text(
                            """
                            SELECT id, installment_index, due_date, amount, paid_on,
                                   paid_amount, status, balance_carried
                            FROM emi_installments
                            WHERE account_id = :account_id
                            ORDER BY installment_index
                            """
                        ),
                        {"account_id": account_id},
                    )
                )
            ]
        else:
            customer["ledger"] = []
            customer["emi"] = []
        customer["interactions"] = _interaction_contracts(conn, customer_id=customer_id, limit=25)
        customer["promises"] = _promise_contracts(conn, customer_id)
        customer["disputes"] = _dispute_contracts(conn, customer_id)
        customer["documents"] = _document_contracts(conn, customer_id)
        customer["notes"] = _note_contracts(conn, customer_id)

    return CustomerResponse(**customer)


def list_customers() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [_dump(_customer_contract(conn, row, include_detail=False)) for row in _base_customer_row(conn)]


def get_customer(customer_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        rows = _base_customer_row(conn, customer_id)
        if not rows:
            return None
        return _dump(_customer_contract(conn, rows[0], include_detail=True))


def _interaction_contracts(conn: Any, customer_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    where = "WHERE i.customer_id = :customer_id" if customer_id else ""
    params = {"customer_id": customer_id}
    limit_sql = "LIMIT :limit" if limit else ""
    if limit:
        params["limit"] = limit
    interactions = _rows(
        conn.execute(
            text(
                f"""
                SELECT
                  i.id,
                  i.channel,
                  i.handler_kind,
                  COALESCE(u.name, b.name) AS handler_name,
                  i.started_at,
                  i.duration_sec,
                  i.disposition,
                  i.sentiment_label,
                  i.avg_sentiment,
                  i.summary,
                  i.query_resolved,
                  i.upsell_presented,
                  i.ptp_captured
                FROM interactions i
                LEFT JOIN users u ON u.id = i.handler_user_id
                LEFT JOIN bots b ON b.id = i.handler_bot_id
                {where}
                ORDER BY i.started_at DESC NULLS LAST, i.id
                {limit_sql}
                """
            ),
            params,
        )
    )
    output = []
    for interaction in interactions:
        transcript = _rows(
            conn.execute(
                text(
                    """
                    SELECT text
                    FROM interaction_transcript
                    WHERE interaction_id = :interaction_id
                    ORDER BY turn_index
                    """
                ),
                {"interaction_id": interaction["id"]},
            )
        )
        output.append(
            {
                "id": interaction["id"],
                "channel": interaction["channel"],
                "handler": {"kind": interaction["handler_kind"], "name": interaction["handler_name"] or "Unknown"},
                "startedAt": interaction["started_at"],
                "duration": _duration(interaction["duration_sec"]),
                "disposition": interaction["disposition"],
                "sentiment": interaction["sentiment_label"] or "neutral",
                "sentimentDelta": _sentiment_delta(interaction["avg_sentiment"]),
                "summary": interaction["summary"],
                "intents": {
                    "queryResolved": bool(interaction["query_resolved"]),
                    "upsellPresented": bool(interaction["upsell_presented"]),
                    "ptpCaptured": bool(interaction["ptp_captured"]),
                },
                "transcript": [t["text"] for t in transcript],
            }
        )
    return output


def _promise_contracts(conn: Any, customer_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT p.id, p.amount, p.promised_at, p.created_at, p.channel, p.status,
                       p.reminder_status, COALESCE(u.name, b.name) AS handler
                FROM promises p
                LEFT JOIN users u ON u.id = p.owner_user_id
                LEFT JOIN bots b ON b.id = p.owner_bot_id
                WHERE p.customer_id = :customer_id
                ORDER BY p.promised_at DESC
                """
            ),
            {"customer_id": customer_id},
        )
    )
    return [
        {
            "id": r["id"],
            "amount": r["amount"],
            "promisedDate": r["promised_at"],
            "createdAt": r["created_at"],
            "channel": r["channel"],
            "handler": r["handler"] or "Unassigned",
            "status": _ptp_status(r["status"]),
            "reminderStatus": _reminder_status(r["reminder_status"]),
        }
        for r in rows
    ]


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
                """
            ),
            {"customer_id": customer_id},
        )
    )
    return [
        {
            "id": r["id"],
            "type": r["type"],
            "amount": r["disputed_amount"],
            "transcriptSnippet": r["transcript_snippet"] or "",
            "status": r["status"],
            "slaLabel": _sla_label(r["sla_due_at"]),
            "filedAt": r["created_at"],
            "assignee": r["assignee"],
        }
        for r in rows
    ]


def _document_contracts(conn: Any, customer_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, doc_type, delivery_channel, status, created_at
                FROM document_requests
                WHERE customer_id = :customer_id
                ORDER BY created_at DESC
                """
            ),
            {"customer_id": customer_id},
        )
    )
    return [
        {
            "id": r["id"],
            "type": r["doc_type"],
            "requestedVia": "voice",
            "requestedAt": r["created_at"],
            "deliveryChannel": _doc_channel(r["delivery_channel"]),
            "status": r["status"],
        }
        for r in rows
    ]


def _note_contracts(conn: Any, customer_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT n.id, COALESCE(u.name, 'System') AS author, n.created_at, n.text, n.pinned
                FROM customer_notes n
                LEFT JOIN users u ON u.id = n.author_user_id
                WHERE n.customer_id = :customer_id
                ORDER BY n.created_at DESC
                """
            ),
            {"customer_id": customer_id},
        )
    )
    return [{"id": r["id"], "author": r["author"], "at": r["created_at"], "text": r["text"], "pinned": r["pinned"]} for r in rows]


def _promise_events(conn: Any, promise_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """activity_events grouped by promise id, for the promises-screen timeline."""
    if not promise_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT entity_id, at, label, tone
                FROM activity_events
                WHERE entity_type = 'promise' AND entity_id = ANY(:ids)
                ORDER BY at
                """
            ),
            {"ids": promise_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append({"at": r["at"], "label": r["label"], "tone": r["tone"]})
    return grouped


def list_promises() -> list[dict[str, Any]]:
    """Promise-to-Pay screen feed (richer than the Customer 360 contract)."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT p.id, p.customer_id, c.name AS customer_name, p.account_id,
                           p.amount, p.promised_at, p.created_at, p.channel, p.status,
                           p.reminder_status, p.paid_amount, p.plan_id, p.owner_kind,
                           COALESCE(u.name, b.name) AS owner
                    FROM promises p
                    JOIN customers c ON c.id = p.customer_id
                    LEFT JOIN users u ON u.id = p.owner_user_id
                    LEFT JOIN bots b ON b.id = p.owner_bot_id
                    ORDER BY p.promised_at DESC
                    """
                )
            )
        )
        events = _promise_events(conn, [r["id"] for r in rows])
        result = []
        for r in rows:
            evts = events.get(r["id"]) or [{"at": r["created_at"], "label": "Promise captured", "tone": "info"}]
            result.append(
                {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountTail": _account_tail(r["account_id"]) or "",
                    "amount": r["amount"],
                    "promisedDate": r["promised_at"],
                    "createdAt": r["created_at"],
                    "channel": r["channel"] or "voice",
                    "source": "bot" if r["owner_kind"] == "bot" else "agent",
                    "owner": r["owner"] or "Unassigned",
                    "reminderStatus": _reminder_status_screen(r["reminder_status"]),
                    "status": r["status"],
                    "paidAmount": r["paid_amount"] if r["paid_amount"] else None,
                    "notes": None,
                    "planId": r["plan_id"],
                    "events": evts,
                }
            )
        return result


def _plan_cadence(due_dates: list[str]) -> str:
    """Infer cadence from the gap between the first two installments."""
    if len(due_dates) < 2:
        return "monthly"
    parsed = sorted(datetime.fromisoformat(d) for d in due_dates)
    gap = (parsed[1] - parsed[0]).days
    if gap <= 8:
        return "weekly"
    if gap <= 17:
        return "biweekly"
    return "monthly"


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


def _document_events(conn: Any, document_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """activity_events grouped by document_request id, for the Documents timeline."""
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


def list_staff() -> list[dict[str, Any]]:
    """Assignable actors: active humans first, then bots."""
    with engine.connect() as conn:
        users = _rows(
            conn.execute(
                text(
                    """
                    SELECT u.id, u.name, t.name AS team, u.status
                    FROM users u
                    LEFT JOIN teams t ON t.id = u.team_id
                    ORDER BY u.name
                    """
                )
            )
        )
        bots = _rows(conn.execute(text("SELECT id, name FROM bots ORDER BY name")))
        return [
            {"id": u["id"], "name": u["name"], "kind": "human", "team": u["team"], "status": u["status"]}
            for u in users
        ] + [
            {"id": b["id"], "name": b["name"], "kind": "bot", "team": None, "status": "active"}
            for b in bots
        ]


def list_teams() -> list[dict[str, Any]]:
    """Queue roster for pickers — real teams, no hardcoded name→id map."""
    with engine.connect() as conn:
        return _rows(conn.execute(text("SELECT id, name FROM teams ORDER BY name")))


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

    Preferred windows in this product are expressed in IST; comparing against the
    UTC hour of a timestamptz would falsely flag every morning slot as DND.
    """
    try:
        at = datetime.fromisoformat(scheduled_at)
    except ValueError:
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    local = at.astimezone(timezone(timedelta(hours=5, minutes=30)))
    hour = local.hour
    if not preferred_window:
        return hour < 9 or hour >= 20
    m = re.search(r"(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})", preferred_window)
    if not m:
        return hour < 9 or hour >= 20
    start_h, end_h = int(m.group(1)), int(m.group(3))
    return hour < start_h or hour >= end_h


def _callback_dnd_active(customer_dnd: bool, preferred_window: str | None, scheduled_at: str) -> bool:
    return bool(customer_dnd) or _outside_preferred_window(scheduled_at, preferred_window)


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


def list_callbacks() -> list[dict[str, Any]]:
    """Callback & Scheduling Manager feed (richer than the Phase 3A write contract)."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT cb.id, cb.customer_id, c.name AS customer_name, cb.account_id,
                           cb.reason, cb.scheduled_at, cb.window_mins, cb.dnd_active,
                           cb.status, cb.disposition, cb.priority, cb.transcript_snippet,
                           cb.outcome_notes, cb.interaction_id, cb.created_at,
                           c.timezone AS customer_timezone, c.preferred_window,
                           c.dnd AS customer_dnd,
                           u.name AS assignee, t.name AS queue,
                           i.channel AS interaction_channel, i.handler_kind
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                    LEFT JOIN users u ON u.id = cb.assignee_user_id
                    LEFT JOIN teams t ON t.id = cb.team_id
                    LEFT JOIN interactions i ON i.id = cb.interaction_id
                    ORDER BY cb.scheduled_at
                    """
                )
            )
        )
        ids = [r["id"] for r in rows]
        events = _callback_events(conn, ids)
        reminders = _callback_reminders(conn, ids)
        result = []
        for r in rows:
            preferred = r["preferred_window"] or "10:00–19:00 IST"
            scheduled = r["scheduled_at"]
            customer_dnd = bool(r["customer_dnd"])
            dnd_active = _callback_dnd_active(customer_dnd, preferred, scheduled)
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
                    "customerTimezone": r["customer_timezone"] or "Asia/Kolkata (IST)",
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


_DAY_NAME_TO_NUM = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
_DAY_NUM_TO_NAME = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
_CONSENT_CHANNEL_ORDER = ("call", "whatsapp", "sms", "email")
_OPT_OUT_SOURCE_MAP = {
    "ivr": "IVR",
    "agent": "Agent",
    "agent-captured": "Agent",
    "web": "Web",
    "self-serve": "Web",
    "customer": "Web",
    "regulator": "Regulator",
    "bulk import": "Bulk Import",
    "bulk_import": "Bulk Import",
    "whatsapp reply": "WhatsApp Reply",
    "whatsapp_reply": "WhatsApp Reply",
    "onboarding": "Onboarding",
    "seed-default": "Onboarding",
    "seed": "Onboarding",
}
_CONSENT_ACTIVITY_KINDS = (
    "consent_updated",
    "consent_renewed",
    "opt_out",
    "dnd_updated",
)


def _consent_segment(raw: str | None) -> str:
    key = (raw or "retail").strip().lower()
    return {"retail": "Retail", "sme": "SME", "priority": "Priority"}.get(key, "Retail")


def _consent_source_screen(raw: str | None) -> str:
    if not raw:
        return "Onboarding"
    if raw in {"IVR", "Agent", "Web", "Regulator", "Bulk Import", "WhatsApp Reply", "Onboarding"}:
        return raw
    return _OPT_OUT_SOURCE_MAP.get(raw.strip().lower(), "Agent")


def _optout_source_screen(raw: str | None) -> str:
    mapped = _consent_source_screen(raw)
    return "Web" if mapped == "Onboarding" else mapped


def _consent_channel_db(channel: str) -> str:
    if channel == "call":
        return "voice"
    if channel == "all":
        return "all"
    return channel


def _consent_channel_screen(channel: str) -> str | None:
    if channel == "all":
        return "all"
    return _consent_channel(channel)


def _parse_allowed_days(raw: str | None) -> list[int]:
    if not raw:
        return [1, 2, 3, 4, 5]
    text_val = raw.strip().lower()
    if "-" in text_val and "," not in text_val:
        parts = [p.strip() for p in text_val.split("-", 1)]
        if len(parts) == 2 and parts[0][:3] in _DAY_NAME_TO_NUM and parts[1][:3] in _DAY_NAME_TO_NUM:
            start, end = _DAY_NAME_TO_NUM[parts[0][:3]], _DAY_NAME_TO_NUM[parts[1][:3]]
            if start <= end:
                return list(range(start, end + 1))
            return list(range(start, 7)) + list(range(0, end + 1))
    days: list[int] = []
    for token in re.split(r"[,\s]+", text_val):
        key = token[:3]
        if key in _DAY_NAME_TO_NUM:
            days.append(_DAY_NAME_TO_NUM[key])
    return days or [1, 2, 3, 4, 5]


def _format_allowed_days(days: list[int]) -> str:
    unique = sorted({d for d in days if 0 <= d <= 6})
    if not unique:
        return "Mon-Fri"
    if unique == list(range(unique[0], unique[-1] + 1)):
        return f"{_DAY_NUM_TO_NAME[unique[0]]}-{_DAY_NUM_TO_NAME[unique[-1]]}"
    return ",".join(_DAY_NUM_TO_NAME[d] for d in unique)


def _parse_allowed_hours(raw: str | None) -> tuple[int, int]:
    if not raw:
        return 10, 19
    m = re.search(r"(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})", raw)
    if not m:
        return 10, 19
    return int(m.group(1)), int(m.group(3))


def _format_allowed_hours(start_hour: int, end_hour: int) -> str:
    return f"{int(start_hour):02d}:00-{int(end_hour):02d}:00 IST"


def _optout_actor_label(actor_kind: str | None, user_name: str | None) -> str:
    if user_name:
        return user_name
    kind = (actor_kind or "").lower()
    if kind == "customer":
        return "Customer"
    if kind == "system":
        return "System"
    if kind == "regulator":
        return "Regulator"
    if kind == "bot":
        return "Bot"
    return "System"


def _consent_channels_grouped(conn: Any, consent_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not consent_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT consent_id, channel, status, source, captured_at,
                       weekly_frequency_cap, used_this_week, created_at
                FROM channel_consents
                WHERE consent_id = ANY(:ids)
                ORDER BY channel
                """
            ),
            {"ids": consent_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        mapped = _consent_channel_screen(r["channel"])
        if mapped is None or mapped == "all":
            continue
        grouped.setdefault(r["consent_id"], []).append(
            {
                "channel": mapped,
                "status": r["status"] if r["status"] in {"opted_in", "opted_out", "dnd", "expired"} else "opted_out",
                "capturedAt": r["captured_at"] or r["created_at"],
                "source": _consent_source_screen(r["source"]),
                "frequencyCapPerWeek": int(r["weekly_frequency_cap"] or 3),
                "usedThisWeek": int(r["used_this_week"] or 0),
            }
        )
    return grouped


def _consent_optouts_grouped(conn: Any, consent_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not consent_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT o.id, o.consent_id, o.channel, o.source, o.actor_kind, o.note,
                       o.occurred_at, u.name AS actor_name
                FROM optout_events o
                LEFT JOIN users u ON u.id = o.actor_user_id
                WHERE o.consent_id = ANY(:ids)
                ORDER BY o.occurred_at
                """
            ),
            {"ids": consent_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        mapped = _consent_channel_screen(r["channel"])
        if mapped is None:
            continue
        grouped.setdefault(r["consent_id"], []).append(
            {
                "id": r["id"],
                "at": r["occurred_at"],
                "channel": mapped,
                "source": _optout_source_screen(r["source"]),
                "actor": _optout_actor_label(r["actor_kind"], r["actor_name"]),
                "note": r["note"] or "",
            }
        )
    return grouped


def _consent_audit_grouped(conn: Any, customer_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not customer_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.id, ae.entity_id, ae.at, ae.label, u.name AS actor
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'customer'
                  AND ae.entity_id = ANY(:ids)
                  AND ae.kind = ANY(:kinds)
                ORDER BY ae.at
                """
            ),
            {"ids": customer_ids, "kinds": list(_CONSENT_ACTIVITY_KINDS)},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(
            {
                "id": r["id"],
                "at": r["at"],
                "actor": r["actor"] or "System",
                "action": r["label"],
            }
        )
    return grouped


def _ensure_channels_complete(channels: list[dict[str, Any]], fallback_at: str) -> list[dict[str, Any]]:
    by_channel = {c["channel"]: c for c in channels}
    complete: list[dict[str, Any]] = []
    for ch in _CONSENT_CHANNEL_ORDER:
        if ch in by_channel:
            complete.append(by_channel[ch])
        else:
            complete.append(
                {
                    "channel": ch,
                    "status": "opted_in",
                    "capturedAt": fallback_at,
                    "source": "Onboarding",
                    "frequencyCapPerWeek": 3,
                    "usedThisWeek": 0,
                }
            )
    return complete


def list_consent() -> list[dict[str, Any]]:
    """Consent & Communication Preferences feed (richer than Customer 360 consent)."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT cr.id, cr.customer_id, cr.dnd_registry, cr.expires_at,
                           cr.allowed_days, cr.allowed_hours, cr.created_at,
                           c.name AS customer_name, c.phone_primary, c.email,
                           c.timezone, c.segment, c.preferred_window, c.dnd AS customer_dnd,
                           a.id AS account_id
                    FROM consent_records cr
                    JOIN customers c ON c.id = cr.customer_id
                    LEFT JOIN LATERAL (
                      SELECT *
                      FROM accounts a
                      WHERE a.customer_id = c.id
                      ORDER BY
                        CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END,
                        a.created_at,
                        a.id
                      LIMIT 1
                    ) a ON true
                    ORDER BY c.name
                    """
                )
            )
        )
        consent_ids = [r["id"] for r in rows]
        customer_ids = [r["customer_id"] for r in rows]
        channels = _consent_channels_grouped(conn, consent_ids)
        optouts = _consent_optouts_grouped(conn, consent_ids)
        audits = _consent_audit_grouped(conn, customer_ids)
        result: list[dict[str, Any]] = []
        for r in rows:
            created = r["created_at"]
            hours_raw = r["allowed_hours"] or r["preferred_window"]
            start_h, end_h = _parse_allowed_hours(hours_raw)
            expires = r["expires_at"]
            if not expires:
                try:
                    base = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                except ValueError:
                    base = datetime.now(timezone.utc)
                expires = (base + timedelta(days=365)).isoformat()
            audit = audits.get(r["customer_id"]) or [
                {
                    "id": f"A-{r['id']}",
                    "at": created,
                    "actor": "Onboarding",
                    "action": "Consent captured",
                }
            ]
            result.append(
                {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountId": r["account_id"] or "",
                    "phone": r["phone_primary"] or "",
                    "email": r["email"] or "",
                    "timezone": r["timezone"] or "Asia/Kolkata",
                    "segment": _consent_segment(r["segment"]),
                    "channels": _ensure_channels_complete(channels.get(r["id"]) or [], created),
                    "allowedWindow": {
                        "days": _parse_allowed_days(r["allowed_days"]),
                        "startHour": start_h,
                        "endHour": end_h,
                    },
                    "consentExpiresAt": expires,
                    "onDndRegistry": bool(r["dnd_registry"] or r["customer_dnd"]),
                    "optOutLog": optouts.get(r["id"]) or [],
                    "audit": audit,
                }
            )
        return result


def list_disputes() -> list[dict[str, Any]]:
    """Disputes & Exceptions queue feed (richer than the Customer 360 contract)."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT d.id, d.customer_id, c.name AS customer_name, d.account_id,
                           d.type, d.disputed_amount, d.source, d.transcript_snippet,
                           d.interaction_id, d.created_at, d.sla_due_at, d.status,
                           d.priority, d.resolution_code, d.resolution_notes,
                           u.name AS assignee, i.channel AS interaction_channel
                    FROM disputes d
                    JOIN customers c ON c.id = d.customer_id
                    LEFT JOIN users u ON u.id = d.assignee_user_id
                    LEFT JOIN interactions i ON i.id = d.interaction_id
                    ORDER BY d.created_at DESC
                    """
                )
            )
        )
        ids = [r["id"] for r in rows]
        events = _dispute_events(conn, ids)
        evidence = _dispute_evidence(conn, ids)
        result = []
        for r in rows:
            captured = r["created_at"]
            sla = r["sla_due_at"] or captured
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
                    "slaDueAt": sla,
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


def list_documents() -> list[dict[str, Any]]:
    """Document Fulfilment Desk feed (richer than the Customer 360 contract)."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT dr.id, dr.customer_id, c.name AS customer_name, dr.account_id,
                           dr.doc_type, dr.period, dr.requested_via, dr.delivery_channel,
                           dr.delivery_target, dr.status, dr.template_id, dr.generated_at,
                           dr.sent_at, dr.failed_reason, dr.size_kb, dr.attempts,
                           dr.created_at, dr.interaction_id,
                           c.phone_primary, c.email,
                           u.name AS assignee,
                           i.channel AS interaction_channel, i.handler_kind,
                           f.generated_at AS file_generated_at,
                           f.size_bytes AS file_size_bytes,
                           da.sent_at AS delivery_sent_at
                    FROM document_requests dr
                    JOIN customers c ON c.id = dr.customer_id
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
                    """
                )
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


def list_payment_plans() -> list[dict[str, Any]]:
    """Payment-plans table for the Promises screen; owner/cadence/start derived."""
    with engine.connect() as conn:
        plans = _rows(
            conn.execute(
                text(
                    """
                    SELECT pp.id, pp.customer_id, c.name AS customer_name, pp.account_id,
                           pp.total_amount, pp.created_at
                    FROM payment_plans pp
                    JOIN customers c ON c.id = pp.customer_id
                    ORDER BY pp.created_at DESC
                    """
                )
            )
        )
        if not plans:
            return []
        plan_ids = [p["id"] for p in plans]
        inst_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT plan_id, installment_index, due_date, amount, paid_status, paid_at
                    FROM promise_installments
                    WHERE plan_id = ANY(:ids)
                    ORDER BY plan_id, installment_index
                    """
                ),
                {"ids": plan_ids},
            )
        )
        owner_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (p.plan_id) p.plan_id, COALESCE(u.name, b.name) AS owner
                    FROM promises p
                    LEFT JOIN users u ON u.id = p.owner_user_id
                    LEFT JOIN bots b ON b.id = p.owner_bot_id
                    WHERE p.plan_id = ANY(:ids)
                    ORDER BY p.plan_id, p.created_at
                    """
                ),
                {"ids": plan_ids},
            )
        )
        owners = {r["plan_id"]: r["owner"] for r in owner_rows}
        by_plan: dict[str, list[dict[str, Any]]] = {}
        for r in inst_rows:
            by_plan.setdefault(r["plan_id"], []).append(r)

        now = datetime.now(timezone.utc)
        result = []
        for p in plans:
            installments = by_plan.get(p["id"], [])
            mapped = [
                {
                    "index": i["installment_index"],
                    "dueDate": i["due_date"],
                    "amount": i["amount"],
                    "paid": i["paid_status"] == "kept",
                    "paidOn": i["paid_at"],
                }
                for i in installments
            ]
            due_dates = [i["due_date"] for i in installments]
            all_paid = bool(mapped) and all(m["paid"] for m in mapped)
            overdue = any(
                (not m["paid"]) and datetime.fromisoformat(m["dueDate"]) < now for m in mapped
            )
            status = "completed" if all_paid else ("slipped" if overdue else "on_track")
            result.append(
                {
                    "id": p["id"],
                    "customerId": p["customer_id"],
                    "customerName": p["customer_name"],
                    "accountTail": _account_tail(p["account_id"]) or "",
                    "total": p["total_amount"],
                    "cadence": _plan_cadence(due_dates),
                    "startDate": min(due_dates) if due_dates else p["created_at"],
                    "installments": mapped,
                    "owner": owners.get(p["id"]) or "Unassigned",
                    "status": status,
                    "createdAt": p["created_at"],
                }
            )
        return result


def list_calls() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      i.id,
                      i.started_at,
                      i.duration_sec,
                      i.channel,
                      i.direction,
                      i.handler_kind,
                      COALESCE(u.name, b.name) AS handled_by,
                      i.customer_id,
                      c.name AS customer_name,
                      c.phone_primary,
                      i.account_id,
                      i.disposition,
                      i.summary,
                      i.avg_sentiment,
                      i.sentiment_label,
                      i.redaction_applied,
                      i.hash,
                      i.rag_hits,
                      i.latency_ms
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN users u ON u.id = i.handler_user_id
                    LEFT JOIN bots b ON b.id = i.handler_bot_id
                    ORDER BY i.started_at DESC NULLS LAST, i.id
                    """
                )
            )
        )
        calls = []
        for row in rows:
            transcript = _rows(
                conn.execute(
                    text(
                        """
                        SELECT id, at_sec AS t, speaker, text
                        FROM interaction_transcript
                        WHERE interaction_id = :interaction_id
                        ORDER BY turn_index
                        """
                    ),
                    {"interaction_id": row["id"]},
                )
            )
            flags = _rows(
                conn.execute(
                    text("SELECT flag, severity FROM interaction_flags WHERE interaction_id = :interaction_id ORDER BY created_at"),
                    {"interaction_id": row["id"]},
                )
            )
            sentiment_series = _rows(
                conn.execute(
                    text(
                        """
                        SELECT at_sec AS t, score AS v
                        FROM interaction_sentiment
                        WHERE interaction_id = :interaction_id
                        ORDER BY at_sec
                        """
                    ),
                    {"interaction_id": row["id"]},
                )
            )
            disclosures = _rows(
                conn.execute(
                    text(
                        """
                        SELECT id, label, read, read_at_sec AS "atSec"
                        FROM interaction_disclosures
                        WHERE interaction_id = :interaction_id
                        ORDER BY id
                        """
                    ),
                    {"interaction_id": row["id"]},
                )
            )
            handled_by = {"kind": row["handler_kind"]}
            if row["handler_kind"] == "bot":
                handled_by["bot"] = row["handled_by"] or "Bot"
            else:
                handled_by["agent"] = row["handled_by"] or "Agent"
            calls.append(
                _dump(
                    CallResponse(
                        id=row["id"],
                        startedAt=row["started_at"],
                        duration=row["duration_sec"] or 0,
                        channel=row["channel"],
                        direction=row["direction"],
                        handledBy=handled_by,
                        customerId=row["customer_id"],
                        customerName=row["customer_name"],
                        accountId=row["account_id"],
                        disposition=row["disposition"],
                        summary=row["summary"],
                        avgSentiment=row["avg_sentiment"],
                        sentiment=row["sentiment_label"] or "neutral",
                        redactionApplied=bool(row["redaction_applied"]),
                        hash=row["hash"],
                        ragHits=row["rag_hits"] or 0,
                        latencyMs=row["latency_ms"],
                        transcript=transcript,
                        flags=flags,
                        phoneMasked=row["phone_primary"] or "",
                        tags=[row["disposition"]] if row["disposition"] else [],
                        sentimentSeries=sentiment_series,
                        disclosures=disclosures,
                        routing=["Postgres", "API"],
                    )
                )
            )
    return calls


def list_leads() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      l.id,
                      l.customer_id,
                      c.name AS customer_name,
                      l.account_id,
                      l.product_id,
                      p.name AS product,
                      l.stage,
                      l.source,
                      l.sentiment_at_capture,
                      l.sentiment_score,
                      l.estimated_value,
                      l.offer_amount,
                      l.offer_roi,
                      l.priority,
                      l.captured_at,
                      l.interaction_id,
                      l.transcript_snippet,
                      u.name AS owner,
                      t.name AS team
                    FROM leads l
                    JOIN customers c ON c.id = l.customer_id
                    LEFT JOIN products p ON p.id = l.product_id
                    LEFT JOIN users u ON u.id = l.owner_user_id
                    LEFT JOIN teams t ON t.id = l.team_id
                    ORDER BY l.captured_at DESC NULLS LAST, l.id
                    """
                )
            )
        )
        leads = []
        for row in rows:
            eligibility = _rows(
                conn.execute(
                    text("SELECT label, passed AS ok, reason AS detail FROM lead_eligibility WHERE lead_id = :lead_id ORDER BY id"),
                    {"lead_id": row["id"]},
                )
            )
            leads.append(
                _dump(
                    LeadResponse(
                        id=row["id"],
                        customerId=row["customer_id"],
                        customerName=row["customer_name"],
                        accountId=row["account_id"],
                        accountTail=_account_tail(row["account_id"]),
                        offer={
                            "productId": row["product_id"],
                            "label": row["product"] or row["product_id"],
                            "indicativeAmount": row["offer_amount"],
                            "indicativeROI": row["offer_roi"],
                        },
                        stage=row["stage"],
                        capturedAt=row["captured_at"],
                        sourceCallId=row["interaction_id"],
                        source=row["source"],
                        sentimentAtCapture=row["sentiment_at_capture"],
                        sentimentScore=row["sentiment_score"],
                        transcriptSnippet=row["transcript_snippet"],
                        eligibilityFlags=eligibility,
                        owner=row["owner"],
                        team=row["team"],
                        priority=row["priority"],
                        estimatedValue=row["estimated_value"],
                        nextFollowUpAt=None,
                        followUps=[],
                        events=[
                            {
                                "at": row["captured_at"],
                                "kind": "created",
                                "by": row["owner"] or "System",
                                "note": row["source"],
                            }
                        ],
                    )
                )
            )
    return leads


def get_dashboard(range: str = "30d", segment: str = "all", team: str = "all") -> dict[str, Any]:
    with engine.connect() as conn:
        summary = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      count(*)::int AS interactions,
                      count(*) FILTER (WHERE ptp_captured)::int AS ptp_captured,
                      count(*) FILTER (WHERE handler_kind = 'human')::int AS human_handled,
                      avg(avg_sentiment) AS avg_sentiment,
                      avg(duration_sec) AS avg_duration_sec
                    FROM interactions
                    """
                )
            )
        ) or {}
        risk = _rows(conn.execute(text("SELECT risk, count(*)::int AS customers FROM customers GROUP BY risk ORDER BY risk")))
        work = _rows(conn.execute(text("SELECT entity_type, count(*)::int AS items FROM work_items GROUP BY entity_type ORDER BY entity_type")))
        daily = _rows(
            conn.execute(
                text(
                    """
                    SELECT metric_date, resolved_calls, escalations, ptp_count, avg_sentiment
                    FROM analytics_daily
                    ORDER BY metric_date
                    """
                )
            )
        )
        at_risk = _rows(
            conn.execute(
                text(
                    """
                    SELECT c.id, c.name, a.id AS account, a.outstanding,
                           a.dpd AS days_past_due, c.risk, c.last_contact_at,
                           p.name AS product
                    FROM customers c
                    JOIN LATERAL (
                      SELECT *
                      FROM accounts a
                      WHERE a.customer_id = c.id
                      ORDER BY CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END, a.created_at, a.id
                      LIMIT 1
                    ) a ON true
                    JOIN products p ON p.id = a.product_id
                    WHERE c.risk IN ('critical','high','medium')
                    ORDER BY a.dpd DESC, a.outstanding DESC
                    LIMIT 6
                    """
                )
            )
        )
        leaderboard_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT u.name, COALESCE(t.name, 'Collections') AS team, COUNT(i.id)::int AS calls,
                           AVG(i.duration_sec)::int AS aht, AVG(i.avg_sentiment) AS csat
                    FROM users u
                    LEFT JOIN teams t ON t.id = u.team_id
                    LEFT JOIN interactions i ON i.handler_user_id = u.id
                    GROUP BY u.name, t.name
                    ORDER BY calls DESC, u.name
                    LIMIT 6
                    """
                )
            )
        )

    interactions = summary.get("interactions") or 0
    human = summary.get("human_handled") or 0
    bot = max(interactions - human, 0)
    aht = round(summary.get("avg_duration_sec") or 0)
    mm, ss = divmod(aht, 60)
    recovered = sum((row.get("outstanding") or 0) for row in at_risk) * 0.42
    ptp = summary.get("ptp_captured") or 0
    avg_sent = summary.get("avg_sentiment") or 0
    dashboard = {
        "heroKpis": [
            {"label": "Avg Handle Time (AHT)", "value": f"{mm}m {ss:02d}s", "raw": aht, "delta": -8.4, "deltaGood": "down", "sub": "Postgres live read", "spark": _spark(aht or 240)},
            {"label": "Upsell Conversion Rate", "value": "14.6%", "raw": 14.6, "unit": "%", "delta": 3.2, "deltaGood": "up", "sub": "eligibility-gated offers accepted", "spark": _spark(14)},
        ],
        "kpis": [
            {"key": "recovered", "label": "Total Dues Recovered", "value": f"${recovered/1000000:.2f}M", "delta": 12.1, "deltaGood": "up", "spark": _spark(80), "tone": "success"},
            {"key": "recoveryRate", "label": "Recovery Rate", "value": "68.4%", "delta": 2.7, "deltaGood": "up", "spark": _spark(65)},
            {"key": "containment", "label": "Bot Containment", "value": f"{(bot / interactions * 100 if interactions else 0):.1f}%", "delta": 5.9, "deltaGood": "up", "spark": _spark(66), "tone": "brand"},
            {"key": "ptp", "label": "Promise-Kept Rate", "value": "61.8%", "delta": -1.4, "deltaGood": "up", "spark": _spark(62), "tone": "warning"},
            {"key": "csat", "label": "Avg Sentiment / CSAT", "value": f"{avg_sent:.2f}", "delta": 0.08, "deltaGood": "up", "spark": _spark(55)},
            {"key": "calls", "label": "Calls Handled", "value": f"{interactions:,}", "delta": 6.3, "deltaGood": "up", "spark": _spark(260)},
        ],
        "recoveryTrend": [{"date": d["metric_date"], "value": d["resolved_calls"] * 12000} for d in daily] or [{"date": "2026-07-21", "value": round(recovered)}],
        "callVolumeStacked": [{"date": d["metric_date"], "voice": interactions, "whatsapp": 13, "chat": 0} for d in daily] or [{"date": "2026-07-21", "voice": interactions, "whatsapp": 13, "chat": 0}],
        "sentimentDistribution": {"positive": 58, "neutral": 27, "negative": 15},
        "botVsHuman": [
            {"name": "Contained by bot", "value": bot, "color": "var(--brand-primary)"},
            {"name": "Escalated to human", "value": human, "color": "var(--warning)"},
            {"name": "Direct to human", "value": max(human // 2, 0), "color": "var(--brand-navy)"},
        ],
        "leaderboard": [
            {
                "rank": idx + 1,
                "name": r["name"],
                "team": r["team"],
                "calls": r["calls"],
                "aht": _duration(r["aht"]),
                "upsell": round(12 + idx * 1.3, 1),
                "csat": round((r["csat"] or 0.6), 2),
            }
            for idx, r in enumerate(leaderboard_rows)
        ],
        "atRiskAccounts": [
            {
                "id": r["id"],
                "name": r["name"],
                "account": r["account"],
                "outstanding": r["outstanding"],
                "daysPastDue": r["days_past_due"],
                "risk": r["risk"],
                "lastContact": r["last_contact_at"],
                "product": _short_product(r["product"]),
            }
            for r in at_risk
        ],
    }
    return _dump(DashboardResponse(**dashboard))


def get_handoff_session() -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      i.id,
                      i.customer_id,
                      c.name AS customer_name,
                      i.account_id,
                      i.channel,
                      i.status,
                      i.disposition,
                      i.summary,
                      i.avg_sentiment,
                      COALESCE(u.name, b.name) AS handler
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN users u ON u.id = i.handler_user_id
                    LEFT JOIN bots b ON b.id = i.handler_bot_id
                    ORDER BY (i.status = 'active') DESC, i.started_at DESC NULLS LAST
                    LIMIT 1
                    """
                )
            )
        )
        if row is None:
            return None
        transcript = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, speaker, at_sec AS at, text, sentiment_delta AS "sentimentDelta"
                    FROM interaction_transcript
                    WHERE interaction_id = :interaction_id
                    ORDER BY turn_index
                    """
                ),
                {"interaction_id": row["id"]},
            )
        )
        suggestions = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, 'Suggested response' AS title, suggestion_text AS body, source, 1 AS "showAfter"
                    FROM ai_response_suggestions
                    WHERE interaction_id = :interaction_id
                    ORDER BY created_at
                    """
                ),
                {"interaction_id": row["id"]},
            )
        )
        customer = get_customer(row["customer_id"]) or {}
    return _dump(
        HandoffResponse(
            activeCall={
                "customerName": row["customer_name"],
                "accountId": row["account_id"],
                "phone": (customer.get("contact") or {}).get("phonePrimary", ""),
                "channel": f"{row['channel'].title()} · Postgres",
                "agentName": row["handler"] or "Unassigned",
                "transferredFrom": "Bot · Kaia v2.4",
                "escalationReason": row["disposition"] or "Live handoff",
                "startedAt": int(datetime.now().timestamp() * 1000),
            },
            customerContext={
                "risk": str(customer.get("risk", "medium")).title(),
                "outstanding": customer.get("outstanding") or 0,
                "currency": "₹",
                "lastPromise": ((customer.get("promises") or [{}])[0] if customer.get("promises") else {"amount": 0, "date": "", "status": "upcoming"}),
                "nextEmi": ((customer.get("emi") or [{}])[0] if customer.get("emi") else {"amount": 0, "dueDate": "", "daysOverdue": 0}),
                "openDisputes": len(customer.get("disputes") or []),
                "dnd": {"allowed": not (customer.get("contact") or {}).get("dnd", False), "window": (customer.get("contact") or {}).get("preferredWindow", ""), "channels": ["Voice", "WhatsApp"]},
                "tenureMonths": 34,
                "product": (customer.get("account") or {}).get("product", "Credit Card"),
            },
            transcriptScript=transcript,
            suggestions=suggestions,
            complianceItems=[
                {"id": "c1", "label": "Recording disclosure read", "required": True, "autoAt": 3},
                {"id": "c2", "label": "Identity verified", "required": True, "autoAt": 28},
                {"id": "c3", "label": "Mini-Miranda / debt-collection notice", "required": True},
                {"id": "c4", "label": "DND & consent window checked", "required": True, "autoAt": 1},
            ],
            dispositions=["PTP captured", "Payment taken", "Dispute - under review", "Info provided", "Callback scheduled", "Escalated to supervisor", "Unresolved - retry"],
        )
    )


def _promise_by_id(conn: Any, promise_id: str) -> dict[str, Any]:
    row = _one(conn.execute(text("SELECT customer_id FROM promises WHERE id = :id"), {"id": promise_id}))
    if row is None:
        raise KeyError("promise_not_found")
    for item in _promise_contracts(conn, row["customer_id"]):
        if item["id"] == promise_id:
            return item
    raise KeyError("promise_not_found")


def _dispute_by_id(conn: Any, dispute_id: str) -> dict[str, Any]:
    row = _one(conn.execute(text("SELECT customer_id FROM disputes WHERE id = :id"), {"id": dispute_id}))
    if row is None:
        raise KeyError("dispute_not_found")
    for item in _dispute_contracts(conn, row["customer_id"]):
        if item["id"] == dispute_id:
            return item
    raise KeyError("dispute_not_found")


def _document_by_id(conn: Any, document_id: str) -> dict[str, Any]:
    row = _one(conn.execute(text("SELECT customer_id FROM document_requests WHERE id = :id"), {"id": document_id}))
    if row is None:
        raise KeyError("document_not_found")
    for item in _document_contracts(conn, row["customer_id"]):
        if item["id"] == document_id:
            return item
    raise KeyError("document_not_found")


def _lead_by_id(conn: Any, lead_id: str) -> dict[str, Any]:
    row = _one(
        conn.execute(
            text(
                """
                SELECT l.id, l.customer_id, c.name AS customer_name, l.account_id, l.product_id,
                       p.name AS product, l.stage, l.source, l.sentiment_at_capture,
                       l.sentiment_score, l.estimated_value, l.offer_amount, l.offer_roi,
                       l.priority, l.captured_at, l.interaction_id, l.transcript_snippet,
                       u.name AS owner, t.name AS team, l.won_amount, l.loss_reason
                FROM leads l
                JOIN customers c ON c.id = l.customer_id
                LEFT JOIN products p ON p.id = l.product_id
                LEFT JOIN users u ON u.id = l.owner_user_id
                LEFT JOIN teams t ON t.id = l.team_id
                WHERE l.id = :id
                """
            ),
            {"id": lead_id},
        )
    )
    if row is None:
        raise KeyError("lead_not_found")
    eligibility = _rows(
        conn.execute(text("SELECT label, passed AS ok, reason AS detail FROM lead_eligibility WHERE lead_id = :lead_id ORDER BY id"), {"lead_id": lead_id})
    )
    followups = _rows(
        conn.execute(text("SELECT id, due_at AS at, 'voice' AS channel, note, status = 'done' AS done FROM followups WHERE lead_id = :lead_id ORDER BY due_at"), {"lead_id": lead_id})
    )
    return _dump(
        LeadResponse(
            id=row["id"],
            customerId=row["customer_id"],
            customerName=row["customer_name"],
            accountId=row["account_id"],
            accountTail=_account_tail(row["account_id"]),
            offer={
                "productId": row["product_id"],
                "label": row["product"] or row["product_id"],
                "indicativeAmount": row["offer_amount"] or row["estimated_value"] or row["won_amount"] or 0,
                "indicativeROI": row["offer_roi"] or "",
            },
            stage=row["stage"],
            capturedAt=row["captured_at"],
            sourceCallId=row["interaction_id"],
            source=row["source"],
            sentimentAtCapture=row["sentiment_at_capture"],
            sentimentScore=row["sentiment_score"],
            transcriptSnippet=row["transcript_snippet"],
            eligibilityFlags=eligibility,
            owner=row["owner"],
            team=row["team"],
            priority=row["priority"],
            estimatedValue=row["estimated_value"],
            nextFollowUpAt=followups[0]["at"] if followups else None,
            followUps=followups,
            events=[{"at": row["captured_at"], "kind": "created", "by": row["owner"] or "System"}],
            wonAmount=row["won_amount"],
            lossReason=row["loss_reason"],
        )
    )


def create_promise(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = "POST /promises"
    with engine.begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        account_id = payload.get("accountId") or _first_account_id(conn, customer_id)
        promise_id = _id("PTP")

        # Honour the chosen owner (human or bot); fall back to the acting user.
        owner_bot_id = payload.get("ownerBotId")
        owner_user_id = payload.get("ownerUserId")
        if owner_bot_id and owner_user_id:
            raise ValueError("provide either ownerUserId or ownerBotId, not both")
        if owner_bot_id:
            if not conn.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": owner_bot_id}).fetchone():
                raise KeyError(f"bot_not_found: {owner_bot_id}")
            owner_kind = "bot"
        else:
            owner_user_id = owner_user_id or _actor_user_id()
            if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": owner_user_id}).fetchone():
                raise KeyError(f"user_not_found: {owner_user_id}")
            owner_kind = "human"

        conn.execute(
            text(
                """
                INSERT INTO promises
                  (id, customer_id, account_id, interaction_id, owner_kind, owner_user_id,
                   owner_bot_id, amount, promised_at, status, reminder_status, paid_amount, channel)
                VALUES
                  (:id, :customer_id, :account_id, :interaction_id, :owner_kind, :owner_user_id,
                   :owner_bot_id, :amount, :promised_at, 'upcoming', :reminder_status, 0, :channel)
                """
            ),
            {
                "id": promise_id,
                "customer_id": customer_id,
                "account_id": account_id,
                "interaction_id": payload.get("interactionId"),
                "owner_kind": owner_kind,
                "owner_user_id": owner_user_id if owner_kind == "human" else None,
                "owner_bot_id": owner_bot_id if owner_kind == "bot" else None,
                "amount": payload["amount"],
                "promised_at": payload["promisedDate"],
                "reminder_status": payload.get("reminderStatus") or "queued",
                "channel": payload.get("channel") or "voice",
            },
        )
        _activity(conn, "promise", promise_id, "promise_created", "Promise-to-pay captured", f"Amount {payload['amount']}", customer_id)
        response = _promise_by_id(conn, promise_id)
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response


def patch_promise(promise_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT status, customer_id FROM promises WHERE id = :id"), {"id": promise_id}))
        if row is None:
            raise KeyError("promise_not_found")
        next_status = payload.get("status")
        if row["status"] == "kept" and next_status in {"broken", "partial"}:
            raise ValueError("kept promise cannot move to broken/partial")
        updates = []
        params = {"id": promise_id}
        if next_status:
            updates.append("status = :status")
            params["status"] = "due_today" if next_status == "upcoming" else next_status
        if payload.get("promisedDate"):
            updates.append("promised_at = :promised_at")
            params["promised_at"] = payload["promisedDate"]
        if payload.get("paidAmount") is not None:
            updates.append("paid_amount = :paid_amount")
            params["paid_amount"] = payload["paidAmount"]
        if updates:
            conn.execute(text(f"UPDATE promises SET {', '.join(updates)} WHERE id = :id"), params)
        if next_status == "broken":
            conn.execute(
                text(
                    """
                    INSERT INTO followups (id, promise_id, customer_id, assignee_user_id, status, priority, due_at, note)
                    VALUES (:id, :promise_id, :customer_id, :assignee_user_id, 'open', 'high', now() + interval '1 day', 'Broken promise follow-up')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": f"FU-{promise_id}", "promise_id": promise_id, "customer_id": row["customer_id"], "assignee_user_id": _actor_user_id()},
            )
        _activity(conn, "promise", promise_id, "promise_updated", "Promise updated", next_status, row["customer_id"])
        return _promise_by_id(conn, promise_id)


def create_payment_plan(payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        account_id = payload.get("accountId") or _first_account_id(conn, customer_id)
        plan_id = _id("PLAN")
        conn.execute(
            text("INSERT INTO payment_plans (id, customer_id, account_id, total_amount) VALUES (:id, :customer_id, :account_id, :total_amount)"),
            {"id": plan_id, "customer_id": customer_id, "account_id": account_id, "total_amount": payload["totalAmount"]},
        )
        for idx, item in enumerate(payload.get("installments") or [], start=1):
            conn.execute(
                text(
                    """
                    INSERT INTO promise_installments (id, plan_id, installment_index, due_date, amount, paid_status)
                    VALUES (:id, :plan_id, :installment_index, :due_date, :amount, 'upcoming')
                    """
                ),
                {"id": f"{plan_id}-{idx}", "plan_id": plan_id, "installment_index": idx, "due_date": item["dueDate"], "amount": item["amount"]},
            )
        first = (payload.get("installments") or [{}])[0]
        promise = create_promise({"customerId": customer_id, "accountId": account_id, "amount": first.get("amount", payload["totalAmount"]), "promisedDate": first.get("dueDate"), "channel": "voice"})
        conn.execute(text("UPDATE promises SET plan_id = :plan_id WHERE id = :id"), {"plan_id": plan_id, "id": promise["id"]})
        _activity(conn, "payment_plan", plan_id, "payment_plan_created", "Payment plan created", None, customer_id)
        return {"id": plan_id, "promise": _promise_by_id(conn, promise["id"])}


def create_dispute(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = "POST /disputes"
    with engine.begin() as conn:
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


def patch_dispute(dispute_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write,
    so an explicit None clears the column (used to unassign)."""
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id, assignee_user_id FROM disputes WHERE id = :id"), {"id": dispute_id}))
        if row is None:
            raise KeyError("dispute_not_found")
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
        if updates:
            conn.execute(text(f"UPDATE disputes SET {', '.join(updates)} WHERE id = :id"), params)

        status = payload.get("status")
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
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id FROM disputes WHERE id = :id"), {"id": dispute_id}))
        if row is None:
            raise KeyError("dispute_not_found")
        text_value = (payload.get("text") or "").strip()
        if not text_value:
            raise ValueError("note text is required")
        _activity(conn, "dispute", dispute_id, "note_added", text_value, None, row["customer_id"])
        return {"id": dispute_id, "text": text_value}


def add_dispute_evidence(dispute_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
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
                or f"minio://dispute-evidence/{TENANT_ID}/{dispute_id}/{payload['filename']}",
                "filename": payload["filename"],
                "mime_type": payload["mimeType"],
                "size_bytes": payload.get("sizeBytes"),
                "hash": payload.get("hash"),
                "uploaded_by_user_id": _actor_user_id(),
            },
        )
        _activity(conn, "dispute", dispute_id, "evidence_added", "Evidence added", payload["filename"], row["customer_id"])
        return {"id": evidence_id, **payload}


def create_callback(payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        cust = _one(
            conn.execute(
                text("SELECT dnd, preferred_window FROM customers WHERE id = :id"),
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
        dnd_active = _callback_dnd_active(bool(cust and cust["dnd"]), cust["preferred_window"] if cust else None, scheduled_at)

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
        return {"id": callback_id, "status": "scheduled"}


def patch_callback(callback_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write,
    so an explicit None clears assignee_user_id (unassign)."""
    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT cb.customer_id, c.dnd AS customer_dnd, c.preferred_window
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                    WHERE cb.id = :id
                    """
                ),
                {"id": callback_id},
            )
        )
        if row is None:
            raise KeyError("callback_not_found")

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
                bool(row["customer_dnd"]), row["preferred_window"], payload["scheduledAt"]
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
    with engine.begin() as conn:
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
        sent_at = datetime.now(timezone.utc).isoformat() if db_status == "sent" else None

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
                "scheduled_at": payload.get("scheduledAt") or datetime.now(timezone.utc).isoformat(),
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


def create_lead(payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        lead_id = _id("LD")
        product_id = payload["productId"]
        conn.execute(
            text(
                """
                INSERT INTO leads
                  (id, customer_id, account_id, interaction_id, product_id, owner_user_id, team_id,
                   stage, source, sentiment_at_capture, sentiment_score, estimated_value,
                   offer_amount, offer_roi, priority, captured_at, transcript_snippet)
                VALUES
                  (:id, :customer_id, :account_id, :interaction_id, :product_id, :owner_user_id, :team_id,
                   :stage, :source, :sentiment_at_capture, :sentiment_score, :estimated_value,
                   :offer_amount, :offer_roi, :priority, now(), :transcript_snippet)
                """
            ),
            {"id": lead_id, "customer_id": customer_id, "account_id": payload.get("accountId") or _first_account_id(conn, customer_id), "interaction_id": payload.get("interactionId"), "product_id": product_id, "owner_user_id": payload.get("ownerUserId") or _actor_user_id(), "team_id": payload.get("teamId") or "retail-sales", "stage": payload.get("stage") or "interested", "source": payload.get("source") or "agent", "sentiment_at_capture": payload.get("sentimentAtCapture") or "neutral", "sentiment_score": payload.get("sentimentScore"), "estimated_value": payload.get("estimatedValue"), "offer_amount": payload.get("offerAmount"), "offer_roi": payload.get("offerRoi"), "priority": payload.get("priority") or "normal", "transcript_snippet": payload.get("transcriptSnippet")},
        )
        # Phase 2-lite: persist evaluated eligibility (honest unknown for bureau/KYC).
        # Savepoint: a capture failure must not abort the lead write + trailing activity.
        try:
            import capture

            with conn.begin_nested():
                flags = payload.get("eligibilityFlags")
                if not isinstance(flags, list):
                    flags = capture.evaluate_product_eligibility(
                        conn, customer_id=customer_id, product_id=product_id
                    )
                capture.insert_lead_eligibility(conn, lead_id=lead_id, flags=flags)
                if payload.get("interactionId"):
                    capture.mark_upsell_presented(conn, payload.get("interactionId"))
                    capture.touch_primary_intent(conn, payload.get("interactionId"), "upsell_opportunity")
        except Exception:
            logger.exception("lead eligibility capture failed for %s", lead_id)
        _activity(conn, "lead", lead_id, "lead_created", "Lead created", None, customer_id)
        return _lead_by_id(conn, lead_id)


def patch_lead(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id FROM leads WHERE id = :id"), {"id": lead_id}))
        if row is None:
            raise KeyError("lead_not_found")
        mapping = {"stage": "stage", "productId": "product_id", "ownerUserId": "owner_user_id", "teamId": "team_id", "offerAmount": "offer_amount", "offerRoi": "offer_roi", "wonAmount": "won_amount", "lossReason": "loss_reason"}
        updates = []
        params = {"id": lead_id}
        for key, column in mapping.items():
            if payload.get(key) is not None:
                updates.append(f"{column} = :{column}")
                params[column] = payload[key]
        if updates:
            conn.execute(text(f"UPDATE leads SET {', '.join(updates)} WHERE id = :id"), params)
        _activity(conn, "lead", lead_id, "lead_updated", "Lead updated", payload.get("stage"), row["customer_id"])
        return _lead_by_id(conn, lead_id)


def add_lead_followup(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id, owner_user_id FROM leads WHERE id = :id"), {"id": lead_id}))
        if row is None:
            raise KeyError("lead_not_found")
        followup_id = _id("FU")
        conn.execute(
            text(
                """
                INSERT INTO followups (id, lead_id, customer_id, assignee_user_id, status, priority, due_at, note)
                VALUES (:id, :lead_id, :customer_id, :assignee_user_id, 'open', 'normal', :due_at, :note)
                """
            ),
            {"id": followup_id, "lead_id": lead_id, "customer_id": row["customer_id"], "assignee_user_id": row["owner_user_id"] or _actor_user_id(), "due_at": payload.get("scheduledAt") or datetime.now(timezone.utc).isoformat(), "note": payload.get("note") or "Lead follow-up"},
        )
        _activity(conn, "lead", lead_id, "lead_followup_created", "Lead follow-up scheduled", None, row["customer_id"])
        return {"id": followup_id, "status": "open"}


def patch_followup(followup_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id, lead_id, promise_id FROM followups WHERE id = :id"), {"id": followup_id}))
        if row is None:
            raise KeyError("followup_not_found")
        if payload.get("status"):
            conn.execute(text("UPDATE followups SET status = :status WHERE id = :id"), {"id": followup_id, "status": payload["status"]})
        entity_type = "lead" if row["lead_id"] else "promise"
        entity_id = row["lead_id"] or row["promise_id"] or followup_id
        _activity(conn, entity_type, entity_id, "followup_updated", "Follow-up updated", payload.get("status"), row["customer_id"])
        return {"id": followup_id, "status": payload.get("status")}


def create_document_request(payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
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
        if requested_via not in {"bot_voice", "bot_chat", "agent"}:
            requested_via = "agent"

        conn.execute(
            text(
                """
                INSERT INTO document_requests
                  (id, customer_id, account_id, interaction_id, assignee_user_id,
                   doc_type, period, requested_via, template_id,
                   delivery_channel, delivery_target, status, attempts, priority, sla_due_at)
                VALUES
                  (:id, :customer_id, :account_id, :interaction_id, :assignee_user_id,
                   :doc_type, :period, :requested_via, :template_id,
                   :delivery_channel, :delivery_target, 'requested', 0, 'normal', now() + interval '1 day')
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
        return _document_by_id(conn, document_id)


def patch_document_request(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write."""
    with engine.begin() as conn:
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
    with engine.begin() as conn:
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
        attempt_id = _id("DLV")
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
    existing = conn.execute(
        text("SELECT 1 FROM document_templates WHERE id = :id"), {"id": template_id}
    ).fetchone()
    if existing:
        return
    conn.execute(
        text(
            """
            INSERT INTO document_templates (id, name, doc_type, preview_lines)
            VALUES (:id, :name, :doc_type, '[]'::jsonb)
            """
        ),
        {"id": template_id, "name": template_id, "doc_type": doc_type},
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
    existing = _one(
        conn.execute(
            text("SELECT id FROM document_files WHERE request_id = :id ORDER BY created_at DESC LIMIT 1"),
            {"id": document_id},
        )
    )
    storage_ref = f"minio://documents/{TENANT_ID}/{document_id}.pdf"
    fname = filename or f"{document_id}.pdf"
    mime = mime_type or "application/pdf"
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


def add_customer_note(customer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        _ensure_customer(conn, customer_id)
        note_id = _id("NOTE")
        conn.execute(
            text(
                """
                INSERT INTO customer_notes (id, customer_id, author_user_id, text, pinned)
                VALUES (:id, :customer_id, :author_user_id, :text, :pinned)
                """
            ),
            {"id": note_id, "customer_id": customer_id, "author_user_id": _actor_user_id(), "text": payload["text"], "pinned": payload.get("pinned") or False},
        )
        _activity(conn, "customer", customer_id, "note_created", "Customer note added", payload["text"], customer_id)
    customer = get_customer(customer_id)
    if customer is None:
        raise KeyError("customer_not_found")
    return customer


def _ensure_consent_record(conn: Any, customer_id: str) -> str:
    consent_id = f"consent-{customer_id}"
    existing = _one(
        conn.execute(text("SELECT id FROM consent_records WHERE customer_id = :id"), {"id": customer_id})
    )
    if existing:
        return existing["id"]
    conn.execute(
        text(
            """
            INSERT INTO consent_records (id, customer_id, dnd_registry, allowed_days, allowed_hours)
            VALUES (:id, :customer_id, false, 'Mon-Fri', '10:00-19:00 IST')
            """
        ),
        {"id": consent_id, "customer_id": customer_id},
    )
    return consent_id


def _channel_status_from_patch(item: dict[str, Any]) -> str:
    status = item.get("status")
    if status in {"opted_in", "opted_out", "dnd", "expired"}:
        return status
    if "optedIn" in item:
        return "opted_in" if item.get("optedIn") else "opted_out"
    raise ValueError("channel status or optedIn is required")


def patch_consent(customer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write."""
    with engine.begin() as conn:
        _ensure_customer(conn, customer_id)
        consent_id = _ensure_consent_record(conn, customer_id)

        dnd_val = None
        if "dnd" in payload:
            dnd_val = payload["dnd"]
        elif "onDndRegistry" in payload:
            dnd_val = payload["onDndRegistry"]
        if dnd_val is not None:
            conn.execute(
                text("UPDATE customers SET dnd = :dnd WHERE id = :id"),
                {"dnd": bool(dnd_val), "id": customer_id},
            )
            conn.execute(
                text("UPDATE consent_records SET dnd_registry = :dnd WHERE id = :id"),
                {"dnd": bool(dnd_val), "id": consent_id},
            )

        if "consentExpiresAt" in payload and payload["consentExpiresAt"] is not None:
            conn.execute(
                text("UPDATE consent_records SET expires_at = :expires_at WHERE id = :id"),
                {"expires_at": payload["consentExpiresAt"], "id": consent_id},
            )

        if "allowedWindow" in payload and payload["allowedWindow"] is not None:
            aw = payload["allowedWindow"]
            days_str = _format_allowed_days(list(aw.get("days") or []))
            hours_str = _format_allowed_hours(int(aw.get("startHour", 10)), int(aw.get("endHour", 19)))
            conn.execute(
                text(
                    """
                    UPDATE consent_records
                    SET allowed_days = :days, allowed_hours = :hours
                    WHERE id = :id
                    """
                ),
                {"days": days_str, "hours": hours_str, "id": consent_id},
            )
            conn.execute(
                text("UPDATE customers SET preferred_window = :hours WHERE id = :id"),
                {"hours": hours_str, "id": customer_id},
            )

        for item in payload.get("channels") or []:
            if not isinstance(item, dict):
                item = item.model_dump() if hasattr(item, "model_dump") else dict(item)
            channel_value = _consent_channel_db(item["channel"])
            status = _channel_status_from_patch(item)
            source = item.get("source") or "Agent"
            cap = item.get("frequencyCapPerWeek")
            used = item.get("usedThisWeek")
            params: dict[str, Any] = {
                "id": f"{consent_id}-{channel_value}",
                "consent_id": consent_id,
                "channel": channel_value,
                "status": status,
                "source": source,
                "cap": cap,
                "used": used,
            }
            conn.execute(
                text(
                    """
                    INSERT INTO channel_consents
                      (id, consent_id, channel, status, source, weekly_frequency_cap, used_this_week, captured_at)
                    VALUES
                      (:id, :consent_id, :channel, :status, :source,
                       COALESCE(:cap, 3), COALESCE(:used, 0), now())
                    ON CONFLICT (consent_id, channel)
                    DO UPDATE SET
                      status = EXCLUDED.status,
                      source = EXCLUDED.source,
                      weekly_frequency_cap = COALESCE(:cap, channel_consents.weekly_frequency_cap),
                      used_this_week = COALESCE(:used, channel_consents.used_this_week),
                      captured_at = now()
                    """
                ),
                params,
            )

        note = (payload.get("note") or "").strip()
        if "consentExpiresAt" in payload and payload.get("consentExpiresAt"):
            kind, label = "consent_renewed", note or "Consent renewed for 12 months."
        elif dnd_val is not None and not payload.get("channels") and "allowedWindow" not in payload:
            kind = "dnd_updated"
            label = note or ("Added to DND registry (calls blocked)." if dnd_val else "Removed from DND registry.")
        else:
            kind, label = "consent_updated", note or "Consent preferences updated."
        _activity(conn, "customer", customer_id, kind, label, note or None, customer_id)

    customer = get_customer(customer_id)
    if customer is None:
        raise KeyError("customer_not_found")
    return customer


def opt_out(customer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    channel_raw = payload["channel"]
    affected = list(_CONSENT_CHANNEL_ORDER) if channel_raw == "all" else [channel_raw]
    source = payload.get("source") or "Agent"
    note = (payload.get("note") or "").strip() or None
    with engine.begin() as conn:
        _ensure_customer(conn, customer_id)
        consent_id = _ensure_consent_record(conn, customer_id)
        for ch in affected:
            channel_value = _consent_channel_db(ch)
            conn.execute(
                text(
                    """
                    INSERT INTO channel_consents
                      (id, consent_id, channel, status, source, captured_at)
                    VALUES
                      (:id, :consent_id, :channel, 'opted_out', :source, now())
                    ON CONFLICT (consent_id, channel)
                    DO UPDATE SET status = 'opted_out', source = EXCLUDED.source, captured_at = EXCLUDED.captured_at
                    """
                ),
                {
                    "id": f"{consent_id}-{channel_value}",
                    "consent_id": consent_id,
                    "channel": channel_value,
                    "source": source,
                },
            )
        # Screen shape stores one opt-out event (channel may be "all").
        event_channel = "all" if channel_raw == "all" else _consent_channel_db(channel_raw)
        conn.execute(
            text(
                """
                INSERT INTO optout_events
                  (id, consent_id, channel, source, actor_kind, actor_user_id, note)
                VALUES
                  (:id, :consent_id, :channel, :source, 'human', :actor_user_id, :note)
                """
            ),
            {
                "id": _id("OPTOUT"),
                "consent_id": consent_id,
                "channel": event_channel,
                "source": source,
                "actor_user_id": _actor_user_id(),
                "note": note,
            },
        )
        label = f"Opt-out captured via {source} ({channel_raw})."
        _activity(conn, "customer", customer_id, "opt_out", label, note, customer_id)
    customer = get_customer(customer_id)
    if customer is None:
        raise KeyError("customer_not_found")
    return customer


def _violation_status_screen(status: str | None) -> str:
    if status in {"open", "in_review", "acknowledged", "resolved"}:
        return status
    if status in {"reviewed", "review"}:
        return "acknowledged"
    return "open"


_RULE_ID_SCREEN = {
    "rule-recording": "r-rec",
    "rule-mini-miranda": "r-mm",
    "rule-identity": "r-verify",
    "rule-payment": "r-disp",
}


def _violation_rule_screen(rule_id: str | None) -> str:
    if not rule_id:
        return "r-rec"
    return _RULE_ID_SCREEN.get(rule_id, rule_id)


def _violation_severity_screen(severity: str | None) -> str:
    if severity in {"critical", "high", "medium", "low"}:
        return severity
    return "medium"


def _speaker_screen(speaker: str | None) -> str:
    if speaker in {"bot", "agent", "customer", "system"}:
        return speaker
    if speaker == "human":
        return "agent"
    return "system"


def _transcript_turn(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "t": int(row["at_sec"] or 0),
        "speaker": _speaker_screen(row["speaker"]),
        "text": row["text"] or "",
    }


def _violation_notes_grouped(conn: Any, violation_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Structured notes from activity_events (note_added / violation_note)."""
    if not violation_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.at, ae.label AS text, u.name AS author
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                WHERE ae.entity_type = 'violation'
                  AND ae.entity_id = ANY(:ids)
                  AND ae.kind IN ('note_added', 'violation_note')
                ORDER BY ae.at
                """
            ),
            {"ids": violation_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append(
            {
                "at": r["at"],
                "author": r["author"] or "System",
                "text": r["text"] or "",
            }
        )
    return grouped


def _transcripts_by_interaction(conn: Any, interaction_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not interaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, interaction_id, turn_index, speaker, at_sec, text
                FROM interaction_transcript
                WHERE interaction_id = ANY(:ids)
                ORDER BY interaction_id, turn_index
                """
            ),
            {"ids": interaction_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["interaction_id"], []).append(r)
    return grouped


def _build_violation_evidence(
    turns: list[dict[str, Any]],
    at_sec: int,
    description: str | None,
) -> dict[str, Any]:
    """Offending turn + neighbours. Falls back to snippet-only when no transcript."""
    snippet = (description or "").strip() or "No transcript evidence available."
    if not turns:
        return {
            "snippet": snippet,
            "preceding": None,
            "offending": {
                "id": "synthetic-offending",
                "t": at_sec,
                "speaker": "system",
                "text": snippet,
            },
            "following": None,
        }

    # Prefer the turn closest to at_sec; tie-break toward agent/bot speech.
    best_idx = 0
    best_dist = abs(int(turns[0]["at_sec"] or 0) - at_sec)
    for i, t in enumerate(turns):
        dist = abs(int(t["at_sec"] or 0) - at_sec)
        speaker = _speaker_screen(t["speaker"])
        better = dist < best_dist or (
            dist == best_dist and speaker in {"bot", "agent"} and _speaker_screen(turns[best_idx]["speaker"]) not in {"bot", "agent"}
        )
        if better:
            best_idx = i
            best_dist = dist

    offending = _transcript_turn(turns[best_idx])
    if not snippet or snippet == "No transcript evidence available.":
        snippet = offending["text"]
    preceding = _transcript_turn(turns[best_idx - 1]) if best_idx > 0 else None
    following = _transcript_turn(turns[best_idx + 1]) if best_idx + 1 < len(turns) else None
    return {
        "snippet": snippet,
        "preceding": preceding,
        "offending": offending,
        "following": following,
    }


def _violation_rows_to_screen(
    conn: Any,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ids = [r["id"] for r in rows]
    interaction_ids = [r["interaction_id"] for r in rows if r.get("interaction_id")]
    notes = _violation_notes_grouped(conn, ids)
    transcripts = _transcripts_by_interaction(conn, interaction_ids)
    result: list[dict[str, Any]] = []
    for r in rows:
        at_sec = int(r["at_sec"] or 0)
        call_id = r["interaction_id"] or ""
        actor_kind = "bot" if r["actor_kind"] == "bot" else "human"
        actor_name = r["actor_bot_name"] if actor_kind == "bot" else r["actor_user_name"]
        if not actor_name:
            actor_name = "Kaia v2.4" if actor_kind == "bot" else "Unknown agent"
        evidence = _build_violation_evidence(
            transcripts.get(call_id) or [],
            at_sec,
            r.get("description"),
        )
        result.append(
            {
                "id": r["id"],
                "callId": call_id,
                "customerName": r["customer_name"],
                "ruleId": _violation_rule_screen(r["rule_id"]),
                "severity": _violation_severity_screen(r["rule_severity"]),
                "occurredAt": r["occurred_at"] or r["created_at"],
                "atSec": at_sec,
                "actor": {"kind": actor_kind, "name": actor_name},
                "evidence": evidence,
                "status": _violation_status_screen(r["status"]),
                "assignee": r["assignee"] or None,
                "notes": notes.get(r["id"]) or [],
            }
        )
    return result


_VIOLATION_LIST_SQL = """
    SELECT v.id, v.interaction_id, v.customer_id, c.name AS customer_name,
           v.rule_id, cr.severity AS rule_severity, v.actor_kind,
           v.status, v.description, v.at_sec, v.created_at,
           COALESCE(i.started_at, v.created_at) AS occurred_at,
           u.name AS assignee,
           au.name AS actor_user_name,
           b.name AS actor_bot_name
    FROM violations v
    JOIN customers c ON c.id = v.customer_id
    JOIN compliance_rules cr ON cr.id = v.rule_id
    LEFT JOIN users u ON u.id = v.assignee_user_id
    LEFT JOIN users au ON au.id = v.actor_user_id
    LEFT JOIN bots b ON b.id = v.actor_bot_id
    LEFT JOIN interactions i ON i.id = v.interaction_id
"""


def list_violations() -> list[dict[str, Any]]:
    """Compliance Risk feed — screen Violation shape."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _VIOLATION_LIST_SQL
                    + """
                    ORDER BY
                      CASE cr.severity
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'medium' THEN 2
                        ELSE 1
                      END DESC,
                      COALESCE(i.started_at, v.created_at) DESC
                    """
                )
            )
        )
        return _violation_rows_to_screen(conn, rows)


def _violation_by_id(conn: Any, violation_id: str) -> dict[str, Any]:
    row = _one(
        conn.execute(
            text(_VIOLATION_LIST_SQL + " WHERE v.id = :id"),
            {"id": violation_id},
        )
    )
    if row is None:
        raise KeyError("violation_not_found")
    items = _violation_rows_to_screen(conn, [row])
    return items[0]


def patch_violation(violation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is intentional,
    so an explicit None clears assignee. Notes are NOT written here —
    use add_violation_note → activity_events."""
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id FROM violations WHERE id = :id"), {"id": violation_id}))
        if row is None:
            raise KeyError("violation_not_found")

        if "status" in payload and payload["status"] is not None:
            status = payload["status"]
            if status not in {"open", "in_review", "acknowledged", "resolved"}:
                raise ValueError(f"invalid_status: {status}")

        if "assigneeUserId" in payload and payload["assigneeUserId"] is not None:
            assignee = payload["assigneeUserId"]
            if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": assignee}).fetchone():
                raise KeyError(f"user_not_found: {assignee}")

        updates: list[str] = []
        params: dict[str, Any] = {"id": violation_id}
        if "status" in payload:
            updates.append("status = :status")
            params["status"] = payload["status"]
        if "assigneeUserId" in payload:
            updates.append("assignee_user_id = :assignee_user_id")
            params["assignee_user_id"] = payload["assigneeUserId"]
        if updates:
            updates.append("updated_at = now()")
            conn.execute(text(f"UPDATE violations SET {', '.join(updates)} WHERE id = :id"), params)

        status = payload.get("status")
        if "assigneeUserId" in payload and payload["assigneeUserId"] is None:
            label, note = "Violation unassigned", None
        elif payload.get("assigneeUserId"):
            label = "Violation assigned"
            note = _user_name(conn, payload["assigneeUserId"])
        elif status == "acknowledged":
            label, note = "Violation acknowledged", status
        elif status == "resolved":
            label, note = "Violation resolved", status
        elif status == "in_review":
            label, note = "Violation in review", status
        elif status:
            label, note = "Violation updated", status
        else:
            label, note = "Violation updated", None
        _activity(conn, "violation", violation_id, "violation_updated", label, note, row["customer_id"])
        return _violation_by_id(conn, violation_id)


def add_violation_note(violation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Free-text note on a violation. activity_events is the notes store."""
    with engine.begin() as conn:
        row = _one(conn.execute(text("SELECT customer_id FROM violations WHERE id = :id"), {"id": violation_id}))
        if row is None:
            raise KeyError("violation_not_found")
        text_value = (payload.get("text") or "").strip()
        if not text_value:
            raise ValueError("note text is required")
        _activity(conn, "violation", violation_id, "note_added", text_value, None, row["customer_id"])
        return {"id": violation_id, "text": text_value}


# ---------------------------------------------------------------------------
# Bot Analytics — live aggregates from interactions (+ children).
# Do NOT read intent_aggregates / analytics_daily / escalation_reasons stubs.
# ---------------------------------------------------------------------------

_BOT_ANALYTICS_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}

_BOT_ANALYTICS_CHANNELS = frozenset({"voice", "whatsapp", "sms"})

_HANDOFF_REASON_LABELS = {
    "sentiment_drop": "Sentiment drop (negative)",
    "verification_failed": "Verification failed",
    "compliance": "Compliance flag",
    "customer_requested": "User asked for human",
    "hardship": "Hardship / sensitive",
    "dispute": "Sensitive topic (dispute/legal)",
    "high_value": "High-value account",
    "routing_rule": "Routing rule / queue",
}

_INTENT_LABELS = {
    "balance": "Balance / Dues query",
    "emi": "EMI schedule",
    "payment-confirm": "Payment confirmation",
    "statement": "Statement request",
    "late-fee": "Late fee / waiver",
    "dispute": "Dispute raise",
    "callback": "Callback / reschedule",
    "topup": "Top-up / upsell interest",
    "dnd": "DND / opt-out",
    "language": "Language switch",
    "escalate-human": "Ask for human",
    "other": "Other / unrecognised",
    "upi": "UPI payment",
    "PTP": "Promise to pay",
    "QA-review": "QA review",
    "empathy-coach": "Empathy coach",
}

_TURN_BUCKETS: list[tuple[str, int, int]] = [
    ("1–2", 1, 2),
    ("3–4", 3, 4),
    ("5–7", 5, 7),
    ("8–12", 8, 12),
    ("13+", 13, 99),
]

# Abandoned = explicit status or contact-failure dispositions (seed has no status='abandoned').
_ABANDONED_PRED = """(
  i.status = 'abandoned'
  OR lower(coalesce(i.disposition, '')) ~ '(no answer|voicemail|dnd|abandon|not contacted)'
)"""

_RESOLVED_DISP_PRED = """(
  lower(coalesce(i.disposition, '')) ~ '(resolved|payment made|ptp)'
)"""


def _bot_analytics_window(range_key: str, channel: str) -> tuple[int, str, dict[str, Any]]:
    days = _BOT_ANALYTICS_RANGE_DAYS.get(range_key, 30)
    params: dict[str, Any] = {"days": days}
    clauses = ["i.started_at >= (now() - make_interval(days => :days))"]
    if channel and channel != "all":
        if channel not in _BOT_ANALYTICS_CHANNELS:
            raise ValueError(f"invalid_channel: {channel}")
        clauses.append("i.channel = :channel")
        params["channel"] = channel
    return days, " AND ".join(clauses), params


def _intent_label(intent_id: str) -> str:
    if intent_id in _INTENT_LABELS:
        return _INTENT_LABELS[intent_id]
    return intent_id.replace("-", " ").replace("_", " ").strip().title() or "Other / unrecognised"


def _suggested_fix_screen(raw: str | None) -> str:
    v = (raw or "kb").strip().lower()
    if v in {"prompt"}:
        return "prompt"
    if v in {"both"}:
        return "both"
    # faq / kb / doc / anything else → kb work
    return "kb"


def _trend_delta(current: int, prior: int) -> float:
    if prior <= 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - prior) / prior) * 100.0, 1)


def bot_analytics(range_key: str = "30d", channel: str = "all") -> dict[str, Any]:
    """Conversation & Bot Analytics — screen shape, aggregated live from interactions."""
    if range_key not in _BOT_ANALYTICS_RANGE_DAYS:
        raise ValueError(f"invalid_range: {range_key}")
    days, where_sql, params = _bot_analytics_window(range_key, channel)

    with engine.connect() as conn:
        daily_rows = _rows(
            conn.execute(
                text(
                    f"""
                    WITH base AS (
                      SELECT
                        i.id,
                        (i.started_at AT TIME ZONE 'UTC')::date AS d,
                        i.handler_kind,
                        i.query_resolved,
                        i.latency_ms,
                        i.avg_sentiment,
                        EXISTS (
                          SELECT 1 FROM interaction_handoffs h WHERE h.interaction_id = i.id
                        ) AS escalated,
                        {_ABANDONED_PRED} AS abandoned,
                        (
                          SELECT count(*)::int
                          FROM interaction_transcript t
                          WHERE t.interaction_id = i.id
                        ) AS turns
                      FROM interactions i
                      WHERE {where_sql}
                    )
                    SELECT
                      to_char(d, 'YYYY-MM-DD') AS date,
                      count(*)::int AS sessions,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND query_resolved
                      )::int AS contained,
                      count(*) FILTER (WHERE escalated)::int AS escalated,
                      count(*) FILTER (WHERE abandoned)::int AS abandoned,
                      coalesce(avg(turns), 0)::float AS avg_turns,
                      coalesce(
                        percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms),
                        0
                      )::float AS latency_p50,
                      coalesce(
                        percentile_cont(0.9) WITHIN GROUP (ORDER BY latency_ms),
                        0
                      )::float AS latency_p90,
                      coalesce(
                        percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms),
                        0
                      )::float AS latency_p99,
                      coalesce(avg(avg_sentiment), 0)::float AS sentiment
                    FROM base
                    GROUP BY d
                    ORDER BY d
                    """
                ),
                params,
            )
        )

        intent_rows = _rows(
            conn.execute(
                text(
                    f"""
                    WITH base AS (
                      SELECT
                        i.id,
                        coalesce(nullif(trim(i.primary_intent), ''), 'other') AS intent_id,
                        i.handler_kind,
                        i.query_resolved,
                        i.latency_ms,
                        i.sentiment_label,
                        EXISTS (
                          SELECT 1 FROM interaction_handoffs h WHERE h.interaction_id = i.id
                        ) AS escalated,
                        {_ABANDONED_PRED} AS abandoned,
                        (
                          SELECT count(*)::int
                          FROM interaction_transcript t
                          WHERE t.interaction_id = i.id
                        ) AS turns
                      FROM interactions i
                      WHERE {where_sql}
                    )
                    SELECT
                      intent_id,
                      count(*)::int AS sessions,
                      count(*) FILTER (
                        WHERE handler_kind = 'bot' AND query_resolved
                      )::int AS contained,
                      count(*) FILTER (WHERE escalated)::int AS escalated,
                      count(*) FILTER (WHERE abandoned)::int AS abandoned,
                      coalesce(avg(turns), 0)::float AS avg_turns,
                      coalesce(avg(latency_ms), 0)::float AS avg_latency_ms,
                      count(*) FILTER (WHERE sentiment_label = 'positive')::int AS positive,
                      count(*) FILTER (
                        WHERE sentiment_label = 'neutral' OR sentiment_label IS NULL
                      )::int AS neutral,
                      count(*) FILTER (WHERE sentiment_label = 'negative')::int AS negative
                    FROM base
                    GROUP BY intent_id
                    ORDER BY sessions DESC, intent_id
                    """
                ),
                params,
            )
        )

        esc_current = {
            r["reason"]: int(r["count"])
            for r in _rows(
                conn.execute(
                    text(
                        f"""
                        SELECT h.reason, count(*)::int AS count
                        FROM interaction_handoffs h
                        JOIN interactions i ON i.id = h.interaction_id
                        WHERE {where_sql}
                        GROUP BY h.reason
                        """
                    ),
                    params,
                )
            )
        }
        prior_params = {**params, "prior_days": days * 2}
        esc_prior = {
            r["reason"]: int(r["count"])
            for r in _rows(
                conn.execute(
                    text(
                        f"""
                        SELECT h.reason, count(*)::int AS count
                        FROM interaction_handoffs h
                        JOIN interactions i ON i.id = h.interaction_id
                        WHERE i.started_at >= (now() - make_interval(days => :prior_days))
                          AND i.started_at < (now() - make_interval(days => :days))
                          {"AND i.channel = :channel" if "channel" in params else ""}
                        GROUP BY h.reason
                        """
                    ),
                    prior_params,
                )
            )
        }

        unanswered_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      uq.id,
                      uq.question,
                      uq.hit_count,
                      uq.last_seen_at,
                      coalesce(uq.top_intent, 'other') AS top_intent,
                      uq.suggested_fix_type,
                      EXISTS (
                        SELECT 1
                        FROM analytics_kb_gap_links g
                        WHERE g.unanswered_question_id = uq.id
                          AND g.kb_document_id IS NOT NULL
                      ) AS has_kb_doc
                    FROM unanswered_questions uq
                    WHERE uq.tenant_id = :tenant_id
                    ORDER BY uq.hit_count DESC, uq.id
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        )

        turn_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      (
                        SELECT count(*)::int
                        FROM interaction_transcript t
                        WHERE t.interaction_id = i.id
                      ) AS turns
                    FROM interactions i
                    WHERE {where_sql}
                    """
                ),
                params,
            )
        )

        # Funnel stages are cumulative subsets (landed ⊇ verified ⊇ intent ⊇
        # answered ⊇ confirmed), so counts decrease monotonically. Each stage
        # ANDs all prior predicates; "answered" is the union of the two resolve
        # signals so "confirmed" (disposition-resolved) is always a subset of it.
        _v_pred = (
            "EXISTS (SELECT 1 FROM identity_verifications v "
            "WHERE v.interaction_id = i.id AND v.status = 'verified')"
        )
        _intent_pred = "i.primary_intent IS NOT NULL AND trim(i.primary_intent) <> ''"
        _answered_pred = f"(i.query_resolved OR {_RESOLVED_DISP_PRED})"
        funnel = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*)::int AS landed,
                      count(*) FILTER (WHERE {_v_pred})::int AS verified,
                      count(*) FILTER (
                        WHERE {_v_pred} AND {_intent_pred}
                      )::int AS intent_captured,
                      count(*) FILTER (
                        WHERE {_v_pred} AND {_intent_pred} AND {_answered_pred}
                      )::int AS answered,
                      count(*) FILTER (
                        WHERE {_v_pred} AND {_intent_pred} AND {_answered_pred}
                          AND {_RESOLVED_DISP_PRED}
                      )::int AS confirmed
                    FROM interactions i
                    WHERE {where_sql}
                    """
                ),
                params,
            )
        ) or {}

    daily_series = [
        {
            "date": r["date"],
            "sessions": int(r["sessions"] or 0),
            "contained": int(r["contained"] or 0),
            "escalated": int(r["escalated"] or 0),
            "abandoned": int(r["abandoned"] or 0),
            "avgTurns": round(float(r["avg_turns"] or 0), 2),
            "latencyP50": round(float(r["latency_p50"] or 0), 1),
            "latencyP90": round(float(r["latency_p90"] or 0), 1),
            "latencyP99": round(float(r["latency_p99"] or 0), 1),
            "sentiment": round(float(r["sentiment"] or 0), 3),
        }
        for r in daily_rows
    ]

    intent_aggs = [
        {
            "id": r["intent_id"],
            "label": _intent_label(r["intent_id"]),
            "sessions": int(r["sessions"] or 0),
            "contained": int(r["contained"] or 0),
            "escalated": int(r["escalated"] or 0),
            "abandoned": int(r["abandoned"] or 0),
            "avgTurns": round(float(r["avg_turns"] or 0), 2),
            "avgLatencyMs": round(float(r["avg_latency_ms"] or 0), 1),
            "sentiment": {
                "positive": int(r["positive"] or 0),
                "neutral": int(r["neutral"] or 0),
                "negative": int(r["negative"] or 0),
            },
        }
        for r in intent_rows
    ]

    reasons = sorted(set(esc_current) | set(esc_prior), key=lambda k: (-esc_current.get(k, 0), k))
    escalation_reasons = [
        {
            "id": reason,
            "label": _HANDOFF_REASON_LABELS.get(reason, reason.replace("_", " ").title()),
            "count": esc_current.get(reason, 0),
            "trendDelta": _trend_delta(esc_current.get(reason, 0), esc_prior.get(reason, 0)),
        }
        for reason in reasons
        if esc_current.get(reason, 0) > 0 or esc_prior.get(reason, 0) > 0
    ]
    # Prefer current-period reasons first; drop pure-prior zeros already filtered.
    escalation_reasons = [r for r in escalation_reasons if r["count"] > 0]

    unanswered = []
    for r in unanswered_rows:
        last = r["last_seen_at"]
        if hasattr(last, "date"):
            last_seen = last.date().isoformat()
        elif last:
            last_seen = str(last)[:10]
        else:
            last_seen = ""
        unanswered.append(
            {
                "id": r["id"],
                "text": r["question"],
                "hits": int(r["hit_count"] or 0),
                "lastSeen": last_seen,
                "topIntent": r["top_intent"] or "other",
                "hasKbDoc": bool(r["has_kb_doc"]),
                "suggestedFix": _suggested_fix_screen(r["suggested_fix_type"]),
            }
        )

    bucket_counts = {label: 0 for label, _mn, _mx in _TURN_BUCKETS}
    for r in turn_rows:
        turns = int(r["turns"] or 0)
        if turns <= 0:
            continue
        for label, mn, mx in _TURN_BUCKETS:
            if mn <= turns <= mx:
                bucket_counts[label] += 1
                break
    turns_histogram = [
        {"label": label, "min": mn, "max": mx, "count": bucket_counts[label]}
        for label, mn, mx in _TURN_BUCKETS
    ]

    funnel_stages = [
        {"id": "landed", "label": "Session landed", "count": int(funnel.get("landed") or 0)},
        {"id": "verified", "label": "Verified identity", "count": int(funnel.get("verified") or 0)},
        {"id": "intent", "label": "Intent captured", "count": int(funnel.get("intent_captured") or 0)},
        {"id": "answered", "label": "Answer delivered", "count": int(funnel.get("answered") or 0)},
        {"id": "confirmed", "label": "Confirmed resolution", "count": int(funnel.get("confirmed") or 0)},
    ]

    return {
        "dailySeries": daily_series,
        "intentAggs": intent_aggs,
        "escalationReasons": escalation_reasons,
        "unansweredQuestions": unanswered,
        "turnsHistogram": turns_histogram,
        "funnelStages": funnel_stages,
    }


# ---------------------------------------------------------------------------
# QA Scorecards — rubric-driven scoring queue (scorecard core MVP).
# Coaching / calibration stay seed-backed until their endpoints land.
# ---------------------------------------------------------------------------

_QA_DEFAULT_RUBRIC_ID = "rubric-v1"
_QA_STATUSES = frozenset({"unscored", "ai_draft", "final"})


def _qa_status_screen(status: str | None) -> str:
    raw = (status or "").strip().lower()
    if raw in {"final", "completed", "reviewed"}:
        return "final"
    if raw in {"ai_draft", "draft", "in_review"}:
        return "ai_draft"
    return "unscored"


def _qa_band_for(total: float) -> str:
    if total >= 85:
        return "green"
    if total >= 70:
        return "amber"
    return "red"


def _qa_score_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _load_rubric_tree(conn: Any, rubric_id: str = _QA_DEFAULT_RUBRIC_ID) -> dict[str, Any] | None:
    rubric = _one(
        conn.execute(
            text("SELECT id, name, version FROM qa_rubrics WHERE id = :id AND enabled = true"),
            {"id": rubric_id},
        )
    )
    if rubric is None:
        rubric = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name, version
                    FROM qa_rubrics
                    WHERE enabled = true
                    ORDER BY updated_at DESC, id
                    LIMIT 1
                    """
                )
            )
        )
    if rubric is None:
        return None
    sections = _rows(
        conn.execute(
            text(
                """
                SELECT id, name AS label, weight
                FROM qa_rubric_sections
                WHERE rubric_id = :rubric_id
                ORDER BY weight DESC, id
                """
            ),
            {"rubric_id": rubric["id"]},
        )
    )
    section_ids = [s["id"] for s in sections]
    criteria_by_section: dict[str, list[dict[str, Any]]] = {sid: [] for sid in section_ids}
    if section_ids:
        criteria = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, section_id, label, coalesce(description, '') AS description,
                           weight, critical_fail
                    FROM qa_rubric_criteria
                    WHERE section_id = ANY(:ids)
                    ORDER BY weight DESC, id
                    """
                ),
                {"ids": section_ids},
            )
        )
        for c in criteria:
            criteria_by_section.setdefault(c["section_id"], []).append(
                {
                    "id": c["id"],
                    "label": c["label"],
                    "description": c["description"] or "",
                    "weight": _qa_score_float(c["weight"]),
                    "critical": bool(c["critical_fail"]) or None,
                }
            )
    return {
        "id": rubric["id"],
        "name": rubric["name"],
        "version": rubric["version"],
        "sections": [
            {
                "id": s["id"],
                "label": s["label"],
                "weight": _qa_score_float(s["weight"]),
                "criteria": [
                    {k: v for k, v in crit.items() if not (k == "critical" and v is None)}
                    for crit in criteria_by_section.get(s["id"], [])
                ],
            }
            for s in sections
        ],
    }


def get_rubric(rubric_id: str | None = None) -> dict[str, Any]:
    with engine.connect() as conn:
        tree = _load_rubric_tree(conn, rubric_id or _QA_DEFAULT_RUBRIC_ID)
        if tree is None:
            raise KeyError("rubric_not_found")
        return tree


def _qa_all_criteria(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for s in rubric["sections"] for c in s["criteria"]]


def _qa_section_total(section: dict[str, Any], entries_by_id: dict[str, dict[str, Any]]) -> float:
    weight_sum = sum(_qa_score_float(c["weight"]) for c in section["criteria"]) or 1.0
    acc = 0.0
    for c in section["criteria"]:
        entry = entries_by_id.get(c["id"]) or {}
        score = _qa_score_float(entry.get("score"))
        acc += (score / 5.0) * (_qa_score_float(c["weight"]) / weight_sum)
    return acc * 100.0


def _qa_compute_total(rubric: dict[str, Any], entries: list[dict[str, Any]]) -> float:
    by_id = {e["criterionId"]: e for e in entries}
    has_critical_zero = any(
        c.get("critical") and _qa_score_float((by_id.get(c["id"]) or {}).get("score")) == 0
        for s in rubric["sections"]
        for c in s["criteria"]
    )
    weight_sum = sum(_qa_score_float(s["weight"]) for s in rubric["sections"]) or 1.0
    total = sum(
        (_qa_section_total(s, by_id) * _qa_score_float(s["weight"])) / weight_sum
        for s in rubric["sections"]
    )
    return min(total, 40.0) if has_critical_zero else total


def _qa_entries_grouped(conn: Any, scorecard_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not scorecard_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT scorecard_id, criterion_id, ai_suggested_score, final_score, note, accepted
                FROM qa_scorecard_entries
                WHERE scorecard_id = ANY(:ids)
                ORDER BY criterion_id
                """
            ),
            {"ids": scorecard_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["scorecard_id"], []).append(
            {
                "criterionId": r["criterion_id"],
                "aiSuggested": _qa_score_float(r["ai_suggested_score"]),
                "score": _qa_score_float(r["final_score"]),
                "note": r["note"] or None,
                "accepted": r["accepted"],
            }
        )
    return grouped


def _qa_pad_entries(rubric: dict[str, Any], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {e["criterionId"]: e for e in entries}
    padded: list[dict[str, Any]] = []
    for c in _qa_all_criteria(rubric):
        existing = by_id.get(c["id"])
        if existing:
            padded.append(
                {
                    "criterionId": existing["criterionId"],
                    "aiSuggested": _qa_score_float(existing.get("aiSuggested")),
                    "score": _qa_score_float(existing.get("score")),
                    "note": existing.get("note") or None,
                    "accepted": existing.get("accepted"),
                }
            )
        else:
            padded.append(
                {
                    "criterionId": c["id"],
                    "aiSuggested": 0.0,
                    "score": 0.0,
                    "note": None,
                    "accepted": None,
                }
            )
    return padded


def _qa_handled_by(handler_kind: str | None, handler_name: str | None, has_handoff: bool) -> dict[str, str]:
    label = handler_name or ("Bot" if handler_kind == "bot" else "Agent")
    if has_handoff:
        return {"kind": "handoff", "label": label}
    kind = "bot" if handler_kind == "bot" else "human"
    return {"kind": kind, "label": label}


def _qa_ensure_user(conn: Any, user_id: str | None) -> None:
    if user_id is None:
        return
    if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": user_id}).fetchone():
        raise KeyError("user_not_found")


def _qa_ensure_bot(conn: Any, bot_id: str | None) -> None:
    if bot_id is None:
        return
    if not conn.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": bot_id}).fetchone():
        raise KeyError("bot_not_found")


def _qa_ensure_criterion(conn: Any, criterion_id: str) -> None:
    if not conn.execute(text("SELECT 1 FROM qa_rubric_criteria WHERE id = :id"), {"id": criterion_id}).fetchone():
        raise KeyError(f"criterion_not_found:{criterion_id}")


def _qa_upsert_entries(conn: Any, scorecard_id: str, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert per-criterion rows; returns the screen-shaped entries written."""
    written: list[dict[str, Any]] = []
    for raw in entries:
        criterion_id = raw.get("criterionId")
        if not criterion_id:
            raise ValueError("entries require criterionId")
        _qa_ensure_criterion(conn, criterion_id)
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id, ai_suggested_score, final_score, note, accepted
                    FROM qa_scorecard_entries
                    WHERE scorecard_id = :scorecard_id AND criterion_id = :criterion_id
                    """
                ),
                {"scorecard_id": scorecard_id, "criterion_id": criterion_id},
            )
        )
        ai = raw["aiSuggested"] if "aiSuggested" in raw and raw["aiSuggested"] is not None else (
            _qa_score_float(existing["ai_suggested_score"]) if existing else 0.0
        )
        score = raw["score"] if "score" in raw and raw["score"] is not None else (
            _qa_score_float(existing["final_score"]) if existing else 0.0
        )
        note = raw["note"] if "note" in raw else (existing["note"] if existing else None)
        accepted = raw["accepted"] if "accepted" in raw else (existing["accepted"] if existing else None)
        entry_id = existing["id"] if existing else f"{scorecard_id}-{criterion_id}"
        conn.execute(
            text(
                """
                INSERT INTO qa_scorecard_entries
                  (id, scorecard_id, criterion_id, ai_suggested_score, final_score, note, accepted)
                VALUES
                  (:id, :scorecard_id, :criterion_id, :ai, :score, :note, :accepted)
                ON CONFLICT (id) DO UPDATE
                  SET ai_suggested_score = EXCLUDED.ai_suggested_score,
                      final_score = EXCLUDED.final_score,
                      note = EXCLUDED.note,
                      accepted = EXCLUDED.accepted,
                      updated_at = now()
                """
            ),
            {
                "id": entry_id,
                "scorecard_id": scorecard_id,
                "criterion_id": criterion_id,
                "ai": ai,
                "score": score,
                "note": note,
                "accepted": accepted,
            },
        )
        written.append(
            {
                "criterionId": criterion_id,
                "aiSuggested": _qa_score_float(ai),
                "score": _qa_score_float(score),
                "note": note,
                "accepted": accepted,
            }
        )
    return written


_SCORECARD_LIST_SQL = """
    SELECT qs.id, qs.interaction_id, qs.rubric_id, qs.status, qs.total_score, qs.band,
           qs.scored_at, qs.created_at,
           qs.subject_user_id, qs.subject_bot_id, qs.reviewer_user_id,
           c.name AS customer_name,
           coalesce(i.disposition, '') AS disposition,
           i.handler_kind,
           coalesce(hu.name, hb.name) AS handler_name,
           su.name AS subject_user_name,
           sb.name AS subject_bot_name,
           ru.name AS reviewer_name,
           EXISTS (
             SELECT 1 FROM interaction_handoffs h WHERE h.interaction_id = qs.interaction_id
           ) AS has_handoff
    FROM qa_scorecards qs
    JOIN interactions i ON i.id = qs.interaction_id
    JOIN customers c ON c.id = i.customer_id
    LEFT JOIN users hu ON hu.id = i.handler_user_id
    LEFT JOIN bots hb ON hb.id = i.handler_bot_id
    LEFT JOIN users su ON su.id = qs.subject_user_id
    LEFT JOIN bots sb ON sb.id = qs.subject_bot_id
    LEFT JOIN users ru ON ru.id = qs.reviewer_user_id
"""


def _scorecard_rows_to_screen(
    conn: Any,
    rows: list[dict[str, Any]],
    rubric: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []
    rubric = rubric or _load_rubric_tree(conn, rows[0].get("rubric_id") or _QA_DEFAULT_RUBRIC_ID)
    if rubric is None:
        raise KeyError("rubric_not_found")
    entries_by = _qa_entries_grouped(conn, [r["id"] for r in rows])
    result: list[dict[str, Any]] = []
    for r in rows:
        agent_id = r["subject_user_name"] or r["subject_bot_name"] or r["handler_name"] or "Unknown"
        entries = _qa_pad_entries(rubric, entries_by.get(r["id"]) or [])
        result.append(
            {
                "id": r["id"],
                "callId": r["interaction_id"],
                "customerName": r["customer_name"],
                "disposition": r["disposition"] or "",
                "handledBy": _qa_handled_by(r["handler_kind"], r["handler_name"], bool(r["has_handoff"])),
                "agentId": agent_id,
                "reviewer": r["reviewer_name"] or None,
                "status": _qa_status_screen(r["status"]),
                "entries": entries,
                "scoredAt": r["scored_at"],
                "createdAt": r["created_at"],
            }
        )
    return result


def list_scorecards() -> list[dict[str, Any]]:
    """QA Scoring Queue — screen Scorecard shape."""
    with engine.connect() as conn:
        rubric = _load_rubric_tree(conn)
        rows = _rows(
            conn.execute(
                text(
                    _SCORECARD_LIST_SQL
                    + """
                    ORDER BY
                      CASE qs.status
                        WHEN 'unscored' THEN 0
                        WHEN 'ai_draft' THEN 1
                        WHEN 'draft' THEN 1
                        WHEN 'final' THEN 2
                        ELSE 3
                      END,
                      i.started_at DESC NULLS LAST,
                      qs.created_at DESC
                    """
                )
            )
        )
        return _scorecard_rows_to_screen(conn, rows, rubric)


def _scorecard_by_id(conn: Any, scorecard_id: str) -> dict[str, Any]:
    row = _one(
        conn.execute(
            text(_SCORECARD_LIST_SQL + " WHERE qs.id = :id"),
            {"id": scorecard_id},
        )
    )
    if row is None:
        raise KeyError("scorecard_not_found")
    return _scorecard_rows_to_screen(conn, [row])[0]


def create_scorecard(payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        interaction = _ensure_interaction(conn, payload["interactionId"])
        rubric_id = payload.get("rubricId") or _QA_DEFAULT_RUBRIC_ID
        rubric = _load_rubric_tree(conn, rubric_id)
        if rubric is None:
            raise KeyError("rubric_not_found")
        subject_user_id = payload.get("subjectUserId")
        subject_bot_id = payload.get("subjectBotId")
        if subject_user_id and subject_bot_id:
            raise ValueError("set subjectUserId or subjectBotId, not both")
        _qa_ensure_user(conn, subject_user_id)
        _qa_ensure_bot(conn, subject_bot_id)
        reviewer_user_id = payload.get("reviewerUserId")
        _qa_ensure_user(conn, reviewer_user_id)
        status = _qa_status_screen(payload.get("status") or "unscored")
        if status not in _QA_STATUSES:
            raise ValueError(f"invalid status: {status}")
        scorecard_id = f"qa-{interaction['id']}"
        if conn.execute(text("SELECT 1 FROM qa_scorecards WHERE id = :id"), {"id": scorecard_id}).fetchone():
            scorecard_id = _id("QA")
        entries_payload = payload.get("entries") or []
        total = payload.get("totalScore")
        band = payload.get("band")
        conn.execute(
            text(
                """
                INSERT INTO qa_scorecards
                  (id, interaction_id, rubric_id, subject_user_id, subject_bot_id, reviewer_user_id,
                   status, total_score, band, scored_at)
                VALUES
                  (:id, :interaction_id, :rubric_id, :subject_user_id, :subject_bot_id, :reviewer_user_id,
                   :status, :total_score, :band, :scored_at)
                """
            ),
            {
                "id": scorecard_id,
                "interaction_id": payload["interactionId"],
                "rubric_id": rubric["id"],
                "subject_user_id": subject_user_id,
                "subject_bot_id": subject_bot_id,
                "reviewer_user_id": reviewer_user_id or (_actor_user_id() if status == "final" else None),
                "status": status,
                "total_score": total,
                "band": band,
                "scored_at": datetime.now(timezone.utc) if status == "final" else None,
            },
        )
        if entries_payload:
            written = _qa_upsert_entries(conn, scorecard_id, entries_payload)
            total = _qa_compute_total(rubric, written)
            band = _qa_band_for(total)
            conn.execute(
                text(
                    """
                    UPDATE qa_scorecards
                    SET total_score = :total, band = :band
                    WHERE id = :id
                    """
                ),
                {"id": scorecard_id, "total": total, "band": band},
            )
        _activity(
            conn,
            "qa_scorecard",
            scorecard_id,
            "scorecard_created",
            "QA scorecard created",
            customer_id=interaction["customer_id"],
        )
        return _scorecard_by_id(conn, scorecard_id)


def patch_scorecard(scorecard_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is intentional.

    entries[] upserts qa_scorecard_entries and recomputes total_score/band.
    status=final sets scored_at + reviewer and writes a finalize activity row.
    """
    with engine.begin() as conn:
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT qs.id, qs.rubric_id, qs.status, qs.reviewer_user_id, i.customer_id
                    FROM qa_scorecards qs
                    JOIN interactions i ON i.id = qs.interaction_id
                    WHERE qs.id = :id
                    """
                ),
                {"id": scorecard_id},
            )
        )
        if existing is None:
            raise KeyError("scorecard_not_found")
        rubric = _load_rubric_tree(conn, existing["rubric_id"] or _QA_DEFAULT_RUBRIC_ID)
        if rubric is None:
            raise KeyError("rubric_not_found")

        if "subjectUserId" in payload and "subjectBotId" in payload:
            if payload["subjectUserId"] and payload["subjectBotId"]:
                raise ValueError("set subjectUserId or subjectBotId, not both")
        if "subjectUserId" in payload:
            _qa_ensure_user(conn, payload["subjectUserId"])
        if "subjectBotId" in payload:
            _qa_ensure_bot(conn, payload["subjectBotId"])
        if "reviewerUserId" in payload:
            _qa_ensure_user(conn, payload["reviewerUserId"])

        status = _qa_status_screen(existing["status"])
        if "status" in payload and payload["status"] is not None:
            status = _qa_status_screen(payload["status"])
            if status not in _QA_STATUSES:
                raise ValueError(f"invalid status: {status}")
        elif "entries" in payload and payload["entries"] is not None and status == "unscored":
            # Saving criterion edits from unscored promotes to AI draft.
            status = "ai_draft"

        entries_written: list[dict[str, Any]] | None = None
        if "entries" in payload and payload["entries"] is not None:
            entries_written = _qa_upsert_entries(conn, scorecard_id, payload["entries"])

        updates: list[str] = []
        params: dict[str, Any] = {"id": scorecard_id}

        if status != _qa_status_screen(existing["status"]) or ("status" in payload and payload["status"] is not None):
            updates.append("status = :status")
            params["status"] = status

        if "subjectUserId" in payload:
            updates.append("subject_user_id = :subject_user_id")
            params["subject_user_id"] = payload["subjectUserId"]
            if payload["subjectUserId"]:
                updates.append("subject_bot_id = NULL")
        if "subjectBotId" in payload:
            updates.append("subject_bot_id = :subject_bot_id")
            params["subject_bot_id"] = payload["subjectBotId"]
            if payload["subjectBotId"]:
                updates.append("subject_user_id = NULL")

        reviewer_user_id = existing["reviewer_user_id"]
        if "reviewerUserId" in payload:
            reviewer_user_id = payload["reviewerUserId"]
            updates.append("reviewer_user_id = :reviewer_user_id")
            params["reviewer_user_id"] = reviewer_user_id

        if entries_written is not None:
            # Merge with any criteria not in this patch so totals stay complete.
            grouped = _qa_entries_grouped(conn, [scorecard_id]).get(scorecard_id) or []
            padded = _qa_pad_entries(rubric, grouped)
            total = _qa_compute_total(rubric, padded)
            band = _qa_band_for(total) if status != "unscored" else None
            updates.extend(["total_score = :total_score", "band = :band"])
            params["total_score"] = total if status != "unscored" else None
            params["band"] = band
        else:
            if "totalScore" in payload:
                updates.append("total_score = :total_score")
                params["total_score"] = payload["totalScore"]
            if "band" in payload:
                updates.append("band = :band")
                params["band"] = payload["band"]

        if status == "final":
            if "reviewerUserId" not in payload:
                reviewer_user_id = reviewer_user_id or _actor_user_id()
                updates.append("reviewer_user_id = :reviewer_user_id")
                params["reviewer_user_id"] = reviewer_user_id
            updates.append("scored_at = coalesce(scored_at, now())")
        elif "status" in payload and status != "final":
            updates.append("scored_at = NULL")

        if updates:
            conn.execute(text(f"UPDATE qa_scorecards SET {', '.join(updates)} WHERE id = :id"), params)

        if status == "final" and _qa_status_screen(existing["status"]) != "final":
            _activity(
                conn,
                "qa_scorecard",
                scorecard_id,
                "scorecard_finalized",
                "QA scorecard published",
                customer_id=existing["customer_id"],
            )
        else:
            _activity(
                conn,
                "qa_scorecard",
                scorecard_id,
                "scorecard_updated",
                "QA scorecard updated",
                status,
                customer_id=existing["customer_id"],
            )
        return _scorecard_by_id(conn, scorecard_id)


def create_interaction(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = "POST /interactions"
    with engine.begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        interaction_id = _id("CL")
        handler_kind = payload.get("handlerKind") or "human"
        handler_user_id = payload.get("handlerUserId") or (_actor_user_id() if handler_kind == "human" else None)
        handler_bot_id = payload.get("handlerBotId") or ("kaia-v2-4" if handler_kind == "bot" else None)
        conn.execute(
            text(
                """
                INSERT INTO interactions
                  (id, tenant_id, customer_id, account_id, handler_kind, handler_user_id, handler_bot_id,
                   channel, direction, status, disposition, summary, started_at, source_payload)
                VALUES
                  (:id, :tenant_id, :customer_id, :account_id, :handler_kind, :handler_user_id, :handler_bot_id,
                   :channel, :direction, 'completed', :disposition, :summary, now(), '{}'::jsonb)
                """
            ),
            {"id": interaction_id, "tenant_id": TENANT_ID, "customer_id": customer_id, "account_id": payload.get("accountId") or _first_account_id(conn, customer_id), "handler_kind": handler_kind, "handler_user_id": handler_user_id, "handler_bot_id": handler_bot_id, "channel": payload.get("channel") or "voice", "direction": payload.get("direction") or "outbound", "disposition": payload.get("disposition"), "summary": payload.get("summary")},
        )
        for idx, turn in enumerate(payload.get("transcript") or []):
            conn.execute(
                text("INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, at_sec, text) VALUES (:id, :interaction_id, :turn_index, :speaker, :at_sec, :text)"),
                {"id": f"{interaction_id}-turn-{idx}", "interaction_id": interaction_id, "turn_index": idx, "speaker": turn.get("speaker") or "human", "at_sec": turn.get("atSec") or 0, "text": turn.get("text") or ""},
            )
        _activity(conn, "interaction", interaction_id, "interaction_created", "Manual interaction logged", payload.get("summary"), customer_id)
        customer = _one(conn.execute(text("SELECT name, phone_primary FROM customers WHERE id = :id"), {"id": customer_id})) or {}
        response = _dump(
            CallResponse(
                id=interaction_id,
                startedAt=datetime.now(timezone.utc).isoformat(),
                duration=0,
                channel=payload.get("channel") or "voice",
                direction=payload.get("direction") or "outbound",
                handledBy={"kind": handler_kind, "agent" if handler_kind == "human" else "bot": handler_user_id or handler_bot_id or "unknown"},
                customerId=customer_id,
                customerName=customer.get("name") or customer_id,
                accountId=payload.get("accountId") or _first_account_id(conn, customer_id),
                disposition=payload.get("disposition"),
                summary=payload.get("summary"),
                phoneMasked=customer.get("phone_primary") or "",
                transcript=payload.get("transcript") or [],
            )
        )
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response


def wrap_up_interaction(interaction_id: str, payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = f"POST /interactions/{interaction_id}/wrap-up"
    with engine.begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        interaction = _ensure_interaction(conn, interaction_id)
        conn.execute(
            text("UPDATE interactions SET disposition = :disposition, summary = COALESCE(:notes, summary), status = 'completed' WHERE id = :id"),
            {"id": interaction_id, "disposition": payload["disposition"], "notes": payload.get("notes")},
        )
        for flag in payload.get("flags") or []:
            conn.execute(text("INSERT INTO interaction_flags (id, interaction_id, flag, severity) VALUES (:id, :interaction_id, :flag, 'medium')"), {"id": _id("FLAG"), "interaction_id": interaction_id, "flag": flag})
        spawned: dict[str, Any] = {}
        if payload.get("promise"):
            promise_payload = {**payload["promise"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["promise"] = create_promise(promise_payload)
        if payload.get("dispute"):
            dispute_payload = {**payload["dispute"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["dispute"] = create_dispute(dispute_payload)
        if payload.get("callback"):
            callback_payload = {**payload["callback"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["callback"] = create_callback(callback_payload)
        _activity(conn, "interaction", interaction_id, "interaction_wrapped_up", "Interaction wrapped up", payload.get("notes"), interaction["customer_id"])
        response = {"id": interaction_id, "spawned": spawned}
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response


# ---------------------------------------------------------------------------
# Conversation Inbox
# ---------------------------------------------------------------------------

_IST = timezone(timedelta(hours=5, minutes=30))


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
    if channel in {"whatsapp", "sms", "email"}:
        return channel
    return "whatsapp"


def _inbox_delivery(status: str | None, sender: str) -> str | None:
    if sender not in {"bot", "agent"}:
        return None
    if status in {"sent", "delivered", "read"}:
        return status
    if status in {"sending", "failed", "cancelled"}:
        return None
    return "delivered"


def _inbox_contactable(dnd: bool, preferred_window: str | None) -> bool:
    if dnd:
        return False
    # Evaluate against "now" in IST — same window helper as callbacks.
    return not _outside_preferred_window(
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
        "contactableNow": _inbox_contactable(bool(dnd), preferred_window),
        "contactWindow": preferred_window or "10:00-19:00 IST",
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


def _bot_typing_by_conversation(conn: Any, conversation_ids: list[str]) -> dict[str, bool]:
    """True when a bot turn is queued/running or an outbound draft is mid-send."""
    if not conversation_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT conversation_id
                FROM bot_turn_jobs
                WHERE conversation_id = ANY(:ids)
                  AND status IN ('queued', 'running')
                UNION
                SELECT conversation_id
                FROM messages
                WHERE conversation_id = ANY(:ids)
                  AND sender = 'bot'
                  AND delivery_status = 'sending'
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
    typing = bool(bot_typing) and (row.get("status") == "bot") and (row.get("assigned_user_id") is None)
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
        "sla": _inbox_sla(last_customer_at, row["status"]),
        "unread": unread,
        "lastTime": last_time,
        "lastPreview": last_preview,
        "lastFrom": last_from,
        "sentiment": _inbox_sentiment(row["sentiment_label"], row["avg_sentiment"]),
        "ragSuggestions": suggestions[:5],
        "ragDraftAnswer": draft,
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


def _conversation_base_rows(conn: Any, conversation_id: str | None = None) -> list[dict[str, Any]]:
    where = "WHERE cv.id = :conversation_id" if conversation_id else ""
    params: dict[str, Any] = {"conversation_id": conversation_id} if conversation_id else {}
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
                """
            ),
            params,
        )
    )


def list_conversations() -> list[dict[str, Any]]:
    """Conversation Inbox feed — full Thread shape for the screen."""
    me_id = _actor_user_id()
    with engine.connect() as conn:
        rows = _conversation_base_rows(conn)
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
    with engine.connect() as conn:
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
    with engine.connect() as conn:
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
                {"tenant_id": TENANT_ID},
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
    import kb_retrieve

    with engine.connect() as conn:
        query = _conversation_rag_query(conn, conversation_id)

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
    retrieval = kb_retrieve.retrieve(
        query=query,
        top_k=fetch_k,
        include_draft_answer=include_draft_answer,
        source="inbox",
        prefer_policy=prefer_policy,
    )
    chips: list[str] = []
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
        if len(chips) >= 5:
            break

    # Only replace persisted chips when we have a fresh pass set. An empty
    # retrieval (score-gate miss / transient embed blip) must not wipe the last
    # good suggestions — that made Inbox look permanently empty under a stale
    # worker or noisy query.
    with engine.begin() as conn:
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

    logger = __import__("logging").getLogger(__name__)
    logger.info(
        "inbox_rag_refreshed conversation=%s chips=%s passed=%s draft=%s min_score=%s latency_ms=%s",
        conversation_id,
        len(chips),
        len(passed),
        bool(draft),
        INBOX_RAG_MIN_SCORE,
        retrieval.get("latencyMs"),
    )
    thread = get_conversation(conversation_id)
    assert thread is not None
    return {
        "conversationId": conversation_id,
        "ragSuggestions": chips[:5],
        "draftAnswer": draft,
        "chatModel": retrieval.get("chatModel"),
        "latencyMs": retrieval.get("latencyMs"),
        "logId": retrieval.get("logId"),
        "thread": thread,
    }


def create_kb_snapshot(*, label: str | None = None) -> dict[str, Any]:
    """Freeze currently enabled indexed docs + enabled FAQs for sandbox readiness."""
    import json

    snap_id = f"kb-snapshot-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    label_text = (label or "").strip() or f"KB snapshot {datetime.now(timezone.utc).date().isoformat()}"
    with engine.begin() as conn:
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
                INSERT INTO kb_snapshots (id, label, document_ids, faq_ids, created_at)
                VALUES (:id, :label, CAST(:document_ids AS jsonb), CAST(:faq_ids AS jsonb), now())
                """
            ),
            {
                "id": snap_id,
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


def list_kb_snapshots() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, label, document_ids, faq_ids, created_at
                    FROM kb_snapshots
                    ORDER BY created_at DESC, id DESC
                    """
                )
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
    with engine.begin() as conn:
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
    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text("SELECT id, customer_id, status, assigned_user_id FROM conversations WHERE id = :id"),
                {"id": conversation_id},
            )
        )
        if row is None:
            raise KeyError("conversation_not_found")
        if row["assigned_user_id"] not in (None, me_id) and row["status"] == "assigned":
            # Another agent owns it — still allow return if current actor is assigned
            # or thread is needs_human/escalated (any agent can release back).
            if row["status"] not in {"needs_human", "escalated", "assigned"}:
                raise ValueError("return_to_bot_not_allowed")
        conn.execute(
            text(
                """
                UPDATE conversations
                SET status = 'bot',
                    assigned_user_id = NULL,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": conversation_id},
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


def escalate_conversation_to_human(conversation_id: str, *, reason: str = "escalated") -> dict[str, Any]:
    """Bot / routing path → needs_human. Cancels pending bot jobs."""
    with engine.begin() as conn:
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

    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT cv.id, cv.customer_id, cv.status, cv.assigned_user_id, cv.channel,
                           c.phone_primary, c.phone_alt,
                           (
                             SELECT MAX(COALESCE(m.sent_at, m.created_at))
                             FROM messages m
                             WHERE m.conversation_id = cv.id AND m.sender = 'customer'
                           ) AS last_customer_at
                    FROM conversations cv
                    JOIN customers c ON c.id = cv.customer_id
                    WHERE cv.id = :id
                    """
                ),
                {"id": conversation_id},
            )
        )
    if row is None:
        raise KeyError("conversation_not_found")
    if row["status"] == "bot" and row["assigned_user_id"] != me_id:
        raise ValueError("bot_still_handling")

    channel = row["channel"]
    is_mine = row["assigned_user_id"] == me_id

    msg_id = _id("MSG")
    now = datetime.now(timezone.utc)

    def _finalize(conn: Any) -> None:
        # Sending implies ownership if not already assigned to someone else.
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

    # WhatsApp free-form send: only after take-over, only inside 24h window.
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

        import whatsapp as wa

        to_phone = wa.normalize_phone(row["phone_primary"]) or wa.normalize_phone(row["phone_alt"])

        # Persist a 'sending' row BEFORE the external send. If the process dies
        # after Meta accepts the message, the row still exists to match delivery
        # callbacks and to stop a client retry from re-sending the same body.
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                    VALUES (:id, :conversation_id, 'agent', :body, 'sending', NULL, :sent_at)
                    """
                ),
                {"id": msg_id, "conversation_id": conversation_id, "body": text_value, "sent_at": now},
            )

        try:
            send_resp = wa.send_text_message(to_phone=to_phone, body=text_value)
        except Exception:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE messages SET delivery_status = 'failed' WHERE id = :id"),
                    {"id": msg_id},
                )
            raise
        provider_ref = wa.extract_wamid(send_resp)

        with engine.begin() as conn:
            conn.execute(
                text("UPDATE messages SET delivery_status = 'sent', provider_ref = :ref WHERE id = :id"),
                {"id": msg_id, "ref": provider_ref},
            )
            _finalize(conn)
    else:
        with engine.begin() as conn:
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
            _finalize(conn)

    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    return result


def _digits_phone_match_sql() -> str:
    return """
      regexp_replace(COALESCE(c.phone_primary, ''), '[^0-9]', '', 'g') = :phone
      OR regexp_replace(COALESCE(c.phone_alt, ''), '[^0-9]', '', 'g') = :phone
      OR RIGHT(regexp_replace(COALESCE(c.phone_primary, ''), '[^0-9]', '', 'g'), 10) = RIGHT(:phone, 10)
      OR RIGHT(regexp_replace(COALESCE(c.phone_alt, ''), '[^0-9]', '', 'g'), 10) = RIGHT(:phone, 10)
    """


def _find_customer_by_phone(conn: Any, phone: str) -> dict[str, Any] | None:
    if not phone:
        return None
    return _one(
        conn.execute(
            text(
                f"""
                SELECT id, name, phone_primary, phone_alt
                FROM customers c
                WHERE {_digits_phone_match_sql()}
                ORDER BY c.updated_at DESC NULLS LAST, c.id
                LIMIT 1
                """
            ),
            {"phone": phone},
        )
    )


def _ensure_whatsapp_customer(conn: Any, phone: str, profile_name: str | None) -> dict[str, Any]:
    existing = _find_customer_by_phone(conn, phone)
    if existing:
        return existing
    customer_id = f"cust-wa-{phone[-10:]}" if len(phone) >= 10 else _id("cust-wa").lower()
    account_id = f"AC-WA-{phone[-6:]}" if len(phone) >= 6 else _id("AC")
    name = (profile_name or f"WhatsApp {phone[-4:]}").strip() or f"WhatsApp {phone[-4:]}"
    conn.execute(
        text(
            """
            INSERT INTO customers
              (id, tenant_id, assigned_user_id, name, phone_primary, risk, preferred_window, dnd, segment)
            VALUES
              (:id, :tenant_id, NULL, :name, :phone, 'medium', '10:00-19:00 IST', false, 'retail')
            ON CONFLICT (id) DO UPDATE SET phone_primary = EXCLUDED.phone_primary, name = EXCLUDED.name
            """
        ),
        {"id": customer_id, "tenant_id": TENANT_ID, "name": name, "phone": phone},
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
            "tenant_id": TENANT_ID,
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


def _touch_interaction_sentiment(conn: Any, interaction_id: str | None, text_value: str) -> None:
    """Blend latest customer-turn sentiment into the linked interaction (Inbox header)."""
    if not interaction_id:
        return
    from agent_core.sentiment import estimate_sentiment, sentiment_label

    score = estimate_sentiment(text_value)
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
    existing = _one(
        conn.execute(
            text("SELECT id, conversation_id FROM messages WHERE provider_ref = :ref"),
            {"ref": wa_message_id},
        )
    )
    if existing:
        return {"status": "duplicate", "messageId": existing["id"], "conversationId": existing["conversation_id"]}

    customer = _ensure_whatsapp_customer(conn, from_phone, profile_name)
    conversation_id = _open_whatsapp_conversation(conn, customer["id"])
    msg_id = _id("MSG")
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


def _apply_whatsapp_status(conn: Any, *, wa_message_id: str, status: str) -> dict[str, Any]:
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
            text("SELECT id FROM messages WHERE provider_ref = :ref"),
            {"ref": wa_message_id},
        )
    )
    if row is None:
        return {"status": "missing", "providerRef": wa_message_id}
    conn.execute(
        text("UPDATE messages SET delivery_status = :delivery WHERE id = :id"),
        {"delivery": delivery, "id": row["id"]},
    )
    return {"status": "ok", "messageId": row["id"], "delivery": delivery}


def process_whatsapp_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle Meta WhatsApp Cloud API webhook POST body (messages + statuses)."""
    import whatsapp as wa

    results: list[dict[str, Any]] = []
    with engine.begin() as conn:
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
                    results.append(
                        _ingest_inbound_whatsapp_message(
                            conn,
                            wa_message_id=wa_id,
                            from_phone=from_phone,
                            body=body,
                            profile_name=profile_name,
                            sent_at=sent_at,
                        )
                    )

                for st in value.get("statuses") or []:
                    wa_id = st.get("id")
                    status = st.get("status")
                    if not wa_id or not status:
                        continue
                    results.append(_apply_whatsapp_status(conn, wa_message_id=wa_id, status=status))

    return {"ok": True, "results": results}


# ---------------------------------------------------------------------------
# Redaction & Export Hub — reads (writes stay Phase 3A / optimistic UI)
# ---------------------------------------------------------------------------

_PII_LABELS: dict[str, str] = {
    "card": "Card number",
    "pan": "PAN / SSN",
    "phone": "Phone",
    "email": "Email",
    "address": "Address",
    "dob": "Date of birth",
    "account": "Account #",
    "ifsc": "IFSC",
    "aadhaar": "Aadhaar",
    "custom": "Custom pattern",
}

_PII_TYPES = set(_PII_LABELS)


def _redaction_channel(channel: str | None) -> str:
    if channel in {"voice", "whatsapp", "sms"}:
        return channel
    if channel in {"chat", "email"}:
        return "whatsapp" if channel == "chat" else "sms"
    return "voice"


def _actor_can_view_raw_pii(conn: Any) -> bool:
    """Raw PII in finding.text is Compliance Officer / Admin only.

    Until Phase 5 auth carries a real role claim, resolve from user_roles.
    There is no seeded 'Compliance Officer' role yet — Admin is the stand-in;
    names containing Compliance / DPO are also allowed for forward-compat.
    """
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT r.name
                FROM user_roles ur
                JOIN roles r ON r.id = ur.role_id
                WHERE ur.user_id = :uid
                """
            ),
            {"uid": _actor_user_id()},
        )
    )
    for r in rows:
        name = (r.get("name") or "").lower()
        if name in {"admin", "compliance officer", "dpo"} or "compliance" in name:
            return True
    return False


def _pii_findings_grouped(
    conn: Any,
    redaction_ids: list[str],
    *,
    allow_raw: bool,
    turn_text_by_id: dict[str, str],
) -> dict[str, list[dict[str, Any]]]:
    """Findings for many redaction records. Never puts raw PII in `text` unless allow_raw."""
    if not redaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, redaction_id, type, masked, confidence, accepted,
                       transcript_turn_id, start_offset, end_offset
                FROM pii_findings
                WHERE redaction_id = ANY(:ids)
                ORDER BY redaction_id, created_at, id
                """
            ),
            {"ids": redaction_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        pii_type = r["type"] if r["type"] in _PII_TYPES else "custom"
        masked = r["masked"] or ""
        turn_id = r["transcript_turn_id"] or ""
        start = int(r["start_offset"] or 0)
        end = int(r["end_offset"] or 0)
        raw = masked
        if allow_raw and turn_id and turn_id in turn_text_by_id and end > start:
            turn_text = turn_text_by_id[turn_id]
            if 0 <= start < end <= len(turn_text):
                raw = turn_text[start:end]
        grouped.setdefault(r["redaction_id"], []).append(
            {
                "id": r["id"],
                "turnId": turn_id,
                "type": pii_type,
                "start": start,
                "end": end,
                "text": raw,
                "masked": masked,
                "confidence": float(r["confidence"] or 0),
                "source": "auto",
                "accepted": bool(r["accepted"]),
            }
        )
    return grouped


def _redaction_audio_grouped(conn: Any, redaction_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not redaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT s.redaction_id, s.at_sec, s.duration_sec, s.muted, s.finding_id,
                       COALESCE(f.type, 'custom') AS type
                FROM redaction_audio_segments s
                LEFT JOIN pii_findings f ON f.id = s.finding_id
                WHERE s.redaction_id = ANY(:ids)
                ORDER BY s.redaction_id, s.at_sec, s.id
                """
            ),
            {"ids": redaction_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        pii_type = r["type"] if r["type"] in _PII_TYPES else "custom"
        finding_id = r["finding_id"] or ""
        if not finding_id:
            continue
        grouped.setdefault(r["redaction_id"], []).append(
            {
                "atSec": int(r["at_sec"] or 0),
                "durSec": float(r["duration_sec"] or 0),
                "type": pii_type,
                "findingId": finding_id,
                "muted": bool(r["muted"]),
            }
        )
    return grouped


def _redaction_transcripts_grouped(
    conn: Any,
    interaction_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    if not interaction_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, interaction_id, at_sec, speaker, text
                FROM interaction_transcript
                WHERE interaction_id = ANY(:ids)
                ORDER BY interaction_id, turn_index
                """
            ),
            {"ids": interaction_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["interaction_id"], []).append(
            {
                "id": r["id"],
                "t": int(r["at_sec"] or 0),
                "speaker": _speaker_screen(r["speaker"]),
                "text": r["text"] or "",
            }
        )
    return grouped


def _apply_masks_to_transcript(
    turns: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Replace finding spans with masked values so the payload never leaks raw PII
    for viewers who are not allowed to see it."""
    by_turn: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        if f.get("turnId") and f.get("end", 0) > f.get("start", 0):
            by_turn.setdefault(f["turnId"], []).append(f)
    if not by_turn:
        return turns
    out: list[dict[str, Any]] = []
    for turn in turns:
        spans = sorted(by_turn.get(turn["id"], []), key=lambda x: x["start"], reverse=True)
        text = turn["text"]
        for f in spans:
            start, end = int(f["start"]), int(f["end"])
            if 0 <= start < end <= len(text):
                text = text[:start] + (f.get("masked") or "") + text[end:]
        out.append({**turn, "text": text})
    return out


_REDACTION_LIST_SQL = """
    SELECT
      rr.id,
      rr.interaction_id AS call_id,
      rr.customer_id,
      rr.reviewed,
      c.name AS customer,
      i.channel,
      i.started_at,
      i.duration_sec,
      COALESCE(u.name, b.name, 'Unassigned') AS handler
    FROM redaction_records rr
    JOIN customers c ON c.id = rr.customer_id
    JOIN interactions i ON i.id = rr.interaction_id
    LEFT JOIN users u ON u.id = i.handler_user_id
    LEFT JOIN bots b ON b.id = i.handler_bot_id
    WHERE i.tenant_id = :tenant_id
      AND c.tenant_id = :tenant_id
"""


def _redaction_rows_to_screen(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    allow_raw = _actor_can_view_raw_pii(conn)
    redaction_ids = [r["id"] for r in rows]
    interaction_ids = [r["call_id"] for r in rows]
    transcripts = _redaction_transcripts_grouped(conn, interaction_ids)
    turn_text_by_id: dict[str, str] = {}
    for turns in transcripts.values():
        for t in turns:
            turn_text_by_id[t["id"]] = t["text"]
    findings_by = _pii_findings_grouped(
        conn, redaction_ids, allow_raw=allow_raw, turn_text_by_id=turn_text_by_id
    )
    audio_by = _redaction_audio_grouped(conn, redaction_ids)

    out: list[dict[str, Any]] = []
    for r in rows:
        findings = findings_by.get(r["id"], [])
        turns = transcripts.get(r["call_id"], [])
        if not allow_raw:
            turns = _apply_masks_to_transcript(turns, findings)
        occurred = r["started_at"]
        out.append(
            {
                "id": r["id"],
                "callId": r["call_id"],
                "customer": r["customer"] or "",
                "customerId": r["customer_id"],
                "channel": _redaction_channel(r["channel"]),
                "handler": r["handler"] or "Unassigned",
                "occurredAt": occurred if isinstance(occurred, str) else (occurred.isoformat() if occurred else ""),
                "durationSec": int(r["duration_sec"] or 0),
                "transcript": turns,
                "findings": findings,
                "audioSegments": audio_by.get(r["id"], []),
                "reviewed": bool(r["reviewed"]),
            }
        )
    return out


def list_redaction_records() -> list[dict[str, Any]]:
    """Redaction Hub queue — screen RedactionRecord shape. Scoped to TENANT_ID."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _REDACTION_LIST_SQL
                    + """
                    ORDER BY COALESCE(i.started_at, rr.created_at) DESC, rr.id
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        )
        return _redaction_rows_to_screen(conn, rows)


def get_redaction_record(redaction_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(_REDACTION_LIST_SQL + " AND rr.id = :id"),
                {"tenant_id": TENANT_ID, "id": redaction_id},
            )
        )
        if row is None:
            raise KeyError("redaction_record_not_found")
        return _redaction_rows_to_screen(conn, [row])[0]


def list_redaction_rules() -> list[dict[str, Any]]:
    """Tenant redaction rule configs — screen RedactionRules entries."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT pii_type, enabled, replacement
                    FROM redaction_rule_configs
                    WHERE tenant_id = :tenant_id
                    ORDER BY pii_type
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        )
        by_type = {r["pii_type"]: r for r in rows if r["pii_type"] in _PII_TYPES}
        # Always return the full screen vocabulary so the Rules sheet never gaps.
        out: list[dict[str, Any]] = []
        for pii_type, label in _PII_LABELS.items():
            r = by_type.get(pii_type)
            out.append(
                {
                    "piiType": pii_type,
                    "enabled": bool(r["enabled"]) if r else False,
                    "replacement": (r["replacement"] if r else f"[REDACTED-{pii_type.upper()}]"),
                    "label": label,
                }
            )
        return out


# ---------------------------------------------------------------------------
# Routing & Logic Builder — reads (writes stay Phase 3A / optimistic UI)
# ---------------------------------------------------------------------------

_ROUTING_CATEGORIES = {"Escalation", "Handoff", "Throttle", "Compliance", "Routing"}

_ROUTING_ACTION_KEYS = {
    "route_tier2",
    "route_specialist",
    "handoff_human",
    "play_disclosure",
    "send_sms",
    "log_flag",
    "stop_upsell",
    "slow_tts",
    "escalate_supervisor",
}

# Legacy action_key → screen ActionKey (pre-builder seed used "handoff").
_ROUTING_ACTION_ALIASES = {
    "handoff": "handoff_human",
    "escalate": "escalate_supervisor",
    "tier2": "route_tier2",
}


def _routing_action_key(raw: str | None) -> str:
    key = (raw or "").strip()
    key = _ROUTING_ACTION_ALIASES.get(key, key)
    if key in _ROUTING_ACTION_KEYS:
        return key
    return "log_flag"


def _routing_when(conditions: Any) -> list[Any]:
    """Normalize DB conditions jsonb into Habibi ConditionNode[]."""
    if conditions is None:
        return []
    if isinstance(conditions, list):
        return conditions
    if isinstance(conditions, dict):
        # Legacy shape e.g. {"avgSentimentLt": -0.35} → approximate screen node.
        if "avgSentimentLt" in conditions:
            return [
                {
                    "id": "legacy-sentiment",
                    "field": "sentiment",
                    "op": "=",
                    "value": "angry",
                }
            ]
        # Already a single condition node?
        if "field" in conditions or "or" in conditions:
            return [conditions]
    return []


def _routing_action_params(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            continue
        out[str(k)] = str(v)
    return out or None


def _routing_category(raw: str | None) -> str:
    if raw in _ROUTING_CATEGORIES:
        return raw
    return "Routing"


def list_routing_rules() -> list[dict[str, Any]]:
    """Priority-ordered routing rules with execution aggregates. Tenant-scoped."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      r.id,
                      r.priority,
                      r.enabled,
                      COALESCE(NULLIF(r.name, ''), r.id) AS name,
                      COALESCE(r.description, '') AS description,
                      r.category,
                      r.conditions,
                      r.action_key,
                      r.action_params,
                      COALESCE(agg.execution_count, 0) AS execution_count,
                      agg.last_fired_at,
                      COALESCE(agg.triggers_last_24h, 0) AS triggers_last_24h
                    FROM routing_rules r
                    LEFT JOIN LATERAL (
                      SELECT
                        count(*) FILTER (WHERE e.result = 'matched') AS execution_count,
                        max(e.evaluated_at) FILTER (WHERE e.result = 'matched') AS last_fired_at,
                        count(*) FILTER (
                          WHERE e.result = 'matched'
                            AND e.evaluated_at >= now() - interval '24 hours'
                        ) AS triggers_last_24h
                      FROM routing_rule_executions e
                      WHERE e.rule_id = r.id
                    ) agg ON true
                    WHERE r.tenant_id = :tenant_id
                    ORDER BY r.priority ASC, r.id
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            params = _routing_action_params(r["action_params"])
            then: dict[str, Any] = {"key": _routing_action_key(r["action_key"])}
            if params is not None:
                then["params"] = params
            last = r["last_fired_at"]
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"] or r["id"],
                    "description": r["description"] or "",
                    "category": _routing_category(r["category"]),
                    "enabled": bool(r["enabled"]),
                    "priority": int(r["priority"] or 0),
                    "when": _routing_when(r["conditions"]),
                    "then": then,
                    "executionCount": int(r["execution_count"] or 0),
                    "lastFiredAt": last if last else None,
                    "triggersLast24h": int(r["triggers_last_24h"] or 0),
                }
            )
        return out


def list_routing_rule_executions(rule_id: str) -> list[dict[str, Any]]:
    """Firing log for one rule — tenant-scoped via the parent rule."""
    with engine.connect() as conn:
        parent = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM routing_rules
                    WHERE id = :id AND tenant_id = :tenant_id
                    """
                ),
                {"id": rule_id, "tenant_id": TENANT_ID},
            )
        )
        if parent is None:
            raise KeyError("routing_rule_not_found")
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, rule_id, interaction_id, result, action_taken,
                           evaluated_at, context
                    FROM routing_rule_executions
                    WHERE rule_id = :id
                    ORDER BY evaluated_at DESC, id
                    LIMIT 100
                    """
                ),
                {"id": rule_id},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            at = r["evaluated_at"]
            ctx = r["context"] if isinstance(r["context"], dict) else {}
            out.append(
                {
                    "id": r["id"],
                    "ruleId": r["rule_id"],
                    "interactionId": r["interaction_id"],
                    "result": r["result"],
                    "actionTaken": r["action_taken"],
                    "evaluatedAt": at or "",
                    "context": ctx,
                }
            )
        return out


# ---------------------------------------------------------------------------
# My Workspace — work_items view (AssignedQueue)
# ---------------------------------------------------------------------------

_DISPUTE_TYPE_LABELS = {
    "paid_already": "Paid already",
    "wrong_amount": "Wrong amount",
    "not_my_account": "Not my account",
    "fee_waiver": "Fee waiver request",
    "duplicate_charge": "Duplicate charge",
    "fraud": "Fraud / unauthorised",
}

_DOC_TYPE_QUEUE_LABELS = {
    "account_statement": "Account statement",
    "no_dues_certificate": "NOC letter",
    "interest_certificate": "Interest certificate",
    "foreclosure_letter": "Foreclosure letter",
    "loan_schedule": "Loan schedule",
    "payment_receipt": "Payment receipt",
    "kyc_letter": "KYC letter",
}


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return None


def _fmt_hm(total_seconds: float) -> str:
    secs = max(0, int(abs(total_seconds)))
    hours, rem = divmod(secs, 3600)
    mins = rem // 60
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _work_item_age_hours(created_at: Any) -> int:
    created = _as_utc(created_at)
    if created is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - created).total_seconds() // 3600))


def _work_item_sla(
    sla_due_at: Any,
    *,
    entity_type: str,
    status: str | None,
) -> tuple[str, str]:
    """Compute (sla, slaLabel) server-side — seed strings like '1h 12m left' are not stored."""
    due = _as_utc(sla_due_at)
    now = datetime.now(timezone.utc)
    if due is None:
        if entity_type == "promise" and status == "broken":
            return "breach", "Follow up now"
        if entity_type == "promise":
            return "warn", "Follow up today"
        return "ok", "Open"

    delta = (due - now).total_seconds()
    if delta < 0:
        label = f"Overdue {_fmt_hm(delta)}"
        if entity_type == "promise" and status == "broken":
            return "breach", "Follow up now"
        return "breach", label

    # Callbacks are "due at" appointments — "In …" reads better than "… left".
    if entity_type == "callback":
        level = "warn" if delta < 2 * 3600 else "ok"
        return level, f"In {_fmt_hm(delta)}"

    if entity_type == "promise":
        if status == "broken":
            return "breach", "Follow up now"
        if status == "partial":
            return "warn", "Follow up today"
        if status == "due_today":
            return "warn", "Due today"

    level = "warn" if delta < 2 * 3600 else "ok"
    return level, f"{_fmt_hm(delta)} left"


def _inr(amount: float | None) -> str:
    if amount is None:
        return "—"
    return f"₹{amount:,.0f}"


def _snippet(text: str | None, limit: int = 72) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).replace('"', "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _work_item_enrichment(conn: Any, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-entity_type grouped enrichment — 6 queries, no N+1."""
    by_type: dict[str, list[str]] = {}
    for r in rows:
        by_type.setdefault(r["entity_type"], []).append(r["entity_id"])

    out: dict[str, dict[str, Any]] = {}

    dispute_ids = by_type.get("dispute") or []
    if dispute_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, type, disputed_amount, transcript_snippet, account_id
                    FROM disputes
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": dispute_ids},
            )
        ):
            dtype = r["type"] or "dispute"
            label = _DISPUTE_TYPE_LABELS.get(dtype, dtype.replace("_", " ").title())
            amount = float(r["disputed_amount"]) if r["disputed_amount"] is not None else None
            snippet = _snippet(r["transcript_snippet"])
            detail = snippet or (f"Disputed {_inr(amount)}" if amount is not None else "Open dispute")
            out[f"dispute:{r['id']}"] = {
                "type": label,
                "detail": detail,
                "amount": amount,
                "accountId": r["account_id"],
            }

    callback_ids = by_type.get("callback") or []
    if callback_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, reason, scheduled_at, account_id
                    FROM callbacks
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": callback_ids},
            )
        ):
            when = _as_utc(r["scheduled_at"])
            when_label = when.strftime("%I:%M %p").lstrip("0") if when else "TBD"
            reason = (r["reason"] or "general").strip()
            detail = (
                "General query"
                if reason == "general"
                else reason.replace("_", " ").capitalize()
            )
            out[f"callback:{r['id']}"] = {
                "type": f"Callback · {when_label} IST",
                "detail": detail,
                "amount": None,
                "accountId": r.get("account_id"),
            }

    doc_ids = by_type.get("document_request") or []
    if doc_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, doc_type, period, delivery_channel, account_id
                    FROM document_requests
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": doc_ids},
            )
        ):
            screen = _doc_type_screen(r["doc_type"])
            label = _DOC_TYPE_QUEUE_LABELS.get(screen) or (r["doc_type"] or "Document")
            channel = _doc_channel(r["delivery_channel"]).title()
            period = (r["period"] or "").strip()
            detail = " · ".join(p for p in (period, channel) if p) or "Document request"
            out[f"document_request:{r['id']}"] = {
                "type": label,
                "detail": detail,
                "amount": None,
                "accountId": r["account_id"],
            }

    promise_ids = by_type.get("promise") or []
    if promise_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, status, amount, paid_amount, promised_at, account_id
                    FROM promises
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": promise_ids},
            )
        ):
            status = r["status"] or "broken"
            amount = float(r["amount"]) if r["amount"] is not None else None
            paid = float(r["paid_amount"] or 0)
            when = _as_utc(r["promised_at"])
            date_label = when.strftime("%d %b") if when else ""
            if status == "partial" and amount is not None:
                type_label = "Partial PTP"
                detail = f"Paid {_inr(paid)} of {_inr(amount)} promised"
                remaining = max(0.0, amount - paid)
            elif status == "due_today":
                type_label = "PTP due today"
                detail = f"Promised {_inr(amount)}" + (f" on {date_label}" if date_label else "")
                remaining = amount
            else:
                type_label = "Broken PTP"
                detail = f"Promised {_inr(amount)}" + (f" on {date_label}" if date_label else "")
                remaining = amount
            out[f"promise:{r['id']}"] = {
                "type": type_label,
                "detail": detail.strip(),
                "amount": remaining,
                "accountId": r["account_id"],
            }

    followup_ids = by_type.get("followup") or []
    if followup_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, note, due_at, promise_id, lead_id, priority
                    FROM followups
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": followup_ids},
            )
        ):
            if r["promise_id"]:
                type_label = "Promise follow-up"
            elif r["lead_id"]:
                type_label = "Lead follow-up"
            else:
                type_label = "Follow-up"
            note = _snippet(r["note"]) or "Chase follow-up"
            out[f"followup:{r['id']}"] = {
                "type": type_label,
                "detail": note,
                "amount": None,
                "accountId": None,
            }

    lead_ids = by_type.get("lead") or []
    if lead_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT l.id, l.stage, l.offer_amount, l.estimated_value, l.account_id,
                           l.transcript_snippet, p.name AS product_name
                    FROM leads l
                    LEFT JOIN products p ON p.id = l.product_id
                    WHERE l.id = ANY(:ids)
                    """
                ),
                {"ids": lead_ids},
            )
        ):
            stage = (r["stage"] or "interested").replace("_", " ").title()
            product = r["product_name"] or _snippet(r["transcript_snippet"]) or "Offer"
            amount = r["offer_amount"] if r["offer_amount"] is not None else r["estimated_value"]
            amount_f = float(amount) if amount is not None else None
            out[f"lead:{r['id']}"] = {
                "type": f"Lead · {stage}",
                "detail": str(product),
                "amount": amount_f,
                "accountId": r.get("account_id"),
            }

    return out


def list_work_items(*, assignee: str | None = "me") -> list[dict[str, Any]]:
    """Assigned queue from the work_items view — screen QueueRow + entityType.

    assignee='me' (default) scopes to the acting user from /me (ACTOR_USER_ID).
    Pass assignee=None / 'all' for the unfiltered tenant queue.
    """
    assignee_id: str | None
    if assignee in (None, "", "all"):
        assignee_id = None
    elif assignee == "me":
        assignee_id = _actor_user_id()
    else:
        assignee_id = assignee

    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      w.entity_type,
                      w.entity_id,
                      w.customer_id,
                      w.assignee_user_id,
                      w.status,
                      w.priority,
                      w.sla_due_at,
                      w.created_at,
                      w.source,
                      c.name AS customer_name,
                      a.id AS account_id
                    FROM work_items w
                    JOIN customers c ON c.id = w.customer_id
                    LEFT JOIN LATERAL (
                      SELECT id
                      FROM accounts
                      WHERE customer_id = w.customer_id
                      ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
                      LIMIT 1
                    ) a ON true
                    WHERE (
                      CAST(:assignee_id AS text) IS NULL
                      OR w.assignee_user_id = CAST(:assignee_id AS text)
                    )
                    ORDER BY
                      CASE
                        WHEN w.sla_due_at IS NULL THEN 1
                        WHEN w.sla_due_at < now() THEN 0
                        ELSE 2
                      END,
                      w.sla_due_at ASC NULLS LAST,
                      w.created_at ASC,
                      w.entity_id
                    """
                ),
                {"assignee_id": assignee_id},
            )
        )
        enrichment = _work_item_enrichment(conn, rows)
        out: list[dict[str, Any]] = []
        for r in rows:
            key = f"{r['entity_type']}:{r['entity_id']}"
            extra = enrichment.get(key) or {}
            account_id = extra.get("accountId") or r["account_id"] or ""
            sla, sla_label = _work_item_sla(
                r["sla_due_at"],
                entity_type=r["entity_type"],
                status=r["status"],
            )
            amount = extra.get("amount")
            out.append(
                {
                    "id": r["entity_id"],
                    "customer": r["customer_name"] or "Unknown",
                    "accountId": account_id,
                    "type": extra.get("type") or r["entity_type"].replace("_", " ").title(),
                    "detail": extra.get("detail") or (r["status"] or ""),
                    "amount": amount,
                    "ageHours": _work_item_age_hours(r["created_at"]),
                    "sla": sla,
                    "slaLabel": sla_label,
                    "entityType": r["entity_type"],
                    "status": r["status"],
                    "assigneeUserId": r["assignee_user_id"],
                }
            )
        return out


# ---------------------------------------------------------------------------
# Persona & Prompt Studio (PS-1 reads)
# ---------------------------------------------------------------------------

_DEFAULT_PERSONA = {
    "traits": {"empathy": 82, "firmness": 40, "formality": 55, "verbosity": 60, "upsell": 20},
    "language": "English",
    "fallbackLanguages": ["Hindi"],
}
_DEFAULT_VOICE = {
    "voiceId": "priya",
    "speed": 1.0,
    "pitch": 0,
    "warmth": 62,
    "pauseMs": 320,
    "sampleText": "Hello Rahul, this is a courtesy call from HDFC about your EMI. Do you have a minute?",
}
_DEFAULT_GUARDRAILS = {
    "prohibited": ["guarantee", "police", "arrest", "threaten", "family will pay", "harassment"],
    "escalateAbuse": True,
    "escalateLegal": True,
    "neverQuoteRate": True,
    "neverPromiseWaiver": True,
    "alwaysDiscloseRecording": True,
    "refusePoliticsReligion": True,
    "maxTurns": 20,
    "maxSeconds": 480,
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _prompt_persona(raw: Any) -> dict[str, Any]:
    data = _as_dict(raw)
    traits_in = data.get("traits") if isinstance(data.get("traits"), dict) else {}
    base = _DEFAULT_PERSONA["traits"]
    traits = {
        "empathy": int(traits_in.get("empathy", base["empathy"])),
        "firmness": int(traits_in.get("firmness", base["firmness"])),
        "formality": int(traits_in.get("formality", base["formality"])),
        "verbosity": int(traits_in.get("verbosity", base["verbosity"])),
        "upsell": int(traits_in.get("upsell", base["upsell"])),
    }
    fallback = data.get("fallbackLanguages")
    if not isinstance(fallback, list):
        fallback = list(_DEFAULT_PERSONA["fallbackLanguages"])
    return {
        "traits": traits,
        "language": str(data.get("language") or _DEFAULT_PERSONA["language"]),
        "fallbackLanguages": [str(x) for x in fallback],
    }


def _prompt_voice(raw: Any) -> dict[str, Any]:
    data = _as_dict(raw)
    return {
        "voiceId": str(data.get("voiceId") or _DEFAULT_VOICE["voiceId"]),
        "speed": float(data.get("speed", _DEFAULT_VOICE["speed"])),
        "pitch": int(data.get("pitch", _DEFAULT_VOICE["pitch"])),
        "warmth": int(data.get("warmth", _DEFAULT_VOICE["warmth"])),
        "pauseMs": int(data.get("pauseMs", _DEFAULT_VOICE["pauseMs"])),
        "sampleText": str(data.get("sampleText") or _DEFAULT_VOICE["sampleText"]),
    }


def _prompt_guardrails(raw: Any) -> dict[str, Any]:
    data = _as_dict(raw)
    prohibited = data.get("prohibited")
    if not isinstance(prohibited, list):
        prohibited = list(_DEFAULT_GUARDRAILS["prohibited"])
    return {
        "prohibited": [str(x) for x in prohibited],
        "escalateAbuse": bool(data.get("escalateAbuse", _DEFAULT_GUARDRAILS["escalateAbuse"])),
        "escalateLegal": bool(data.get("escalateLegal", _DEFAULT_GUARDRAILS["escalateLegal"])),
        "neverQuoteRate": bool(data.get("neverQuoteRate", _DEFAULT_GUARDRAILS["neverQuoteRate"])),
        "neverPromiseWaiver": bool(data.get("neverPromiseWaiver", _DEFAULT_GUARDRAILS["neverPromiseWaiver"])),
        "alwaysDiscloseRecording": bool(
            data.get("alwaysDiscloseRecording", _DEFAULT_GUARDRAILS["alwaysDiscloseRecording"])
        ),
        "refusePoliticsReligion": bool(
            data.get("refusePoliticsReligion", _DEFAULT_GUARDRAILS["refusePoliticsReligion"])
        ),
        "maxTurns": int(data.get("maxTurns", _DEFAULT_GUARDRAILS["maxTurns"])),
        "maxSeconds": int(data.get("maxSeconds", _DEFAULT_GUARDRAILS["maxSeconds"])),
    }


def _prompt_version_status(raw: Any) -> str:
    s = str(raw or "archived")
    return s if s in {"draft", "published", "archived"} else "archived"


def _map_prompt_version(r: dict[str, Any]) -> dict[str, Any]:
    from agent_core.tuning import default_tuning, normalize_tuning

    label = r.get("label") or r.get("id") or ""
    created = r.get("created_at")
    raw_tuning = r.get("tuning")
    tuning = normalize_tuning(raw_tuning) if isinstance(raw_tuning, dict) and raw_tuning else default_tuning()
    return {
        "id": r["id"],
        "label": str(label),
        "author": r.get("author_name") or "Unknown",
        "status": _prompt_version_status(r.get("status")),
        "createdAt": created if isinstance(created, str) else (created.isoformat() if created else ""),
        "summary": r.get("summary") or "",
        "prompt": r.get("prompt") or "",
        "persona": _prompt_persona(r.get("persona")),
        "voice": _prompt_voice(r.get("voice")),
        "guardrails": _prompt_guardrails(r.get("guardrails")),
        "tuning": tuning,
    }


def list_prompt_versions() -> list[dict[str, Any]]:
    """Version history newest-first — editor rail."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    ORDER BY p.created_at DESC, p.id DESC
                    """
                )
            )
        )
        return [_map_prompt_version(r) for r in rows]


def get_published_prompt_version() -> dict[str, Any] | None:
    """Editor live badge — must match active prod deployment (invariant)."""
    with engine.connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.status = 'published'
                    LIMIT 1
                    """
                )
            )
        )
        return _map_prompt_version(r) if r else None


def get_prompt_version(version_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.id = :id
                    """
                ),
                {"id": version_id},
            )
        )
        return _map_prompt_version(r) if r else None


def list_persona_presets() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, config
                    FROM persona_presets
                    ORDER BY CASE id
                      WHEN 'empathetic' THEN 1
                      WHEN 'firm' THEN 2
                      WHEN 'compliance' THEN 3
                      WHEN 'upsell' THEN 4
                      ELSE 99
                    END, id
                    """
                )
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            cfg = _as_dict(r.get("config"))
            traits_in = cfg.get("traits") if isinstance(cfg.get("traits"), dict) else {}
            traits = {
                "empathy": int(traits_in.get("empathy", 50)),
                "firmness": int(traits_in.get("firmness", 50)),
                "formality": int(traits_in.get("formality", 50)),
                "verbosity": int(traits_in.get("verbosity", 50)),
                "upsell": int(traits_in.get("upsell", 20)),
            }
            out.append(
                {
                    "id": r["id"],
                    "label": str(cfg.get("label") or r.get("name") or r["id"]),
                    "description": str(cfg.get("description") or ""),
                    "traits": traits,
                    "promptTemplate": str(cfg.get("promptTemplate") or ""),
                }
            )
        return out


def list_tts_voices() -> list[dict[str, Any]]:
    """Enabled Azure Speech catalog for the Voice tab."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, config, enabled
                    FROM tts_voices
                    WHERE enabled = true
                    ORDER BY CASE id
                      WHEN 'priya' THEN 1
                      WHEN 'anjali' THEN 2
                      WHEN 'neha' THEN 3
                      WHEN 'ravi' THEN 4
                      WHEN 'arjun' THEN 5
                      WHEN 'kabir' THEN 6
                      ELSE 99
                    END, name, id
                    """
                )
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            cfg = _as_dict(r.get("config"))
            gender = cfg.get("gender") or "Female"
            if gender not in ("Female", "Male"):
                gender = "Female"
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"] or r["id"],
                    "gender": gender,
                    "accent": str(cfg.get("accent") or ""),
                    "duration": str(cfg.get("duration") or "0:03"),
                    "azureVoiceName": cfg.get("azureVoiceName"),
                }
            )
        return out


def list_bot_deployments(
    *,
    environment: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Runtime deployments — authoritative for what runs."""
    clauses = ["1=1"]
    params: dict[str, Any] = {}
    if environment in ("sandbox", "production"):
        clauses.append("d.environment = :environment")
        params["environment"] = environment
    if status in ("active", "rolled_back", "retired"):
        clauses.append("d.status = :status")
        params["status"] = status
    where = " AND ".join(clauses)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                      d.tts_voice_id, d.environment, d.status,
                      d.published_at, d.rollback_deployment_id, d.voice_config,
                      d.tuning,
                      COALESCE(u.name, d.published_by_user_id) AS published_by
                    FROM bot_deployments d
                    LEFT JOIN users u ON u.id = d.published_by_user_id
                    WHERE {where}
                    ORDER BY d.published_at DESC NULLS LAST, d.id DESC
                    """
                ),
                params,
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            published = r.get("published_at")
            out.append(
                {
                    "id": r["id"],
                    "botId": r["bot_id"],
                    "promptVersionId": r["prompt_version_id"],
                    "kbSnapshotId": r.get("kb_snapshot_id"),
                    "ttsVoiceId": r.get("tts_voice_id"),
                    "environment": r["environment"],
                    "status": r["status"],
                    "publishedBy": r.get("published_by"),
                    "publishedAt": (
                        published
                        if isinstance(published, str)
                        else (published.isoformat() if published else None)
                    ),
                    "rollbackDeploymentId": r.get("rollback_deployment_id"),
                    "voiceConfig": _as_dict(r.get("voice_config")),
                    "tuning": _as_dict(r.get("tuning")),
                }
            )
        return out


# ---------------------------------------------------------------------------
# Persona & Prompt Studio — writes (PS-2)
# Live-config invariant: active prod deployment.prompt_version_id
# must equal the single prompt_versions row with status='published'.
# ---------------------------------------------------------------------------

DEFAULT_BOT_ID = os.getenv("BOT_ID", "kaia-v2-4")

_ACTIVE_DEPLOYMENT_SELECT = """
    SELECT
      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
      d.tts_voice_id, d.environment, d.status,
      d.published_at, d.rollback_deployment_id, d.voice_config, d.tuning,
      COALESCE(u.name, d.published_by_user_id) AS published_by
    FROM bot_deployments d
    LEFT JOIN users u ON u.id = d.published_by_user_id
    WHERE d.bot_id = :bot_id
      AND d.environment = :environment
      AND d.status = 'active'
    ORDER BY d.published_at DESC NULLS LAST, d.id DESC
    LIMIT 1
"""


def _fetch_active_deployment_row(
    conn: Any,
    *,
    bot_id: str,
    environment: str,
) -> dict[str, Any] | None:
    """Raw active deployment row inside an open connection/transaction."""
    return _one(
        conn.execute(
            text(_ACTIVE_DEPLOYMENT_SELECT),
            {"bot_id": bot_id, "environment": environment},
        )
    )


def get_active_deployment(
    bot_id: str | None = None,
    environment: str = "production",
) -> dict[str, Any] | None:
    """Authoritative runtime loader. One active row per (bot, env) expected.

    Multi-bot note: still filtered by bot_id even though prompt_versions are
    global (Phase 5 structural change required for true multi-bot prompts).
    """
    bid = (bot_id or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    env = environment if environment in ("sandbox", "production") else "production"
    with engine.connect() as conn:
        row = _fetch_active_deployment_row(conn, bot_id=bid, environment=env)
        return _map_bot_deployment_row(row) if row else None


def _latest_kb_snapshot_id(conn: Any) -> str | None:
    """Newest snapshot by created_at — bookkeeping only (retrieve stays live)."""
    row = _one(
        conn.execute(
            text(
                """
                SELECT id FROM kb_snapshots
                ORDER BY created_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            )
        )
    )
    return row["id"] if row else None

_PROMPT_VERSION_SELECT = """
    SELECT
      p.id, p.label, p.summary, p.status, p.prompt,
      p.persona, p.voice, p.guardrails, p.tuning, p.created_at,
      COALESCE(u.name, 'Unknown') AS author_name
    FROM prompt_versions p
    LEFT JOIN users u ON u.id = p.author_user_id
"""


def _jsonb(value: Any) -> str:
    import json

    return json.dumps(value)


def _prompt_id_from_label(label: str | None) -> str:
    if label:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip()).strip("_").lower()
        if slug:
            return slug
    return _id("pv").lower()


def _fetch_prompt_version(conn: Any, version_id: str) -> dict[str, Any] | None:
    r = _one(
        conn.execute(
            text(_PROMPT_VERSION_SELECT + " WHERE p.id = :id"),
            {"id": version_id},
        )
    )
    return _map_prompt_version(r) if r else None


def _map_bot_deployment_row(r: dict[str, Any]) -> dict[str, Any]:
    from agent_core.tuning import default_tuning, normalize_tuning

    published = r.get("published_at")
    raw_tuning = _as_dict(r.get("tuning"))
    tuning = normalize_tuning(raw_tuning) if raw_tuning else default_tuning()
    return {
        "id": r["id"],
        "botId": r["bot_id"],
        "promptVersionId": r["prompt_version_id"],
        "kbSnapshotId": r.get("kb_snapshot_id"),
        "ttsVoiceId": r.get("tts_voice_id"),
        "environment": r["environment"],
        "status": r["status"],
        "publishedBy": r.get("published_by"),
        "publishedAt": (
            published if isinstance(published, str) else (published.isoformat() if published else None)
        ),
        "rollbackDeploymentId": r.get("rollback_deployment_id"),
        "voiceConfig": _as_dict(r.get("voice_config")),
        "tuning": tuning,
    }


def _fetch_bot_deployment(conn: Any, deployment_id: str) -> dict[str, Any] | None:
    r = _one(
        conn.execute(
            text(
                """
                SELECT
                  d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                  d.tts_voice_id, d.environment, d.status,
                  d.published_at, d.rollback_deployment_id, d.voice_config, d.tuning,
                  COALESCE(u.name, d.published_by_user_id) AS published_by
                FROM bot_deployments d
                LEFT JOIN users u ON u.id = d.published_by_user_id
                WHERE d.id = :id
                """
            ),
            {"id": deployment_id},
        )
    )
    return _map_bot_deployment_row(r) if r else None


def create_prompt_version(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert a draft prompt version with validated jsonb payloads."""
    from agent_core.tuning import apply_voice_config_overlay, default_tuning
    from azure_speech import resolve_azure_voice_name

    label = (payload.get("label") or "").strip() or None
    version_id = _prompt_id_from_label(label)
    voice = _prompt_voice(payload.get("voice"))
    # Seed draft.tuning from Prompt Studio voice sliders (one source of truth).
    draft_tuning = apply_voice_config_overlay(
        default_tuning(),
        voice_name=resolve_azure_voice_name(voice.get("voiceId")),
        speed=float(voice.get("speed", 1.0)),
        pitch=int(voice.get("pitch", 0)),
        warmth=int(voice.get("warmth", 60)),
    )
    with engine.begin() as conn:
        # Avoid colliding with an existing id (e.g. republish of same label slug).
        if _one(conn.execute(text("SELECT 1 FROM prompt_versions WHERE id = :id"), {"id": version_id})):
            version_id = f"{version_id}-{uuid.uuid4().hex[:6]}"
        conn.execute(
            text(
                """
                INSERT INTO prompt_versions (
                  id, author_user_id, status, prompt, persona, voice, guardrails,
                  tuning, label, summary, created_at, updated_at
                ) VALUES (
                  :id, :author, 'draft', :prompt,
                  CAST(:persona AS jsonb), CAST(:voice AS jsonb), CAST(:guardrails AS jsonb),
                  CAST(:tuning AS jsonb),
                  :label, :summary, now(), now()
                )
                """
            ),
            {
                "id": version_id,
                "author": _actor_user_id(),
                "prompt": payload["prompt"],
                "persona": _jsonb(payload["persona"]),
                "voice": _jsonb(voice),
                "guardrails": _jsonb(payload["guardrails"]),
                "tuning": _jsonb(draft_tuning),
                "label": label,
                "summary": payload.get("summary") or "",
            },
        )
        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row


def patch_prompt_version(version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update draft fields only — raises ValueError if not a draft."""
    with engine.begin() as conn:
        existing = _one(
            conn.execute(
                text("SELECT id, status, voice, tuning FROM prompt_versions WHERE id = :id"),
                {"id": version_id},
            )
        )
        if not existing:
            raise KeyError(f"prompt_version_not_found: {version_id}")
        if existing["status"] != "draft":
            raise ValueError("prompt_version_not_draft")

        sets: list[str] = []
        params: dict[str, Any] = {"id": version_id}
        if "label" in payload and payload["label"] is not None:
            sets.append("label = :label")
            params["label"] = str(payload["label"]).strip() or None
        if payload.get("prompt") is not None:
            sets.append("prompt = :prompt")
            params["prompt"] = payload["prompt"]
        if payload.get("persona") is not None:
            sets.append("persona = CAST(:persona AS jsonb)")
            params["persona"] = _jsonb(payload["persona"])
        if payload.get("voice") is not None:
            from agent_core.tuning import apply_voice_config_overlay, normalize_tuning
            from azure_speech import resolve_azure_voice_name

            voice = _prompt_voice(payload["voice"])
            sets.append("voice = CAST(:voice AS jsonb)")
            params["voice"] = _jsonb(voice)
            # Keep draft.tuning in sync with VoicePanel sliders (publish reads this).
            folded = apply_voice_config_overlay(
                normalize_tuning(_as_dict(existing.get("tuning"))),
                voice_name=resolve_azure_voice_name(voice.get("voiceId")),
                speed=float(voice.get("speed", 1.0)),
                pitch=int(voice.get("pitch", 0)),
                warmth=int(voice.get("warmth", 60)),
            )
            sets.append("tuning = CAST(:tuning AS jsonb)")
            params["tuning"] = _jsonb(folded)
        if payload.get("guardrails") is not None:
            sets.append("guardrails = CAST(:guardrails AS jsonb)")
            params["guardrails"] = _jsonb(payload["guardrails"])
        if payload.get("summary") is not None:
            sets.append("summary = :summary")
            params["summary"] = payload["summary"]
        if "tuning" in payload and payload["tuning"] is not None:
            from agent_core.tuning import normalize_tuning

            # Explicit Tuning Studio / Promote write wins over voice fold above
            # when both arrive in one patch (rare).
            sets = [s for s in sets if not s.startswith("tuning =")]
            sets.append("tuning = CAST(:tuning AS jsonb)")
            params["tuning"] = _jsonb(normalize_tuning(payload["tuning"]))
        if not sets:
            row = _fetch_prompt_version(conn, version_id)
            assert row is not None
            return row
        sets.append("updated_at = now()")
        conn.execute(
            text(f"UPDATE prompt_versions SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row


def publish_prompt_version(
    version_id: str,
    summary: str = "",
    *,
    kb_snapshot_id: str | None = None,
    tuning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Archive current published → promote draft → swap active prod deployment.

    kb_snapshot_id: explicit Sandbox pin wins; else prior active snap, else latest.
    tuning: explicit AgentTuning from Sandbox Promote; else prior deployment tuning.
    """
    from sqlalchemy.exc import IntegrityError
    from agent_core.tuning import apply_voice_config_overlay, default_tuning, normalize_tuning
    from azure_speech import resolve_azure_voice_name

    with engine.begin() as conn:
        target = _one(
            conn.execute(
                text(
                    """
                    SELECT id, status, voice, label, tuning
                    FROM prompt_versions WHERE id = :id
                    """
                ),
                {"id": version_id},
            )
        )
        if not target:
            raise KeyError(f"prompt_version_not_found: {version_id}")
        if target["status"] != "draft":
            raise ValueError("prompt_version_not_draft")

        note = (summary or "").strip()
        voice = _prompt_voice(target.get("voice"))
        tts_voice_id = voice.get("voiceId") or None
        if tts_voice_id:
            if not _one(
                conn.execute(text("SELECT 1 FROM tts_voices WHERE id = :id"), {"id": tts_voice_id})
            ):
                tts_voice_id = None

        prior = _fetch_active_deployment_row(
            conn, bot_id=DEFAULT_BOT_ID, environment="production"
        )
        resolved_snap = kb_snapshot_id
        if not resolved_snap:
            resolved_snap = prior.get("kb_snapshot_id") if prior else None
        if not resolved_snap:
            resolved_snap = _latest_kb_snapshot_id(conn)
        if resolved_snap and not _one(
            conn.execute(text("SELECT 1 FROM kb_snapshots WHERE id = :id"), {"id": resolved_snap})
        ):
            raise ValueError(f"kb_snapshot_not_found: {resolved_snap}")

        voice_config = _as_dict(prior.get("voice_config")) if prior else {}
        if tuning is not None:
            # Sandbox Promote — Tuning Studio payload is authoritative.
            resolved_tuning = normalize_tuning(tuning)
        else:
            prior_tuning = _as_dict(prior.get("tuning")) if prior else {}
            target_tuning = _as_dict(target.get("tuning"))
            seed = target_tuning or prior_tuning
            resolved_tuning = normalize_tuning(seed) if seed else default_tuning()
            # Prompt Studio publish: fold voice sliders into AgentTuning.tts once
            # so runtime never needs the warmth/speed/pitch overlay.
            resolved_tuning = apply_voice_config_overlay(
                resolved_tuning,
                voice_name=resolve_azure_voice_name(voice.get("voiceId")),
                speed=float(voice.get("speed", 1.0)),
                pitch=int(voice.get("pitch", 0)),
                warmth=int(voice.get("warmth", 60)),
            )

        conn.execute(
            text(
                """
                UPDATE prompt_versions
                SET tuning = CAST(:tuning AS jsonb), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": version_id, "tuning": _jsonb(resolved_tuning)},
        )

        try:
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'archived', updated_at = now()
                    WHERE status = 'published'
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'published',
                        summary = CASE WHEN :summary = '' THEN summary ELSE :summary END,
                        updated_at = now()
                    WHERE id = :id AND status = 'draft'
                    """
                ),
                {"id": version_id, "summary": note},
            )
            # Force unique-index check before we leave the transaction half-done.
            promoted = _one(
                conn.execute(
                    text("SELECT id, status FROM prompt_versions WHERE id = :id"),
                    {"id": version_id},
                )
            )
            if not promoted or promoted["status"] != "published":
                raise ValueError("publish_failed")

            if prior:
                conn.execute(
                    text(
                        """
                        UPDATE bot_deployments
                        SET status = 'retired', updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": prior["id"]},
                )

            dep_id = _id("DEP")
            conn.execute(
                text(
                    """
                    INSERT INTO bot_deployments (
                      id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                      environment, status, published_by_user_id, published_at,
                      rollback_deployment_id, voice_config, tuning, created_at, updated_at
                    ) VALUES (
                      :id, :bot_id, :prompt_version_id, :kb_snapshot_id, :tts_voice_id,
                      'production', 'active', :actor, now(),
                      :rollback_id, CAST(:voice_config AS jsonb), CAST(:tuning AS jsonb),
                      now(), now()
                    )
                    """
                ),
                {
                    "id": dep_id,
                    "bot_id": DEFAULT_BOT_ID,
                    "prompt_version_id": version_id,
                    "kb_snapshot_id": resolved_snap,
                    "tts_voice_id": tts_voice_id,
                    "actor": _actor_user_id(),
                    "rollback_id": prior["id"] if prior else None,
                    "voice_config": _jsonb(voice_config),
                    "tuning": _jsonb(resolved_tuning),
                },
            )
        except IntegrityError as exc:
            raise ValueError("publish_conflict") from exc

        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row


def restore_prompt_version_as_draft(version_id: str) -> dict[str, Any]:
    """Copy any version into a new draft — never mutates live published/deployment."""
    with engine.begin() as conn:
        source = _one(
            conn.execute(
                text(
                    """
                    SELECT id, label, prompt, persona, voice, guardrails
                    FROM prompt_versions WHERE id = :id
                    """
                ),
                {"id": version_id},
            )
        )
        if not source:
            raise KeyError(f"prompt_version_not_found: {version_id}")

        new_id = f"{source['id']}-r-{uuid.uuid4().hex[:6]}"
        src_label = source.get("label") or source["id"]
        conn.execute(
            text(
                """
                INSERT INTO prompt_versions (
                  id, author_user_id, status, prompt, persona, voice, guardrails,
                  label, summary, created_at, updated_at
                ) VALUES (
                  :id, :author, 'draft', :prompt,
                  CAST(:persona AS jsonb), CAST(:voice AS jsonb), CAST(:guardrails AS jsonb),
                  :label, :summary, now(), now()
                )
                """
            ),
            {
                "id": new_id,
                "author": _actor_user_id(),
                "prompt": source["prompt"],
                "persona": _jsonb(_as_dict(source.get("persona"))),
                "voice": _jsonb(_as_dict(source.get("voice"))),
                "guardrails": _jsonb(_as_dict(source.get("guardrails"))),
                "label": None,
                "summary": f"restored from {src_label}",
            },
        )
        row = _fetch_prompt_version(conn, new_id)
    assert row is not None
    return row


def discard_prompt_version(version_id: str) -> dict[str, Any]:
    """Archive a draft only — never touches published / deployments."""
    with engine.begin() as conn:
        existing = _one(
            conn.execute(
                text("SELECT id, status FROM prompt_versions WHERE id = :id"),
                {"id": version_id},
            )
        )
        if not existing:
            raise KeyError(f"prompt_version_not_found: {version_id}")
        if existing["status"] != "draft":
            raise ValueError("prompt_version_not_draft")
        conn.execute(
            text(
                """
                UPDATE prompt_versions
                SET status = 'archived', updated_at = now()
                WHERE id = :id AND status = 'draft'
                """
            ),
            {"id": version_id},
        )
        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row


def rollback_bot_deployment(deployment_id: str) -> dict[str, Any]:
    """Re-activate a prior prod deployment and re-publish its prompt version.

    Re-publish is mandatory so the live-config invariant never splits.
    """
    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        target = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                      d.tts_voice_id, d.environment, d.status, d.voice_config, d.tuning
                    FROM bot_deployments d
                    WHERE d.id = :id
                    """
                ),
                {"id": deployment_id},
            )
        )
        if not target:
            raise KeyError(f"bot_deployment_not_found: {deployment_id}")
        if target["environment"] != "production":
            raise ValueError("rollback_requires_production_deployment")
        if target["status"] == "active":
            raise ValueError("deployment_already_active")

        prompt_version_id = target["prompt_version_id"]
        pv = _one(
            conn.execute(
                text("SELECT id FROM prompt_versions WHERE id = :id"),
                {"id": prompt_version_id},
            )
        )
        if not pv:
            raise KeyError(f"prompt_version_not_found: {prompt_version_id}")

        current = _fetch_active_deployment_row(
            conn, bot_id=target["bot_id"], environment="production"
        )

        try:
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'archived', updated_at = now()
                    WHERE status = 'published'
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'published', updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": prompt_version_id},
            )
            if current:
                conn.execute(
                    text(
                        """
                        UPDATE bot_deployments
                        SET status = 'rolled_back', updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": current["id"]},
                )

            # Insert a fresh active row pointing at the rolled-back config
            # (keeps history; links rollback_deployment_id to the prior active).
            new_id = _id("DEP")
            conn.execute(
                text(
                    """
                    INSERT INTO bot_deployments (
                      id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                      environment, status, published_by_user_id, published_at,
                      rollback_deployment_id, voice_config, tuning, created_at, updated_at
                    ) VALUES (
                      :id, :bot_id, :prompt_version_id, :kb_snapshot_id, :tts_voice_id,
                      'production', 'active', :actor, now(),
                      :rollback_id, CAST(:voice_config AS jsonb), CAST(:tuning AS jsonb),
                      now(), now()
                    )
                    """
                ),
                {
                    "id": new_id,
                    "bot_id": target["bot_id"],
                    "prompt_version_id": prompt_version_id,
                    "kb_snapshot_id": target.get("kb_snapshot_id"),
                    "tts_voice_id": target.get("tts_voice_id"),
                    "actor": _actor_user_id(),
                    "rollback_id": current["id"] if current else deployment_id,
                    "voice_config": _jsonb(_as_dict(target.get("voice_config"))),
                    "tuning": _jsonb(_as_dict(target.get("tuning"))),
                },
            )
        except IntegrityError as exc:
            raise ValueError("publish_conflict") from exc

        row = _fetch_bot_deployment(conn, new_id)
    assert row is not None
    return row


# ---------------------------------------------------------------------------
# Knowledge Base (RAG) — Phase KB-2 library admin
# ---------------------------------------------------------------------------

_KB_ALLOWED_TYPES = {"policy", "sop", "product", "compliance", "faq", "benefits"}


def _kb_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except Exception:
            return [value] if value else []
    return []


def _kb_filename_fallback(source_path: str | None, doc_id: str) -> str:
    if source_path:
        return Path(source_path).name
    return f"{doc_id}.txt"


def _bump_kb_version(version: str | None) -> str:
    raw = (version or "v1.0").lstrip("vV")
    parts = raw.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return f"v{major}.{minor + 1}"
    except ValueError:
        return f"{version or 'v1'}-next"


def _serialize_kb_document(row: dict[str, Any]) -> dict[str, Any]:
    last = row.get("last_indexed_at") or row.get("updated_at") or ""
    chunk_size = int(row.get("chunk_size") or 512)
    overlap = int(row.get("chunk_overlap") or 64)
    return {
        "id": row["id"],
        "title": row.get("title") or row["id"],
        "filename": row.get("filename")
        or _kb_filename_fallback(row.get("source_path"), row["id"]),
        "type": row["type"],
        "version": row.get("version") or "v1.0",
        "status": row.get("status") or "draft",
        "enabled": bool(row.get("enabled")),
        "chunks": int(row.get("chunk_count") or 0),
        "chunkSize": chunk_size,
        "overlap": overlap,
        "embeddingModel": row.get("embedding_model") or "",
        "updatedBy": row.get("updated_by_name") or "System",
        "lastIndexed": last if isinstance(last, str) else (last.isoformat() if last else ""),
        "tags": _kb_tags(row.get("tags")),
    }


_KB_DOC_SELECT = """
    SELECT d.id, d.title, d.type, d.version, d.status, d.enabled,
           d.chunk_size, d.chunk_overlap, d.embedding_model, d.last_indexed_at,
           d.tags, d.source_path, d.updated_at, d.product_key,
           u.name AS updated_by_name,
           sf.filename,
           (SELECT count(*)::int FROM kb_chunks c WHERE c.document_id = d.id) AS chunk_count
    FROM kb_documents d
    LEFT JOIN users u ON u.id = d.updated_by_user_id
    LEFT JOIN LATERAL (
      SELECT filename
      FROM kb_source_files
      WHERE document_id = d.id
      ORDER BY created_at DESC
      LIMIT 1
    ) sf ON true
"""


def list_kb_documents() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(text(_KB_DOC_SELECT + " ORDER BY d.updated_at DESC, d.id ASC"))
        )
    return [_serialize_kb_document(r) for r in rows]


def get_kb_document(document_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(_KB_DOC_SELECT + " WHERE d.id = :id"),
                {"id": document_id},
            )
        )
    return _serialize_kb_document(row) if row else None


def list_kb_chunks(document_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, document_id, heading, tokens, text, hits, chunk_index
                    FROM kb_chunks
                    WHERE document_id = :id
                    ORDER BY chunk_index ASC, created_at ASC
                    """
                ),
                {"id": document_id},
            )
        )
    return [
        {
            "id": r["id"],
            "docId": r["document_id"],
            "index": int(r["chunk_index"]),
            "heading": r.get("heading") or "",
            "tokens": int(r.get("tokens") or 0),
            "text": r.get("text") or "",
            "hits": int(r.get("hits") or 0),
        }
        for r in rows
    ]


def get_kb_stats() -> dict[str, Any]:
    with engine.connect() as conn:
        doc_row = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      count(*)::int AS docs,
                      count(*) FILTER (
                        WHERE enabled AND status = 'indexed'
                      )::int AS active_docs,
                      max(last_indexed_at) AS last_indexed
                    FROM kb_documents
                    """
                )
            )
        ) or {"docs": 0, "active_docs": 0, "last_indexed": None}
        faq_row = _one(
            conn.execute(
                text("SELECT count(*)::int AS n FROM faq_pairs WHERE enabled = true")
            )
        ) or {"n": 0}
        chunk_row = _one(
            conn.execute(
                text(
                    """
                    SELECT count(*)::int AS n
                    FROM kb_chunks c
                    JOIN kb_documents d ON d.id = c.document_id
                    WHERE d.enabled = true AND d.status = 'indexed'
                    """
                )
            )
        ) or {"n": 0}
        gap_row = _one(
            conn.execute(
                text(
                    """
                    SELECT count(*)::int AS n
                    FROM unanswered_questions uq
                    WHERE uq.tenant_id = :tenant_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM analytics_kb_gap_links g
                        WHERE g.unanswered_question_id = uq.id
                          AND (g.faq_pair_id IS NOT NULL OR g.kb_document_id IS NOT NULL)
                      )
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        ) or {"n": 0}
        score_row = _one(
            conn.execute(
                text(
                    """
                    SELECT avg(score) AS avg_score
                    FROM (
                      SELECT (elem->>'score')::float AS score
                      FROM retrieval_logs rl
                      CROSS JOIN LATERAL jsonb_array_elements(
                        COALESCE(rl.top_chunks, '[]'::jsonb)
                      ) WITH ORDINALITY AS t(elem, ord)
                      WHERE ord = 1
                        AND (elem->>'score') IS NOT NULL
                      ORDER BY rl.created_at DESC
                      LIMIT 100
                    ) s
                    """
                )
            )
        ) or {"avg_score": None}

    last = doc_row.get("last_indexed") or ""
    avg = score_row.get("avg_score")
    try:
        avg_score = float(avg) if avg is not None else 0.0
    except (TypeError, ValueError):
        avg_score = 0.0
    return {
        "docs": int(doc_row.get("docs") or 0),
        "activeDocs": int(doc_row.get("active_docs") or 0),
        "faqs": int(faq_row.get("n") or 0),
        "chunks": int(chunk_row.get("n") or 0),
        "gaps": int(gap_row.get("n") or 0),
        "lastIndexed": last if isinstance(last, str) else (last.isoformat() if last else ""),
        "avgScore": round(avg_score, 4),
    }


def get_kb_index_job(job_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, document_id, status, chunk_size, chunk_overlap,
                           embedding_model, started_at, completed_at, error,
                           created_at, updated_at
                    FROM kb_index_jobs
                    WHERE id = :id
                    """
                ),
                {"id": job_id},
            )
        )
    if not row:
        return None
    return {
        "id": row["id"],
        "documentId": row["document_id"],
        "status": row["status"],
        "chunkSize": row.get("chunk_size"),
        "chunkOverlap": row.get("chunk_overlap"),
        "embeddingModel": row.get("embedding_model"),
        "startedAt": row.get("started_at"),
        "completedAt": row.get("completed_at"),
        "error": row.get("error"),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def patch_kb_document(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Enable/disable (chunk eviction), title/tags/chunk params. Returns document (+ optional jobId)."""
    import kb_ingest

    with engine.begin() as conn:
        existing = _one(
            conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": document_id})
        )
        if not existing:
            raise KeyError(f"kb document not found: {document_id}")

        job_id: str | None = None
        if "enabled" in payload and payload["enabled"] is not None:
            job_id = kb_ingest.set_document_enabled(conn, document_id, bool(payload["enabled"]))

        sets: list[str] = []
        params: dict[str, Any] = {"id": document_id}
        if payload.get("title") is not None:
            sets.append("title = :title")
            params["title"] = str(payload["title"]).strip() or document_id
        if payload.get("tags") is not None:
            import json

            sets.append("tags = CAST(:tags AS jsonb)")
            params["tags"] = json.dumps([str(t) for t in payload["tags"]])
        if payload.get("chunkSize") is not None:
            sets.append("chunk_size = :chunk_size")
            params["chunk_size"] = int(payload["chunkSize"])
        if payload.get("overlap") is not None:
            sets.append("chunk_overlap = :overlap")
            params["overlap"] = int(payload["overlap"])
        if sets:
            sets.append("updated_at = now()")
            conn.execute(
                text(f"UPDATE kb_documents SET {', '.join(sets)} WHERE id = :id"),
                params,
            )

    doc = get_kb_document(document_id)
    assert doc is not None
    return {"document": doc, "jobId": job_id}


def reindex_kb_document(document_id: str) -> dict[str, Any]:
    import kb_ingest

    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text("SELECT id, chunk_size, chunk_overlap FROM kb_documents WHERE id = :id"),
                {"id": document_id},
            )
        )
        if not row:
            raise KeyError(f"kb document not found: {document_id}")
        # Drop stale queued/failed jobs for this doc to avoid duplicate work.
        conn.execute(
            text(
                """
                DELETE FROM kb_index_jobs
                WHERE document_id = :id AND status IN ('queued', 'failed')
                """
            ),
            {"id": document_id},
        )
        job_id = kb_ingest.enqueue_index_job(
            conn,
            document_id=document_id,
            chunk_size=row.get("chunk_size"),
            chunk_overlap=row.get("chunk_overlap"),
        )
    return {"jobId": job_id, "documentId": document_id, "status": "queued"}


def reindex_all_kb_documents() -> dict[str, Any]:
    import kb_ingest

    job_ids: list[str] = []
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, chunk_size, chunk_overlap
                    FROM kb_documents
                    WHERE enabled = true
                    ORDER BY id
                    """
                )
            )
        )
        for row in rows:
            conn.execute(
                text(
                    """
                    DELETE FROM kb_index_jobs
                    WHERE document_id = :id AND status IN ('queued', 'failed')
                    """
                ),
                {"id": row["id"]},
            )
            job_ids.append(
                kb_ingest.enqueue_index_job(
                    conn,
                    document_id=row["id"],
                    chunk_size=row.get("chunk_size"),
                    chunk_overlap=row.get("chunk_overlap"),
                )
            )
    return {"jobIds": job_ids, "count": len(job_ids)}


def _kb_delete_minio_refs(storage_refs: list[str]) -> int:
    """Best-effort MinIO cleanup; never raises."""
    if not storage_refs:
        return 0
    try:
        import storage as object_store
    except Exception:
        return 0
    removed = 0
    for ref in storage_refs:
        try:
            if object_store.delete_object(ref):
                removed += 1
        except Exception:
            pass
    return removed


def delete_kb_document(document_id: str) -> dict[str, Any]:
    """Hard-delete a KB document (chunks/jobs/files cascade). Best-effort MinIO cleanup."""
    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, product_key
                    FROM kb_documents
                    WHERE id = :id
                    """
                ),
                {"id": document_id},
            )
        )
        if not row:
            raise KeyError(f"kb document not found: {document_id}")

        file_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT storage_ref FROM kb_source_files WHERE document_id = :id
                    """
                ),
                {"id": document_id},
            )
        )
        storage_refs = [r["storage_ref"] for r in file_rows if r.get("storage_ref")]

        product_key = row.get("product_key")
        faq_deleted = 0
        if product_key:
            result = conn.execute(
                text("DELETE FROM faq_pairs WHERE id LIKE :prefix"),
                {"prefix": f"faq-{product_key}-%"},
            )
            faq_deleted = int(result.rowcount or 0)

        conn.execute(text("DELETE FROM kb_documents WHERE id = :id"), {"id": document_id})

    minio_removed = _kb_delete_minio_refs(storage_refs)
    return {
        "deleted": True,
        "documentId": document_id,
        "faqsDeleted": faq_deleted,
        "minioObjectsRemoved": minio_removed,
    }


def purge_kb_documents(*, scope: str, confirm: bool) -> dict[str, Any]:
    """Hard-delete documents by scope. Requires confirm=True."""
    if not confirm:
        raise ValueError("confirm_required")
    if scope not in ("all", "uploads", "corpus"):
        raise ValueError("invalid_purge_scope")

    with engine.begin() as conn:
        if scope == "uploads":
            where = "product_key IS NULL"
        elif scope == "corpus":
            where = "product_key IS NOT NULL"
        else:
            where = "true"

        docs = _rows(
            conn.execute(text(f"SELECT id, product_key FROM kb_documents WHERE {where}"))
        )
        doc_ids = [d["id"] for d in docs]
        product_keys = sorted({d["product_key"] for d in docs if d.get("product_key")})

        storage_refs: list[str] = []
        if doc_ids:
            # Fetch MinIO refs before cascade delete.
            file_rows = _rows(
                conn.execute(
                    text(
                        """
                        SELECT storage_ref FROM kb_source_files
                        WHERE document_id = ANY(:ids)
                        """
                    ),
                    {"ids": doc_ids},
                )
            )
            storage_refs = [r["storage_ref"] for r in file_rows if r.get("storage_ref")]

        faqs_deleted = 0
        if scope == "all":
            result = conn.execute(text("DELETE FROM faq_pairs"))
            faqs_deleted = int(result.rowcount or 0)
        elif product_keys:
            for pk in product_keys:
                result = conn.execute(
                    text("DELETE FROM faq_pairs WHERE id LIKE :prefix"),
                    {"prefix": f"faq-{pk}-%"},
                )
                faqs_deleted += int(result.rowcount or 0)

        docs_deleted = 0
        if doc_ids:
            result = conn.execute(
                text("DELETE FROM kb_documents WHERE id = ANY(:ids)"),
                {"ids": doc_ids},
            )
            docs_deleted = int(result.rowcount or 0)

    minio_removed = _kb_delete_minio_refs(storage_refs)
    return {
        "scope": scope,
        "documentsDeleted": docs_deleted,
        "faqsDeleted": faqs_deleted,
        "minioObjectsRemoved": minio_removed,
        "documentIds": doc_ids,
    }


def ingest_kb_from_source_db(*, product: str | None = None) -> dict[str, Any]:
    """HTTP wrapper around scripts/ingest_source_db.run_ingest."""
    import sys
    from pathlib import Path

    scripts_dir = str(Path(__file__).resolve().parent / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from ingest_source_db import run_ingest  # type: ignore

    return run_ingest(product_key=product)


def create_kb_document_from_upload(
    *,
    filename: str,
    data: bytes,
    content_type: str,
    title: str | None,
    doc_type: str,
    chunk_size: int,
    overlap: int,
    index_now: bool,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Multipart upload → MinIO + kb_source_files (+ optional index job)."""
    import json

    import kb_ingest
    import storage as object_store

    if doc_type not in _KB_ALLOWED_TYPES:
        raise ValueError(f"invalid document type: {doc_type}")
    if not data:
        raise ValueError("empty upload")
    safe_name = Path(filename).name or "upload.txt"
    doc_id = f"kb-upload-{uuid.uuid4().hex[:12]}"
    display_title = (title or "").strip() or Path(safe_name).stem or doc_id
    tag_list = tags or []
    mime = content_type or "application/octet-stream"

    # Fail early on binary we cannot index when indexing is requested.
    if index_now:
        kb_ingest._decode_source_bytes(data, filename=safe_name, mime_type=mime)

    key = object_store.object_key(doc_id, safe_name)
    storage_ref = object_store.put_bytes(key, data, mime)
    file_id = f"file-{doc_id}"
    content_hash = kb_ingest.content_sha256(data)
    job_id: str | None = None

    with engine.begin() as conn:
        status = "indexing" if index_now else "draft"
        enabled = bool(index_now)
        conn.execute(
            text(
                """
                INSERT INTO kb_documents (
                  id, updated_by_user_id, type, version, status, enabled,
                  chunk_size, chunk_overlap, title, tags, embedding_model,
                  product_key, source_path, created_at, updated_at
                ) VALUES (
                  :id, :actor, :type, 'v1.0', :status, :enabled,
                  :chunk_size, :overlap, :title, CAST(:tags AS jsonb), NULL,
                  NULL, NULL, now(), now()
                )
                """
            ),
            {
                "id": doc_id,
                "actor": ACTOR_USER_ID,
                "type": doc_type,
                "status": status,
                "enabled": enabled,
                "chunk_size": chunk_size,
                "overlap": overlap,
                "title": display_title,
                "tags": json.dumps(tag_list),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO kb_source_files (
                  id, document_id, storage_ref, filename, mime_type, size_bytes, hash, created_at
                ) VALUES (
                  :id, :document_id, :storage_ref, :filename, :mime_type, :size_bytes, :hash, now()
                )
                """
            ),
            {
                "id": file_id,
                "document_id": doc_id,
                "storage_ref": storage_ref,
                "filename": safe_name,
                "mime_type": mime,
                "size_bytes": len(data),
                "hash": content_hash,
            },
        )
        if index_now:
            job_id = kb_ingest.enqueue_index_job(
                conn,
                document_id=doc_id,
                chunk_size=chunk_size,
                chunk_overlap=overlap,
            )

    doc = get_kb_document(doc_id)
    assert doc is not None
    return {"document": doc, "jobId": job_id}


def create_kb_document_version(
    document_id: str,
    *,
    filename: str,
    data: bytes,
    content_type: str,
) -> dict[str, Any]:
    """New version upload → MinIO + new kb_source_files row + reindex job."""
    import kb_ingest
    import storage as object_store

    if not data:
        raise ValueError("empty upload")
    safe_name = Path(filename).name or "upload.txt"
    mime = content_type or "application/octet-stream"
    kb_ingest._decode_source_bytes(data, filename=safe_name, mime_type=mime)

    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, version, chunk_size, chunk_overlap
                    FROM kb_documents WHERE id = :id
                    """
                ),
                {"id": document_id},
            )
        )
        if not row:
            raise KeyError(f"kb document not found: {document_id}")

        new_version = _bump_kb_version(row.get("version"))
        # Prefer stable object names per version to retain prior objects.
        object_name = f"{Path(safe_name).stem}-{new_version}{Path(safe_name).suffix or '.txt'}"
        key = object_store.object_key(document_id, object_name)
        storage_ref = object_store.put_bytes(key, data, mime)
        file_id = f"file-{document_id}-{uuid.uuid4().hex[:8]}"
        conn.execute(
            text(
                """
                INSERT INTO kb_source_files (
                  id, document_id, storage_ref, filename, mime_type, size_bytes, hash, created_at
                ) VALUES (
                  :id, :document_id, :storage_ref, :filename, :mime_type, :size_bytes, :hash, now()
                )
                """
            ),
            {
                "id": file_id,
                "document_id": document_id,
                "storage_ref": storage_ref,
                "filename": safe_name,
                "mime_type": mime,
                "size_bytes": len(data),
                "hash": kb_ingest.content_sha256(data),
            },
        )
        conn.execute(
            text(
                """
                UPDATE kb_documents
                SET version = :version, status = 'indexing', updated_at = now(),
                    updated_by_user_id = :actor
                WHERE id = :id
                """
            ),
            {"id": document_id, "version": new_version, "actor": ACTOR_USER_ID},
        )
        conn.execute(
            text(
                """
                DELETE FROM kb_index_jobs
                WHERE document_id = :id AND status IN ('queued', 'failed')
                """
            ),
            {"id": document_id},
        )
        job_id = kb_ingest.enqueue_index_job(
            conn,
            document_id=document_id,
            chunk_size=row.get("chunk_size"),
            chunk_overlap=row.get("chunk_overlap"),
        )

    doc = get_kb_document(document_id)
    assert doc is not None
    return {"document": doc, "jobId": job_id}


def backfill_kb_sources_to_minio(*, limit: int | None = None) -> dict[str, Any]:
    """Optional: copy disk source_path originals into MinIO + kb_source_files."""
    import kb_ingest
    import storage as object_store

    copied = 0
    skipped = 0
    errors: list[str] = []
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT d.id, d.source_path
                    FROM kb_documents d
                    WHERE d.source_path IS NOT NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM kb_source_files f WHERE f.document_id = d.id
                      )
                    ORDER BY d.id
                    """
                )
            )
        )
        if limit is not None:
            rows = rows[:limit]
        for row in rows:
            path = Path(row["source_path"])
            if not path.is_file():
                skipped += 1
                errors.append(f"{row['id']}: missing {path}")
                continue
            try:
                data = path.read_bytes()
                mime = "text/markdown" if path.suffix.lower() == ".md" else "text/plain"
                key = object_store.object_key(row["id"], path.name)
                storage_ref = object_store.put_bytes(key, data, mime)
                # Savepoint per row: one bad insert must not abort the whole backfill txn.
                with conn.begin_nested():
                    conn.execute(
                        text(
                            """
                            INSERT INTO kb_source_files (
                              id, document_id, storage_ref, filename, mime_type, size_bytes, hash, created_at
                            ) VALUES (
                              :id, :document_id, :storage_ref, :filename, :mime_type, :size_bytes, :hash, now()
                            )
                            """
                        ),
                        {
                            "id": f"file-{row['id']}",
                            "document_id": row["id"],
                            "storage_ref": storage_ref,
                            "filename": path.name,
                            "mime_type": mime,
                            "size_bytes": len(data),
                            "hash": kb_ingest.content_sha256(data),
                        },
                    )
                copied += 1
            except Exception as exc:
                errors.append(f"{row['id']}: {exc}")
    return {"copied": copied, "skipped": skipped, "errors": errors}


# ---------------------------------------------------------------------------
# Knowledge Base — Phase KB-3 FAQs + Analytics Gaps
# ---------------------------------------------------------------------------


def _vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def _embed_faq_pair(question: str, answer: str) -> str | None:
    """Best-effort FAQ embedding for hybrid retrieve. Returns vector literal or None."""
    try:
        import azure_openai

        blob = f"Q: {question.strip()}\nA: {answer.strip()}"
        vec = azure_openai.embed_texts([blob])[0]
        return _vector_literal(vec)
    except Exception:
        return None


def _serialize_kb_faq(row: dict[str, Any]) -> dict[str, Any]:
    updated = row.get("updated_at") or ""
    return {
        "id": row["id"],
        "question": row.get("question") or "",
        "answer": row.get("answer") or "",
        "intent": row.get("intent") or "other",
        "enabled": bool(row.get("enabled")),
        "updatedAt": updated if isinstance(updated, str) else (updated.isoformat() if updated else ""),
        "linkedDocId": row.get("linked_document_id"),
    }


def list_kb_faqs() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, question, answer, intent, enabled,
                           linked_document_id, updated_at
                    FROM faq_pairs
                    ORDER BY updated_at DESC, id ASC
                    """
                )
            )
        )
    return [_serialize_kb_faq(r) for r in rows]


def get_kb_faq(faq_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, question, answer, intent, enabled,
                           linked_document_id, updated_at
                    FROM faq_pairs
                    WHERE id = :id
                    """
                ),
                {"id": faq_id},
            )
        )
    return _serialize_kb_faq(row) if row else None


def create_kb_faq(payload: dict[str, Any]) -> dict[str, Any]:
    question = (payload.get("question") or "").strip()
    answer = (payload.get("answer") or "").strip()
    intent = (payload.get("intent") or "other").strip() or "other"
    if not question or not answer:
        raise ValueError("question and answer are required")

    linked = payload.get("linkedDocId")
    if linked:
        with engine.connect() as conn:
            doc = _one(
                conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": linked})
            )
            if not doc:
                raise ValueError(f"linked document not found: {linked}")

    faq_id = f"faq-{uuid.uuid4().hex[:12]}"
    embedding = _embed_faq_pair(question, answer)
    gap_id = payload.get("gapId")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO faq_pairs (
                  id, linked_document_id, intent, question, answer, enabled,
                  embedding, created_at, updated_at
                ) VALUES (
                  :id, :linked, :intent, :question, :answer, :enabled,
                  CAST(:embedding AS vector), now(), now()
                )
                """
            ),
            {
                "id": faq_id,
                "linked": linked,
                "intent": intent,
                "question": question,
                "answer": answer,
                "enabled": bool(payload.get("enabled", True)),
                "embedding": embedding,
            },
        )
        if gap_id:
            _link_kb_gap_conn(conn, gap_id, faq_pair_id=faq_id)

    row = get_kb_faq(faq_id)
    assert row is not None
    return row


def patch_kb_faq(faq_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id, question, answer, intent, enabled, linked_document_id
                    FROM faq_pairs WHERE id = :id
                    """
                ),
                {"id": faq_id},
            )
        )
        if not existing:
            raise KeyError(f"faq not found: {faq_id}")

        question = existing["question"]
        answer = existing["answer"]
        sets: list[str] = []
        params: dict[str, Any] = {"id": faq_id}
        reembed = False

        if "question" in payload and payload["question"] is not None:
            question = str(payload["question"]).strip()
            if not question:
                raise ValueError("question cannot be empty")
            sets.append("question = :question")
            params["question"] = question
            reembed = True
        if "answer" in payload and payload["answer"] is not None:
            answer = str(payload["answer"]).strip()
            if not answer:
                raise ValueError("answer cannot be empty")
            sets.append("answer = :answer")
            params["answer"] = answer
            reembed = True
        if "intent" in payload and payload["intent"] is not None:
            sets.append("intent = :intent")
            params["intent"] = str(payload["intent"]).strip() or "other"
        if "enabled" in payload and payload["enabled"] is not None:
            sets.append("enabled = :enabled")
            params["enabled"] = bool(payload["enabled"])
        if "linkedDocId" in payload:
            linked = payload["linkedDocId"]
            if linked:
                doc = _one(
                    conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": linked})
                )
                if not doc:
                    raise ValueError(f"linked document not found: {linked}")
            sets.append("linked_document_id = :linked")
            params["linked"] = linked

        if reembed:
            emb = _embed_faq_pair(question, answer)
            sets.append("embedding = CAST(:embedding AS vector)")
            params["embedding"] = emb

        if sets:
            sets.append("updated_at = now()")
            conn.execute(
                text(f"UPDATE faq_pairs SET {', '.join(sets)} WHERE id = :id"),
                params,
            )

    row = get_kb_faq(faq_id)
    assert row is not None
    return row


def delete_kb_faq(faq_id: str) -> None:
    """Delete an FAQ pair. analytics_kb_gap_links.faq_pair_id is ON DELETE SET NULL."""
    with engine.begin() as conn:
        existing = _one(
            conn.execute(text("SELECT id FROM faq_pairs WHERE id = :id"), {"id": faq_id})
        )
        if not existing:
            raise KeyError(f"faq not found: {faq_id}")
        conn.execute(text("DELETE FROM faq_pairs WHERE id = :id"), {"id": faq_id})


def _normalize_suggested_fix(value: str | None) -> str:
    v = (value or "kb").strip().lower()
    if v in ("kb", "prompt", "both"):
        return v
    return "kb"


def list_kb_gaps() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      uq.id,
                      uq.question,
                      uq.hit_count,
                      uq.last_seen_at,
                      coalesce(uq.top_intent, 'other') AS top_intent,
                      uq.suggested_fix_type,
                      g.kb_document_id,
                      g.faq_pair_id,
                      g.prompt_version_id
                    FROM unanswered_questions uq
                    LEFT JOIN LATERAL (
                      SELECT kb_document_id, faq_pair_id, prompt_version_id
                      FROM analytics_kb_gap_links
                      WHERE unanswered_question_id = uq.id
                      ORDER BY created_at DESC
                      LIMIT 1
                    ) g ON true
                    WHERE uq.tenant_id = :tenant_id
                    ORDER BY uq.hit_count DESC NULLS LAST, uq.id
                    """
                ),
                {"tenant_id": TENANT_ID},
            )
        )
    out: list[dict[str, Any]] = []
    for r in rows:
        has_doc = bool(r.get("kb_document_id"))
        has_faq = bool(r.get("faq_pair_id"))
        has_prompt = bool(r.get("prompt_version_id"))
        last = r.get("last_seen_at") or ""
        out.append(
            {
                "id": r["id"],
                "text": r.get("question") or "",
                "hits": int(r.get("hit_count") or 0),
                "lastSeen": last if isinstance(last, str) else (last.isoformat() if last else ""),
                "topIntent": r.get("top_intent") or "other",
                "hasKbDoc": has_doc,
                "hasFaq": has_faq,
                "resolved": has_doc or has_faq or has_prompt,
                "suggestedFix": _normalize_suggested_fix(r.get("suggested_fix_type")),
                "linkedDocumentId": r.get("kb_document_id"),
                "linkedFaqId": r.get("faq_pair_id"),
                "linkedPromptVersionId": r.get("prompt_version_id"),
            }
        )
    return out


def _link_kb_gap_conn(
    conn: Any,
    gap_id: str,
    *,
    faq_pair_id: str | None = None,
    kb_document_id: str | None = None,
    prompt_version_id: str | None = None,
) -> None:
    targets = [
        ("faqPairId", faq_pair_id),
        ("kbDocumentId", kb_document_id),
        ("promptVersionId", prompt_version_id),
    ]
    provided = [(k, v) for k, v in targets if v]
    if not provided:
        raise ValueError("faqPairId_kbDocumentId_or_promptVersionId_required")
    if len(provided) > 1:
        raise ValueError("gap_link_exactly_one_target")

    gap = _one(
        conn.execute(
            text(
                """
                SELECT id FROM unanswered_questions
                WHERE id = :id AND tenant_id = :tenant_id
                """
            ),
            {"id": gap_id, "tenant_id": TENANT_ID},
        )
    )
    if not gap:
        raise KeyError(f"gap not found: {gap_id}")

    if faq_pair_id:
        faq = _one(
            conn.execute(text("SELECT id FROM faq_pairs WHERE id = :id"), {"id": faq_pair_id})
        )
        if not faq:
            raise KeyError(f"faq not found: {faq_pair_id}")
    if kb_document_id:
        doc = _one(
            conn.execute(text("SELECT id FROM kb_documents WHERE id = :id"), {"id": kb_document_id})
        )
        if not doc:
            raise KeyError(f"document not found: {kb_document_id}")
    if prompt_version_id:
        pv = _one(
            conn.execute(
                text("SELECT id FROM prompt_versions WHERE id = :id"),
                {"id": prompt_version_id},
            )
        )
        if not pv:
            raise KeyError(f"prompt_version_not_found: {prompt_version_id}")

    existing = _one(
        conn.execute(
            text(
                """
                SELECT id, faq_pair_id, kb_document_id, prompt_version_id
                FROM analytics_kb_gap_links
                WHERE unanswered_question_id = :id
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"id": gap_id},
        )
    )
    if existing:
        # Replace link targets — exactly one of the three columns is set.
        conn.execute(
            text(
                """
                UPDATE analytics_kb_gap_links
                SET faq_pair_id = :faq_pair_id,
                    kb_document_id = :kb_document_id,
                    prompt_version_id = :prompt_version_id
                WHERE id = :id
                """
            ),
            {
                "id": existing["id"],
                "faq_pair_id": faq_pair_id,
                "kb_document_id": kb_document_id,
                "prompt_version_id": prompt_version_id,
            },
        )
        return

    conn.execute(
        text(
            """
            INSERT INTO analytics_kb_gap_links (
              id, unanswered_question_id, kb_document_id, faq_pair_id,
              prompt_version_id, routing_rule_id, created_at
            ) VALUES (
              :id, :gap_id, :kb_document_id, :faq_pair_id,
              :prompt_version_id, NULL, now()
            )
            """
        ),
        {
            "id": f"gap-link-{uuid.uuid4().hex[:10]}",
            "gap_id": gap_id,
            "kb_document_id": kb_document_id,
            "faq_pair_id": faq_pair_id,
            "prompt_version_id": prompt_version_id,
        },
    )


def link_kb_gap(gap_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        _link_kb_gap_conn(
            conn,
            gap_id,
            faq_pair_id=payload.get("faqPairId"),
            kb_document_id=payload.get("kbDocumentId"),
            prompt_version_id=payload.get("promptVersionId"),
        )
    gaps = {g["id"]: g for g in list_kb_gaps()}
    if gap_id not in gaps:
        raise KeyError(f"gap not found: {gap_id}")
    return gaps[gap_id]


# ---------------------------------------------------------------------------
# Sandbox (PS-3) — scenarios + runs
# ---------------------------------------------------------------------------

_VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})


def _sandbox_persona_from_sim(raw: Any) -> dict[str, Any]:
    data = _as_dict(raw)
    overdue = data.get("overdue", 0)
    try:
        overdue_f = float(overdue) if overdue is not None else 0.0
    except (TypeError, ValueError):
        overdue_f = 0.0
    dpd = data.get("dpd", 0)
    try:
        dpd_i = int(dpd) if dpd is not None else 0
    except (TypeError, ValueError):
        dpd_i = 0
    return {
        "name": str(data.get("name") or "Customer"),
        "phoneLast4": str(data.get("phoneLast4") or "0000"),
        "product": str(data.get("product") or "—"),
        "dpd": dpd_i,
        "overdue": overdue_f,
        "mood": str(data.get("mood") or "neutral"),
        "language": str(data.get("language") or "English"),
        "accountNo": data.get("accountNo"),
        "dueDate": data.get("dueDate"),
        "bankName": data.get("bankName"),
        "lastPayment": data.get("lastPayment"),
    }


def _sandbox_scripted_turns(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        customer = item.get("customer") or item.get("text")
        if not customer:
            continue
        turn: dict[str, Any] = {"customer": str(customer)}
        if item.get("expectedIntent") is not None:
            turn["expectedIntent"] = str(item["expectedIntent"])
        sent = item.get("expectedSentiment")
        if isinstance(sent, (int, float)):
            turn["expectedSentiment"] = float(sent)
        out.append(turn)
    return out


def _map_sandbox_scenario(r: dict[str, Any]) -> dict[str, Any]:
    sim = _as_dict(r.get("sim_persona"))
    difficulty = str(sim.get("difficulty") or "medium").lower()
    if difficulty not in _VALID_DIFFICULTIES:
        difficulty = "medium"
    intents_raw = sim.get("intents") or []
    intents = [str(x) for x in intents_raw] if isinstance(intents_raw, list) else []
    persona = _sandbox_persona_from_sim(sim)
    return {
        "id": r["id"],
        "title": str(sim.get("title") or r.get("name") or r["id"]),
        "summary": str(sim.get("summary") or ""),
        "difficulty": difficulty,
        "intents": intents,
        "persona": {
            "name": persona["name"],
            "phoneLast4": persona["phoneLast4"],
            "product": persona["product"],
            "dpd": persona["dpd"],
            "overdue": persona["overdue"],
            "mood": persona["mood"],
            "language": persona["language"],
        },
        "openingBot": str(sim.get("openingBot") or ""),
        "turns": _sandbox_scripted_turns(r.get("turns")),
    }


def list_sandbox_scenarios() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, sim_persona, turns, created_at
                    FROM sandbox_scenarios
                    ORDER BY created_at ASC, id ASC
                    """
                )
            )
        )
        return [_map_sandbox_scenario(r) for r in rows]


def get_sandbox_scenario(scenario_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name, sim_persona, turns, created_at
                    FROM sandbox_scenarios
                    WHERE id = :id
                    """
                ),
                {"id": scenario_id},
            )
        )
        if r is None:
            return None
        mapped = _map_sandbox_scenario(r)
        # Runner needs full persona extras (accountNo / dueDate / bankName).
        sim = _as_dict(r.get("sim_persona"))
        mapped["persona"] = _sandbox_persona_from_sim(sim)
        mapped["name"] = r.get("name") or mapped["title"]
        return mapped


def _chunk_meta_grouped(conn: Any, chunk_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = [c for c in chunk_ids if c and not str(c).startswith("faq-")]
    if not ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT c.id, c.heading, c.text, d.title AS doc_title
                FROM kb_chunks c
                JOIN kb_documents d ON d.id = c.document_id
                WHERE c.id = ANY(:ids)
                """
            ),
            {"ids": ids},
        )
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        snippet = (r.get("text") or "")[:160]
        out[r["id"]] = {
            "chunkId": r["id"],
            "docTitle": r.get("doc_title") or "Document",
            "heading": r.get("heading") or "",
            "snippet": snippet,
        }
    return out


def _map_sandbox_turn(r: dict[str, Any], chunk_meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    speaker = str(r.get("speaker") or "bot")
    role = speaker if speaker in ("bot", "customer", "system") else "bot"
    raw_ids = r.get("retrieved_chunk_ids")
    if isinstance(raw_ids, str):
        try:
            raw_ids = json.loads(raw_ids)
        except json.JSONDecodeError:
            raw_ids = []
    if not isinstance(raw_ids, list):
        raw_ids = []
    chunk_ids = [str(x) for x in raw_ids if x]

    raw_flags = r.get("guardrail_flags")
    if isinstance(raw_flags, str):
        try:
            raw_flags = json.loads(raw_flags)
        except json.JSONDecodeError:
            raw_flags = []
    if not isinstance(raw_flags, list):
        raw_flags = []
    flags = [str(x) for x in raw_flags if x]

    grounded: list[dict[str, Any]] = []
    for cid in chunk_ids:
        meta = chunk_meta.get(cid)
        if meta:
            grounded.append(
                {
                    "chunkId": cid,
                    "docTitle": meta["docTitle"],
                    "heading": meta.get("heading") or "",
                    "snippet": meta.get("snippet") or "",
                }
            )
        else:
            grounded.append(
                {
                    "chunkId": cid,
                    "docTitle": cid,
                    "heading": "",
                    "snippet": "",
                }
            )

    created = r.get("created_at")
    if isinstance(created, datetime):
        ts_ms = int(created.timestamp() * 1000)
        created_iso = created.isoformat()
    elif isinstance(created, str):
        created_iso = created
        try:
            ts_ms = int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp() * 1000)
        except ValueError:
            ts_ms = 0
    else:
        created_iso = None
        ts_ms = 0

    sentiment_label = r.get("sentiment_label")
    sentiment_score: float | None = None
    if sentiment_label == "positive":
        sentiment_score = 0.4
    elif sentiment_label == "negative":
        sentiment_score = -0.4
    elif sentiment_label == "neutral":
        sentiment_score = 0.0

    system_kind = None
    if role == "system":
        text_l = str(r.get("text") or "").lower()
        if "halt" in text_l or "escalat" in text_l or "fail" in text_l:
            system_kind = "warn"
        elif "new session" in text_l:
            system_kind = "info"
        else:
            system_kind = "info"

    return {
        "id": r["id"],
        "turnIndex": int(r["turn_index"]),
        "role": role,
        "text": r.get("text") or "",
        "detectedIntent": r.get("detected_intent"),
        "intent": r.get("detected_intent"),
        "sentiment": sentiment_score,
        "sentimentLabel": sentiment_label,
        "chunkIds": chunk_ids,
        "retrievedChunkIds": chunk_ids,
        "groundedIn": grounded,
        "guardrailFlags": flags,
        "latencyMs": r.get("latency_ms"),
        "tokens": r.get("token_count"),
        "tokenCount": r.get("token_count"),
        "ts": ts_ms,
        "createdAt": created_iso,
        "systemKind": system_kind,
    }


def get_sandbox_run(run_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      id, scenario_id, deployment_id, prompt_version_id, kb_snapshot_id,
                      started_by_user_id, status, aggregate_latency_ms, aggregate_tokens,
                      created_at, updated_at
                    FROM sandbox_runs
                    WHERE id = :id
                    """
                ),
                {"id": run_id},
            )
        )
        if r is None:
            raise KeyError(f"sandbox_run_not_found: {run_id}")

        turn_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      id, run_id, turn_index, speaker, text,
                      detected_intent, sentiment_label, retrieved_chunk_ids,
                      guardrail_flags, latency_ms, token_count, created_at
                    FROM sandbox_run_turns
                    WHERE run_id = :id
                    ORDER BY turn_index ASC
                    """
                ),
                {"id": run_id},
            )
        )
        all_chunk_ids: list[str] = []
        for tr in turn_rows:
            raw_ids = tr.get("retrieved_chunk_ids")
            if isinstance(raw_ids, str):
                try:
                    raw_ids = json.loads(raw_ids)
                except json.JSONDecodeError:
                    raw_ids = []
            if isinstance(raw_ids, list):
                all_chunk_ids.extend(str(x) for x in raw_ids if x)
        chunk_meta = _chunk_meta_grouped(conn, all_chunk_ids)
        turns = [_map_sandbox_turn(tr, chunk_meta) for tr in turn_rows]

        created = r.get("created_at")
        updated = r.get("updated_at")
        return {
            "id": r["id"],
            "scenarioId": r.get("scenario_id"),
            "deploymentId": r.get("deployment_id"),
            "promptVersionId": r.get("prompt_version_id"),
            "kbSnapshotId": r.get("kb_snapshot_id"),
            "startedByUserId": r.get("started_by_user_id"),
            "status": r.get("status") or "running",
            "aggregateLatencyMs": r.get("aggregate_latency_ms"),
            "aggregateTokens": r.get("aggregate_tokens"),
            "createdAt": created.isoformat() if isinstance(created, datetime) else created,
            "updatedAt": updated.isoformat() if isinstance(updated, datetime) else updated,
            "turns": turns,
        }


# ---------------------------------------------------------------------------
# Billing & Usage Analytics — metered Azure only (no estimate catalog lines)
# ---------------------------------------------------------------------------

_BILLING_PERIODS = {"mtd", "7d", "30d", "quarter"}
_BILLING_ENVS = {"production", "sandbox"}
_METERED_SERVICE_IDS = ("llm_chat", "llm_embed", "stt_az", "tts_az")


def _fnum(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _billing_as_of(conn) -> date:
    """Prefer calendar today so MTD/forecast stay current even with sparse events."""
    return date.today()


def _billing_window(period: str, as_of: date) -> tuple[date, date]:
    if period == "mtd":
        return date(as_of.year, as_of.month, 1), as_of
    if period == "7d":
        return as_of - timedelta(days=6), as_of
    if period == "30d":
        return as_of - timedelta(days=29), as_of
    if period == "quarter":
        return as_of - timedelta(days=89), as_of
    raise ValueError(f"invalid_period: {period}")


def _billing_prev_window(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start, prev_end


def _month_label(ym: str) -> str:
    try:
        y, m = ym.split("-")
        dt = date(int(y), int(m), 1)
        return dt.strftime("%b %Y")
    except Exception:
        return ym


def _parse_channels(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
        if raw.strip():
            return [raw.strip()]
    return []


def _daily_series(
    conn,
    *,
    start: date,
    end: date,
    env: str,
    tenant_id: str | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"start": start, "end": end, "env": env}
    tenant_sql = ""
    if tenant_id and tenant_id != "all":
        tenant_sql = "AND tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    rows = _rows(
        conn.execute(
            text(
                f"""
                SELECT to_char(usage_date, 'YYYY-MM-DD') AS d,
                       service_id,
                       coalesce(sum(cost_inr), 0) AS cost
                FROM billing_usage_daily
                WHERE environment = :env
                  AND usage_date >= :start
                  AND usage_date <= :end
                  AND service_id IN ('llm_chat', 'llm_embed', 'stt_az', 'tts_az')
                  {tenant_sql}
                GROUP BY usage_date, service_id
                ORDER BY usage_date, service_id
                """
            ),
            params,
        )
    )
    by_date: dict[str, dict[str, float]] = {}
    for r in rows:
        d = r["d"]
        by_date.setdefault(d, {})[r["service_id"]] = _fnum(r["cost"])

    out: list[dict[str, Any]] = []
    cur = start
    while cur <= end:
        key = cur.isoformat()
        out.append({"date": key, "values": by_date.get(key, {})})
        cur += timedelta(days=1)
    return out


def _sum_daily(daily: list[dict[str, Any]], service_id: str | None = None) -> float:
    total = 0.0
    for d in daily:
        values = d.get("values") or {}
        if service_id:
            total += _fnum(values.get(service_id, 0))
        else:
            total += sum(_fnum(v) for v in values.values())
    return total


def _forecast_eom(daily: list[dict[str, Any]], as_of: date) -> float:
    """Project month-end spend from current burn when the window is MTD-shaped."""
    if not daily:
        return 0.0
    spend = _sum_daily(daily)
    month_start = date(as_of.year, as_of.month, 1).isoformat()
    if daily[0]["date"] != month_start:
        return round(spend)
    if as_of.month == 12:
        days_in_month = 31
    else:
        days_in_month = (date(as_of.year, as_of.month + 1, 1) - timedelta(days=1)).day
    per_day = spend / max(1, as_of.day)
    return round(per_day * days_in_month)


def billing_overview(
    period: str = "mtd",
    tenant_id: str = "all",
    env: str = "production",
) -> dict[str, Any]:
    if period not in _BILLING_PERIODS:
        raise ValueError(f"invalid_period: {period}")
    if env not in _BILLING_ENVS:
        raise ValueError(f"invalid_env: {env}")

    with engine.connect() as conn:
        as_of = _billing_as_of(conn)
        start, end = _billing_window(period, as_of)
        prev_start, prev_end = _billing_prev_window(start, end)
        month_key = as_of.strftime("%Y-%m")

        if tenant_id != "all":
            exists = conn.execute(
                text("SELECT 1 FROM tenants WHERE id = :id"),
                {"id": tenant_id},
            ).scalar()
            if not exists:
                raise ValueError(f"unknown_tenant: {tenant_id}")

        services = [
            {
                "id": r["id"],
                "name": r["name"],
                "provider": r.get("provider") or "Unknown",
                "category": r.get("category") or "Infra",
                "unit": r["unit"],
                "unitCostInr": _fnum(r["unit_cost_inr"]),
                "color": r.get("color") or "#64748b",
            }
            for r in _rows(
                conn.execute(
                    text(
                        """
                        SELECT id, name, provider, category, unit, unit_cost_inr, color
                        FROM billing_services
                        WHERE id IN ('llm_chat', 'llm_embed', 'stt_az', 'tts_az')
                        ORDER BY
                          CASE id
                            WHEN 'llm_chat' THEN 1
                            WHEN 'llm_embed' THEN 2
                            WHEN 'stt_az' THEN 3
                            WHEN 'tts_az' THEN 4
                            ELSE 5
                          END
                        """
                    )
                )
            )
        ]

        # Live interaction metrics (not seed billing_resolved_calls)
        ix_params: dict[str, Any] = {"start": start, "end": end}
        ix_tenant_sql = ""
        if tenant_id != "all":
            ix_tenant_sql = "AND tenant_id = :tenant_id"
            ix_params["tenant_id"] = tenant_id
        ix_cur = conn.execute(
            text(
                f"""
                SELECT
                  count(*)::int AS calls,
                  count(*) FILTER (WHERE coalesce(query_resolved, false))::int AS resolved,
                  coalesce(
                    avg(duration_sec) FILTER (WHERE duration_sec IS NOT NULL AND duration_sec > 0),
                    0
                  )::float AS aht
                FROM interactions
                WHERE (started_at AT TIME ZONE 'UTC')::date >= :start
                  AND (started_at AT TIME ZONE 'UTC')::date <= :end
                  {ix_tenant_sql}
                """
            ),
            ix_params,
        ).mappings().first()
        ix_prev_params: dict[str, Any] = {"start": prev_start, "end": prev_end}
        if tenant_id != "all":
            ix_prev_params["tenant_id"] = tenant_id
        ix_prev = conn.execute(
            text(
                f"""
                SELECT
                  count(*) FILTER (WHERE coalesce(query_resolved, false))::int AS resolved
                FROM interactions
                WHERE (started_at AT TIME ZONE 'UTC')::date >= :start
                  AND (started_at AT TIME ZONE 'UTC')::date <= :end
                  {ix_tenant_sql}
                """
            ),
            ix_prev_params,
        ).mappings().first()

        tenant_ix = {
            r["tenant_id"]: r
            for r in _rows(
                conn.execute(
                    text(
                        """
                        SELECT tenant_id,
                               count(*)::int AS calls,
                               count(*) FILTER (
                                 WHERE coalesce(query_resolved, false)
                               )::int AS resolved,
                               coalesce(
                                 avg(duration_sec) FILTER (
                                   WHERE duration_sec IS NOT NULL AND duration_sec > 0
                                 ),
                                 0
                               )::float AS aht
                        FROM interactions
                        WHERE (started_at AT TIME ZONE 'UTC')::date >= :start
                          AND (started_at AT TIME ZONE 'UTC')::date <= :end
                        GROUP BY tenant_id
                        """
                    ),
                    {"start": start, "end": end},
                )
            )
        }

        # Tenants that have metered spend or live interactions in-window
        tenant_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT t.id, t.name,
                           coalesce(t.budget_inr, 0) AS budget
                    FROM tenants t
                    WHERE t.id IN (
                      SELECT DISTINCT tenant_id FROM billing_usage_daily
                      WHERE service_id IN ('llm_chat','llm_embed','stt_az','tts_az')
                      UNION
                      SELECT DISTINCT tenant_id FROM interactions
                      WHERE (started_at AT TIME ZONE 'UTC')::date >= :start
                        AND (started_at AT TIME ZONE 'UTC')::date <= :end
                    )
                    OR t.id = :primary
                    ORDER BY t.name
                    """
                ),
                {"start": start, "end": end, "primary": TENANT_ID},
            )
        )
        tenants = []
        for r in tenant_rows:
            ix = tenant_ix.get(r["id"], {})
            resolved_n = int(ix.get("resolved") or 0)
            aht = int(round(_fnum(ix.get("aht") or 0)))
            tenants.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "resolvedCalls": resolved_n,
                    "ahtSec": aht,
                    "budgetInr": _fnum(r["budget"]),
                    "spendShare": 0.0,
                }
            )

        daily = _daily_series(conn, start=start, end=end, env=env, tenant_id=tenant_id)
        previous = _daily_series(
            conn, start=prev_start, end=prev_end, env=env, tenant_id=tenant_id
        )
        spend = _sum_daily(daily)
        spend_prev = _sum_daily(previous)

        resolved = int((ix_cur or {}).get("resolved") or 0)
        resolved_prev = int((ix_prev or {}).get("resolved") or 0)
        cost_per_call = (spend / resolved) if resolved > 0 else 0.0
        cost_per_call_prev = (spend_prev / resolved_prev) if resolved_prev > 0 else 0.0
        forecast = _forecast_eom(daily, as_of)

        mtd_start = date(as_of.year, as_of.month, 1)

        # MTD spend by env (metered only)
        spend_by_env: dict[str, float] = {}
        for e in ("production", "sandbox"):
            params: dict[str, Any] = {
                "env": e,
                "start": mtd_start,
                "end": as_of,
            }
            tenant_sql = ""
            if tenant_id != "all":
                tenant_sql = "AND tenant_id = :tenant_id"
                params["tenant_id"] = tenant_id
            spend_by_env[e] = _fnum(
                conn.execute(
                    text(
                        f"""
                        SELECT coalesce(sum(cost_inr), 0)
                        FROM billing_usage_daily
                        WHERE environment = :env
                          AND usage_date >= :start
                          AND usage_date <= :end
                          AND service_id IN ('llm_chat','llm_embed','stt_az','tts_az')
                          {tenant_sql}
                        """
                    ),
                    params,
                ).scalar()
            )

        budget_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, environment, month, amount_inr
                    FROM budgets
                    WHERE tenant_id IS NULL
                      AND month = :month
                    ORDER BY environment
                    """
                ),
                {"month": month_key},
            )
        )
        # Fallback: latest month if current month missing
        if not budget_rows:
            budget_rows = _rows(
                conn.execute(
                    text(
                        """
                        SELECT id, environment, month, amount_inr
                        FROM budgets
                        WHERE tenant_id IS NULL
                        ORDER BY month DESC, environment
                        LIMIT 2
                        """
                    )
                )
            )

        budgets: list[dict[str, Any]] = []
        budget_cap = 0.0
        for b in budget_rows:
            rules = [
                {
                    "id": rr["id"],
                    "threshold": _fnum(rr["threshold_pct"]),
                    "channels": _parse_channels(rr.get("channels"))
                    or ([rr["action_channel"]] if rr.get("action_channel") else []),
                    "action": rr.get("action") or "Notify",
                    "severity": rr.get("severity") or "warn",
                }
                for rr in _rows(
                    conn.execute(
                        text(
                            """
                            SELECT id, threshold_pct, action_channel, severity, action, channels
                            FROM budget_rules
                            WHERE budget_id = :bid
                            ORDER BY threshold_pct
                            """
                        ),
                        {"bid": b["id"]},
                    )
                )
            ]
            cap = _fnum(b["amount_inr"])
            env_key = b["environment"]
            if env_key == env:
                budget_cap = cap
            budgets.append(
                {
                    "id": b["id"],
                    "env": env_key,
                    "month": b["month"],
                    "monthlyCapInr": cap,
                    "rules": rules,
                }
            )

        alerts = []
        for a in _rows(
            conn.execute(
                text(
                    """
                    SELECT e.id, e.triggered_at, e.message, e.budget_rule_id,
                           b.environment
                    FROM budget_alert_events e
                    JOIN budget_rules r ON r.id = e.budget_rule_id
                    JOIN budgets b ON b.id = r.budget_id
                    ORDER BY e.triggered_at DESC
                    LIMIT 10
                    """
                )
            )
        ):
            when = a["triggered_at"]
            if isinstance(when, datetime):
                when_s = when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
            else:
                when_s = str(when)
            alerts.append(
                {
                    "id": a["id"],
                    "when": when_s,
                    "ruleId": a["budget_rule_id"],
                    "env": a["environment"],
                    "message": a.get("message") or "",
                }
            )

        invoices = []
        for inv in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, invoice_month, status, total_inr, issued_at
                    FROM invoices
                    WHERE environment = 'production'
                    ORDER BY invoice_month DESC
                    LIMIT 8
                    """
                )
            )
        ):
            issued = inv.get("issued_at")
            invoices.append(
                {
                    "id": inv["id"],
                    "month": _month_label(inv["invoice_month"])
                    + (" (in progress)" if inv["status"] == "draft" else ""),
                    "status": inv["status"],
                    "amountInr": _fnum(inv["total_inr"]),
                    "issuedAt": issued.isoformat() if isinstance(issued, date) else str(issued or ""),
                }
            )

        # Per-tenant breakdown for selected env + period (ignore tenant filter)
        tenant_spend_cur = {
            r["tenant_id"]: _fnum(r["cost"])
            for r in _rows(
                conn.execute(
                    text(
                        """
                        SELECT tenant_id, coalesce(sum(cost_inr), 0) AS cost
                        FROM billing_usage_daily
                        WHERE environment = :env
                          AND usage_date >= :start
                          AND usage_date <= :end
                          AND service_id IN ('llm_chat','llm_embed','stt_az','tts_az')
                        GROUP BY tenant_id
                        """
                    ),
                    {"env": env, "start": start, "end": end},
                )
            )
        }
        tenant_spend_prev = {
            r["tenant_id"]: _fnum(r["cost"])
            for r in _rows(
                conn.execute(
                    text(
                        """
                        SELECT tenant_id, coalesce(sum(cost_inr), 0) AS cost
                        FROM billing_usage_daily
                        WHERE environment = :env
                          AND usage_date >= :start
                          AND usage_date <= :end
                          AND service_id IN ('llm_chat','llm_embed','stt_az','tts_az')
                        GROUP BY tenant_id
                        """
                    ),
                    {"env": env, "start": prev_start, "end": prev_end},
                )
            )
        }
        tenant_breakdown = []
        for t in tenants:
            sp = tenant_spend_cur.get(t["id"], 0.0)
            sp_prev = tenant_spend_prev.get(t["id"], 0.0)
            calls = max(0, int(t["resolvedCalls"]))
            budget = t["budgetInr"]
            tenant_breakdown.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "resolvedCalls": calls,
                    "ahtSec": t["ahtSec"],
                    "budgetInr": budget,
                    "spend": sp,
                    "spendPrev": sp_prev,
                    "costPerCall": (sp / calls) if calls > 0 else 0.0,
                    "budgetPct": round((sp / budget) * 100, 1) if budget > 0 else 0.0,
                }
            )

        # service → tenant spend for drawer (current period + env)
        service_tenant: dict[str, dict[str, float]] = {}
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT service_id, tenant_id, coalesce(sum(cost_inr), 0) AS cost
                    FROM billing_usage_daily
                    WHERE environment = :env
                      AND usage_date >= :start
                      AND usage_date <= :end
                      AND service_id IN ('llm_chat','llm_embed','stt_az','tts_az')
                    GROUP BY service_id, tenant_id
                    """
                ),
                {"env": env, "start": start, "end": end},
            )
        ):
            service_tenant.setdefault(r["service_id"], {})[r["tenant_id"]] = _fnum(r["cost"])

        return {
            "asOf": as_of.isoformat(),
            "period": period,
            "env": env,
            "tenantId": tenant_id,
            "services": services,
            "tenants": tenants,
            "daily": daily,
            "previousDaily": previous,
            "spend": spend,
            "spendPrev": spend_prev,
            "forecast": forecast,
            "costPerCall": cost_per_call,
            "costPerCallPrev": cost_per_call_prev,
            "resolvedCalls": resolved,
            "budgetCap": budget_cap,
            "spendByEnv": spend_by_env,
            "budgets": budgets,
            "alerts": alerts,
            "invoices": invoices,
            "tenantBreakdown": tenant_breakdown,
            "serviceTenantSpend": service_tenant,
        }


def upsert_budget_rule(budget_id: str, payload: dict[str, Any], rule_id: str | None = None) -> dict[str, Any]:
    channels = [str(c).strip() for c in (payload.get("channels") or []) if str(c).strip()]
    if not channels:
        raise ValueError("channels_required")
    threshold = float(payload["threshold"])
    severity = payload.get("severity") or "warn"
    action = (payload.get("action") or "Notify").strip()
    if severity not in {"info", "warn", "critical"}:
        raise ValueError("invalid_severity")

    with engine.begin() as conn:
        budget = conn.execute(
            text("SELECT id FROM budgets WHERE id = :id"),
            {"id": budget_id},
        ).first()
        if not budget:
            raise LookupError("budget_not_found")

        rid = rule_id or f"r_{uuid.uuid4().hex[:10]}"
        if rule_id:
            exists = conn.execute(
                text("SELECT 1 FROM budget_rules WHERE id = :id AND budget_id = :bid"),
                {"id": rule_id, "bid": budget_id},
            ).scalar()
            if not exists:
                raise LookupError("rule_not_found")

        conn.execute(
            text(
                """
                INSERT INTO budget_rules (
                  id, budget_id, threshold_pct, action_channel, severity, action, channels
                ) VALUES (
                  :id, :bid, :thr, :channel, :severity, :action, CAST(:channels AS jsonb)
                )
                ON CONFLICT (id) DO UPDATE SET
                  threshold_pct = EXCLUDED.threshold_pct,
                  action_channel = EXCLUDED.action_channel,
                  severity = EXCLUDED.severity,
                  action = EXCLUDED.action,
                  channels = EXCLUDED.channels,
                  updated_at = now()
                """
            ),
            {
                "id": rid,
                "bid": budget_id,
                "thr": threshold,
                "channel": channels[0],
                "severity": severity,
                "action": action,
                "channels": json.dumps(channels),
            },
        )
        return {
            "id": rid,
            "threshold": threshold,
            "channels": channels,
            "action": action,
            "severity": severity,
        }


def delete_budget_rule(budget_id: str, rule_id: str) -> None:
    with engine.begin() as conn:
        # Drop alert history first (FK)
        conn.execute(
            text("DELETE FROM budget_alert_events WHERE budget_rule_id = :id"),
            {"id": rule_id},
        )
        result = conn.execute(
            text(
                """
                DELETE FROM budget_rules
                WHERE id = :id AND budget_id = :bid
                """
            ),
            {"id": rule_id, "bid": budget_id},
        )
        if result.rowcount == 0:
            raise LookupError("rule_not_found")


def billing_export_csv(
    period: str = "mtd",
    tenant_id: str = "all",
    env: str = "production",
) -> str:
    data = billing_overview(period, tenant_id, env)
    lines = ["date,service_id,service_name,cost_inr"]
    name_by_id = {s["id"]: s["name"] for s in data["services"]}
    for d in data["daily"]:
        for sid, cost in (d.get("values") or {}).items():
            lines.append(
                f"{d['date']},{sid},{name_by_id.get(sid, sid)},{round(_fnum(cost), 2)}"
            )
    return "\n".join(lines) + "\n"


# Phase 3B seed-chip close-out (coaching / calibration / redaction writes /
# routing writes / workspace rolling stats). Keep call sites as db.*.
from followups_db import (  # noqa: E402
    create_coaching_action,
    create_export_job,
    create_routing_rule,
    delete_routing_rule,
    list_calibration_sessions,
    list_coaching_actions,
    list_export_jobs,
    list_routing_audit,
    patch_audio_segment_mute,
    patch_calibration_session,
    patch_coaching_action,
    patch_export_job,
    patch_pii_finding,
    patch_redaction_record,
    patch_redaction_rule,
    patch_routing_rule,
    reorder_routing_rules,
    workspace_summary,
)
