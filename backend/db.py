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

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

import contact_window
import money_inr
import tenant_context
import visibility
from env_utils import env_int as _env_int
from pg_errors import is_unique_violation as _is_unique_violation
from schemas import (
    CallResponse,
    CustomerResponse,
    DashboardResponse,
    HandoffQueueItem,
    HandoffQueueResponse,
    HandoffSessionResponse,
    LeadResponse,
    ProductResponse,
)

logger = logging.getLogger(__name__)


BASE = Path(__file__).parent
DEFAULT_DATABASE_URL = "postgresql+psycopg://collections:collections@localhost:5432/collections"


class OwnerBotNotFound(KeyError):
    """The requested ownerBotId does not exist in this environment.

    Subclasses KeyError so existing ``except KeyError -> 404`` handlers keep
    working, while callers that want to retry without a bot owner can catch
    exactly this condition instead of every KeyError (including a genuine
    missing-payload-key bug).
    """


def _read_env_file(key: str) -> str | None:
    """Read one key from ``backend/.env`` without mutating ``os.environ``.

    Was ``_read_env_database_url``, hard-coded to a single key. It needs to
    serve TENANT_ID too: ``.env`` sets TENANT_ID, ``env_loader.load_env()``
    publishes it to the environment, and modules that call ``load_env()``
    (``usage_meter``) therefore saw a value this module did not. The two agreed
    only because the ``.env`` entry happened to repeat the default below — set
    ``.env`` to any other tenant and metering would bill one tenant while every
    query read another. Under row-level security that divergence stops being a
    billing discrepancy and becomes an empty application.

    Deliberately does not call ``load_env()``: importing ``db`` must not have
    the side effect of publishing the whole ``.env`` into the process, which
    would change what every later import sees.
    """
    env_file = BASE / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


DATABASE_URL = os.getenv("DATABASE_URL") or _read_env_file("DATABASE_URL") or DEFAULT_DATABASE_URL

# Tenant + acting user are config, not literals sprinkled through the SQL.
#
# TENANT_ID is the *process* tenant: the value a process falls back to when
# nothing has bound one. Read it through `_tenant()` rather than referencing the
# constant, so that a request able to carry its own tenant is a change in one
# place instead of ninety. Actor identity is already request-scoped this way
# (`actor_context`); this is the same seam for tenancy.
TENANT_ID = os.getenv("TENANT_ID") or _read_env_file("TENANT_ID") or "hdfc.retail"
ACTOR_USER_ID = os.getenv("ACTOR_USER_ID", "priya-nair")


def current_tenant() -> str:
    """The tenant this call is acting for.

    Public name for other modules: `db.current_tenant()` replaces the four
    different spellings that grew up around `db.TENANT_ID` (direct reference,
    `getattr(db, "TENANT_ID", None)`, a private `_tenant()` copy in
    `ops_screens`, and a second `os.getenv` read in `usage_meter`). They agreed
    by accident; under row-level security a disagreement between the value in a
    SQL predicate and the value in the `app.tenant_id` GUC is not a visible
    error — every query simply returns nothing.
    """
    return tenant_context.current_tenant()


# Module-internal alias. `db.py` writes `_tenant()` several dozen times, and the
# short name keeps those parameter dicts on one line as they were.
_tenant = current_tenant


# Binding concurrency ceiling: default QueuePool was pool_size=5 + max_overflow=10
# → 15 conns/process. Budget across uvicorn workers + KB/bot/voice processes so the
# sum stays under Postgres max_connections (default 100) minus reserved.
DB_POOL_SIZE = max(1, _env_int("DB_POOL_SIZE", 5))
DB_MAX_OVERFLOW = max(0, _env_int("DB_MAX_OVERFLOW", 10))
DB_POOL_RECYCLE = max(60, _env_int("DB_POOL_RECYCLE", 1800))
# API path default 15s; workers/voice default 60s unless DB_STATEMENT_TIMEOUT_MS set.
_PROCESS_ROLE = (os.getenv("DB_PROCESS_ROLE") or "api").strip().lower()
_DEFAULT_STATEMENT_TIMEOUT_MS = 60000 if _PROCESS_ROLE in {"worker", "bot_worker", "voice"} else 15000
DB_STATEMENT_TIMEOUT_MS = max(1000, _env_int("DB_STATEMENT_TIMEOUT_MS", _DEFAULT_STATEMENT_TIMEOUT_MS))

# The tenant travels to Postgres as a libpq *startup* parameter, not as a
# statement issued after connecting. That choice is the whole safety argument
# for turning row-level security on:
#
#   - a startup parameter is set before the connection can run anything, so
#     there is no window in which `app.tenant_id` is unset;
#   - it is not transactional, so a ROLLBACK — including the one the pool
#     issues on every return-to-pool — cannot silently unset it.
#
# An RLS policy comparing against an unset GUC matches no rows, so a connection
# that could lose the value would not fail loudly; it would return empty
# results for every query in the application. This closes that door.
engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=DB_POOL_SIZE,
    max_overflow=DB_MAX_OVERFLOW,
    pool_recycle=DB_POOL_RECYCLE,
    connect_args={
        "options": (
            f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} "
            f"-c {tenant_context.GUC}={tenant_context.validate(TENANT_ID)}"
        )
    },
)


@event.listens_for(engine, "begin")
def _bind_tenant_for_transaction(conn) -> None:
    """Override the connection's startup tenant when a call bound its own.

    `SET LOCAL` scopes the override to this transaction, so it cannot outlive
    the work that asked for it and reach the next borrower of a pooled
    connection. When nothing is bound — the case for every call today — this
    costs a ContextVar read and issues no statement.

    Interpolating the value is safe here and only here: `validate()` has already
    constrained it to `[A-Za-z0-9._:-]`, and Postgres does not accept bind
    parameters in `SET`.
    """
    tenant = tenant_context.current_tenant()
    if tenant == TENANT_ID:
        return
    conn.exec_driver_sql(f"SET LOCAL {tenant_context.GUC} = '{tenant_context.validate(tenant)}'")


# Screen-list caps. Most list accessors here return every matching row, which
# was correct against a demo seed and is not correct against a real portfolio:
# the query cost, the response size and the memory to build it all scale with
# how long the deployment has been running.
#
# Bounding them has to be additive, because the routes return a bare JSON array
# and the frontend consumes it as one. So: a default cap that makes the query
# safe, an opt-in `limit` up to a hard ceiling, and an `offset` to page.
DEFAULT_LIST_LIMIT = max(1, _env_int("DEFAULT_LIST_LIMIT", 200))
MAX_LIST_LIMIT = max(DEFAULT_LIST_LIMIT, _env_int("MAX_LIST_LIMIT", 1000))
# Calls carry their whole transcript inline, so a call row is orders of
# magnitude larger than a customer row and gets its own, tighter default.
DEFAULT_CALLS_LIMIT = max(1, _env_int("DEFAULT_CALLS_LIMIT", 100))
# Child collections rendered inside one customer's 360 view. Bounded by that
# customer's own history rather than the portfolio, so the ceiling can be
# generous — but not absent: a five-year-old account with a thousand notes
# should render its recent ones, not every one ever written.
DEFAULT_DETAIL_LIMIT = max(1, _env_int("DEFAULT_DETAIL_LIMIT", 100))


def clamp_list_limit(limit: int | None, default: int = DEFAULT_LIST_LIMIT) -> int:
    """Resolve a caller-supplied page size to a safe one.

    ``None`` means "use the default", not "unbounded" — an accessor must have no
    way to express an unbounded read, or the next caller will express one.
    """
    if limit is None:
        return min(default, MAX_LIST_LIMIT)
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return min(default, MAX_LIST_LIMIT)
    return max(1, min(value, MAX_LIST_LIMIT))


def clamp_offset(offset: int | None) -> int:
    try:
        return max(0, int(offset or 0))
    except (TypeError, ValueError):
        return 0


#: Tables ``_assert_tenant_owns`` will guard. An allow-list because the table
#: name is interpolated into SQL — every entry here is a literal in this file,
#: never a caller-supplied string.
_CUSTOMER_SCOPED_TABLES: frozenset[str] = frozenset(
    {
        "accounts",
        "callbacks",
        "consent_records",
        "conversations",
        "disputes",
        "document_requests",
        "interactions",
        "leads",
        "payment_plans",
        "promises",
        "treatment_holds",
        "authority_decisions",
    }
)


#: Substituted into any query built through :func:`_sql`. Constant — see
#: ``visibility.CUSTOMER_PREDICATE`` for why it is bind-parameterised rather
#: than assembled per actor.
_VIS_PREDICATE = "AND " + visibility.predicate("c")


def _sql(query: str) -> Any:
    """``text()``, with the customer-visibility marker substituted.

    Queries that read customer data write ``/*VISIBILITY*/`` where the scope
    predicate belongs and are built through this instead of ``text()``. One
    definition, one place to review, and no per-actor string assembly.

    A query that forgets to use this keeps the marker as an inert SQL comment
    and is therefore *unscoped* — fail-open, which is the wrong direction. That
    is deliberately not defended against here, because a syntactic guard would
    only catch the queries that already remembered the marker. What catches it
    is ``tests/test_object_visibility.py``, which asserts the behaviour for
    every customer-facing accessor and fails when a new one is not covered.
    """
    return text(query.replace("/*VISIBILITY*/", _VIS_PREDICATE))


def _vis_params() -> dict[str, Any]:
    """Bind parameters for the marker, for the actor of the current request."""
    return visibility.params()


def _assert_tenant_owns(conn: Any, table: str, row_id: str | None) -> None:
    """Refuse a by-id operation on a row belonging to another tenant.

    The list accessors were leaking whole screens across tenants; the by-id
    paths leak one record at a time, to a caller who supplies the id — which is
    the worse of the two, because it is the shape someone probes deliberately
    rather than stumbles into. Every table guarded here carries ``customer_id``,
    so tenancy is exactly one join away.

    Raises ``KeyError``, which these callers already translate to 404, rather
    than a distinct forbidden error. That is deliberate: answering "that exists
    but is not yours" confirms the id, and an enumerable id is most of what an
    attacker needs. Not-found reveals nothing either way.

    This is a guard, not the mechanism. The structural fix is the row-level
    security in ``rls.py``, where a query that forgets its predicate returns
    nothing regardless of what the Python says — but that is inert until the
    application stops connecting as a superuser.
    """
    if table not in _CUSTOMER_SCOPED_TABLES:
        raise ValueError(f"_assert_tenant_owns: {table!r} is not an allow-listed table")
    if not row_id:
        raise KeyError(f"{table}_not_found")
    join = (
        "WHERE t.id = :row_id AND t.tenant_id = :tenant_id"
        if table == "customers"
        else "JOIN customers c ON c.id = t.customer_id "
        "WHERE t.id = :row_id AND c.tenant_id = :tenant_id"
    )
    found = conn.execute(
        text(f"SELECT 1 FROM {table} t {join}"),
        {"row_id": row_id, "tenant_id": _tenant()},
    ).fetchone()
    if not found:
        raise KeyError(f"{table}_not_found")


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


def _account_tail(account_id: str | None) -> str | None:
    return account_id[-4:] if account_id else None


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def _actor_user_id() -> str:
    """The acting user for this request (ContextVar), else process default.

    Set by ``ApiKeyMiddleware`` from ``API_KEY_MAP`` / ``X-Actor-User-Id`` /
    ``ACTOR_USER_ID``. Phase 5 replaces resolution with JWT ``sub``.
    """
    try:
        import actor_context

        return actor_context.get_actor_user_id()
    except Exception:
        return ACTOR_USER_ID


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
        return {
            "id": row["id"],
            "name": row["name"],
            "kind": "human",
            "team": row["team"],
            "status": row["status"],
            "tenantId": _tenant(),
        }


def replace_role_permissions(role_id: str, permission_ids: list[str]) -> dict[str, Any]:
    """Replace the grant set for one role. Admin keeps admin.write."""
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


def _activity(conn: Any, entity_type: str, entity_id: str, kind: str, label: str, note: str | None = None, customer_id: str | None = None) -> None:
    conn.execute(
        text(
            """
            INSERT INTO activity_events
              (id, tenant_id, entity_type, entity_id, actor_kind, actor_user_id, kind, label, note, payload)
            VALUES
              (:id, :tenant_id, :entity_type, :entity_id, 'human', :actor_user_id, :kind, :label, :note,
               CAST(:payload AS jsonb))
            """
        ),
        {
            "id": _id("ACT"),
            "tenant_id": _tenant(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_user_id": _actor_user_id(),
            "kind": kind,
            "label": label,
            # `note or customer_id` wrote `CUST-…` into the notes column of
            # every event that had nothing to say — takeover, return-to-bot,
            # inbound — and `note` is rendered as a human note on the customer,
            # dispute and violation timelines. The id is still worth keeping;
            # it belongs in the structured column.
            "note": note,
            "payload": json.dumps({"customerId": customer_id} if customer_id else {}),
        },
    )


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
            "timezone": row["timezone"] or "Asia/Kolkata",
            "language": row["language"] or "English",
            "preferredWindow": row["preferred_window"] or "10:00-19:00 IST",
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

    ``recommend_treatment`` writes a decision row, and that is deliberate — the
    shadow corpus should be built from the questions people actually ask, and
    somebody opening a customer is asking one. It enacts nothing outside live
    mode, and the trigger kind says where the question came from.
    """
    try:
        from agent_core.treatment import Trigger, recommend_treatment

        result = recommend_treatment(
            customer_id=customer_id,
            trigger=Trigger(kind="manual"),
            conn=conn,
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
            "requestedVia": "voice",
            "requestedAt": r["created_at"],
            "deliveryChannel": _doc_channel(r["delivery_channel"]),
            "status": r["status"],
            "source": r.get("source") or "crm",
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

    The rule itself lives in :mod:`contact_window` because ``agent_core``'s
    code-mode script runs the same check and cannot import this module. It used
    to hold its own copy, and the copy's default bounds had drifted.
    """
    return contact_window.outside_preferred_window(scheduled_at, preferred_window)


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
                           u.name AS assignee, t.name AS queue,
                           i.channel AS interaction_channel, i.handler_kind
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
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
                    "timezone": r["timezone"] or "Asia/Kolkata",
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
# Executive dashboard
#
# Every number below used to be one of three things: a literal, a literal
# multiplied by a live count, or a read of `analytics_daily` — a table with one
# seeded row and no runtime writer, which db.py:4592 already tells callers not
# to read. The range/segment/team parameters were accepted and never used, so
# every filter combination returned identical numbers.
#
# All of it now comes from interactions / ledger_entries / promises / leads.
# Where a figure genuinely cannot be computed (no prior period to compare
# against, a rep with no leads) the API returns null and the UI renders a dash,
# rather than inventing a plausible-looking number.
# ---------------------------------------------------------------------------

# The UI's own vocabulary (Habibi/src/data/dashboard-seed.ts). Deliberately not
# _BOT_ANALYTICS_RANGE_DAYS, which speaks 7d/30d/90d and raises on anything else
# — a dashboard should degrade to its default range, not 400.
_DASHBOARD_RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30, "qtd": 90}
_DASHBOARD_DEFAULT_DAYS = 30

# UI segment → products.family. The screen speaks product language and the
# catalog stores portfolio families; without this map the segment filter
# silently matched nothing.
_DASHBOARD_SEGMENT_FAMILIES = {
    "card": ("revolving_credit",),
    "personal": ("unsecured_loan",),
    "auto": ("secured_loan",),
}


def _dashboard_window(range_key: str, segment: str, team: str) -> dict[str, Any]:
    """Resolve the three filters the endpoint has always accepted and ignored."""
    days = _DASHBOARD_RANGE_DAYS.get(
        (range_key or "").strip().lower(), _DASHBOARD_DEFAULT_DAYS
    )
    families = _DASHBOARD_SEGMENT_FAMILIES.get((segment or "").strip().lower())
    handler = (team or "").strip().lower()
    return {
        "days": days,
        "families": list(families) if families else None,
        "handler_kind": handler if handler in ("bot", "human") else None,
    }


def _pct_delta(current: float | None, prior: float | None) -> float | None:
    """Percentage change, or None when there is nothing to compare against.

    None rather than 0.0: "flat" and "we have no prior data" are different
    claims, and the KPI chips used to render the second as the first.
    """
    if current is None or prior is None or not prior:
        return None
    return round((float(current) - float(prior)) / abs(float(prior)) * 100.0, 1)


def _spark_from_series(values: list[float], *, points: int = 14) -> list[float]:
    """Downsample a real daily series for a sparkline.

    Replaces _spark(seed), which generated deterministic noise from an unrelated
    number — a chart that looked like data and was not.
    """
    clean = [float(v or 0) for v in values]
    if not clean:
        return []
    if len(clean) <= points:
        return [round(v, 2) for v in clean]
    step = len(clean) / points
    return [round(clean[min(len(clean) - 1, int(i * step))], 2) for i in range(points)]


def _inr_compact(amount: float | None) -> str:
    """Compact Indian money. See money_inr.inr_compact for the canonical ladder.

    Mirrors Habibi/src/data/billing-seed.ts::inrCompact exactly. The two used to
    disagree twice over: this side printed "₹1.5 K" where the client printed
    "₹1.5k", and — the one that mattered — this side floored every sub-rupee
    amount to "₹0", which is precisely what main.py warns must not happen to a
    metering figure.
    """
    return money_inr.inr_compact(amount)


def get_dashboard(range: str = "30d", segment: str = "all", team: str = "all") -> dict[str, Any]:
    window = _dashboard_window(range, segment, team)
    days = window["days"]
    families = window["families"]
    handler_kind = window["handler_kind"]

    # Interactions filtered by segment reach products through their account.
    # EXISTS rather than a join so an interaction with no account_id is excluded
    # from a specific segment but still counted under "all".
    ix_segment = (
        """
        AND EXISTS (
          SELECT 1 FROM accounts a
          JOIN products p ON p.id = a.product_id
          WHERE a.id = i.account_id AND p.family = ANY(:families)
        )
        """
        if families
        else ""
    )
    ix_team = " AND i.handler_kind = :handler_kind " if handler_kind else ""
    ix_where = (
        "WHERE i.tenant_id = :tenant_id "
        "AND i.started_at >= :since AND i.started_at < :until "
        + ix_segment
        + ix_team
    )
    params: dict[str, Any] = {"tenant_id": _tenant(), "days": days}
    if families:
        params["families"] = families
    if handler_kind:
        params["handler_kind"] = handler_kind

    ttft_hours: float | None = None
    ttft_n = 0

    # Bound intervals are interpolated as literal day counts from a fixed dict,
    # never from the caller's string — _dashboard_window maps any unknown range
    # to the default rather than passing it through.
    since_cur = f"now() - CAST('{days} days' AS interval)"
    until_cur = "now()"
    since_prior = f"now() - CAST('{days * 2} days' AS interval)"
    until_prior = since_cur

    def _ix_window(since: str, until: str) -> str:
        return ix_where.replace(":since", since).replace(":until", until)

    with engine.connect() as conn:
        summary = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*)::int AS interactions,
                      count(*) FILTER (WHERE i.ptp_captured)::int AS ptp_captured,
                      count(*) FILTER (WHERE i.handler_kind = 'human')::int AS human_handled,
                      avg(i.avg_sentiment) AS avg_sentiment,
                      avg(i.duration_sec) AS avg_duration_sec,
                      count(*) FILTER (WHERE i.sentiment_label = 'positive')::int AS pos,
                      count(*) FILTER (WHERE i.sentiment_label = 'neutral')::int AS neu,
                      count(*) FILTER (WHERE i.sentiment_label = 'negative')::int AS neg
                    FROM interactions i
                    {_ix_window(since_cur, until_cur)}
                    """
                ),
                params,
            )
        ) or {}
        prior_summary = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*)::int AS interactions,
                      count(*) FILTER (WHERE i.handler_kind = 'human')::int AS human_handled,
                      avg(i.avg_sentiment) AS avg_sentiment,
                      avg(i.duration_sec) AS avg_duration_sec
                    FROM interactions i
                    {_ix_window(since_prior, until_prior)}
                    """
                ),
                params,
            )
        ) or {}

        # Daily interaction volume, split by channel. bot_analytics treats
        # channel as a filter; here it is a pivot, so this cannot reuse it.
        volume_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT to_char(date_trunc('day', i.started_at), 'YYYY-MM-DD') AS date,
                           count(*) FILTER (WHERE i.channel = 'voice')::int AS voice,
                           count(*) FILTER (WHERE i.channel = 'whatsapp')::int AS whatsapp,
                           count(*) FILTER (WHERE i.channel IN ('chat','sms','email'))::int AS chat
                    FROM interactions i
                    {_ix_window(since_cur, until_cur)}
                    GROUP BY 1 ORDER BY 1
                    """
                ),
                params,
            )
        )

        # Money actually collected. Payments are stored negative (a credit
        # against the balance), so the sign is flipped to report a recovery.
        led_segment = " AND p.family = ANY(:families) " if families else ""
        recovery_sql = f"""
            SELECT to_char(date_trunc('day', l.posted_at), 'YYYY-MM-DD') AS date,
                   SUM(-l.amount)::numeric AS value
            FROM ledger_entries l
            JOIN accounts a ON a.id = l.account_id
            JOIN customers c ON c.id = a.customer_id
            JOIN products p ON p.id = a.product_id
            WHERE c.tenant_id = :tenant_id
              AND l.type = 'payment'
              AND l.posted_at >= {{since}} AND l.posted_at < {{until}}
              {led_segment}
            GROUP BY 1 ORDER BY 1
        """
        recovery_rows = _rows(
            conn.execute(
                text(recovery_sql.format(since=since_cur, until=until_cur)), params
            )
        )
        prior_recovery = _one(
            conn.execute(
                text(
                    f"""
                    SELECT COALESCE(SUM(-l.amount), 0)::numeric AS value
                    FROM ledger_entries l
                    JOIN accounts a ON a.id = l.account_id
                    JOIN customers c ON c.id = a.customer_id
                    JOIN products p ON p.id = a.product_id
                    WHERE c.tenant_id = :tenant_id
                      AND l.type = 'payment'
                      AND l.posted_at >= {since_prior} AND l.posted_at < {until_prior}
                      {led_segment}
                    """
                ),
                params,
            )
        ) or {}

        # Outstanding across the filtered book — the denominator of recovery rate.
        outstanding_row = _one(
            conn.execute(
                text(
                    f"""
                    SELECT COALESCE(SUM(a.outstanding), 0)::numeric AS total
                    FROM accounts a
                    JOIN customers c ON c.id = a.customer_id
                    JOIN products p ON p.id = a.product_id
                    WHERE c.tenant_id = :tenant_id AND a.status = 'active'
                      {led_segment}
                    """
                ),
                params,
            )
        ) or {}

        # Promise-kept rate. Denominator is settled promises only: an 'upcoming'
        # promise has not failed, and counting it as unkept made the rate a
        # function of how recently the bot had been running.
        prom_segment = " AND p.family = ANY(:families) " if families else ""
        promise_sql = f"""
            SELECT
              count(*) FILTER (WHERE pr.status = 'kept')::int AS kept,
              count(*) FILTER (WHERE pr.status IN ('kept','broken','partial'))::int AS settled
            FROM promises pr
            JOIN accounts a ON a.id = pr.account_id
            JOIN customers c ON c.id = a.customer_id
            JOIN products p ON p.id = a.product_id
            WHERE c.tenant_id = :tenant_id
              AND pr.created_at >= {{since}} AND pr.created_at < {{until}}
              {prom_segment}
        """
        promises_cur = _one(
            conn.execute(text(promise_sql.format(since=since_cur, until=until_cur)), params)
        ) or {}
        promises_prior = _one(
            conn.execute(
                text(promise_sql.format(since=since_prior, until=until_prior)), params
            )
        ) or {}

        # Upsell conversion — leads won over leads captured.
        lead_sql = """
            SELECT count(*)::int AS total,
                   count(*) FILTER (WHERE l.stage = 'won')::int AS won
            FROM leads l
            JOIN customers c ON c.id = l.customer_id
            WHERE c.tenant_id = :tenant_id
              AND l.created_at >= {since} AND l.created_at < {until}
        """
        leads_cur = _one(
            conn.execute(text(lead_sql.format(since=since_cur, until=until_cur)), params)
        ) or {}
        leads_prior = _one(
            conn.execute(text(lead_sql.format(since=since_prior, until=until_prior)), params)
        ) or {}

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
        # Reps ranked over the same window as everything else, with a real
        # upsell number joined from leads rather than `12 + idx * 1.3`.
        leaderboard_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT u.id,
                           u.name,
                           COALESCE(t.name, 'Collections') AS team,
                           COUNT(i.id)::int AS calls,
                           AVG(i.duration_sec)::int AS aht,
                           AVG(i.avg_sentiment) AS csat,
                           (
                             SELECT count(*)::int FROM leads l
                             WHERE l.owner_user_id = u.id
                               AND l.created_at >= {since_cur} AND l.created_at < {until_cur}
                           ) AS leads_total,
                           (
                             SELECT count(*)::int FROM leads l
                             WHERE l.owner_user_id = u.id AND l.stage = 'won'
                               AND l.created_at >= {since_cur} AND l.created_at < {until_cur}
                           ) AS leads_won
                    FROM users u
                    LEFT JOIN teams t ON t.id = u.team_id
                    LEFT JOIN interactions i
                           ON i.handler_user_id = u.id
                          AND i.started_at >= {since_cur} AND i.started_at < {until_cur}
                    GROUP BY u.id, u.name, t.name
                    ORDER BY calls DESC, u.name
                    LIMIT 6
                    """
                ),
                params,
            )
        )

        ttft_hours = None
        ttft_n = 0
        try:
            ttft = _one(
                conn.execute(
                    text(
                        f"""
                        SELECT
                          percentile_cont(0.5) WITHIN GROUP (
                            ORDER BY EXTRACT(EPOCH FROM (pe.first_touch_at - pe.occurred_at)) / 3600.0
                          ) AS hours,
                          count(*) FILTER (WHERE pe.first_touch_at IS NOT NULL)::int AS touched
                        FROM payment_events pe
                        JOIN customers c ON c.id = pe.customer_id
                        WHERE pe.kind = 'bounce'
                          AND c.tenant_id = :tenant_id
                          AND pe.occurred_at >= {since_cur}
                          AND pe.occurred_at < {until_cur}
                          AND pe.first_touch_at IS NOT NULL
                        """
                    ),
                    params,
                )
            ) or {}
            if ttft.get("hours") is not None:
                ttft_hours = float(ttft["hours"])
            ttft_n = int(ttft.get("touched") or 0)
        except Exception:
            logger.debug("time-to-first-touch kpi skipped", exc_info=True)

    interactions = summary.get("interactions") or 0
    human = summary.get("human_handled") or 0
    bot = max(interactions - human, 0)
    aht = round(summary.get("avg_duration_sec") or 0)
    mm, ss = divmod(aht, 60)
    avg_sent = float(summary.get("avg_sentiment") or 0)

    recovery_trend = [
        {"date": r["date"], "value": float(r["value"] or 0)} for r in recovery_rows
    ]
    recovered = sum(p["value"] for p in recovery_trend)
    prior_recovered = float(prior_recovery.get("value") or 0)

    # Recovery rate: collected over (collected + still owed). Stated in the KPI
    # `sub` so the definition is auditable from the screen rather than only from
    # this file — a rate whose formula nobody can see is a rate nobody trusts.
    outstanding_total = float(outstanding_row.get("total") or 0)
    denominator = recovered + outstanding_total
    recovery_rate = (recovered / denominator * 100.0) if denominator > 0 else None

    settled = promises_cur.get("settled") or 0
    ptp_rate = ((promises_cur.get("kept") or 0) / settled * 100.0) if settled else None
    prior_settled = promises_prior.get("settled") or 0
    prior_ptp_rate = (
        ((promises_prior.get("kept") or 0) / prior_settled * 100.0) if prior_settled else None
    )

    leads_total = leads_cur.get("total") or 0
    upsell_rate = ((leads_cur.get("won") or 0) / leads_total * 100.0) if leads_total else None
    prior_leads_total = leads_prior.get("total") or 0
    prior_upsell_rate = (
        ((leads_prior.get("won") or 0) / prior_leads_total * 100.0) if prior_leads_total else None
    )

    prior_interactions = prior_summary.get("interactions") or 0
    prior_human = prior_summary.get("human_handled") or 0
    prior_containment = (
        (max(prior_interactions - prior_human, 0) / prior_interactions * 100.0)
        if prior_interactions
        else None
    )
    containment = (bot / interactions * 100.0) if interactions else None

    volume_series = [
        {
            "date": r["date"],
            "voice": int(r["voice"] or 0),
            "whatsapp": int(r["whatsapp"] or 0),
            "chat": int(r["chat"] or 0),
        }
        for r in volume_rows
    ]
    daily_calls = [v["voice"] + v["whatsapp"] + v["chat"] for v in volume_series]

    # Normalised to ints summing 100, or all zeros for an empty window. The
    # denominator genuinely can be 0 now that the window is real, so this is a
    # live divide-by-zero rather than a theoretical one.
    labelled = (summary.get("pos") or 0) + (summary.get("neu") or 0) + (summary.get("neg") or 0)
    if labelled:
        pos_pct = round((summary.get("pos") or 0) / labelled * 100)
        neu_pct = round((summary.get("neu") or 0) / labelled * 100)
        sentiment_distribution = {
            "positive": pos_pct,
            "neutral": neu_pct,
            # Absorb the rounding drift here so the three always sum to 100.
            "negative": max(0, 100 - pos_pct - neu_pct),
        }
    else:
        sentiment_distribution = {"positive": 0, "neutral": 0, "negative": 0}

    def _pct(value: float | None) -> str:
        return "—" if value is None else f"{value:.1f}%"

    dashboard = {
        "heroKpis": [
            {
                "label": "Avg Handle Time (AHT)",
                "value": f"{mm}m {ss:02d}s" if aht else "—",
                "raw": aht,
                "delta": _pct_delta(aht, prior_summary.get("avg_duration_sec")),
                "deltaGood": "down",
                "sub": f"mean duration over {days}d",
                "spark": _spark_from_series(daily_calls),
            },
            {
                "label": "Upsell Conversion Rate",
                "value": _pct(upsell_rate),
                "raw": round(upsell_rate, 1) if upsell_rate is not None else 0,
                "unit": "%",
                "delta": _pct_delta(upsell_rate, prior_upsell_rate),
                "deltaGood": "up",
                "sub": f"{leads_cur.get('won') or 0} won of {leads_total} leads",
                "spark": [],
            },
        ],
        "kpis": [
            {
                "key": "recovered",
                "label": "Total Dues Recovered",
                "value": _inr_compact(recovered),
                "delta": _pct_delta(recovered, prior_recovered),
                "deltaGood": "up",
                "spark": _spark_from_series([p["value"] for p in recovery_trend]),
                "tone": "success",
            },
            {
                "key": "recoveryRate",
                "label": "Recovery Rate",
                "value": _pct(recovery_rate),
                "delta": None,
                "deltaGood": "up",
                "sub": "collected ÷ (collected + outstanding)",
                "spark": [],
            },
            {
                "key": "containment",
                "label": "Bot Containment",
                "value": _pct(containment),
                "delta": _pct_delta(containment, prior_containment),
                "deltaGood": "up",
                "spark": [],
                "tone": "brand",
            },
            {
                "key": "ptp",
                "label": "Promise-Kept Rate",
                "value": _pct(ptp_rate),
                "delta": _pct_delta(ptp_rate, prior_ptp_rate),
                "deltaGood": "up",
                "sub": f"{promises_cur.get('kept') or 0} kept of {settled} settled",
                "spark": [],
                "tone": "warning",
            },
            {
                "key": "timeToFirstTouch",
                "label": "Time to first touch",
                "value": f"{ttft_hours:.1f}h" if ttft_hours is not None else "—",
                "delta": None,
                "deltaGood": "down",
                "sub": (
                    f"median hours bounce→contact · {ttft_n} touched"
                    if ttft_n
                    else "median hours bounce→first contact"
                ),
                "spark": [],
                "tone": "brand",
            },
            {
                "key": "csat",
                "label": "Avg Sentiment / CSAT",
                "value": f"{avg_sent:.2f}" if labelled else "—",
                # No percentage delta. Sentiment is a signed score in [-1, 1],
                # so 0.02 → 0.07 is "+217%", which is arithmetically true and
                # tells a reader nothing. The prior value is shown instead.
                "delta": None,
                "deltaGood": "up",
                "sub": (
                    f"prior period {float(prior_summary['avg_sentiment']):.2f}"
                    if prior_summary.get("avg_sentiment") is not None
                    else "no prior period"
                ),
                "spark": [],
            },
            {
                "key": "calls",
                "label": "Calls Handled",
                "value": f"{interactions:,}",
                "delta": _pct_delta(interactions, prior_interactions),
                "deltaGood": "up",
                "spark": _spark_from_series([float(v) for v in daily_calls]),
            },
        ],
        "recoveryTrend": recovery_trend,
        "callVolumeStacked": volume_series,
        "sentimentDistribution": sentiment_distribution,
        "botVsHuman": [
            {"name": "Contained by bot", "value": bot, "color": "var(--background-brand-bold)"},
            {"name": "Handled by human", "value": human, "color": "var(--chart-warning-bold)"},
        ],
        "leaderboard": [
            {
                "rank": idx + 1,
                "name": r["name"],
                "team": r["team"],
                "calls": r["calls"],
                "aht": _duration(r["aht"]) if r["aht"] else "—",
                # None, not a number, when the rep captured no leads in the
                # window. The UI renders a dash — "no data" is not "12.0%".
                "upsell": (
                    round((r["leads_won"] or 0) / r["leads_total"] * 100.0, 1)
                    if r["leads_total"]
                    else None
                ),
                "csat": round(float(r["csat"]), 2) if r["csat"] is not None else None,
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


def _trace_redact(value: Any) -> Any:
    """Redact anything that reaches a trace response.

    ``bot_tool_calls.result_preview`` holds up to 1500 chars of raw tool output
    — balances, DPD, phone tails — and ``args`` holds model-supplied customer
    speech (``flag_dispute.summary``, ``capture_lead.summary``). Until now only
    the Inbox read this table; an endpoint widens the audience, so it is masked
    on the way out rather than trusted to be safe.
    """
    import transcript_view

    if value is None:
        return None
    if isinstance(value, str):
        return transcript_view.redact_line(value)
    if isinstance(value, dict):
        return {k: _trace_redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trace_redact(v) for v in value]
    return value


def get_turn_trace(interaction_id: str) -> list[dict[str, Any]]:
    """Every turn of one interaction, with its tool calls, retrievals and latency."""
    with engine.connect() as conn:
        exists = _one(
            conn.execute(
                text("SELECT id FROM interactions WHERE id = :id"), {"id": interaction_id}
            )
        )
        if not exists:
            raise KeyError(f"interaction not found: {interaction_id}")

        turns = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, turn_index, speaker, at_sec, text, intent, intent_score,
                           sentiment_delta, ttfb_ms, ttfa_ms, tokens,
                           stt_ttfb_ms, llm_ttfb_ms, tts_ttfb_ms,
                           user_turn_ms, tool_ms, aggregation_ms
                    FROM interaction_transcript
                    WHERE interaction_id = :ix
                    ORDER BY turn_index
                    LIMIT :lim
                    """
                ),
                {"ix": interaction_id, "lim": _TRACE_MAX_TURNS},
            )
        )
        tool_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT transcript_turn_id, tool_name, args, result_ok, error,
                           result_preview, latency_ms, channel, created_at,
                           agent_id, skill_id, connector_id
                    FROM bot_tool_calls
                    WHERE interaction_id = :ix
                    ORDER BY created_at
                    """
                ),
                {"ix": interaction_id},
            )
        )
        retrieval_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT transcript_turn_id, query, top_chunks, latency_ms,
                           selected_answer_source, created_at
                    FROM retrieval_logs
                    WHERE interaction_id = :ix
                    ORDER BY created_at
                    """
                ),
                {"ix": interaction_id},
            )
        )

    # Rows whose turn could not be resolved (the tool ran before the transcript
    # row existed) are kept under a null key and surfaced as an "unattributed"
    # bucket rather than dropped — losing an audit record to a race is worse
    # than showing it in the wrong place.
    tools_by_turn: dict[Any, list[dict[str, Any]]] = {}
    for r in tool_rows:
        tools_by_turn.setdefault(r["transcript_turn_id"], []).append(
            {
                "tool": r["tool_name"],
                "ok": bool(r["result_ok"]),
                "error": r["error"],
                "latencyMs": r["latency_ms"],
                "channel": r["channel"],
                "args": _trace_redact(r["args"]),
                "resultPreview": _trace_redact(r["result_preview"]),
                "at": r["created_at"],
                "agentId": r.get("agent_id"),
                "skillId": r.get("skill_id"),
                "connectorId": r.get("connector_id"),
            }
        )

    retrievals_by_turn: dict[Any, list[dict[str, Any]]] = {}
    for r in retrieval_rows:
        chunks = r["top_chunks"] or []
        retrievals_by_turn.setdefault(r["transcript_turn_id"], []).append(
            {
                # Already redacted at write time in kb_retrieve; masked again on
                # the way out because the write-side patterns and these are not
                # guaranteed to stay in sync.
                "query": _trace_redact(r["query"]),
                "hits": len(chunks) if isinstance(chunks, list) else 0,
                "topScore": (
                    chunks[0].get("score")
                    if isinstance(chunks, list) and chunks and isinstance(chunks[0], dict)
                    else None
                ),
                "chunks": chunks,
                "latencyMs": r["latency_ms"],
                "source": r["selected_answer_source"],
                "at": r["created_at"],
            }
        )

    out: list[dict[str, Any]] = []
    for t in turns:
        out.append(
            {
                "turnId": t["id"],
                "turnIndex": t["turn_index"],
                "speaker": t["speaker"],
                "atSec": t["at_sec"],
                "text": _trace_redact(t["text"]),
                "intent": t["intent"],
                "intentScore": float(t["intent_score"]) if t["intent_score"] is not None else None,
                "sentimentDelta": (
                    float(t["sentiment_delta"]) if t["sentiment_delta"] is not None else None
                ),
                "latency": {
                    "ttfbMs": t["ttfb_ms"],
                    "ttfaMs": t["ttfa_ms"],
                    "tokens": t["tokens"],
                    "sttTtfbMs": t["stt_ttfb_ms"],
                    "llmTtfbMs": t["llm_ttfb_ms"],
                    "ttsTtfbMs": t["tts_ttfb_ms"],
                    "userTurnMs": t["user_turn_ms"],
                    "toolMs": t["tool_ms"],
                    "aggregationMs": t["aggregation_ms"],
                },
                "toolCalls": tools_by_turn.get(t["id"], []),
                "retrievals": retrievals_by_turn.get(t["id"], []),
            }
        )

    orphan_tools = tools_by_turn.get(None, [])
    orphan_retrievals = retrievals_by_turn.get(None, [])
    if orphan_tools or orphan_retrievals:
        out.append(
            {
                "turnId": None,
                "turnIndex": None,
                "speaker": "system",
                "atSec": None,
                "text": "Events that could not be attributed to a turn.",
                "intent": None,
                "intentScore": None,
                "sentimentDelta": None,
                "latency": {},
                "toolCalls": orphan_tools,
                "retrievals": orphan_retrievals,
            }
        )
    return out


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
            "promised_at": payload["promisedDate"],
            "reminder_status": payload.get("reminderStatus") or "queued",
            "channel": payload.get("channel") or "voice",
        },
    )
    _activity(conn, "promise", promise_id, "promise_created", "Promise-to-pay captured", f"Amount {payload['amount']}", customer_id)
    try:
        import promise_fulfillment

        fulfillment = promise_fulfillment.fulfill(conn, promise_id)
    except Exception:
        logger.exception("ptp fulfill failed promise=%s", promise_id)
        fulfillment = None
    response = _promise_by_id(conn, promise_id)
    if fulfillment is not None:
        response["_fulfillment"] = fulfillment.as_dict()
        response["_spoken"] = fulfillment.spoken_summary
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
        if updates:
            conn.execute(text(f"UPDATE disputes SET {', '.join(updates)} WHERE id = :id"), params)

        status = payload.get("status")
        resolution = payload.get("resolutionCode")
        if status == "resolved" and resolution == "valid_waive_fee":
            try:
                from agent_core.authority import enact as authority_enact

                authority_enact.post_waiver_for_dispute(conn, dispute_id=dispute_id)
            except Exception:
                logger.exception("goodwill ledger post failed for dispute %s", dispute_id)
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


def patch_consent(customer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write."""
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

# The unanswered-questions table used to be hand-seeded at ~10 rows, so this
# read was unbounded. Runtime gap capture makes it grow with traffic, and the
# screen only renders a top-N table.
_BOT_ANALYTICS_GAP_LIMIT = 50

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
                        coalesce(i.upsell_presented, false) AS upsell_presented,
                        coalesce(i.ptp_captured, false) AS ptp_captured,
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
                      count(*) FILTER (WHERE upsell_presented)::int AS upsell_presented,
                      count(*) FILTER (WHERE ptp_captured)::int AS ptp_captured,
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
                    LIMIT :gap_lim
                    """
                ),
                {"tenant_id": _tenant(), "gap_lim": _BOT_ANALYTICS_GAP_LIMIT},
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

        by_card_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      coalesce(nullif(trim(i.handler_bot_id), ''), 'unknown') AS bot_id,
                      count(*)::int AS sessions,
                      count(*) FILTER (
                        WHERE i.handler_kind = 'bot' AND i.query_resolved
                      )::int AS contained,
                      count(*) FILTER (
                        WHERE EXISTS (
                          SELECT 1 FROM interaction_handoffs h WHERE h.interaction_id = i.id
                        )
                      )::int AS escalated,
                      coalesce(
                        percentile_cont(0.99) WITHIN GROUP (ORDER BY i.latency_ms),
                        0
                      )::float AS latency_p99
                    FROM interactions i
                    WHERE {where_sql}
                    GROUP BY 1
                    ORDER BY sessions DESC, bot_id
                    """
                ),
                params,
            )
        )

        skill_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      coalesce(nullif(trim(c.skill_id), ''), 'none') AS skill_id,
                      count(*)::int AS activations
                    FROM bot_tool_calls c
                    JOIN interactions i ON i.id = c.interaction_id
                    WHERE {where_sql}
                      AND c.skill_id IS NOT NULL
                      AND trim(c.skill_id) <> ''
                    GROUP BY 1
                    ORDER BY activations DESC, skill_id
                    LIMIT 24
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
            "upsellPresented": int(r["upsell_presented"] or 0),
            "ptpCaptured": int(r["ptp_captured"] or 0),
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

    by_card = [
        {
            "botId": r["bot_id"],
            "sessions": int(r["sessions"] or 0),
            "contained": int(r["contained"] or 0),
            "escalated": int(r["escalated"] or 0),
            "containment": round(
                (int(r["contained"] or 0) / int(r["sessions"] or 1)) * 100.0, 1
            )
            if int(r["sessions"] or 0)
            else 0.0,
            "handoffRate": round(
                (int(r["escalated"] or 0) / int(r["sessions"] or 1)) * 100.0, 1
            )
            if int(r["sessions"] or 0)
            else 0.0,
            "latencyP99": round(float(r["latency_p99"] or 0), 1),
            "sloMs": 800,
        }
        for r in by_card_rows
    ]
    skill_histogram = [
        {"skillId": r["skill_id"], "activations": int(r["activations"] or 0)}
        for r in skill_rows
    ]

    return {
        "dailySeries": daily_series,
        "intentAggs": intent_aggs,
        "escalationReasons": escalation_reasons,
        "unansweredQuestions": unanswered,
        "turnsHistogram": turns_histogram,
        "funnelStages": funnel_stages,
        "byCard": by_card,
        "skillHistogram": skill_histogram,
    }


# ---------------------------------------------------------------------------
# QA Scorecards — rubric-driven scoring queue (scorecard core MVP).
# Coaching / calibration stay seed-backed until their endpoints land.
# ---------------------------------------------------------------------------

_QA_DEFAULT_RUBRIC_ID = "rubric-v1"
_QA_CLERK_RUBRIC_ID = "rubric-clerk-sms"
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


def load_rubric_tree(rubric_id: str | None = None) -> dict[str, Any] | None:
    """Rubric tree, or None when there is no enabled rubric.

    ``get_rubric`` raises for the HTTP layer, which wants a 404. The QA
    auto-scorer is a background sweep and a missing rubric is a reason to skip
    the tick, not to raise into a worker loop.
    """
    with engine.connect() as conn:
        return _load_rubric_tree(conn, rubric_id or _QA_DEFAULT_RUBRIC_ID)


def rubric_id_for_interaction(interaction_id: str) -> str | None:
    """Voice collections rubric, or the clerk SMS rubric. Never mix them.

    A clerk WhatsApp/SMS must not be scored against recording-disclosure or
    barge criteria. If the clerk rubric is missing, return None so autoscore
    skips rather than using the voice tree.
    """
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text("SELECT channel, handler_kind FROM interactions WHERE id = :id"),
                {"id": interaction_id},
            )
        )
        if row is None:
            return _QA_DEFAULT_RUBRIC_ID
        channel = str(row.get("channel") or "")
        if channel in {"sms", "whatsapp"} or str(row.get("handler_kind") or "") == "system":
            exists = conn.execute(
                text("SELECT 1 FROM qa_rubrics WHERE id = :id AND enabled = true"),
                {"id": _QA_CLERK_RUBRIC_ID},
            ).first()
            return _QA_CLERK_RUBRIC_ID if exists else None
        return _QA_DEFAULT_RUBRIC_ID


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
    trees: dict[str, dict[str, Any] | None] = {}

    def tree_for(rubric_id: str | None) -> dict[str, Any] | None:
        key = rubric_id or _QA_DEFAULT_RUBRIC_ID
        if key not in trees:
            trees[key] = _load_rubric_tree(conn, key)
        return trees[key]

    if rubric is not None:
        trees[rubric.get("id") or _QA_DEFAULT_RUBRIC_ID] = rubric
    fallback = tree_for(_QA_DEFAULT_RUBRIC_ID)
    entries_by = _qa_entries_grouped(conn, [r["id"] for r in rows])
    result: list[dict[str, Any]] = []
    for r in rows:
        rid = r.get("rubric_id") or _QA_DEFAULT_RUBRIC_ID
        tree = tree_for(rid) or fallback
        if tree is None:
            raise KeyError("rubric_not_found")
        agent_id = r["subject_user_name"] or r["subject_bot_name"] or r["handler_name"] or "Unknown"
        entries = _qa_pad_entries(tree, entries_by.get(r["id"]) or [])
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
                "rubricId": rid,
            }
        )
    return result


def list_scorecards() -> list[dict[str, Any]]:
    """QA Scoring Queue — screen Scorecard shape."""
    with engine.connect() as conn:
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
        return _scorecard_rows_to_screen(conn, rows)


def qa_coverage_stats(*, days: int = 7) -> dict[str, Any]:
    """Share of completed interactions that have a scorecard in the window."""
    window = max(1, min(int(days), 90))
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                  count(*) FILTER (
                    WHERE i.status IN ('completed', 'abandoned')
                      AND i.ended_at >= now() - CAST(:window AS interval)
                  )::int AS completed,
                  count(*) FILTER (
                    WHERE i.status IN ('completed', 'abandoned')
                      AND i.ended_at >= now() - CAST(:window AS interval)
                      AND qs.id IS NOT NULL
                  )::int AS scored,
                  count(*) FILTER (
                    WHERE qs.status = 'ai_draft'
                      AND qs.created_at >= now() - CAST(:window AS interval)
                  )::int AS pending_review,
                  count(*) FILTER (
                    WHERE qs.band = 'red'
                      AND qs.created_at >= now() - CAST(:window AS interval)
                  )::int AS critical
                FROM interactions i
                LEFT JOIN qa_scorecards qs ON qs.interaction_id = i.id
                WHERE i.tenant_id = :tenant
                """
            ),
            {"tenant": current_tenant(), "window": f"{window} days"},
        ).mappings().one()
    completed = int(row["completed"] or 0)
    scored = int(row["scored"] or 0)
    coverage = (scored / completed) if completed else None
    return {
        "windowDays": window,
        "completed": completed,
        "scored": scored,
        "coverage": round(coverage, 4) if coverage is not None else None,
        "pendingReview": int(row["pending_review"] or 0),
        "criticalFails": int(row["critical"] or 0),
    }


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
        "contactableNow": _inbox_contactable(conn, customer_id, bool(dnd), preferred_window),
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
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if conversation_id:
        clauses.append("cv.id = :conversation_id")
        params["conversation_id"] = conversation_id
    if updated_after is not None:
        clauses.append("COALESCE(cv.updated_at, cv.created_at) > :updated_after")
        params["updated_after"] = updated_after
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
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
    with engine.connect() as conn:
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

    with engine.connect() as conn:
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
    with engine.connect() as conn:
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
    with engine.begin() as conn:
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
    with engine.begin() as conn:
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


def handoff_to_agent(
    *,
    interaction_id: str,
    from_bot_id: str | None,
    target_bot_id: str,
    reason: str,
    payload: str | None = None,
) -> dict[str, Any]:
    """Move a live bot-handled interaction to another first-party card.

    Writes ``transferred_from_bot_id`` / ``handler_bot_id``. Does not open a
    human handoff — that is ``escalate_to_human``. Calling this is the only
    way a transfer is recorded; transcript prose does not reach here.
    """
    target = (target_bot_id or "").strip()
    if not target:
        raise ValueError("target_bot_required")
    with engine.begin() as conn:
        if not _one(conn.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": target})):
            raise KeyError(f"bot_not_found:{target}")
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
    with engine.connect() as conn:
        return {r["id"] for r in _rows(conn.execute(text("SELECT id FROM bots")))}


def get_latest_context_summary(interaction_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
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
    with engine.begin() as conn:
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


def get_latest_eval_report(*, bot_id: str, kind: str) -> dict[str, Any] | None:
    """Newest report for this bot whose suite matches ``kind`` (regression/redteam)."""
    with engine.connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT r.id, r.status, r.summary, r.suite_id, r.bot_id, r.created_at
                    FROM eval_reports r
                    JOIN eval_suites s ON s.id = r.suite_id
                    WHERE r.bot_id = :bot AND s.kind = :kind
                    ORDER BY r.created_at DESC
                    LIMIT 1
                    """
                ),
                {"bot": bot_id, "kind": kind},
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
    with engine.begin() as conn:
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


def list_eval_reports(
    *, kind: str | None = None, bot_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    clauses = ["r.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": _tenant(), "n": max(1, min(int(limit), 200))}
    if kind:
        clauses.append("s.kind = :kind")
        params["kind"] = kind
    if bot_id:
        clauses.append("r.bot_id = :bot_id")
        params["bot_id"] = bot_id
    where = " AND ".join(clauses)
    with engine.connect() as conn:
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
    with engine.connect() as conn:
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
    with engine.begin() as conn:
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

    with engine.begin() as conn:
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
            )

            import whatsapp as wa
            import whatsapp_outbound as wa_out

            to_phone = wa.normalize_phone(row["phone_primary"]) or wa.normalize_phone(row["phone_alt"])
            if not to_phone:
                raise ValueError("whatsapp_missing_recipient")

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
    with engine.connect() as conn:
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


def _actor_role_names(conn: Any, user_id: str | None = None) -> list[str]:
    uid = (user_id or _actor_user_id() or "").strip()
    if not uid:
        return []
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
            {"uid": uid},
        )
    )
    out: list[str] = []
    for r in rows:
        name = (r.get("name") or "").strip().lower().replace("-", "_").replace(" ", "_")
        if name:
            out.append(name)
    return out


def _actor_can_view_raw_pii(conn: Any) -> bool:
    """Raw PII in finding.text is Compliance Officer / Admin only.

    Until Phase 5 auth carries a real role claim, resolve from user_roles.
    There is no seeded 'Compliance Officer' role yet — Admin is the stand-in;
    names containing Compliance / DPO are also allowed for forward-compat.
    """
    for name in _actor_role_names(conn):
        if name in {"admin", "compliance_officer", "dpo"}:
            return True
    return False


def actor_is_admin(user_id: str | None = None) -> bool:
    """True when the actor has Admin role or perm-admin-write."""
    uid = (user_id or _actor_user_id() or "").strip()
    if not uid:
        return False
    with engine.connect() as conn:
        for name in _actor_role_names(conn, uid):
            if name == "admin":
                return True
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT 1
                    FROM user_roles ur
                    JOIN role_permissions rp ON rp.role_id = ur.role_id
                    WHERE ur.user_id = :uid
                      AND rp.permission_id = 'perm-admin-write'
                    LIMIT 1
                    """
                ),
                {"uid": uid},
            )
        )
        return row is not None


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
        # `turn_text`, not `text` — the module-level sqlalchemy `text` import is
        # shadowed for the rest of the function otherwise, and any SQL added
        # here later would fail with a confusing TypeError.
        turn_text = turn["text"]
        invalid = False
        for f in spans:
            start, end = int(f["start"]), int(f["end"])
            if not (0 <= start < end <= len(turn_text)):
                invalid = True
                break
            turn_text = turn_text[:start] + (f.get("masked") or "") + turn_text[end:]
        if invalid:
            # Fail closed: do not leave raw PII when offsets are corrupt.
            masked_bits = [str(f.get("masked") or "[redacted]") for f in spans]
            turn_text = " ".join(masked_bits) if masked_bits else "[redacted]"
        out.append({**turn, "text": turn_text})
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


def list_redaction_records(
    *,
    limit: int = 100,
    before_id: str | None = None,
) -> list[dict[str, Any]]:
    """Redaction Hub queue — screen RedactionRecord shape. Scoped to TENANT_ID.

    Newest-first with an enforced maximum page size. Optional ``before_id``
    names the last record of the previous page; the next page continues from
    that record's position in the sort (exclusive).
    """
    capped = max(1, min(int(limit or 100), 200))
    params: dict[str, Any] = {"tenant_id": _tenant(), "limit": capped}
    cursor_sql = ""
    if before_id:
        # The cursor must compare on the same key the ORDER BY uses. Comparing
        # `rr.id` alone against a list ordered by (started_at DESC, id DESC)
        # both skipped and repeated records, because id order and timestamp
        # order are unrelated.
        cursor_sql = """
              AND (COALESCE(i.started_at, rr.created_at), rr.id) < (
                    SELECT COALESCE(i2.started_at, rr2.created_at), rr2.id
                    FROM redaction_records rr2
                    JOIN interactions i2 ON i2.id = rr2.interaction_id
                    WHERE rr2.id = :before_id AND i2.tenant_id = :tenant_id
                  )
        """
        params["before_id"] = before_id
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _REDACTION_LIST_SQL
                    + cursor_sql
                    + """
                    ORDER BY COALESCE(i.started_at, rr.created_at) DESC, rr.id DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        )
        return _redaction_rows_to_screen(conn, rows)


def get_redaction_record(redaction_id: str) -> dict[str, Any]:
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(_REDACTION_LIST_SQL + " AND rr.id = :id"),
                {"tenant_id": _tenant(), "id": redaction_id},
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
                {"tenant_id": _tenant()},
            )
        )
        by_type = {r["pii_type"]: r for r in rows if r["pii_type"] in _PII_TYPES}
        # Always return the full screen vocabulary so the Rules sheet never gaps.
        return [
            _map_redaction_rule(pii_type, by_type.get(pii_type))
            for pii_type in _PII_LABELS
        ]


def _map_redaction_rule(pii_type: str, row: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "piiType": pii_type,
        "enabled": bool(row["enabled"]) if row else False,
        "replacement": (row["replacement"] if row else f"[REDACTED-{pii_type.upper()}]"),
        "label": _PII_LABELS[pii_type],
    }


def get_redaction_rule(pii_type: str) -> dict[str, Any] | None:
    """Single redaction rule — used by write paths instead of re-listing."""
    if pii_type not in _PII_LABELS:
        return None
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT pii_type, enabled, replacement
                    FROM redaction_rule_configs
                    WHERE tenant_id = :tenant_id AND pii_type = :pii_type
                    """
                ),
                {"tenant_id": _tenant(), "pii_type": pii_type},
            )
        )
    return _map_redaction_rule(pii_type, row)


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


_ROUTING_RULE_SELECT = """
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
"""


def _map_routing_rule(r: dict[str, Any]) -> dict[str, Any]:
    params = _routing_action_params(r["action_params"])
    then: dict[str, Any] = {"key": _routing_action_key(r["action_key"])}
    if params is not None:
        then["params"] = params
    last = r["last_fired_at"]
    return {
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


def get_routing_rule(rule_id: str) -> dict[str, Any] | None:
    """Single tenant-scoped rule — used by write paths instead of re-listing."""
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(_ROUTING_RULE_SELECT + " AND r.id = :rule_id"),
                {"tenant_id": _tenant(), "rule_id": rule_id},
            )
        )
    return _map_routing_rule(row) if row else None


def list_routing_rules() -> list[dict[str, Any]]:
    """Priority-ordered routing rules with execution aggregates. Tenant-scoped."""
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(_ROUTING_RULE_SELECT + " ORDER BY r.priority ASC, r.id"),
                {"tenant_id": _tenant()},
            )
        )
    return [_map_routing_rule(r) for r in rows]


_TEAM_NAME_ALIASES = {
    "hardship desk": "card-collections",
    "hardship": "card-collections",
    "dispute desk": "card-collections",
    "dispute": "card-collections",
    "supervisors": "supervisors",
    "supervisor": "supervisors",
    "tier 2": "retail-collections",
    "tier2": "retail-collections",
    "card collections": "card-collections",
    "retail collections": "retail-collections",
}

_ACTION_DEFAULT_TEAM = {
    "escalate_supervisor": "supervisors",
    "route_tier2": "card-collections",
    "route_specialist": "card-collections",
    "handoff_human": "card-collections",
}


def _routing_coerce(a: Any, b: Any) -> tuple[Any, Any]:
    if isinstance(b, bool) or isinstance(a, bool):
        def _b(v: Any) -> bool:
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in {"1", "true", "yes", "y"}

        return _b(a), _b(b)
    try:
        return float(a), float(b)
    except (TypeError, ValueError):
        return str(a).strip().lower() if a is not None else "", str(b).strip().lower() if b is not None else ""


def _routing_eval_condition(cond: dict[str, Any], context: dict[str, Any]) -> bool:
    field = str(cond.get("field") or "")
    op = str(cond.get("op") or "=")
    raw = context.get(field)
    if op in {">", "<", ">=", "<="}:
        try:
            av = float(raw) if raw is not None else None
            bv = float(cond.get("value"))
        except (TypeError, ValueError):
            return False
        if av is None:
            return False
        if op == ">":
            return av > bv
        if op == "<":
            return av < bv
        if op == ">=":
            return av >= bv
        return av <= bv
    av, bv = _routing_coerce(raw, cond.get("value"))
    if op == "=":
        return av == bv
    if op == "!=":
        return av != bv
    if op == "in":
        if isinstance(cond.get("value"), list):
            return str(raw) in {str(x) for x in cond["value"]}
        return str(raw) in {s.strip() for s in str(cond.get("value") or "").split(",")}
    if op == "contains":
        return str(bv) in str(av)
    return False


def _routing_eval_node(node: Any, context: dict[str, Any]) -> bool:
    if not isinstance(node, dict):
        return False
    if "or" in node and isinstance(node["or"], list):
        return any(
            _routing_eval_condition(c, context)
            for c in node["or"]
            if isinstance(c, dict)
        )
    return _routing_eval_condition(node, context)


def _resolve_team_id(conn: Any, action_key: str, params: dict[str, str] | None) -> str | None:
    params = params or {}
    hint = (params.get("team") or params.get("teamId") or params.get("queue") or "").strip()
    if hint:
        by_id = _one(
            conn.execute(
                text("SELECT id FROM teams WHERE id = :id AND tenant_id = :t"),
                {"id": hint, "t": _tenant()},
            )
        )
        if by_id:
            return by_id["id"]
        alias = _TEAM_NAME_ALIASES.get(hint.lower())
        if alias:
            return alias
        by_name = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM teams
                    WHERE tenant_id = :t AND lower(name) = lower(:name)
                    LIMIT 1
                    """
                ),
                {"t": _tenant(), "name": hint},
            )
        )
        if by_name:
            return by_name["id"]
    return _ACTION_DEFAULT_TEAM.get(action_key)


def _resolve_assignee_for_team(conn: Any, team_id: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (assignee_user_id, assignee_name, team_name)."""
    if not team_id:
        team_id = "card-collections"
    team = _one(
        conn.execute(
            text(
                """
                SELECT id, name, supervisor_user_id
                FROM teams WHERE id = :id AND tenant_id = :t
                """
            ),
            {"id": team_id, "t": _tenant()},
        )
    )
    if not team:
        # Last-resort: any seeded team with a supervisor.
        team = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name, supervisor_user_id
                    FROM teams
                    WHERE tenant_id = :t AND supervisor_user_id IS NOT NULL
                    ORDER BY id
                    LIMIT 1
                    """
                ),
                {"t": _tenant()},
            )
        )
    if not team:
        return None, None, None
    uid = team.get("supervisor_user_id")
    if not uid:
        member = _one(
            conn.execute(
                text(
                    """
                    SELECT u.id
                    FROM users u
                    WHERE u.team_id = :team
                    ORDER BY u.name
                    LIMIT 1
                    """
                ),
                {"team": team["id"]},
            )
        )
        uid = member["id"] if member else None
    if not uid:
        # Empty team (e.g. retail-collections with no members) — borrow Card Collections.
        fallback = _one(
            conn.execute(
                text(
                    """
                    SELECT id, name, supervisor_user_id
                    FROM teams
                    WHERE id = 'card-collections' AND tenant_id = :t
                    """
                ),
                {"t": _tenant()},
            )
        )
        if fallback and fallback.get("supervisor_user_id"):
            team = fallback
            uid = fallback["supervisor_user_id"]
    name = _user_name(conn, uid) if uid else None
    return uid, name, team.get("name")


def _match_routing_rule(
    conn: Any,
    rules: list[dict[str, Any]],
    ctx: dict[str, Any],
    *,
    interaction_id: str | None = None,
    sandbox_run_id: str | None = None,
) -> dict[str, Any]:
    """First matching enabled rule → decision dict, logging the execution.

    Connection-scoped on purpose — the escalation path is already inside a
    transaction and must not open a nested one.
    """
    for rule in rules:
        if not rule.get("enabled"):
            continue
        when = rule.get("when") or []
        if not when:
            continue
        if not all(_routing_eval_node(node, ctx) for node in when):
            continue
        action = rule.get("then") or {}
        action_key = _routing_action_key(action.get("key"))
        params = action.get("params") if isinstance(action.get("params"), dict) else None
        team_id = _resolve_team_id(conn, action_key, params)
        assignee_id, assignee_name, team_name = _resolve_assignee_for_team(conn, team_id)
        action_taken = f"{action_key}:{team_id or 'none'}:{assignee_id or 'unassigned'}"
        exec_id = _id("RRE")
        conn.execute(
            text(
                """
                INSERT INTO routing_rule_executions (
                  id, rule_id, interaction_id, sandbox_run_id, context,
                  result, action_taken, evaluated_at, created_at
                ) VALUES (
                  :id, :rule_id, :interaction_id, :sandbox_run_id,
                  CAST(:context AS jsonb), 'matched', :action_taken, now(), now()
                )
                """
            ),
            {
                "id": exec_id,
                "rule_id": rule["id"],
                "interaction_id": interaction_id,
                "sandbox_run_id": sandbox_run_id,
                "context": json.dumps(ctx),
                "action_taken": action_taken[:240],
            },
        )
        return {
            "matched": True,
            "ruleId": rule["id"],
            "ruleName": rule.get("name"),
            "actionKey": action_key,
            "actionParams": params,
            "teamId": team_id,
            "teamName": team_name,
            "assigneeUserId": assignee_id,
            "assigneeName": assignee_name,
            "executionId": exec_id,
        }

    return {
        "matched": False,
        "ruleId": None,
        "ruleName": None,
        "actionKey": None,
        "actionParams": None,
        "teamId": _ACTION_DEFAULT_TEAM.get("handoff_human"),
        "teamName": None,
        "assigneeUserId": None,
        "assigneeName": None,
        "executionId": None,
    }


#: Escalation reasons that should also stop outbound collections. Warm-
#: transferring a borrower who has just described losing their job, and then
#: dialling them again tomorrow morning because the campaign says so, is the
#: single most complained-about thing a collections floor does. Until now
#: "hardship" was a routing label that expired with the call.
_ESCALATION_HOLDS = {"hardship": "hardship", "dispute": "dispute"}

#: Hours a specialist has to pick the case up. Matches the roadmap's "hardship
#: as a first-class object with specialist SLA"; the hold itself does not
#: expire on it — an unattended hardship case must stay held, not quietly
#: resume dunning.
_HOLD_SLA_HOURS = 24


def _hold_on_escalation(
    conn: Any, *, customer_id: str | None, reason: str, interaction_id: str | None
) -> None:
    """Place a treatment hold when an escalation says to stop collecting.

    ``ON CONFLICT DO NOTHING`` against the partial unique index, so a second
    escalation on the same call is a no-op rather than an error. Failures are
    swallowed: an escalation must complete even if the hold cannot be written,
    because a customer stuck mid-transfer is a worse outcome than a hold that
    has to be placed by hand.
    """
    kind = _ESCALATION_HOLDS.get(reason)
    if not kind or not customer_id:
        return
    try:
        nested = conn.begin_nested()
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO treatment_holds (
                      id, tenant_id, customer_id, kind, reason, source,
                      interaction_id, placed_by_user_id, sla_due_at
                    ) VALUES (
                      :id, :tenant_id, :customer_id, :kind, :reason, 'bot',
                      :interaction_id, NULL, now() + make_interval(hours => :sla)
                    )
                    ON CONFLICT (customer_id, COALESCE(account_id, ''), kind)
                    WHERE released_at IS NULL
                    DO NOTHING
                    """
                ),
                {
                    "id": _id("THD"),
                    "tenant_id": _tenant(),
                    "customer_id": customer_id,
                    "kind": kind,
                    "reason": f"Escalated from a call: {reason}",
                    "interaction_id": interaction_id,
                    "sla": _HOLD_SLA_HOURS,
                },
            )
            nested.commit()
        except Exception:
            nested.rollback()
            raise
    except Exception:
        logger.exception("treatment hold on escalation failed for %s", customer_id)


def escalate_voice_interaction(
    *,
    interaction_id: str,
    reason: str,
    bot_id: str | None = None,
    customer_id: str | None = None,
    note_text: str | None = None,
    route_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Single-transaction escalate: handoff + note + routing + inbox conversation.

    Collapses the four sequential pool round-trips previously done from
    ``voice.tools.escalate_to_human`` so PSTN calls spend one connection slot.
    """
    ix = (interaction_id or "").strip()
    if not ix:
        raise ValueError("interaction_id_required")

    reasons = {
        "sentiment_drop",
        "verification_failed",
        "compliance",
        "customer_requested",
        "hardship",
        "dispute",
        "high_value",
        "routing_rule",
    }
    r = reason if reason in reasons else "customer_requested"
    ctx = {str(k): v for k, v in (route_context or {}).items()}
    # Read rules outside the write txn (stable catalog).
    rules = list_routing_rules()

    with engine.begin() as conn:
        interaction = _one(
            conn.execute(
                text(
                    """
                    SELECT id, customer_id, channel, status
                    FROM interactions WHERE id = :id
                    """
                ),
                {"id": ix},
            )
        )
        if interaction is None:
            raise KeyError("interaction_not_found")

        cid = customer_id or interaction.get("customer_id")
        hid = _id("HO")
        conn.execute(
            text(
                """
                INSERT INTO interaction_handoffs (
                  id, interaction_id, from_kind, from_user_id, from_bot_id,
                  to_kind, to_user_id, to_bot_id, to_team_id, reason, queue,
                  requested_at, created_at
                ) VALUES (
                  :id, :interaction_id, 'bot', NULL, :bot_id,
                  'human', NULL, NULL, 'retail-collections', :reason, 'Retail Collections',
                  now(), now()
                )
                """
            ),
            {
                "id": hid,
                "interaction_id": ix,
                "bot_id": bot_id or DEFAULT_BOT_ID,
                "reason": r,
            },
        )
        conn.execute(
            text(
                """
                UPDATE interactions
                SET disposition = COALESCE(disposition, 'escalated'),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": ix},
        )

        _hold_on_escalation(conn, customer_id=cid, reason=r, interaction_id=ix)

        note_id = None
        if note_text and cid:
            note_id = _id("NOTE")
            conn.execute(
                text(
                    """
                    INSERT INTO customer_notes (id, customer_id, author_user_id, text, pinned)
                    VALUES (:id, :customer_id, :author_user_id, :text, false)
                    """
                ),
                {
                    "id": note_id,
                    "customer_id": cid,
                    "author_user_id": _actor_user_id(),
                    "text": note_text[:2000],
                },
            )
            _activity(
                conn,
                "customer",
                cid,
                "note_created",
                "Customer note added",
                note_text[:240],
                cid,
            )

        # Routing match — connection-scoped so it joins this transaction
        # instead of opening a nested one.
        decision = _match_routing_rule(conn, rules, ctx, interaction_id=ix)

        assignee_user_id = decision.get("assigneeUserId")
        team_id = decision.get("teamId")

        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM conversations
                    WHERE interaction_id = :ix
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"ix": ix},
            )
        )
        now = datetime.now(timezone.utc)
        if existing:
            conversation_id = existing["id"]
        else:
            channel = interaction.get("channel") or "voice"
            if channel not in {"whatsapp", "sms", "email", "chat", "voice"}:
                channel = "chat"
            conversation_id = _id("CV")
            # Savepoint: a failed INSERT aborts the enclosing transaction in
            # Postgres, so the voice->chat fallback below would itself fail with
            # 25P02 and the whole escalation would be lost.
            nested = conn.begin_nested()
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO conversations
                          (id, interaction_id, customer_id, assigned_user_id,
                           status, channel, created_at, updated_at)
                        VALUES
                          (:id, :interaction_id, :customer_id, :assignee,
                           'needs_human', :channel, :now, :now)
                        """
                    ),
                    {
                        "id": conversation_id,
                        "interaction_id": ix,
                        "customer_id": interaction["customer_id"],
                        "assignee": assignee_user_id,
                        "channel": channel,
                        "now": now,
                    },
                )
                nested.commit()
            except Exception as exc:
                nested.rollback()
                from sqlalchemy.exc import IntegrityError

                msg = str(getattr(exc, "orig", exc)).lower()
                # Only the schema's channel CHECK is recoverable here; anything
                # else (FK violation, deadlock) must surface.
                if (
                    isinstance(exc, IntegrityError)
                    and channel == "voice"
                    and ("channel" in msg or "check" in msg)
                ):
                    conn.execute(
                        text(
                            """
                            INSERT INTO conversations
                              (id, interaction_id, customer_id, assigned_user_id,
                               status, channel, created_at, updated_at)
                            VALUES
                              (:id, :interaction_id, :customer_id, :assignee,
                               'needs_human', 'chat', :now, :now)
                            """
                        ),
                        {
                            "id": conversation_id,
                            "interaction_id": ix,
                            "customer_id": interaction["customer_id"],
                            "assignee": assignee_user_id,
                            "now": now,
                        },
                    )
                else:
                    raise
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, sent_at, created_at)
                    VALUES (:id, :cid, 'system', :body, :now, :now)
                    """
                ),
                {
                    "id": _id("MSG"),
                    "cid": conversation_id,
                    "body": f"Escalated from voice · {r}"[:500],
                    "now": now,
                },
            )

        sets = ["status = 'needs_human'", "updated_at = now()"]
        params: dict[str, Any] = {"id": conversation_id}
        if assignee_user_id:
            sets.append("assigned_user_id = :assignee")
            params["assignee"] = assignee_user_id
        conn.execute(
            text(f"UPDATE conversations SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        _activity(
            conn,
            "conversation",
            conversation_id,
            "conversation_escalated",
            "Escalated to human",
            r[:240],
            interaction["customer_id"],
        )

        # Live alert inside the same txn (was a second begin() via persist).
        conn.execute(
            text(
                """
                INSERT INTO live_alerts (
                  id, interaction_id, kind, severity, reason, created_at
                ) VALUES (
                  :id, :interaction_id, 'escalation', 'high', :reason, now()
                )
                """
            ),
            {"id": _id("ALERT"), "interaction_id": ix, "reason": r},
        )

        # Snapshot conversation fields without a post-txn get_conversation() round-trip.
        conv_row = _one(
            conn.execute(
                text(
                    """
                    SELECT c.id, c.assigned_user_id, u.name AS assigned_user_name
                    FROM conversations c
                    LEFT JOIN users u ON u.id = c.assigned_user_id
                    WHERE c.id = :id
                    """
                ),
                {"id": conversation_id},
            )
        )

    return {
        "handoffId": hid,
        "noteId": note_id,
        "conversationId": conversation_id,
        "assigneeUserId": (conv_row or {}).get("assigned_user_id") or assignee_user_id,
        "assigneeName": decision.get("assigneeName")
        or (conv_row or {}).get("assigned_user_name"),
        "teamId": team_id,
        "teamName": decision.get("teamName"),
        "routing": decision,
        "reason": r,
    }


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
                {"id": rule_id, "tenant_id": _tenant()},
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
    if entity_type == "bounce" and status == "in_progress":
        return "ok", "Awaiting pay"
    if due is None:
        if entity_type == "promise" and status == "broken":
            return "breach", "Follow up now"
        if entity_type == "promise":
            return "warn", "Follow up today"
        if entity_type == "bounce":
            return "warn", "First touch pending"
        return "ok", "Open"

    delta = (due - now).total_seconds()
    if delta < 0:
        label = f"Overdue {_fmt_hm(delta)}"
        if entity_type == "promise" and status == "broken":
            return "breach", "Follow up now"
        if entity_type == "bounce":
            return "breach", label
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
    """Indian digit grouping — ₹12,34,567. See money_inr.inr for the reasoning.

    Kept as a module-local name because db.py writes it several dozen times and
    six other modules used to carry their own divergent copy. There is now one
    implementation and three import sites.
    """
    return money_inr.inr(amount)


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

    bounce_ids = by_type.get("bounce") or []
    if bounce_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, reason, amount, account_id, first_touch_channel, status
                    FROM payment_events
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": bounce_ids},
            )
        ):
            why = (r["reason"] or "unknown").replace("_", " ")
            amount = float(r["amount"]) if r["amount"] is not None else None
            channel = r["first_touch_channel"]
            if channel:
                detail = f"{why} · sent via {channel}"
            else:
                detail = why
            out[f"bounce:{r['id']}"] = {
                "type": "EMI bounce",
                "detail": detail,
                "amount": amount,
                "accountId": r.get("account_id"),
            }

    return out


def _enacted_by_map(conn: Any, entity_ids: list[str]) -> dict[str, str]:
    """Latest treatment actor, plus clerk-sourced document requests."""
    ids = [e for e in entity_ids if e]
    if not ids:
        return {}
    out: dict[str, str] = {}
    for r in _rows(
        conn.execute(
            text(
                """
                SELECT DISTINCT ON (trigger_ref) trigger_ref, enacted_by
                  FROM treatment_decisions
                 WHERE trigger_ref = ANY(:ids)
                   AND enacted_by IS NOT NULL
                 ORDER BY trigger_ref, created_at DESC
                """
            ),
            {"ids": ids},
        )
    ):
        actor = r.get("enacted_by")
        if actor:
            out[r["trigger_ref"]] = str(actor)
    for r in _rows(
        conn.execute(
            text(
                """
                SELECT id FROM document_requests
                 WHERE id = ANY(:ids) AND source = 'clerk'
                """
            ),
            {"ids": ids},
        )
    ):
        out.setdefault(r["id"], "clerk_agent")
    return out


def list_work_items(
    *, assignee: str | None = "me", limit: int | None = None, offset: int | None = None
) -> list[dict[str, Any]]:
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

    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
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
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
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
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "assignee_id": assignee_id,
                    "tenant_id": _tenant(), **_vis_params(),
                    "limit": page,
                    "offset": skip,
                },
            )
        )
        enrichment = _work_item_enrichment(conn, rows)
        enacted = _enacted_by_map(conn, [r["entity_id"] for r in rows])
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
                    "customerId": r["customer_id"],
                    "enactedBy": enacted.get(r["entity_id"]),
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
    "azureVoiceName": "en-IN-AartiNeural",
    "speed": 1.0,
    "pitch": 0,
    "warmth": 62,
    "pauseMs": 320,
    "sampleText": "Hello Rahul, this is a courtesy call from HDFC about your EMI. Do you have a minute?",
}
_DEFAULT_AZURE_TTS_VOICE = "en-IN-AartiNeural"
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
    # Local, like every other agent_core.tuning use in this module. The module
    # itself imports nothing from db, so this is convention rather than a cycle.
    from agent_core.tuning import normalize_tts_params

    data = _as_dict(raw)
    return {
        "voiceId": str(data.get("voiceId") or _DEFAULT_VOICE["voiceId"]),
        "azureVoiceName": str(
            data.get("azureVoiceName")
            or data.get("shortName")
            or _DEFAULT_VOICE.get("azureVoiceName")
            or _DEFAULT_AZURE_TTS_VOICE
        ).strip()
        or _DEFAULT_AZURE_TTS_VOICE,
        "speed": float(data.get("speed", _DEFAULT_VOICE["speed"])),
        "pitch": int(data.get("pitch", _DEFAULT_VOICE["pitch"])),
        "warmth": int(data.get("warmth", _DEFAULT_VOICE["warmth"])),
        "pauseMs": int(data.get("pauseMs", _DEFAULT_VOICE["pauseMs"])),
        "sampleText": str(data.get("sampleText") or _DEFAULT_VOICE["sampleText"]),
        "style": (str(data["style"]).strip() if data.get("style") else None),
        # Provider-specific TTS controls (Fish temperature, Cartesia speed, ...).
        # This function is a whitelist, so a key it does not name is dropped —
        # which is how the Voice tab's model controls used to reach the preview
        # and nothing else. Sanitised by the same helper `normalize_tuning`
        # uses, so what is stored and what is folded into AgentTuning agree.
        "params": normalize_tts_params(data.get("params")),
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


def _prompt_flow(raw: Any) -> dict[str, Any]:
    """The stored graph if it can be read, the sentinel plus a flag if it cannot.

    Degrading to `{}` alone would be the same failure this codebase keeps
    finding: an unreadable graph and a card that never authored one would render
    identically, as an empty canvas over "No authored flow". `flowUnreadable`
    is what lets the studio say which of the two it is looking at.
    """
    if not isinstance(raw, dict):
        return {"flow": {}, "flowUnreadable": False}
    if not raw:
        return {"flow": {}, "flowUnreadable": False}
    import flow_graph

    try:
        flow_graph.parse_graph(raw)
    except Exception:
        logger.warning("prompt version holds an unreadable flow graph; serving it as empty")
        return {"flow": {}, "flowUnreadable": True}
    return {"flow": raw, "flowUnreadable": False}


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
        # Authored conversation graph; '{}' on every version that predates flow
        # authoring, which flow_graph.parse_graph reads as "no graph".
        #
        # Checked here rather than handed straight to the response model. That
        # model's `flow` is a FlowGraph with extra="forbid", so ONE row holding
        # an unknown key or an out-of-vocabulary enum — a hand-edited row, or a
        # write from a newer build — raised ResponseValidationError, and that is
        # a 500 on GET /prompt-versions for the whole bot. Every version becomes
        # unreadable because one of them is, and the studio has no way in at
        # all: no history, no editor, no diff, and no way to discard the row
        # that caused it.
        **_prompt_flow(r.get("flow")),
        "botId": r.get("bot_id") or DEFAULT_BOT_ID,
        "agentCard": r.get("agent_card") if isinstance(r.get("agent_card"), dict) else {},
    }


def list_prompt_versions(
    *,
    limit: int | None = None,
    offset: int | None = None,
    bot_id: str | None = None,
) -> list[dict[str, Any]]:
    """Version history newest-first — editor rail. Grows with every draft."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    where = "WHERE p.bot_id = :bot_id" if bot_id else ""
    params: dict[str, Any] = {"limit": page, "offset": skip}
    if bot_id:
        params["bot_id"] = bot_id
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    {where}
                    ORDER BY p.created_at DESC, p.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        )
        return [_map_prompt_version(r) for r in rows]


def get_published_prompt_version(bot_id: str | None = None) -> dict[str, Any] | None:
    """Editor live badge — must match active prod deployment (invariant)."""
    bid = (bot_id or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    with engine.connect() as conn:
        r = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.status = 'published' AND p.bot_id = :bot_id
                    LIMIT 1
                    """
                ),
                {"bot_id": bid},
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
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at,
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


def list_agent_studio_cards(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """Fleet index: first-party mouths plus tenant clones. Not a fifth first-party.

    Reachability is stamped here rather than per card: it is a property of the
    whole handoff graph, and a single card cannot know whether anything routes
    to it.
    """
    from agent_core.cards.defaults import FIRST_PARTY_BOTS, card_dump
    from agent_core.cards.routing import reachability, runtime_entry_bot_id

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for bot_id, name, version in FIRST_PARTY_BOTS:
        out.append(_agent_studio_card_summary(bot_id, name, version, card_dump))
        seen.add(bot_id)
    where = "" if include_archived else " AND archived_at IS NULL"
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT id, name, version, archived_at FROM bots
                     WHERE tenant_id = :tenant{where}
                     ORDER BY name, id
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    for r in rows:
        if r["id"] in seen:
            continue
        summary = _agent_studio_card_summary(
            r["id"], r["name"], r.get("version") or "1.0", card_dump
        )
        summary["archivedAt"] = _iso_ts(r.get("archived_at"))
        out.append(summary)
        seen.add(r["id"])

    entry = runtime_entry_bot_id()
    # A retired card cannot carry traffic, so its handoffs are not a path: leaving
    # them in made a card look reachable through an agent that no longer answers.
    routes = reachability(
        [(c["botId"], c["agentCard"]) for c in out if not c.get("archivedAt")],
        entry=entry,
        # A card holding its own active deployment is addressable by bot_id, so
        # it seeds the walk too. deploymentStatus is already computed per card.
        deployed=[c["botId"] for c in out if c.get("deploymentStatus") == "live"],
    )
    for card in out:
        card["entryBotId"] = entry
        card["reachability"] = (
            "archived" if card.get("archivedAt") else routes.get(card["botId"], "unreachable")
        )
    return out


def _studio_card_versions(bot_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(published, newest draft) for one bot, from one snapshot.

    Two separate calls let a concurrent publish land between them and produce a
    summary whose published id and card came from different rows.
    """
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.bot_id = :bot_id AND p.status IN ('published', 'draft')
                    ORDER BY p.created_at DESC, p.id DESC
                    """
                ),
                {"bot_id": bot_id},
            )
        )
    pub = next((r for r in rows if r["status"] == "published"), None)
    draft = next((r for r in rows if r["status"] == "draft"), None)
    return (
        _map_prompt_version(pub) if pub else None,
        _map_prompt_version(draft) if draft else None,
    )


def _agent_studio_card_summary(  # noqa: PLR0913 - one row of a wide summary
    bot_id: str,
    name: str,
    version: str,
    card_dump,
    *,
    versions: tuple[dict[str, Any] | None, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS

    published, draft = versions if versions is not None else _studio_card_versions(bot_id)
    dep = get_active_deployment(bot_id=bot_id, environment="production")

    def _card_of(row: dict[str, Any] | None) -> dict[str, Any] | None:
        raw = (row or {}).get("agentCard")
        return raw if isinstance(raw, dict) and raw else None

    published_card = _card_of(published)
    # The editor PATCHes the draft, so the draft is what it must read back.
    # Returning the published card here is what made every Skills/Connectors
    # toggle snap back: the write landed on the draft, the refetch returned the
    # published row, and the UI reverted. It also left every cloned card — which
    # has a draft and no published row — showing an empty card.
    card = _card_of(draft) or published_card
    source = "draft" if _card_of(draft) else ("published" if published_card else "default")
    if card is None:
        try:
            card = card_dump(bot_id)
        except KeyError:
            # Not first-party and no version yet. An empty card is unauthorable,
            # which made a bot row with no prompt version a dead end in the
            # editor; a scaffold gives it something real to edit.
            from agent_core.cards.defaults import scaffold_card

            card = scaffold_card(bot_id, name)
            source = "scaffold"
    identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    tools = card.get("tools") if isinstance(card.get("tools"), dict) else {}
    skill_rows = card.get("skills") if isinstance(card.get("skills"), list) else []
    if not skill_rows:
        try:
            from agent_core.skills.defaults import CARD_SKILLS

            skill_rows = [
                {"skill_id": slug, "version": "1", "pin": "exact"}
                for slug in CARD_SKILLS.get(bot_id, ())
            ]
            if skill_rows:
                card = {**card, "skills": skill_rows}
        except Exception:
            skill_rows = []
    if dep:
        status = "live"
    elif published:
        status = "published"
    elif draft:
        status = "draft"
    else:
        status = "empty"
    return {
        "botId": bot_id,
        "name": identity.get("display_name") or name,
        "version": version,
        "slug": identity.get("slug") or bot_id,
        "purpose": identity.get("purpose") or "",
        "channels": identity.get("channels") or [],
        "skills": [
            s.get("skill_id")
            for s in skill_rows
            if isinstance(s, dict) and s.get("skill_id")
        ],
        "toolCount": len(tools.get("include") or []),
        "evalStatus": (
            (get_latest_eval_report(bot_id=bot_id, kind="redteam") or {}).get("status")
            or (get_latest_eval_report(bot_id=bot_id, kind="regression") or {}).get("status")
            or "skipped"
        ),
        # None, not 100: a card with no active deployment takes no traffic, and
        # claiming 100% made every unpublished clone look live on the fleet index.
        "trafficPct": (dep or {}).get("trafficPct") if dep else None,
        "deploymentStatus": status,
        "lastPublish": (dep or {}).get("publishedAt"),
        "promptVersionId": (published or {}).get("id"),
        "draftVersionId": (draft or {}).get("id"),
        "hasDraft": draft is not None,
        # What the editor edits vs what production is running — the Ship tab and
        # the fleet badge need to tell those apart.
        "cardSource": source,
        # Explicit rather than inferred: the fleet guessed first-party from
        # cardSource == "default", but a first-party card with a published row
        # reports "published", so its Archive button enabled and then 409'd.
        "isFirstParty": bot_id in FIRST_PARTY_BOT_IDS,
        # Always present: set here rather than only on the tenant branch of
        # list_agent_studio_cards, which left first-party rows without the key
        # while the single-card endpoint always had it.
        "archivedAt": None,
        "agentCard": card,
        "publishedCard": published_card or {},
    }


def _handoff_edges() -> list[tuple[str, Any]]:
    """(bot_id, card) for every bot, from the draft when there is one.

    Only the handoff arrays matter here, but the card column is one read either
    way and parsing it in Python keeps the closure logic in one place.
    """
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (p.bot_id) p.bot_id, p.agent_card
                      FROM prompt_versions p
                      JOIN bots b ON b.id = p.bot_id
                     WHERE p.status IN ('published', 'draft')
                       AND b.archived_at IS NULL
                       AND b.tenant_id = :tenant
                     ORDER BY p.bot_id, (p.status = 'draft') DESC, p.created_at DESC
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    return [(r["bot_id"], _as_dict(r.get("agent_card"))) for r in rows]


def _live_deployment_bot_ids() -> list[str]:
    """Cards carrying an active production deployment.

    These are addressable by bot_id whether or not anything hands off to them —
    agent_core/deployment.py resolves ``bot_id or DEFAULT_BOT_ID`` — so they
    seed the reachability walk alongside the configured entry card.
    """
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT d.bot_id
                      FROM bot_deployments d
                      JOIN bots b ON b.id = d.bot_id
                     WHERE d.status = 'active'
                       AND d.environment = 'production'
                       AND b.archived_at IS NULL
                       AND b.tenant_id = :tenant
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    return [r["bot_id"] for r in rows]


def get_agent_studio_card(bot_id: str) -> dict[str, Any] | None:
    """One card by id — without building the whole fleet to throw it away."""
    from agent_core.cards.defaults import FIRST_PARTY_BOTS, card_dump
    from agent_core.cards.routing import reachability, runtime_entry_bot_id

    bid = (bot_id or "").strip()
    if not bid:
        return None
    archived_at = None
    summary: dict[str, Any] | None = None
    for fp_id, name, version in FIRST_PARTY_BOTS:
        if fp_id == bid:
            summary = _agent_studio_card_summary(bid, name, version, card_dump)
            break
    if summary is None:
        with engine.connect() as conn:
            row = _one(
                conn.execute(
                    text(
                        """
                        SELECT id, name, version, archived_at FROM bots
                         WHERE id = :id AND tenant_id = :tenant
                        """
                    ),
                    {"id": bid, "tenant": _tenant()},
                )
            )
        if not row:
            return None
        archived_at = _iso_ts(row.get("archived_at"))
        summary = _agent_studio_card_summary(
            bid, row["name"], row.get("version") or "1.0", card_dump
        )
    summary["archivedAt"] = archived_at

    entry = runtime_entry_bot_id()
    edges = {b: c for b, c in _handoff_edges()}
    edges[bid] = summary["agentCard"]  # unsaved-but-loaded card wins for this one
    summary["entryBotId"] = entry
    summary["reachability"] = (
        "archived"
        if archived_at
        else reachability(
            list(edges.items()), entry=entry, deployed=_live_deployment_bot_ids()
        ).get(bid, "unreachable")
    )
    return summary


def archive_agent_studio_card(bot_id: str) -> dict[str, Any]:
    """Retire a tenant card. Never deletes — the row is referenced by audit.

    ``bots.id`` is a foreign key on interactions, eval_reports, activity_events
    and a2a_tasks. A DELETE would cascade the deployments and NULL the audit
    trail of every call the agent ever handled, so retirement is a timestamp.

    Refused when the card is first-party (re-seeded on boot) or when it is the
    runtime entry point — inbound traffic would resolve to a retired bot.

    A live production deployment is retired here rather than refused. It used to
    be a third guard, which made the whole feature unreachable: publish always
    leaves an active deployment and rollback only swaps which one is active, so
    no card that had ever shipped could be retired. Taking no traffic *is* what
    archiving means, so retiring the deployment is the operation, not a side
    effect. Restore does not redeploy — publish again to bring the card back.
    """
    from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS
    from agent_core.cards.routing import runtime_entry_bot_id

    bid = (bot_id or "").strip()
    if not bid:
        raise ValueError("bot_id_required")
    if bid in FIRST_PARTY_BOT_IDS:
        raise ValueError("first_party_card_not_archivable")
    if bid == runtime_entry_bot_id():
        raise ValueError("entry_card_not_archivable")
    with engine.begin() as conn:
        updated = conn.execute(
            text(
                """
                UPDATE bots SET archived_at = now(), updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND archived_at IS NULL
                """
            ),
            {"id": bid, "t": _tenant()},
        ).rowcount
        if updated:
            retired = _one(
                conn.execute(
                    text(
                        """
                        SELECT id FROM bot_deployments
                         WHERE bot_id = :id AND environment = 'production'
                           AND status = 'active'
                         LIMIT 1
                        """
                    ),
                    {"id": bid},
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE bot_deployments
                       SET status = 'retired', updated_at = now()
                     WHERE bot_id = :id AND environment = 'production'
                       AND status = 'active'
                    """
                ),
                {"id": bid},
            )
            from agent_core import change_log

            change_log.record_archive(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=bid,
                retired_deployment_id=(retired or {}).get("id"),
            )
    if not updated:
        raise KeyError(f"agent_card_not_found_or_archived:{bid}")
    return {"ok": True, "botId": bid, "archived": True}


def restore_agent_studio_card(bot_id: str) -> dict[str, Any]:
    """Undo an archive. The card returns exactly as it was left.

    Recorded in the change log for the same reason the archive is: an agent
    reappearing on the roster is a configuration change, and a chain that logs
    only the retirement reads as though the card is still retired.
    """
    bid = (bot_id or "").strip()
    if not bid:
        raise ValueError("bot_id_required")
    with engine.begin() as conn:
        # Read before the UPDATE nulls it — the archived window is the fact the
        # entry exists to carry, and afterwards it is gone.
        archived_at = _one(
            conn.execute(
                text(
                    """
                    SELECT archived_at FROM bots
                     WHERE id = :id AND tenant_id = :t AND archived_at IS NOT NULL
                    """
                ),
                {"id": bid, "t": _tenant()},
            )
        )
        updated = conn.execute(
            text(
                """
                UPDATE bots SET archived_at = NULL, updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND archived_at IS NOT NULL
                """
            ),
            {"id": bid, "t": _tenant()},
        ).rowcount
        if updated:
            from agent_core import change_log

            change_log.record_restore(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=bid,
                archived_at=(archived_at or {}).get("archived_at"),
            )
    if not updated:
        raise KeyError(f"archived_card_not_found:{bid}")
    return {"ok": True, "botId": bid, "archived": False}


def agent_change_log(bot_id: str | None = None, *, limit: int = 50) -> dict[str, Any]:
    """Publish / rollback / archive history, plus the chain-integrity verdict.

    ``chain`` is reported alongside the entries rather than on a separate call:
    a change log whose integrity you have to remember to check separately is one
    nobody checks.
    """
    from agent_core import change_log

    with engine.connect() as conn:
        return {
            "entries": change_log.read_entries(
                conn, tenant_id=_tenant(), bot_id=bot_id, limit=limit
            ),
            "chain": change_log.verify_chain(conn, tenant_id=_tenant()),
        }


def compile_agent_studio_card(
    bot_id: str,
    *,
    card_raw: dict[str, Any] | None = None,
    flow: Any = None,
    traffic_pct: int | None = None,
    auto_rollback: list[str] | None = None,
    voice: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from agent_core.cards.compile import compile_card
    from agent_core.cards.defaults import card_dump
    from agent_core.tools.catalog import CATALOG

    published, draft = _studio_card_versions(bot_id)
    card = card_raw if isinstance(card_raw, dict) and card_raw else None
    if card is None:
        # Compile preview must gate what publish will actually ship, and publish
        # ships the draft. Falling straight to published reported a green compile
        # for a draft whose card had not been checked.
        for row in (draft, published):
            candidate = (row or {}).get("agentCard")
            if isinstance(candidate, dict) and candidate:
                card = candidate
                break
    if not card:
        try:
            card = card_dump(bot_id)
        except KeyError:
            card = {}
    graph = flow if flow is not None else ((draft or published or {}).get("flow") or {})
    # Same precedence the card itself follows: preview what publish will ship,
    # which is the draft. The caller may pass the editor's unsaved voice and
    # persona instead — without that the preview gates the last autosave, and
    # G15 is exactly the gate an operator would trip between two of them.
    mouth = draft or published or {}
    voice_short, voice_locale, card_locales = voice_locale_facts(
        voice if voice is not None else mouth.get("voice"),
        persona if persona is not None else mouth.get("persona"),
    )
    attached = None
    try:
        from agent_core.cards.schema import is_authored, parse_card
        from agent_core.skills.persist import packs_for_slugs

        raw = card if isinstance(card, dict) else {}
        if is_authored(raw):
            parsed = parse_card(raw)
            attached = packs_for_slugs([r.skill_id for r in parsed.skills]) or None
    except Exception:
        attached = None
    report = compile_card(
        bot_id=bot_id,
        card_raw=card,
        flow=graph,
        catalog_names=set(CATALOG.specs),
        known_bot_ids=list_bot_ids(),
        eval_report=get_latest_eval_report(bot_id=bot_id, kind="regression"),
        redteam_report=get_latest_eval_report(bot_id=bot_id, kind="redteam"),
        twin_report=_latest_twin_gate_report(),
        outbound_report=get_latest_eval_report(bot_id=bot_id, kind="outbound"),
        attached_skills=attached,
        # Without these the preview read the card's stored experiment while
        # publish used the Ship tab's, so G12 reported "full ship" green and the
        # very next call 422'd on "canary split requires auto_rollback".
        traffic_pct=traffic_pct,
        auto_rollback=auto_rollback,
        voice_short_name=voice_short,
        voice_locale=voice_locale,
        card_locales=card_locales,
    )
    return report.model_dump()


def list_persona_presets() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, config
                    FROM persona_presets
                    WHERE tenant_id = :tenant_id
                    ORDER BY CASE id
                      WHEN 'empathetic' THEN 1
                      WHEN 'firm' THEN 2
                      WHEN 'compliance' THEN 3
                      WHEN 'upsell' THEN 4
                      ELSE 99
                    END, id
                    """
                ),
                {"tenant_id": _tenant()},
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
    """Legacy studio alias rows (priya/…); picker uses tts_voice_catalog instead.

    Kept for optional ShortName resolution when an old draft still stores a
    studio alias as voiceId. Deployments no longer FK to this table.
    """
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, config, enabled
                    FROM tts_voices
                    WHERE enabled = true AND tenant_id = :tenant_id
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
                ),
                {"tenant_id": _tenant()},
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


def resolve_prompt_azure_voice(voice: dict[str, Any] | None) -> str:
    """Resolve Prompt Studio voice config → Azure ShortName."""
    from azure_speech import looks_like_azure_short_name, resolve_azure_voice_name

    data = _as_dict(voice)
    short = str(data.get("azureVoiceName") or data.get("shortName") or "").strip()
    if short:
        return short
    voice_id = str(data.get("voiceId") or "").strip()
    if looks_like_azure_short_name(voice_id):
        return voice_id
    db_name: str | None = None
    if voice_id:
        for v in list_tts_voices():
            if v["id"] == voice_id:
                db_name = v.get("azureVoiceName")
                break
    return resolve_azure_voice_name(voice_id or None, db_azure_name=db_name)


def voice_locale_facts(voice: Any, persona: Any) -> tuple[str, str | None, list[str]]:
    """(the short name that will speak, its catalog locale, the card's tags).

    The three inputs G15 needs, resolved in one place so the compile preview and
    publish cannot disagree about them. The short name comes from
    ``resolve_prompt_azure_voice`` rather than ``voice.voiceId`` because that is
    what seeds ``AgentTuning.tts.voice`` — the gate has to judge the voice that
    will actually speak, not the one the row happens to carry.

    Locale is ``None`` when the catalog cannot resolve the id; the gate skips on
    that rather than guessing, since the runtime falls back to a different voice
    entirely in that case.
    """
    from agent_core import languages

    cfg = _as_dict(voice)
    short = resolve_prompt_azure_voice(cfg) if cfg else ""
    entry = get_tts_voice_catalog_entry(short) if short else None
    locale = str((entry or {}).get("locale") or "").strip() or None
    p = _as_dict(persona)
    fallbacks = p.get("fallbackLanguages")
    names = [p.get("language"), *(fallbacks if isinstance(fallbacks, list) else [])]
    tags: list[str] = []
    for name in names:
        tag = languages.tag_for(str(name)) if name else None
        if tag and tag not in tags:
            tags.append(tag)
    return short, locale, tags


def _map_catalog_row(r: dict[str, Any], *, include_raw: bool = False) -> dict[str, Any]:
    styles = r.get("styles")
    if not isinstance(styles, list):
        styles = []
    model_series = r.get("model_series")
    if not isinstance(model_series, list):
        model_series = []
    personalities = r.get("personalities")
    if not isinstance(personalities, list):
        personalities = []
    scenarios = r.get("scenarios")
    if not isinstance(scenarios, list):
        scenarios = []
    out: dict[str, Any] = {
        "shortName": r["short_name"],
        "displayName": r.get("display_name") or r["short_name"],
        "localName": r.get("local_name") or "",
        "gender": r.get("gender") or "Neutral",
        "locale": r.get("locale") or "",
        "localeName": r.get("locale_name") or "",
        "voiceType": r.get("voice_type") or "Neural",
        "status": r.get("status") or "GA",
        "priceTier": r.get("price_tier") or "standard",
        "providerId": r.get("provider_id") or "azure",
        "isPremium": bool(r.get("is_premium")),
        "approxUsdPer1MChars": (
            float(r["approx_usd"]) if r.get("approx_usd") is not None else None
        ),
        "styles": [str(s) for s in styles],
        "personalities": [str(s) for s in personalities],
        "scenarios": [str(s) for s in scenarios],
        "wordsPerMinute": r.get("words_per_minute"),
        "sampleRateHertz": r.get("sample_rate_hertz"),
        "modelSeries": [str(s) for s in model_series],
        "removedAt": r["removed_at"].isoformat() if r.get("removed_at") else None,
        "enabledForPicker": bool(r.get("enabled_for_picker", True)),
    }
    if include_raw:
        out["raw"] = _as_dict(r.get("raw"))
    return out


def list_tts_voice_catalog(
    *,
    q: str | None = None,
    locale: str | None = None,
    gender: str | None = None,
    status: str | None = "GA",
    price_tier: str | None = None,
    provider_id: str | None = None,
    include_premium: bool = False,
    include_removed: bool = False,
    limit: int = 60,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Filtered TTS catalog for the Voice picker.

    ``provider_id`` filters server-side rather than in the browser: the list is
    keyset-paginated, so a client-side provider filter would only ever filter
    the page already fetched and would report counts for a subset.
    """
    from tts_catalog_sync import DEFAULT_VOICE, last_synced_at

    limit = max(1, min(int(limit or 60), 200))
    clauses = ["c.enabled_for_picker = true"]
    params: dict[str, Any] = {"limit": limit}
    if not include_removed:
        clauses.append("c.removed_at IS NULL")
    if not include_premium:
        clauses.append("c.is_premium = false")
    if status:
        clauses.append("c.status = :status")
        params["status"] = status
    if gender:
        clauses.append("lower(c.gender) = lower(:gender)")
        params["gender"] = gender
    if price_tier:
        clauses.append("c.price_tier = :price_tier")
        params["price_tier"] = price_tier
    if provider_id:
        # Rows synced before the registry have NULL provider_id and are Azure
        # by construction, so azure must match them too or the default provider
        # filter would hide 774 voices.
        if provider_id == "azure":
            clauses.append("(c.provider_id = :provider_id OR c.provider_id IS NULL)")
        else:
            clauses.append("c.provider_id = :provider_id")
        params["provider_id"] = provider_id
    if locale:
        loc = locale.strip()
        if loc.endswith("-") or loc.endswith("*"):
            clauses.append("c.locale ILIKE :locale_prefix")
            params["locale_prefix"] = loc.rstrip("*") + "%"
        else:
            clauses.append("c.locale = :locale")
            params["locale"] = loc
    if q:
        clauses.append(
            "("
            "c.short_name ILIKE :q OR c.display_name ILIKE :q OR c.local_name ILIKE :q "
            "OR c.locale_name ILIKE :q OR c.locale ILIKE :q"
            ")"
        )
        params["q"] = f"%{q.strip()}%"
    if cursor:
        clauses.append(
            "(c.locale, c.display_name, c.short_name) > "
            "(SELECT locale, display_name, short_name FROM tts_voice_catalog WHERE short_name = :cursor)"
        )
        params["cursor"] = cursor

    where = " AND ".join(clauses)
    with engine.connect() as conn:
        total = (
            conn.execute(
                text(f"SELECT count(*)::int AS n FROM tts_voice_catalog c WHERE {where}"),
                {k: v for k, v in params.items() if k != "limit"},
            )
            .mappings()
            .first()
        )
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT c.*, t.approx_usd_per_1m_chars AS approx_usd
                    FROM tts_voice_catalog c
                    LEFT JOIN tts_price_tiers t ON t.tier = c.price_tier
                    WHERE {where}
                    ORDER BY c.locale, c.display_name, c.short_name
                    LIMIT :limit
                    """
                ),
                params,
            )
        )
    items = [_map_catalog_row(r) for r in rows]
    next_cursor = items[-1]["shortName"] if len(items) == limit else None
    synced = last_synced_at(engine)
    return {
        "items": items,
        "total": int(total["n"]) if total else 0,
        "nextCursor": next_cursor,
        "lastSyncedAt": synced.isoformat() if synced else None,
        "defaultVoice": DEFAULT_VOICE,
        "premiumHiddenByDefault": True,
    }


def get_tts_voice_catalog_entry(short_name: str) -> dict[str, Any] | None:
    sn = (short_name or "").strip()
    if not sn:
        return None
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT c.*, t.approx_usd_per_1m_chars AS approx_usd
                    FROM tts_voice_catalog c
                    LEFT JOIN tts_price_tiers t ON t.tier = c.price_tier
                    WHERE c.short_name = :sn
                    """
                ),
                {"sn": sn},
            )
        )
    return _map_catalog_row(row, include_raw=True) if row else None


def list_tts_price_tiers() -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT tier, label, approx_usd_per_1m_chars, is_premium, notes
                    FROM tts_price_tiers
                    ORDER BY CASE tier
                      WHEN 'standard' THEN 1
                      WHEN 'hd_flash' THEN 2
                      WHEN 'hd' THEN 3
                      WHEN 'turbo' THEN 4
                      ELSE 99
                    END
                    """
                )
            )
        )
    return [
        {
            "tier": r["tier"],
            "label": r["label"],
            "approxUsdPer1MChars": (
                float(r["approx_usd_per_1m_chars"])
                if r.get("approx_usd_per_1m_chars") is not None
                else None
            ),
            "isPremium": bool(r["is_premium"]),
            "notes": r.get("notes") or "",
        }
        for r in rows
    ]


def tts_catalog_is_populated() -> bool:
    """True when the Azure voice catalog has been synced at least once."""
    with engine.connect() as conn:
        return bool(_one(conn.execute(text("SELECT 1 FROM tts_voice_catalog LIMIT 1"))))


def get_tts_voice_warning(short_name: str | None) -> dict[str, Any] | None:
    """Warn when selected voice is missing / removed / deprecated.

    Returns None when the catalog has never been synced. An empty table means
    "no catalog data", not "Azure removed every voice" — and because the caller
    rewrites ``tts.voice`` to ``fallbackVoice``, judging on no data silently
    forced every call onto the default voice regardless of what the operator
    picked in Prompt Studio or the Tuning Studio.
    """
    from tts_catalog_sync import DEFAULT_VOICE

    sn = (short_name or "").strip()
    if not sn:
        return None
    entry = get_tts_voice_catalog_entry(sn)
    if entry is None:
        # The fallback cannot be "missing" — rewriting it to itself is noise,
        # and reporting it as broken is misleading in the Studio's voice picker.
        if sn == DEFAULT_VOICE or not tts_catalog_is_populated():
            return None
        return {
            "shortName": sn,
            "code": "missing",
            "message": f"Voice {sn} is not in the catalog; runtime will use {DEFAULT_VOICE}.",
            "fallbackVoice": DEFAULT_VOICE,
        }
    if entry.get("removedAt"):
        return {
            "shortName": sn,
            "code": "removed",
            "message": f"Voice {sn} was removed from Azure; runtime will use {DEFAULT_VOICE}.",
            "fallbackVoice": DEFAULT_VOICE,
        }
    if str(entry.get("status") or "").lower() == "deprecated":
        return {
            "shortName": sn,
            "code": "deprecated",
            "message": f"Voice {sn} is deprecated; consider switching to {DEFAULT_VOICE}.",
            "fallbackVoice": DEFAULT_VOICE,
        }
    return None


def _tts_sync_run_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None

    def _ts(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return {
        "id": row["id"],
        "startedAt": _ts(row.get("started_at")),
        "finishedAt": _ts(row.get("finished_at")),
        "source": row.get("source"),
        "fetchedCount": int(row.get("fetched_count") or 0),
        "upserted": int(row.get("upserted") or 0),
        "softRemoved": int(row.get("soft_removed") or 0),
        "unchanged": int(row.get("unchanged") or 0),
        "error": row.get("error"),
        "region": row.get("region") or "",
    }


def latest_tts_sync_run() -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, started_at, finished_at, source, fetched_count, upserted,
                           soft_removed, unchanged, error, region
                    FROM tts_voice_sync_runs
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                )
            )
        )
    return _tts_sync_run_row(row)


def list_tts_sync_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit or 20), 100))
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, started_at, finished_at, source, fetched_count, upserted,
                           soft_removed, unchanged, error, region
                    FROM tts_voice_sync_runs
                    ORDER BY started_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": lim},
            )
        )
    out: list[dict[str, Any]] = []
    for row in rows:
        mapped = _tts_sync_run_row(row)
        if mapped:
            out.append(mapped)
    return out


def list_bot_deployments(
    *,
    environment: str | None = None,
    status: str | None = None,
    bot_id: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Runtime deployments — authoritative for what runs.

    Paged: this table gains a row on every publish, so it grows with release
    cadence rather than staying at the handful the demo has.
    """
    clauses = ["1=1"]
    params: dict[str, Any] = {}
    if environment in ("sandbox", "production"):
        clauses.append("d.environment = :environment")
        params["environment"] = environment
    if status in ("active", "rolled_back", "retired"):
        clauses.append("d.status = :status")
        params["status"] = status
    if bot_id:
        clauses.append("d.bot_id = :bot_id")
        params["bot_id"] = bot_id
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
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": clamp_list_limit(limit), "offset": clamp_offset(offset)},
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
      d.traffic_pct, d.shadow, d.eval_report_id,
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

    Multi-bot: filtered by bot_id. One published prompt per bot.
    """
    bid = (bot_id or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    env = environment if environment in ("sandbox", "production") else "production"
    with engine.connect() as conn:
        row = _fetch_active_deployment_row(conn, bot_id=bid, environment=env)
        return _map_bot_deployment_row(row) if row else None


def get_deployment(deployment_id: str) -> dict[str, Any] | None:
    """Load a deployment by id, including retired baselines used by canary split."""
    with engine.connect() as conn:
        return _fetch_bot_deployment(conn, deployment_id)


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
      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
      p.bot_id, p.agent_card, p.created_at,
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
        "trafficPct": int(r.get("traffic_pct") or 100),
        "shadow": bool(r.get("shadow")),
        "evalReportId": r.get("eval_report_id"),
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
                  d.traffic_pct, d.shadow, d.eval_report_id,
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

    label = (payload.get("label") or "").strip() or None
    version_id = _prompt_id_from_label(label)
    voice = _prompt_voice(payload.get("voice"))
    # Seed draft.tuning from Prompt Studio voice sliders (one source of truth).
    draft_tuning = apply_voice_config_overlay(
        default_tuning(),
        voice_name=resolve_prompt_azure_voice(voice),
        speed=float(voice.get("speed", 1.0)),
        pitch=int(voice.get("pitch", 0)),
        warmth=int(voice.get("warmth", 60)),
        params=voice.get("params"),
    )
    with engine.begin() as conn:
        # Avoid colliding with an existing id (e.g. republish of same label slug).
        if _one(conn.execute(text("SELECT 1 FROM prompt_versions WHERE id = :id"), {"id": version_id})):
            version_id = f"{version_id}-{uuid.uuid4().hex[:6]}"
        bot_id = str(payload.get("botId") or payload.get("bot_id") or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
        if not _one(conn.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": bot_id})):
            raise KeyError(f"bot_not_found:{bot_id}")
        card_raw = payload.get("agentCard") if "agentCard" in payload else payload.get("agent_card")
        if card_raw is None:
            # Inherit this bot's current card before reaching for the on-disk
            # first-party default. Autosave and publish both create versions
            # without an agentCard, so jumping straight to card_dump reset every
            # authored skill/tool edit on a first-party bot, and wiped the card
            # outright on a tenant clone (card_dump raises for those ids).
            inherited = _one(
                conn.execute(
                    text(
                        """
                        SELECT agent_card FROM prompt_versions
                         WHERE bot_id = :bot_id
                           AND status IN ('published', 'draft')
                           AND agent_card IS NOT NULL
                           AND agent_card <> '{}'::jsonb
                         ORDER BY (status = 'published') DESC, created_at DESC, id DESC
                         LIMIT 1
                        """
                    ),
                    {"bot_id": bot_id},
                )
            )
            card_raw = _as_dict((inherited or {}).get("agent_card")) or None
        if card_raw is None:
            try:
                from agent_core.cards.defaults import card_dump as _card_dump

                card_raw = _card_dump(bot_id)
            except KeyError:
                card_raw = {}
        conn.execute(
            text(
                """
                INSERT INTO prompt_versions (
                  id, tenant_id, bot_id, author_user_id, status, prompt, persona, voice,
                  guardrails, tuning, flow, agent_card, label, summary, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :bot_id, :author, 'draft', :prompt,
                  CAST(:persona AS jsonb), CAST(:voice AS jsonb), CAST(:guardrails AS jsonb),
                  CAST(:tuning AS jsonb), CAST(:flow AS jsonb), CAST(:agent_card AS jsonb),
                  :label, :summary, now(), now()
                )
                """
            ),
            {
                "id": version_id,
                "tenant_id": _tenant(),
                "bot_id": bot_id,
                "author": _actor_user_id(),
                "prompt": payload["prompt"],
                "persona": _jsonb(payload["persona"]),
                "voice": _jsonb(voice),
                "guardrails": _jsonb(payload["guardrails"]),
                "tuning": _jsonb(draft_tuning),
                # Absent flow stores '{}', which parse_graph reads as "no graph"
                # and the runtime treats as "use the built-in flow".
                "flow": _jsonb(payload.get("flow") or {}),
                "agent_card": _jsonb(card_raw if isinstance(card_raw, dict) else {}),
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

            voice = _prompt_voice(payload["voice"])
            sets.append("voice = CAST(:voice AS jsonb)")
            params["voice"] = _jsonb(voice)
            # Keep draft.tuning in sync with VoicePanel sliders (publish reads this).
            folded = apply_voice_config_overlay(
                normalize_tuning(_as_dict(existing.get("tuning"))),
                voice_name=resolve_prompt_azure_voice(voice),
                speed=float(voice.get("speed", 1.0)),
                pitch=int(voice.get("pitch", 0)),
                warmth=int(voice.get("warmth", 60)),
                params=voice.get("params"),
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
        # Key present vs omitted, not truthiness: an explicit {} means "no
        # authored graph" (use the built-in script). A missing key leaves the
        # stored graph alone so a save that never opened the flow tab cannot
        # wipe one.
        if "flow" in payload:
            flow_val = payload["flow"]
            if hasattr(flow_val, "model_dump"):
                flow_val = flow_val.model_dump()
            sets.append("flow = CAST(:flow AS jsonb)")
            params["flow"] = _jsonb(flow_val or {})
        card_val = payload["agentCard"] if "agentCard" in payload else payload.get("agent_card") if "agent_card" in payload else None
        if "agentCard" in payload or "agent_card" in payload:
            if hasattr(card_val, "model_dump"):
                card_val = card_val.model_dump()
            sets.append("agent_card = CAST(:agent_card AS jsonb)")
            params["agent_card"] = _jsonb(card_val if isinstance(card_val, dict) else {})
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


def _change_log_components(
    conn: Any, version_id: str, target: dict[str, Any], summary: str
) -> dict[str, Any]:
    """The version as the change log hashes it.

    Read back rather than taken from ``target``: the publishing transaction
    rewrites ``agent_card`` (the shipped experiment) and ``tuning`` before this
    point, so the in-memory copy is stale and the digest would describe a
    version that was never live.
    """
    row = _one(
        conn.execute(
            text(
                """
                SELECT id, label, prompt, persona, voice, guardrails, flow, agent_card
                  FROM prompt_versions WHERE id = :id
                """
            ),
            {"id": version_id},
        )
    ) or {}
    return {**dict(row), "label": row.get("label") or target.get("label"), "summary": summary}


def publish_prompt_version(
    version_id: str,
    summary: str = "",
    *,
    kb_snapshot_id: str | None = None,
    tuning: dict[str, Any] | None = None,
    traffic_pct: int | None = None,
    shadow: bool = False,
    auto_rollback: list[str] | None = None,
) -> dict[str, Any]:
    """Archive current published → promote draft → swap active prod deployment.

    kb_snapshot_id: explicit Sandbox pin wins; else prior active snap, else latest.
    tuning: explicit AgentTuning from Sandbox Promote; else prior deployment tuning.
    """
    from sqlalchemy.exc import IntegrityError
    from agent_core.tuning import apply_voice_config_overlay, default_tuning, normalize_tuning

    with engine.begin() as conn:
        target = _one(
            conn.execute(
                text(
                    """
                    SELECT id, status, voice, persona, label, tuning, flow, bot_id, agent_card
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

        bot_id = str(target.get("bot_id") or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
        # Serialize publish/rollback for this bot+env (single-active invariant).
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"{bot_id}:production"},
        )

        # Compiler: flow + Agent Card gates. Empty card is legacy (G0 skipped).
        from agent_core.cards.compile import compile_card, assert_publishable as _assert_card
        from agent_core.tools.catalog import CATALOG as _CATALOG

        known_bots = {r["id"] for r in _rows(conn.execute(text("SELECT id FROM bots")))}
        card_raw = target.get("agent_card") if isinstance(target.get("agent_card"), dict) else {}
        attached = None
        try:
            from agent_core.cards.schema import is_authored, parse_card
            from agent_core.skills.persist import packs_for_slugs, sync_attachments_from_card

            if is_authored(card_raw):
                parsed = parse_card(card_raw)
                attached = packs_for_slugs([r.skill_id for r in parsed.skills]) or None
        except Exception:
            attached = None
        exp = card_raw.get("experiment") if isinstance(card_raw.get("experiment"), dict) else {}
        pct = traffic_pct if traffic_pct is not None else int(exp.get("traffic_pct") or 100)
        triggers = auto_rollback if auto_rollback is not None else list(exp.get("auto_rollback") or [])
        a2a_raw = card_raw.get("a2a") if isinstance(card_raw.get("a2a"), dict) else {}
        cert_ok = None
        if a2a_raw.get("expose"):
            try:
                from agent_core.a2a import partner_has_cert

                cert_ok = partner_has_cert(bot_id)
            except Exception:
                cert_ok = False
        import authz as _authz

        uid = _actor_user_id()
        has_publish = bool(uid and _authz.has_permission(uid, _authz.AGENT_PUBLISH))
        voice_short, voice_locale, card_locales = voice_locale_facts(
            target.get("voice"), target.get("persona")
        )
        report = compile_card(
            bot_id=bot_id,
            card_raw=card_raw,
            flow=target.get("flow"),
            catalog_names=set(_CATALOG.specs),
            known_bot_ids=known_bots,
            eval_report=get_latest_eval_report(bot_id=bot_id, kind="regression"),
            redteam_report=get_latest_eval_report(bot_id=bot_id, kind="redteam"),
            twin_report=_latest_twin_gate_report(),
            outbound_report=get_latest_eval_report(bot_id=bot_id, kind="outbound"),
            attached_skills=attached,
            traffic_pct=pct,
            auto_rollback=triggers,
            has_publish=has_publish,
            a2a_cert_ok=cert_ok,
            voice_short_name=voice_short,
            voice_locale=voice_locale,
            card_locales=card_locales,
        )
        _assert_card(report)
        # Fold the shipped experiment back into the card. The deployment row
        # recorded the split, but the card kept whatever it was authored with —
        # so the Studio's Ship tab, which reads the card, showed 100% after a
        # 40% canary and would silently re-ship at full traffic on the next
        # publish. Only valid triggers are stored: CardExperiment types them as
        # a Literal, so an unknown one would make the card unparseable.
        shipped_card = card_raw
        try:
            from agent_core.cards.compile import _ROLLBACK_TRIGGERS
            from agent_core.cards.schema import is_authored as _is_authored

            if _is_authored(card_raw):
                shipped_exp = {
                    "traffic_pct": int(pct),
                    "shadow": bool(shadow),
                    "auto_rollback": [t for t in triggers if t in _ROLLBACK_TRIGGERS],
                }
                if (card_raw.get("experiment") or {}) != shipped_exp:
                    shipped_card = {**card_raw, "experiment": shipped_exp}
                    conn.execute(
                        text(
                            """
                            UPDATE prompt_versions
                            SET agent_card = CAST(:card AS jsonb), updated_at = now()
                            WHERE id = :id
                            """
                        ),
                        {"id": version_id, "card": _jsonb(shipped_card)},
                    )
        except Exception:
            logger.exception("could not persist the shipped experiment onto the card")
        try:
            from agent_core.skills.persist import sync_attachments_from_card

            sync_attachments_from_card(version_id, card_raw)
        except Exception:
            logger.exception("skill attachment sync failed")

        note = (summary or "").strip()
        voice = _prompt_voice(target.get("voice"))
        # Column stores Azure ShortName (no FK to legacy tts_voices aliases).
        if tuning is not None:
            early = normalize_tuning(tuning)
            tts_voice_id = str((early.get("tts") or {}).get("voice") or "").strip() or None
        else:
            tts_voice_id = None
        if not tts_voice_id:
            tts_voice_id = resolve_prompt_azure_voice(voice) or _DEFAULT_AZURE_TTS_VOICE

        prior = _fetch_active_deployment_row(
            conn, bot_id=bot_id, environment="production"
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
        # Keep voice_config.azureVoiceName aligned with the authoritative ShortName.
        voice_config = {
            **voice_config,
            **{
                k: voice.get(k)
                for k in ("speed", "pitch", "warmth", "pauseMs", "sampleText", "style", "params")
                if k in voice
            },
            "azureVoiceName": tts_voice_id,
            "voiceId": tts_voice_id,
        }
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
                voice_name=tts_voice_id,
                speed=float(voice.get("speed", 1.0)),
                pitch=int(voice.get("pitch", 0)),
                warmth=int(voice.get("warmth", 60)),
                params=voice.get("params"),
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

        # Captured while it is still the live row — the change log diffs the
        # incoming version against the one it replaces, and the next statement
        # archives it.
        previously_published = _one(
            conn.execute(
                text(
                    """
                    SELECT id, label, prompt, persona, voice, guardrails, flow, agent_card
                      FROM prompt_versions
                     WHERE bot_id = :bot_id AND status = 'published'
                     LIMIT 1
                    """
                ),
                {"bot_id": bot_id},
            )
        )

        try:
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'archived', updated_at = now()
                    WHERE status = 'published' AND bot_id = :bot_id
                    """
                ),
                {"bot_id": bot_id},
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
                      rollback_deployment_id, voice_config, tuning,
                      traffic_pct, shadow, created_at, updated_at
                    ) VALUES (
                      :id, :bot_id, :prompt_version_id, :kb_snapshot_id, :tts_voice_id,
                      'production', 'active', :actor, now(),
                      :rollback_id, CAST(:voice_config AS jsonb), CAST(:tuning AS jsonb),
                      :traffic_pct, :shadow, now(), now()
                    )
                    """
                ),
                {
                    "id": dep_id,
                    "bot_id": bot_id,
                    "prompt_version_id": version_id,
                    "kb_snapshot_id": resolved_snap,
                    "tts_voice_id": tts_voice_id,
                    "actor": _actor_user_id(),
                    "rollback_id": prior["id"] if prior else None,
                    "voice_config": _jsonb(voice_config),
                    "tuning": _jsonb(resolved_tuning),
                    "traffic_pct": pct,
                    "shadow": bool(shadow),
                },
            )
            try:
                from agent_core.canary import record_experiment

                record_experiment(
                    conn,
                    bot_id=bot_id,
                    canary_deployment_id=dep_id,
                    baseline_deployment_id=prior["id"] if prior else None,
                    traffic_pct=pct,
                    shadow=bool(shadow),
                    auto_rollback=list(triggers or []),
                )
            except Exception:
                logger.exception("canary experiment record failed")

            # Change log — inside the transaction on purpose. A record that can
            # be lost when the process dies mid-publish is worse than none,
            # because it looks complete. Not wrapped in try/except for the same
            # reason: if the agent's configuration history cannot be written,
            # the configuration must not change either.
            from agent_core import change_log

            change_log.record_publish(
                conn,
                tenant_id=_tenant(),
                actor_user_id=uid or "system",
                entry_id=_id("AUD"),
                bot_id=bot_id,
                version=_change_log_components(conn, version_id, target, note),
                previous_version=previously_published,
                deployment_id=dep_id,
                traffic_pct=pct,
                shadow=bool(shadow),
                auto_rollback=list(triggers or []),
                report=report,
            )
        except IntegrityError as exc:
            raise ValueError("publish_conflict") from exc

        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row


def _restorable_voice(raw: Any) -> dict[str, Any]:
    """The stored voice, normalised to something that can actually speak.

    Restore copied the jsonb verbatim, which is the one write path that never
    ran the voice through ``_prompt_voice``. A version carrying a hand-edited or
    legacy id therefore produced a draft whose Voice tab named one voice and
    whose runtime spoke the fallback — and the draft could then be published in
    that state. The catalog check on top of the whitelist is what turns an id
    nothing can resolve into the same fallback the picker already displays.

    Provider controls go with it. ``style`` and ``params`` are the vocabulary of
    the provider that owns the missing voice; carried onto an Azure fallback
    they are noise the SSML preview would try to honour.
    """
    voice = _prompt_voice(raw)
    warning = get_tts_voice_warning(resolve_prompt_azure_voice(voice))
    if warning and warning.get("code") in {"missing", "removed"} and warning.get("fallbackVoice"):
        fallback = str(warning["fallbackVoice"])
        voice["voiceId"] = fallback
        voice["azureVoiceName"] = fallback
        voice["style"] = None
        voice["params"] = {}
    return voice


def restore_prompt_version_as_draft(version_id: str) -> dict[str, Any]:
    """Copy any version into a new draft — never mutates live published/deployment."""
    from agent_core.tuning import normalize_tuning

    with engine.begin() as conn:
        source = _one(
            conn.execute(
                text(
                    """
                    SELECT id, label, prompt, persona, voice, guardrails, tuning, flow,
                           bot_id, agent_card
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
        tuning_json = _jsonb(normalize_tuning(_as_dict(source.get("tuning"))))
        conn.execute(
            text(
                """
                INSERT INTO prompt_versions (
                  id, tenant_id, bot_id, author_user_id, status, prompt, persona, voice,
                  guardrails, tuning, flow, agent_card, label, summary, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :bot_id, :author, 'draft', :prompt,
                  CAST(:persona AS jsonb), CAST(:voice AS jsonb), CAST(:guardrails AS jsonb),
                  CAST(:tuning AS jsonb), CAST(:flow AS jsonb), CAST(:agent_card AS jsonb),
                  :label, :summary, now(), now()
                )
                """
            ),
            {
                "id": new_id,
                "tenant_id": _tenant(),
                "bot_id": source.get("bot_id") or DEFAULT_BOT_ID,
                "author": _actor_user_id(),
                "prompt": source["prompt"],
                "persona": _jsonb(_as_dict(source.get("persona"))),
                "voice": _jsonb(_restorable_voice(source.get("voice"))),
                "guardrails": _jsonb(_as_dict(source.get("guardrails"))),
                "tuning": tuning_json,
                # Carried across: a restore that dropped the graph would produce
                # a draft that is not actually the version it claims to restore.
                "flow": _jsonb(_as_dict(source.get("flow"))),
                "agent_card": _jsonb(_as_dict(source.get("agent_card"))),
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
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"{target['bot_id']}:{target['environment']}"},
        )
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
                    WHERE status = 'published' AND bot_id = :bot_id
                    """
                ),
                {"bot_id": target["bot_id"]},
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

            # A rollback changes what callers hear exactly as much as a publish
            # does, so it belongs in the same chain.
            from agent_core import change_log

            change_log.record_rollback(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=target["bot_id"],
                to_deployment_id=new_id,
                from_deployment_id=current["id"] if current else None,
                version_id=prompt_version_id,
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


def list_kb_documents(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    _KB_DOC_SELECT
                    + " ORDER BY d.updated_at DESC, d.id ASC LIMIT :limit OFFSET :offset"
                ),
                {"limit": page, "offset": skip},
            )
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


def list_kb_chunks(
    document_id: str, *, limit: int | None = None, offset: int | None = None
) -> list[dict[str, Any]]:
    """Chunks of one document, newest ingest first within chunk order.

    Bounded because every row carries its full chunk ``text``: a long policy PDF
    is thousands of chunks, and the chunk viewer only ever renders a page of
    them. This was the largest single response the API could produce.
    """
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, document_id, heading, tokens, text, hits, chunk_index
                    FROM kb_chunks
                    WHERE document_id = :id
                    ORDER BY chunk_index ASC, created_at ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"id": document_id, "limit": page, "offset": skip},
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
                {"tenant_id": _tenant()},
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

    # The object is already in MinIO. If the rows that give it a name never
    # commit, nothing will ever reference or reclaim it — compensate here so a
    # failed upload does not leave a permanently unreachable blob behind.
    try:
        job_id = _kb_upload_rows(
            doc_id=doc_id,
            file_id=file_id,
            storage_ref=storage_ref,
            safe_name=safe_name,
            mime=mime,
            data=data,
            content_hash=content_hash,
            doc_type=doc_type,
            display_title=display_title,
            tag_list=tag_list,
            chunk_size=chunk_size,
            overlap=overlap,
            index_now=index_now,
        )
    except Exception:
        _discard_orphan_object(storage_ref)
        raise

    doc = get_kb_document(doc_id)
    assert doc is not None
    return {"document": doc, "jobId": job_id}


def _discard_orphan_object(storage_ref: str) -> None:
    """Best-effort delete of an object whose owning rows never committed."""
    import storage as object_store

    try:
        object_store.delete_object(storage_ref)
    except Exception:
        logger.warning("orphaned kb upload not reclaimed: %s", storage_ref, exc_info=True)


def _kb_upload_rows(
    *,
    doc_id: str,
    file_id: str,
    storage_ref: str,
    safe_name: str,
    mime: str,
    data: bytes,
    content_hash: str,
    doc_type: str,
    display_title: str,
    tag_list: list[str],
    chunk_size: int,
    overlap: int,
    index_now: bool,
) -> str | None:
    import json

    import kb_ingest

    job_id: str | None = None
    with engine.begin() as conn:
        status = "indexing" if index_now else "draft"
        enabled = bool(index_now)
        conn.execute(
            text(
                """
                INSERT INTO kb_documents (
                  id, tenant_id, updated_by_user_id, type, version, status, enabled,
                  chunk_size, chunk_overlap, title, tags, embedding_model,
                  product_key, source_path, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :actor, :type, 'v1.0', :status, :enabled,
                  :chunk_size, :overlap, :title, CAST(:tags AS jsonb), NULL,
                  NULL, NULL, now(), now()
                )
                """
            ),
            {
                "id": doc_id,
                "tenant_id": _tenant(),
                "actor": _actor_user_id(),
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
    return job_id


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

    storage_ref: str | None = None
    try:
        with engine.begin() as conn:
            row = _one(
                conn.execute(
                    text(
                        """
                        SELECT id, version, chunk_size, chunk_overlap
                        FROM kb_documents WHERE id = :id
                        FOR UPDATE
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
                {"id": document_id, "version": new_version, "actor": _actor_user_id()},
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

    except Exception:
        # The version object is written inside the transaction; a later
        # failure rolls the rows back but not the blob.
        if storage_ref:
            _discard_orphan_object(storage_ref)
        raise

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


def list_kb_faqs(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, question, answer, intent, enabled,
                           linked_document_id, updated_at
                    FROM faq_pairs
                    ORDER BY updated_at DESC, id ASC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip},
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
    if embedding is None:
        logger.warning("faq_create_without_embedding faq_id=%s", faq_id)
    gap_id = payload.get("gapId")

    with engine.begin() as conn:
        if embedding is None:
            conn.execute(
                text(
                    """
                    INSERT INTO faq_pairs (
                      id, linked_document_id, intent, question, answer, enabled,
                      embedding, created_at, updated_at
                    ) VALUES (
                      :id, :linked, :intent, :question, :answer, :enabled,
                      NULL, now(), now()
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
                },
            )
        else:
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
    # Validate under a short transaction, then embed *outside* any checked-out
    # connection so Azure latency cannot pin a pool slot.
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

        if sets and not reembed:
            sets.append("updated_at = now()")
            conn.execute(
                text(f"UPDATE faq_pairs SET {', '.join(sets)} WHERE id = :id"),
                params,
            )

    if reembed:
        emb = _embed_faq_pair(question, answer)
        if emb is None:
            logger.warning("faq_reembed_skipped faq_id=%s reason=embed_none", faq_id)
        else:
            sets.append("embedding = CAST(:embedding AS vector)")
            params["embedding"] = emb
        sets.append("updated_at = now()")
        with engine.begin() as conn:
            res = conn.execute(
                text(f"UPDATE faq_pairs SET {', '.join(sets)} WHERE id = :id"),
                params,
            )
            # The non-reembed branch raises on a missing row; this one silently
            # reported success for a deleted FAQ.
            if res.rowcount == 0:
                raise KeyError(f"faq not found: {faq_id}")

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


# A question shorter than this is not a content gap — it is "ok", "haan", a
# stray STT fragment, or a barge-in. Recording those buries the real gaps.
KB_GAP_MIN_CHARS = 8
# Long enough for a real question, short enough that the KB-gap table stays
# readable and one runaway turn cannot store a transcript.
KB_GAP_MAX_CHARS = 300


def record_kb_gap(
    *,
    question: str,
    intent: str | None = None,
    channel: str | None = None,
    interaction_id: str | None = None,
    conn: Any | None = None,
) -> str | None:
    """Record that the bot could not answer ``question``. Upsert, not insert.

    Returns the gap id, or ``None`` when the question was too short to be worth
    recording. ``channel`` and ``interaction_id`` are accepted for call-site
    symmetry and logging; the table deliberately does not store them — the
    screen aggregates across channels and a per-sighting FK would turn a
    counter into an event log.

    The question is redacted before it is stored. Callers hand us whatever the
    customer said, which on a collections line routinely contains a card or
    mobile number read aloud.
    """
    import pii_redact

    q = " ".join((pii_redact.redact_text(question) or "").split()).strip()
    if len(q) < KB_GAP_MIN_CHARS:
        return None
    q = q[:KB_GAP_MAX_CHARS]

    # "unknown" is what the KB handler's gate produces when no intent was
    # resolved (voice passes apply_intent_gate=False, so it always does). Stored
    # verbatim it becomes a literal "unknown" bucket on the gap screen, sitting
    # next to the "other" bucket that NULL already renders as. Collapse it.
    top_intent = (intent or "").strip().lower()
    if top_intent in {"", "unknown", "other", "none"}:
        top_intent = None

    params = {
        "id": _id("GAP"),
        "tenant_id": _tenant(),
        "question": q,
        "top_intent": top_intent,
    }
    sql = text(
        """
        INSERT INTO unanswered_questions
          (id, tenant_id, question, hit_count, last_seen_at,
           suggested_fix_type, top_intent, created_at, updated_at)
        VALUES
          (:id, :tenant_id, :question, 1, now(), 'kb', :top_intent, now(), now())
        ON CONFLICT (tenant_id, lower(btrim(question))) DO UPDATE SET
          hit_count = unanswered_questions.hit_count + 1,
          last_seen_at = now(),
          -- COALESCE keeps the FIRST intent seen rather than the latest: the
          -- screen groups by it, and a single off-topic sighting should not
          -- relabel a gap that has been asked fifty times.
          top_intent = COALESCE(unanswered_questions.top_intent, EXCLUDED.top_intent),
          -- suggested_fix_type is deliberately NOT touched. It starts at 'kb'
          -- and an operator may switch it to 'prompt'/'both'; overwriting on
          -- every sighting would silently revert their triage decision.
          updated_at = now()
        RETURNING id
        """
    )

    if conn is not None:
        row = _one(conn.execute(sql, params))
        return row["id"] if row else None
    with engine.begin() as own:
        row = _one(own.execute(sql, params))
    return row["id"] if row else None


def purge_stale_kb_gaps(*, ttl_days: int = 90, conn: Any | None = None) -> int:
    """Drop one-off gaps nobody acted on. Returns rows deleted.

    Two guards, both load-bearing. ``hit_count = 1`` keeps anything asked more
    than once, which is the definition of a recurring gap. ``NOT EXISTS`` keeps
    anything an operator linked to a doc, FAQ or prompt version — those links
    cascade from this table, so deleting a linked gap would destroy the record
    that someone already fixed it.
    """
    sql = text(
        """
        DELETE FROM unanswered_questions uq
         WHERE uq.tenant_id = :tenant_id
           AND uq.hit_count <= 1
           AND uq.last_seen_at IS NOT NULL
           AND uq.last_seen_at < now() - CAST(:window AS interval)
           AND NOT EXISTS (
             SELECT 1 FROM analytics_kb_gap_links g
              WHERE g.unanswered_question_id = uq.id
           )
        """
    )
    params = {"tenant_id": _tenant(), "window": f"{max(1, int(ttl_days))} days"}
    if conn is not None:
        return conn.execute(sql, params).rowcount or 0
    with engine.begin() as own:
        return own.execute(sql, params).rowcount or 0


# The screen pages and sorts by hit_count; before runtime capture this table was
# hand-seeded at ~10 rows and unbounded was fine. It now grows with traffic.
KB_GAP_LIST_LIMIT = 200


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
                    LIMIT :lim
                    """
                ),
                {"tenant_id": _tenant(), "lim": KB_GAP_LIST_LIMIT},
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
            {"id": gap_id, "tenant_id": _tenant()},
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
                    WHERE tenant_id = :tenant_id
                    ORDER BY created_at ASC, id ASC
                    """
                ),
                {"tenant_id": _tenant()},
            )
        )
        return [_map_sandbox_scenario(r) for r in rows]


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


def _billing_as_of() -> date:
    """Billing day boundary is always UTC — not the API host's local calendar."""
    return datetime.now(timezone.utc).date()


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
                  AND service_id = ANY(:services)
                  {tenant_sql}
                GROUP BY usage_date, service_id
                ORDER BY usage_date, service_id
                """
            ),
            {**params, "services": list(_METERED_SERVICE_IDS)},
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
        as_of = _billing_as_of()
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
                      WHERE service_id = ANY(:services)
                      UNION
                      SELECT DISTINCT tenant_id FROM interactions
                      WHERE (started_at AT TIME ZONE 'UTC')::date >= :start
                        AND (started_at AT TIME ZONE 'UTC')::date <= :end
                    )
                    OR t.id = :primary
                    ORDER BY t.name
                    """
                ),
                {
                    "start": start,
                    "end": end,
                    "primary": _tenant(),
                    "services": list(_METERED_SERVICE_IDS),
                },
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

        # The measured counterpart to cost_per_call above. Kept alongside rather
        # than replacing it: calls that predate metering have no events, so this
        # is 0 for historical windows and the allocated figure is still the only
        # number available there.
        attributed_cpc, attributed_calls = _attributed_cost_per_call(
            conn, start=start, end=end, env=env, tenant_id=tenant_id
        )
        model_spend = _model_spend(
            conn, start=start, end=end, env=env, tenant_id=tenant_id
        )
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
                          AND service_id = ANY(:services)
                          {tenant_sql}
                        """
                    ),
                    {**params, "services": list(_METERED_SERVICE_IDS)},
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
                          AND service_id = ANY(:services)
                        GROUP BY tenant_id
                        """
                    ),
                    {
                        "env": env,
                        "start": start,
                        "end": end,
                        "services": list(_METERED_SERVICE_IDS),
                    },
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
                          AND service_id = ANY(:services)
                        GROUP BY tenant_id
                        """
                    ),
                    {
                        "env": env,
                        "start": prev_start,
                        "end": prev_end,
                        "services": list(_METERED_SERVICE_IDS),
                    },
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
                      AND service_id = ANY(:services)
                    GROUP BY service_id, tenant_id
                    """
                ),
                {
                    "env": env,
                    "start": start,
                    "end": end,
                    "services": list(_METERED_SERVICE_IDS),
                },
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
            "attributedCostPerCall": attributed_cpc,
            "attributedCalls": attributed_calls,
            "modelSpend": model_spend,
        }


def interaction_cost(interaction_id: str) -> dict[str, Any]:
    """What one call actually cost, broken down by service and model.

    Reads ``usage_events`` rather than the daily rollup: the rollup is keyed by
    (service, tenant, env, day) and deliberately carries neither dimension.

    ``attributed`` distinguishes "this call cost nothing" from "this call
    predates metering" — every voice call before the pipeline was instrumented
    has no events at all, and showing those as ₹0.00 would be a lie.
    """
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT ue.service_id,
                           bs.name  AS service_name,
                           bs.unit  AS unit,
                           bs.category,
                           bs.color,
                           ue.model,
                           SUM(ue.units)    AS units,
                           SUM(ue.cost_inr) AS cost,
                           COUNT(*)         AS events
                      FROM usage_events ue
                      JOIN billing_services bs ON bs.id = ue.service_id
                     WHERE ue.interaction_id = :ix
                     GROUP BY ue.service_id, bs.name, bs.unit, bs.category,
                              bs.color, ue.model
                     ORDER BY SUM(ue.cost_inr) DESC
                    """
                ),
                {"ix": interaction_id},
            )
        )

        meta = _one(
            conn.execute(
                text(
                    """
                    SELECT duration_sec, started_at, channel, status
                      FROM interactions WHERE id = :ix
                    """
                ),
                {"ix": interaction_id},
            )
        )

        tokens = _one(
            conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(tokens), 0) AS tokens
                      FROM interaction_transcript
                     WHERE interaction_id = :ix AND tokens IS NOT NULL
                    """
                ),
                {"ix": interaction_id},
            )
        )

    lines = [
        {
            "serviceId": r["service_id"],
            "serviceName": r["service_name"],
            "unit": r["unit"],
            "category": r["category"],
            "color": r["color"],
            "model": r["model"],
            "units": _fnum(r["units"]),
            "costInr": _fnum(r["cost"]),
            "events": int(r["events"] or 0),
        }
        for r in rows
    ]
    total = sum(line["costInr"] for line in lines)
    return {
        "interactionId": interaction_id,
        "attributed": bool(lines),
        "totalInr": total,
        "lines": lines,
        "durationSec": int((meta or {}).get("duration_sec") or 0),
        "channel": (meta or {}).get("channel"),
        "status": (meta or {}).get("status"),
        "totalTokens": int((tokens or {}).get("tokens") or 0),
    }


def _model_spend(
    conn: Any, *, start: date, end: date, env: str, tenant_id: str
) -> list[dict[str, Any]]:
    """Spend grouped by model.

    The per-model dimension only exists on ``usage_events`` — ``billing_services``
    has a single blended ``llm_chat`` row, so a gpt-5 turn and a gpt-4o-mini turn
    are indistinguishable in the rollup even though they price ~8x apart.
    """
    params: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "env": env,
        "services": list(_METERED_SERVICE_IDS),
    }
    tenant_sql = ""
    if tenant_id and tenant_id != "all":
        tenant_sql = "AND ue.tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    rows = _rows(
        conn.execute(
            text(
                f"""
                SELECT ue.service_id,
                       bs.name AS service_name,
                       bs.unit AS unit,
                       bs.color,
                       COALESCE(ue.model, '(unspecified)') AS model,
                       COALESCE(ue.source_ref, '(unspecified)') AS source_ref,
                       SUM(ue.units)    AS units,
                       SUM(ue.cost_inr) AS cost,
                       COUNT(DISTINCT ue.interaction_id) AS calls
                  FROM usage_events ue
                  JOIN billing_services bs ON bs.id = ue.service_id
                 WHERE ue.occurred_at >= CAST(:start AS date)
                   AND ue.occurred_at < CAST(:end AS date) + INTERVAL '1 day'
                   AND ue.environment = :env
                   AND ue.service_id = ANY(:services)
                   {tenant_sql}
                 GROUP BY ue.service_id, bs.name, bs.unit, bs.color, ue.model, ue.source_ref
                 ORDER BY SUM(ue.cost_inr) DESC
                """
            ),
            params,
        )
    )
    return [
        {
            "serviceId": r["service_id"],
            "serviceName": r["service_name"],
            "unit": r["unit"],
            "color": r["color"],
            "model": r["model"],
            "sourceRef": r.get("source_ref"),
            "units": _fnum(r["units"]),
            "costInr": _fnum(r["cost"]),
            "calls": int(r["calls"] or 0),
        }
        for r in rows
    ]


def _attributed_cost_per_call(
    conn: Any, *, start: date, end: date, env: str, tenant_id: str
) -> tuple[float, int]:
    """Mean cost over calls that actually carry metered usage.

    Distinct from the ``costPerCall`` KPI beside it, which is total spend over
    resolved calls — that one divides *all* spend (including embeddings and
    batch work no call incurred) by a call count, so it is an allocation, not a
    measurement. This one only counts calls with attributed events.
    """
    params: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "env": env,
        "services": list(_METERED_SERVICE_IDS),
    }
    tenant_sql = ""
    if tenant_id and tenant_id != "all":
        tenant_sql = "AND ue.tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    row = _one(
        conn.execute(
            text(
                f"""
                SELECT COALESCE(AVG(call_cost), 0) AS avg_cost,
                       COUNT(*)                    AS calls
                  FROM (
                        SELECT ue.interaction_id, SUM(ue.cost_inr) AS call_cost
                          FROM usage_events ue
                         WHERE ue.interaction_id IS NOT NULL
                           AND ue.occurred_at >= CAST(:start AS date)
                           AND ue.occurred_at < CAST(:end AS date) + INTERVAL '1 day'
                           AND ue.environment = :env
                           AND ue.service_id = ANY(:services)
                           {tenant_sql}
                         GROUP BY ue.interaction_id
                       ) per_call
                """
            ),
            params,
        )
    )
    return _fnum((row or {}).get("avg_cost")), int((row or {}).get("calls") or 0)


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
# Redundant aliases are explicit re-exports so F401 does not treat them as dead.
# get_calibration_session stays in followups_db — only patch uses it.
# ---------------------------------------------------------------------------
# Treatment holds (P3)
#
# The veto that had no home. Hardship, an open dispute, a regulatory complaint,
# bereavement and a matter with legal all mean "stop dunning this borrower",
# and all five used to live as prose in the policy corpus or as a routing rule
# that fired only when a human was already on the call. As rows they bind the
# bot at 02:00 exactly as they bind a supervisor.
# ---------------------------------------------------------------------------

HOLD_KINDS = ("hardship", "dispute", "complaint", "bereavement", "legal")
HOLD_SOURCES = ("manual", "bot", "system", "regulator")


def list_treatment_holds(
    *,
    customer_id: str | None = None,
    active_only: bool = True,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Holds visible to the caller. Tenant- and object-scoped like any queue."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    where = ["c.tenant_id = :tenant_id"]
    params: dict[str, Any] = {
        "tenant_id": _tenant(),
        "limit": page,
        "offset": skip,
        **_vis_params(),
    }
    if customer_id:
        where.append("h.customer_id = :customer_id")
        params["customer_id"] = customer_id
    if active_only:
        where.append(
            "h.released_at IS NULL AND h.starts_at <= now()"
            " AND (h.expires_at IS NULL OR h.expires_at > now())"
        )
    clause = " AND ".join(where)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    f"""
                    SELECT h.id, h.customer_id, c.name AS customer_name, h.account_id,
                           h.kind, h.reason, h.source, h.interaction_id,
                           h.sla_due_at, h.starts_at, h.expires_at,
                           h.released_at, h.released_reason, h.created_at,
                           p.name AS placed_by, s.name AS specialist
                    FROM treatment_holds h
                    JOIN customers c ON c.id = h.customer_id
                     /*VISIBILITY*/
                    LEFT JOIN users p ON p.id = h.placed_by_user_id
                    LEFT JOIN users s ON s.id = h.specialist_user_id
                    WHERE {clause}
                    ORDER BY h.starts_at DESC, h.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        )
    return [
        {
            "id": r["id"],
            "customerId": r["customer_id"],
            "customerName": r["customer_name"],
            "accountId": r["account_id"],
            "kind": r["kind"],
            "reason": r["reason"],
            "source": r["source"],
            "interactionId": r["interaction_id"],
            "slaDueAt": r["sla_due_at"],
            "startsAt": r["starts_at"],
            "expiresAt": r["expires_at"],
            "releasedAt": r["released_at"],
            "releasedReason": r["released_reason"],
            "placedBy": r["placed_by"],
            "specialist": r["specialist"],
            "active": r["released_at"] is None,
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def create_treatment_hold(payload: dict[str, Any]) -> dict[str, Any]:
    """Place a hold. Re-placing an active one is a no-op, not an error.

    Idempotent by design rather than by an idempotency key: a bot that hears
    "I lost my job" twice in one call, and an agent who clicks twice, must both
    end with one hold. The partial unique index is what enforces it; this
    surfaces the existing row instead of a 409 so the caller's flow continues.
    """
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in HOLD_KINDS:
        raise ValueError(f"invalid_kind: {kind}")
    source = str(payload.get("source") or "manual").strip().lower()
    if source not in HOLD_SOURCES:
        raise ValueError(f"invalid_source: {source}")
    customer_id = payload.get("customerId")

    with engine.begin() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        account_id = payload.get("accountId")
        if account_id:
            _assert_tenant_owns(conn, "accounts", account_id)
        existing = _one(
            conn.execute(
                text(
                    """
                    SELECT id FROM treatment_holds
                    WHERE customer_id = :cid
                      AND COALESCE(account_id, '') = COALESCE(:aid, '')
                      AND kind = :kind
                      AND released_at IS NULL
                    """
                ),
                {"cid": customer_id, "aid": account_id, "kind": kind},
            )
        )
        if existing:
            return _treatment_hold(conn, existing["id"])

        hold_id = _id("THD")
        conn.execute(
            text(
                """
                INSERT INTO treatment_holds (
                  id, tenant_id, customer_id, account_id, kind, reason, source,
                  interaction_id, placed_by_user_id, specialist_user_id,
                  sla_due_at, expires_at
                ) VALUES (
                  :id, :tenant_id, :customer_id, :account_id, :kind, :reason, :source,
                  :interaction_id, :placed_by, :specialist, :sla_due_at, :expires_at
                )
                """
            ),
            {
                "id": hold_id,
                "tenant_id": _tenant(),
                "customer_id": customer_id,
                "account_id": account_id,
                "kind": kind,
                "reason": payload.get("reason"),
                "source": source,
                "interaction_id": payload.get("interactionId"),
                "placed_by": _actor_user_id(),
                "specialist": payload.get("specialistUserId"),
                "sla_due_at": payload.get("slaDueAt"),
                "expires_at": payload.get("expiresAt"),
            },
        )
        record_activity(
            conn,
            "customer",
            str(customer_id),
            "hold_placed",
            f"{kind.capitalize()} hold placed",
            payload.get("reason"),
            str(customer_id),
        )
        return _treatment_hold(conn, hold_id)


def release_treatment_hold(
    hold_id: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Lift a hold. Releasing an already-released one is idempotent."""
    body = payload or {}
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "treatment_holds", hold_id)
        conn.execute(
            text(
                """
                UPDATE treatment_holds
                SET released_at = now(),
                    released_by_user_id = :actor,
                    released_reason = :reason
                WHERE id = :id AND released_at IS NULL
                """
            ),
            {"id": hold_id, "actor": _actor_user_id(), "reason": body.get("reason")},
        )
        row = _treatment_hold(conn, hold_id)
        record_activity(
            conn,
            "customer",
            str(row["customerId"]),
            "hold_released",
            f"{str(row['kind']).capitalize()} hold released",
            body.get("reason"),
            str(row["customerId"]),
        )
        return row


def _treatment_hold(conn: Any, hold_id: str) -> dict[str, Any]:
    row = _one(
        conn.execute(
            text(
                """
                SELECT h.id, h.customer_id, h.account_id, h.kind, h.reason, h.source,
                       h.interaction_id, h.sla_due_at, h.starts_at, h.expires_at,
                       h.released_at, h.released_reason, h.created_at
                FROM treatment_holds h WHERE h.id = :id
                """
            ),
            {"id": hold_id},
        )
    )
    if row is None:
        raise KeyError("treatment_holds_not_found")
    return {
        "id": row["id"],
        "customerId": row["customer_id"],
        "accountId": row["account_id"],
        "kind": row["kind"],
        "reason": row["reason"],
        "source": row["source"],
        "interactionId": row["interaction_id"],
        "slaDueAt": row["sla_due_at"],
        "startsAt": row["starts_at"],
        "expiresAt": row["expires_at"],
        "releasedAt": row["released_at"],
        "releasedReason": row["released_reason"],
        "active": row["released_at"] is None,
        "createdAt": row["created_at"],
    }


def next_treatment(
    *,
    customer_id: str,
    account_id: str | None = None,
    trigger: str = "manual",
) -> dict[str, Any]:
    """What the treatment engine would do for this borrower, right now.

    Read-only from the caller's point of view. The engine does write a decision
    row — that is deliberate, since the shadow corpus should be built from the
    questions people actually ask — but it enacts nothing outside live mode.
    """
    from agent_core.treatment import Trigger, recommend_treatment

    with engine.connect() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        if account_id:
            _assert_tenant_owns(conn, "accounts", account_id)
    result = recommend_treatment(
        customer_id=customer_id,
        account_id=account_id,
        trigger=Trigger(kind=trigger),
    )
    payload = result.to_payload()

    # The Action Contract, for whoever is going to execute this. Until now it
    # existed and nothing served it, which made it an interface with no other
    # side -- a voice runner, a WhatsApp job or a field dispatcher had no way to
    # receive the authorisation the design note says it must be handed.
    #
    # Built with a connection so the authority matrix can price a fee waiver
    # once, here, rather than leaving a bot to query it mid-call under latency.
    # Absent for a suppressed or `wait` decision rather than present-and-empty:
    # a contract is an authorisation to act, and an empty one invites a channel
    # to decide for itself what that means.
    try:
        with engine.connect() as conn:
            contract = result.action_contract(conn=conn)
    except Exception:
        logger.exception("action contract build failed for %s", result.decision_id)
        contract = result.action_contract()
    if contract is not None:
        payload["contract"] = contract
    return payload


def list_treatment_cases(
    *,
    customer_id: str | None = None,
    open_only: bool = True,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """The ladder, one row per case, with every rung it has walked.

    A case is ``(customer, trigger kind, trigger ref)`` — one bounce, one broken
    promise. The single-decision view answers "what did the engine say?"; this
    answers the question a floor lead actually has, which is "what has already
    been tried on this account and what is left".
    """
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    where = ["c.tenant_id = :tenant_id", "td.trigger_ref IS NOT NULL"]
    params: dict[str, Any] = {
        "tenant_id": _tenant(),
        "limit": page,
        "offset": skip,
        **_vis_params(),
    }
    if customer_id:
        where.append("td.customer_id = :customer_id")
        params["customer_id"] = customer_id
    if open_only:
        where.append(
            "NOT EXISTS (SELECT 1 FROM treatment_decisions r"
            " WHERE r.customer_id = td.customer_id AND r.trigger_kind = td.trigger_kind"
            "   AND r.trigger_ref = td.trigger_ref AND r.outcome IN ('paid','ptp'))"
        )
    clause = " AND ".join(where)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    f"""
                    SELECT td.customer_id, c.name AS customer_name, td.account_id,
                           td.trigger_kind, td.trigger_ref,
                           count(*)::int AS decisions,
                           count(*) FILTER (WHERE td.enacted)::int AS attempts,
                           max(td.created_at) AS last_decided_at,
                           max(td.enacted_at) AS last_attempt_at,
                           (array_agg(td.chosen_action ORDER BY td.created_at DESC))[1]
                             AS last_action,
                           (array_agg(td.outcome ORDER BY td.created_at DESC))[1]
                             AS last_outcome,
                           (array_agg(td.suppression_reason ORDER BY td.created_at DESC))[1]
                             AS last_suppression,
                           (array_agg(td.rationale ORDER BY td.created_at DESC))[1]
                             AS last_rationale,
                           array_remove(
                             array_agg(td.chosen_action ORDER BY td.created_at)
                               FILTER (WHERE td.enacted), NULL
                           ) AS ladder
                    FROM treatment_decisions td
                    JOIN customers c ON c.id = td.customer_id
                     /*VISIBILITY*/
                    WHERE {clause}
                    GROUP BY td.customer_id, c.name, td.account_id,
                             td.trigger_kind, td.trigger_ref
                    ORDER BY max(td.created_at) DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        )
    return [
        {
            "id": f"{r['trigger_kind']}:{r['trigger_ref']}",
            "customerId": r["customer_id"],
            "customerName": r["customer_name"],
            "accountId": r["account_id"],
            "trigger": r["trigger_kind"],
            "triggerRef": r["trigger_ref"],
            "decisions": r["decisions"],
            "attempts": r["attempts"],
            "ladder": list(r["ladder"] or []),
            "lastAction": r["last_action"],
            "lastOutcome": r["last_outcome"],
            "lastSuppression": r["last_suppression"],
            "rationale": r["last_rationale"],
            "lastDecidedAt": r["last_decided_at"],
            "lastAttemptAt": r["last_attempt_at"],
        }
        for r in rows
    ]


def treatment_insights(days: int = 14) -> dict[str, Any]:
    """The shadow-rollout scoreboard behind ``GET /treatment/insights``."""
    from agent_core.treatment import decisions as treatment_decisions

    with engine.connect() as conn:
        return treatment_decisions.insights(conn, days=days)


def treatment_metrics(days: int = 28, *, include_simulated: bool = False) -> dict[str, Any]:
    """The design note's S17 scoreboard: causal, efficiency, model health,
    compliance, borrower experience, capacity.

    Distinct from ``treatment_insights``, which answers "is this safe to switch
    on?". This answers "is it working, and what is it costing?" -- and its
    headline is incremental recovery per rupee against the control arm, never a
    collections rate. A response model looks excellent on collections rate
    precisely because it targets borrowers who would have paid anyway.
    """
    from agent_core.treatment import metrics as treatment_metrics_mod

    with engine.connect() as conn:
        return treatment_metrics_mod.report(
            conn, days=days, include_simulated=include_simulated
        )


def treatment_model_health(days: int = 14, *, include_simulated: bool = False) -> dict[str, Any]:
    """Drift and calibration only -- the S15 half, without the rest of S17."""
    from agent_core.treatment import monitor

    with engine.connect() as conn:
        return monitor.report(conn, days=days, include_simulated=include_simulated)


def treatment_models(target: str | None = None, limit: int = 50) -> dict[str, Any]:
    """The champion/challenger ledger, plus whether it matches what is serving.

    ``verify`` is the part worth reading first. A registry that only records
    promotions cannot tell you that the file underneath one was replaced
    afterwards, and every log line downstream would keep naming the promoted
    version while different coefficients decided whether borrowers got called.
    """
    from agent_core.treatment import registry

    tenant = current_tenant()
    with engine.connect() as conn:
        return {
            "history": registry.history(conn, tenant_id=tenant, target=target, limit=limit),
            "serving": registry.verify(conn, tenant_id=tenant),
        }


def next_authority(
    *,
    customer_id: str,
    account_id: str | None = None,
    fee_type: str = "late_fee",
    asked_amount: float | None = None,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    """What the authority matrix would allow on this call, right now.

    Writes a decision row (the shadow corpus) and enacts nothing outside live
    mode. Safe to call from Handoff / Floor / 360.
    """
    from agent_core.authority import recommend_authority

    with engine.connect() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        if account_id:
            _assert_tenant_owns(conn, "accounts", account_id)
    result = recommend_authority(
        customer_id=customer_id,
        account_id=account_id,
        interaction_id=interaction_id,
        fee_type=fee_type,
        asked_amount=asked_amount,
    )
    return result.to_payload()


def apply_authority(payload: dict[str, Any]) -> dict[str, Any]:
    """Post the goodwill the matrix already approved. Live mode only."""
    from agent_core.authority import enact as authority_enact
    from agent_core.authority.enact import AuthorityError

    decision_id = payload["decisionId"]
    with engine.begin() as conn:
        _assert_tenant_owns(conn, "authority_decisions", decision_id)
        try:
            return authority_enact.apply_goodwill(
                decision_id=decision_id,
                amount=payload.get("amount"),
                dispute_id=payload.get("disputeId"),
                conn=conn,
            )
        except AuthorityError as exc:
            raise ValueError(str(exc)) from exc


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
