"""PostgreSQL error classification shared by every write path.

Kept in one place so the "is this a duplicate?" decision cannot drift between
the job queues, the WhatsApp ingest path and db.py — a mismatch there either
double-inserts or swallows an unrelated constraint failure as a duplicate.
"""

from __future__ import annotations

__all__ = ["PG_UNIQUE_VIOLATION", "is_unique_violation"]

# PostgreSQL unique_violation.
PG_UNIQUE_VIOLATION = "23505"


def is_unique_violation(exc: BaseException) -> bool:
    """True for a PostgreSQL unique-violation, across psycopg2/psycopg3."""
    # SQLAlchemy wraps the driver error in .orig; a directly-caught psycopg
    # error carries the SQLSTATE itself. Both reach the job queues and the
    # WhatsApp ingest path, so neither shape may fall through as "not unique".
    driver_exc = getattr(exc, "orig", None) or exc
    code = getattr(driver_exc, "sqlstate", None) or getattr(driver_exc, "pgcode", None)
    if code:
        return str(code) == PG_UNIQUE_VIOLATION
    # Driver did not expose a SQLSTATE — fall back to the message. Match the
    # duplicate-key wording specifically: "there is no unique constraint
    # matching given keys" (42830) also contains "unique constraint", and
    # swallowing that as a duplicate hides a schema error as a no-op.
    return "duplicate key" in str(exc).lower()
