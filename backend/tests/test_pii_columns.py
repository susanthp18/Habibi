"""PII columns are encrypted at rest, and the application cannot tell.

`customers` is a view over `customers_pii` (sql/01_pii.sql, sql/02b): phone
numbers, email and address are pgcrypto ciphertext in the base table, the
key rides on the connection as `app.pii_key` (pii_key.py), reads decrypt,
writes encrypt through INSTEAD OF triggers, and an equality lookup by phone
uses the HMAC index rather than the plaintext.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db


def _new_customer(conn, phone: str, email: str) -> str:
    cid = f"pii-{uuid.uuid4().hex[:10]}"
    conn.execute(
        text(
            """
            INSERT INTO customers (id, tenant_id, name, phone_primary, email, address, risk)
            VALUES (:id, :t, 'PII Test', :phone, :email, '12 Test Lane', 'low')
            """
        ),
        {"id": cid, "t": db.current_tenant(), "phone": phone, "email": email},
    )
    return cid


def test_the_base_table_holds_no_plaintext(db_tx) -> None:
    cid = _new_customer(db_tx, "+91 98765 43210", "pii@example.test")
    cols = {
        r[0]
        for r in db_tx.execute(
            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'customers_pii'")
        )
    }
    assert {"phone_primary", "phone_alt", "email", "address"}.isdisjoint(cols)
    row = db_tx.execute(
        text("SELECT phone_primary_enc, email_enc, address_enc FROM customers_pii WHERE id = :id"),
        {"id": cid},
    ).mappings().first()
    assert row is not None
    for cipher in row.values():
        assert isinstance(cipher, (bytes, memoryview))
        assert b"98765" not in bytes(cipher) and b"example.test" not in bytes(cipher)


def test_the_view_round_trips_through_the_key(db_tx) -> None:
    cid = _new_customer(db_tx, "+91 98765 43210", "pii@example.test")
    row = db_tx.execute(
        text("SELECT phone_primary, email, address FROM customers WHERE id = :id"), {"id": cid}
    ).mappings().first()
    assert dict(row) == {
        "phone_primary": "+91 98765 43210",
        "email": "pii@example.test",
        "address": "12 Test Lane",
    }
    db_tx.execute(
        text("UPDATE customers SET phone_primary = :p, name = 'Renamed' WHERE id = :id"),
        {"id": cid, "p": "+91 91111 22222"},
    )
    again = db_tx.execute(
        text("SELECT phone_primary, name FROM customers WHERE id = :id"), {"id": cid}
    ).mappings().first()
    assert again["phone_primary"] == "+91 91111 22222" and again["name"] == "Renamed"
    db_tx.execute(text("DELETE FROM customers WHERE id = :id"), {"id": cid})
    assert db_tx.execute(text("SELECT count(*) FROM customers_pii WHERE id = :id"), {"id": cid}).scalar() == 0


def test_a_session_without_the_key_reads_nothing_and_writes_nothing(db_tx) -> None:
    """Fail closed, like an unset tenant. The GUC is a startup parameter, so
    a session that lost it is a session that never had it; SET LOCAL to empty
    is the closest a test can come."""
    cid = _new_customer(db_tx, "+91 98765 43210", "pii@example.test")
    with db_tx.begin_nested():
        db_tx.execute(text("SET LOCAL app.pii_key = ''"))
        blind = db_tx.execute(
            text("SELECT phone_primary, email FROM customers WHERE id = :id"), {"id": cid}
        ).mappings().first()
        assert blind["phone_primary"] is None and blind["email"] is None
        with pytest.raises(Exception, match="pii_key_unset"):
            with db_tx.begin_nested():
                _new_customer(db_tx, "+91 90000 00000", "blind@example.test")


def test_a_phone_lookup_uses_the_hmac_index(db_tx) -> None:
    cid = _new_customer(db_tx, "+91 98765 43210", "pii@example.test")
    # 22 rows on a dev book: the planner prefers a scan. Turn that off (for
    # this transaction only) to prove the predicate is index-shaped, which is
    # what matters at scale.
    db_tx.execute(text("SET LOCAL enable_seqscan = off"))
    plan = "\n".join(
        r[0]
        for r in db_tx.execute(
            text(
                "EXPLAIN SELECT id FROM customers c WHERE c.phone_primary_hmac = pii_phone_hmac('919876543210')"
            )
        )
    )
    db_tx.execute(text("SET LOCAL enable_seqscan = on"))
    assert "idx_customers_phone_primary_hmac" in plan, plan

    import db_inbox

    found = db_inbox.find_customer_by_phone("919876543210")
    assert found is not None and found["id"] == cid


def test_rls_still_isolates_through_the_view(db_tx) -> None:
    import rls

    status = rls.status(db_tx)
    assert "customers_pii" not in status["missing_policy"]
    assert db_tx.execute(
        text("SELECT count(*) FROM pg_policy WHERE polrelid = 'customers_pii'::regclass")
    ).scalar() >= 1
    security_invoker = db_tx.execute(
        text(
            "SELECT 'security_invoker=true' = ANY(reloptions) FROM pg_class "
            "WHERE relname = 'customers' AND relkind = 'v'"
        )
    ).scalar()
    assert security_invoker is True
