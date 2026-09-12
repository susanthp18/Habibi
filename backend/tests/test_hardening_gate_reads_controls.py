"""The hardening gate reads the database, not a list.

`_DEFERRED_HARDENING_CONTROLS` named "RLS tenant isolation" as deferred after
RLS was on -- a gate that reads a constant cannot notice the constant is
stale, and every HABIBI_DEPLOYED=1 process refused to boot for a control that
was enforced. The gate now asks rls.status(), pg_trigger and, for PII column
encryption, pg_extension plus the shape of `customers` (a view over
`customers_pii`) plus the key on this process's connections.
"""

from __future__ import annotations

import pytest


def test_the_gate_lists_only_what_the_database_does_not_enforce(monkeypatch) -> None:
    import main
    import rls

    import pii_key

    inactive = main._inactive_hardening_controls()
    with main.db.engine.connect() as conn:
        status = rls.status(conn)
        trigger = conn.execute(
            main.text("SELECT 1 FROM pg_trigger WHERE tgname = 'audit_log_append_only'")
        ).scalar()
        view = conn.execute(
            main.text(
                "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relname = 'customers' AND c.relkind = 'v'"
            )
        ).scalar()
        keyed = conn.execute(main.text("SELECT current_setting('app.pii_key', true) <> ''")).scalar()
    rls_listed = any(item.startswith("RLS tenant isolation") for item in inactive)
    assert rls_listed == bool(
        status["role_bypasses_rls"] or not status["enforcing"] or status["missing_policy"]
    )
    assert any("append-only" in item for item in inactive) == (not trigger)
    pii_listed = any(item.startswith("PII column encryption") for item in inactive)
    assert pii_listed == (not view or not pii_key.configured() or not keyed)


def test_the_gate_lists_pii_when_the_key_is_missing(monkeypatch) -> None:
    import main
    import pii_key

    monkeypatch.setattr(pii_key, "configured", lambda: False)
    inactive = main._inactive_hardening_controls()
    assert any("PII_ENCRYPTION_KEY" in item or "customers_pii" in item for item in inactive)


def test_a_deployed_process_refuses_with_the_real_reasons(monkeypatch) -> None:
    import main

    monkeypatch.setenv("HABIBI_DEPLOYED", "1")
    monkeypatch.setattr(main, "_inactive_hardening_controls", lambda: ["RLS tenant isolation (probe)"])
    with pytest.raises(RuntimeError, match="RLS tenant isolation \(probe\)"):
        main._assert_hardening_gate()
    monkeypatch.setattr(main, "_inactive_hardening_controls", lambda: [])
    main._assert_hardening_gate()  # every control active: a deployed boot is allowed


def test_the_application_role_cannot_rewrite_the_audit_log(db_tx) -> None:
    import db
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    role = db_tx.execute(text("SELECT current_user")).scalar()
    if role != "collections_app":
        pytest.skip("the append-only trigger exempts the owner; this runs as the app role")
    entry = db_tx.execute(
        text("SELECT id FROM audit_log WHERE tenant_id = :t LIMIT 1"), {"t": db.current_tenant()}
    ).scalar()
    if not entry:
        pytest.skip("no audit rows to protect")
    nested = db_tx.begin_nested()
    with pytest.raises(DBAPIError, match="append-only"):
        db_tx.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry})
    nested.rollback()


def test_the_gate_lists_the_public_origin_when_it_is_unset(monkeypatch) -> None:
    """`payments.public_base_url` fell back to `http://127.0.0.1:8000`, so a
    deployed process with PUBLIC_BASE_URL unset minted pay links that pointed
    at itself. The gate names it, like the other controls."""
    import main

    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert any(item.startswith("public origin") for item in main._inactive_hardening_controls())
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://collections.example.bank")
    assert not any(item.startswith("public origin") for item in main._inactive_hardening_controls())
