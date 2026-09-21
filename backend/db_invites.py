"""Operator invites: persist, resend, revoke, consume on first Entra login."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from db_core import _actor_user_id, _id, _tenant
import db_users

ALLOWED_EMAIL_SUFFIX = "@bigtapp.ai"


def _db():
    import db as d

    return d


def _iso(value: Any) -> str | None:
    return db_users._iso(value)


def normalize_invite_email(raw: str) -> str:
    email = (raw or "").strip().lower()
    if email.count("@") != 1 or not email.endswith(ALLOWED_EMAIL_SUFFIX):
        raise ValueError("invalid_email")
    local = email[: -len(ALLOWED_EMAIL_SUFFIX)]
    if not local or any(ch.isspace() for ch in email):
        raise ValueError("invalid_email")
    return email


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "email": row["email"],
        "roleId": str(row["role_id"]),
        "roleName": row["role_name"],
        "status": row["status"],
        "invitedByUserId": row["invited_by_user_id"],
        "invitedByName": row["invited_by_name"],
        "sentAt": _iso(row["sent_at"]),
        "acceptedAt": _iso(row["accepted_at"]),
        "lastError": row["last_error"],
    }


def list_invites() -> dict[str, Any]:
    try:
        with _db().engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT i.id, i.email, i.role_id, r.name AS role_name, i.status,
                           i.invited_by_user_id, u.name AS invited_by_name,
                           i.sent_at, i.accepted_at, i.last_error
                      FROM operator_invites i
                      JOIN roles r ON r.id = i.role_id
                      LEFT JOIN users u ON u.id = i.invited_by_user_id
                     WHERE i.tenant_id = :t
                     ORDER BY i.sent_at DESC, i.id
                    """
                ),
                {"t": _tenant()},
            ).mappings().all()
    except ProgrammingError:
        return {"invites": []}
    return {"invites": [_row(r) for r in rows]}


def _load_one(conn: Any, invite_id: str) -> Any:
    return conn.execute(
        text(
            """
            SELECT i.id, i.email, i.role_id, r.name AS role_name, i.status,
                   i.invited_by_user_id, u.name AS invited_by_name,
                   i.sent_at, i.accepted_at, i.last_error
              FROM operator_invites i
              JOIN roles r ON r.id = i.role_id
              LEFT JOIN users u ON u.id = i.invited_by_user_id
             WHERE i.tenant_id = :t AND i.id = :id
            """
        ),
        {"t": _tenant(), "id": invite_id},
    ).mappings().first()


def _operator_for_email(conn: Any, email: str) -> Any:
    return conn.execute(
        text(
            """
            SELECT u.id, u.status,
                   EXISTS (
                       SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id
                   ) AS has_role
              FROM users u
             WHERE u.tenant_id = :t
               AND u.entra_oid IS NOT NULL
               AND lower(coalesce(u.entra_upn, u.email, '')) = :email
             LIMIT 1
            """
        ),
        {"t": _tenant(), "email": email},
    ).mappings().first()


def _invite_blocked(row: Any) -> bool:
    """Active operators who already hold a role cannot be invited again."""
    if row is None:
        return False
    if str(row["status"] or "") != "active":
        return False
    return bool(row["has_role"])


def apply_invite_role(conn: Any, user_id: str, role_id: str, *, activate: bool) -> None:
    """Grant the invite role. Inactive operators are a fresh grant, not a merge."""
    if activate:
        conn.execute(
            text("UPDATE users SET status = 'active', updated_at = now() WHERE id = :id"),
            {"id": user_id},
        )
        conn.execute(text("DELETE FROM user_roles WHERE user_id = :id"), {"id": user_id})
    conn.execute(
        text(
            """
            INSERT INTO user_roles (user_id, role_id)
            VALUES (:uid, :rid)
            ON CONFLICT DO NOTHING
            """
        ),
        {"uid": user_id, "rid": role_id},
    )


def _send(email: str, role_name: str, inviter_name: str | None) -> str | None:
    import invite_mail

    return invite_mail.send_invite_email(
        to_email=email, role_name=role_name, inviter_name=inviter_name
    )


def create_invite(email: str, role_id: str) -> dict[str, Any]:
    wanted_email = normalize_invite_email(email)
    role_ref = (role_id or "").strip()
    actor = _actor_user_id()
    existing_id: str | None = None
    with _db().engine.begin() as conn:
        operator = _operator_for_email(conn, wanted_email)
        if _invite_blocked(operator):
            raise ValueError("already_signed_in")
        role = db_users._load_role(conn, role_ref)
        if role is None:
            raise ValueError(f"unknown_role:{role_ref}")
        inviter = conn.execute(
            text("SELECT name FROM users WHERE id = :id"),
            {"id": actor},
        ).mappings().first()
        inviter_name = str(inviter["name"]) if inviter else None
        pending = conn.execute(
            text(
                """
                SELECT id FROM operator_invites
                 WHERE tenant_id = :t AND lower(email) = :email AND status = 'pending'
                 LIMIT 1
                """
            ),
            {"t": _tenant(), "email": wanted_email},
        ).mappings().first()
        invite_id = str(pending["id"]) if pending else _id("INV")
        if pending is None:
            conn.execute(
                text(
                    """
                    INSERT INTO operator_invites (
                        id, tenant_id, email, role_id, invited_by_user_id, status, sent_at
                    ) VALUES (
                        :id, :t, :email, :rid, :actor, 'pending', now()
                    )
                    """
                ),
                {
                    "id": invite_id,
                    "t": _tenant(),
                    "email": wanted_email,
                    "rid": role["id"],
                    "actor": actor or None,
                },
            )
        else:
            conn.execute(
                text(
                    """
                    UPDATE operator_invites
                       SET role_id = :rid,
                           invited_by_user_id = :actor,
                           sent_at = now(),
                           last_error = NULL,
                           updated_at = now()
                     WHERE id = :id
                    """
                ),
                {"id": invite_id, "rid": role["id"], "actor": actor or None},
            )
        err = _send(wanted_email, str(role["name"]), inviter_name)
        conn.execute(
            text(
                """
                UPDATE operator_invites
                   SET last_error = :err, updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": invite_id, "err": err},
        )
        conn.execute(
            text(
                """
                INSERT INTO audit_log (
                    id, tenant_id, actor_user_id, action, entity_type, entity_id, payload
                ) VALUES (
                    :id, :t, :actor, 'user.invite', 'operator_invite', :uid,
                    CAST(:payload AS jsonb)
                )
                """
            ),
            {
                "id": _id("AUD"),
                "t": _tenant(),
                "actor": actor,
                "uid": invite_id,
                "payload": json.dumps(
                    {"email": wanted_email, "roleId": role["id"], "lastError": err}
                ),
            },
        )
        if operator is not None:
            existing_id = str(operator["id"])
            apply_invite_role(
                conn,
                existing_id,
                str(role["id"]),
                activate=str(operator["status"] or "") != "active",
            )
            conn.execute(
                text(
                    """
                    UPDATE operator_invites
                       SET status = 'accepted', accepted_at = now(), updated_at = now()
                     WHERE id = :id
                    """
                ),
                {"id": invite_id},
            )
        row = _load_one(conn, invite_id)
    if existing_id:
        import actor_context
        import authz

        authz.invalidate_permission_cache(existing_id)
        actor_context.invalidate_user_exists(existing_id)
    return {"invite": _row(row)}


def resend_invite(invite_id: str) -> dict[str, Any]:
    uid = (invite_id or "").strip()
    actor = _actor_user_id()
    with _db().engine.begin() as conn:
        row = _load_one(conn, uid)
        if row is None:
            raise KeyError("invite_not_found")
        if str(row["status"]) != "pending":
            raise ValueError("invite_not_pending")
        if _invite_blocked(_operator_for_email(conn, str(row["email"]).lower())):
            raise ValueError("already_signed_in")
        err = _send(str(row["email"]), str(row["role_name"]), row["invited_by_name"])
        conn.execute(
            text(
                """
                UPDATE operator_invites
                   SET sent_at = now(), last_error = :err, updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": uid, "err": err},
        )
        conn.execute(
            text(
                """
                INSERT INTO audit_log (
                    id, tenant_id, actor_user_id, action, entity_type, entity_id, payload
                ) VALUES (
                    :id, :t, :actor, 'user.invite.resend', 'operator_invite', :uid,
                    CAST(:payload AS jsonb)
                )
                """
            ),
            {
                "id": _id("AUD"),
                "t": _tenant(),
                "actor": actor,
                "uid": uid,
                "payload": json.dumps({"lastError": err}),
            },
        )
        row = _load_one(conn, uid)
    return {"invite": _row(row)}


def revoke_invite(invite_id: str) -> dict[str, Any]:
    uid = (invite_id or "").strip()
    actor = _actor_user_id()
    with _db().engine.begin() as conn:
        row = _load_one(conn, uid)
        if row is None:
            raise KeyError("invite_not_found")
        if str(row["status"]) != "pending":
            raise ValueError("invite_not_pending")
        conn.execute(
            text(
                """
                UPDATE operator_invites
                   SET status = 'revoked', updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": uid},
        )
        conn.execute(
            text(
                """
                INSERT INTO audit_log (
                    id, tenant_id, actor_user_id, action, entity_type, entity_id, payload
                ) VALUES (
                    :id, :t, :actor, 'user.invite.revoke', 'operator_invite', :uid,
                    CAST(:payload AS jsonb)
                )
                """
            ),
            {
                "id": _id("AUD"),
                "t": _tenant(),
                "actor": actor,
                "uid": uid,
                "payload": json.dumps({"email": row["email"]}),
            },
        )
        row = _load_one(conn, uid)
    return {"invite": _row(row)}


def consume_pending_invite(conn: Any, tenant_id: str, upn: str) -> str | None:
    """Mark a pending invite accepted and return its role_id. Missing table is a no-op."""
    email = (upn or "").strip().lower()
    if not email:
        return None
    nested = conn.begin_nested()
    try:
        row = conn.execute(
            text(
                """
                SELECT id, role_id FROM operator_invites
                 WHERE tenant_id = :t AND lower(email) = :email AND status = 'pending'
                 ORDER BY sent_at DESC
                 LIMIT 1
                 FOR UPDATE
                """
            ),
            {"t": tenant_id, "email": email},
        ).mappings().first()
        if row is None:
            nested.commit()
            return None
        conn.execute(
            text(
                """
                UPDATE operator_invites
                   SET status = 'accepted', accepted_at = now(), last_error = NULL,
                       updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": row["id"]},
        )
        nested.commit()
        return str(row["role_id"])
    except ProgrammingError:
        nested.rollback()
        return None
