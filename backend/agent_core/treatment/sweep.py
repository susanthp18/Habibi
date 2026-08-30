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
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.engine import Engine

from agent_core.treatment import config
from agent_core.treatment.features import zone

logger = logging.getLogger(__name__)

#: Accounts claimed per call. Small enough that one worker iteration is short
#: and a kill loses little; large enough that the per-batch overhead is not the
#: dominant cost.
BATCH = 50

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

    decided = 0
    with engine.begin() as conn:
        tenant = _tenant(conn)
        if tenant is None:
            return False
        cursor = _read_cursor(conn, tenant)
        accounts = _claim(conn, tenant=tenant, after=cursor, limit=BATCH)
        if not accounts:
            # The tail. Reset so tomorrow's sweep starts at the beginning
            # rather than at the end of the book, and report no work — a sweep
            # that reports True on an empty batch starves every other loop in
            # the worker.
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


def enabled() -> bool:
    """Off by default.

    A worker that starts deciding across an entire book the moment it is
    deployed is a worker nobody chose to run. Shadow mode makes that harmless
    to borrowers, but it is still a per-account write against production every
    day, and that is an operational decision rather than a deployment
    side-effect.
    """
    import os

    return (os.getenv("TREATMENT_SWEEP") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
    from agent_core.treatment.engine import recommend_treatment
    from agent_core.treatment.features import Trigger

    now = datetime.now(timezone.utc)
    local_day = _local_day(now, account.get("timezone"))

    if _decided_today(conn, account["customer_id"], local_day):
        return False

    savepoint = conn.begin_nested()
    try:
        result = recommend_treatment(
            customer_id=account["customer_id"],
            account_id=account["id"],
            trigger=Trigger(kind=TRIGGER, at=now, ref=local_day),
            now=now,
            conn=conn,
        )
    except Exception:
        # recommend_treatment promises not to raise; this catches the INSERT it
        # wraps failing on a constraint. One borrower's bad row must not cost
        # the other forty-nine in the batch.
        savepoint.rollback()
        logger.exception("treatment sweep failed for account=%s", account["id"])
        return False
    savepoint.commit()
    return result.decision_id is not None


def _decided_today(conn: Any, customer_id: str, local_day: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM treatment_decisions
            WHERE customer_id = :cid
              AND trigger_kind = :kind
              AND trigger_ref = :ref
            LIMIT 1
            """
        ),
        {"cid": customer_id, "kind": TRIGGER, "ref": local_day},
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
    import db as dbmod

    conn.execute(
        text(
            """
            INSERT INTO work_runtime_jobs (
              id, tenant_id, workflow_type, status, payload, idempotency_key
            ) VALUES (
              :id, :tenant, :workflow, 'working',
              -- CAST because jsonb_build_object takes "any", so Postgres cannot
              -- infer a bind parameter's type from the call site.
              jsonb_build_object('afterAccountId', CAST(:after AS TEXT)), :key
            )
            ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
              SET payload = jsonb_build_object(
                    'afterAccountId', CAST(:after AS TEXT)
                  ),
                  updated_at = now()
            """
        ),
        {
            "id": dbmod._id("WRJ"),
            "tenant": tenant,
            "workflow": CURSOR_WORKFLOW,
            "after": after,
            "key": CURSOR_KEY,
        },
    )
