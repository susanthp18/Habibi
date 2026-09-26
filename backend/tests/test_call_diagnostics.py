"""The per-reply quality checks and the written-vs-spoken comparison.

These decide what a test call's ``diag.llm_out`` / ``diag.spoken`` lines flag,
so a check that misfires sends the next investigation the wrong way.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pipecat")

from voice.call_diagnostics import reply_flags, spoken_coverage  # noqa: E402


def _flags(text, *, name=None, previous=(), name_in_last=False):
    return reply_flags(text, name=name, previous=list(previous), name_in_last=name_in_last)[0]


def test_a_good_reply_raises_nothing():
    assert _flags("I've moved it to the tenth of October. Does that work for you?") == []


@pytest.mark.parametrize(
    "text, flag",
    [
        ("Your balance is INR 62,400. Shall we set a date?", "format"),
        ("It is due on 2026-10-03. Is that fine?", "format"),
        ("Your number ends 2324, correct?", "digits"),
        ("Would you like cover? Or a callback? Or both?", "multi_q"),
        ("Here are the options:\n- Basic\n- Gold\nWhich one?", "markup"),
        ("Hello {customer_name}, how are you?", "template"),
        ("I'm not able to help with that, is there anything else?", "deflect"),
        ("Sorry about that. Shall we continue?", "apology"),
        ("The payment has been recorded.", "no_q"),
    ],
)
def test_each_check_fires_on_its_case(text, flag):
    assert flag in _flags(text)


def test_a_closing_line_needs_no_question():
    assert "no_q" not in _flags("Thank you, have a good day. Goodbye.")


def test_a_long_reply_is_flagged():
    assert "long" in _flags(" ".join(["word"] * 50) + "?")


def test_the_name_twice_or_in_consecutive_replies():
    assert "name" in _flags("Susanth, thanks Susanth. Shall we?", name="Susanth P")
    assert "name" in _flags("Thanks Susanth. Shall we?", name="Susanth", name_in_last=True)
    assert "name" not in _flags("Thanks Susanth. Shall we?", name="Susanth")


def test_a_repeated_reply_and_opener():
    earlier = "I can move your payment date to the tenth of October for you today."
    flags, facts = reply_flags(
        "I can move your payment date to the tenth of October for you now.",
        name=None,
        previous=[earlier],
        name_in_last=False,
    )
    assert "repeat" in flags and facts["repeat_of"] == 1
    assert "same_opener" in flags


def test_spoken_against_written():
    covered, extra = spoken_coverage("Travel cover includes medical costs abroad.", "Travel cover includes")
    assert covered == 0.5 and extra == 0.0
    covered, extra = spoken_coverage("Yes.", "Sure, I can look that up. Yes.")
    assert covered == 1.0 and extra > 0.5


def test_one_call_through_the_observer(caplog):
    """Real pipecat frames, each pushed across three hops, read end to end."""
    import asyncio
    from types import SimpleNamespace

    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        BotStoppedSpeakingFrame,
        EndFrame,
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
        TranscriptionFrame,
        TTSTextFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )

    from voice.call_diagnostics import CallDiagnosticsObserver

    session = SimpleNamespace(session_id="VS-TEST", interaction_id="IX-1", extra={})
    obs = CallDiagnosticsObserver(session=session, name_getter=lambda: "Susanth")
    frames = [
        UserStartedSpeakingFrame(),
        UserStoppedSpeakingFrame(),
        TranscriptionFrame(text="I want something for my travel to Singapore", user_id="u", timestamp="t"),
        LLMFullResponseStartFrame(),
        LLMTextFrame(text="Travel Protect360 covers medical costs abroad. "),
        LLMTextFrame(text="Shall I tell you more?"),
        LLMFullResponseEndFrame(),
        BotStartedSpeakingFrame(),
        TTSTextFrame(text="Travel Protect360 covers medical costs abroad.", aggregated_by="sentence"),
        BotStoppedSpeakingFrame(),
        EndFrame(),
    ]

    sink = SimpleNamespace(name="Pipeline#1::Sink")

    async def run():
        for frame in frames:
            for hop in range(3):  # pipecat reports every hop
                await obs.on_push_frame(
                    SimpleNamespace(frame=frame, source=None, destination=sink if hop == 2 else None)
                )

    with caplog.at_level("WARNING", logger="voice.trace"):
        asyncio.run(run())
    lines = [r.getMessage() for r in caplog.records if r.name == "voice.trace"]
    kinds = [line.split()[1] for line in lines]
    assert kinds == ["diag.stt", "diag.llm_out", "diag.spoken", "diag.scorecard"], kinds
    spoken = next(line for line in lines if "diag.spoken" in line)
    assert "flags=unspoken" in spoken  # the question was written but never spoken
    card = lines[-1]
    assert "caller_turns=1" in card and "bot_responses=1" in card and "unspoken=1" in card


def _drive(obs, hops):
    import asyncio
    from types import SimpleNamespace

    async def run():
        for frame, source, destination in hops:
            await obs.on_push_frame(SimpleNamespace(frame=frame, source=source, destination=destination))

    asyncio.run(run())


def test_a_tool_only_reply_is_not_empty_and_hangup_waits_for_the_sink(caplog):
    """VS-36E9E26C13: every tool call was flagged empty, and the card missed the last turn."""
    from types import SimpleNamespace

    from pipecat.frames.frames import (
        EndFrame,
        FunctionCallInProgressFrame,
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
    )

    from voice.call_diagnostics import CallDiagnosticsObserver

    obs = CallDiagnosticsObserver(session=SimpleNamespace(session_id="VS-T", interaction_id="IX", extra={}))
    end = EndFrame()
    with caplog.at_level("WARNING", logger="voice.trace"):
        _drive(
            obs,
            [
                (LLMFullResponseStartFrame(), None, None),
                (LLMFullResponseEndFrame(), None, None),
                # Pipecat pushes the tool frame after the response end.
                (FunctionCallInProgressFrame(function_name="verify_identity", tool_call_id="t1", arguments={}), None, None),
                (end, None, None),  # queued: not the end of the call yet
                (LLMFullResponseStartFrame(), None, None),
                (LLMFullResponseEndFrame(), None, None),  # the closing reply, no words
                (end, None, SimpleNamespace(name="Pipeline#1::Sink")),
            ],
        )
    lines = [r.getMessage() for r in caplog.records if r.name == "voice.trace"]
    card = lines[-1]
    assert "diag.scorecard" in card and "bot_responses=2" in card, card
    assert "empty_replies=1" in card  # the closing one, not the tool call
    assert sum("diag.empty_reply" in line for line in lines) == 1


def test_an_interrupted_reply_reports_what_was_heard(caplog):
    """VS-58097BA530: 1s into a 16-word question was logged as all 16 words spoken."""
    from types import SimpleNamespace

    from pipecat.frames.frames import (
        BotStartedSpeakingFrame,
        InterruptionFrame,
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
        TTSTextFrame,
    )

    from voice.call_diagnostics import CallDiagnosticsObserver

    class FastAPIWebsocketOutputTransport:  # the class name is what is matched
        pass

    out = FastAPIWebsocketOutputTransport()
    obs = CallDiagnosticsObserver(session=SimpleNamespace(session_id="VS-T", interaction_id="IX", extra={}))
    first = TTSTextFrame(text="Thanks for confirming.", aggregated_by="sentence")
    second = TTSTextFrame(text="Could you share the last four digits?", aggregated_by="sentence")
    with caplog.at_level("WARNING", logger="voice.trace"):
        _drive(
            obs,
            [
                (LLMFullResponseStartFrame(), None, None),
                (LLMTextFrame(text="Thanks for confirming. Could you share the last four digits?"), None, None),
                (LLMFullResponseEndFrame(), None, None),
                (BotStartedSpeakingFrame(), None, None),
                (first, None, None),  # synthesised
                (second, None, None),  # synthesised
                (first, out, None),  # played
                (InterruptionFrame(), None, None),
            ],
        )
    spoken = next(r.getMessage() for r in caplog.records if "diag.spoken" in r.getMessage())
    assert "spoken=Thanks for confirming." in spoken and "digits" not in spoken.split("spoken=")[1]
