"""Stable external-to-canonical identifiers, tenant-scoped."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from bank_boundary import schema_ready


def resolve(
    conn: Any,
    *,
    tenant_id: str,
    namespace: str,
    external_id: str,
) -> str | None:
    if not schema_ready.w5_ready(conn):
        return None
    return conn.execute(
        text(
            """
            SELECT canonical_id FROM bank_id_map
             WHERE tenant_id = :tid AND namespace = :ns AND external_id = :ext
            """
        ),
        {"tid": tenant_id, "ns": namespace, "ext": external_id},
    ).scalar()


def bind(
    conn: Any,
    *,
    tenant_id: str,
    namespace: str,
    external_id: str,
    canonical_id: str,
    canonical_table: str,
) -> str:
    existing = resolve(
        conn, tenant_id=tenant_id, namespace=namespace, external_id=external_id
    )
    if existing and existing != canonical_id:
        raise ValueError(f"id_collision:{namespace}:{external_id}")
    if existing:
        return existing
    conn.execute(
        text(
            """
            INSERT INTO bank_id_map (
              tenant_id, namespace, external_id, canonical_id, canonical_table
            ) VALUES (
              :tid, :ns, :ext, :cid, :tbl
            )
            ON CONFLICT (tenant_id, namespace, external_id) DO NOTHING
            """
        ),
        {
            "tid": tenant_id,
            "ns": namespace,
            "ext": external_id,
            "cid": canonical_id,
            "tbl": canonical_table,
        },
    )
    resolved = resolve(
        conn, tenant_id=tenant_id, namespace=namespace, external_id=external_id
    )
    if resolved and resolved != canonical_id:
        raise ValueError(f"id_collision:{namespace}:{external_id}")
    return resolved or canonical_id
