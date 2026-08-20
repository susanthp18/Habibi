"""Floor command snapshot: IDs, composite risk, presence, real queue wait."""

from __future__ import annotations

import pytest

import actor_context
import ops_screens


@pytest.fixture
def as_actor():
    tokens = []

    def _use(user_id: str):
        tokens.append(actor_context.set_actor_user_id(user_id))

    yield _use
    for token in reversed(tokens):
        actor_context.reset_actor_user_id(token)


def test_floor_snapshot_shape(db_tx, as_actor) -> None:
    as_actor("priya-nair")
    snap = ops_screens.get_floor_snapshot()
    assert set(snap) >= {"calls", "alerts", "stats", "agents"}
    stats = snap["stats"]
    for key in (
        "callsInProgress",
        "avgSentiment",
        "criticalAlerts",
        "queueDepth",
        "agentsAvailable",
        "agentsOnCall",
        "botAtRisk",
        "longestWaitSec",
    ):
        assert key in stats
    if snap["calls"]:
        call = snap["calls"][0]
        assert "customerId" in call
        assert "recommendedAction" in call
        assert "flags" in call
        assert call["risk"] in {"low", "medium", "high"}
