"""Retired Routing / Logic rules cannot affect escalation or API routes."""

from __future__ import annotations

import pytest
from sqlalchemy import event, text

import db
import db_core


def test_retired_builder_has_no_live_api_routes() -> None:
    from fastapi.routing import APIRoute
    from main import app

    paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    assert not any(path.startswith("/routing-rules") for path in paths)
    assert "/routing-audit" not in paths
    assert "/voice-studio/routing" in paths


def test_legacy_escalation_does_not_read_retired_rules(db_tx) -> None:
    row = db_tx.execute(text(
        "SELECT id, customer_id FROM interactions WHERE customer_id IS NOT NULL "
        "ORDER BY created_at DESC LIMIT 1"
    )).mappings().first()
    if not row:
        pytest.skip("no interaction to escalate")

    def refuse_rule_sql(conn, cursor, statement, parameters, context, executemany):
        if "routing_rules" in statement or "routing_rule_executions" in statement:
            raise AssertionError("retired routing tables were accessed")

    event.listen(db_core.engine, "before_cursor_execute", refuse_rule_sql)
    try:
        result = db.escalate_voice_interaction(
            interaction_id=row["id"], reason="customer_requested",
            customer_id=row["customer_id"],
        )
    finally:
        event.remove(db_core.engine, "before_cursor_execute", refuse_rule_sql)

    assert result["handoffId"]
    assert result["conversationId"]
    assert result["teamId"] == "card-collections"
