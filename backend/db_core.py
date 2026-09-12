"""Engine, tenant binding, and the row helpers every accessor shares.

41 production modules bind to ``db.py``'s private helpers. Splitting ``db.py``
is impossible until those names live somewhere that is not the 18,000-line
file. This module is that place.

``db.py`` re-exports every public name so existing ``import db`` call sites
keep resolving. That is the whole shim: verified, no importer uses
``from db import X``.

The engine and its ``begin`` listener are one object. They must be created
together, in this module, exactly once. A factory that built a new Engine
per call — or a second ``create_engine`` in a peel — would silently undo
the libpq-startup-parameter argument for row-level security: a pool
ROLLBACK cannot unset a startup GUC, and that is the entire safety case
for turning RLS on.

Carved modules (the peels that follow this commit) must reach the engine
through :func:`_db`, never ``from db_core import engine``.
``tests/conftest.py`` wraps ``db.engine`` with a savepoint proxy so
``outer.rollback()`` undoes every test write. A name bound from this
module bypasses the proxy; the suite stays green and committed rows stay
behind. Commit ``fd855ca`` is this repository paying for that once.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

import tenant_context
import visibility
from env_utils import env_int as _env_int

__all__ = [
    "ACTOR_USER_ID",
    "DATABASE_URL",
    "DB_MAX_OVERFLOW",
    "DB_POOL_RECYCLE",
    "DB_POOL_SIZE",
    "DB_STATEMENT_TIMEOUT_MS",
    "DEFAULT_DATABASE_URL",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "TENANT_ID",
    "_IST",
    "_account_tail",
    "_activity",
    "_actor_user_id",
    "_as_dict",
    "_as_utc",
    "_assert_tenant_owns",
    "_bind_tenant_for_transaction",
    "_db",
    "_dump",
    "_id",
    "_jsonb",
    "_one",
    "_rows",
    "_speaker_screen",
    "_sql",
    "_tenant",
    "_vis_params",
    "clamp_list_limit",
    "clamp_offset",
    "UNKNOWN_CALLER_ID",
    "current_tenant",
    "is_unknown_caller",
    "unknown_caller_id",
    "engine",
]


BASE = Path(__file__).parent
DEFAULT_DATABASE_URL = "postgresql+psycopg://collections:collections@localhost:5432/collections"


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


#: The unbound-caller sentinel. One customer row per tenant, so an unbound
#: call at one bank never references a customer row that belongs to another.
#:
#: The bare id is the process tenant's row: it existed before tenants were
#: distinguished here and is referenced by every interaction that ever opened
#: unbound, so it keeps its name. Every other tenant's sentinel carries the
#: tenant as a suffix. Ask :func:`is_unknown_caller`, never compare to the
#: constant -- the constant is one tenant's spelling.
UNKNOWN_CALLER_ID = "UNKNOWN-CALLER"


def unknown_caller_id(tenant: str | None = None) -> str:
    t = tenant or current_tenant()
    return UNKNOWN_CALLER_ID if t == TENANT_ID else f"{UNKNOWN_CALLER_ID}:{t}"


def is_unknown_caller(customer_id: str | None) -> bool:
    cid = (customer_id or "").strip()
    return cid == UNKNOWN_CALLER_ID or cid.startswith(UNKNOWN_CALLER_ID + ":")


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
# The three that were missing. A pool with no `pool_timeout` waits forever for
# a connection when the pool is exhausted; a session with no
# `idle_in_transaction_session_timeout` holds its locks for as long as a
# crashed request leaves it; a statement with no `lock_timeout` queues behind
# a migration until the statement timeout, and a connect with no
# `connect_timeout` hangs a worker on a database that is down.
DB_CONNECT_TIMEOUT_S = max(1, _env_int("DB_CONNECT_TIMEOUT_S", 10))
DB_LOCK_TIMEOUT_MS = max(1000, _env_int("DB_LOCK_TIMEOUT_MS", 15_000))
DB_IDLE_IN_TX_TIMEOUT_MS = max(1000, _env_int("DB_IDLE_IN_TX_TIMEOUT_MS", 60_000))
DB_POOL_TIMEOUT_S = max(1, _env_int("DB_POOL_TIMEOUT_S", 30))

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
    pool_timeout=DB_POOL_TIMEOUT_S,
    connect_args={
        "connect_timeout": DB_CONNECT_TIMEOUT_S,
        # No server-side prepared statements.
        #
        # psycopg3 promotes a statement to a server-side PREPARE after five
        # executions on a connection. The plan caches the result *types*, so any
        # DDL that changes a table's columns makes every pooled connection that
        # has seen a `SELECT *` on it start raising
        #
        #   FeatureNotSupported: cached plan must not change result type
        #
        # until the connection is recycled. `collections_wk_batch` crash-looped
        # on exactly this — `SELECT * FROM work_runtime_jobs` in its claim query
        # — and it is latent everywhere else: 87 `SELECT *` across 38 modules,
        # any one of which becomes a crashing worker after a migration touching
        # its table. Naming 87 column lists fixes them one at a time and leaves
        # the 88th; this closes the class.
        #
        # The cost is real and small: we lose plan reuse on hot statements. This
        # workload is dominated by pgvector ANN scans and single-row lookups, not
        # by parse time, and a worker that cannot start costs more than a parse.
        "prepare_threshold": None,
        "options": (
            f"-c statement_timeout={DB_STATEMENT_TIMEOUT_MS} "
            f"-c lock_timeout={DB_LOCK_TIMEOUT_MS} "
            f"-c idle_in_transaction_session_timeout={DB_IDLE_IN_TX_TIMEOUT_MS} "
            f"-c {tenant_context.GUC}={tenant_context.validate(TENANT_ID)}"
        ),
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


def _account_tail(account_id: str | None) -> str | None:
    """Last 4 *digits* of an account id -- never letters.

    Ids look like ``AC-77410`` (-> ``7410``); a vanity id like ``AC-SUSANTH``
    has no trailing digits, and the old ``[-4:]`` here showed the desk "SANTH"
    while the mouth (``agent_core.context.account_tail``, which delegates to
    this) said nothing. One rule now, and the desk and the phone agree.
    """
    digits = "".join(ch for ch in (account_id or "") if ch.isdigit())
    return digits[-4:] if len(digits) >= 4 else None


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


def _actor() -> tuple[str, str | None, str | None]:
    """``(actor_kind, actor_user_id, actor_bot_id)`` for the current context.

    A person acts through a request and has a user id. A worker or the voice
    process binds itself as ``system``/``bot`` at startup and has none -- an
    audit row for a machine action that names the process default user is a
    forgery, not a fallback.
    """
    try:
        import actor_context

        kind = actor_context.get_actor_kind()
        if kind == "human":
            return "human", _actor_user_id(), None
        return kind, None, actor_context.get_actor_bot_id()
    except Exception:
        return "human", ACTOR_USER_ID, None


def _activity(conn: Any, entity_type: str, entity_id: str, kind: str, label: str, note: str | None = None, customer_id: str | None = None) -> None:
    actor_kind, actor_user_id, actor_bot_id = _actor()
    conn.execute(
        text(
            """
            INSERT INTO activity_events
              (id, tenant_id, entity_type, entity_id, actor_kind, actor_user_id, actor_bot_id,
               kind, label, note, payload)
            VALUES
              (:id, :tenant_id, :entity_type, :entity_id, :actor_kind, :actor_user_id, :actor_bot_id,
               :kind, :label, :note, CAST(:payload AS jsonb))
            """
        ),
        {
            "id": _id("ACT"),
            "tenant_id": _tenant(),
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_kind": actor_kind,
            "actor_user_id": actor_user_id,
            "actor_bot_id": actor_bot_id,
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


# Operating timezone for operator-facing time labels. Fixed offset — India
# has no DST, so this needs no tz database at runtime.
_IST = timezone(timedelta(hours=5, minutes=30))


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


def _vector_literal(vec: list[float]) -> str:
    """A float list as a pgvector literal. The 8dp is the storage precision.

    Four modules formatted this themselves — ``db_kb``, ``kb_ingest``,
    ``kb_retrieve`` and the source-DB ingest script — byte for byte the same
    line. They agreed only by luck: a fifth writer choosing ``repr`` or a
    different precision would produce vectors that no longer match the ones
    already in the column, and nothing would fail loudly.
    """
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"


def _speaker_screen(speaker: str | None) -> str:
    """Map a transcript speaker label onto the screen vocabulary.

    Moved down from the violations section so Redaction (peel 8) and the
    remaining kernel share one implementation. ``human`` is the voice-bot
    dialect for the collecting agent.
    """
    if speaker in {"bot", "agent", "customer", "system"}:
        return speaker
    if speaker == "human":
        return "agent"
    return "system"


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


def _jsonb(value: Any) -> str:
    import json

    return json.dumps(value)


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. ``tests/conftest.py`` wraps ``db.engine`` with a savepoint
    proxy; a name bound from this module bypasses it, ``outer.rollback()``
    rolls back nothing those modules wrote, and the suite goes green while
    leaving committed rows behind.
    """
    import db as d

    return d
