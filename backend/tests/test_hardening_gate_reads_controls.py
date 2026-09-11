"""The hardening gate reads the database, not a list.

`_DEFERRED_HARDENING_CONTROLS` named "RLS tenant isolation" as deferred after
RLS was on -- a gate that reads a constant cannot notice the constant is
stale, and every HABIBI_DEPLOYED=1 process refused to boot for a control that
was enforced. The gate now asks rls.status() and pg_trigger; PII column
encryption is the one control with no implementation, so a deployed boot
still refuses, honestly.
"""

from __future__ import annotations

import pytest


def test_the_gate_lists_only_what_the_database_does_not_enforce(monkeypatch) -> None:
    import main
    import rls

    inactive = main._inactive_hardening_controls()
    assert inactive[-1] == main._PII_ENCRYPTION_DEFERRED
    with main.db.engine.connect() as conn:
        status = rls.status(conn)
        trigger = conn.execute(
            main.text("SELECT 1 FROM pg_trigger WHERE tgname = 'audit_log_append_only'")
        ).scalar()
    rls_listed = any(item.startswith("RLS tenant isolation") for item in inactive)
    assert rls_listed == bool(
        status["role_bypasses_rls"] or not status["enforcing"] or status["missing_policy"]
    )
    assert any("append-only" in item for item in inactive) == (not trigger)


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
