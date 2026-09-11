"""Postgres accessors plus API response serializers."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

import contact_window
from agent_core import clock
import visibility
from env_utils import env_int as _env_int
from schemas import (
    CallResponse,
    CustomerResponse,
    HandoffQueueItem,
    HandoffQueueResponse,
    HandoffSessionResponse,
    LeadResponse,
    ProductResponse,
)
from db_core import (
    ACTOR_USER_ID as ACTOR_USER_ID,
    BASE as BASE,
    DATABASE_URL as DATABASE_URL,
    DB_MAX_OVERFLOW as DB_MAX_OVERFLOW,
    DB_POOL_RECYCLE as DB_POOL_RECYCLE,
    DB_POOL_SIZE as DB_POOL_SIZE,
    DB_STATEMENT_TIMEOUT_MS as DB_STATEMENT_TIMEOUT_MS,
    DEFAULT_DATABASE_URL as DEFAULT_DATABASE_URL,
    DEFAULT_LIST_LIMIT as DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT as MAX_LIST_LIMIT,
    TENANT_ID as TENANT_ID,
    _CUSTOMER_SCOPED_TABLES as _CUSTOMER_SCOPED_TABLES,
    _DEFAULT_STATEMENT_TIMEOUT_MS as _DEFAULT_STATEMENT_TIMEOUT_MS,
    _IST as _IST,
    _PROCESS_ROLE as _PROCESS_ROLE,
    _VIS_PREDICATE as _VIS_PREDICATE,
    _account_tail as _account_tail,
    _activity as _activity,
    _actor_user_id as _actor_user_id,
    _as_dict as _as_dict,
    _as_utc as _as_utc,
    _assert_tenant_owns as _assert_tenant_owns,
    _bind_tenant_for_transaction as _bind_tenant_for_transaction,
    _clean as _clean,
    _dump as _dump,
    _id as _id,
    _jsonb as _jsonb,
    _one as _one,
    _read_env_file as _read_env_file,
    _rows as _rows,
    _speaker_screen as _speaker_screen,
    _sql as _sql,
    _tenant as _tenant,
    _vector_literal as _vector_literal,
    _vis_params as _vis_params,
    clamp_list_limit as clamp_list_limit,
    clamp_offset as clamp_offset,
    current_tenant as current_tenant,
    engine as engine,
)

logger = logging.getLogger(__name__)


class OwnerBotNotFound(KeyError):
    """The requested ownerBotId does not exist in this environment.

    Subclasses KeyError so existing ``except KeyError -> 404`` handlers keep
    working, while callers that want to retry without a bot owner can catch
    exactly this condition instead of every KeyError (including a genuine
    missing-payload-key bug).
    """


# Calls carry their whole transcript inline, so a call row is orders of
# magnitude larger than a customer row and gets its own, tighter default.
DEFAULT_CALLS_LIMIT = max(1, _env_int("DEFAULT_CALLS_LIMIT", 100))
# Child collections rendered inside one customer's 360 view. Bounded by that
# customer's own history rather than the portfolio, so the ceiling can be
# generous — but not absent: a five-year-old account with a thousand notes
# should render its recent ones, not every one ever written.
DEFAULT_DETAIL_LIMIT = max(1, _env_int("DEFAULT_DETAIL_LIMIT", 100))


def _assert_tenant_owns_customer(conn: Any, customer_id: str | None) -> None:
    """The same guard where the id *is* the customer id."""
    if not customer_id:
        raise KeyError("customer_not_found")
    found = conn.execute(
        text("SELECT 1 FROM customers WHERE id = :row_id AND tenant_id = :tenant_id"),
        {"row_id": customer_id, "tenant_id": _tenant()},
    ).fetchone()
    if not found:
        raise KeyError("customer_not_found")


def pool_snapshot() -> dict[str, Any]:
    """QueuePool occupancy for /ready headroom checks (no DB round-trip)."""
    pool = engine.pool
    checked_out = int(pool.checkedout()) if hasattr(pool, "checkedout") else 0
    overflow = int(pool.overflow()) if hasattr(pool, "overflow") else 0
    capacity = DB_POOL_SIZE + DB_MAX_OVERFLOW
    return {
        "poolSize": DB_POOL_SIZE,
        "maxOverflow": DB_MAX_OVERFLOW,
        "capacity": capacity,
        "checkedOut": checked_out,
        "overflow": overflow,
        "available": max(0, capacity - checked_out),
        "statementTimeoutMs": DB_STATEMENT_TIMEOUT_MS,
        "poolRecycle": DB_POOL_RECYCLE,
    }


def readiness() -> dict[str, Any]:
    """Liveness of DB + pool headroom. Exhausted pool → not ready (shed load)."""
    snap = pool_snapshot()
    if snap["available"] <= 0:
        return {
            "ok": False,
            "db": None,
            "pool": snap,
            "detail": "pool_exhausted",
        }
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "db": True, "pool": snap}
    except Exception:
        # /ready is typically unauthenticated (load balancers poll it). A
        # SQLAlchemy connection error stringifies the full DSN including the
        # database user — log it, never return it.
        logger.exception("readiness_check_failed")
        return {
            "ok": False,
            "db": False,
            "pool": snap,
            "detail": "db_unavailable",
        }


def dispose_engine() -> None:
    """Graceful shutdown — release pooled connections."""
    try:
        engine.dispose()
    except Exception:
        logger.exception("engine.dispose failed")


def init_and_seed() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1 FROM tenants LIMIT 1"))


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


def user_exists(user_id: str) -> bool:
    uid = (user_id or "").strip()
    if not uid:
        return False
    with engine.connect() as conn:
        row = _one(
            conn.execute(text("SELECT id FROM users WHERE id = :id"), {"id": uid})
        )
        return row is not None


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
        # The permission set the route table will actually enforce for this
        # actor, so the shell can hide what it cannot do instead of learning
        # it from a 403 after the click.
        import authz

        return {
            "id": row["id"],
            "name": row["name"],
            "kind": "human",
            "team": row["team"],
            "status": row["status"],
            "tenantId": _tenant(),
            "permissions": sorted(authz.actor_permissions(row["id"])),
        }


def replace_role_permissions(role_id: str, permission_ids: list[str]) -> dict[str, Any]:
    """Replace the grant set for one role. Admin keeps admin.write.

    An empty ``permission_ids`` is a real opinion — the role is configured
    with no grants, not "never configured". Callers that previously deleted
    every row and fell back to ``ROLE_DEFAULTS`` were restoring access.
    """
    import authz

    rid = (role_id or "").strip()
    wanted = [p for p in permission_ids if p in authz.ALL_PERMISSIONS]
    with engine.begin() as conn:
        role = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name FROM roles
                     WHERE tenant_id = :t AND (id = :id OR lower(name) = lower(:id))
                     LIMIT 1
                    """
                ),
                {"t": _tenant(), "id": rid},
            )
        )
        if not role:
            raise KeyError("role_not_found")
        if authz._normalize_role(role["name"]) == "admin" and authz.ADMIN_WRITE not in wanted:
            wanted.append(authz.ADMIN_WRITE)
        conn.execute(
            text(
                """
                UPDATE roles
                   SET configured_at = now(), updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": role["id"]},
        )
        conn.execute(text("DELETE FROM role_permissions WHERE role_id = :id"), {"id": role["id"]})
        for pid in wanted:
            conn.execute(
                text(
                    """
                    INSERT INTO role_permissions (role_id, permission_id)
                    VALUES (:rid, :pid)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"rid": role["id"], "pid": pid},
            )
        from agent_core import change_log

        change_log.record_role_grants(
            conn,
            tenant_id=_tenant(),
            actor_user_id=_actor_user_id() or "system",
            entry_id=_id("AUD"),
            role_id=role["id"],
            permission_ids=sorted(wanted),
        )
    # Role changes are rare and the cache is per-process; drop all of it so a
    # revocation is visible on the next request rather than up to PERMS_TTL_S
    # later. The docstring on invalidate_permission_cache is "call after a
    # role change" — this is that caller.
    authz.invalidate_permission_cache()
    return {"id": role["id"], "name": role["name"], "permissionIds": sorted(wanted)}


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


def record_activity(
    conn: Any,
    entity_type: str,
    entity_id: str,
    kind: str,
    label: str,
    note: str | None = None,
    customer_id: str | None = None,
) -> None:
    """Public alias for _activity — out-of-module callers (bot_runtime) should
    not reach into a private helper for a supported operation."""
    _activity(conn, entity_type, entity_id, kind, label, note, customer_id)


def _idempotent_response(conn: Any, key: str | None, endpoint: str) -> dict[str, Any] | None:
    """Return the stored response for ``key``, serialising concurrent replays.

    The read alone was not enough: two requests carrying the same key both saw
    no row, both performed the mutation, and the second ``ON CONFLICT DO
    NOTHING`` store silently discarded its response — two promises for one
    idempotent POST. The transaction-scoped advisory lock makes the second
    caller wait for the first to commit, so its SELECT (READ COMMITTED, taken
    after the lock) sees the canonical response and skips the write entirely.
    """
    if not key:
        return None
    # Two-int form. The first int folds tenant into endpoint with a separator:
    # a hash collision between two (tenant, endpoint) pairs costs one spurious
    # shared lock — extra serialisation, never a wrong answer, because identity
    # is enforced by the primary key and by the SELECT below, not by the lock.
    conn.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "  hashtext(:tenant_id || '/' || :endpoint), hashtext(:key))"
        ),
        {"tenant_id": _tenant(), "endpoint": endpoint, "key": key},
    )
    row = conn.execute(
        text(
            "SELECT response FROM idempotency_keys "
            " WHERE tenant_id = :tenant_id AND key = :key AND endpoint = :endpoint"
        ),
        {"tenant_id": _tenant(), "key": key, "endpoint": endpoint},
    ).fetchone()
    return row[0] if row else None


def _store_idempotent_response(conn: Any, key: str | None, endpoint: str, response: dict[str, Any]) -> None:
    if not key:
        return
    conn.execute(
        text(
            """
            INSERT INTO idempotency_keys (tenant_id, key, endpoint, response)
            VALUES (:tenant_id, :key, :endpoint, CAST(:response AS jsonb))
            ON CONFLICT (tenant_id, endpoint, key) DO NOTHING
            """
        ),
        {
            "tenant_id": _tenant(),
            "key": key,
            "endpoint": endpoint,
            "response": json.dumps(response),
        },
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
    if requested_via in {
        "bot_voice",
        "bot_chat",
        "agent",
        "mcp",
        "clerk",
        "vision",
        "inbox",
    }:
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


# A dispute is at risk once less than a quarter of its filing→due window is
# left, and breached the moment it passes due.
DISPUTE_SLA_WARN_FRACTION = 0.25


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
    remaining = (due - datetime.now(timezone.utc)).total_seconds()
    label = _dispute_sla_countdown(remaining)
    minutes = int(remaining / 60)
    if remaining < 0:
        return "breach", label, minutes
    captured = _as_utc(captured_at)
    window = (due - captured).total_seconds() if captured else 0.0
    if window > 0 and remaining < window * DISPUTE_SLA_WARN_FRACTION:
        return "warn", label, minutes
    return "ok", label, minutes


def _base_customer_row(
    conn: Any,
    customer_id: str | None = None,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    # Always tenant-scoped, like every other customer-facing read in this
    # module: this feeds both list_customers() and get_customer(), so an
    # unscoped query here is the one that hands another tenant's PII to the
    # Customer 360 screen.
    #
    # It carries the object-level scope for the same reason. Both the list and
    # the single-customer lookup come through here, so `get_customer` on a
    # customer outside the actor's book returns no row and the route answers
    # 404 — without a second check written somewhere else and kept in step.
    where = f"WHERE c.tenant_id = :tenant_id AND {visibility.predicate('c')}"
    params: dict[str, Any] = {"tenant_id": _tenant(), **_vis_params()}
    if customer_id:
        where += " AND c.id = :customer_id"
        params["customer_id"] = customer_id
    # A single-customer lookup needs no page; a full list must have one.
    page_sql = ""
    if not customer_id:
        params["limit"] = clamp_list_limit(limit, DEFAULT_LIST_LIMIT)
        params["offset"] = clamp_offset(offset)
        page_sql = "LIMIT :limit OFFSET :offset"
    return _rows(
        conn.execute(
            text(
                f"""
                SELECT
                  c.id,
                  c.name,
                  c.risk,
                  -- The seed column is a fossil nothing at runtime updates; the
                  -- last contact is the newest admitted touch on the gate's
                  -- own ledger, falling back to the seed for a customer with
                  -- no events yet.
                  COALESCE(
                    (SELECT max(ce.occurred_at) FROM contact_events ce
                      WHERE ce.customer_id = c.id AND ce.outcome = 'allowed'),
                    c.last_contact_at
                  ) AS last_contact_at,
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
                ORDER BY c.name, c.id
                {page_sql}
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
        "minimumDue": float(row["minimum_due"] or 0),
        "lastContact": row["last_contact_at"],
        "assignedTo": row["assigned_to"] or "Unassigned",
        "contact": {
            "phonePrimary": row["phone_primary"] or "",
            "phoneAlt": row["phone_alt"],
            "email": row["email"] or "",
            "address": row["address"] or "",
            "timezone": row["timezone"] or clock.DEFAULT_TIMEZONE,
            "language": row["language"] or "English",
            "preferredWindow": row["preferred_window"] or contact_window.DEFAULT_WINDOW,
            "dnd": bool(row["dnd"]),
        },
        "account": {
            "product": row["product"] or "Credit Card",
            "openedOn": row["opened_on"] or None,
            "apr": float(row["apr"] or 0),
            "sanctionedAmount": float(row["sanctioned_amount"] or 0),
            "bucket": row["bucket"] or "Current",
            "dpd": int(row["dpd"] or 0),
            "riskScore": int(row["risk_score"] or 0),
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


def list_customers(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Customer list, bounded. ``include_detail=False`` issues no per-row query,
    so this is one indexed read plus serialization — the cost was the row count,
    not a fan-out."""
    with engine.connect() as conn:
        return [
            _dump(_customer_contract(conn, row, include_detail=False))
            for row in _base_customer_row(conn, limit=limit, offset=offset)
        ]


def get_customer(customer_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        rows = _base_customer_row(conn, customer_id)
        if not rows:
            return None
        return _dump(_customer_contract(conn, rows[0], include_detail=True))


def _customer_activity_preview(conn: Any, customer_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """Pull recent activity_events tied to this customer's related entities."""
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.id, ae.kind, ae.label, ae.note, ae.at, ae.tone
                FROM activity_events ae
                WHERE ae.tenant_id = :tenant_id
                  AND (
                    (ae.entity_type = 'customer' AND ae.entity_id = :customer_id)
                    OR ae.entity_id IN (SELECT id FROM interactions WHERE customer_id = :customer_id)
                    OR ae.entity_id IN (SELECT id FROM promises WHERE customer_id = :customer_id)
                    OR ae.entity_id IN (SELECT id FROM disputes WHERE customer_id = :customer_id)
                    OR ae.entity_id IN (SELECT id FROM conversations WHERE customer_id = :customer_id)
                    OR ae.entity_id IN (SELECT id FROM document_requests WHERE customer_id = :customer_id)
                    OR ae.entity_id IN (SELECT id FROM customer_notes WHERE customer_id = :customer_id)
                  )
                ORDER BY ae.at DESC
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "tenant_id": _tenant(), "limit": limit},
        )
    )
    return [
        {
            "id": r["id"],
            "kind": r["kind"] or "event",
            "label": r["label"],
            "note": r.get("note"),
            "at": r["at"].isoformat().replace("+00:00", "Z") if hasattr(r["at"], "isoformat") else str(r["at"]),
            "tone": r.get("tone"),
        }
        for r in rows
    ]


def get_customer_insights(customer_id: str) -> dict[str, Any] | None:
    from agent_core.reco import policy
    from agent_core.authority import policy as authority_policy
    from customer_insights import derive_insights

    customer = get_customer(customer_id)
    if customer is None:
        return None
    with engine.connect() as conn:
        activity = _customer_activity_preview(conn, customer_id)
        offer = policy.snapshot(
            conn, customer_id=customer_id, tenant_id=_tenant()
        )
        authority = authority_policy.snapshot(
            conn, customer_id=customer_id, tenant_id=_tenant()
        )
        treatment = _treatment_snapshot(conn, customer_id)
    return derive_insights(
        customer,
        activity=activity or None,
        offer_policy=offer,
        authority_policy=authority,
        treatment=treatment,
    )


def _treatment_snapshot(conn: Any, customer_id: str) -> dict[str, Any] | None:
    """What the decision engine would do for this borrower, right now.

    The third policy on this card, and the one that was missing. It already
    carried two real snapshots — the offer policy and the authority matrix —
    while the "next best action" list beside them was a hand-written ladder
    that consulted neither the contact policy nor the decision log.

    Never raises, and returns None rather than a placeholder on failure: an
    absent engine row leaves the card showing its case-handling items, which is
    a degraded view. A fabricated one would be a wrong recommendation with a
    rupee figure attached to it.

    ``recommend_treatment`` is called with persist='preview' so opening a
    customer writes zero decision rows. Event and sweep callers remain the
    only persistent decision producers.
    """
    try:
        from agent_core.treatment import Trigger, recommend_treatment

        result = recommend_treatment(
            customer_id=customer_id,
            trigger=Trigger(kind="manual"),
            conn=conn,
            persist="preview",
        )
        return result.to_payload()
    except Exception:
        logger.exception("treatment snapshot failed for customer=%s", customer_id)
        return None


def _interaction_contracts(conn: Any, customer_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    # Tenant-scoped unconditionally. Filtering on customer_id alone was safe
    # only because every live caller passes one and customers are themselves
    # tenant-scoped; the customer_id=None path selected across tenants, and
    # neither the limit nor the tenant were required by the signature.
    where = "WHERE i.tenant_id = :tenant_id"
    params: dict[str, Any] = {"tenant_id": _tenant()}
    if customer_id:
        where += " AND i.customer_id = :customer_id"
        params["customer_id"] = customer_id
    # No unbounded branch: this loads full transcripts per interaction.
    params["limit"] = clamp_list_limit(limit, DEFAULT_CALLS_LIMIT)
    limit_sql = "LIMIT :limit"
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
    # Batch transcripts — avoid N+1 (one query per interaction).
    transcripts_by_id: dict[str, list[str]] = {row["id"]: [] for row in interactions}
    interaction_ids = list(transcripts_by_id)
    if interaction_ids:
        for trow in _rows(
            conn.execute(
                text(
                    """
                    SELECT interaction_id, text
                    FROM interaction_transcript
                    WHERE interaction_id = ANY(:ids)
                    ORDER BY interaction_id, turn_index
                    """
                ),
                {"ids": interaction_ids},
            )
        ):
            transcripts_by_id.setdefault(trow["interaction_id"], []).append(trow["text"])

    output = []
    for interaction in interactions:
        output.append(
            {
                "id": interaction["id"],
                "channel": interaction["channel"],
                "handler": {"kind": interaction["handler_kind"], "name": interaction["handler_name"] or "Unknown"},
                "startedAt": interaction["started_at"],
                "duration": _duration(interaction["duration_sec"]),
                "disposition": interaction["disposition"] or "Unknown",
                "sentiment": interaction["sentiment_label"] or "neutral",
                "sentimentDelta": _sentiment_delta(interaction["avg_sentiment"]),
                "summary": interaction["summary"] or "",
                "intents": {
                    "queryResolved": bool(interaction["query_resolved"]),
                    "upsellPresented": bool(interaction["upsell_presented"]),
                    "ptpCaptured": bool(interaction["ptp_captured"]),
                },
                "transcript": transcripts_by_id.get(interaction["id"], []),
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
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "limit": DEFAULT_DETAIL_LIMIT},
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


def _document_contracts(conn: Any, customer_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, doc_type, delivery_channel, status, created_at,
                       requested_via, source
                FROM document_requests
                WHERE customer_id = :customer_id
                ORDER BY created_at DESC
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "limit": DEFAULT_DETAIL_LIMIT},
        )
    )
    return [
        {
            "id": r["id"],
            "type": r["doc_type"],
            # The channel the request came through, from the stored origin.
            # A literal "voice" made every WhatsApp, desk and MCP request read
            # as a call on the customer's Documents tab.
            "requestedVia": _requested_via_channel(r.get("requested_via")),
            "requestedAt": r["created_at"],
            "deliveryChannel": _doc_channel(r["delivery_channel"]),
            "status": r["status"],
            "source": r.get("source") or "crm",
        }
        for r in rows
    ]


#: `document_requests.requested_via` is an origin (bot_voice, bot_chat, agent,
#: mcp, clerk, vision, inbox); the customer contract shows a channel.
_REQUESTED_VIA_CHANNEL = {
    "bot_voice": "voice",
    "bot_chat": "whatsapp",
    "clerk": "sms",
    "inbox": "whatsapp",
}


def _requested_via_channel(origin: str | None) -> str:
    return _REQUESTED_VIA_CHANNEL.get(str(origin or ""), "chat")


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
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "limit": DEFAULT_DETAIL_LIMIT},
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


def list_promises(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Promise-to-Pay screen feed (richer than the Customer 360 contract)."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT p.id, p.customer_id, c.name AS customer_name, p.account_id,
                           p.amount, p.promised_at, p.created_at, p.channel, p.status,
                           p.reminder_status, p.paid_amount, p.plan_id, p.owner_kind,
                           COALESCE(u.name, b.name) AS owner,
                           pi.status AS payment_intent_status,
                           pi.confirm_channel,
                           pi.suppression_reason,
                           pi.phone_last4,
                           pi.id AS payment_intent_id
                    FROM promises p
                    JOIN customers c ON c.id = p.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN users u ON u.id = p.owner_user_id
                    LEFT JOIN bots b ON b.id = p.owner_bot_id
                    LEFT JOIN LATERAL (
                        SELECT status, confirm_channel, suppression_reason, phone_last4, id
                        FROM payment_intents
                        WHERE promise_id = p.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) pi ON true
                    ORDER BY p.promised_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
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
                    "confirmChannel": r.get("confirm_channel"),
                    "confirmStatus": (
                        "suppressed"
                        if r.get("suppression_reason") and r.get("payment_intent_status") not in {"sent", "opened", "paid"}
                        else r.get("payment_intent_status")
                    ),
                    "paymentIntentStatus": r.get("payment_intent_status"),
                    "paymentIntentId": r.get("payment_intent_id"),
                    "payLinkSent": r.get("payment_intent_status") in {"sent", "opened", "paid"},
                    "phoneLast4": r.get("phone_last4"),
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
    """Assignable actors: humans first, then bots.

    A bot is ``active`` only when it carries an active production deployment
    and is not archived. ``webchatbot`` / ``collectionsbot-v2-4`` exist as
    history scaffolds — they hold no prompt and no deployment — and must not
    be claimed as live. Status is still returned so name resolution of
    historical owners keeps working.
    """
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
        bots = _rows(
            conn.execute(
                text(
                    """
                    SELECT b.id, b.name, b.archived_at,
                           EXISTS (
                             SELECT 1 FROM bot_deployments d
                              WHERE d.bot_id = b.id
                                AND d.status = 'active'
                                AND d.environment = 'production'
                           ) AS has_deployment
                      FROM bots b
                     ORDER BY b.name
                    """
                )
            )
        )
        return [
            {"id": u["id"], "name": u["name"], "kind": "human", "team": u["team"], "status": u["status"]}
            for u in users
        ] + [
            {
                "id": b["id"],
                "name": b["name"],
                "kind": "bot",
                "team": None,
                "status": (
                    "archived"
                    if b.get("archived_at")
                    else ("active" if b.get("has_deployment") else "inactive")
                ),
            }
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
    """Consent days for the CRM's screens, substituting Mon-Fri when unrecorded.

    The parsing itself is :func:`contact_window.allowed_days` — the same one the
    contact Gate vetoes with. This module had its own copy that did not
    normalise the dash, so ``Mon–Sat`` came back as ``[1]``: the range branch
    missed, the token split matched the leading "mon", and a six-day consent was
    displayed and compared as Monday alone.

    The Mon-Fri substitution stays here rather than moving into the shared
    parser. "Blank consent days means Mon-Fri" is a product claim this screen
    makes, not a fact about the text, and the Gate deliberately makes the
    opposite one — absent days there mean no day restriction to apply. Both are
    defensible; neither should be hidden inside a parser where the other side
    cannot see it.
    """
    return contact_window.allowed_days(raw) or [1, 2, 3, 4, 5]


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
            # No consent row means no consent. Synthesising "opted_in" made the
            # Consent screen assert a permission nobody captured — the one
            # place in the product where the answer must never be inferred.
            complete.append(
                {
                    "channel": ch,
                    "status": "opted_out",
                    "capturedAt": fallback_at,
                    # Stays "Onboarding" — the screen's `source` is a closed
                    # union (ChannelConsent in consent-seed.ts) and the status
                    # is what carries the correction.
                    "source": "Onboarding",
                    "frequencyCapPerWeek": 3,
                    "usedThisWeek": 0,
                }
            )
    return complete


def list_consent(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Consent & Communication Preferences feed (richer than Customer 360 consent)."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT cr.id, cr.customer_id, cr.dnd_registry, cr.expires_at,
                           cr.allowed_days, cr.allowed_hours, cr.created_at,
                           c.name AS customer_name, c.phone_primary, c.email,
                           c.timezone, c.segment, c.preferred_window, c.dnd AS customer_dnd,
                           a.id AS account_id
                    FROM consent_records cr
                    JOIN customers c ON c.id = cr.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
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
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
            )
        )
        consent_ids = [r["id"] for r in rows]
        customer_ids = [r["customer_id"] for r in rows]
        channels = _consent_channels_grouped(conn, consent_ids)
        optouts = _consent_optouts_grouped(conn, consent_ids)
        audits = _consent_audit_grouped(conn, customer_ids)
        usage: dict[str, dict[str, Any]] = {}
        try:
            import contact_policy

            usage = contact_policy.ledger_usage(conn, customer_ids)
        except Exception:
            logger.exception("contact_policy ledger_usage failed")
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
            stats = usage.get(r["customer_id"]) or {}
            by_ch = stats.get("byChannel") or {}
            complete = _ensure_channels_complete(channels.get(r["id"]) or [], created)
            for item in complete:
                db_ch = "voice" if item["channel"] == "call" else item["channel"]
                if db_ch in by_ch:
                    item["usedThisWeek"] = by_ch[db_ch]
            result.append(
                {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountId": r["account_id"] or "",
                    "phone": r["phone_primary"] or "",
                    "email": r["email"] or "",
                    "timezone": r["timezone"] or clock.DEFAULT_TIMEZONE,
                    "segment": _consent_segment(r["segment"]),
                    "channels": complete,
                    "allowedWindow": {
                        "days": _parse_allowed_days(r["allowed_days"]),
                        "startHour": start_h,
                        "endHour": end_h,
                    },
                    "consentExpiresAt": expires,
                    "onDndRegistry": bool(r["dnd_registry"] or r["customer_dnd"]),
                    "optOutLog": optouts.get(r["id"]) or [],
                    "audit": audit,
                    "outreachToday": int(stats.get("outreachToday") or 0),
                    "dailyCap": int(stats.get("dailyCap") or 3),
                    "lastDecisionReason": stats.get("lastDecisionReason"),
                }
            )
        return result


def get_contact_policy(customer_id: str, channel: str = "whatsapp", purpose: str = "outreach") -> dict[str, Any]:
    """Dry-run of the contact gate for Inbox / Floor / Consent pills."""
    import contact_policy

    with engine.connect() as conn:
        if _one(conn.execute(text("SELECT 1 FROM customers WHERE id = :id AND tenant_id = :tid"), {"id": customer_id, "tid": _tenant()})) is None:
            raise KeyError("customer_not_found")
        decision = contact_policy.evaluate(
            conn,
            customer_id=customer_id,
            channel=channel,
            purpose=purpose,
        )
    payload = decision.as_dict()
    payload["channel"] = contact_policy.normalize_channel(channel)
    payload["purpose"] = purpose if purpose in contact_policy.PURPOSES else "outreach"
    return payload


def list_disputes(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Disputes & Exceptions queue feed (richer than the Customer 360 contract)."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
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


def list_documents(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Document Fulfilment Desk feed (richer than the Customer 360 contract)."""
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


def list_payment_plans(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Payment-plans table for the Promises screen; owner/cadence/start derived."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        plans = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT pp.id, pp.customer_id, c.name AS customer_name, pp.account_id,
                           pp.total_amount, pp.created_at
                    FROM payment_plans pp
                    JOIN customers c ON c.id = pp.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    ORDER BY pp.created_at DESC, pp.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
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


def list_calls(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Audit-screen call list, newest first.

    Bounded and tenant-scoped. Both were missing: the outer query selected every
    interaction the deployment had ever recorded, and the four child queries
    below then loaded *every transcript turn of every one of them* into memory
    to assemble the response. That is fine against a demo seed and is a
    guaranteed outage against a real portfolio.
    """
    page = clamp_list_limit(limit, DEFAULT_CALLS_LIMIT)
    skip = clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
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
                    WHERE i.tenant_id = :tenant_id
                      /*VISIBILITY*/
                    ORDER BY i.started_at DESC NULLS LAST, i.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"tenant_id": _tenant(), "limit": page, "offset": skip, **_vis_params()},
            )
        )
        # Four child tables, one query each — not four per interaction. The
        # per-row version issued 4N round trips against an unbounded outer
        # query, so the Calls screen got slower in direct proportion to how
        # long the deployment had been running.
        interaction_ids = [row["id"] for row in rows]

        def _grouped(sql: str) -> dict[str, list[dict[str, Any]]]:
            grouped: dict[str, list[dict[str, Any]]] = {}
            if not interaction_ids:
                return grouped
            for r in _rows(conn.execute(text(sql), {"interaction_ids": interaction_ids})):
                grouped.setdefault(r.pop("interaction_id"), []).append(r)
            return grouped

        transcripts_by = _grouped(
            """
            SELECT interaction_id, id, at_sec AS t, speaker, text
            FROM interaction_transcript
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, turn_index
            """
        )
        flags_by = _grouped(
            """
            SELECT interaction_id, flag, severity
            FROM interaction_flags
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, created_at
            """
        )
        sentiment_by = _grouped(
            """
            SELECT interaction_id, at_sec AS t, score AS v
            FROM interaction_sentiment
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, at_sec
            """
        )
        disclosures_by = _grouped(
            """
            SELECT interaction_id, id, label, read, read_at_sec AS "atSec"
            FROM interaction_disclosures
            WHERE interaction_id = ANY(:interaction_ids)
            ORDER BY interaction_id, id
            """
        )

        calls = []
        for row in rows:
            transcript = transcripts_by.get(row["id"], [])
            flags = flags_by.get(row["id"], [])
            sentiment_series = sentiment_by.get(row["id"], [])
            disclosures = disclosures_by.get(row["id"], [])
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


def list_products(include_inactive: bool = False) -> list[dict[str, Any]]:
    """Offer catalog. Inactive products stay retrievable for historical leads —
    a lead captured last month must still render its product name after the
    product is switched off."""
    # Tenant first, so the optional is_active filter cannot be the only
    # predicate — include_inactive=True used to widen this to every tenant's
    # catalog rather than only to this tenant's retired products.
    clause = "" if include_inactive else " AND is_active IS TRUE"
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT id, name, category, family, description, type,
                           ticket_min, ticket_max, roi, roi_numeric,
                           tenor_months_min, tenor_months_max,
                           margin_score, is_active, channels
                    FROM products
                    WHERE tenant_id = :tenant_id{clause}
                    ORDER BY COALESCE(category, type), name, id
                    """
                ),
                {"tenant_id": _tenant()},
            )
        )
    return [
        _dump(
            ProductResponse(
                id=r["id"],
                name=r["name"],
                # `type` is the legacy column every seeded row has; `category` is
                # the curated one. Prefer category, fall back so the UI is never
                # handed a null grouping key.
                category=r["category"] or (r["type"] or "").title() or None,
                family=r["family"],
                description=r["description"],
                minTicket=r["ticket_min"],
                maxTicket=r["ticket_max"],
                indicativeROI=r["roi"],
                roiNumeric=r["roi_numeric"],
                tenorMonthsMin=r["tenor_months_min"],
                tenorMonthsMax=r["tenor_months_max"],
                marginScore=r["margin_score"] if r["margin_score"] is not None else 0.5,
                isActive=bool(r["is_active"]),
                channels=list(r["channels"] or []),
            )
        )
        for r in rows
    ]


# Filters the pipeline screen actually offers, resolved server-side. They used
# to be applied only in the browser, over whatever the first page happened to
# contain — so "All owners" on a 5,000-lead book filtered 200 rows and said
# nothing about it.
#
# Every parameter is CAST to text before the NULL test. Postgres cannot infer a
# type for a bare placeholder in `$1 IS NULL` and rejects the statement with
# AmbiguousParameter; the cast is what tells it what an absent filter is.
_LEAD_FILTER_SQL = """
              AND (CAST(:stage      AS text) IS NULL OR l.stage = :stage)
              AND (CAST(:owner      AS text) IS NULL OR u.name = :owner)
              AND (CAST(:team       AS text) IS NULL OR t.name = :team)
              AND (CAST(:product_id AS text) IS NULL OR l.product_id = :product_id)
              AND (CAST(:source     AS text) IS NULL OR l.source = :source)
              -- Comma-separated, because the screen's priority and sentiment
              -- controls are multi-select. A single-value filter here would
              -- have forced those two to stay client-side, and then the KPI
              -- strip and the board would be describing different sets.
              AND (
                CAST(:priority AS text) IS NULL
                OR l.priority = ANY(string_to_array(:priority, ','))
              )
              AND (
                CAST(:sentiment AS text) IS NULL
                OR l.sentiment_at_capture = ANY(string_to_array(:sentiment, ','))
              )
              AND (
                CAST(:q AS text) IS NULL
                OR l.id ILIKE '%%' || :q || '%%'
                OR c.name ILIKE '%%' || :q || '%%'
                OR COALESCE(l.account_id, '') ILIKE '%%' || :q || '%%'
                OR COALESCE(p.name, '') ILIKE '%%' || :q || '%%'
                OR COALESCE(l.transcript_snippet, '') ILIKE '%%' || :q || '%%'
              )
"""


def _lead_filter_params(filters: dict[str, Any] | None) -> dict[str, Any]:
    """Normalise the screen's filter vocabulary. "all" and "" both mean unset."""
    f = filters or {}

    def pick(key: str) -> str | None:
        raw = str(f.get(key) or "").strip()
        return None if not raw or raw == "all" else raw

    return {
        "stage": pick("stage"),
        "owner": pick("owner"),
        "team": pick("team"),
        "product_id": pick("productId"),
        "source": pick("source"),
        "priority": pick("priority"),
        "sentiment": pick("sentiment"),
        "q": pick("q"),
    }


def list_leads(
    *,
    limit: int | None = None,
    offset: int | None = None,
    filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
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
                      l.closed_at,
                      l.won_amount,
                      l.loss_reason,
                      l.interaction_id,
                      l.transcript_snippet,
                      u.name AS owner,
                      t.name AS team
                    FROM leads l
                    JOIN customers c ON c.id = l.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN products p ON p.id = l.product_id
                    LEFT JOIN users u ON u.id = l.owner_user_id
                    LEFT JOIN teams t ON t.id = l.team_id
                    WHERE TRUE
                    """
                    + _LEAD_FILTER_SQL
                    + """
                    ORDER BY l.captured_at DESC NULLS LAST, l.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "limit": page,
                    "offset": skip,
                    "tenant_id": _tenant(),
                    **_vis_params(),
                    **_lead_filter_params(filters),
                },
            )
        )
        # Three bulk queries rather than 3N. The list endpoint is the ONLY
        # source the Upsell screen reads — the detail drawer re-uses the row
        # from this array rather than fetching — so everything the drawer
        # renders has to be here. Returning [] for follow-ups meant one
        # scheduled a second ago showed as "No follow-ups yet".
        lead_ids = [r["id"] for r in rows]
        eligibility_by_lead: dict[str, list[dict[str, Any]]] = {}
        for elig in _rows(
            conn.execute(
                text(
                    "SELECT lead_id, label, passed AS ok, reason AS detail"
                    " FROM lead_eligibility WHERE lead_id = ANY(:ids) ORDER BY lead_id, id"
                ),
                {"ids": lead_ids},
            )
        ):
            eligibility_by_lead.setdefault(elig.pop("lead_id"), []).append(elig)
        followups_by_lead = _lead_followups_bulk(conn, lead_ids)
        events_by_lead = _lead_events_bulk(conn, lead_ids)

        leads = []
        for row in rows:
            eligibility = eligibility_by_lead.get(row["id"], [])
            followups = followups_by_lead.get(row["id"], [])
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
                        nextFollowUpAt=_next_followup_at(followups),
                        followUps=followups,
                        events=events_by_lead.get(row["id"], []),
                        closedAt=row["closed_at"],
                        wonAmount=row["won_amount"],
                        lossReason=row["loss_reason"],
                    )
                )
            )
    return leads


def lead_metrics(filters: dict[str, Any] | None = None) -> dict[str, Any]:
    """The pipeline KPI strip, computed over the whole book.

    These numbers were derived in the browser from whatever ``GET /leads``
    returned, and that endpoint pages at 200. Below the page size the answer
    happened to be right; above it "Conversion (30d)" quietly described the 200
    most recently captured leads while the header claimed to be showing
    everything. A summary statistic computed from a page is not a summary
    statistic.

    Definitions match the client-side ones they replace, deliberately: a lead's
    value is its won amount once won and its estimate before that; conversion
    is won-over-captured within the last 30 days, by capture date; and
    time-to-close spans every closed lead, not just recent ones.
    """
    params = {"tenant_id": _tenant(), **_vis_params(), **_lead_filter_params(filters)}
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                _sql(
                    """
                    WITH scoped AS (
                      SELECT
                        l.stage,
                        l.captured_at,
                        l.closed_at,
                        COALESCE(
                          CASE WHEN l.stage = 'won'
                               THEN COALESCE(l.won_amount, l.estimated_value)
                               ELSE l.estimated_value END,
                          0
                        ) AS value
                      FROM leads l
                      JOIN customers c ON c.id = l.customer_id
                       AND c.tenant_id = :tenant_id
                       /*VISIBILITY*/
                      LEFT JOIN products p ON p.id = l.product_id
                      LEFT JOIN users u ON u.id = l.owner_user_id
                      LEFT JOIN teams t ON t.id = l.team_id
                      WHERE TRUE
                    """
                    + _LEAD_FILTER_SQL
                    + """
                    )
                    SELECT
                      COUNT(*)::int                                              AS total,
                      COUNT(*) FILTER (
                        WHERE stage IN ('interested','contacted','qualified')
                      )::int                                                     AS open_leads,
                      COALESCE(SUM(value) FILTER (
                        WHERE stage IN ('interested','contacted','qualified')
                      ), 0)::float                                               AS pipeline_value,
                      COUNT(*) FILTER (
                        WHERE stage = 'won' AND closed_at > now() - interval '7 days'
                      )::int                                                     AS won_week,
                      COALESCE(SUM(value) FILTER (
                        WHERE stage = 'won' AND closed_at > now() - interval '7 days'
                      ), 0)::float                                               AS won_week_amount,
                      COUNT(*) FILTER (
                        WHERE captured_at > now() - interval '30 days'
                      )::int                                                     AS captured_30d,
                      COUNT(*) FILTER (
                        WHERE captured_at > now() - interval '30 days' AND stage = 'won'
                      )::int                                                     AS won_30d,
                      AVG(
                        EXTRACT(EPOCH FROM (closed_at - captured_at)) / 86400.0
                      ) FILTER (WHERE closed_at IS NOT NULL)                     AS avg_days_to_close
                    FROM scoped
                    """
                ),
                params,
            )
        ) or {}

        by_stage = {
            r["stage"]: {"count": r["n"], "amount": float(r["amount"] or 0)}
            for r in _rows(
                conn.execute(
                    _sql(
                        """
                        SELECT
                          l.stage,
                          COUNT(*)::int AS n,
                          COALESCE(SUM(
                            COALESCE(
                              CASE WHEN l.stage = 'won'
                                   THEN COALESCE(l.won_amount, l.estimated_value)
                                   ELSE l.estimated_value END,
                              0
                            )
                          ), 0)::float AS amount
                        FROM leads l
                        JOIN customers c ON c.id = l.customer_id
                         AND c.tenant_id = :tenant_id
                         /*VISIBILITY*/
                        LEFT JOIN products p ON p.id = l.product_id
                        LEFT JOIN users u ON u.id = l.owner_user_id
                        LEFT JOIN teams t ON t.id = l.team_id
                        WHERE TRUE
                        """
                        + _LEAD_FILTER_SQL
                        + """
                        GROUP BY 1
                        """
                    ),
                    params,
                )
            )
        }

    captured_30d = int(row.get("captured_30d") or 0)
    won_30d = int(row.get("won_30d") or 0)
    avg_days = row.get("avg_days_to_close")
    return {
        "total": int(row.get("total") or 0),
        "openLeads": int(row.get("open_leads") or 0),
        "pipelineValue": float(row.get("pipeline_value") or 0),
        "wonWeek": int(row.get("won_week") or 0),
        "wonWeekAmount": float(row.get("won_week_amount") or 0),
        # None, not 0, when nothing was captured in the window. "no leads to
        # convert" and "converted none of them" are different facts and the
        # strip renders them differently.
        "conversionRate": (
            round(won_30d / captured_30d * 100) if captured_30d else None
        ),
        "captured30d": captured_30d,
        "won30d": won_30d,
        "avgDaysToClose": None if avg_days is None else round(float(avg_days)),
        "perStage": {
            stage: by_stage.get(stage, {"count": 0, "amount": 0.0})
            for stage in ("interested", "contacted", "qualified", "won", "lost")
        },
    }



# ---------------------------------------------------------------------------
# Per-turn trace
#
# Tool calls, retrievals and latency lived at three non-joinable grains, so
# "what did the bot do on turn 4, and how long did each part take" could not be
# answered — which is why the Sandbox's Trace tab reconstructs a timeline from
# client-side state instead of reading one. Migration 0055 gave the two event
# tables a transcript_turn_id; this assembles them.
# ---------------------------------------------------------------------------

# One call's worth. A trace is a debugging view of a single conversation, not a
# reporting surface; an unbounded read here would be a foot-gun on a long call.
_TRACE_MAX_TURNS = 200






HANDOFF_DISPOSITIONS = [
    "PTP captured",
    "Payment taken",
    "Dispute - under review",
    "Info provided",
    "Callback scheduled",
    "Escalated to supervisor",
    "Unresolved - retry",
]

# Checklist catalog for the hub — disclosure rules, not the full violation taxonomy.
_HANDOFF_DISCLOSURE_RULES = (
    ("rule-recording", "Recording disclosure read"),
    ("rule-identity", "Identity verified"),
    ("rule-mini-miranda", "Mini-Miranda / debt-collection notice"),
    ("rule-payment", "Payment terms / data-use consent"),
)


def _epoch_ms(value: Any) -> int:
    if value is None:
        return int(datetime.now(timezone.utc).timestamp() * 1000)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    if isinstance(value, (int, float)):
        return int(value)
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _iso_ts(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _handoff_status(ix_status: str | None, claimed: bool) -> str:
    if ix_status == "completed":
        return "completed"
    if claimed:
        return "active"
    return "pending_claim"


def _actor_team_id(conn: Any) -> str | None:
    row = _one(
        conn.execute(
            text("SELECT team_id FROM users WHERE id = :id"),
            {"id": _actor_user_id()},
        )
    )
    return row["team_id"] if row else None


def _handoff_queue_visible(conn: Any, to_team_id: str | None) -> bool:
    """Whether this unclaimed handoff belongs on the actor's queue."""
    vis = visibility.resolve(_actor_user_id())
    if vis.is_unrestricted:
        return True
    if not to_team_id:
        return True
    actor_team = _actor_team_id(conn)
    if vis.scope == visibility.TEAM:
        supervised = _one(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM teams
                    WHERE id = :tid AND supervisor_user_id = :uid
                    """
                ),
                {"tid": to_team_id, "uid": _actor_user_id()},
            )
        )
        return bool(supervised) or to_team_id == actor_team
    return to_team_id == actor_team


def _handoff_queue_sql_filter() -> str:
    """Bind-parameterised team filter for the unclaimed queue."""
    return """
      AND (
        :vis_all
        OR h.to_team_id IS NULL
        OR h.to_team_id = :actor_team
        OR (:vis_team AND h.to_team_id IN (
              SELECT t.id FROM teams t WHERE t.supervisor_user_id = :vis_actor
            ))
      )
    """


def list_handoff_queue(*, customer_id: str | None = None) -> dict[str, Any]:
    actor = _actor_user_id()
    vis = visibility.resolve(actor)
    with engine.connect() as conn:
        actor_team = _actor_team_id(conn)
        params: dict[str, Any] = {
            "tenant_id": _tenant(),
            "actor": actor,
            "actor_team": actor_team,
            "vis_all": vis.is_unrestricted,
            "vis_team": vis.scope == visibility.TEAM,
            "vis_actor": actor,
        }
        customer_sql = ""
        if customer_id:
            customer_sql = "AND i.customer_id = :customer_id"
            params["customer_id"] = customer_id
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      i.id AS interaction_id,
                      h.id AS handoff_id,
                      i.customer_id,
                      c.name AS customer_name,
                      COALESCE(i.account_id, '') AS account_id,
                      h.reason,
                      h.queue,
                      COALESCE(c.risk, 'medium') AS risk,
                      h.requested_at,
                      EXTRACT(EPOCH FROM (now() - COALESCE(h.requested_at, h.created_at)))::int AS wait_sec
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    JOIN customers c ON c.id = i.customer_id
                    WHERE i.tenant_id = :tenant_id
                      AND i.status = 'active'
                      AND h.to_user_id IS NULL
                      AND h.accepted_at IS NULL
                      AND h.completed_at IS NULL
                      {customer_sql}
                      {_handoff_queue_sql_filter()}
                    ORDER BY h.requested_at ASC NULLS LAST, h.created_at ASC
                    LIMIT 50
                    """
                ),
                params,
            )
        )
        mine = _one(
            conn.execute(
                text(
                    """
                    SELECT i.id
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    WHERE i.tenant_id = :tenant_id
                      AND i.status = 'active'
                      AND h.completed_at IS NULL
                      AND h.accepted_at IS NOT NULL
                      AND (
                        h.to_user_id = :actor
                        OR i.handler_user_id = :actor
                      )
                    ORDER BY h.accepted_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": _tenant(), "actor": actor},
            )
        )
    items = [
        _dump(
            HandoffQueueItem(
                interactionId=r["interaction_id"],
                handoffId=r["handoff_id"],
                customerId=r["customer_id"],
                customerName=r["customer_name"],
                accountId=r["account_id"] or "",
                reason=r["reason"],
                queue=r["queue"],
                risk=str(r["risk"] or "medium"),
                waitSec=max(0, int(r["wait_sec"] or 0)),
                requestedAt=_iso_ts(r["requested_at"]),
            )
        )
        for r in rows
    ]
    return _dump(
        HandoffQueueResponse(
            items=items,
            activeInteractionId=mine["id"] if mine else None,
        )
    )


def get_active_handoff_session() -> dict[str, Any] | None:
    actor = _actor_user_id()
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT i.id
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    WHERE i.tenant_id = :tenant_id
                      AND i.status = 'active'
                      AND h.completed_at IS NULL
                      AND h.accepted_at IS NOT NULL
                      AND (
                        h.to_user_id = :actor
                        OR i.handler_user_id = :actor
                      )
                    ORDER BY h.accepted_at DESC
                    LIMIT 1
                    """
                ),
                {"tenant_id": _tenant(), "actor": actor},
            )
        )
    if row is None:
        return None
    return get_handoff_session(row["id"])


def get_handoff_session(interaction_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
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
                      i.started_at,
                      i.handler_user_id,
                      i.transferred_from_bot_id,
                      COALESCE(u.name, '') AS handler_name,
                      COALESCE(tb.name, fb.name, '') AS transferred_from,
                      c.risk,
                      c.phone_primary,
                      c.preferred_window,
                      c.dnd,
                      a.product_id,
                      p.name AS product,
                      a.opened_on,
                      a.outstanding AS account_outstanding,
                      h.id AS handoff_id,
                      h.reason,
                      h.to_user_id,
                      h.accepted_at,
                      h.completed_at,
                      h.to_team_id,
                      conv.id AS conversation_id
                    FROM interactions i
                    JOIN customers c ON c.id = i.customer_id
                    LEFT JOIN users u ON u.id = i.handler_user_id
                    LEFT JOIN bots tb ON tb.id = i.transferred_from_bot_id
                    LEFT JOIN bots fb ON fb.id = i.handler_bot_id
                    LEFT JOIN accounts a ON a.id = i.account_id
                    LEFT JOIN products p ON p.id = a.product_id
                    LEFT JOIN LATERAL (
                      SELECT id, reason, to_user_id, accepted_at, completed_at, to_team_id
                      FROM interaction_handoffs
                      WHERE interaction_id = i.id
                      ORDER BY requested_at DESC NULLS LAST, created_at DESC
                      LIMIT 1
                    ) h ON true
                    LEFT JOIN LATERAL (
                      SELECT id FROM conversations
                      WHERE interaction_id = i.id
                      ORDER BY created_at DESC
                      LIMIT 1
                    ) conv ON true
                    WHERE i.id = :id
                    """
                ),
                {"id": interaction_id},
            )
        )
        if row is None or not row.get("handoff_id"):
            raise KeyError("handoff_not_found")

        actor = _actor_user_id()
        claimed = bool(row["accepted_at"] and (row["to_user_id"] or row["handler_user_id"]))
        is_mine = row["to_user_id"] == actor or row["handler_user_id"] == actor
        import authz

        is_supervisor = authz.has_permission(actor, authz.SUPERVISOR_READ)
        if claimed and not is_mine and not is_supervisor:
            raise PermissionError("handoff_not_assigned")
        if not claimed and not _handoff_queue_visible(conn, row.get("to_team_id")) and not is_supervisor:
            raise PermissionError("handoff_not_assigned")

        status = _handoff_status(row["status"], bool(row["accepted_at"] or is_mine))
        claimed_flag = bool(row["accepted_at"] or is_mine)
        monitor = bool(is_supervisor and not is_mine)

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
                {"interaction_id": interaction_id},
            )
        )
        sentiment_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT score
                    FROM interaction_sentiment
                    WHERE interaction_id = :interaction_id
                    ORDER BY at_sec, created_at
                    """
                ),
                {"interaction_id": interaction_id},
            )
        )
        suggestion_sql = """
                    SELECT id, suggestion_text AS body, source, accepted
                    FROM ai_response_suggestions
                    WHERE interaction_id = :interaction_id
                    ORDER BY created_at
                    """
        suggestion_params: dict[str, Any] = {"interaction_id": interaction_id}
        if row.get("conversation_id"):
            suggestion_sql = """
                    SELECT id, suggestion_text AS body, source, accepted
                    FROM ai_response_suggestions
                    WHERE interaction_id = :interaction_id
                       OR conversation_id = :conversation_id
                    ORDER BY created_at
                    """
            suggestion_params["conversation_id"] = row["conversation_id"]
        suggestions = _rows(
            conn.execute(text(suggestion_sql), suggestion_params)
        )
        alerts = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, kind, severity, reason
                    FROM live_alerts
                    WHERE interaction_id = :interaction_id
                      AND acknowledged_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT 8
                    """
                ),
                {"interaction_id": interaction_id},
            )
        )
        context = _handoff_customer_context(conn, row)
        compliance = _handoff_compliance_items(conn, interaction_id)
        bot_name = row["transferred_from"] or "Bot"
        speakers = {
            "customer": row["customer_name"],
            "agent": "You" if is_mine else (row["handler_name"] or "Agent"),
            "bot": f"Bot · {bot_name}",
            "system": "System",
        }
        channel = row["channel"] or "voice"
        channel_label = channel.replace("_", " ").title()
        reason = row["reason"] or "routing_rule"
        started_at = _epoch_ms(row["started_at"])
        outstanding = float(row["account_outstanding"] or 0)
        context["outstanding"] = outstanding
        context["risk"] = str(row["risk"] or "medium").title()
        context["product"] = row["product"] or context.get("product") or ""

    session = HandoffSessionResponse(
        interactionId=interaction_id,
        handoffId=row["handoff_id"],
        customerId=row["customer_id"],
        conversationId=row.get("conversation_id"),
        status=status,  # type: ignore[arg-type]
        claimed=claimed_flag,
        monitor=monitor,
        activeCall={
            "interactionId": interaction_id,
            "handoffId": row["handoff_id"],
            "customerId": row["customer_id"],
            "conversationId": row.get("conversation_id"),
            "customerName": row["customer_name"],
            "accountId": row["account_id"] or "",
            "phone": row["phone_primary"] or "",
            "channel": channel_label,
            "agentName": "You" if is_mine else (row["handler_name"] or "Unassigned"),
            "transferredFrom": f"Bot · {bot_name}" if bot_name else "",
            "escalationReason": reason.replace("_", " "),
            "startedAt": started_at,
            "status": status,
            "claimed": claimed_flag,
            "risk": str(row["risk"] or "medium"),
            "handlerUserId": row["handler_user_id"],
        },
        customerContext=context,
        transcriptScript=transcript,
        sentimentSeries=_handoff_sentiment_series(sentiment_rows, transcript),
        suggestions=[
            {
                "id": s["id"],
                "title": "Suggested response",
                "body": s["body"],
                "source": s["source"] or "",
                "showAfter": 0,
                "accepted": bool(s["accepted"]),
            }
            for s in suggestions
        ],
        complianceItems=compliance,
        alerts=[
            {
                "id": a["id"],
                "kind": a["kind"],
                "severity": a["severity"] or "medium",
                "reason": a["reason"],
            }
            for a in alerts
        ],
        dispositions=list(HANDOFF_DISPOSITIONS),
        speakers=speakers,
    )
    return _dump(session)


def _handoff_sentiment_series(
    sentiment_rows: list[dict[str, Any]],
    transcript: list[dict[str, Any]],
) -> list[float]:
    if sentiment_rows:
        return [float(r["score"] or 0) for r in sentiment_rows]
    running = 0.0
    series: list[float] = []
    for turn in transcript:
        delta = turn.get("sentimentDelta")
        if delta is not None:
            running = max(-1.0, min(1.0, running + float(delta)))
            series.append(running)
    return series


def _handoff_customer_context(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    customer_id = row["customer_id"]
    account_id = row.get("account_id")
    last_promise = _one(
        conn.execute(
            text(
                """
                SELECT amount, promised_at, status
                FROM promises
                WHERE customer_id = :cid
                ORDER BY promised_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        )
    )
    next_emi = None
    if account_id:
        next_emi = _one(
            conn.execute(
                text(
                    """
                    SELECT amount, due_date, status
                    FROM emi_installments
                    WHERE account_id = :aid
                      AND status IN ('overdue', 'upcoming', 'partial')
                    ORDER BY
                      CASE status WHEN 'overdue' THEN 0 WHEN 'partial' THEN 1 ELSE 2 END,
                      due_date ASC
                    LIMIT 1
                    """
                ),
                {"aid": account_id},
            )
        )
    open_disputes = _one(
        conn.execute(
            text(
                """
                SELECT count(*)::int AS n
                FROM disputes
                WHERE customer_id = :cid
                  AND status IN ('new', 'under_review', 'awaiting_customer')
                """
            ),
            {"cid": customer_id},
        )
    )
    consents = _rows(
        conn.execute(
            text(
                """
                SELECT cc.channel, cc.status
                FROM consent_records cr
                JOIN channel_consents cc ON cc.consent_id = cr.id
                WHERE cr.customer_id = :cid
                """
            ),
            {"cid": customer_id},
        )
    )
    allowed_channels = [
        (c["channel"] or "").replace("_", " ").title()
        for c in consents
        if c["status"] == "opted_in"
    ]
    if not allowed_channels:
        allowed_channels = ["Voice", "WhatsApp"]
    tenure = 0
    opened = row.get("opened_on")
    if isinstance(opened, datetime):
        opened = opened.date()
    if isinstance(opened, date):
        tenure = max(0, (date.today() - opened).days // 30)
    last = None
    if last_promise:
        last = {
            "amount": float(last_promise["amount"] or 0),
            "date": _iso_ts(last_promise["promised_at"]) or "",
            "status": last_promise["status"] or "upcoming",
        }
    emi = None
    if next_emi:
        due = next_emi["due_date"]
        due_d = due.date() if isinstance(due, datetime) else due
        days = 0
        if isinstance(due_d, date):
            days = max(0, (date.today() - due_d).days)
        emi = {
            "amount": float(next_emi["amount"] or 0),
            "dueDate": _iso_ts(due) or "",
            "daysOverdue": days if (next_emi["status"] == "overdue") else 0,
        }
    return {
        "risk": str(row.get("risk") or "medium").title(),
        "outstanding": 0,
        "currency": "₹",
        "lastPromise": last,
        "nextEmi": emi,
        "openDisputes": int((open_disputes or {}).get("n") or 0),
        "dnd": {
            "allowed": not bool(row.get("dnd")),
            "window": row.get("preferred_window") or "",
            "channels": allowed_channels,
        },
        "tenureMonths": tenure,
        "product": row.get("product") or "",
        "offerPolicy": _handoff_offer_policy(conn, row),
        "authorityPolicy": _handoff_authority_policy(conn, row),
        "liveQa": _handoff_live_qa(conn, row),
    }


def _handoff_offer_policy(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    from agent_core.reco import policy

    try:
        return policy.snapshot(
            conn,
            customer_id=row["customer_id"],
            tenant_id=_tenant(),
            interaction_id=row.get("id"),
        )
    except Exception:
        logger.exception("offer policy snapshot failed for handoff %s", row.get("id"))
        return policy.empty()


def _handoff_authority_policy(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    from agent_core.authority import policy

    try:
        return policy.snapshot(
            conn,
            customer_id=row["customer_id"],
            tenant_id=_tenant(),
            interaction_id=row.get("id"),
        )
    except Exception:
        logger.exception("authority policy snapshot failed for handoff %s", row.get("id"))
        return policy.empty()


def _handoff_live_qa(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    from agent_core.live_qa import policy

    try:
        snap = policy.snapshot(
            conn,
            tenant_id=_tenant(),
            interaction_id=row.get("id"),
        )
        capable = policy.audio_capable_map(conn, [row.get("id") or ""])
        snap["audioCapable"] = bool(capable.get(row.get("id")))
        return snap
    except Exception:
        logger.exception("live_qa snapshot failed for handoff %s", row.get("id"))
        return policy.empty()


def _handoff_compliance_items(conn: Any, interaction_id: str) -> list[dict[str, Any]]:
    disclosures = _rows(
        conn.execute(
            text(
                """
                SELECT id, rule_id, label, read
                FROM interaction_disclosures
                WHERE interaction_id = :iid
                ORDER BY created_at
                """
            ),
            {"iid": interaction_id},
        )
    )
    by_rule: dict[str, dict[str, Any]] = {}
    by_label: dict[str, dict[str, Any]] = {}
    for d in disclosures:
        if d.get("rule_id"):
            by_rule[d["rule_id"]] = d
        by_label[(d.get("label") or "").lower()] = d
    identity = _one(
        conn.execute(
            text(
                """
                SELECT id, status, method
                FROM identity_verifications
                WHERE interaction_id = :iid
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"iid": interaction_id},
        )
    )
    items: list[dict[str, Any]] = []
    for rule_id, label in _HANDOFF_DISCLOSURE_RULES:
        row = by_rule.get(rule_id) or by_label.get(label.lower())
        checked = bool(row and row.get("read"))
        locked = False
        item_id = row["id"] if row else rule_id
        if rule_id == "rule-identity":
            verified = bool(identity and identity.get("status") == "verified")
            checked = checked or verified
            locked = verified
            item_id = "identity" if not row else row["id"]
        items.append(
            {
                "id": item_id,
                "label": label,
                "required": rule_id != "rule-payment",
                "checked": checked,
                "locked": locked,
                "ruleId": rule_id,
            }
        )
    dnd_row = by_label.get("dnd & consent window checked")
    items.append(
        {
            "id": dnd_row["id"] if dnd_row else "dnd-consent",
            "label": "DND & consent window checked",
            "required": True,
            "checked": bool(dnd_row and dnd_row.get("read")),
            "locked": False,
            "ruleId": None,
        }
    )
    return items


def claim_handoff(interaction_id: str) -> dict[str, Any]:
    actor = _actor_user_id()
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        ho = _one(
            conn.execute(
                text(
                    """
                    SELECT h.id, h.to_user_id, h.accepted_at, h.completed_at, h.to_team_id,
                           i.status, i.handler_user_id
                    FROM interaction_handoffs h
                    JOIN interactions i ON i.id = h.interaction_id
                    WHERE h.interaction_id = :iid
                    ORDER BY h.requested_at DESC NULLS LAST, h.created_at DESC
                    LIMIT 1
                    FOR UPDATE OF h
                    """
                ),
                {"iid": interaction_id},
            )
        )
        if ho is None:
            raise KeyError("handoff_not_found")
        if ho["completed_at"] is not None or ho["status"] == "completed":
            raise ValueError("handoff_already_completed")
        if ho["to_user_id"] and ho["to_user_id"] != actor:
            raise ValueError("handoff_already_claimed")
        if ho["accepted_at"] and ho["to_user_id"] == actor:
            pass  # idempotent re-claim
        else:
            if not _handoff_queue_visible(conn, ho.get("to_team_id")):
                raise PermissionError("handoff_not_assigned")
            updated = conn.execute(
                text(
                    """
                    UPDATE interaction_handoffs
                    SET to_user_id = :uid, accepted_at = COALESCE(accepted_at, now())
                    WHERE id = :id
                      AND (to_user_id IS NULL OR to_user_id = :uid)
                      AND completed_at IS NULL
                    RETURNING id
                    """
                ),
                {"id": ho["id"], "uid": actor},
            ).fetchone()
            if updated is None:
                raise ValueError("handoff_already_claimed")
        conn.execute(
            text(
                """
                UPDATE interactions
                SET handler_kind = 'human',
                    handler_user_id = :uid,
                    handler_bot_id = NULL,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": interaction_id, "uid": actor},
        )
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM interaction_participants
                    WHERE interaction_id = :iid
                      AND participant_kind = 'human'
                      AND user_id = :uid
                      AND left_at IS NULL
                    LIMIT 1
                    """
                ),
                {"iid": interaction_id, "uid": actor},
            )
        )
        if existing is None:
            conn.execute(
                text(
                    """
                    INSERT INTO interaction_participants (
                      id, interaction_id, participant_kind, user_id, role, joined_at
                    ) VALUES (
                      :id, :iid, 'human', :uid, 'primary', now()
                    )
                    """
                ),
                {"id": _id("IP"), "iid": interaction_id, "uid": actor},
            )
        _activity(
            conn,
            "interaction",
            interaction_id,
            "handoff_claimed",
            "Handoff claimed",
            None,
        )
    return get_handoff_session(interaction_id)


def record_handoff_disclosure(interaction_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    actor = _actor_user_id()
    item_id = (payload.get("itemId") or "").strip()
    rule_id = (payload.get("ruleId") or "").strip() or None
    label = (payload.get("label") or "").strip()
    read = bool(payload.get("read", True))
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        _assert_handoff_assignee(conn, interaction_id, actor)
        if item_id == "identity" or rule_id == "rule-identity":
            ident = _one(
                conn.execute(
                    text(
                        """
                        SELECT id, status FROM identity_verifications
                        WHERE interaction_id = :iid
                        ORDER BY created_at DESC LIMIT 1
                        """
                    ),
                    {"iid": interaction_id},
                )
            )
            if ident and ident["status"] == "verified":
                raise ValueError("identity_locked")
            if read:
                cust = _one(
                    conn.execute(
                        text("SELECT customer_id FROM interactions WHERE id = :id"),
                        {"id": interaction_id},
                    )
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO identity_verifications (
                          id, interaction_id, customer_id, method, status,
                          attempt_count, verified_at
                        ) VALUES (
                          :id, :iid, :cid, 'manual', 'verified', 1, now()
                        )
                        """
                    ),
                    {
                        "id": _id("IV"),
                        "iid": interaction_id,
                        "cid": cust["customer_id"],
                    },
                )
            rule_id = rule_id or "rule-identity"
            label = label or "Identity verified"
        if not label:
            for rid, lbl in _HANDOFF_DISCLOSURE_RULES:
                if rid == rule_id or rid == item_id:
                    label = lbl
                    rule_id = rid
                    break
            if item_id == "dnd-consent":
                label = "DND & consent window checked"
        if not label:
            raise ValueError("disclosure_label_required")
        existing = None
        if item_id and not item_id.startswith("rule-") and item_id not in {"identity", "dnd-consent"}:
            existing = _one(
                conn.execute(
                    text(
                        """
                        SELECT id FROM interaction_disclosures
                        WHERE id = :id AND interaction_id = :iid
                        """
                    ),
                    {"id": item_id, "iid": interaction_id},
                )
            )
        if existing:
            conn.execute(
                text(
                    """
                    UPDATE interaction_disclosures
                    SET read = :read, read_at_sec = COALESCE(read_at_sec, 0),
                        read_by_kind = 'human', read_by_user_id = :uid, read_by_bot_id = NULL
                    WHERE id = :id
                    """
                ),
                {"id": existing["id"], "read": read, "uid": actor},
            )
        else:
            conn.execute(
                text(
                    """
                    INSERT INTO interaction_disclosures (
                      id, interaction_id, rule_id, label, read, read_at_sec,
                      read_by_kind, read_by_user_id
                    ) VALUES (
                      :id, :iid, :rule_id, :label, :read, 0, 'human', :uid
                    )
                    """
                ),
                {
                    "id": _id("DISC"),
                    "iid": interaction_id,
                    "rule_id": rule_id,
                    "label": label,
                    "read": read,
                    "uid": actor,
                },
            )
    return get_handoff_session(interaction_id)


def accept_handoff_suggestion(interaction_id: str, suggestion_id: str) -> dict[str, Any]:
    actor = _actor_user_id()
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "interactions", interaction_id)
        _assert_handoff_assignee(conn, interaction_id, actor)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM ai_response_suggestions
                    WHERE id = :sid
                      AND (interaction_id = :iid OR conversation_id IN (
                            SELECT id FROM conversations WHERE interaction_id = :iid
                          ))
                    """
                ),
                {"sid": suggestion_id, "iid": interaction_id},
            )
        )
        if row is None:
            raise KeyError("suggestion_not_found")
        conn.execute(
            text(
                """
                UPDATE ai_response_suggestions
                SET accepted = true,
                    accepted_by_user_id = :uid,
                    accepted_at = now()
                WHERE id = :id
                """
            ),
            {"id": suggestion_id, "uid": actor},
        )
    return get_handoff_session(interaction_id)


def _assert_handoff_assignee(conn: Any, interaction_id: str, actor: str) -> None:
    row = _one(
        conn.execute(
            text(
                """
                SELECT i.handler_user_id, h.to_user_id
                FROM interactions i
                LEFT JOIN LATERAL (
                  SELECT to_user_id FROM interaction_handoffs
                  WHERE interaction_id = i.id
                  ORDER BY requested_at DESC NULLS LAST, created_at DESC
                  LIMIT 1
                ) h ON true
                WHERE i.id = :id
                """
            ),
            {"id": interaction_id},
        )
    )
    if row is None:
        raise KeyError("interaction_not_found")
    if row["handler_user_id"] != actor and row["to_user_id"] != actor:
        raise PermissionError("handoff_not_assigned")


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


# activity_events.kind → the LeadEventKind the UI timeline renders. Anything
# not listed is still shown, with its raw kind, rather than dropped: an
# unmapped event is a labelling gap, not a reason to hide history.
_LEAD_EVENT_KINDS: dict[str, str] = {
    "lead_created": "created",
    "lead_updated": "stage_moved",
    "lead_stage_moved": "stage_moved",
    "lead_assigned": "assigned",
    "lead_team_changed": "team_changed",
    "lead_offer_edited": "offer_edited",
    "lead_followup_created": "followup_scheduled",
    # Rendered as a scheduling event rather than a new timeline vocabulary
    # word: the note carries "Follow-up overdue" and the channel and time, so
    # the reader loses nothing, and the UI's LeadEventKind union stays closed.
    "lead_followup_overdue": "followup_scheduled",
    "followup_updated": "followup_done",
    "lead_won": "won",
    "lead_lost": "lost",
    "lead_eligibility_revalidated": "eligibility_revalidated",
}


def _lead_events(conn: Any, lead_id: str) -> list[dict[str, Any]]:
    """Real audit trail for a lead, from activity_events.

    The list and detail endpoints both used to synthesise a single "created"
    entry from the lead row, so the Timeline tab — an audit surface — never
    showed a stage move, a reassignment or an offer edit. Every one of those
    mutations has been writing an activity_events row all along.
    """
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.at, ae.kind, ae.label, ae.note, ae.actor_kind,
                       u.name AS user_name, b.name AS bot_name
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                LEFT JOIN bots b ON b.id = ae.actor_bot_id
                WHERE ae.entity_type = 'lead' AND ae.entity_id = :id
                  -- See _lead_events_bulk: lead_captured duplicates the fact
                  -- lead_created already records on this timeline.
                  AND ae.kind <> 'lead_captured'
                ORDER BY ae.at DESC, ae.id DESC
                LIMIT 100
                """
            ),
            {"id": lead_id},
        )
    )
    return [_lead_event(row) for row in rows]


def _lead_followups(conn: Any, lead_id: str) -> list[dict[str, Any]]:
    return _rows(
        conn.execute(
            text(
                """
                SELECT id, due_at AS at, COALESCE(channel, 'voice') AS channel, note, status = 'done' AS done
                FROM followups
                WHERE lead_id = :lead_id
                ORDER BY due_at
                """
            ),
            {"lead_id": lead_id},
        )
    )


def _lead_followups_bulk(conn: Any, lead_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Follow-ups for many leads in one round trip.

    The list endpoint renders every lead on the board; per-lead queries here
    would be 2N round trips on a screen that already loads the whole pipeline.
    """
    if not lead_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT lead_id, id, due_at AS at, COALESCE(channel, 'voice') AS channel, note,
                       status = 'done' AS done
                FROM followups
                WHERE lead_id = ANY(:ids)
                ORDER BY lead_id, due_at
                """
            ),
            {"ids": lead_ids},
        )
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        out.setdefault(row.pop("lead_id"), []).append(row)
    return out


def _lead_events_bulk(conn: Any, lead_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Audit trail for many leads in one round trip."""
    if not lead_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT ae.entity_id, ae.at, ae.kind, ae.label, ae.note, ae.actor_kind,
                       u.name AS user_name, b.name AS bot_name
                FROM activity_events ae
                LEFT JOIN users u ON u.id = ae.actor_user_id
                LEFT JOIN bots b ON b.id = ae.actor_bot_id
                WHERE ae.entity_type = 'lead' AND ae.entity_id = ANY(:ids)
                  -- lead_captured is the offer funnel's numerator, written for
                  -- the same act that writes lead_created. Both belong in the
                  -- table; showing both in the drawer would put "Lead created"
                  -- on the timeline twice.
                  AND ae.kind <> 'lead_captured'
                ORDER BY ae.entity_id, ae.at DESC, ae.id DESC
                """
            ),
            {"ids": lead_ids},
        )
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        bucket = out.setdefault(row["entity_id"], [])
        # Cap per lead: the board only ever renders a preview, and one
        # pathologically-edited lead must not dominate the response.
        if len(bucket) >= 50:
            continue
        bucket.append(_lead_event(row))
    return out


def _lead_event(row: dict[str, Any]) -> dict[str, Any]:
    by = row["user_name"] or row["bot_name"]
    if not by:
        by = "System"
    return {
        "at": row["at"],
        "kind": _LEAD_EVENT_KINDS.get(row["kind"], row["kind"]),
        "by": by,
        "note": row["note"] or row["label"],
    }


def _next_followup_at(followups: list[dict[str, Any]]) -> Any:
    """First OPEN follow-up. followups[0] was wrong: a completed one still
    sorts first by due_at, so the UI advertised a past, already-done call as
    the next action."""
    for f in followups:
        if not f.get("done"):
            return f.get("at")
    return None


def _lead_by_id(conn: Any, lead_id: str) -> dict[str, Any]:
    row = _one(
        conn.execute(
            text(
                """
                SELECT l.id, l.customer_id, c.name AS customer_name, l.account_id, l.product_id,
                       p.name AS product, l.stage, l.source, l.sentiment_at_capture,
                       l.sentiment_score, l.estimated_value, l.offer_amount, l.offer_roi,
                       l.priority, l.captured_at, l.closed_at, l.interaction_id,
                       l.transcript_snippet,
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
    followups = _lead_followups(conn, lead_id)
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
            nextFollowUpAt=_next_followup_at(followups),
            followUps=followups,
            events=_lead_events(conn, lead_id),
            closedAt=row["closed_at"],
            wonAmount=row["won_amount"],
            lossReason=row["loss_reason"],
        )
    )


def create_promise(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = "POST /promises"
    with engine.begin() as conn:
        return _create_promise(conn, payload, idempotency_key, endpoint)


def _create_promise(
    conn: Any,
    payload: dict[str, Any],
    idempotency_key: str | None,
    endpoint: str,
) -> dict[str, Any]:
    """Connection-scoped body of :func:`create_promise`.

    Callers that already hold a transaction (payment plans, interaction wrap-up)
    must spawn the promise inside it. Re-entering ``engine.begin()`` there took
    a second pooled connection and committed independently, so a failure in the
    caller's remaining work left an orphan promise the caller believed it had
    rolled back — and a retry then created a second one.
    """
    cached = _idempotent_response(conn, idempotency_key, endpoint)
    if cached:
        try:
            import promise_fulfillment

            pid = cached.get("id")
            if pid:
                fulfillment = promise_fulfillment.fulfill(conn, pid)
                cached = dict(cached)
                cached["_fulfillment"] = fulfillment.as_dict()
                cached["_spoken"] = fulfillment.spoken_summary
        except Exception:
            logger.exception("ptp fulfill on idempotent replay failed promise=%s", cached.get("id"))
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
            raise OwnerBotNotFound(f"bot_not_found: {owner_bot_id}")
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
            "promised_at": clock.local_midnight(payload["promisedDate"]),
            "reminder_status": payload.get("reminderStatus") or "queued",
            "channel": payload.get("channel") or "voice",
        },
    )
    _activity(conn, "promise", promise_id, "promise_created", "Promise-to-pay captured", f"Amount {payload['amount']}", customer_id)
    fulfillment = None
    fulfillment_error: str | None = None
    try:
        import promise_fulfillment

        # A savepoint: a fulfiller that raised mid-statement used to abort the
        # caller's transaction, so the promise row -- inserted above, on the
        # same connection -- was lost with it while this function reported the
        # promise as created. The promise is the regulated record; the
        # reminder schedule is derived from it and may be retried.
        with conn.begin_nested():
            fulfillment = promise_fulfillment.fulfill(conn, promise_id)
    except Exception as exc:
        logger.exception("ptp fulfill failed promise=%s", promise_id)
        fulfillment_error = f"{type(exc).__name__}: {exc}"
    response = _promise_by_id(conn, promise_id)
    if fulfillment is not None:
        response["_fulfillment"] = fulfillment.as_dict()
        response["_spoken"] = fulfillment.spoken_summary
    elif fulfillment_error:
        response["_fulfillment"] = {"error": fulfillment_error}
    _store_idempotent_response(conn, idempotency_key, endpoint, response)
    return response


def patch_promise(promise_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "promises", promise_id)
        row = _one(
            conn.execute(
                text("SELECT status, customer_id, amount, paid_amount FROM promises WHERE id = :id"),
                {"id": promise_id},
            )
        )
        if row is None:
            raise KeyError("promise_not_found")
        next_status = payload.get("status")
        if row["status"] == "kept" and next_status in {"broken", "partial"}:
            raise ValueError("kept promise cannot move to broken/partial")
        if next_status == "kept":
            current_paid = float(row["paid_amount"] or 0)
            if current_paid < float(row["amount"] or 0):
                raise ValueError("kept_requires_payment")
        updates = []
        params = {"id": promise_id}
        if next_status:
            updates.append("status = :status")
            # `upcoming` is stored as `upcoming`. "Due today" is a fact about
            # `promised_at` and the calendar, not a status the client can
            # express; writing it here produced rows no schema could read back.
            params["status"] = next_status
        if payload.get("promisedDate"):
            updates.append("promised_at = :promised_at")
            params["promised_at"] = clock.local_midnight(payload["promisedDate"])
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


def resend_promise_confirm(promise_id: str) -> dict[str, Any]:
    """Re-enqueue the written PTP confirm on the existing open intent."""
    import promise_fulfillment

    with engine.begin() as conn:
        _assert_tenant_owns(conn, "promises", promise_id)
        result = promise_fulfillment.fulfill(conn, promise_id, resend=True)
        row = _promise_by_id(conn, promise_id)
        row["_fulfillment"] = result.as_dict()
        row["_spoken"] = result.spoken_summary
        return row


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
        # Same transaction as the plan and its installments: the first
        # instalment's promise is part of the plan, not an independently
        # committed row that survives a rollback of everything around it.
        promise = _create_promise(
            conn,
            {
                "customerId": customer_id,
                "accountId": account_id,
                "amount": first.get("amount", payload["totalAmount"]),
                "promisedDate": first.get("dueDate"),
                "channel": "voice",
            },
            None,
            "POST /promises",
        )
        conn.execute(text("UPDATE promises SET plan_id = :plan_id WHERE id = :id"), {"plan_id": plan_id, "id": promise["id"]})
        _activity(conn, "payment_plan", plan_id, "payment_plan_created", "Payment plan created", None, customer_id)
        return {"id": plan_id, "promise": _promise_by_id(conn, promise["id"])}


def create_dispute(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = "POST /disputes"
    with engine.begin() as conn:
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


def patch_dispute(dispute_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write,
    so an explicit None clears the column (used to unassign)."""
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "disputes", dispute_id)
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
    with engine.begin() as conn:
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


def create_callback(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
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


def patch_callback(callback_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write,
    so an explicit None clears assignee_user_id (unassign)."""
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "callbacks", callback_id)
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT cb.customer_id, c.dnd AS customer_dnd, c.preferred_window,
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


# Product category → sales team. A lead for a policy must not land in the
# retail-loan queue simply because "retail-sales" was the hardcoded default on
# every bot-captured row.
_TEAM_BY_CATEGORY: dict[str, str] = {
    "insurance": "insurance",
    "card": "cards-sales",
    "loan": "retail-sales",
    "deposit": "retail-sales",
}
_DEFAULT_LEAD_TEAM = "retail-sales"

# Stages in which a lead is still being worked. A second lead for the same
# product while one of these is open is a duplicate, not a new opportunity.
OPEN_LEAD_STAGES = ("interested", "contacted", "qualified")


def find_open_lead(conn: Any, customer_id: str, product_id: str) -> dict[str, Any] | None:
    """An existing in-flight lead for this customer/product, if any."""
    return _one(
        conn.execute(
            text(
                """
                SELECT id, stage, captured_at
                FROM leads
                WHERE customer_id = :cid AND product_id = :pid
                  AND stage = ANY(:stages)
                ORDER BY captured_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id, "pid": product_id, "stages": list(OPEN_LEAD_STAGES)},
        )
    )


def _route_team_id(conn: Any, product_id: str, explicit: str | None) -> str | None:
    """Team that should own this lead. Explicit wins; otherwise route by
    product category, and fall back to NULL rather than an id that does not
    exist — a bad team_id is an IntegrityError, i.e. an HTTP 500 on a write
    that had nothing wrong with it."""
    candidate = explicit
    if not candidate:
        row = _one(
            conn.execute(
                text("SELECT category, type FROM products WHERE id = :id"), {"id": product_id}
            )
        )
        key = ((row or {}).get("category") or (row or {}).get("type") or "").strip().lower()
        candidate = _TEAM_BY_CATEGORY.get(key, _DEFAULT_LEAD_TEAM)
    exists = _one(
        conn.execute(text("SELECT id FROM teams WHERE id = :id"), {"id": candidate})
    )
    if exists:
        return candidate
    if candidate != _DEFAULT_LEAD_TEAM:
        fallback = _one(
            conn.execute(
                text("SELECT id FROM teams WHERE id = :id"), {"id": _DEFAULT_LEAD_TEAM}
            )
        )
        if fallback:
            return _DEFAULT_LEAD_TEAM
    logger.warning("lead routing: no team row for %r — leaving unassigned", candidate)
    return None


def create_lead(
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    *,
    allow_duplicate: bool = False,
    emitted: list[str] | None = None,
) -> dict[str, Any]:
    """Capture a lead. ``emitted`` is an out-parameter: the names of the
    analytics events that actually landed.

    The bot tool reports those names back to the model, and it must not claim
    an event whose row was never written — so the fact has to travel out of
    here rather than being assumed by the caller. It is not part of the API
    response because it is not part of the lead.
    """
    endpoint = "POST /leads"
    with engine.begin() as conn:
        # Same contract as create_promise / create_dispute / create_callback.
        # capture_lead was the one CRM write with no replay protection, so a
        # retried tool call — the single most common thing an LLM does — put two
        # identical leads in the pipeline and two reps on the phone.
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached

        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        lead_id = _id("LD")
        product_id = payload.get("productId")
        if not product_id:
            raise ValueError("productId_required")

        # Validate before INSERT: a bad product id would otherwise surface as an
        # unhandled IntegrityError (HTTP 500) instead of a 409 the caller can act on.
        product = _one(
            conn.execute(
                text("SELECT id, name, category, ticket_min, ticket_max, roi FROM products WHERE id = :id"),
                {"id": product_id},
            )
        )
        if product is None:
            raise ValueError("product_not_found")

        if not allow_duplicate:
            # Serialise concurrent capture of the same (customer, product): the
            # voice tool and the WhatsApp worker are genuinely concurrent
            # writers, so a plain SELECT-then-INSERT races. Transaction-scoped,
            # released on commit — same pattern as _idempotent_response.
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtext('lead'), hashtext(:k))"),
                {"k": f"{customer_id}:{product_id}"},
            )
            existing = find_open_lead(conn, customer_id, product_id)
            if existing:
                raise ValueError(f"duplicate_open_lead:{existing['id']}")

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
            {
                "id": lead_id,
                "customer_id": customer_id,
                "account_id": payload.get("accountId") or _first_account_id(conn, customer_id),
                "interaction_id": payload.get("interactionId"),
                "product_id": product_id,
                # A bot has no user identity; falling back to the API actor made
                # every bot-captured lead look like it was raised by whichever
                # service account happened to be configured.
                "owner_user_id": payload.get("ownerUserId"),
                "team_id": _route_team_id(conn, product_id, payload.get("teamId")),
                "stage": payload.get("stage") or "interested",
                "source": payload.get("source") or "agent",
                "sentiment_at_capture": payload.get("sentimentAtCapture") or "neutral",
                "sentiment_score": payload.get("sentimentScore"),
                # estimated_value drives every money figure on the board. A NULL
                # here rendered as ₹NaN column subtotals and crashed the lead
                # card outright, so it falls back to the offer amount and then to
                # the product's ticket floor rather than staying empty.
                "estimated_value": (
                    payload.get("estimatedValue")
                    if payload.get("estimatedValue") is not None
                    else payload.get("offerAmount")
                    if payload.get("offerAmount") is not None
                    else product.get("ticket_min")
                ),
                "offer_amount": payload.get("offerAmount"),
                "offer_roi": payload.get("offerRoi") or product.get("roi"),
                "priority": payload.get("priority") or "normal",
                "transcript_snippet": payload.get("transcriptSnippet"),
            },
        )
        # Phase 2-lite: persist evaluated eligibility (honest unknown for bureau/KYC).
        # Savepoint: a capture failure must not abort the lead write + trailing activity.
        try:
            import capture

            with conn.begin_nested():
                flags = payload.get("eligibilityFlags")
                if not isinstance(flags, list):
                    flags = capture.evaluate_product_eligibility(
                        conn,
                        customer_id=customer_id,
                        product_id=product_id,
                        channel=payload.get("channel"),
                    )
                capture.insert_lead_eligibility(conn, lead_id=lead_id, flags=flags)
                if payload.get("interactionId"):
                    # A captured lead genuinely IS a presented offer, so the
                    # flag belongs here. What it must NOT be tied to is a bare
                    # eligibility probe — see voice/tools.py.
                    capture.mark_upsell_presented(conn, payload.get("interactionId"))
                    capture.touch_primary_intent(conn, payload.get("interactionId"), "upsell_opportunity")
        except Exception:
            logger.exception("lead eligibility capture failed for %s", lead_id)
        # The offer funnel's numerator. This lives here, in the one function
        # every capture path goes through, rather than in the bot tool that
        # used to own it: a lead captured from the UI — including the "Capture
        # lead" button on a decision the engine itself recommended — emitted
        # only `lead_created`, which nothing counts. The funnel's denominator
        # (close_probe_presented) came from the call and its numerator came
        # from one caller of three, so close-probe conversion was structurally
        # understated and no arithmetic on it meant anything.
        #
        # Its own savepoint: an eligibility failure above must not swallow the
        # funnel event, and a funnel-event failure must not lose the lead.
        try:
            import capture

            with conn.begin_nested():
                bot_id = payload.get("actorBotId")
                capture.record_lead_captured(
                    conn,
                    interaction_id=payload.get("interactionId"),
                    lead_id=lead_id,
                    product_id=product_id,
                    actor_bot_id=bot_id,
                    actor_user_id=None if bot_id else _actor_user_id(),
                )
            if emitted is not None:
                emitted.append("lead_captured")
        except Exception:
            logger.exception("lead_captured event failed for %s", lead_id)
        _activity(conn, "lead", lead_id, "lead_created", "Lead created", None, customer_id)
        decision_id = payload.get("decisionId")
        if decision_id:
            try:
                conn.execute(
                    text(
                        """
                        UPDATE offer_decisions
                        SET lead_id = :lead_id,
                            response = COALESCE(response, 'interested'),
                            responded_at = COALESCE(responded_at, now()),
                            presented = true,
                            presented_at = COALESCE(presented_at, now())
                        WHERE id = :id AND tenant_id = :tenant
                        """
                    ),
                    {"id": decision_id, "lead_id": lead_id, "tenant": _tenant()},
                )
                # W12: the same label into the absorbed log. This is the third
                # writer of an offer response and the one most easily missed --
                # it is not in `agent_core/reco/` at all.
                from agent_core.reco import decisions as reco_decisions

                reco_decisions.mirror_update(
                    conn,
                    "lead_id = :lead_id,"
                    " offer_response = COALESCE(offer_response, 'interested'),"
                    " responded_at = COALESCE(responded_at, now()),"
                    " presented = true,"
                    " presented_at = COALESCE(presented_at, now())",
                    {"id": decision_id, "lead_id": lead_id},
                )
            except Exception:
                logger.exception("attach_lead failed for decision %s", decision_id)
        response = _lead_by_id(conn, lead_id)
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response


# A lead's stage is a state machine, not a free-text column. Without this any
# stage could be written over any other — including straight from 'interested'
# to 'won' with no amount, or back out of a closed stage silently.
_LEAD_STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "interested": frozenset({"contacted", "qualified", "won", "lost"}),
    "contacted": frozenset({"interested", "qualified", "won", "lost"}),
    "qualified": frozenset({"interested", "contacted", "won", "lost"}),
    # Closed stages reopen only deliberately: won↔lost corrects a mis-click,
    # and either can be pulled back into the pipeline for re-engagement.
    "won": frozenset({"lost", "interested"}),
    "lost": frozenset({"won", "interested"}),
}
_CLOSED_LEAD_STAGES = frozenset({"won", "lost"})


def offer_decision_exists(decision_id: str) -> bool:
    """Whether this tenant has an offer decision with that id.

    Tenant-scoped, so an id guessed or leaked from another tenant reads as
    absent rather than as labellable. The route above returns 404 on False:
    without it a caller could POST a response for an hour and silently label
    nothing, which is exactly the failure mode that left `offer_decisions` with
    zero responses in the first place.
    """
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text(
                    "SELECT 1 FROM offer_decisions"
                    " WHERE id = :id AND tenant_id = :tenant"
                ),
                {"id": decision_id, "tenant": _tenant()},
            ).first()
        )


def patch_lead(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "leads", lead_id)
        row = _one(
            conn.execute(
                text(
                    "SELECT customer_id, product_id, stage, estimated_value, offer_amount"
                    " FROM leads WHERE id = :id"
                ),
                {"id": lead_id},
            )
        )
        if row is None:
            raise KeyError("lead_not_found")

        current_stage = row["stage"]
        next_stage = payload.get("stage")
        updates: list[str] = []
        params: dict[str, Any] = {"id": lead_id}
        events: list[tuple[str, str, str | None]] = []  # (kind, label, note)

        if next_stage and next_stage != current_stage:
            allowed = _LEAD_STAGE_TRANSITIONS.get(current_stage, frozenset())
            if next_stage not in allowed:
                raise ValueError(f"invalid_stage_transition:{current_stage}->{next_stage}")

            if next_stage == "lost" and not (payload.get("lossReason") or "").strip():
                # A loss with no reason is a data point that teaches nobody
                # anything, and it is what the loss-reason breakdown reports on.
                raise ValueError("loss_reason_required")

            updates.append("stage = :stage")
            params["stage"] = next_stage

            if next_stage in _CLOSED_LEAD_STAGES:
                updates.append("closed_at = now()")
                if next_stage == "won" and payload.get("wonAmount") is None:
                    # Fall back to the pipeline value we have been reporting all
                    # along rather than closing a win worth NULL.
                    fallback = row["estimated_value"] or row["offer_amount"]
                    if fallback is not None:
                        updates.append("won_amount = :won_amount_default")
                        params["won_amount_default"] = fallback
            else:
                # Reopening: the close date is no longer true.
                updates.append("closed_at = NULL")

            events.append(
                (
                    "lead_won" if next_stage == "won" else "lead_lost" if next_stage == "lost" else "lead_stage_moved",
                    f"Lead moved to {next_stage}",
                    payload.get("lossReason") if next_stage == "lost" else next_stage,
                )
            )

        # Explicit-None means "clear this field". `is not None` made lossReason
        # and wonAmount permanently sticky once set.
        clearable = {"lossReason": "loss_reason", "wonAmount": "won_amount"}
        settable = {
            "productId": "product_id",
            "ownerUserId": "owner_user_id",
            "teamId": "team_id",
            "offerAmount": "offer_amount",
            "offerRoi": "offer_roi",
        }
        for key, column in {**settable, **clearable}.items():
            if key not in payload:
                continue
            value = payload[key]
            if value is None and key not in clearable:
                continue
            updates.append(f"{column} = :{column}")
            params[column] = value

        product_changed = bool(payload.get("productId")) and payload["productId"] != row["product_id"]
        if product_changed:
            product = _one(
                conn.execute(
                    text("SELECT id FROM products WHERE id = :id"), {"id": payload["productId"]}
                )
            )
            if product is None:
                raise ValueError("product_not_found")
            events.append(("lead_offer_edited", "Offer product changed", payload["productId"]))

        if payload.get("ownerUserId"):
            events.append(("lead_assigned", "Lead reassigned", payload["ownerUserId"]))
        if payload.get("teamId"):
            events.append(("lead_team_changed", "Lead routed to another team", payload["teamId"]))
        if payload.get("offerAmount") is not None and not product_changed:
            events.append(("lead_offer_edited", "Offer amount updated", str(payload["offerAmount"])))

        if updates:
            conn.execute(text(f"UPDATE leads SET {', '.join(updates)} WHERE id = :id"), params)

        # Switching the product invalidates every stored eligibility flag: they
        # describe the OLD product. Leaving them made the drawer show a green
        # "all checks passed" for a product that was never evaluated.
        if product_changed:
            try:
                import capture

                with conn.begin_nested():
                    flags = capture.evaluate_product_eligibility(
                        conn,
                        customer_id=row["customer_id"],
                        product_id=payload["productId"],
                        channel=payload.get("channel"),
                    )
                    capture.insert_lead_eligibility(conn, lead_id=lead_id, flags=flags)
            except Exception:
                logger.exception("lead eligibility re-evaluation failed for %s", lead_id)

        if not events:
            events.append(("lead_updated", "Lead updated", None))
        for kind, label, note in events:
            _activity(conn, "lead", lead_id, kind, label, note, row["customer_id"])
        return _lead_by_id(conn, lead_id)


def revalidate_lead_eligibility(lead_id: str, channel: str | None = None) -> dict[str, Any]:
    """Re-evaluate a lead's eligibility against today's facts.

    Eligibility was evaluated once, at capture, and never again — so a customer
    who opted out afterwards kept an actionable lead with a green badge on it.
    Called by the nightly sweep and by the drawer's refresh action.
    """
    import capture

    with engine.begin() as conn:
        row = _one(
            conn.execute(
                text("SELECT customer_id, product_id, stage FROM leads WHERE id = :id"),
                {"id": lead_id},
            )
        )
        if row is None:
            raise KeyError("lead_not_found")
        if not row["product_id"]:
            raise ValueError("lead_has_no_product")

        flags = capture.evaluate_product_eligibility(
            conn,
            customer_id=row["customer_id"],
            product_id=row["product_id"],
            channel=channel,
        )
        capture.insert_lead_eligibility(conn, lead_id=lead_id, flags=flags)
        blocked = capture.eligibility_blocks_capture(flags)
        _activity(
            conn,
            "lead",
            lead_id,
            "lead_eligibility_revalidated",
            "Eligibility re-checked" + (f" — blocked: {blocked}" if blocked else " — still eligible"),
            blocked,
            row["customer_id"],
        )
        return {"leadId": lead_id, "eligible": blocked is None, "blockReason": blocked, "flags": flags}


def revalidate_open_leads(limit: int = 500) -> dict[str, Any]:
    """Nightly sweep over open leads. Returns a compact report."""
    with engine.connect() as conn:
        ids = [
            r["id"]
            for r in _rows(
                conn.execute(
                    text(
                        "SELECT id FROM leads WHERE stage = ANY(:stages)"
                        " AND product_id IS NOT NULL ORDER BY captured_at DESC NULLS LAST LIMIT :lim"
                    ),
                    {"stages": list(OPEN_LEAD_STAGES), "lim": max(1, int(limit))},
                )
            )
        ]
    checked = 0
    blocked: list[str] = []
    for lead_id in ids:
        try:
            result = revalidate_lead_eligibility(lead_id)
        except Exception:
            logger.exception("revalidate failed for %s", lead_id)
            continue
        checked += 1
        if not result["eligible"]:
            blocked.append(lead_id)
    return {"checked": checked, "blocked": blocked, "blockedCount": len(blocked)}


def sweep_due_followups(limit: int = 500) -> dict[str, Any]:
    """Escalate lead follow-ups whose moment has passed.

    Nothing acted on a due follow-up. An agent scheduled a callback for Tuesday
    at 11:00, Tuesday came and went, and the row sat at ``normal`` priority
    among every other open item — the entire pipeline was a passive record that
    depended on a human noticing. This is the smallest honest fix: the system
    now notices.

    It deliberately does **not** contact anyone. Sending on a customer's behalf
    is a contact-policy decision with consent, calling hours and frequency caps
    attached to it, and a background sweep is the wrong place to make one
    silently. What it does is raise the work where a human will see it.

    Idempotent by construction: the only rows it touches are those not already
    at ``high``, so a second pass over the same follow-up is a no-op and no
    "already escalated" bookkeeping column is needed.
    """
    escalated: list[dict[str, Any]] = []
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT f.id, f.lead_id, f.customer_id, f.due_at, f.channel
                    FROM followups f
                    JOIN leads l ON l.id = f.lead_id
                    WHERE f.status IN ('open', 'in_progress')
                      AND f.priority <> 'high'
                      AND f.due_at <= now()
                      AND l.stage = ANY(:stages)
                    ORDER BY f.due_at
                    LIMIT :lim
                    FOR UPDATE OF f SKIP LOCKED
                    """
                ),
                {"stages": list(OPEN_LEAD_STAGES), "lim": max(1, int(limit))},
            )
        )
        for row in rows:
            conn.execute(
                text("UPDATE followups SET priority = 'high', updated_at = now() WHERE id = :id"),
                {"id": row["id"]},
            )
            # The lead carries the priority the board sorts and colours by, so
            # escalating only the follow-up would raise the work in the queue
            # and leave it looking routine on the pipeline.
            conn.execute(
                text(
                    "UPDATE leads SET priority = 'high', updated_at = now()"
                    " WHERE id = :id AND priority IN ('low', 'normal')"
                ),
                {"id": row["lead_id"]},
            )
            _activity(
                conn,
                "lead",
                row["lead_id"],
                "lead_followup_overdue",
                "Follow-up overdue",
                # _rows already serialises timestamps to ISO strings — do not
                # reach for strftime here.
                f"{row['channel']} follow-up was due {row['due_at']}",
                row["customer_id"],
            )
            escalated.append({"followupId": row["id"], "leadId": row["lead_id"]})
    return {"escalated": len(escalated), "leads": [e["leadId"] for e in escalated]}


def _lead_followup_channel(channel: str | None) -> str:
    if channel in {"voice", "whatsapp", "email", "sms"}:
        return channel
    return "voice"


def _parse_followup_due(scheduled_at: Any) -> datetime:
    """Resolve the requested slot to an aware UTC instant.

    Parsed rather than passed through as a string because the contact-policy
    check needs an actual moment to convert into the customer's local time —
    "is 03:00 inside the calling window" is not a question you can ask of text.
    A missing or unparseable value means now, which is what the previous
    ``or datetime.now()`` fallback meant too.
    """
    if isinstance(scheduled_at, datetime):
        parsed = scheduled_at
    else:
        raw = str(scheduled_at or "").strip()
        if not raw:
            return datetime.now(timezone.utc)
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def add_lead_followup(lead_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "leads", lead_id)
        row = _one(conn.execute(text("SELECT customer_id, owner_user_id FROM leads WHERE id = :id"), {"id": lead_id}))
        if row is None:
            raise KeyError("lead_not_found")
        followup_id = _id("FU")
        channel = _lead_followup_channel(payload.get("channel"))
        due_at = _parse_followup_due(payload.get("scheduledAt"))

        # The sales side used to book touches the collections side would never
        # have been allowed to make. Nothing here consulted consent, DND or the
        # RBI 08:00–19:00 calling window, so a voice follow-up could be diaried
        # for 03:00 on an opted-out customer and the first person to find out
        # was the rep who dialled it.
        import contact_policy

        blocked = contact_policy.blocks_scheduling(
            conn, customer_id=row["customer_id"], channel=channel, at=due_at
        )
        if blocked:
            raise ValueError(f"contact_policy:{blocked}")

        conn.execute(
            text(
                """
                INSERT INTO followups (id, lead_id, customer_id, assignee_user_id, status, priority, due_at, note, channel)
                VALUES (:id, :lead_id, :customer_id, :assignee_user_id, 'open', 'normal', :due_at, :note, :channel)
                """
            ),
            {
                "id": followup_id,
                "lead_id": lead_id,
                "customer_id": row["customer_id"],
                "assignee_user_id": row["owner_user_id"] or _actor_user_id(),
                "due_at": due_at,
                "note": payload.get("note") or "Lead follow-up",
                "channel": channel,
            },
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


def create_document_request(
    payload: dict[str, Any], idempotency_key: str | None = None
) -> dict[str, Any]:
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


def _incoming_window_days(aw: dict[str, Any]) -> list[int] | None:
    if "days" not in aw:
        return None
    try:
        return sorted(int(d) for d in (aw.get("days") or []))
    except (TypeError, ValueError):
        return None


def _incoming_window_hours(aw: dict[str, Any]) -> tuple[int, int] | None:
    """GET always sends both hours. Missing hours are not filled with 10–19."""
    start = aw.get("startHour")
    end = aw.get("endHour")
    if start is None or end is None:
        return None
    try:
        return (int(start), int(end))
    except (TypeError, ValueError):
        return None


def _window_days_echo_stored(incoming_days: list[int], allowed_days: str | None) -> bool:
    """True when ``incoming_days`` is the GET serializer's view of ``allowed_days``.

    Writing that view reformats the text: an en-dash ``Mon–Sat`` becomes
    ``Mon-Mon``. The parser that produces that artefact is WP-030; this only
    refuses to persist it. Decided per field so an hours edit cannot rewrite days.
    """
    return incoming_days == sorted(_parse_allowed_days(allowed_days))


def _window_hours_echo_stored(incoming_hours: tuple[int, int], hours_raw: str | None) -> bool:
    """True when ``incoming_hours`` is the GET serializer's view of the stored hours.

    Writing that view turns a NULL window into ``10:00-19:00 IST`` and drops
    minutes from a stored ``08:30-17:45 IST``. The parser is WP-030.
    """
    return incoming_hours == _parse_allowed_hours(hours_raw)


def patch_consent(customer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write.

    ``allowedWindow`` is the exception: the consent screen used to echo the GET
    serializer on every save, so a present key may be a round-trip of the stored
    text rather than an operator edit. Each field whose parsed value matches the
    stored string is left byte-identical; only a real edit is written.
    """
    with engine.begin() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
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
            if not isinstance(aw, dict):
                aw = aw.model_dump() if hasattr(aw, "model_dump") else dict(aw)
            stored = _one(
                conn.execute(
                    text(
                        """
                        SELECT cr.allowed_days, cr.allowed_hours, c.preferred_window
                        FROM consent_records cr
                        JOIN customers c ON c.id = cr.customer_id
                        WHERE cr.id = :id
                        """
                    ),
                    {"id": consent_id},
                )
            )
            days_raw = stored["allowed_days"] if stored else None
            # GET uses allowed_hours, then preferred_window. Match that view so
            # a round-trip of either column is recognised as an echo.
            hours_raw = (stored["allowed_hours"] or stored["preferred_window"]) if stored else None
            incoming_days = _incoming_window_days(aw)
            incoming_hours = _incoming_window_hours(aw)
            # Preserve each stored string when its parsed value round-trips
            # unchanged. A whole-window skip still rewrote days on an hours
            # edit (Mon–Sat → Mon-Mon) and hours on a days edit.
            if incoming_days is not None and not _window_days_echo_stored(
                incoming_days, days_raw
            ):
                conn.execute(
                    text("UPDATE consent_records SET allowed_days = :days WHERE id = :id"),
                    {"days": _format_allowed_days(incoming_days), "id": consent_id},
                )
            if incoming_hours is not None and not _window_hours_echo_stored(
                incoming_hours, hours_raw
            ):
                hours_str = _format_allowed_hours(*incoming_hours)
                conn.execute(
                    text("UPDATE consent_records SET allowed_hours = :hours WHERE id = :id"),
                    {"hours": hours_str, "id": consent_id},
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
            # Servicing unless the screen says otherwise. This is the only way a
            # promotional consent can be captured, and it has to exist: a gate
            # nobody can satisfy is not a compliance control, it is an outage
            # with a paragraph number attached.
            purpose = str(item.get("purpose") or "servicing").strip().lower()
            if purpose not in ("servicing", "promotional"):
                purpose = "servicing"
            params: dict[str, Any] = {
                "id": f"{consent_id}-{channel_value}-{purpose}",
                "consent_id": consent_id,
                "channel": channel_value,
                "purpose": purpose,
                "status": status,
                "source": source,
                "cap": cap,
            }
            conn.execute(
                text(
                    """
                    INSERT INTO channel_consents
                      (id, consent_id, channel, purpose, status, source,
                       weekly_frequency_cap, used_this_week, captured_at)
                    VALUES
                      (:id, :consent_id, :channel, :purpose, :status, :source,
                       COALESCE(:cap, 3), 0, now())
                    ON CONFLICT (consent_id, channel, purpose)
                    DO UPDATE SET
                      status = EXCLUDED.status,
                      source = EXCLUDED.source,
                      weekly_frequency_cap = COALESCE(:cap, channel_consents.weekly_frequency_cap),
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
        # On the consent chain: what was written, hashed, so a later edit of
        # the row is visible against the last authorised one.
        from agent_core import change_log

        change_log.record_consent_change(
            conn,
            tenant_id=current_tenant(),
            actor_user_id=_actor_user_id(),
            customer_id=customer_id,
            change={"kind": kind, "fields": {k: v for k, v in payload.items() if k != "note"}},
        )

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
            # An opt-out closes **both** purposes, and closes the promotional
            # one even where no promotional consent was ever captured.
            #
            # Somebody who says "stop contacting me" has not opted out of
            # servicing while leaving marketing open, and reading it that way
            # would be the most self-serving construction available. The
            # promotional row is inserted rather than merely updated so that a
            # later promotional capture has an explicit opt-out to overwrite,
            # deliberately, rather than an absence to fill in.
            for consent_purpose in ("servicing", "promotional"):
                conn.execute(
                    text(
                        """
                        INSERT INTO channel_consents
                          (id, consent_id, channel, purpose, status, source, captured_at)
                        VALUES
                          (:id, :consent_id, :channel, :purpose, 'opted_out', :source, now())
                        ON CONFLICT (consent_id, channel, purpose)
                        DO UPDATE SET status = 'opted_out', source = EXCLUDED.source,
                                      captured_at = EXCLUDED.captured_at
                        """
                    ),
                    {
                        "id": f"{consent_id}-{channel_value}-{consent_purpose}",
                        "consent_id": consent_id,
                        "channel": channel_value,
                        "purpose": consent_purpose,
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
        from agent_core import change_log

        change_log.record_consent_change(
            conn,
            tenant_id=current_tenant(),
            actor_user_id=_actor_user_id(),
            customer_id=customer_id,
            change={"kind": "opt_out", "channel": channel_raw, "source": source},
        )
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
# QA Scorecards — rubric-driven scoring queue (scorecard core MVP).
# Coaching / calibration stay seed-backed until their endpoints land.
# ---------------------------------------------------------------------------



















































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
            {"id": interaction_id, "tenant_id": _tenant(), "customer_id": customer_id, "account_id": payload.get("accountId") or _first_account_id(conn, customer_id), "handler_kind": handler_kind, "handler_user_id": handler_user_id, "handler_bot_id": handler_bot_id, "channel": payload.get("channel") or "voice", "direction": payload.get("direction") or "outbound", "disposition": payload.get("disposition"), "summary": payload.get("summary")},
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
        _assert_tenant_owns(conn, "interactions", interaction_id)
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        interaction = _ensure_interaction(conn, interaction_id)
        conn.execute(
            text(
                """
                UPDATE interactions
                SET disposition = :disposition,
                    summary = COALESCE(:notes, summary),
                    status = 'completed',
                    ended_at = COALESCE(ended_at, now()),
                    ptp_captured = ptp_captured OR :ptp,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": interaction_id,
                "disposition": payload["disposition"],
                "notes": payload.get("notes"),
                "ptp": bool(payload.get("promise")),
            },
        )
        conn.execute(
            text(
                """
                UPDATE interaction_handoffs
                SET completed_at = now()
                WHERE interaction_id = :id AND completed_at IS NULL
                """
            ),
            {"id": interaction_id},
        )
        for flag in payload.get("flags") or []:
            conn.execute(text("INSERT INTO interaction_flags (id, interaction_id, flag, severity) VALUES (:id, :interaction_id, :flag, 'medium')"), {"id": _id("FLAG"), "interaction_id": interaction_id, "flag": flag})
        spawned: dict[str, Any] = {}
        # Connection-scoped: a wrap-up spawning a promise, a dispute and a
        # callback is one atomic outcome. The public create_* entrypoints open
        # their own transaction, so a failure after the second spawn used to
        # leave the first two committed while the wrap-up itself rolled back —
        # and the idempotent replay then spawned them a second time.
        if payload.get("promise"):
            promise_payload = {**payload["promise"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["promise"] = _create_promise(conn, promise_payload, None, "POST /promises")
        if payload.get("dispute"):
            dispute_payload = {**payload["dispute"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["dispute"] = _create_dispute(conn, dispute_payload, None, "POST /disputes")
        if payload.get("callback"):
            callback_payload = {**payload["callback"], "customerId": interaction["customer_id"], "accountId": interaction["account_id"], "interactionId": interaction_id}
            spawned["callback"] = _create_callback(conn, callback_payload)
        _activity(conn, "interaction", interaction_id, "interaction_wrapped_up", "Interaction wrapped up", payload.get("notes"), interaction["customer_id"])
        response = {"id": interaction_id, "spawned": spawned}
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response


# ---------------------------------------------------------------------------

# Phase 3B seed-chip close-out (coaching / calibration / redaction writes /
# routing writes / workspace rolling stats). Keep call sites as db.*.
# Redundant aliases are explicit re-exports so F401 does not treat them as dead.
# get_calibration_session stays in followups_db — only patch uses it.
# ---------------------------------------------------------------------------
from db_inbox import (  # noqa: E402
    INBOX_RAG_MIN_SCORE as INBOX_RAG_MIN_SCORE,
    _DELIVERY_RANK as _DELIVERY_RANK,
    _INBOX_RAG_COLLECTIONS_HINTS as _INBOX_RAG_COLLECTIONS_HINTS,
    _INBOX_RAG_MAX_TURN_CHARS as _INBOX_RAG_MAX_TURN_CHARS,
    _INBOX_RAG_NOISE as _INBOX_RAG_NOISE,
    _INBOX_RAG_TEST_MARKERS as _INBOX_RAG_TEST_MARKERS,
    _TYPING_STALE_AFTER as _TYPING_STALE_AFTER,
    _apply_whatsapp_status as _apply_whatsapp_status,
    _bot_typing_by_conversation as _bot_typing_by_conversation,
    _chip_from_result as _chip_from_result,
    _clip_inbox_rag_turn as _clip_inbox_rag_turn,
    _conversation_base_rows as _conversation_base_rows,
    _conversation_messages as _conversation_messages,
    _conversation_rag_query as _conversation_rag_query,
    _conversation_suggestions as _conversation_suggestions,
    _digits_phone_exact_sql as _digits_phone_exact_sql,
    _digits_phone_tail10_sql as _digits_phone_tail10_sql,
    _ensure_whatsapp_customer as _ensure_whatsapp_customer,
    _find_customer_by_phone as _find_customer_by_phone,
    _inbox_aging as _inbox_aging,
    _inbox_channel as _inbox_channel,
    _inbox_clock as _inbox_clock,
    _inbox_contactable as _inbox_contactable,
    _inbox_delivery as _inbox_delivery,
    _inbox_promise_status as _inbox_promise_status,
    _inbox_relative as _inbox_relative,
    _inbox_risk as _inbox_risk,
    _inbox_sentiment as _inbox_sentiment,
    _inbox_sla as _inbox_sla,
    _ingest_inbound_whatsapp_message as _ingest_inbound_whatsapp_message,
    _is_inbox_rag_noise as _is_inbox_rag_noise,
    _is_questionish as _is_questionish,
    _latest_twin_gate_report as _latest_twin_gate_report,
    _looks_collections_topic as _looks_collections_topic,
    _looks_like_pasted_draft as _looks_like_pasted_draft,
    _open_whatsapp_conversation as _open_whatsapp_conversation,
    _serialize_conversation as _serialize_conversation,
    _tail10_predicate as _tail10_predicate,
    _thread_context as _thread_context,
    _touch_interaction_sentiment as _touch_interaction_sentiment,
    create_kb_snapshot as create_kb_snapshot,
    escalate_conversation_to_human as escalate_conversation_to_human,
    find_customer_by_phone as find_customer_by_phone,
    get_conversation as get_conversation,
    get_latest_context_summary as get_latest_context_summary,
    get_latest_eval_report as get_latest_eval_report,
    handoff_to_agent as handoff_to_agent,
    list_bot_ids as list_bot_ids,
    list_canned_responses as list_canned_responses,
    list_conversations as list_conversations,
    list_eval_reports as list_eval_reports,
    list_eval_suites as list_eval_suites,
    list_kb_snapshots as list_kb_snapshots,
    process_whatsapp_webhook as process_whatsapp_webhook,
    refresh_conversation_suggestions as refresh_conversation_suggestions,
    return_conversation_to_bot as return_conversation_to_bot,
    save_context_summary as save_context_summary,
    save_eval_report as save_eval_report,
    send_conversation_message as send_conversation_message,
    takeover_conversation as takeover_conversation,
    touch_interaction_sentiment as touch_interaction_sentiment,
)

from db_billing import (  # noqa: E402
    _BILLING_ENVS as _BILLING_ENVS,
    _billing_as_of as _billing_as_of,
    billing_export_csv as billing_export_csv,
    billing_overview as billing_overview,
    delete_budget_rule as delete_budget_rule,
    interaction_cost as interaction_cost,
    upsert_budget_rule as upsert_budget_rule,
)

from db_treatment_holds import (  # noqa: E402
    HOLD_KINDS as HOLD_KINDS,
    HOLD_SOURCES as HOLD_SOURCES,
    apply_authority as apply_authority,
    create_treatment_hold as create_treatment_hold,
    list_treatment_cases as list_treatment_cases,
    list_treatment_holds as list_treatment_holds,
    next_authority as next_authority,
    next_treatment as next_treatment,
    release_treatment_hold as release_treatment_hold,
    treatment_insights as treatment_insights,
    treatment_metrics as treatment_metrics,
    treatment_model_health as treatment_model_health,
    treatment_models as treatment_models,
)

from db_dashboard import (  # noqa: E402
    _inr_compact as _inr_compact,
    get_dashboard as get_dashboard,
)

from db_workspace import (  # noqa: E402
    _enacted_by_map as _enacted_by_map,
    _inr as _inr,
    _work_item_sla as _work_item_sla,
    list_work_items as list_work_items,
)

from db_sandbox import (  # noqa: E402
    get_sandbox_run as get_sandbox_run,
    list_sandbox_scenarios as list_sandbox_scenarios,
)

from db_bot_analytics import (  # noqa: E402
    bot_analytics as bot_analytics,
)

from db_routing import (  # noqa: E402
    _routing_action_key as _routing_action_key,
    _routing_category as _routing_category,
    _routing_eval_condition as _routing_eval_condition,
    escalate_voice_interaction as escalate_voice_interaction,
    get_routing_rule as get_routing_rule,
    list_routing_rule_executions as list_routing_rule_executions,
    list_routing_rules as list_routing_rules,
)

from db_redaction import (  # noqa: E402
    actor_is_admin as actor_is_admin,
    get_redaction_record as get_redaction_record,
    get_redaction_rule as get_redaction_rule,
    list_redaction_records as list_redaction_records,
    list_redaction_rules as list_redaction_rules,
)

from db_kb import (  # noqa: E402
    KB_GAP_LIST_LIMIT as KB_GAP_LIST_LIMIT,
    KB_GAP_MAX_CHARS as KB_GAP_MAX_CHARS,
    KB_GAP_MIN_CHARS as KB_GAP_MIN_CHARS,
    backfill_kb_sources_to_minio as backfill_kb_sources_to_minio,
    create_kb_document_from_upload as create_kb_document_from_upload,
    create_kb_document_version as create_kb_document_version,
    create_kb_faq as create_kb_faq,
    delete_kb_document as delete_kb_document,
    delete_kb_faq as delete_kb_faq,
    get_kb_document as get_kb_document,
    get_kb_faq as get_kb_faq,
    get_kb_index_job as get_kb_index_job,
    get_kb_stats as get_kb_stats,
    ingest_kb_from_source_db as ingest_kb_from_source_db,
    link_kb_gap as link_kb_gap,
    list_kb_chunks as list_kb_chunks,
    list_kb_documents as list_kb_documents,
    list_kb_faqs as list_kb_faqs,
    list_kb_gaps as list_kb_gaps,
    patch_kb_document as patch_kb_document,
    patch_kb_faq as patch_kb_faq,
    purge_kb_documents as purge_kb_documents,
    purge_stale_kb_gaps as purge_stale_kb_gaps,
    record_kb_gap as record_kb_gap,
    reindex_all_kb_documents as reindex_all_kb_documents,
    reindex_kb_document as reindex_kb_document,
)

from db_prompt_studio import (  # noqa: E402
    DEFAULT_BOT_ID as DEFAULT_BOT_ID,
    _DEFAULT_GUARDRAILS as _DEFAULT_GUARDRAILS,
    _DEFAULT_PERSONA as _DEFAULT_PERSONA,
    _DEFAULT_VOICE as _DEFAULT_VOICE,
    _handoff_edges as _handoff_edges,
    _map_prompt_version as _map_prompt_version,
    _prompt_voice as _prompt_voice,
    agent_change_log as agent_change_log,
    archive_agent_studio_card as archive_agent_studio_card,
    compile_agent_studio_card as compile_agent_studio_card,
    create_prompt_version as create_prompt_version,
    discard_prompt_version as discard_prompt_version,
    get_active_deployment as get_active_deployment,
    get_agent_studio_card as get_agent_studio_card,
    get_deployment as get_deployment,
    get_effective_contract as get_effective_contract,
    get_prompt_version as get_prompt_version,
    get_published_prompt_version as get_published_prompt_version,
    get_tts_voice_catalog_entry as get_tts_voice_catalog_entry,
    get_tts_voice_warning as get_tts_voice_warning,
    latest_tts_sync_run as latest_tts_sync_run,
    list_agent_studio_cards as list_agent_studio_cards,
    list_entry_bindings as list_entry_bindings,
    policy_engines as policy_engines,
    remove_entry_binding as remove_entry_binding,
    set_entry_binding as set_entry_binding,
    list_bot_deployments as list_bot_deployments,
    list_persona_presets as list_persona_presets,
    list_prompt_versions as list_prompt_versions,
    list_tts_price_tiers as list_tts_price_tiers,
    list_tts_sync_runs as list_tts_sync_runs,
    list_tts_voice_catalog as list_tts_voice_catalog,
    list_tts_voices as list_tts_voices,
    patch_prompt_version as patch_prompt_version,
    publish_prompt_version as publish_prompt_version,
    resolve_prompt_azure_voice as resolve_prompt_azure_voice,
    restore_agent_studio_card as restore_agent_studio_card,
    restore_prompt_version_as_draft as restore_prompt_version_as_draft,
    rollback_bot_deployment as rollback_bot_deployment,
    tts_catalog_is_populated as tts_catalog_is_populated,
    voice_locale_facts as voice_locale_facts,
)

from followups_db import (  # noqa: E402
    create_coaching_action as create_coaching_action,
    create_export_job as create_export_job,
    create_routing_rule as create_routing_rule,
    delete_routing_rule as delete_routing_rule,
    list_calibration_sessions as list_calibration_sessions,
    list_coaching_actions as list_coaching_actions,
    list_export_jobs as list_export_jobs,
    list_routing_audit as list_routing_audit,
    patch_audio_segment_mute as patch_audio_segment_mute,
    patch_calibration_session as patch_calibration_session,
    patch_coaching_action as patch_coaching_action,
    patch_export_job as patch_export_job,
    patch_pii_finding as patch_pii_finding,
    patch_redaction_record as patch_redaction_record,
    patch_redaction_rule as patch_redaction_rule,
    patch_routing_rule as patch_routing_rule,
    reorder_routing_rules as reorder_routing_rules,
    workspace_summary as workspace_summary,
)


def list_tts_voice_provider_counts() -> list[dict[str, Any]]:
    """Voice count per provider, for the catalog's provider filter chips.

    Counts respect the same visibility rules as the default catalog query
    (picker-enabled, not removed, GA) so a chip reading "24" and the list that
    opens when you click it cannot disagree. Premium is *included* here on
    purpose: the chip tells you the provider exists, the premium toggle governs
    what the list then shows.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT COALESCE(provider_id, 'azure') AS provider_id, count(*) AS n
                FROM tts_voice_catalog
                WHERE enabled_for_picker = true
                  AND removed_at IS NULL
                  AND status = 'GA'
                GROUP BY 1
                ORDER BY 2 DESC
                """
            )
        ).mappings().all()
    return [{"providerId": r["provider_id"], "count": int(r["n"])} for r in rows]


def list_tts_voice_locale_counts(*, limit: int = 60) -> list[dict[str, Any]]:
    """Voice count per locale, for the catalog's locale picker.

    The picker used to carry a hardcoded India-only preset list (en-IN, hi-IN,
    ta, te, kn, mr, bn). Once the catalog holds ~140 locales that list is not a
    shortcut, it is a filter that hides most of the catalog from the operator.
    Deriving from the data means a locale appears the moment a voice for it does.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.locale,
                       max(c.locale_name) AS locale_name,
                       count(*) AS n
                FROM tts_voice_catalog c
                WHERE c.enabled_for_picker = true
                  AND c.removed_at IS NULL
                  AND c.status = 'GA'
                  AND c.locale <> ''
                GROUP BY c.locale
                ORDER BY count(*) DESC, c.locale
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(int(limit or 60), 400))},
        ).mappings().all()
    return [
        {
            "locale": r["locale"],
            "localeName": r["locale_name"] or r["locale"],
            "count": int(r["n"]),
        }
        for r in rows
    ]

from db_trace import (  # noqa: E402
    _trace_redact as _trace_redact,
    get_turn_trace as get_turn_trace,
)

from db_qa import (  # noqa: E402
    _QA_CLERK_RUBRIC_ID as _QA_CLERK_RUBRIC_ID,
    _QA_DEFAULT_RUBRIC_ID as _QA_DEFAULT_RUBRIC_ID,
    _QA_STATUSES as _QA_STATUSES,
    _SCORECARD_LIST_SQL as _SCORECARD_LIST_SQL,
    _load_rubric_tree as _load_rubric_tree,
    _qa_all_criteria as _qa_all_criteria,
    _qa_band_for as _qa_band_for,
    _qa_compute_total as _qa_compute_total,
    _qa_ensure_bot as _qa_ensure_bot,
    _qa_ensure_criterion as _qa_ensure_criterion,
    _qa_ensure_user as _qa_ensure_user,
    _qa_entries_grouped as _qa_entries_grouped,
    _qa_handled_by as _qa_handled_by,
    _qa_pad_entries as _qa_pad_entries,
    _qa_score_float as _qa_score_float,
    _qa_section_total as _qa_section_total,
    _qa_status_screen as _qa_status_screen,
    _qa_upsert_entries as _qa_upsert_entries,
    _scorecard_by_id as _scorecard_by_id,
    _scorecard_rows_to_screen as _scorecard_rows_to_screen,
    create_scorecard as create_scorecard,
    get_rubric as get_rubric,
    list_scorecards as list_scorecards,
    load_rubric_tree as load_rubric_tree,
    patch_scorecard as patch_scorecard,
    qa_coverage_stats as qa_coverage_stats,
    rubric_id_for_interaction as rubric_id_for_interaction,
)
