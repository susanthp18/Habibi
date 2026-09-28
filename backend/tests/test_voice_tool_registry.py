"""Anti-drift contract for the voice tool surface (voice/tools.py).

``tests/test_tool_catalog.py`` pins the WhatsApp/text side (CATALOG ↔
bot_tools). This is the voice mirror. It exists because seven tools used to
declare their contract *twice* — a ToolSpec in agent_core.tools.catalog **and**
a hand-rolled Pipecat direct function with its own signature and docstring — so
the two could drift silently and nothing failed.

It also happens to be the only test that calls ``build_tools`` at all, which
means it is the only thing that catches a NameError in the tools dict. Nothing
else in the suite constructs the voice tool surface.

The nine zero-argument flow-control tools are deliberately NOT in CATALOG:
ToolSpec exists to stop argument-name drift *between channels*, and these have
no arguments and no other channel. Pinning them by name here is the cheaper and
more honest mechanism.
"""

from __future__ import annotations

from agent_core.tools.catalog import CATALOG


# Zero-arg, voice-only flow control. Adding a name here must be a conscious act.
VOICE_CONTROL_TOOLS = frozenset(
    {
        "disclose_recording",
        "refuse_verification",
        "not_account_holder",
        "begin_negotiate",
        "begin_dispute",
        "begin_wrap_up",
        "return_to_position",
        "pause_for_caller",
        "end_call",
    }
)


def test_control_tools_are_absent_from_the_text_catalog() -> None:
    """So the WhatsApp channel can never advertise a voice-only node hop."""
    assert VOICE_CONTROL_TOOLS.isdisjoint(CATALOG.specs)
