"""Operator access requests: ask for a page, admin grants a role."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from db_core import _actor_user_id, _id, _tenant
import db_users

_STATUSES = frozenset({"pending", "approved", "denied"})


def _db():
    import db as d

    return d


def _iso(value: Any) -> str | None:
    return db_users._iso(value)


def permission_label(permission: str | None) -> str | None:
    if not permission:
        return None
    import authz

    for pid, _module, _action, description in authz.PERMISSION_CATALOG:
        if pid == permission:
            return description
    return permission.removeprefix("perm-").replace("-", " ")


def normalize_page_path(raw: str) -> str:
    path = (raw or "").strip()
    if (
        not path.startswith("/")
        or "://" in path
        or any(ch.isspace() for ch in path)
        or len(path) > 200
    ):
        raise ValueError("invalid_path")
    return path


def normalize_permission(raw: str | None) -> str | None:
    perm = (raw or "").strip()
    if not perm:
        return None
    if not perm.startswith("perm-") or len(perm) > 80 or any(ch.isspace() for ch in perm):
        raise ValueError("invalid_permission")
    return perm


def normalize_reason(raw: str) -> str:
    reason = (raw or "").strip()
    if len(reason) < 8 or len(reason) > 500:
        raise ValueError("invalid_reason")
    return reason


def _row(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "userId": str(row["user_id"]),
        "userName": row["user_name"],
        "userEmail": row["user_email"],
        "pagePath": row["page_path"],
        "permission": row["permission"],
        "permissionLabel": permission_label(row["permission"]),
        "reason": row["reason"],
        "status": row["status"],
        "grantedRoleId": str(row["granted_role_id"]) if row["granted_role_id"] else None,
        "grantedRoleName": row["granted_role_name"],
        "requestedAt": _iso(row["requested_at"]),
        "reviewedAt": _iso(row["reviewed_at"]),
        "reviewedByUserId": row["reviewed_by_user_id"],
        "reviewedByName": row["reviewed_by_name"],
        "lastError": row["last_error"],
    }


_SELECT = """
SELECT r.id, r.user_id, u.name AS user_name,
       coalesce(u.email, u.entra_upn) AS user_email,
       r.page_path, r.permission, r.reason, r.status,
       r.granted_role_id, g.name AS granted_role_name,
       r.requested_at, r.reviewed_at, r.reviewed_by_user_id,
       rv.name AS reviewed_by_name, r.last_error
  FROM operator_access_requests r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN roles g ON g.id = r.granted_role_id
  LEFT JOIN users rv ON rv.id = r.reviewed_by_user_id
"""


def list_access_requests() -> dict[str, Any]:
    try:
        with _db().engine.connect() as conn:
            rows = conn.execute(
                text(
                    _SELECT
                    + """
                     WHERE r.tenant_id = :t
                     ORDER BY CASE r.status WHEN 'pending' THEN 0 ELSE 1 END,
                              r.requested_at DESC, r.id
                    """
                ),
                {"t": _tenant()},
            ).mappings().all()
    except ProgrammingError:
        return {"requests": []}
    return {"requests": [_row(r) for r in rows]}


def _load_one(conn: Any, request_id: str) -> Any:
    return conn.execute(
        text(_SELECT + " WHERE r.tenant_id = :t AND r.id = :id"),
        {"t": _tenant(), "id": request_id},
    ).mappings().first()


def _admin_mailboxes(conn: Any, *, exclude_user_id: str | None) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for uid in db_users._active_admin_ids(conn):
        if exclude_user_id and uid == exclude_user_id:
            continue
        row = conn.execute(
            text(
                """
                SELECT name, coalesce(email, entra_upn) AS email
                  FROM users WHERE id = :id
                """
            ),
            {"id": uid},
        ).mappings().first()
        if row is None:
            continue
        email = (row["email"] or "").strip().lower()
        if not email or "@" not in email or email in seen:
            continue
        seen.add(email)
        out.append((email, str(row["name"] or "")))
    return out


def _notify(
    *,
    requester_name: str,
    requester_email: str | None,
    page_path: str,
    permission: str | None,
    reason: str,
    mailboxes: list[tuple[str, str]],
) -> str | None:
    if not mailboxes:
        return "no_admin_mailbox"
    import invite_mail

    last: str | None = None
    for email, _name in mailboxes:
        err = invite_mail.send_access_request_email(
            to_email=email,
            requester_name=requester_name,
            requester_email=requester_email,
            page_path=page_path,
            permission_label=permission_label(permission),
            reason=reason,
        )
        if err:
            last = err
    return last


def create_access_request(
    page_path: str, reason: str, permission: str | None = None
) -> dict[str, Any]:
    actor = (_actor_user_id() or "").strip()
    if not actor:
        raise ValueError("actor_required")
    wanted_path = normalize_page_path(page_path)
    wanted_reason = normalize_reason(reason)
    wanted_perm = normalize_permission(permission)
    try:
        return _insert_access_request(actor, wanted_path, wanted_reason, wanted_perm)
    except ProgrammingError:
        raise ValueError("access_requests_unavailable") from None
    except IntegrityError:
        raise ValueError("already_pending") from None


def _insert_access_request(
    actor: str, wanted_path: str, wanted_reason: str, wanted_perm: str | None
) -> dict[str, Any]:
    with _db().engine.begin() as conn:
        user = conn.execute(
            text(
                """
                SELECT id, name, coalesce(email, entra_upn) AS email
                  FROM users
                 WHERE tenant_id = :t AND id = :id AND entra_oid IS NOT NULL
                """
            ),
            {"t": _tenant(), "id": actor},
        ).mappings().first()
        if user is None:
            raise KeyError("user_not_found")
        existing = conn.execute(
            text(
                """
                SELECT id FROM operator_access_requests
                 WHERE tenant_id = :t AND user_id = :uid AND page_path = :path
                   AND status = 'pending'
                 LIMIT 1
                """
            ),
            {"t": _tenant(), "uid": actor, "path": wanted_path},
        ).first()
        if existing is not None:
            raise ValueError("already_pending")
        rid = _id("AR")
        conn.execute(
            text(
                """
                INSERT INTO operator_access_requests (
                    id, tenant_id, user_id, page_path, permission, reason, status
                ) VALUES (
                    :id, :t, :uid, :path, :perm, :reason, 'pending'
                )
                """
            ),
            {
                "id": rid,
                "t": _tenant(),
                "uid": actor,
                "path": wanted_path,
                "perm": wanted_perm,
                "reason": wanted_reason,
            },
        )
        mailboxes = _admin_mailboxes(conn, exclude_user_id=actor)
        last_error = _notify(
            requester_name=str(user["name"] or ""),
            requester_email=user["email"],
            page_path=wanted_path,
            permission=wanted_perm,
            reason=wanted_reason,
            mailboxes=mailboxes,
        )
        if last_error:
            conn.execute(
                text(
                    """
                    UPDATE operator_access_requests
                       SET last_error = :err, updated_at = now()
                     WHERE id = :id
                    """
                ),
                {"id": rid, "err": last_error},
            )
        loaded = _load_one(conn, rid)
    return {"request": _row(loaded)}


def approve_access_request(request_id: str, role_id: str) -> dict[str, Any]:
    rid = (request_id or "").strip()
    actor = (_actor_user_id() or "").strip()
    with _db().engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, user_id, status
                  FROM operator_access_requests
                 WHERE tenant_id = :t AND id = :id
                 FOR UPDATE
                """
            ),
            {"t": _tenant(), "id": rid},
        ).mappings().first()
        if row is None:
            raise KeyError("request_not_found")
        if row["status"] != "pending":
            raise ValueError("request_not_pending")
        role = db_users._load_role(conn, role_id)
        if role is None:
            raise ValueError(f"unknown_role:{role_id}")
        target = str(row["user_id"])
        target_status = conn.execute(
            text("SELECT status FROM users WHERE id = :id"),
            {"id": target},
        ).scalar()
        current = [
            str(r[0])
            for r in conn.execute(
                text("SELECT role_id FROM user_roles WHERE user_id = :id ORDER BY role_id"),
                {"id": target},
            )
        ]
        if str(role["id"]) not in current:
            current.append(str(role["id"]))
    db_users.replace_user_roles(target, current)
    if str(target_status or "") != "active":
        db_users.patch_user_status(target, "active")
    with _db().engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE operator_access_requests
                   SET status = 'approved',
                       granted_role_id = :role,
                       reviewed_at = now(),
                       reviewed_by_user_id = :actor,
                       updated_at = now()
                 WHERE id = :id AND status = 'pending'
                """
            ),
            {"id": rid, "role": str(role["id"]), "actor": actor or None},
        )
        loaded = _load_one(conn, rid)
    return {"request": _row(loaded)}


def deny_access_request(request_id: str) -> dict[str, Any]:
    rid = (request_id or "").strip()
    actor = (_actor_user_id() or "").strip()
    with _db().engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, status
                  FROM operator_access_requests
                 WHERE tenant_id = :t AND id = :id
                 FOR UPDATE
                """
            ),
            {"t": _tenant(), "id": rid},
        ).mappings().first()
        if row is None:
            raise KeyError("request_not_found")
        if row["status"] != "pending":
            raise ValueError("request_not_pending")
        conn.execute(
            text(
                """
                UPDATE operator_access_requests
                   SET status = 'denied',
                       reviewed_at = now(),
                       reviewed_by_user_id = :actor,
                       updated_at = now()
                 WHERE id = :id
                """
            ),
            {"id": rid, "actor": actor or None},
        )
        loaded = _load_one(conn, rid)
    return {"request": _row(loaded)}
