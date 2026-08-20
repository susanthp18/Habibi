"""vault_refs persistence. Secrets never leave this module as API fields named token."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from sqlalchemy import text

import db
from agent_core.vault.seal import open_sealed, seal

logger = logging.getLogger(__name__)


def _azure_url() -> str:
    return (os.getenv("AZURE_KEY_VAULT_URL") or "").rstrip("/")


def list_refs() -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, purpose, backend, azure_secret_name,
                           last_rotated_at, last_used_at, created_at
                      FROM vault_refs
                     WHERE tenant_id = :t
                     ORDER BY name
                    """
                ),
                {"t": db._tenant()},
            )
        )
    return [_public(r) for r in rows]


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "purpose": row["purpose"],
        "backend": row["backend"],
        "azureSecretName": row.get("azure_secret_name"),
        "lastRotatedAt": str(row["last_rotated_at"]) if row.get("last_rotated_at") else None,
        "lastUsedAt": str(row["last_used_at"]) if row.get("last_used_at") else None,
        "createdAt": str(row["created_at"]) if row.get("created_at") else None,
        "hasSecret": True,
    }


def put_secret(
    *,
    name: str,
    purpose: str,
    secret: str,
    ref_id: str | None = None,
) -> dict[str, Any]:
    if not secret.strip():
        raise ValueError("vault_secret_required")
    if not name.strip():
        raise ValueError("vault_name_required")
    azure = _azure_url()
    backend = "azure" if azure else "local"
    rid = ref_id or f"vault-{uuid.uuid4().hex[:12]}"
    azure_name = None
    ciphertext = None
    if backend == "azure":
        azure_name = _put_azure(name, secret)
    else:
        ciphertext = seal(secret)
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO vault_refs (
                  id, tenant_id, name, purpose, backend, azure_secret_name, ciphertext, last_rotated_at
                ) VALUES (
                  :id, :t, :name, :purpose, :backend, :azure, :ct, now()
                )
                ON CONFLICT (tenant_id, name) DO UPDATE SET
                  purpose = EXCLUDED.purpose,
                  backend = EXCLUDED.backend,
                  azure_secret_name = EXCLUDED.azure_secret_name,
                  ciphertext = EXCLUDED.ciphertext,
                  last_rotated_at = now()
                """
            ),
            {
                "id": rid,
                "t": db._tenant(),
                "name": name.strip(),
                "purpose": purpose,
                "backend": backend,
                "azure": azure_name,
                "ct": ciphertext,
            },
        )
        row = db._one(
            conn.execute(
                text("SELECT * FROM vault_refs WHERE tenant_id = :t AND name = :n"),
                {"t": db._tenant(), "n": name.strip()},
            )
        )
    return _public(row)


def reveal(ref_id: str) -> str:
    """Return the secret. Callers must not put this on a JSON response."""
    with db.engine.begin() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM vault_refs WHERE id = :id AND tenant_id = :t"),
                {"id": ref_id, "t": db._tenant()},
            )
        )
        if not row:
            raise KeyError("vault_ref_not_found")
        conn.execute(
            text("UPDATE vault_refs SET last_used_at = now() WHERE id = :id"),
            {"id": ref_id},
        )
    if row["backend"] == "azure":
        return _get_azure(str(row.get("azure_secret_name") or row["name"]))
    if not row.get("ciphertext"):
        raise ValueError("vault_ciphertext_missing")
    return open_sealed(row["ciphertext"])


def rotate(ref_id: str, secret: str) -> dict[str, Any]:
    current = None
    with db.engine.connect() as conn:
        current = db._one(
            conn.execute(
                text("SELECT * FROM vault_refs WHERE id = :id AND tenant_id = :t"),
                {"id": ref_id, "t": db._tenant()},
            )
        )
    if not current:
        raise KeyError("vault_ref_not_found")
    return put_secret(name=current["name"], purpose=current["purpose"], secret=secret, ref_id=current["id"])


def _put_azure(name: str, secret: str) -> str:
    token = (os.getenv("AZURE_KEY_VAULT_TOKEN") or "").strip()
    url = _azure_url()
    if not token or not url:
        raise ValueError("azure_key_vault_not_configured")
    import httpx

    secret_name = name.replace(" ", "-")
    resp = httpx.put(
        f"{url}/secrets/{secret_name}?api-version=7.4",
        headers={"Authorization": f"Bearer {token}"},
        json={"value": secret},
        timeout=10.0,
    )
    resp.raise_for_status()
    return secret_name


def _get_azure(secret_name: str) -> str:
    token = (os.getenv("AZURE_KEY_VAULT_TOKEN") or "").strip()
    url = _azure_url()
    if not token or not url:
        raise ValueError("azure_key_vault_not_configured")
    import httpx

    resp = httpx.get(
        f"{url}/secrets/{secret_name}?api-version=7.4",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )
    resp.raise_for_status()
    value = resp.json().get("value")
    if not value:
        raise ValueError("azure_secret_empty")
    return str(value)
