"""One gate id, one name — and every id spoken for.

The ids lived only as ~40 string literals inside ``compile.py``, and both
failure modes that invites had already happened. ``G-OB1`` was emitted as
``missions_declared`` from the outbound loop and as ``outbound`` on its two skip
paths, so the same gate arrived at the operator under two names depending on
which branch ran. And two designs each specified a ``G-F12``, because nothing in
the tree said which ids were taken.

``_gate()`` now asserts against ``_GATE_NAMES``, which turns both into an
immediate failure at the call site. These tests cover what that assert cannot:
that the map itself is sane, and that a real compile actually exercises it.
"""

from __future__ import annotations

import pytest

from agent_core.cards.compile import _GATE_NAMES, _gate, compile_card
from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS, card_dump


def test_the_map_is_injective() -> None:
    """Two ids sharing a name is the same confusion as one id with two."""
    by_name: dict[str, list[str]] = {}
    for gate, name in _GATE_NAMES.items():
        by_name.setdefault(name, []).append(gate)
    duplicates = {n: g for n, g in by_name.items() if len(g) > 1}
    assert not duplicates, f"gate names shared by several ids: {duplicates}"


def test_an_unregistered_id_is_refused() -> None:
    with pytest.raises(AssertionError, match="unregistered gate id"):
        _gate("G-NOPE", "whatever", "pass")


def test_a_registered_id_cannot_be_given_a_second_name() -> None:
    """The G-OB1 bug, as a test."""
    with pytest.raises(AssertionError, match="missions_declared"):
        _gate("G-OB1", "outbound", "skipped")


def test_reserved_ids_are_not_yet_in_use() -> None:
    """G-F16 is spoken for by design; taking one by accident is the bug the
    registry exists to prevent.

    G-F12 and G-F15 left this list when they were built (`fleet.compile
    .fleet_gates`), which is the only way an id may leave it -- being claimed,
    with a name, by code that runs.
    """
    assert "G-F16" not in _GATE_NAMES


def test_the_fleet_gates_that_were_reserved_now_have_the_names_they_were_reserved_for() -> None:
    """Two designs each independently specified a `G-F12`, which is why the
    registry exists. Pinning the name against the reservation is what stops the
    id being reused for something else later."""
    assert _GATE_NAMES["G-F12"] == "publish_scope"
    assert _GATE_NAMES["G-F15"] == "fleet_hop"


@pytest.mark.parametrize("bot_id", sorted(FIRST_PARTY_BOT_IDS))
def test_every_gate_a_real_compile_emits_is_registered(bot_id: str) -> None:
    """The assert in ``_gate`` only fires on a line that runs, so run them."""
    from agent_core.tools import CATALOG

    report = compile_card(
        bot_id=bot_id,
        card_raw=card_dump(bot_id),
        flow={},
        catalog_names=set(CATALOG.specs),
        known_bot_ids=set(FIRST_PARTY_BOT_IDS),
    )
    assert report.gates, "a compile that emits no gate is not a compile"
    for result in report.gates:
        assert _GATE_NAMES.get(result.gate) == result.name
