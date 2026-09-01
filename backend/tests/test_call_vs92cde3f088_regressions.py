"""Regressions from live sandbox call VS-92CDE3F088 (2026-08-19 22:52-22:56).

Four minutes of audio, three separate defects, none of them a wording problem:

* the caller was told the call was recorded three times, minutes apart;
* the line went completely silent for 24 seconds after ``begin_negotiate``,
  and the idle ladder never logged a strike;
* the outstanding and minimum due were read out twice in seven seconds, and
  the caller was asked for "the exact date in YYYY-MM-DD".

Each test below pins the mechanism, not the symptom.
"""

from __future__ import annotations

import asyncio

import pytest

import flow_graph as fg
from agent_core.guardrails import evaluate_guardrails
from agent_core.tools import kb_plan
from voice.session import VoiceSession
from voice.spoken_text import to_spoken

pytest.importorskip("pipecat.flows")

from voice.flows_dynamic import build_authored_flow  # noqa: E402

_DISCLOSE = {"alwaysDiscloseRecording": True}


def _flags(bot_text: str, *, turn_index: int, disclosed: bool = False) -> list[str]:
    return evaluate_guardrails(
        customer_text="",
        bot_text=bot_text,
        intent="out_of_scope",
        guardrails=_DISCLOSE,
        turn_index=turn_index,
        elapsed_seconds=1.0,
        customer_bot_exchanges=1,
        recording_disclosed=disclosed,
    )


# --- the disclosure was said three times -----------------------------------


def test_greeting_that_discloses_satisfies_the_rule() -> None:
    assert "missing-recording-disclosure" not in _flags(
        "Hello, this is Priya from HDFC Bank Collections, and this call is "
        "recorded for quality and compliance.",
        turn_index=0,
    )


def test_second_turn_is_not_asked_to_disclose_again() -> None:
    """The bug. Turn 0 disclosed; turn 1 was flagged for not repeating it.

    The flag reached the turn critic, which injected "you have not yet
    satisfied a required disclosure", and the caller heard it twice more.
    """
    assert "missing-recording-disclosure" not in _flags(
        "Sure, I can help with your past due payments, but first I will need "
        "to verify your account.",
        turn_index=1,
        disclosed=True,
    )


def test_a_call_that_never_discloses_is_still_flagged() -> None:
    """The check must not have been softened into never firing."""
    assert "missing-recording-disclosure" in _flags(
        "Your outstanding is 62,400 rupees.", turn_index=1, disclosed=False
    )


def test_the_opening_turn_alone_is_not_yet_late() -> None:
    """Turn 0 is the greeting; lateness is judged from turn 1."""
    assert "missing-recording-disclosure" not in _flags(
        "Hello, this is Priya.", turn_index=0, disclosed=False
    )


def test_the_rendered_guardrail_says_once_not_always() -> None:
    from agent_core.prompt import guardrail_rules

    rule = " ".join(guardrail_rules(_DISCLOSE)).lower()
    assert "never say it again" in rule
    assert "always disclose" not in rule


# --- 24 seconds of dead air -------------------------------------------------


def _listen_first_graph() -> fg.FlowGraph:
    graph = fg.empty_graph()
    graph.nodes[0].data.respondImmediately = False
    return graph


def _compile(graph: fg.FlowGraph, session: VoiceSession) -> dict:
    _state, _tools, initial, _globals = build_authored_flow(
        session, graph.model_dump(), role_message="You are Priya."
    )
    return initial()


def test_listen_first_is_honoured_when_the_bot_spoke_last() -> None:
    session = VoiceSession(session_id="VS-DEADAIR01")
    session.last_speaker = "bot"
    assert _compile(_listen_first_graph(), session)["respond_immediately"] is False


def test_listen_first_is_overridden_when_the_caller_spoke_last() -> None:
    """The caller answered a question and was met with 24 seconds of silence.

    Nothing could break it: Pipecat's UserIdleController only arms its timer on
    BotStoppedSpeakingFrame, and no bot turn had happened.
    """
    session = VoiceSession(session_id="VS-DEADAIR02")
    session.last_speaker = "customer"
    assert _compile(_listen_first_graph(), session)["respond_immediately"] is True


def test_an_entry_line_lets_a_step_listen_even_after_the_caller_spoke() -> None:
    """Speaking on entry settles the debt; the step may then wait."""
    graph = _listen_first_graph()
    graph.nodes[0].data.entryLine = "Happy to set that up."
    session = VoiceSession(session_id="VS-DEADAIR03")
    session.last_speaker = "customer"
    config = _compile(graph, session)
    assert config["respond_immediately"] is False
    assert config["pre_actions"] == [
        {
            "type": "tts_say",
            "text": "Happy to set that up.",
            "append_text_to_context": False,
        }
    ]


def test_no_entry_line_means_no_pre_action() -> None:
    session = VoiceSession(session_id="VS-DEADAIR04")
    session.last_speaker = "bot"
    assert "pre_actions" not in _compile(_listen_first_graph(), session)


def test_exporting_the_builtin_script_keeps_its_bridge_lines() -> None:
    """The export dropped pre_actions, so a reload produced a silent step."""
    from voice.flow_export import _entry_line

    said = {"pre_actions": [{"type": "tts_say", "text": "Happy to set that up."}]}
    assert _entry_line(said) == "Happy to set that up."
    assert _entry_line({"pre_actions": [{"type": "function", "handler": "x"}]}) == ""
    assert _entry_line({}) == ""


# --- the silence nothing was watching --------------------------------------


class _Processed:
    """Minimal stand-in for pipecat's FrameProcessed payload."""

    def __init__(self, frame) -> None:
        self.frame = frame


def test_observer_measures_silence_the_idle_controller_cannot_see() -> None:
    from pipecat.frames.frames import UserStoppedSpeakingFrame

    from voice.bot_turn_state import BotTurnStateObserver

    observer = BotTurnStateObserver()
    assert observer.silent_for() == 0.0, "a call that has not begun is not quiet"

    asyncio.run(observer.on_push_frame(_Processed(UserStoppedSpeakingFrame())))
    assert observer.silent_for() > 0.0


def test_thinking_is_not_silence_the_caller_should_be_nudged_out_of() -> None:
    """busy() is what stops the watchdog nudging over a normal tool call."""
    from pipecat.frames.frames import LLMFullResponseStartFrame

    from voice.bot_turn_state import BotTurnStateObserver

    observer = BotTurnStateObserver()
    asyncio.run(observer.on_push_frame(_Processed(LLMFullResponseStartFrame())))
    assert observer.busy() is True


def test_an_interruption_ends_the_bot_turn_it_cancelled() -> None:
    """A barge-in cancels the response — so the bot no longer owes that turn.

    `_generating` is raised by LLMFullResponseStartFrame and lowered by
    LLMFullResponseEndFrame. An interruption cancels the in-flight response
    *without* ever emitting the End frame, so the flag latched on and `busy()`
    answered True for the rest of the call.

    That flag is what the idle ladder consults before nudging. On call
    VS-F93E3B2133 the caller barged in 326ms into "Great, let me verify that
    quick…", the response was cancelled, the tool result landed in a dead
    context, and no further inference ever ran. The dead-air watchdog — the one
    safety net that would have re-engaged them — was suppressed on every tick
    because `busy()` still claimed a turn was in flight. The caller heard 30
    seconds of silence and hung up.

    An interruption is precisely the event that ends a bot turn. The observer
    has to treat it as one.
    """
    from pipecat.frames.frames import (
        InterruptionFrame,
        LLMFullResponseStartFrame,
    )

    from voice.bot_turn_state import BotTurnStateObserver

    observer = BotTurnStateObserver()
    asyncio.run(observer.on_push_frame(_Processed(LLMFullResponseStartFrame())))
    assert observer.busy() is True, "a generating bot owes a turn"

    asyncio.run(observer.on_push_frame(_Processed(InterruptionFrame())))
    assert observer.busy(grace_seconds=0.0) is False, (
        "after a barge-in the cancelled turn is not still owed — leaving it "
        "owed suppresses the dead-air watchdog for the rest of the call"
    )


def test_an_interruption_clears_a_tool_call_that_will_never_return() -> None:
    """The same latch, reached through the tool counter.

    `_tool_calls` is decremented by FunctionCallResultFrame. A barge-in during a
    tool call can cancel the turn before any result arrives, and an outstanding
    count keeps `busy()` True exactly as a stuck `_generating` does.
    """
    from pipecat.frames.frames import FunctionCallInProgressFrame, InterruptionFrame

    from voice.bot_turn_state import BotTurnStateObserver

    observer = BotTurnStateObserver()
    frame = FunctionCallInProgressFrame(
        function_name="verify_identity",
        tool_call_id="call_1",
        arguments={},
    )
    asyncio.run(observer.on_push_frame(_Processed(frame)))
    assert observer.busy() is True

    asyncio.run(observer.on_push_frame(_Processed(InterruptionFrame())))
    assert observer.busy(grace_seconds=0.0) is False


# --- the balance, twice -----------------------------------------------------


def test_tool_state_tracks_whether_the_position_was_stated() -> None:
    from voice.tools import ToolState

    assert ToolState().position_stated is False


# --- "the exact date in YYYY-MM-DD" ----------------------------------------


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        (
            "tell me the exact date in YYYY-MM-DD you will pay it by.",
            "tell me the exact date you will pay it by.",
        ),
        ("Give me a date in the format DD/MM/YYYY please.", "Give me a date please."),
        ("We can call you at HH:MM tomorrow.", "We can call you tomorrow."),
    ],
)
def test_date_format_tokens_never_reach_the_speaker(said: str, expected: str) -> None:
    assert to_spoken(said) == expected


@pytest.mark.parametrize(
    "said",
    [
        "Pay by 2026-08-23 please.",
        "Your minimum due is 4,800 rupees.",
        "My dad said hmm about that.",
        "I will call you on Monday.",
    ],
)
def test_real_speech_is_left_alone(said: str) -> None:
    assert to_spoken(said) == said


# --- the KB judge that never ran -------------------------------------------


def test_the_planner_cannot_spend_the_judges_budget() -> None:
    """Shared first-come-first-served, the planner took it all every time.

    Measured: planner 1796ms of a 2500ms budget, embed 355ms, judge left 0.13s
    - under _MIN_CALL_BUDGET_S, so it never ran and every voice lookup logged
    "kb answerability degraded (judge_unavailable)".

    The first attempt at this subtracted a reserve from the planner's timeout,
    which is what the earlier version of this test asserted. It did not work:
    the deadline is absolute wall clock and the embed and vector search spend
    it too, so the judge was still offered 0.0s. The guarantee is a floor now —
    see :meth:`kb_plan.Deadline.guaranteed`.
    """
    # The bug is now unreachable by construction: there is no judge to starve.
    # kb.py is asserted judge-free in
    # test_kb_judge_budget_and_prewarm.py::test_the_judge_is_not_called_at_all.
    assert not hasattr(kb_plan, "judge_passages")
    assert not hasattr(kb_plan, "judge_reserve_s")

    # The guarantee mechanism itself still holds for whatever uses it next.
    exhausted = kb_plan.Deadline(0.0)
    assert exhausted.remaining() == 0.0
    assert exhausted.guaranteed(2.5) == pytest.approx(2.5)


def test_the_voice_budget_covers_the_planner() -> None:
    """Worst-case retrieval is the planner budget now, not planner + judge.

    It was 2.5 + 3.5 = 6.0s. Removing the judge removes the second term
    outright, which is the single largest latency change on the voice KB path.
    """
    observed_planner_secs = 1.8
    assert kb_plan.voice_budget_s() >= observed_planner_secs
    assert kb_plan.voice_budget_s() <= 3.0
