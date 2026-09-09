"""A retired key is dropped on read; an invented one still fails.

Every model in ``agent_core.cards.schema`` sets ``extra="forbid"``, and all 18
published cards store the keys this phase is removing. So the deletion is not a
schema edit: without a tolerated-drop path it makes every published card
unparseable, G0 fails and the fleet stops recompiling.

The pair of assertions below is the whole contract. Dropping the first would
make the deletion an outage; dropping the second would turn ``_RETIRED`` into
``extra="ignore"`` by the back door, which is the guardrail — a typo in a hand
-edited card failing loudly — that the list exists to preserve.
"""

from __future__ import annotations

import pytest

from agent_core.cards.schema import _RETIRED, AgentCard, parse_card

# The shape a published card actually has today, retired keys and all.
_STORED = {
    "schema_version": "1",
    "identity": {
        "bot_id": "kaia-v2-4",
        "slug": "collections",
        "display_name": "Collections",
        "data_class": ["pii", "money"],
        "regulator_tags": ["rbi-fair-practices", "dpdp"],
    },
    "mouth": {"flow_ref": None, "languages": ["English", "Hindi"]},
    "memory": {
        "scopes": ["turn", "call"],
        "compaction": {"raw_last_n": 8, "summarize_over_budget": True},
        "max_hops_per_call": 2,
    },
    "outbound": {
        "direction": "both",
        "concurrency_share": 0,
        "objectives": [{"key": "bounce_cure", "success": ["ptp_captured"]}],
        "cadences": [{"name": "collections", "time_of_day": "engine"}],
    },
    "experiment": {"traffic_pct": 100, "shadow": False},
}


def test_a_stored_card_still_parses() -> None:
    card = parse_card(_STORED)
    assert card.identity.bot_id == "kaia-v2-4"
    # The parts that are not retired survive the drop.
    assert card.memory.max_hops_per_call == 2
    assert card.outbound.direction == "both"
    assert card.outbound.objectives[0].success == ["ptp_captured"]
    assert card.outbound.cadences[0].name == "collections"
    assert card.experiment.traffic_pct == 100


def test_an_invented_key_still_raises() -> None:
    """`_RETIRED` is a named list, not `extra="ignore"`."""
    with pytest.raises(Exception):
        parse_card({**_STORED, "not_a_real_key": 1})
    with pytest.raises(Exception):
        parse_card({**_STORED, "identity": {**_STORED["identity"], "invented": 1}})


def test_the_drop_does_not_mutate_the_callers_dict() -> None:
    """Cards are read straight out of a bundle dict that other code still holds."""
    raw = {"schema_version": "1", "identity": dict(_STORED["identity"])}
    parse_card(raw)
    assert "data_class" in raw["identity"]


def test_every_retired_path_is_gone_from_the_dump() -> None:
    """What republishes must be the new shape, or the list never shrinks."""
    dumped = parse_card(_STORED).model_dump(mode="json")
    for path in _RETIRED:
        node: object = dumped
        for segment in path:
            if segment == "*":
                node = node[0] if isinstance(node, list) and node else None
            elif isinstance(node, dict):
                node = node.get(segment)
            else:
                node = None
            if node is None:
                break
        assert node is None, f"retired path {'.'.join(path)} survived model_dump"
