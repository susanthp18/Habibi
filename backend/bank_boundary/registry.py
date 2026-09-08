"""Per-tenant contract bindings and closed dispatch."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from bank_boundary import ALL_CODES, CONTRACT_VERSION, schema_ready


def bind(
    conn: Any,
    *,
    tenant_id: str,
    contract_code: str,
    schema_version: str = CONTRACT_VERSION,
    portfolio_id: str = "",
    adapter: str = "reference",
    state: str = "shadow",
) -> str:
    if contract_code not in ALL_CODES:
        raise ValueError(f"unknown_contract:{contract_code}")
    if not schema_ready.w5_ready(conn):
        raise RuntimeError("w5_schema_missing")
    row_id = f"BBIND-{uuid.uuid4().hex[:10].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO bank_contract_bindings (
              id, tenant_id, portfolio_id, contract_code, schema_version,
              adapter, state
            ) VALUES (
              :id, :tid, :pid, :code, :ver, :adapter, :state
            )
            ON CONFLICT (tenant_id, portfolio_id, contract_code) DO UPDATE SET
              schema_version = EXCLUDED.schema_version,
              adapter = EXCLUDED.adapter,
              state = EXCLUDED.state
            """
        ),
        {
            "id": row_id,
            "tid": tenant_id,
            "pid": portfolio_id,
            "code": contract_code,
            "ver": schema_version,
            "adapter": adapter,
            "state": state,
        },
    )
    found = conn.execute(
        text(
            """
            SELECT id FROM bank_contract_bindings
             WHERE tenant_id = :tid AND portfolio_id = :pid AND contract_code = :code
            """
        ),
        {"tid": tenant_id, "pid": portfolio_id, "code": contract_code},
    ).scalar()
    return str(found or row_id)


def status(conn: Any, *, tenant_id: str, portfolio_id: str = "") -> list[dict[str, Any]]:
    if not schema_ready.w5_ready(conn):
        return []
    return [
        dict(r)
        for r in conn.execute(
            text(
                """
                SELECT contract_code, schema_version, adapter, state, bound_at
                  FROM bank_contract_bindings
                 WHERE tenant_id = :tid AND portfolio_id = :pid
                 ORDER BY contract_code
                """
            ),
            {"tid": tenant_id, "pid": portfolio_id},
        ).mappings().all()
    ]
