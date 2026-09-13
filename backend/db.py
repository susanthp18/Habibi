"""Postgres accessors plus API response serializers."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

import contact_window
from agent_core import clock
import visibility
from env_utils import env_float

from db_core import (
    DEFAULT_DETAIL_LIMIT as DEFAULT_DETAIL_LIMIT,
    user_exists as user_exists,
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
            customer["ledger"] = _ledger_rows(conn, account_id, MAX_LIST_LIMIT)
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
                -- One typed leg per related table, so each probes the
                -- (entity_type, entity_id) index; six OR'd IN (subquery) legs
                -- without the type scanned the whole table per card open.
                WITH related(entity_type, entity_id) AS (
                  SELECT 'customer', CAST(:customer_id AS text)
                  UNION ALL SELECT 'interaction', id FROM interactions WHERE customer_id = :customer_id
                  UNION ALL SELECT 'promise', id FROM promises WHERE customer_id = :customer_id
                  UNION ALL SELECT 'dispute', id FROM disputes WHERE customer_id = :customer_id
                  UNION ALL SELECT 'conversation', id FROM conversations WHERE customer_id = :customer_id
                  UNION ALL SELECT 'document_request', id FROM document_requests WHERE customer_id = :customer_id
                )
                SELECT ae.id, ae.kind, ae.label, ae.note, ae.at, ae.tone
                FROM activity_events ae
                JOIN related r ON r.entity_type = ae.entity_type AND r.entity_id = ae.entity_id
                WHERE ae.tenant_id = :tenant_id
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


def _ledger_rows(conn: Any, account_id: str, limit: int) -> list[dict[str, Any]]:
    """Newest first, bounded: the 360 reads up to the list ceiling, a tool a page."""
    return _rows(
        conn.execute(
            text(
                """
                SELECT id, posted_at AS date, description, type, amount, invoice_id AS "invoiceId"
                FROM ledger_entries
                WHERE account_id = :account_id
                ORDER BY posted_at DESC
                LIMIT :limit
                """
            ),
            {"account_id": account_id, "limit": limit},
        )
    )


def list_ledger(account_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    """The voice/WhatsApp tool's read: a page, not the aggregate get_customer hydrates."""
    with engine.connect() as conn:
        return _ledger_rows(conn, account_id, clamp_list_limit(limit, default=8))


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


# ---------------------------------------------------------------------------

# Coaching / calibration, and the writes that live with their readers
# (redaction, routing, workspace). Keep call sites as db.*.
# get_calibration_session stays in db_coaching — only patch uses it.
# ---------------------------------------------------------------------------
from db_inbox import (  # noqa: E402
    _TYPING_STALE_AFTER as _TYPING_STALE_AFTER,
    _bot_typing_by_conversation as _bot_typing_by_conversation,
    _conversation_base_rows as _conversation_base_rows,
    _conversation_messages as _conversation_messages,
    _conversation_suggestions as _conversation_suggestions,
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
    _serialize_conversation as _serialize_conversation,
    _thread_context as _thread_context,
    escalate_conversation_to_human as escalate_conversation_to_human,
    get_conversation as get_conversation,
    get_latest_context_summary as get_latest_context_summary,
    handoff_to_agent as handoff_to_agent,
    list_bot_ids as list_bot_ids,
    list_canned_responses as list_canned_responses,
    list_conversations as list_conversations,
    return_conversation_to_bot as return_conversation_to_bot,
    save_context_summary as save_context_summary,
    send_conversation_message as send_conversation_message,
    takeover_conversation as takeover_conversation,
)
from db_inbox_rag import (  # noqa: E402
    INBOX_RAG_MIN_SCORE as INBOX_RAG_MIN_SCORE,
    _INBOX_RAG_COLLECTIONS_HINTS as _INBOX_RAG_COLLECTIONS_HINTS,
    _INBOX_RAG_MAX_TURN_CHARS as _INBOX_RAG_MAX_TURN_CHARS,
    _INBOX_RAG_NOISE as _INBOX_RAG_NOISE,
    _INBOX_RAG_TEST_MARKERS as _INBOX_RAG_TEST_MARKERS,
    _chip_from_result as _chip_from_result,
    _clip_inbox_rag_turn as _clip_inbox_rag_turn,
    _conversation_rag_query as _conversation_rag_query,
    _is_inbox_rag_noise as _is_inbox_rag_noise,
    _is_questionish as _is_questionish,
    _looks_collections_topic as _looks_collections_topic,
    _looks_like_pasted_draft as _looks_like_pasted_draft,
    refresh_conversation_suggestions as refresh_conversation_suggestions,
)
from db_whatsapp import (  # noqa: E402
    _DELIVERY_RANK as _DELIVERY_RANK,
    _apply_whatsapp_status as _apply_whatsapp_status,
    _digits_phone_exact_sql as _digits_phone_exact_sql,
    _digits_phone_tail10_sql as _digits_phone_tail10_sql,
    _ensure_whatsapp_customer as _ensure_whatsapp_customer,
    _find_customer_by_phone as _find_customer_by_phone,
    _ingest_inbound_whatsapp_message as _ingest_inbound_whatsapp_message,
    _open_whatsapp_conversation as _open_whatsapp_conversation,
    _tail10_predicate as _tail10_predicate,
    _touch_interaction_sentiment as _touch_interaction_sentiment,
    find_customer_by_phone as find_customer_by_phone,
    process_whatsapp_webhook as process_whatsapp_webhook,
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

from db_disputes import (  # noqa: E402
    DISPUTE_SLA_WARN_FRACTION as DISPUTE_SLA_WARN_FRACTION,
    _dispute_sla_countdown as _dispute_sla_countdown,
    _dispute_sla as _dispute_sla,
    _dispute_contracts as _dispute_contracts,
    _dispute_source_screen as _dispute_source_screen,
    _evidence_kind as _evidence_kind,
    _dispute_event_tone as _dispute_event_tone,
    _dispute_events as _dispute_events,
    _dispute_evidence as _dispute_evidence,
    list_disputes as list_disputes,
    _dispute_by_id as _dispute_by_id,
    create_dispute as create_dispute,
    _create_dispute as _create_dispute,
    patch_dispute as patch_dispute,
    add_dispute_note as add_dispute_note,
    add_dispute_evidence as add_dispute_evidence,
)

from db_interactions import (  # noqa: E402
    DEFAULT_CALLS_LIMIT as DEFAULT_CALLS_LIMIT,
    _sentiment_delta as _sentiment_delta,
    _interaction_contracts as _interaction_contracts,
    list_calls as list_calls,
    create_interaction as create_interaction,
    wrap_up_interaction as wrap_up_interaction,
)

from db_promises import (  # noqa: E402
    REVISION_REASONS as REVISION_REASONS,
    cancel_promise as cancel_promise,
    revise_promise as revise_promise,
    _promise_contracts as _promise_contracts,
    OwnerBotNotFound as OwnerBotNotFound,
    _create_promise as _create_promise,
    _plan_cadence as _plan_cadence,
    _promise_by_id as _promise_by_id,
    _promise_events as _promise_events,
    create_payment_plan as create_payment_plan,
    create_promise as create_promise,
    list_payment_plans as list_payment_plans,
    list_promises as list_promises,
    patch_promise as patch_promise,
    resend_promise_confirm as resend_promise_confirm,
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
