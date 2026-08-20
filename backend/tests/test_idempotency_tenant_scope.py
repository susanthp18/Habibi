"""Idempotency keys must not be shared across tenants.

The bug this locks shut is a data leak, not a scoping oversight.
``idempotency_keys`` caches a *response body* keyed by ``(endpoint, key)``. The
key is client-supplied and clients reuse predictable ones ("order-123"), so two
tenants posting the same key to the same endpoint collided — and the second
caller was served the first tenant's stored response verbatim.

Verbatim is the important word: the replay path returns the cached body without
re-reading any row, so none of the tenant predicates in the data layer get a
chance to filter it. Every other tenant-scoping fix in this codebase protects a
query; this one protects a cache.
"""

from __future__ import annotations

import json

from sqlalchemy import text

import db


ENDPOINT = "POST /promises"
SHARED_KEY = "order-123"  # the kind of key a client actually sends


def _foreign_tenant(conn, tenant_id: str = "other.bank") -> str:
    conn.execute(
        text("INSERT INTO tenants (id, name) VALUES (:t, 'Other Bank') ON CONFLICT DO NOTHING"),
        {"t": tenant_id},
    )
    return tenant_id


def test_primary_key_includes_tenant(db_tx) -> None:
    """Structural guard: the PK is what makes the two rows distinct."""
    cols = db_tx.execute(
        text(
            """
            SELECT kcu.column_name
              FROM information_schema.table_constraints tc
              JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = tc.constraint_name
               AND kcu.table_schema = tc.table_schema
             WHERE tc.table_schema = 'public'
               AND tc.table_name = 'idempotency_keys'
               AND tc.constraint_type = 'PRIMARY KEY'
             ORDER BY kcu.ordinal_position
            """
        )
    ).scalars().all()
    assert cols == ["tenant_id", "endpoint", "key"], cols


def test_same_key_in_two_tenants_stores_two_rows(db_tx) -> None:
    """Previously the second INSERT hit ON CONFLICT and was silently dropped."""
    other = _foreign_tenant(db_tx)
    for tenant, body in ((db.TENANT_ID, {"id": "ours"}), (other, {"id": "theirs"})):
        db_tx.execute(
            text(
                """
                INSERT INTO idempotency_keys (tenant_id, key, endpoint, response)
                VALUES (:t, :k, :e, CAST(:r AS jsonb))
                ON CONFLICT (tenant_id, endpoint, key) DO NOTHING
                """
            ),
            {"t": tenant, "k": SHARED_KEY, "e": ENDPOINT, "r": json.dumps(body)},
        )

    n = db_tx.execute(
        text(
            "SELECT count(*) FROM idempotency_keys WHERE key = :k AND endpoint = :e"
        ),
        {"k": SHARED_KEY, "e": ENDPOINT},
    ).scalar()
    assert n == 2, "both tenants must keep their own cached response"


def test_replay_never_returns_another_tenants_response(db_tx) -> None:
    """The leak itself: our lookup must not see the other tenant's body."""
    other = _foreign_tenant(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO idempotency_keys (tenant_id, key, endpoint, response)
            VALUES (:t, :k, :e, CAST(:r AS jsonb))
            """
        ),
        {
            "t": other,
            "k": SHARED_KEY,
            "e": ENDPOINT,
            "r": json.dumps({"id": "PTP-OTHER-TENANT", "customerName": "Someone Else"}),
        },
    )

    found = db._idempotent_response(db_tx, SHARED_KEY, ENDPOINT)
    assert found is None, f"served another tenant's cached response: {found}"


def test_replay_still_returns_our_own_response(db_tx) -> None:
    """Scoping must not break idempotency for the tenant that owns the key."""
    ours = {"id": "PTP-OURS"}
    db._store_idempotent_response(db_tx, SHARED_KEY, ENDPOINT, ours)
    assert db._idempotent_response(db_tx, SHARED_KEY, ENDPOINT) == ours


def test_store_is_still_idempotent_within_a_tenant(db_tx) -> None:
    db._store_idempotent_response(db_tx, SHARED_KEY, ENDPOINT, {"id": "first"})
    db._store_idempotent_response(db_tx, SHARED_KEY, ENDPOINT, {"id": "second"})
    assert db._idempotent_response(db_tx, SHARED_KEY, ENDPOINT) == {"id": "first"}


def test_missing_key_is_a_passthrough(db_tx) -> None:
    """No key means no idempotency, not an empty cached response."""
    assert db._idempotent_response(db_tx, None, ENDPOINT) is None
    db._store_idempotent_response(db_tx, None, ENDPOINT, {"id": "x"})  # must not raise


def test_endpoint_still_separates_keys(db_tx) -> None:
    """Tenant was added to the key, not substituted for endpoint."""
    db._store_idempotent_response(db_tx, SHARED_KEY, "POST /promises", {"id": "promise"})
    db._store_idempotent_response(db_tx, SHARED_KEY, "POST /disputes", {"id": "dispute"})
    assert db._idempotent_response(db_tx, SHARED_KEY, "POST /promises") == {"id": "promise"}
    assert db._idempotent_response(db_tx, SHARED_KEY, "POST /disputes") == {"id": "dispute"}
