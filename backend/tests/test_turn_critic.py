"""In-call self-correction.

The guarantees that matter here are mostly negative ones: the critic must never
raise into a call, never spend an Azure call it does not need, never exceed its
budget, and never let a model suppress a compliance finding the deterministic
path already made.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_core import turn_critic
from agent_core.turn_critic import (
    KIND_GUARDRAIL,
    KIND_LANGUAGE,
    KIND_REPETITION,
    KIND_UNANSWERED,
    Correction,
    critique_turn,
)


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("TURN_CRITIC_ENABLED", "true")


class _Understanding:
    def __init__(self, language="en"):
        self.language = language


def _no_azure(monkeypatch):
    """Fail loudly if a code path reaches Azure when it should not."""

    def boom(*_a, **_kw):
        raise AssertionError("Azure must not be called on this path")

    monkeypatch.setattr(turn_critic, "_unanswered_correction", boom)


# ------------------------------------------------------------------- the flag


def test_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TURN_CRITIC_ENABLED", raising=False)
    assert turn_critic.enabled() is False
    assert critique_turn(bot_text="anything", guardrail_flags=["prohibited:threat"]) is None


def test_flag_off_makes_no_azure_call(monkeypatch) -> None:
    monkeypatch.delenv("TURN_CRITIC_ENABLED", raising=False)
    _no_azure(monkeypatch)
    assert critique_turn(bot_text="hello there", user_text="what is my balance?") is None


# ------------------------------------------------------------------- priority


def test_guardrail_wins_over_everything(on, monkeypatch) -> None:
    """A compliance finding must not be displaced by a cheaper detector, and
    must not cost an Azure call to confirm."""
    _no_azure(monkeypatch)
    repeated = "Your outstanding balance is twelve thousand rupees and due now."

    c = critique_turn(
        bot_text=repeated,
        user_text="kya hai",
        guardrail_flags=["prohibited:threat"],
        recent_bot_turns=[repeated],
        understanding=_Understanding("hi"),
    )

    assert c is not None and c.kind == KIND_GUARDRAIL
    assert c.severity == turn_critic.SEVERITY_HIGH
    assert "prohibited:threat" in c.directive


def test_repetition_beats_language(on, monkeypatch) -> None:
    _no_azure(monkeypatch)
    repeated = "I can certainly help you set up a payment plan for that amount today."

    c = critique_turn(
        bot_text=repeated,
        recent_bot_turns=["something else entirely", repeated],
        understanding=_Understanding("hi"),
    )

    assert c is not None and c.kind == KIND_REPETITION


def test_language_fires_before_any_azure_call(on, monkeypatch) -> None:
    """Language comes off the understanding layer, which already ran. Paying
    for a second LLM call to notice it would be waste."""
    _no_azure(monkeypatch)

    c = critique_turn(
        bot_text="Certainly, I can help you with that today.",
        user_text="mujhe apna balance janna hai",
        understanding=_Understanding("hinglish"),
    )

    assert c is not None and c.kind == KIND_LANGUAGE
    assert "Hindi and English" in c.directive


# --------------------------------------------------------------- guardrail


def test_guardrail_accepts_dict_flags(on, monkeypatch) -> None:
    """The flag shape belongs to evaluate_guardrails, not to this module."""
    _no_azure(monkeypatch)
    c = critique_turn(bot_text="x", guardrail_flags=[{"rule": "waiver-blocked"}])
    assert c is not None and "waiver-blocked" in c.directive


def test_guardrail_ignores_empty_and_placeholder_flags(on, monkeypatch) -> None:
    _no_azure(monkeypatch)
    assert critique_turn(bot_text="x", guardrail_flags=["none", "", None]) is None


def test_correction_never_tells_the_caller_it_was_corrected(on, monkeypatch) -> None:
    _no_azure(monkeypatch)
    c = critique_turn(bot_text="x", guardrail_flags=["prohibited:threat"])
    assert "without" in c.directive and "drawing attention" in c.directive


# -------------------------------------------------------------- repetition


def test_short_turns_are_not_repetitions(on, monkeypatch) -> None:
    """"Sure." and "Of course." are similar and mean nothing."""
    _no_azure(monkeypatch)
    assert critique_turn(bot_text="Sure.", recent_bot_turns=["Sure."]) is None


def test_distinct_turns_are_not_repetitions(on, monkeypatch) -> None:
    _no_azure(monkeypatch)
    c = critique_turn(
        bot_text="Your outstanding balance is sixty two thousand four hundred rupees.",
        recent_bot_turns=["Could you confirm the last four digits of your mobile number?"],
    )
    assert c is None


def test_repetition_only_looks_back_a_short_window(on, monkeypatch) -> None:
    """Saying the same sentence once at the start and once at the end of a long
    call is not a loop."""
    _no_azure(monkeypatch)
    line = "I can certainly help you set up a payment plan for that amount today."
    stale = [line] + [f"unrelated filler sentence number {i} for padding" for i in range(6)]
    assert critique_turn(bot_text=line, recent_bot_turns=stale) is None


# ---------------------------------------------------------------- language


@pytest.mark.parametrize("lang", ["en", "other", "", None])
def test_no_language_correction_when_caller_is_in_english(on, monkeypatch, lang) -> None:
    _no_azure(monkeypatch)
    assert critique_turn(bot_text="Sure, I can help.", understanding=_Understanding(lang)) is None


def test_no_language_correction_when_bot_already_switched(on, monkeypatch) -> None:
    _no_azure(monkeypatch)
    c = critique_turn(bot_text="जी हाँ, मैं मदद कर सकता हूँ।", understanding=_Understanding("hi"))
    assert c is None


# --------------------------------------------------------------- resilience


def test_a_broken_detector_never_raises_into_the_call(on, monkeypatch) -> None:
    def boom(*_a, **_kw):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(turn_critic, "_repetition_correction", boom)
    assert critique_turn(bot_text="hello", user_text="hi") is None


def test_azure_busy_sheds_rather_than_raising(on, monkeypatch) -> None:
    import azure_openai

    def busy(*_a, **_kw):
        raise azure_openai.AzureBusyError("saturated")

    monkeypatch.setattr(azure_openai, "chat_with_tools", busy)
    assert critique_turn(bot_text="Sure.", user_text="what about my EMI?") is None


def test_malformed_llm_payload_is_dropped(on, monkeypatch) -> None:
    import azure_openai

    monkeypatch.setattr(
        azure_openai,
        "chat_with_tools",
        lambda *_a, **_kw: {"toolCalls": [{"name": "record_critique", "arguments": "not json"}]},
    )
    assert critique_turn(bot_text="Sure.", user_text="what about my EMI?") is None


def test_llm_saying_answered_produces_nothing(on, monkeypatch) -> None:
    import azure_openai

    monkeypatch.setattr(
        azure_openai,
        "chat_with_tools",
        lambda *_a, **_kw: {
            "toolCalls": [
                {"name": "record_critique", "arguments": '{"unanswered": false, "missed": ""}'}
            ]
        },
    )
    assert critique_turn(bot_text="Sure.", user_text="what about my EMI?") is None


def test_llm_unanswered_produces_a_directive(on, monkeypatch) -> None:
    import azure_openai

    monkeypatch.setattr(
        azure_openai,
        "chat_with_tools",
        lambda *_a, **_kw: {
            "toolCalls": [
                {
                    "name": "record_critique",
                    "arguments": '{"unanswered": true, "missed": "their EMI due date"}',
                }
            ]
        },
    )
    c = critique_turn(bot_text="Sure.", user_text="what about my EMI?")
    assert c is not None and c.kind == KIND_UNANSWERED
    assert "their EMI due date" in c.directive


def test_allow_llm_false_keeps_the_free_detectors(on, monkeypatch) -> None:
    _no_azure(monkeypatch)
    c = critique_turn(
        bot_text="x", guardrail_flags=["prohibited:threat"], allow_llm=False
    )
    assert c is not None and c.kind == KIND_GUARDRAIL


def test_pii_never_reaches_the_model(on, monkeypatch) -> None:
    """The prompt carries caller speech, which can contain card numbers."""
    seen: dict = {}

    import azure_openai

    def capture(messages, **_kw):
        seen["text"] = " ".join(m["content"] for m in messages)
        return {"toolCalls": []}

    monkeypatch.setattr(azure_openai, "chat_with_tools", capture)
    critique_turn(bot_text="Noted.", user_text="my card is 4111111111111111 ok")

    assert "4111111111111111" not in seen["text"]


# ------------------------------------------------------------ message shape


def test_correction_renders_as_a_developer_message() -> None:
    msg = Correction(kind=KIND_LANGUAGE, directive="Speak Hindi.").to_message()
    assert msg["role"] == "developer"
    assert msg["content"].startswith("SELF-CORRECTION:")


# --------------------------------------------------------------- the budget


def test_sink_stops_injecting_after_the_budget(on) -> None:
    """Four directives is the cap; a bot told what to fix on every turn stops
    sounding like an agent."""
    from voice.crm_sink import CrmSink
    from voice.session import VoiceSession

    sent: list = []

    async def scenario():
        sink = CrmSink(VoiceSession(session_id="VS-CRITIC1"))
        await sink.start()
        sink.configure_live_handlers(on_correction=lambda c: _record(c))

        for i in range(turn_critic.MAX_CORRECTIONS_PER_CALL + 3):
            sink.enqueue_critique(
                bot_text=f"turn {i}",
                user_text="hello",
                guardrail_flags=["prohibited:threat"],
                recent_bot_turns=[],
            )
        # Let the analysis drain run.
        for _ in range(40):
            await asyncio.sleep(0.01)
            if sink._analysis_queue.empty():
                break
        await asyncio.sleep(0.05)
        await sink.stop()

    async def _record(c):
        sent.append(c)

    asyncio.run(scenario())

    assert len(sent) <= turn_critic.MAX_CORRECTIONS_PER_CALL
    assert sent, "the critic produced nothing at all"
    assert all(c.kind == KIND_GUARDRAIL for c in sent)


def test_sink_does_nothing_without_a_correction_handler(on) -> None:
    from voice.crm_sink import CrmSink
    from voice.session import VoiceSession

    async def scenario():
        sink = CrmSink(VoiceSession(session_id="VS-CRITIC2"))
        await sink.start()
        sink.enqueue_critique(
            bot_text="x", user_text="y", guardrail_flags=["prohibited:threat"], recent_bot_turns=[]
        )
        assert sink._analysis_queue.empty()
        await sink.stop()

    asyncio.run(scenario())
