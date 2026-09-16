"""People admin: last-Admin protection and directory listing."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import authz
import db_users
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


def _provision(upn: str, name: str, *, bootstrap: bool = False) -> str:
    oid = str(uuid.uuid4())
    return entra.provision_user(
        {
            "oid": oid,
            "tid": TID,
            "preferred_username": upn,
            "name": name,
            "ver": "2.0",
            "scp": "access_as_user",
        }
    )


def _inactivate_everyone_else(keep_id: str) -> None:
    for user in db_users.list_directory_users()["users"]:
        if user["id"] == keep_id or user["status"] != "active":
            continue
        if user["bootstrapAdmin"]:
            continue
        db_users.patch_user_status(user["id"], "inactive")


def test_last_admin_cannot_be_demoted(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    admin_id = _provision("susanth.p@bigtapp.ai", "Susanth P", bootstrap=True)
    _inactivate_everyone_else(admin_id)
    with pytest.raises(ValueError, match="bootstrap_admin_protected"):
        db_users.replace_user_roles(admin_id, ["role-viewer"])


def test_last_admin_cannot_be_deactivated(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    admin_id = _provision("susanth.p@bigtapp.ai", "Susanth P")
    _inactivate_everyone_else(admin_id)
    with pytest.raises(ValueError, match="bootstrap_admin_protected"):
        db_users.patch_user_status(admin_id, "inactive")


def test_second_admin_cannot_demote_bootstrap(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    bootstrap_id = _provision("susanth.p@bigtapp.ai", "Susanth P")
    other_id = _provision("other@bigtapp.ai", "Other Person")
    db_users.replace_user_roles(other_id, ["role-admin"])
    authz.invalidate_permission_cache()
    assert authz.ADMIN_WRITE in authz.actor_permissions(other_id)
    with pytest.raises(ValueError, match="bootstrap_admin_protected"):
        db_users.replace_user_roles(bootstrap_id, ["role-viewer"])
    authz.invalidate_permission_cache(bootstrap_id)
    assert authz.ADMIN_WRITE in authz.actor_permissions(bootstrap_id)
    assert authz.ADMIN_WRITE in authz.actor_permissions(other_id)


def test_second_admin_cannot_deactivate_bootstrap(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    bootstrap_id = _provision("susanth.p@bigtapp.ai", "Susanth P")
    other_id = _provision("other@bigtapp.ai", "Other Person")
    db_users.replace_user_roles(other_id, ["role-admin"])
    with pytest.raises(ValueError, match="bootstrap_admin_protected"):
        db_users.patch_user_status(bootstrap_id, "inactive")


def test_last_granted_admin_cannot_be_demoted(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "nobody@example.com")
    admin_id = _provision("solo-admin@bigtapp.ai", "Solo Admin")
    db_users.replace_user_roles(admin_id, ["role-admin"])
    authz.invalidate_permission_cache(admin_id)
    _inactivate_everyone_else(admin_id)
    with db_users._db().engine.begin() as conn:
        holders = db_users._active_admin_ids(conn)
    if holders - {admin_id}:
        pytest.skip("other Entra admins already exist in this database")
    with pytest.raises(ValueError, match="last_admin"):
        db_users.replace_user_roles(admin_id, ["role-viewer"])


def test_list_users_includes_roles_not_extra_pii(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    user_id = _provision("alex@bigtapp.ai", "Alex Example")
    body = db_users.list_directory_users()
    match = next(u for u in body["users"] if u["id"] == user_id)
    assert match["name"] == "Alex Example"
    assert match["upn"] == "alex@bigtapp.ai"
    assert "Viewer" in match["roleNames"]
    assert match["email"] == "alex@bigtapp.ai"
    assert set(match) <= {
        "id",
        "name",
        "email",
        "upn",
        "status",
        "bootstrapAdmin",
        "lastLoginAt",
        "roleIds",
        "roleNames",
    }


def test_directory_omits_seed_users_without_entra_oid(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")
    sso_id = _provision("alex@bigtapp.ai", "Alex Example")
    body = db_users.list_directory_users()
    ids = {u["id"] for u in body["users"]}
    assert sso_id in ids
    assert "priya-nair" not in ids


def test_me_permissions_match_authz(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    import actor_context
    import db

    _ensure_schema(db_tx)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "nobody@example.com")
    user_id = _provision("alex@bigtapp.ai", "Alex Example")
    token = actor_context.set_actor_user_id(user_id)
    try:
        me = db.get_current_user()
    finally:
        actor_context.reset_actor_user_id(token)
    assert me["name"] == "Alex Example"
    assert set(me["permissions"]) == set(authz.actor_permissions(user_id))
    assert set(me["permissions"]) == set(authz.ROLE_DEFAULTS["viewer"])
