"""Dead-air and coherence fixes: NO_RESPONSE, the spoke-probe, tool-change messages.

Three small changes that share one theme — stop the bot producing a turn that
says nothing, and stop it saying two things at once.

Note on NO_RESPONSE: the source plan proposed it for the ``begin_*`` node hops.
That is not viable and the tests below pin why. In pipecat 1.6.0
(``flows/manager.py``) ``NO_RESPONSE`` *occupies the next-node slot*::

    is_no_response = next_node is NO_RESPONSE
    if is_no_response or not next_node:   # stay on the CURRENT node
        properties = FunctionCallResultProperties(run_llm=not is_no_response)

so returning it means "stay here and stay silent" — mutually exclusive with
transitioning. ``flows/types.py`` says as much: for transitioning functions,
``NodeConfig.respond_immediately`` is the equivalent control.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.flows import NO_RESPONSE
from pipecat.frames.frames import (
    InterruptionFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TextFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from voice import config as voice_config
from voice.flows import build_collections_flow
from voice.session import VoiceSession
from voice.turn_probe import SpokeThisResponseProbe


def _flow(**kw):
    return build_collections_flow(
        VoiceSession(session_id="VS-TURNTEST1"), role_message="role", **kw
    )


# ------------------------------------------------------------------ NO_RESPONSE


def test_pause_for_caller_returns_no_response() -> None:
    """It already spoke "Of course, take your time." — a second inference would
    talk over the bot's own hold acknowledgement, on a turn whose whole point is
    silence."""
    _state, tools, _initial, _globals = _flow()
    _result, next_slot = asyncio.run(tools["pause_for_caller"](None))
    assert next_slot is NO_RESPONSE


def test_pause_for_caller_still_reports_holding() -> None:
    """NO_RESPONSE suppresses speech, not the tool result itself."""
    _state, tools, _initial, _globals = _flow()
    result, _ = asyncio.run(tools["pause_for_caller"](None))
    assert result["holding"] is True


def test_transitioning_tools_do_not_use_no_response() -> None:
    """The plan's proposed targets. NO_RESPONSE occupies the next-node slot, so
    using it here would silently cancel the transition."""
    session = VoiceSession(session_id="VS-TURNTEST1")
    session.identity_verified = True
    nodes: dict = {}
    from voice.tools import build_tools

    state, tools = build_tools(session, bot_id=None, start_recording=None, nodes=nodes)
    nodes.update(
        {
            "negotiate_ptp": lambda: {"name": "negotiate_ptp"},
            "handle_dispute": lambda: {"name": "handle_dispute"},
            "wrap_up": lambda: {"name": "wrap_up"},
            "state_position": lambda: {"name": "state_position"},
        }
    )

    for tool, expected in (
        ("begin_negotiate", "negotiate_ptp"),
        ("begin_dispute", "handle_dispute"),
        ("begin_wrap_up", "wrap_up"),
        ("return_to_position", "state_position"),
    ):
        _result, next_node = asyncio.run(tools[tool](None))
        assert next_node is not NO_RESPONSE, f"{tool} would lose its transition"
        assert next_node["name"] == expected


def test_add_customer_note_is_silent_only_when_already_spoken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unconditional suppression would leave dead air when the model called the
    tool without speaking first."""
    import db

    monkeypatch.setattr(db, "add_customer_note", lambda *_a, **_k: {"id": "N-1"})

    session = VoiceSession(session_id="VS-TURNTEST1", customer_id="C1")
    session.identity_verified = True
    from voice.tools import build_tools

    def _run(spoke: bool):
        _state, tools = build_tools(
            session,
            bot_id=None,
            start_recording=None,
            nodes={},
            spoke_this_response=lambda: spoke,
        )
        return asyncio.run(tools["add_customer_note"].handler({"text": "note body"}, None))

    _res_spoke, next_spoke = _run(True)
    res_silent, next_silent = _run(False)

    assert next_spoke is NO_RESPONSE, "spoke already — should not inference again"
    assert next_silent is None, "called silently — must still say something"
    assert res_silent.get("say"), "no instruction to speak on the silent path"


def test_add_customer_note_without_a_probe_still_speaks() -> None:
    """A PSTN call that never wires the probe must not go silent."""
    import db

    original = db.add_customer_note
    db.add_customer_note = lambda *_a, **_k: {"id": "N-1"}
    try:
        session = VoiceSession(session_id="VS-TURNTEST1", customer_id="C1")
        session.identity_verified = True
        from voice.tools import build_tools

        _state, tools = build_tools(session, bot_id=None, start_recording=None, nodes={})
        _res, next_slot = asyncio.run(
            tools["add_customer_note"].handler({"text": "note"}, None)
        )
    finally:
        db.add_customer_note = original
    assert next_slot is None


# -------------------------------------------------------------------- the probe


class _ProbeHarness:
    def __init__(self) -> None:
        self.probe = SpokeThisResponseProbe()

        async def _push(frame, direction=FrameDirection.DOWNSTREAM):
            return None

        self.probe.push_frame = _push  # type: ignore[method-assign]

    async def send(self, frame) -> None:
        await self.probe.process_frame(frame, FrameDirection.DOWNSTREAM)


def test_probe_starts_false_and_sets_on_text() -> None:
    async def scenario() -> tuple[bool, bool]:
        h = _ProbeHarness()
        await h.send(LLMFullResponseStartFrame())
        before = h.probe.spoke_this_response
        await h.send(LLMTextFrame("Sure, I can set that up."))
        return before, h.probe.spoke_this_response

    before, after = asyncio.run(scenario())
    assert before is False
    assert after is True


def test_probe_resets_on_each_new_response() -> None:
    """Otherwise the filler is suppressed for the rest of the call after one
    spoken turn."""

    async def scenario() -> bool:
        h = _ProbeHarness()
        await h.send(LLMFullResponseStartFrame())
        await h.send(LLMTextFrame("Sure."))
        await h.send(LLMFullResponseStartFrame())
        return h.probe.spoke_this_response

    assert asyncio.run(scenario()) is False


def test_probe_resets_on_interruption() -> None:
    """A barge-in abandons the response; what follows has not been spoken."""

    async def scenario() -> bool:
        h = _ProbeHarness()
        await h.send(LLMFullResponseStartFrame())
        await h.send(LLMTextFrame("Sure, I can..."))
        await h.send(InterruptionFrame())
        return h.probe.spoke_this_response

    assert asyncio.run(scenario()) is False


def test_probe_ignores_whitespace_only_text() -> None:
    """Streaming emits empty/whitespace chunks; those are not speech."""

    async def scenario() -> bool:
        h = _ProbeHarness()
        await h.send(LLMFullResponseStartFrame())
        await h.send(TextFrame("   "))
        return h.probe.spoke_this_response

    assert asyncio.run(scenario()) is False


def test_probe_pushes_every_frame_it_inspects() -> None:
    """The probe sits between llm and tts; swallowing a text frame would mute
    the bot.

    SystemFrames (InterruptionFrame) are excluded: pipecat's base class routes
    those itself and needs an initialised TaskManager, which is framework
    behaviour every processor shares rather than anything this class does.
    """
    pushed: list[str] = []

    async def scenario() -> None:
        probe = SpokeThisResponseProbe()

        async def _push(frame, direction=FrameDirection.DOWNSTREAM):
            pushed.append(type(frame).__name__)

        probe.push_frame = _push  # type: ignore[method-assign]
        for f in (LLMFullResponseStartFrame(), LLMTextFrame("hi"), TextFrame("there")):
            await probe.process_frame(f, FrameDirection.DOWNSTREAM)

    asyncio.run(scenario())
    assert pushed == ["LLMFullResponseStartFrame", "LLMTextFrame", "TextFrame"]


# --------------------------------------------------------- tool change messages


def test_tool_change_messages_default_on() -> None:
    assert voice_config.voice_tool_change_messages() is True


def test_aggregator_params_accept_the_field() -> None:
    """Pin the pipecat contract: both aggregators carry it, and pipecat's own
    implementation is dedupe-safe across the pair, which is why bot.py sets it
    on both rather than reasoning about frame direction."""
    from pipecat.processors.aggregators.llm_response_universal import (
        LLMAssistantAggregatorParams,
        LLMUserAggregatorParams,
    )

    assert LLMUserAggregatorParams(add_tool_change_messages=True).add_tool_change_messages
    assert LLMAssistantAggregatorParams(add_tool_change_messages=True).add_tool_change_messages


# ------------------------------------------------------- acknowledge-then-call


def test_role_message_asks_for_acknowledge_then_call() -> None:
    from voice.natural import VOICE_NATURALNESS_OVERLAY

    overlay = VOICE_NATURALNESS_OVERLAY.lower()
    assert "same reply as the call" in overlay
    assert "acknowledgement, not a stall" in overlay


def test_role_message_still_bans_contentless_filler() -> None:
    """The new instruction must not read as licence to stall — the two rules
    have to coexist or the bot goes back to saying "one moment"."""
    from voice.natural import VOICE_NATURALNESS_OVERLAY

    overlay = VOICE_NATURALNESS_OVERLAY.lower()
    assert "contentless filler" in overlay
    assert "one moment" in overlay
