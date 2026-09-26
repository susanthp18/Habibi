"""Revocable per-user credentials for the Voice Studio authoring MCP gateway."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text


SCOPES = frozenset({"studio.read", "studio.edit"})


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _audit(conn: Any, actor: str, key_id: str, action: str) -> None:
    import db
    from agent_core import change_log

    change_log.record_agentstudio_change(
        conn, tenant_id=db.current_tenant(), actor_user_id=actor,
        entry_id=f"as-{uuid.uuid4().hex}", method="POST",
        path=f"/studio-mcp/keys/{key_id}/{action}", status=200,
    )


def mint(actor: str, *, name: str, scopes: list[str], days: int,
         rotated_from: str | None = None) -> dict[str, Any]:
    import db

    chosen = sorted(set(scopes))
    if not chosen or set(chosen) - SCOPES:
        raise ValueError("Choose studio.read and/or studio.edit")
    if not 1 <= days <= 90:
        raise ValueError("Key expiry must be between 1 and 90 days")
    label = name.strip()
    if not 1 <= len(label) <= 100:
        raise ValueError("Key name must be 1 to 100 characters")
    key_id = f"vsm-{uuid.uuid4().hex}"
    secret = f"vsm_{secrets.token_urlsafe(32)}"
    expiry = datetime.now(timezone.utc) + timedelta(days=days)
    with db.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO voice_studio_mcp_keys
              (id, tenant_id, user_id, name, key_hash, key_prefix, scopes, expires_at, rotated_from)
            VALUES (:id, :tenant, :user, :name, :hash, :prefix, :scopes, :expiry, :rotated)
        """), {"id": key_id, "tenant": db.current_tenant(), "user": actor,
               "name": label, "hash": _digest(secret), "prefix": secret[:8],
               "scopes": chosen, "expiry": expiry, "rotated": rotated_from})
        _audit(conn, actor, key_id, "created")
    return {"id": key_id, "name": label, "scopes": chosen, "key": secret,
            "prefix": secret[:8], "expiresAt": expiry.isoformat()}


def authenticate(raw: str | None) -> dict[str, Any] | None:
    import db

    secret = (raw or "").strip()
    if not secret.startswith("vsm_") or len(secret) > 256:
        return None
    with db.engine.begin() as conn:
        row = conn.execute(text("""
            SELECT k.id, k.user_id, k.tenant_id, k.key_hash, k.scopes
            FROM voice_studio_mcp_keys k
            JOIN users u ON u.id = k.user_id AND u.tenant_id = k.tenant_id
            WHERE k.key_hash = :hash AND k.tenant_id = :tenant
              AND k.revoked_at IS NULL AND k.expires_at > now() AND u.status = 'active'
        """), {"hash": _digest(secret), "tenant": db.current_tenant()}).mappings().first()
        if row is None or not hmac.compare_digest(row["key_hash"], _digest(secret)):
            return None
        conn.execute(text("UPDATE voice_studio_mcp_keys SET last_used_at = now() WHERE id = :id"),
                     {"id": row["id"]})
    return {"id": row["id"], "userId": row["user_id"], "tenantId": row["tenant_id"],
            "scopes": list(row["scopes"] or [])}


def list_keys(actor: str) -> list[dict[str, Any]]:
    import db

    with db.engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, name, key_prefix, scopes, expires_at, created_at, last_used_at, revoked_at
            FROM voice_studio_mcp_keys WHERE tenant_id = :tenant AND user_id = :user
            ORDER BY created_at DESC
        """), {"tenant": db.current_tenant(), "user": actor}).mappings().all()
    return [{"id": r["id"], "name": r["name"], "prefix": r["key_prefix"],
             "scopes": list(r["scopes"] or []), "expiresAt": r["expires_at"].isoformat(),
             "createdAt": r["created_at"].isoformat(),
             "lastUsedAt": r["last_used_at"].isoformat() if r["last_used_at"] else None,
             "revoked": r["revoked_at"] is not None} for r in rows]


def revoke(actor: str, key_id: str) -> None:
    import db

    with db.engine.begin() as conn:
        row = conn.execute(text("""
            UPDATE voice_studio_mcp_keys SET revoked_at = now()
            WHERE id = :id AND tenant_id = :tenant AND user_id = :user AND revoked_at IS NULL
            RETURNING id
        """), {"id": key_id, "tenant": db.current_tenant(), "user": actor}).first()
        if row is None:
            raise KeyError("studio_mcp_key_not_found")
        _audit(conn, actor, key_id, "revoked")


def rotate(actor: str, key_id: str) -> dict[str, Any]:
    import db

    replacement_id = f"vsm-{uuid.uuid4().hex}"
    secret = f"vsm_{secrets.token_urlsafe(32)}"
    with db.engine.begin() as conn:
        row = conn.execute(text("""
            SELECT name, scopes, expires_at FROM voice_studio_mcp_keys
            WHERE id = :id AND tenant_id = :tenant AND user_id = :user AND revoked_at IS NULL
            FOR UPDATE
        """), {"id": key_id, "tenant": db.current_tenant(), "user": actor}).mappings().first()
        if row is None:
            raise KeyError("studio_mcp_key_not_found")
        if row["expires_at"] <= datetime.now(timezone.utc):
            raise ValueError("expired_key_cannot_rotate")
        conn.execute(text("""
            INSERT INTO voice_studio_mcp_keys
              (id, tenant_id, user_id, name, key_hash, key_prefix, scopes, expires_at, rotated_from)
            VALUES (:id, :tenant, :user, :name, :hash, :prefix, :scopes, :expiry, :old)
        """), {"id": replacement_id, "tenant": db.current_tenant(), "user": actor,
               "name": row["name"], "hash": _digest(secret), "prefix": secret[:8],
               "scopes": list(row["scopes"] or []), "expiry": row["expires_at"],
               "old": key_id})
        conn.execute(text("UPDATE voice_studio_mcp_keys SET revoked_at = now() WHERE id = :id"),
                     {"id": key_id})
        _audit(conn, actor, key_id, "rotated")
        _audit(conn, actor, replacement_id, "created")
    return {"id": replacement_id, "name": row["name"], "scopes": list(row["scopes"] or []),
            "key": secret, "prefix": secret[:8], "expiresAt": row["expires_at"].isoformat()}
