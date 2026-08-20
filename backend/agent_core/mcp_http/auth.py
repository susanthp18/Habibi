"""Scoped MCP keys. Never 'all tools'. Writes stay denied regardless of scope."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from typing import Any

from sqlalchemy import text

import db

SCOPE_CRM_READ = "crm.read"
SCOPE_KB_SEARCH = "kb.search"
SCOPE_OFFERS_READ = "offers.read"
SCOPE_TASKS_WRITE = "tasks.write"
SCOPE_POLICY_READ = "policy.read"

ALL_READ = frozenset({SCOPE_CRM_READ, SCOPE_KB_SEARCH, SCOPE_OFFERS_READ, SCOPE_POLICY_READ})
KNOWN_SCOPES = ALL_READ | {SCOPE_TASKS_WRITE}

TOOL_SCOPES: dict[str, str] = {
    "get_customer_context": SCOPE_CRM_READ,
    "get_payment_history": SCOPE_CRM_READ,
    "get_emi_schedule": SCOPE_CRM_READ,
    "search_knowledge_base": SCOPE_KB_SEARCH,
    "check_product_eligibility": SCOPE_OFFERS_READ,
    "enqueue_task": SCOPE_TASKS_WRITE,
}

RESOURCE_SCOPES: dict[str, str] = {
    "customer": SCOPE_CRM_READ,
    "account": SCOPE_CRM_READ,
    "interaction": SCOPE_CRM_READ,
    "kb": SCOPE_KB_SEARCH,
    "policy": SCOPE_POLICY_READ,
}


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bootstrap_scopes() -> set[str]:
    return set(ALL_READ)


def authenticate(presented: str | None) -> dict[str, Any] | None:
    """Return principal {id, scopes} or None."""
    raw = (presented or "").strip()
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    if not raw:
        return None
    digest = hash_key(raw)
    env_key = (os.getenv("MCP_API_KEY") or "").strip()
    if env_key and hmac.compare_digest(hash_key(env_key), digest):
        return {"id": "env-bootstrap", "name": "MCP_API_KEY", "scopes": sorted(_bootstrap_scopes())}
    try:
        with db.engine.begin() as conn:
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT id, name, scopes FROM mcp_keys
                         WHERE key_hash = :h AND tenant_id = :t AND revoked_at IS NULL
                        """
                    ),
                    {"h": digest, "t": db._tenant()},
                )
            )
            if not row:
                return None
            conn.execute(text("UPDATE mcp_keys SET last_used_at = now() WHERE id = :id"), {"id": row["id"]})
    except Exception:
        return None
    scopes = list(row.get("scopes") or [])
    if hasattr(scopes, "tolist"):
        scopes = list(scopes)
    return {"id": row["id"], "name": row["name"], "scopes": [s for s in scopes if s in KNOWN_SCOPES]}


def tool_allowed(principal: dict[str, Any], tool_name: str) -> bool:
    need = TOOL_SCOPES.get(tool_name)
    if need is None:
        return False
    return need in set(principal.get("scopes") or [])


def resource_allowed(principal: dict[str, Any], scheme: str) -> bool:
    need = RESOURCE_SCOPES.get(scheme)
    if need is None:
        return False
    return need in set(principal.get("scopes") or [])


def mint_key(*, name: str, scopes: list[str]) -> dict[str, Any]:
    allowed = [s for s in scopes if s in KNOWN_SCOPES]
    if not allowed:
        raise ValueError("mcp_scopes_required")
    raw = "mcp_" + secrets.token_urlsafe(32)
    kid = f"mcpk-{uuid.uuid4().hex[:12]}"
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO mcp_keys (id, tenant_id, name, key_hash, key_prefix, scopes)
                VALUES (:id, :t, :name, :hash, :prefix, CAST(:scopes AS text[]))
                """
            ),
            {
                "id": kid,
                "t": db._tenant(),
                "name": name.strip() or kid,
                "hash": hash_key(raw),
                "prefix": raw[:7],
                "scopes": "{" + ",".join(allowed) + "}",
            },
        )
    return {"id": kid, "name": name, "scopes": allowed, "key": raw, "prefix": raw[:7]}


def list_keys() -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, key_prefix, scopes, revoked_at, last_used_at, created_at
                      FROM mcp_keys WHERE tenant_id = :t ORDER BY created_at DESC
                    """
                ),
                {"t": db._tenant()},
            )
        )
    out = []
    for r in rows:
        scopes = list(r.get("scopes") or [])
        if hasattr(scopes, "tolist"):
            scopes = list(scopes)
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "prefix": r["key_prefix"],
                "scopes": scopes,
                "revoked": r["revoked_at"] is not None,
                "lastUsedAt": str(r["last_used_at"]) if r.get("last_used_at") else None,
                "createdAt": str(r["created_at"]) if r.get("created_at") else None,
            }
        )
    return out


def revoke_key(key_id: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text("UPDATE mcp_keys SET revoked_at = now() WHERE id = :id AND tenant_id = :t"),
            {"id": key_id, "t": db._tenant()},
        )


def rotate_key(key_id: str) -> dict[str, Any]:
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT name, scopes FROM mcp_keys WHERE id = :id AND tenant_id = :t"),
                {"id": key_id, "t": db._tenant()},
            )
        )
    if not row:
        raise KeyError("mcp_key_not_found")
    revoke_key(key_id)
    scopes = list(row.get("scopes") or [])
    if hasattr(scopes, "tolist"):
        scopes = list(scopes)
    return mint_key(name=str(row["name"]), scopes=scopes)
