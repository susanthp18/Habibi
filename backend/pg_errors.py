"""PostgreSQL error classification shared by every write path.

Kept in one place so the "is this a duplicate?" decision cannot drift between
the job queues, the WhatsApp ingest path and db.py — a mismatch there either
double-inserts or swallows an unrelated constraint failure as a duplicate.
"""

from __future__ import annotations

__all__ = [
    "PG_CHECK_VIOLATION",
    "PG_FOREIGN_KEY_VIOLATION",
    "PG_NOT_NULL_VIOLATION",
    "PG_UNIQUE_VIOLATION",
    "constraint_detail",
    "is_unique_violation",
    "sqlstate",
]

# PostgreSQL unique_violation.
PG_UNIQUE_VIOLATION = "23505"
PG_FOREIGN_KEY_VIOLATION = "23503"
PG_NOT_NULL_VIOLATION = "23502"
PG_CHECK_VIOLATION = "23514"

#: What the API says for each integrity class. One map, so a write path cannot
#: call a foreign-key miss a duplicate.
_DETAIL_BY_SQLSTATE = {
    PG_UNIQUE_VIOLATION: "duplicate",
    PG_FOREIGN_KEY_VIOLATION: "unknown_reference",
    PG_NOT_NULL_VIOLATION: "missing_required_field",
    PG_CHECK_VIOLATION: "check_violation",
}


def sqlstate(exc: BaseException) -> str | None:
    """The SQLSTATE behind a driver or SQLAlchemy error, or None."""
    # SQLAlchemy wraps the driver error in .orig; a directly-caught psycopg
    # error carries the SQLSTATE itself. Both reach the job queues and the
    # WhatsApp ingest path, so neither shape may fall through.
    driver_exc = getattr(exc, "orig", None) or exc
    code = getattr(driver_exc, "sqlstate", None) or getattr(driver_exc, "pgcode", None)
    return str(code) if code else None


def constraint_detail(exc: BaseException) -> str:
    """The client-facing word for an IntegrityError: duplicate, unknown_reference,
    missing_required_field, check_violation -- or constraint_violation when the
    driver exposed no SQLSTATE."""
    return _DETAIL_BY_SQLSTATE.get(sqlstate(exc) or "", "constraint_violation")


def is_unique_violation(exc: BaseException) -> bool:
    """True for a PostgreSQL unique-violation, across psycopg2/psycopg3."""
    code = sqlstate(exc)
    if code:
        return code == PG_UNIQUE_VIOLATION
    # Driver did not expose a SQLSTATE — fall back to the message. Match the
    # duplicate-key wording specifically: "there is no unique constraint
    # matching given keys" (42830) also contains "unique constraint", and
    # swallowing that as a duplicate hides a schema error as a no-op.
    return "duplicate key" in str(exc).lower()
