"""The book sweep — one decision per delinquent account per day.

Until this existed the engine only woke on a bounce or a broken promise, which
means an account rolling silently 30 → 60 → 90 never got a decision at all. Not
a *bad* decision; none. The two triggers wired in production fire on events, and
the borrower who never bounces again because the mandate was cancelled in March
generates no events whatsoever.

That gap is why the decision log holds four rows. Everything downstream of a
corpus — uplift models, off-policy evaluation, a control arm that means
anything — is gated on this worker existing, and it is the only piece of the
design that cannot be added retrospectively.

**One decision per account per local day.** ``trigger_ref`` is the borrower's
own local date, so the case key is ``(customer, 'dpd_tick', '2026-08-21')`` and
:mod:`followthrough` treats a day's sweep as an ordinary case it can walk a
ladder over — ``dpd_tick`` is in ``LOOPED_TRIGGERS``, which for a while it was
not, so this sentence described an intention rather than a behaviour. Local
rather than UTC because a "day" is the borrower's day: an account swept at
23:30 IST and again at 00:30 IST has been swept twice, and under UTC dates it
would look like once. It is also what bounds the ladder: a day is one case, so
tomorrow starts a new one instead of extending yesterday's forever.

**Resumable, and it does not restart.** The cursor is the last account id
visited, held in ``work_runtime_jobs`` under one well-known key, so a worker
killed halfway through two million accounts resumes rather than beginning
again — which on a book that size is the difference between a sweep that
finishes daily and one that never finishes at all.

**Concurrency is the account row lock**, not a unique index. ``SELECT ... FOR
UPDATE SKIP LOCKED`` means two workers cannot hold the same account, and the
"decided today?" check runs inside that lock. A unique index on the decision
would have been tempting and wrong: the ladder legitimately writes a second
decision for the same case when the first attempt fails to resolve it, and a
constraint that forbids the second rung fails as an IntegrityError inside a
transaction the engine was lent.

**A per-account savepoint.** One borrower whose features cannot be built must
not take the batch down with them. ``recommend_treatment`` already promises
never to raise, but the logging INSERT it wraps can still fail on a constraint,
and at book scale "cannot happen" is a statement about frequency rather than
possibility.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from agent_core.treatment import config
from agent_core.treatment.features import zone
from env_utils import env_bool
from agent_core import clock

logger = logging.getLogger(__name__)

#: Accounts claimed per call. Small enough that one worker iteration is short
#: and a kill loses little; large enough that the per-batch overhead is not the
#: dominant cost.
BATCH = 500

#: Where the resume cursor lives. A work-runtime job rather than a table of its
#: own: it is one row of operational state, it already has tenant scoping and
#: an idempotency key, and a new table for a single string is a migration
#: somebody has to review.
CURSOR_WORKFLOW = "treatment_book_sweep"
CURSOR_KEY = "treatment-book-sweep-cursor"

TRIGGER = "dpd_tick"


def process_one(engine: Engine) -> bool:
    """Sweep one batch. Returns True if any account was decided.

    Returning False is what tells the worker loop to move on to other work, so
    a finished sweep must report False rather than spinning on an empty tail.
    """
    if config.mode() == config.MODE_OFF:
        return False
    if not enabled():
        return False

    with engine.begin() as conn:
        from agent_core.treatment import schema_ready

        blocked = duals_missing(conn)
        if blocked:
            # §10.5: "The sweep REFUSES to start without duals_ready or an
            # operator-set static-quota flag. A degradation with a name and a
            # page, never a silent fall-back to yesterday's prices."
            logger.error(
                "treatment sweep refuses to start: %s. Dual pricing is on, so "
                "every expected value this sweep would write has a capacity "
                "surcharge in it, and there is no solve to take it from. Set "
                "TREATMENT_STATIC_QUOTA=1 to decide without prices and say so "
                "on the rows, or run the capacity solve.",
                blocked,
            )
            return False
        if schema_ready.w6_ready(conn):
            return _process_sharded(conn)
        return _process_legacy(conn)


def duals_missing(conn: Any) -> str | None:
    """Why this sweep must not start, or ``None``.

    Only ever non-``None`` when dual pricing is switched on. With it off the
    sweep does not consume λ at all, and refusing to decide the book because a
    price nobody reads is missing would be a self-inflicted outage — which is
    why §10.5's refusal is conditional here rather than unconditional.

    ``TREATMENT_STATIC_QUOTA`` is §10.5's named escape: an operator may decide
    the book on fixed quotas instead. It is not a bypass of the §10.4 gates —
    it does not turn pricing on, it declares that today runs without it.
    """
    from agent_core.treatment import allocate

    if not allocate.enabled():
        return None
    if env_bool("TREATMENT_STATIC_QUOTA"):
        return None
    try:
        ready = conn.execute(
            text(
                """
                SELECT 1 FROM capacity_duals
                WHERE plan_date = CURRENT_DATE AND converged AND feasible
                LIMIT 1
                """
            )
        ).scalar()
    except Exception:
        logger.exception("capacity_duals unreadable")
        return "duals_unreadable"
    return None if ready else "no_duals_for_today"


def _process_legacy(conn: Any) -> bool:
    """Pre-0113 compatibility path; never used after Layer 0 is active."""
    decided = 0
    tenant = _tenant(conn)
    if tenant is None:
        return False
    cursor = _read_cursor(conn, tenant)
    accounts = _claim(conn, tenant=tenant, after=cursor, limit=BATCH)
    if not accounts:
        if cursor:
            _write_cursor(conn, tenant, "")
        return False

    for account in accounts:
        if _decide_account(conn, account):
            decided += 1
    _write_cursor(conn, tenant, accounts[-1]["id"])
    if decided:
        logger.info("treatment sweep decided %s account(s)", decided)
    return decided > 0


def _ensure_shards(conn: Any, *, tenant: str, limit: int = 5_000) -> int:
    """Give unsharded accounts a shard key before the sweep looks for them.

    ``0113`` adds ``accounts.shard_key`` as a plain nullable column, so on a
    fresh install every account has NULL and ``_claim_shard`` -- which filters
    on ``shard_key IS NOT NULL`` -- finds nothing. The sweep then decides zero
    accounts, reports no work, and looks exactly like a book that is already
    done. ``scripts/backfill_account_shards.py`` fixes it, and a step somebody
    has to remember is a step that does not happen: the day 0113 landed the
    engine would have gone quiet on the whole book with no error anywhere.

    The key is a pure function of ``(tenant_id, id)``, so computing it here is
    the same answer the script gives, and re-running is a no-op.
    """
    from bank_boundary.facts import SHARD_COUNT, SHARD_VERSION, shard_key

    rows = conn.execute(
        text(
            """
            SELECT a.id FROM accounts a
              JOIN customers c ON c.id = a.customer_id
             WHERE c.tenant_id = :tenant
               AND (a.shard_key IS NULL OR a.shard_version IS DISTINCT FROM :version)
             ORDER BY a.id
             LIMIT :limit
            """
        ),
        {"tenant": tenant, "version": SHARD_VERSION, "limit": limit},
    ).scalars().all()
    if not rows:
        return 0
    conn.execute(
        text(
            "UPDATE accounts SET shard_key = :shard_key, shard_version = :version"
            " WHERE id = :account_id"
        ),
        [
            {
                "account_id": str(account_id),
                "shard_key": shard_key(tenant, str(account_id), shard_count=SHARD_COUNT),
                "version": SHARD_VERSION,
            }
            for account_id in rows
        ],
    )
    logger.info("sweep sharded %s account(s) for tenant=%s", len(rows), tenant)
    return len(rows)


def _process_sharded(conn: Any) -> bool:
    tenant = _tenant(conn)
    if tenant is None:
        return False
    _ensure_shards(conn, tenant=tenant)
    from bank_boundary.facts import SHARD_VERSION

    owner = (os.getenv("HOSTNAME") or f"wk-batch-{uuid.uuid4().hex[:8]}")[:100]
    local_date = clock.today_local()
    conn.execute(
        text(
            """
            INSERT INTO treatment_sweep_runs (
              id, tenant_id, portfolio_id, local_date, shard_key,
              shard_version, state
            )
            SELECT 'TSR-' || substr(md5(
                     c.tenant_id || ':' || CAST(:day AS text) || ':' ||
                     a.shard_version::text || ':' || a.shard_key::text
                   ), 1, 24),
                   c.tenant_id, '', :day, a.shard_key, a.shard_version, 'pending'
              FROM accounts a JOIN customers c ON c.id = a.customer_id
             WHERE c.tenant_id = :tenant
               AND c.id NOT LIKE 'SIM-%'
               AND a.status = 'active' AND a.dpd > 0
               AND a.shard_key IS NOT NULL
               AND a.shard_version = :version
             GROUP BY c.tenant_id, a.shard_key, a.shard_version
            ON CONFLICT (
              tenant_id, portfolio_id, local_date, shard_version, shard_key
            ) DO NOTHING
            """
        ),
        {"tenant": tenant, "day": local_date, "version": SHARD_VERSION},
    )
    run = conn.execute(
        text(
            """
            SELECT *
              FROM treatment_sweep_runs
             WHERE tenant_id = :tenant AND local_date = :day
               AND shard_version = :version
               AND state <> 'complete'
               AND (lease_until IS NULL OR lease_until < now() OR lease_owner = :owner)
             ORDER BY shard_key
             LIMIT 1
             FOR UPDATE SKIP LOCKED
            """
        ),
        {
            "tenant": tenant,
            "day": local_date,
            "version": SHARD_VERSION,
            "owner": owner,
        },
    ).mappings().first()
    if run is None:
        return False
    lock_name = (
        f"treatment-sweep:{tenant}:{local_date}:{run['shard_version']}:{run['shard_key']}"
    )
    locked = conn.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtextextended(:name, 0))"),
        {"name": lock_name},
    ).scalar()
    if locked is not True:
        return False
    conn.execute(
        text(
            """
            UPDATE treatment_sweep_runs
               SET state = 'working', lease_owner = :owner,
                   lease_until = now() + interval '10 minutes',
                   started_at = COALESCE(started_at, now()), error = NULL
             WHERE id = :id
            """
        ),
        {"id": run["id"], "owner": owner},
    )
    claimed_any = False
    for attempt in (1, 2):
        claims = _claim_sharded_accounts(
            conn,
            tenant=tenant,
            run_id=str(run["id"]),
            shard_key=int(run["shard_key"]),
            local_date=local_date,
            owner=owner,
        )
        if not claims:
            continue
        if attempt == 2:
            conn.execute(
                text(
                    """
                    UPDATE treatment_sweep_runs
                       SET retry_passes = retry_passes + 1
                     WHERE id = :id
                    """
                ),
                {"id": run["id"]},
            )
        for raw in claims:
            account = dict(raw)
            conn.execute(
                text(
                    """
                    UPDATE treatment_sweep_claims
                       SET lease_until = now() + interval '10 minutes',
                           updated_at = now()
                     WHERE id = :id AND lease_owner = :owner
                    """
                ),
                {"id": account["claim_id"], "owner": owner},
            )
            decision_id = _decide_account_id(
                conn, account, tenant=tenant, local_day=local_date.isoformat()
            )
            state = "decided" if decision_id else "skipped"
            conn.execute(
                text(
                    """
                    UPDATE treatment_sweep_claims
                       SET state = :state, decision_id = :decision_id,
                           lease_until = NULL, updated_at = now()
                     WHERE id = :id AND lease_owner = :owner
                    """
                ),
                {
                    "id": account["claim_id"],
                    "owner": owner,
                    "state": state,
                    "decision_id": decision_id,
                },
            )
        claimed_any = True
        logger.info(
            "treatment sweep tenant=%s day=%s shard=%s claimed=%s attempt=%s",
            tenant,
            local_date,
            run["shard_key"],
            len(claims),
            attempt,
        )
    _reconcile_shard(conn, str(run["id"]), tenant, local_date, int(run["shard_key"]))
    return claimed_any


def _claim_sharded_accounts(
    conn: Any,
    *,
    tenant: str,
    run_id: str,
    shard_key: int,
    local_date: Any,
    owner: str,
) -> list[dict[str, Any]]:
    from bank_boundary.facts import SHARD_VERSION

    rows = conn.execute(
        text(
            """
            WITH eligible AS (
              SELECT a.id AS account_id, a.customer_id, c.timezone
                FROM accounts a JOIN customers c ON c.id = a.customer_id
               WHERE c.tenant_id = :tenant
                 AND c.id NOT LIKE 'SIM-%'
                 AND a.status = 'active' AND a.dpd > 0
                 AND a.shard_key = :shard
                 AND a.shard_version = :version
                 AND NOT EXISTS (
                   SELECT 1 FROM treatment_sweep_claims sc
                    WHERE sc.tenant_id = :tenant
                      AND sc.account_id = a.id
                      AND sc.trigger_kind = :kind
                      AND sc.local_date = :day
                 )
               ORDER BY a.id
               LIMIT :limit
            ),
            inserted AS (
              INSERT INTO treatment_sweep_claims (
                id, tenant_id, run_id, account_id, trigger_kind, local_date,
                state, lease_owner, lease_until
              )
              SELECT 'TSC-' || substr(md5(
                       :tenant || ':' || e.account_id || ':' || :kind || ':' || CAST(:day AS text)
                     ), 1, 24),
                     :tenant, :run_id, e.account_id, :kind, :day,
                     'claimed', :owner, now() + interval '10 minutes'
                FROM eligible e
              ON CONFLICT (tenant_id, account_id, trigger_kind, local_date)
              DO NOTHING
              RETURNING id, account_id
            )
            SELECT i.id AS claim_id, e.account_id AS id, e.customer_id, e.timezone
              FROM inserted i JOIN eligible e ON e.account_id = i.account_id
             ORDER BY e.account_id
            """
        ),
        {
            "tenant": tenant,
            "shard": shard_key,
            "version": SHARD_VERSION,
            "kind": TRIGGER,
            "day": local_date,
            "limit": BATCH,
            "run_id": run_id,
            "owner": owner,
        },
    ).mappings().all()
    return [dict(row) for row in rows]


def _reconcile_shard(
    conn: Any, run_id: str, tenant: str, local_date: Any, shard_key: int
) -> None:
    from bank_boundary.facts import SHARD_VERSION

    counts = conn.execute(
        text(
            """
            SELECT
              count(*)::bigint AS eligible,
              count(*) FILTER (WHERE sc.state = 'decided')::bigint AS decided,
              count(*) FILTER (WHERE sc.state = 'skipped')::bigint AS skipped,
              count(*) FILTER (WHERE sc.id IS NULL OR sc.state IN ('claimed','failed'))::bigint
                AS remaining
              FROM accounts a
              JOIN customers c ON c.id = a.customer_id
              LEFT JOIN treatment_sweep_claims sc
                ON sc.tenant_id = c.tenant_id
               AND sc.account_id = a.id
               AND sc.trigger_kind = :kind
               AND sc.local_date = :day
             WHERE c.tenant_id = :tenant
               AND c.id NOT LIKE 'SIM-%'
               AND a.status = 'active' AND a.dpd > 0
               AND a.shard_key = :shard
               AND a.shard_version = :version
            """
        ),
        {
            "kind": TRIGGER,
            "day": local_date,
            "tenant": tenant,
            "shard": shard_key,
            "version": SHARD_VERSION,
        },
    ).mappings().one()
    complete = int(counts["remaining"] or 0) == 0
    conn.execute(
        text(
            """
            UPDATE treatment_sweep_runs
               SET eligible_count = :eligible, decided_count = :decided,
                   skipped_count = :skipped,
                   state = CASE WHEN :complete THEN 'complete' ELSE 'working' END,
                   completed_at = CASE WHEN :complete THEN now() ELSE NULL END,
                   lease_owner = CASE WHEN :complete THEN NULL ELSE lease_owner END,
                   lease_until = CASE
                     WHEN :complete THEN NULL
                     ELSE now() + interval '10 minutes'
                   END
             WHERE id = :id
            """
        ),
        {
            "id": run_id,
            "eligible": int(counts["eligible"] or 0),
            "decided": int(counts["decided"] or 0),
            "skipped": int(counts["skipped"] or 0),
            "complete": complete,
        },
    )


def enabled() -> bool:
    """Off by default.

    A worker that starts deciding across an entire book the moment it is
    deployed is a worker nobody chose to run. Shadow mode makes that harmless
    to borrowers, but it is still a per-account write against production every
    day, and that is an operational decision rather than a deployment
    side-effect.
    """
    return env_bool("TREATMENT_SWEEP")


def _tenant(conn: Any) -> str | None:
    import db as dbmod

    try:
        return dbmod.current_tenant()
    except Exception:
        logger.exception("treatment sweep could not resolve the tenant")
        return None


def _claim(
    conn: Any, *, tenant: str, after: str | None, limit: int
) -> list[dict[str, Any]]:
    """Lock the next slice of the delinquent book.

    ``FOR UPDATE OF a SKIP LOCKED`` on the account, not the customer: two
    accounts of one borrower are two decisions, and locking the customer would
    serialise a household behind whichever of its loans was claimed first.
    """
    rows = conn.execute(
        text(
            """
            SELECT a.id, a.customer_id, c.timezone
            FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.tenant_id = :tenant
              AND a.status = 'active'
              AND a.dpd > 0
              AND a.id > COALESCE(:after, '')
            ORDER BY a.id
            LIMIT :limit
            FOR UPDATE OF a SKIP LOCKED
            """
        ),
        {"tenant": tenant, "after": after or None, "limit": limit},
    ).mappings().all()
    return [dict(r) for r in rows]


def _decide_account(conn: Any, account: dict[str, Any]) -> bool:
    """One account, inside its own savepoint. Returns True if a row was written."""
    now = datetime.now(timezone.utc)
    local_day = _local_day(now, account.get("timezone"))
    return (
        _decide_account_id(
            conn,
            account,
            tenant=None,
            local_day=local_day,
            now=now,
        )
        is not None
    )


def _decide_account_id(
    conn: Any,
    account: dict[str, Any],
    *,
    tenant: str | None,
    local_day: str,
    now: datetime | None = None,
) -> str | None:
    """Decide one leased account and return the persisted decision id."""
    from agent_core.treatment.engine import recommend_treatment
    from agent_core.treatment.features import Trigger

    if _decided_today(
        conn,
        account["customer_id"],
        local_day,
        account_id=account["id"],
        tenant=tenant,
    ):
        return None

    savepoint = conn.begin_nested()
    try:
        instant = now or datetime.now(timezone.utc)
        result = recommend_treatment(
            customer_id=account["customer_id"],
            account_id=account["id"],
            trigger=Trigger(kind=TRIGGER, at=instant, ref=local_day),
            now=instant,
            conn=conn,
        )
    except Exception:
        # recommend_treatment promises not to raise; this catches the INSERT it
        # wraps failing on a constraint. One borrower's bad row must not cost
        # the other forty-nine in the batch.
        savepoint.rollback()
        logger.exception("treatment sweep failed for account=%s", account["id"])
        return None
    savepoint.commit()
    return str(result.decision_id) if result.decision_id is not None else None


def _decided_today(
    conn: Any,
    customer_id: str,
    local_day: str,
    *,
    account_id: str | None = None,
    tenant: str | None = None,
) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM treatment_decisions
            WHERE customer_id = :cid
              AND (CAST(:aid AS TEXT) IS NULL OR account_id = :aid)
              AND (CAST(:tenant AS TEXT) IS NULL OR tenant_id = :tenant)
              AND trigger_kind = :kind
              AND trigger_ref = :ref
              AND mode <> 'simulated'
            LIMIT 1
            """
        ),
        {
            "cid": customer_id,
            "aid": account_id,
            "tenant": tenant,
            "kind": TRIGGER,
            "ref": local_day,
        },
    ).scalar()
    return row is not None


def _local_day(now: datetime, timezone_name: str | None) -> str:
    tz: ZoneInfo = zone(timezone_name)
    return now.astimezone(tz).date().isoformat()


# ---------------------------------------------------------------------------
# The resume cursor
# ---------------------------------------------------------------------------


def _read_cursor(conn: Any, tenant: str) -> str | None:
    row = conn.execute(
        text(
            """
            SELECT payload->>'afterAccountId' AS after
            FROM work_runtime_jobs
            WHERE tenant_id = :tenant AND idempotency_key = :key
            """
        ),
        {"tenant": tenant, "key": CURSOR_KEY},
    ).scalar()
    return str(row) if row else None


def _write_cursor(conn: Any, tenant: str, after: str) -> None:
    from work_runtime import upsert_job

    upsert_job(
        workflow_type=CURSOR_WORKFLOW,
        payload={"afterAccountId": after},
        idempotency_key=CURSOR_KEY,
        status="working",
        conn=conn,
    )
