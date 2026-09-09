"""Nodes that say goodbye hang up, and "Max call duration" is a duration.

* **FLOW-2.** ``voice/flow_export.py`` marked only ``call_ended`` as
  ``endConversation``. ``wrap_up``, ``terminate_politely`` and
  ``escalate_close`` all carry ``post_actions: end_conversation`` in
  ``voice/flows.py``, so loading the built-in script into the canvas and
  publishing it produced three terminals that say goodbye and keep the line
  open. The export now reads the post-action rather than a node's name.

* **GUARDRAILS-3.** ``guardrails.maxSeconds`` was authored, published and read
  by nobody: every call ran to the fixed ten-minute platform cap. It now
  narrows that cap and can never widen it.
"""

from __future__ import annotations

import inspect

from tests.conftest import frontend_file
from voice import flow_export


def _exported() -> dict[str, dict]:
    graph = flow_export.built_in_collections_graph()
    nodes = graph["nodes"] if isinstance(graph, dict) else graph.nodes
    out = {}
    for node in nodes:
        key = node["key"] if isinstance(node, dict) else node.key
        data = node["data"] if isinstance(node, dict) else node.data
        out[key] = data if isinstance(data, dict) else data.model_dump()
    return out


# ---------------------------------------------------------------------------
# Terminals
# ---------------------------------------------------------------------------


def test_every_node_that_hangs_up_exports_as_one() -> None:
    exported = _exported()
    for key in ("call_ended", "wrap_up", "terminate_politely", "escalate_close"):
        assert key in exported, f"{key} missing from the export"
        assert exported[key]["endConversation"] is True, key


def test_a_node_that_keeps_talking_does_not() -> None:
    """``pre_close`` is the one terminal-adjacent node with no
    ``end_conversation`` — it is the "anything else?" turn."""
    exported = _exported()
    assert exported["greet_disclose"]["endConversation"] is False
    if "pre_close" in exported:
        assert exported["pre_close"]["endConversation"] is False


def test_the_export_reads_the_script_not_a_name_list() -> None:
    src = inspect.getsource(flow_export._node_json)
    assert '"endConversation": _ends_conversation(node)' in src
    assert '"endConversation": key == "call_ended"' not in src


def test_the_flag_and_the_interpreter_agree_on_one_action() -> None:
    """``flows_dynamic`` re-emits ``end_conversation`` from ``endConversation``.
    Deriving the flag from the same action makes the round trip lossless."""
    assert flow_export._ends_conversation({"post_actions": [{"type": "end_conversation"}]})
    assert not flow_export._ends_conversation({"post_actions": [{"type": "tts_say"}]})
    assert not flow_export._ends_conversation({})


# ---------------------------------------------------------------------------
# The call budget
# ---------------------------------------------------------------------------


def test_an_authored_duration_can_only_shorten_the_call() -> None:
    """The slider is not a way to buy a longer call than the platform allows."""
    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "cap = min(cap, authored)" in src
    assert "await asyncio.sleep(cap)" in src
    assert "await asyncio.sleep(_MAX_CALL_DURATION_SECS)" not in src


def test_the_watchdog_reads_the_published_guardrail() -> None:
    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert '(bundle.get("guardrails") or {}).get("maxSeconds")' in src
    assert 'session.extra["guardrail_max_seconds"]' in src


def test_a_non_numeric_duration_does_not_break_the_call() -> None:
    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "except (TypeError, ValueError):" in src


def test_the_slider_cannot_ask_for_more_than_the_platform_cap() -> None:
    """The panel ran to 15 minutes against a 10-minute runtime cap, so every
    value above 600s was a number the runtime would never honour."""
    panel = frontend_file("src", "components", "prompt-studio", "GuardrailsPanel.tsx")
    import voice.bot as bot

    text = panel.read_text(encoding="utf-8")
    assert f"const MAX_CALL_SECONDS = {bot._MAX_CALL_DURATION_SECS};" in text
    assert "max={MAX_CALL_SECONDS}" in text
    assert "max={900}" not in text
