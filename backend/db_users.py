"""Operator directory: people, role assignment, activation.

Peeled out of db.py so the Entra identity surface does not grow the CRM
kernel. Reach the engine through ``_db()`` so ``db_tx`` still wraps it.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from db_core import _actor_user_id, _id, _tenant
import authz


def _db():
    import db as d

    return d


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def list_directory_users() -> dict[str, Any]:
    """Every operator in the tenant: id, display, roles, bootstrap, last login."""
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT u.id, u.name, u.status, u.entra_upn, u.bootstrap_admin,
                       u.last_login_at, r.id AS role_id, r.name AS role_name
                  FROM users u
             LEFT JOIN user_roles ur ON ur.user_id = u.id
             LEFT JOIN roles r ON r.id = ur.role_id
                 WHERE u.tenant_id = :t
                 ORDER BY lower(u.name), u.id, r.name
                """
            ),
            {"t": _tenant()},
        ).mappings().all()
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows:
        uid = str(row["id"])
        if uid not in by_id:
            by_id[uid] = {
                "id": uid,
                "name": row["name"],
                "upn": row["entra_upn"],
                "status": row["status"],
                "bootstrapAdmin": bool(row["bootstrap_admin"]),
                "lastLoginAt": _iso(row["last_login_at"]),
                "roleIds": [],
                "roleNames": [],
            }
            order.append(uid)
        if row["role_id"]:
            rid = str(row["role_id"])
            if rid not in by_id[uid]["roleIds"]:
                by_id[uid]["roleIds"].append(rid)
                by_id[uid]["roleNames"].append(str(row["role_name"]))
    return {"users": [by_id[i] for i in order]}


def _load_role(conn: Any, role_ref: str) -> dict[str, Any] | None:
    return conn.execute(
        text(
            """
            SELECT r.id, r.name, r.configured_at
              FROM roles r
             WHERE r.tenant_id = :t AND (r.id = :id OR lower(r.name) = lower(:id))
             LIMIT 1
            """
        ),
        {"t": _tenant(), "id": role_ref},
    ).mappings().first()


def _explicit_grants(conn: Any, role_id: str) -> list[str]:
    return [
        str(row[0])
        for row in conn.execute(
            text("SELECT permission_id FROM role_permissions WHERE role_id = :id"),
            {"id": role_id},
        )
    ]


def _permissions_for_roles(conn: Any, role_ids: list[str]) -> frozenset[str]:
    granted: set[str] = set()
    for rid in role_ids:
        role = _load_role(conn, rid)
        if role is None:
            continue
        granted |= set(
            authz.resolve_role_grants(
                role["name"],
                _explicit_grants(conn, role["id"]),
                configured=role["configured_at"] is not None,
            )
        )
    return frozenset(granted)


def _active_admin_ids(conn: Any) -> set[str]:
    """Holders of perm-admin-write, computed on this connection (not the cache)."""
    user_rows = conn.execute(
        text("SELECT id FROM users WHERE tenant_id = :t AND status = 'active'"),
        {"t": _tenant()},
    )
    holders: set[str] = set()
    for (uid,) in user_rows:
        role_ids = [
            str(row[0])
            for row in conn.execute(
                text("SELECT role_id FROM user_roles WHERE user_id = :id"),
                {"id": uid},
            )
        ]
        if authz.ADMIN_WRITE in _permissions_for_roles(conn, role_ids):
            holders.add(str(uid))
    return holders


def _assert_not_last_admin(conn: Any, user_id: str, still_admin: bool) -> None:
    if still_admin:
        return
    holders = _active_admin_ids(conn)
    if user_id not in holders:
        return
    if not (holders - {user_id}):
        raise ValueError("last_admin")


def replace_user_roles(user_id: str, role_ids: list[str]) -> dict[str, Any]:
    """Replace the role set for one operator. Refuses emptying the last Admin."""
    uid = (user_id or "").strip()
    wanted_refs = [r.strip() for r in role_ids if r and str(r).strip()]
    actor = _actor_user_id()
    with _db().engine.begin() as conn:
        user = conn.execute(
            text(
                """
                SELECT id, bootstrap_admin, status FROM users
                 WHERE tenant_id = :t AND id = :id
                 FOR UPDATE
                """
            ),
            {"t": _tenant(), "id": uid},
        ).mappings().first()
        if user is None:
            raise KeyError("user_not_found")
        resolved: list[str] = []
        for ref in wanted_refs:
            role = _load_role(conn, ref)
            if role is None:
                raise ValueError(f"unknown_role:{ref}")
            if role["id"] not in resolved:
                resolved.append(str(role["id"]))
        new_perms = _permissions_for_roles(conn, resolved)
        still_admin = authz.ADMIN_WRITE in new_perms
        _assert_not_last_admin(conn, uid, still_admin)
        conn.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": uid})
        for rid in resolved:
            conn.execute(
                text(
                    """
                    INSERT INTO user_roles (user_id, role_id)
                    VALUES (:uid, :rid)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"uid": uid, "rid": rid},
            )
        conn.execute(
            text(
                """
                INSERT INTO audit_log (
                    id, tenant_id, actor_user_id, action, entity_type, entity_id, payload
                ) VALUES (
                    :id, :t, :actor, 'user.roles', 'user', :uid, CAST(:payload AS jsonb)
                )
                """
            ),
            {
                "id": _id("AUD"),
                "t": _tenant(),
                "actor": actor,
                "uid": uid,
                "payload": json.dumps({"roleIds": resolved, "bootstrapAdmin": bool(user["bootstrap_admin"])}),
            },
        )
    authz.invalidate_permission_cache(uid)
    return list_directory_users()


def patch_user_status(user_id: str, status: str) -> dict[str, Any]:
    """Activate or deactivate one operator. Same last-Admin rule as role replace."""
    uid = (user_id or "").strip()
    wanted = (status or "").strip().lower()
    if wanted not in {"active", "inactive"}:
        raise ValueError("invalid_status")
    actor = _actor_user_id()
    with _db().engine.begin() as conn:
        user = conn.execute(
            text(
                """
                SELECT id, status, bootstrap_admin FROM users
                 WHERE tenant_id = :t AND id = :id
                 FOR UPDATE
                """
            ),
            {"t": _tenant(), "id": uid},
        ).mappings().first()
        if user is None:
            raise KeyError("user_not_found")
        if wanted == "inactive":
            _assert_not_last_admin(conn, uid, still_admin=False)
        conn.execute(
            text("UPDATE users SET status = :s, updated_at = now() WHERE id = :id"),
            {"s": wanted, "id": uid},
        )
        conn.execute(
            text(
                """
                INSERT INTO audit_log (
                    id, tenant_id, actor_user_id, action, entity_type, entity_id, payload
                ) VALUES (
                    :id, :t, :actor, 'user.status', 'user', :uid, CAST(:payload AS jsonb)
                )
                """
            ),
            {
                "id": _id("AUD"),
                "t": _tenant(),
                "actor": actor,
                "uid": uid,
                "payload": json.dumps({"status": wanted, "previous": user["status"]}),
            },
        )
    authz.invalidate_permission_cache(uid)
    import actor_context

    actor_context.invalidate_user_exists(uid)
    return list_directory_users()
