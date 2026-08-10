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
"""

from __future__ import annotations

import pytest

import flow_graph as fg
from voice.session import VoiceSession

pytest.importorskip("pipecat.flows")


def _live_tool_keys() -> set[str]:
    from voice.tools import build_tools

    _state, tools = build_tools(
        VoiceSession(session_id="VS-CATALOGTEST"),
        bot_id=None,
        start_recording=None,
        nodes={},
    )
    return set(tools)


def test_catalog_matches_the_live_registry_exactly() -> None:
    catalog = {t["key"] for t in fg.tool_catalog()}
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


def test_text_only_tools_are_not_offered_for_voice_flows() -> None:
    """identify_customer is the text-channel twin of verify_identity."""
    assert "identify_customer" not in {t["key"] for t in fg.tool_catalog()}
