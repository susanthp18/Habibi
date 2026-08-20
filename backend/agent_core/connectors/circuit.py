"""Circuit breaker for remote MCP connectors. Fail closed."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

import db

OPEN_AFTER = 3
COOLDOWN_S = 30


def allow(connector: dict[str, Any]) -> bool:
    opened = connector.get("circuit_opened_at") or connector.get("circuitOpenedAt")
    if not opened:
        return True
    if isinstance(opened, str):
        try:
            opened_dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        except ValueError:
            return False
    else:
        opened_dt = opened
    if opened_dt.tzinfo is None:
        opened_dt = opened_dt.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - opened_dt).total_seconds()
    return elapsed >= COOLDOWN_S


def record_failure(connector_id: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE mcp_connectors
                   SET circuit_fails = circuit_fails + 1,
                       circuit_opened_at = CASE
                         WHEN circuit_fails + 1 >= :n THEN now()
                         ELSE circuit_opened_at
                       END,
                       health = CASE WHEN circuit_fails + 1 >= :n THEN 'down' ELSE 'degraded' END
                 WHERE id = :id AND tenant_id = :t
                """
            ),
            {"id": connector_id, "t": db._tenant(), "n": OPEN_AFTER},
        )


def record_success(connector_id: str) -> None:
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE mcp_connectors
                   SET circuit_fails = 0, circuit_opened_at = NULL, health = 'healthy',
                       last_tools_list_at = now()
                 WHERE id = :id AND tenant_id = :t
                """
            ),
            {"id": connector_id, "t": db._tenant()},
        )
