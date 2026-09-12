"""Floor command snapshot: IDs, composite risk, presence, real queue wait."""

from __future__ import annotations

import pytest

import actor_context
import db_floor


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
    snap = db_floor.get_floor_snapshot()
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


def test_floor_flags_are_a_set(db_tx, as_actor) -> None:
    """A flag raised on two turns is one chip on the card, not two with one key."""
    as_actor("priya-nair")
    for call in db_floor.get_floor_snapshot()["calls"]:
        assert len(call["flags"]) == len(set(call["flags"])), call["interactionId"]
