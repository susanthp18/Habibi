"""First-login provision: bootstrap Admin vs Viewer. Requires entra columns."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import authz
import entra

TID = "9f2e2b7d-6081-4b3a-b7f5-433b581f6a5f"


def _ensure_schema(conn) -> None:
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_oid UUID"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_tid UUID"))
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS entra_upn TEXT"))
    conn.execute(
        text("ALTER TABLE users ADD COLUMN IF NOT EXISTS bootstrap_admin boolean NOT NULL DEFAULT false")
    )
    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at timestamptz"))
    conn.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_entra_oid "
            "ON users (entra_oid) WHERE entra_oid IS NOT NULL"
        )
    )
    tenant = conn.execute(text("SELECT id FROM tenants ORDER BY created_at LIMIT 1")).scalar()
    if tenant:
        conn.execute(
            text(
                """
                INSERT INTO roles (id, tenant_id, name)
                SELECT 'role-viewer', :t, 'Viewer'
                WHERE NOT EXISTS (SELECT 1 FROM roles WHERE id = 'role-viewer')
                """
            ),
            {"t": tenant},
        )


def _claims(*, oid: str, upn: str, name: str) -> dict:
    return {
        "oid": oid,
        "tid": TID,
        "preferred_username": upn,
        "name": name,
        "ver": "2.0",
        "scp": "access_as_user",
    }


def test_first_login_bootstrap_upn_becomes_admin(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_TENANT_ID", TID)
    monkeypatch.setenv("ENTRA_API_AUDIENCE", "8b5d91de-0bc3-4763-9bcd-809f42f9f003")
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    oid = str(uuid.uuid4())
    user_id = entra.provision_user(
        _claims(oid=oid, upn="Susanth.P@bigtapp.ai", name="Susanth P")
    )
    assert user_id == oid
    row = db_tx.execute(
        text("SELECT name, bootstrap_admin, entra_upn FROM users WHERE id = :id"),
        {"id": user_id},
    ).mappings().one()
    assert row["bootstrap_admin"] is True
    assert row["name"] == "Susanth P"
    roles = {
        r[0]
        for r in db_tx.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": user_id},
        )
    }
    assert "Admin" in roles
    assert authz.ADMIN_WRITE in authz.actor_permissions(user_id)


def test_first_login_other_member_is_viewer(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    oid = str(uuid.uuid4())
    user_id = entra.provision_user(
        _claims(oid=oid, upn="alex@bigtapp.ai", name="Alex Example")
    )
    roles = {
        r[0]
        for r in db_tx.execute(
            text(
                "SELECT r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id "
                "WHERE ur.user_id = :id"
            ),
            {"id": user_id},
        )
    }
    assert roles == {"Viewer"}
    perms = authz.actor_permissions(user_id)
    assert perms == authz.ROLE_DEFAULTS["viewer"]
    assert authz.CUSTOMERS_READ not in perms
    assert authz.VOICE_OPERATE not in perms
    assert authz.ADMIN_WRITE not in perms
    assert authz.PII_RAW_READ not in perms


def test_second_login_does_not_change_roles(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    oid = str(uuid.uuid4())
    claims = _claims(oid=oid, upn="alex@bigtapp.ai", name="Alex Example")
    entra.provision_user(claims)
    entra.provision_user({**claims, "name": "Alex Renamed", "preferred_username": "alex@bigtapp.ai"})
    row = db_tx.execute(
        text("SELECT name, entra_upn FROM users WHERE entra_oid = CAST(:oid AS uuid)"),
        {"oid": oid},
    ).mappings().one()
    assert row["name"] == "Alex Renamed"
    roles = [
        r[0]
        for r in db_tx.execute(
            text("SELECT role_id FROM user_roles WHERE user_id = :id"),
            {"id": oid},
        )
    ]
    assert roles == ["role-viewer"] or all("viewer" in r.lower() for r in roles)


def test_inactive_oid_is_refused(db_tx) -> None:
    _ensure_schema(db_tx)
    oid = str(uuid.uuid4())
    entra.provision_user(_claims(oid=oid, upn="parked@bigtapp.ai", name="Parked"))
    db_tx.execute(text("UPDATE users SET status = 'inactive' WHERE id = :id"), {"id": oid})
    with pytest.raises(entra.EntraAuthError):
        entra.provision_user(_claims(oid=oid, upn="parked@bigtapp.ai", name="Parked"))
