"""Detect whether the W5 bank-boundary schema is present."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.treatment import schema_ready as _base


def w5_ready(conn: Any) -> bool:
    return all(
        _base.has_table(conn, table)
        for table in (
            "bank_contracts",
            "bank_contract_versions",
            "bank_contract_bindings",
            "bank_inbound_manifests",
            "bank_reconciliation_runs",
            "bank_freshness",
            "action_contracts",
            "bank_outbound_outbox",
            "bank_outbound_acks",
        )
    )


def evaluation_ready(conn: Any) -> bool:
    try:
        found = conn.execute(
            text("SELECT to_regclass('evaluation.protected_attributes')")
        ).scalar()
        return found is not None
    except Exception:
        return False
