"""Circuit breaker for remote MCP connectors. Fail closed.

Fail closed includes corrupt state. A ``circuit_opened_at`` that will not parse
is a row this module cannot reason about, and the two readings are not
symmetrical: reading it as expired re-opens the dispatch path for a connector
whose breaker may well be open — which is the state the column exists to
record — while reading it as open costs one connector its dispatch path until
someone looks. This takes the same line ``agent_core/skills/persist`` takes for
a signed pack version that will not parse: a corrupt row is not read as absent,
and the capability it gates stays denied.

The deny is not the terminal, unrecoverable block it looks like.
``connectors.persist.health_test`` is not gated by :func:`allow`, and it calls
:func:`record_success`, which sets the column back to NULL — so an operator's
health probe is the recovery path, and it needs no direct SQL.

What was actually wrong was the silence. The parse failure returned ``False``
without a word, so every call answered ``connector_circuit_open`` with nothing
anywhere saying that the reason was a malformed timestamp rather than a real
outage. It logs now.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

import db

logger = logging.getLogger(__name__)

OPEN_AFTER = 3
COOLDOWN_S = 30


def allow(connector: dict[str, Any]) -> bool:
    """Whether the breaker lets a call through.

    Reads ``circuit_opened_at`` only. ``circuit_fails`` counts toward *opening*
    the breaker (see :func:`record_failure`, which stamps the column once the
    count reaches :data:`OPEN_AFTER`) but is not consulted here — a connector
    with failures and no stamp is still below the threshold, so it is allowed.

    An unparseable timestamp denies, and says so in the log. That is the
    deliberate choice, not an oversight; the module docstring has the reasoning
    and the recovery path.
    """
    opened = connector.get("circuit_opened_at") or connector.get("circuitOpenedAt")
    if not opened:
        return True
    if isinstance(opened, str):
        try:
            opened_dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
        except ValueError:
            logger.warning(
                "connector circuit state unparseable · id=%s · circuit_opened_at=%r"
                " · denying until a health probe clears it",
                connector.get("id") or connector.get("slug"),
                opened,
            )
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
