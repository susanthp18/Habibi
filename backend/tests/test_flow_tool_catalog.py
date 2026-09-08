"""The flow tool catalog must match what the runtime actually accepts.

``flow_graph.tool_catalog()`` is assembled from the pipecat-free
``agent_core.tools.CATALOG`` plus a hand-declared list of the flow-control tools
that only exist inside ``voice.tools.build_tools``. It has to be declared rather
than introspected because the API process — which serves the editor — does not
have pipecat installed.

That makes it exactly the kind of list that rots: add a tool to build_tools and
the editor never offers it; rename one and the editor offers a key the runtime
will silently drop. These tests run in the voice container, where pipecat *is*
available, and pin the two against each other.

The comparison is against the catalog's **voice slice**. ``tool_catalog()`` used
to filter to voice itself, which is how the two TEXT_ONLY specs came to be
grantable from nowhere: absent from the palette, so on no card and in no pack,
so refused by the runtime — while ``bot_runtime`` named one of them in every
WhatsApp system prompt. It now serves every channel with each row's own
``channels``, and each of the three pickers it feeds filters to what it is for.
A flow node is still a voice node, so this file still holds it to voice.
"""

from __future__ import annotations

import pytest

import flow_graph as fg
from voice.session import VoiceSession

pytest.importorskip("pipecat.flows")


def _live_tool_keys() -> set[str]:
    from agent_core.tools.catalog import CATALOG
    from voice.tools import ALWAYS_ON, build_tools

    _state, tools = build_tools(
        VoiceSession(session_id="VS-CATALOGTEST"),
        bot_id=None,
        start_recording=None,
        nodes={},
        allowed_tool_names=set(CATALOG.specs) | set(ALWAYS_ON),
    )
    return set(tools)


def _voice_catalog_keys() -> set[str]:
    """What the Flow tab offers: the rows that render on a call."""
    return {t["key"] for t in fg.tool_catalog() if "voice" in t["channels"]}


def test_catalog_matches_the_live_registry_exactly() -> None:
    catalog = _voice_catalog_keys()
    live = _live_tool_keys()

    missing = live - catalog
    assert not missing, (
        f"build_tools exposes {sorted(missing)} but the editor cannot offer them. "
        "Add them to flow_graph._FLOW_CONTROL_TOOLS or give the ToolSpec the "
        "'voice' channel."
    )
    extra = catalog - live
    assert not extra, (
        f"The editor offers {sorted(extra)} but build_tools does not provide them — "
        "an authored node using one would silently lose it at runtime."
    )


def test_every_catalog_entry_has_a_description() -> None:
    """The description is what the author picks by, and what the model reads."""
    blank = [t["key"] for t in fg.tool_catalog() if not t["description"].strip()]
    assert not blank, f"tools with no description: {blank}"


def test_transitioning_flags_match_tools_that_return_a_node() -> None:
    """Mislabelling this misleads the author about who controls the transition."""
    catalog = {t["key"]: t["transitions"] for t in fg.tool_catalog()}
    for key in fg._TRANSITIONING_TOOLS:
        assert catalog.get(key) is True, f"{key} should be flagged as transitioning"


def test_declared_flow_control_tools_are_all_real() -> None:
    live = _live_tool_keys()
    stale = set(fg._FLOW_CONTROL_TOOLS) - live
    assert not stale, f"declared but no longer in build_tools: {sorted(stale)}"


def test_text_only_tools_are_served_but_not_as_voice_flow_choices() -> None:
    """``identify_customer`` is the text-channel twin of ``verify_identity``.

    It has to reach the Studio — the Tools tab is where a card grants it, and
    the skill editor is where a pack lists it — and it must never be a choice on
    a flow node. The row carries its own channels and says which it is.
    """
    rows = {t["key"]: t for t in fg.tool_catalog()}
    assert rows["identify_customer"]["channels"] == ["text"]
    assert "identify_customer" not in _voice_catalog_keys()
    assert "ingest_customer_document" not in _voice_catalog_keys()


def test_every_row_states_the_channels_it_renders_on() -> None:
    """A row with no channels would be filtered by nobody and offered by all."""
    blank = [t["key"] for t in fg.tool_catalog() if not t["channels"]]
    assert not blank, f"tools with no channels: {blank}"


def test_the_always_on_flag_is_the_runtime_floor_and_not_a_second_list() -> None:
    from agent_core.tools.grant import TEXT_ALWAYS, VOICE_ALWAYS
    from voice.tools import ALWAYS_ON

    rows = fg.tool_catalog()
    marked = {t["key"] for t in rows if t["alwaysOn"]}
    # voice.tools.ALWAYS_ON *is* VOICE_ALWAYS, imported rather than restated.
    assert set(ALWAYS_ON) <= marked
    assert marked == (VOICE_ALWAYS | TEXT_ALWAYS) & {t["key"] for t in rows}
