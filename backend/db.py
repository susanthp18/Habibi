"""Postgres accessors plus API response serializers."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

import contact_window
from agent_core import clock
from agent_core.clock import utc_now
import visibility
from env_utils import env_float
from env_utils import env_int as _env_int

from db_core import (
    DEFAULT_DETAIL_LIMIT as DEFAULT_DETAIL_LIMIT,
    _assert_tenant_owns_customer as _assert_tenant_owns_customer,
    _duration as _duration,
    _short_product as _short_product,
    _user_name as _user_name,
    _first_account_id as _first_account_id,
    _ensure_customer as _ensure_customer,
    _ensure_interaction as _ensure_interaction,
    record_activity as record_activity,
    _idempotent_response as _idempotent_response,
    _store_idempotent_response as _store_idempotent_response,
    _consent_channel as _consent_channel,
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
    assert_transition as assert_transition,
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

if TYPE_CHECKING:
    from schemas import CustomerResponse

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


def probe() -> None:
    """One round trip at boot: the schema is reachable, or the process does not start."""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1 FROM tenants LIMIT 1"))


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


def list_role_grant_rows() -> list[dict[str, Any]]:
    """Every role with each explicit grant, one row per (role, permission).

    ``permission_id`` is NULL for a role with no explicit grants;
    ``configured_at`` says whether the empty set is an opinion or a default.
    """
    with engine.connect() as conn:
        return _rows(
            conn.execute(
                text(
                    """
                    SELECT r.id AS role_id, r.name AS role_name, r.configured_at,
                           rp.permission_id
                      FROM roles r
                 LEFT JOIN role_permissions rp ON rp.role_id = r.id
                     WHERE r.tenant_id = :t
                     ORDER BY r.name, rp.permission_id
                    """
                ),
                {"t": _tenant()},
            )
        )


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
    from schemas import CustomerResponse

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
                        SELECT id, posted_at AS date, description, type, amount, invoice_id AS "invoiceId"
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
    only persistent decision producers. The preview is memoised per customer
    for ``TREATMENT_PREVIEW_TTL_S`` (60 s): every open of a card ran the whole
    engine -- features, candidates, veto, score -- and a desk that opens and
    re-opens the same borrower paid it each time for the same answer.
    """
    now = time.monotonic()
    cached = _PREVIEW_CACHE.get(customer_id)
    if cached and now - cached[0] < _PREVIEW_TTL_S:
        return cached[1]
    try:
        from agent_core.treatment import Trigger, recommend_treatment

        result = recommend_treatment(
            customer_id=customer_id,
            trigger=Trigger(kind="manual"),
            conn=conn,
            persist="preview",
        )
        payload = result.to_payload()
    except Exception:
        logger.exception("treatment snapshot failed for customer=%s", customer_id)
        return None
    if len(_PREVIEW_CACHE) > 512:
        _PREVIEW_CACHE.clear()
    _PREVIEW_CACHE[customer_id] = (now, payload)
    return payload


#: customer_id -> (monotonic, payload). Process-local, like authz's grant cache.
_PREVIEW_CACHE: dict[str, tuple[float, dict[str, Any] | None]] = {}
_PREVIEW_TTL_S = env_float("TREATMENT_PREVIEW_TTL_S", 60.0)


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

        now = utc_now()
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

    from schemas import CallResponse
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

    from schemas import ProductResponse
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
        if payload.get("promisedDate"):
            # Moving the date moves what the pay link has to say. The intent is
            # a separate row carrying its own `expires_at`, derived from the
            # promise date at the moment it was minted, and nothing here used to
            # touch it — so a rescheduled promise kept the old expiry and the
            # borrower was sent "pay by 28 Aug, link valid until 23 Aug".
            #
            # `fulfill` reuses the open intent (the partial unique index allows
            # only one) and now refreshes its amount and expiry from the live
            # promise, so this is a re-derivation rather than a second link.
            import promise_fulfillment

            try:
                with conn.begin_nested():
                    promise_fulfillment.fulfill(conn, promise_id)
            except Exception:
                # A reschedule must still succeed if the confirm cannot be
                # re-sent — the operator's edit is the record, the message is a
                # consequence of it.
                logger.exception("promise reschedule re-fulfil failed promise=%s", promise_id)
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


# A dispute's status is a state machine. `resolved` is terminal -- a resolved
# fee waiver has a ledger row behind it -- and `rejected` reopens only into
# review (an appeal), never straight back to new.
_DISPUTE_TRANSITIONS: dict[str, frozenset[str]] = {
    "new": frozenset({"under_review", "awaiting_customer", "resolved", "rejected"}),
    "under_review": frozenset({"awaiting_customer", "resolved", "rejected"}),
    "awaiting_customer": frozenset({"under_review", "resolved", "rejected"}),
    "rejected": frozenset({"under_review"}),
}


def patch_dispute(dispute_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Payload arrives with exclude_unset: a present key is an intentional write,
    so an explicit None clears the column (used to unassign)."""
    with engine.begin() as conn:
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


def create_interaction(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    from schemas import CallResponse

    endpoint = "POST /interactions"
    with engine.begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        interaction_id = _id("CL")
        handler_kind = payload.get("handlerKind") or "human"
        # Attribution is the acting user, never a value the client chose.
        handler_user_id = _actor_user_id() if handler_kind == "human" else None
        handler_bot_id = payload.get("handlerBotId") or (DEFAULT_BOT_ID if handler_kind == "bot" else None)
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
                startedAt=utc_now().isoformat(),
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

# Coaching / calibration, and the writes that live with their readers
# (redaction, routing, workspace). Keep call sites as db.*.
# get_calibration_session stays in db_coaching — only patch uses it.
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
    _looks_collections_topic as _looks_collections_topic,
    _looks_like_pasted_draft as _looks_like_pasted_draft,
    _open_whatsapp_conversation as _open_whatsapp_conversation,
    _serialize_conversation as _serialize_conversation,
    _tail10_predicate as _tail10_predicate,
    _thread_context as _thread_context,
    _touch_interaction_sentiment as _touch_interaction_sentiment,
    escalate_conversation_to_human as escalate_conversation_to_human,
    find_customer_by_phone as find_customer_by_phone,
    get_conversation as get_conversation,
    get_latest_context_summary as get_latest_context_summary,
    handoff_to_agent as handoff_to_agent,
    list_bot_ids as list_bot_ids,
    list_canned_responses as list_canned_responses,
    list_conversations as list_conversations,
    process_whatsapp_webhook as process_whatsapp_webhook,
    refresh_conversation_suggestions as refresh_conversation_suggestions,
    return_conversation_to_bot as return_conversation_to_bot,
    save_context_summary as save_context_summary,
    send_conversation_message as send_conversation_message,
    takeover_conversation as takeover_conversation,
    touch_interaction_sentiment as touch_interaction_sentiment,
)

from db_evals import (  # noqa: E402
    TENANT_WIDE_REPORTS as TENANT_WIDE_REPORTS,
    _latest_twin_gate_report as _latest_twin_gate_report,
    get_eval_report as get_eval_report,
    get_latest_eval_report as get_latest_eval_report,
    list_eval_reports as list_eval_reports,
    list_eval_suites as list_eval_suites,
    save_eval_report as save_eval_report,
)

from db_kb_snapshots import (  # noqa: E402
    create_kb_snapshot as create_kb_snapshot,
    list_kb_snapshots as list_kb_snapshots,
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
    workspace_summary as workspace_summary,
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
    create_routing_rule as create_routing_rule,
    delete_routing_rule as delete_routing_rule,
    escalate_voice_interaction as escalate_voice_interaction,
    get_routing_rule as get_routing_rule,
    list_routing_audit as list_routing_audit,
    list_routing_rule_executions as list_routing_rule_executions,
    list_routing_rules as list_routing_rules,
    patch_routing_rule as patch_routing_rule,
    reorder_routing_rules as reorder_routing_rules,
    simulate_routing_rules as simulate_routing_rules,
)

from db_redaction import (  # noqa: E402
    actor_is_admin as actor_is_admin,
    create_export_job as create_export_job,
    get_redaction_record as get_redaction_record,
    get_redaction_rule as get_redaction_rule,
    list_export_jobs as list_export_jobs,
    list_redaction_records as list_redaction_records,
    list_redaction_rules as list_redaction_rules,
    patch_audio_segment_mute as patch_audio_segment_mute,
    patch_export_job as patch_export_job,
    patch_pii_finding as patch_pii_finding,
    patch_redaction_record as patch_redaction_record,
    patch_redaction_rule as patch_redaction_rule,
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
    list_tts_voice_locale_counts as list_tts_voice_locale_counts,
    list_tts_voice_provider_counts as list_tts_voice_provider_counts,
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

from db_coaching import (  # noqa: E402
    create_coaching_action as create_coaching_action,
    list_calibration_sessions as list_calibration_sessions,
    list_coaching_actions as list_coaching_actions,
    patch_calibration_session as patch_calibration_session,
    patch_coaching_action as patch_coaching_action,
)


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

from db_handoff import (  # noqa: E402
    HANDOFF_DISPOSITIONS as HANDOFF_DISPOSITIONS,
    _HANDOFF_DISCLOSURE_RULES as _HANDOFF_DISCLOSURE_RULES,
    _actor_team_id as _actor_team_id,
    _assert_handoff_assignee as _assert_handoff_assignee,
    _epoch_ms as _epoch_ms,
    _handoff_authority_policy as _handoff_authority_policy,
    _handoff_compliance_items as _handoff_compliance_items,
    _handoff_customer_context as _handoff_customer_context,
    _handoff_live_qa as _handoff_live_qa,
    _handoff_offer_policy as _handoff_offer_policy,
    _handoff_queue_sql_filter as _handoff_queue_sql_filter,
    _handoff_queue_visible as _handoff_queue_visible,
    _handoff_sentiment_series as _handoff_sentiment_series,
    _handoff_status as _handoff_status,
    _iso_ts as _iso_ts,
    accept_handoff_suggestion as accept_handoff_suggestion,
    claim_handoff as claim_handoff,
    get_active_handoff_session as get_active_handoff_session,
    get_handoff_session as get_handoff_session,
    list_handoff_queue as list_handoff_queue,
    record_handoff_disclosure as record_handoff_disclosure,
)

from db_leads import (  # noqa: E402
    OPEN_LEAD_STAGES as OPEN_LEAD_STAGES,
    _CLOSED_LEAD_STAGES as _CLOSED_LEAD_STAGES,
    _DEFAULT_LEAD_TEAM as _DEFAULT_LEAD_TEAM,
    _LEAD_EVENT_KINDS as _LEAD_EVENT_KINDS,
    _LEAD_FILTER_SQL as _LEAD_FILTER_SQL,
    _LEAD_STAGE_TRANSITIONS as _LEAD_STAGE_TRANSITIONS,
    _TEAM_BY_CATEGORY as _TEAM_BY_CATEGORY,
    _lead_by_id as _lead_by_id,
    _lead_event as _lead_event,
    _lead_events as _lead_events,
    _lead_events_bulk as _lead_events_bulk,
    _lead_filter_params as _lead_filter_params,
    _lead_followup_channel as _lead_followup_channel,
    _lead_followups as _lead_followups,
    _lead_followups_bulk as _lead_followups_bulk,
    _next_followup_at as _next_followup_at,
    _parse_followup_due as _parse_followup_due,
    _route_team_id as _route_team_id,
    add_lead_followup as add_lead_followup,
    create_lead as create_lead,
    find_open_lead as find_open_lead,
    lead_metrics as lead_metrics,
    list_leads as list_leads,
    offer_decision_exists as offer_decision_exists,
    patch_followup as patch_followup,
    patch_lead as patch_lead,
    revalidate_lead_eligibility as revalidate_lead_eligibility,
    revalidate_open_leads as revalidate_open_leads,
    sweep_due_followups as sweep_due_followups,
)

from db_documents import (  # noqa: E402
    _DOC_TYPE_SCREEN as _DOC_TYPE_SCREEN,
    _DOC_TYPE_ALIASES as _DOC_TYPE_ALIASES,
    _TEMPLATE_SCREEN as _TEMPLATE_SCREEN,
    _DEFAULT_TEMPLATE_FOR_DOC as _DEFAULT_TEMPLATE_FOR_DOC,
    _doc_channel as _doc_channel,
    _doc_type_screen as _doc_type_screen,
    _doc_template_screen as _doc_template_screen,
    _doc_requested_via as _doc_requested_via,
    _mask_email as _mask_email,
    _doc_delivery_target as _doc_delivery_target,
    _doc_event_tone as _doc_event_tone,
    _document_contracts as _document_contracts,
    _REQUESTED_VIA_CHANNEL as _REQUESTED_VIA_CHANNEL,
    _requested_via_channel as _requested_via_channel,
    _document_by_id as _document_by_id,
    _document_events as _document_events,
    _ensure_document_file as _ensure_document_file,
    _ensure_document_template as _ensure_document_template,
    add_document_delivery_attempt as add_document_delivery_attempt,
    create_document_request as create_document_request,
    list_documents as list_documents,
    patch_document_request as patch_document_request,
)

from db_callbacks import (  # noqa: E402
    CB_DISPOSITIONS as CB_DISPOSITIONS,
    CB_REASONS as CB_REASONS,
    _callback_disposition as _callback_disposition,
    _callback_dnd_active as _callback_dnd_active,
    _callback_event_tone as _callback_event_tone,
    _callback_events as _callback_events,
    _callback_reason as _callback_reason,
    _callback_reminder_channel as _callback_reminder_channel,
    _callback_reminder_status as _callback_reminder_status,
    _callback_reminders as _callback_reminders,
    _callback_source as _callback_source,
    _callback_window as _callback_window,
    _create_callback as _create_callback,
    _outside_preferred_window as _outside_preferred_window,
    add_callback_reminder as add_callback_reminder,
    create_callback as create_callback,
    list_callbacks as list_callbacks,
    patch_callback as patch_callback,
)

from db_violations import (  # noqa: E402
    _RULE_ID_SCREEN as _RULE_ID_SCREEN,
    _VIOLATION_LIST_SQL as _VIOLATION_LIST_SQL,
    _build_violation_evidence as _build_violation_evidence,
    _transcript_turn as _transcript_turn,
    _transcripts_by_interaction as _transcripts_by_interaction,
    _violation_by_id as _violation_by_id,
    _violation_notes_grouped as _violation_notes_grouped,
    _violation_rows_to_screen as _violation_rows_to_screen,
    _violation_rule_screen as _violation_rule_screen,
    _violation_severity_screen as _violation_severity_screen,
    _violation_status_screen as _violation_status_screen,
    add_violation_note as add_violation_note,
    list_violations as list_violations,
    patch_violation as patch_violation,
)

from db_consent import (  # noqa: E402
    _CONSENT_ACTIVITY_KINDS as _CONSENT_ACTIVITY_KINDS,
    _CONSENT_CHANNEL_ORDER as _CONSENT_CHANNEL_ORDER,
    _DAY_NAME_TO_NUM as _DAY_NAME_TO_NUM,
    _DAY_NUM_TO_NAME as _DAY_NUM_TO_NAME,
    _OPT_OUT_SOURCE_MAP as _OPT_OUT_SOURCE_MAP,
    _channel_status_from_patch as _channel_status_from_patch,
    _consent_audit_grouped as _consent_audit_grouped,
    _consent_channel_db as _consent_channel_db,
    _consent_channel_screen as _consent_channel_screen,
    _consent_channels_grouped as _consent_channels_grouped,
    _consent_optouts_grouped as _consent_optouts_grouped,
    _consent_segment as _consent_segment,
    _consent_source_screen as _consent_source_screen,
    _ensure_channels_complete as _ensure_channels_complete,
    _ensure_consent_record as _ensure_consent_record,
    _format_allowed_days as _format_allowed_days,
    _format_allowed_hours as _format_allowed_hours,
    _incoming_window_days as _incoming_window_days,
    _incoming_window_hours as _incoming_window_hours,
    _optout_actor_label as _optout_actor_label,
    _optout_source_screen as _optout_source_screen,
    _parse_allowed_days as _parse_allowed_days,
    _parse_allowed_hours as _parse_allowed_hours,
    _window_days_echo_stored as _window_days_echo_stored,
    _window_hours_echo_stored as _window_hours_echo_stored,
    get_contact_policy as get_contact_policy,
    list_consent as list_consent,
    opt_out as opt_out,
    patch_consent as patch_consent,
)
