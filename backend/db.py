"""Postgres accessors plus API response serializers."""

from __future__ import annotations

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
        "accountId": row["account_id"],
        "risk": row["risk"],
        "outstanding": row["outstanding"] or 0,
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
            "dpd": row["dpd"] or 0,
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
            {"id": lead_id, "customer_id": customer_id, "account_id": payload.get("accountId") or _first_account_id(conn, customer_id), "interaction_id": payload.get("interactionId"), "product_id": payload["productId"], "owner_user_id": payload.get("ownerUserId") or _actor_user_id(), "team_id": payload.get("teamId") or "retail-sales", "stage": payload.get("stage") or "interested", "source": payload.get("source") or "agent", "sentiment_at_capture": payload.get("sentimentAtCapture") or "neutral", "sentiment_score": payload.get("sentimentScore"), "estimated_value": payload.get("estimatedValue"), "offer_amount": payload.get("offerAmount"), "offer_roi": payload.get("offerRoi"), "priority": payload.get("priority") or "normal", "transcript_snippet": payload.get("transcriptSnippet")},
        )
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
                SELECT id, entity_id, at, label, kind
                FROM activity_events
                WHERE entity_type = 'conversation'
                  AND entity_id = ANY(:ids)
                  AND kind = 'conversation_takeover'
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
        if any(item.get("kind") == "system" and item.get("text") == label for _, _, item in staged[cid]):
            continue
        staged[cid].append(
            (
                _ts(ev["at"]),
                ev["id"],
                {
                    "id": ev["id"],
                    "kind": "system",
                    "text": label,
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
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    if not conversation_ids and not interaction_ids:
        return {}, {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT conversation_id, interaction_id, suggestion_text
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
    for r in rows:
        text_value = (r["suggestion_text"] or "").strip()
        if not text_value:
            continue
        if r["conversation_id"]:
            by_conv.setdefault(r["conversation_id"], []).append(text_value)
        if r["interaction_id"]:
            by_ix.setdefault(r["interaction_id"], []).append(text_value)
    return by_conv, by_ix


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


def _serialize_conversation(
    conn: Any,
    row: dict[str, Any],
    messages: list[dict[str, Any]],
    suggestions: list[str],
    me_id: str,
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
    return {
        "id": row["id"],
        "customer": row["customer_name"],
        "accountId": row["account_id"] or "",
        "channel": _inbox_channel(row["channel"]),
        "status": row["status"] if row["status"] in {"bot", "needs_human", "escalated", "assigned"} else "bot",
        "assignedUserId": row["assigned_user_id"],
        "isMine": row["assigned_user_id"] == me_id,
        "sla": _inbox_sla(last_customer_at, row["status"]),
        "unread": unread,
        "lastTime": last_time,
        "lastPreview": last_preview,
        "lastFrom": last_from,
        "sentiment": _inbox_sentiment(row["sentiment_label"], row["avg_sentiment"]),
        "ragSuggestions": suggestions[:5],
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
        by_conv, by_ix = _conversation_suggestions(conn, ids, interaction_ids)
        result = []
        for r in rows:
            suggestions = list(by_conv.get(r["id"]) or [])
            if not suggestions and r["interaction_id"]:
                suggestions = list(by_ix.get(r["interaction_id"]) or [])
            if not suggestions:
                suggestions = [
                    "Payment link / settlement options",
                    "How to raise a payment dispute",
                    "Callback scheduling policy",
                ]
            result.append(
                _serialize_conversation(conn, r, messages_by.get(r["id"]) or [], suggestions, me_id)
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
        by_conv, by_ix = _conversation_suggestions(
            conn, [conversation_id], [r["interaction_id"]] if r["interaction_id"] else []
        )
        suggestions = list(by_conv.get(conversation_id) or [])
        if not suggestions and r["interaction_id"]:
            suggestions = list(by_ix.get(r["interaction_id"]) or [])
        if not suggestions:
            suggestions = [
                "Payment link / settlement options",
                "How to raise a payment dispute",
                "Callback scheduling policy",
            ]
        return _serialize_conversation(conn, r, messages, suggestions, me_id)


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


def send_conversation_message(conversation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    text_value = (payload.get("text") or "").strip()
    if not text_value:
        raise ValueError("empty_message")
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
        if row["status"] == "bot" and row["assigned_user_id"] != me_id:
            raise ValueError("bot_still_handling")
        msg_id = _id("MSG")
        now = datetime.now(timezone.utc)
        conn.execute(
            text(
                """
                INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                VALUES (:id, :conversation_id, 'agent', :body, 'sent', NULL, :sent_at)
                """
            ),
            {
                "id": msg_id,
                "conversation_id": conversation_id,
                "body": text_value,
                "sent_at": now,
            },
        )
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
    result = get_conversation(conversation_id)
    if result is None:
        raise KeyError("conversation_not_found")
    return result
