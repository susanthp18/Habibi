"""The tenant a call acts for, and how it reaches Postgres.

Row-level security compares ``tenant_id`` against the ``app.tenant_id`` GUC. If
that GUC is ever unset the comparison is NULL, no row matches, and every query
in the application returns nothing — an outage that looks like an empty
database. These tests hold the two properties that make that impossible: the
value is present on a connection before it can run anything, and no rollback
can take it away.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db
import tenant_context


def test_default_is_the_process_tenant() -> None:
    assert tenant_context.current_tenant() == db.TENANT_ID
    assert not tenant_context.is_bound()


def test_bind_scopes_the_tenant_and_restores_it() -> None:
    with tenant_context.bind("rival.bank") as bound:
        assert bound == "rival.bank"
        assert tenant_context.current_tenant() == "rival.bank"
        assert tenant_context.is_bound()
    assert tenant_context.current_tenant() == db.TENANT_ID
    assert not tenant_context.is_bound()


def test_bind_restores_on_exception() -> None:
    with pytest.raises(ValueError):
        with tenant_context.bind("rival.bank"):
            raise ValueError("boom")
    assert tenant_context.current_tenant() == db.TENANT_ID


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "tenant with space",          # would split the libpq options string
        "tenant'; DROP TABLE x --",   # would escape the SET statement
        "tenant\nid",
        "x" * 129,
    ],
)
def test_unsafe_tenant_ids_are_refused(bad: str) -> None:
    """The value is interpolated into ``SET`` and into libpq ``options``.

    Postgres accepts no bind parameter in ``SET``, so the safety of that
    interpolation rests entirely on this check rather than on quoting.
    """
    with pytest.raises(tenant_context.InvalidTenantId):
        tenant_context.set_tenant(bad)


@pytest.mark.parametrize("good", ["hdfc.retail", "acme-bank", "t_1", "a:b", "x"])
def test_ordinary_tenant_ids_are_accepted(good: str) -> None:
    assert tenant_context.validate(good) == good


# ---------------------------------------------------------------------------
# The GUC on a real connection
# ---------------------------------------------------------------------------


def _guc(conn) -> str | None:
    return conn.execute(
        text(f"SELECT current_setting('{tenant_context.GUC}', true)")
    ).scalar()


def test_guc_is_set_on_every_connection() -> None:
    with db.engine.connect() as conn:
        assert _guc(conn) == db.TENANT_ID


def test_guc_survives_a_rollback() -> None:
    """The property that rules out the zero-rows outage.

    A GUC set with ``SET`` inside a transaction is reverted by ROLLBACK, and the
    pool issues one on every return-to-pool. Passing the tenant as a libpq
    startup parameter instead puts it outside transaction scope entirely.
    """
    with db.engine.connect() as conn:
        trans = conn.begin()
        conn.execute(text("SELECT 1"))
        trans.rollback()
        assert _guc(conn) == db.TENANT_ID


def test_bound_tenant_reaches_the_database() -> None:
    with tenant_context.bind("rival.bank"):
        with db.engine.begin() as conn:
            assert _guc(conn) == "rival.bank"


def test_bound_tenant_does_not_leak_to_the_next_transaction() -> None:
    """``SET LOCAL`` — a pooled connection must not carry one call's tenant
    into the next borrower's."""
    with tenant_context.bind("rival.bank"):
        with db.engine.begin() as conn:
            assert _guc(conn) == "rival.bank"
    with db.engine.begin() as conn:
        assert _guc(conn) == db.TENANT_ID
