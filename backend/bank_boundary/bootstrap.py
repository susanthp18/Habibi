"""Apply sql/24 inside a rolled-back test transaction when W5 is absent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready as treatment_schema
from bank_boundary import ALL_CODES, CONTRACT_VERSION, schema_ready

BACKEND = Path(__file__).resolve().parents[1]
SQL_24 = BACKEND / "sql" / "24_bank_boundary.sql"

REFERENCE_LMS = (
    ("reference", "active", "active", True),
    ("reference", "closed", "closed", False),
    ("reference", "charged_off", "charged_off", False),
)
REFERENCE_RAIL = (
    ("reference", "U5", "insufficient_funds", True),
    ("reference", "account_closed", "account_closed", False),
    ("reference", "technical", "technical", True),
)


def ensure(conn: Any) -> None:
    treatment_schema.reset_cache()
    if schema_ready.w5_ready(conn):
        _seed_maps(conn)
        return
    sql = SQL_24.read_text(encoding="utf-8")
    before, marker, rest = sql.partition("-- W5_ROLE_DDL_BEGIN")
    if marker:
        _, end, after = rest.partition("-- W5_ROLE_DDL_END")
        if not end:
            raise RuntimeError("unterminated W5 role DDL marker")
        sql = before + after
    conn.exec_driver_sql(sql)
    treatment_schema.reset_cache()
    _seed_maps(conn)


def _seed_maps(conn: Any) -> None:
    for namespace, code, normalised, permitted in REFERENCE_LMS:
        conn.execute(
            text(
                """
                INSERT INTO lms_account_status (
                  namespace, code, normalised, contacting_permitted
                ) VALUES (:ns, :code, :norm, :ok)
                ON CONFLICT (namespace, code) DO NOTHING
                """
            ),
            {"ns": namespace, "code": code, "norm": normalised, "ok": permitted},
        )
    for namespace, code, normalised, retryable in REFERENCE_RAIL:
        conn.execute(
            text(
                """
                INSERT INTO rail_return_codes (
                  namespace, code, normalised, retryable
                ) VALUES (:ns, :code, :norm, :ok)
                ON CONFLICT (namespace, code) DO NOTHING
                """
            ),
            {"ns": namespace, "code": code, "norm": normalised, "ok": retryable},
        )
    tenants = conn.execute(text("SELECT id FROM tenants")).scalars().all()
    for tenant_id in tenants:
        for code in ALL_CODES:
            conn.execute(
                text(
                    """
                    INSERT INTO bank_contract_bindings (
                      id, tenant_id, portfolio_id, contract_code,
                      schema_version, adapter, state
                    ) VALUES (
                      :id, :tid, '', :code, :version, 'reference', 'shadow'
                    )
                    ON CONFLICT (tenant_id, portfolio_id, contract_code)
                    DO NOTHING
                    """
                ),
                {
                    "id": f"REF-{tenant_id}-{code}"[:80],
                    "tid": tenant_id,
                    "code": code,
                    "version": CONTRACT_VERSION,
                },
            )
