"""Entra identity columns on ``users``.

The app role cannot ALTER ``users`` (it is not the owner). The columns already
ship in ``sql/01_identity.sql`` / ``sql/53_entra_identity.sql``. Fixtures that
used to ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` therefore fail on this
database even when the schema is already present.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

_NEEDED = (
    "entra_oid",
    "entra_tid",
    "entra_upn",
    "bootstrap_admin",
    "last_login_at",
)


def ensure_entra_user_columns(conn, *, unique_index: bool = False) -> None:
    """Skip the test if the Entra identity columns are not installed.

    Never ALTER: the collections role is not table owner, and a missing column
    means the identity schema has not been applied, which a fixture cannot fix.
    """
    existing = {
        row[0]
        for row in conn.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users'
                """
            )
        )
    }
    missing = [name for name in _NEEDED if name not in existing]
    if missing:
        pytest.skip(f"users missing {missing}; entra identity schema is not applied")
    if not unique_index:
        return
    has_idx = conn.execute(
        text(
            """
            SELECT 1 FROM pg_indexes
            WHERE schemaname = 'public' AND indexname = 'uq_users_entra_oid'
            """
        )
    ).scalar()
    if not has_idx:
        pytest.skip("uq_users_entra_oid is not installed")


def ensure_relation(conn, name: str) -> None:
    """Skip when a table the test needs has not been applied."""
    found = conn.execute(text("SELECT to_regclass(:n)"), {"n": name}).scalar()
    if not found:
        pytest.skip(f"{name} is not installed")
