"""The voicemail classifier may read what the callee said, and nothing else.

`VoicemailDetector` is a `ParallelPipeline`: every frame entering it is copied
into both branches. One branch is the conversation; the other is a small LLM
whose only job is to answer CONVERSATION or VOICEMAIL.

`pipecat-flows` drives the call by pushing `LLMMessagesAppendFrame` downstream
when it enters a node. Those reached the classifier branch too, where its
aggregator appended them to the *classifier's* context -- so the classifier read
the collections agent's own script:

    "You placed this call. Open by greeting them ... call me back ..."

That text is dense with the phrases the classifier's own rules list as voicemail
evidence. On a live call it returned VOICEMAIL 1.1 seconds after connect, before
the human who had answered had said a word. The caller then heard the greeting
twice and a voicemail message.

Two things made it expensive to find: the misclassification and the duplicated
greeting looked like separate bugs, and neither produced an error anywhere.
"""

from __future__ import annotations

import pytest


def _frame(name: str):
    """Build a real pipecat frame by class name."""
    from pipecat.frames import frames as F

    cls = getattr(F, name)
    if name == "LLMMessagesAppendFrame":
        return cls(messages=[{"role": "developer", "content": "You placed this call."}])
    if name == "LLMMessagesUpdateFrame":
        return cls(messages=[{"role": "developer", "content": "replaced"}])
    if name == "LLMSetToolsFrame":
        return cls(tools=[])
    if name == "TranscriptionFrame":
        return cls(text="Hello?", user_id="u", timestamp="2026-08-29T00:00:00Z")
    raise AssertionError(name)


# --- what the guard blocks --------------------------------------------------


def _named(name: str):
    """The guard keys on ``type(frame).__name__``, not the import path."""

    return type(name, (), {})()


@pytest.mark.parametrize(
    "name",
    [
        "LLMMessagesAppendFrame",
        "LLMMessagesUpdateFrame",
        "LLMSetToolsFrame",
        "LLMUpdateSettingsFrame",
        "FunctionCallsStartedFrame",
        "FunctionCallInProgressFrame",
        "FunctionCallResultFrame",
        "FunctionCallCancelFrame",
    ],
)
def test_context_mutating_frames_never_reach_the_classifier(name: str) -> None:
    """These change what the classifier *is*, not what it heard."""
    from voice.amd import _ClassifierContextGuard

    frame = _named(name) if name not in {
        "LLMMessagesAppendFrame",
        "LLMMessagesUpdateFrame",
        "LLMSetToolsFrame",
    } else _frame(name)
    assert _ClassifierContextGuard.blocks(frame) is True
    assert _ClassifierContextGuard().allow(frame) is False


def test_the_callee_transcription_still_reaches_the_classifier() -> None:
    """Blocking everything would be a different bug with the same symptom.

    The classifier has to hear "Hello?" to answer CONVERSATION; a guard that
    starved it would leave every call undecided.
    """
    from voice.amd import _ClassifierContextGuard

    assert _ClassifierContextGuard.blocks(_frame("TranscriptionFrame")) is False


# --- the wiring -------------------------------------------------------------


def test_the_detector_is_built_with_the_guard_in_the_classifier_branch() -> None:
    """Both branches present, and the guard only in the classifier's."""
    from pipecat.processors.filters.function_filter import FunctionFilter

    from voice.amd import build_voicemail_detector

    detector = build_voicemail_detector(llm=_StubLLM())
    branches = detector.processors
    assert len(branches) == 2, "conversation branch + classifier branch"

    conversation, classifier = branches
    conv_types = [type(p).__name__ for p in conversation.processors]
    clas_types = [type(p).__name__ for p in classifier.processors]

    assert not any(t == FunctionFilter.__name__ for t in conv_types), (
        "the real LLM must keep receiving the flow's context updates"
    )
    assert FunctionFilter.__name__ in clas_types, (
        "the classifier branch must be guarded"
    )
    # Order matters: the guard protects the aggregator, so it must precede it.
    guard_at = clas_types.index(FunctionFilter.__name__)
    agg_at = next(
        i for i, t in enumerate(clas_types) if "Aggregator" in t or "aggregator" in t
    )
    assert guard_at < agg_at


def test_bot_builds_the_detector_through_the_guarded_helper() -> None:
    """A future edit that reaches for the raw constructor reopens the bug."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "voice" / "bot.py").read_text(encoding="utf-8")
    assert "amd.build_voicemail_detector(" in src
    assert "VoicemailDetector(llm=" not in src, (
        "constructing the library detector directly skips the guard"
    )


def _StubLLM():
    """A real `FrameProcessor` standing in for the classifier LLM.

    `Pipeline` links its processors at construction, so this has to be the real
    base class — a bare object fails with `no attribute 'link'` and tells you
    nothing about the wiring under test.
    """
    from pipecat.processors.frame_processor import FrameProcessor

    return FrameProcessor(name="stub-classifier")


# --- no speech, no classification -------------------------------------------


def _ctx_frame():
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.aggregators.llm_context import LLMContext

    return LLMContextFrame(context=LLMContext([]))


def test_the_classifier_does_not_run_before_anyone_speaks() -> None:
    """Removing the wrong evidence exposed that there was no evidence.

    With the flow's script filtered out, the classifier still ran -- on an empty
    context. A VAD blip on answer (the connect tone, a breath) closes a user
    turn with no transcription and the aggregator pushes a context frame
    regardless. Asked to classify silence the model guesses, and on a live call
    it guessed VOICEMAIL against a human who had said nothing yet.
    """
    from voice.amd import _ClassifierContextGuard

    guard = _ClassifierContextGuard()
    assert guard.allow(_ctx_frame()) is False, "inference must wait for speech"


def test_speech_opens_the_gate() -> None:
    from voice.amd import _ClassifierContextGuard

    guard = _ClassifierContextGuard()
    assert guard.allow(_frame("TranscriptionFrame")) is True
    assert guard.seen_speech is True
    assert guard.allow(_ctx_frame()) is True, "after real words, classify freely"


def test_empty_transcriptions_do_not_count_as_speech() -> None:
    """An empty transcription is the silence that caused this, not evidence."""
    from pipecat.frames.frames import TranscriptionFrame

    from voice.amd import _ClassifierContextGuard

    guard = _ClassifierContextGuard()
    blank = TranscriptionFrame(text="   ", user_id="u", timestamp="2026-08-29T00:00:00Z")
    guard.allow(blank)
    assert guard.seen_speech is False
    assert guard.allow(_ctx_frame()) is False


def test_each_call_gets_its_own_gate() -> None:
    """Two concurrent calls must not share "has anyone spoken yet"."""
    from voice.amd import _ClassifierContextGuard

    a, b = _ClassifierContextGuard(), _ClassifierContextGuard()
    a.allow(_frame("TranscriptionFrame"))
    assert a.seen_speech is True
    assert b.seen_speech is False
    assert b.allow(_ctx_frame()) is False


def test_the_script_is_still_blocked_after_speech_starts() -> None:
    """The two rules are independent: speech never licenses reading the flow."""
    from voice.amd import _ClassifierContextGuard

    guard = _ClassifierContextGuard()
    guard.allow(_frame("TranscriptionFrame"))
    assert guard.allow(_frame("LLMMessagesAppendFrame")) is False


def test_punctuation_is_not_callee_speech() -> None:
    from pipecat.frames.frames import TranscriptionFrame

    from voice.amd import _ClassifierContextGuard

    guard = _ClassifierContextGuard()
    noise = TranscriptionFrame(text=".", user_id="u", timestamp="2026-08-29T00:00:00Z")
    guard.allow(noise)
    assert guard.seen_speech is False
    assert guard.allow(_ctx_frame()) is False


def test_demo_calls_skip_amd() -> None:
    from voice.amd import is_demo_call, should_enable_amd

    extra = {"twilio_params": {"call_type": "outbound", "demo": "1"}}
    assert is_demo_call(extra) is True
    assert should_enable_amd(extra, is_twilio=True) is False
    assert should_enable_amd(
        {"twilio_params": {"call_type": "outbound"}}, is_twilio=True
    ) is True


def test_voicemail_does_not_act_before_the_callee_speaks() -> None:
    from types import SimpleNamespace

    from voice.amd import voicemail_action_allowed

    session = SimpleNamespace(extra={})
    assert voicemail_action_allowed(session) == "no_callee_speech"
    assert (
        voicemail_action_allowed(session, bot_speaking=True, bot_has_spoken=True, guard=SimpleNamespace(seen_speech=True))
        == "bot_already_speaking"
    )
    assert (
        voicemail_action_allowed(session, bot_has_spoken=False, guard=SimpleNamespace(seen_speech=True))
        == "greeting_incomplete"
    )
    session.extra["amd"] = "human"
    assert voicemail_action_allowed(session, bot_has_spoken=True, guard=SimpleNamespace(seen_speech=True)) == "already_decided"


def test_voicemail_may_act_after_greeting_and_callee_speech() -> None:
    from types import SimpleNamespace

    from voice.amd import voicemail_action_allowed

    session = SimpleNamespace(extra={})
    assert (
        voicemail_action_allowed(
            session,
            bot_speaking=False,
            bot_has_spoken=True,
            guard=SimpleNamespace(seen_speech=True),
        )
        is None
    )


def test_closed_guard_stops_further_classification() -> None:
    from voice.amd import _ClassifierContextGuard

    guard = _ClassifierContextGuard()
    guard.allow(_frame("TranscriptionFrame"))
    guard.closed = True
    assert guard.allow(_ctx_frame()) is False


def test_bot_does_not_force_prewarm_on_connect() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "voice" / "bot.py").read_text(encoding="utf-8")
    assert "prewarm_llm_connection(force=True)" not in src


def test_bot_binds_inbound_ani() -> None:
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "voice" / "bot.py").read_text(encoding="utf-8")
    assert "customer_id_for_bind" in src
    assert "pstn_customer" in src


def test_voicemail_handler_does_not_speak_over_a_live_greeting() -> None:
    """VS-4D8667B522: VOICEMAIL arrived while the greeting was still playing."""
    import asyncio
    from types import SimpleNamespace

    from voice.amd import attach_voicemail_handlers

    class _Det:
        def event_handler(self, name):
            def deco(fn):
                setattr(self, name, fn)
                return fn

            return deco

    spoken: list[object] = []

    class _Proc:
        async def push_frame(self, *a, **_k):
            spoken.append(a[0] if a else None)

    async def _run() -> None:
        det = _Det()
        session = SimpleNamespace(session_id="VS-4D8667B522", extra={}, interaction_id=None)
        await attach_voicemail_handlers(
            voicemail_detector=det,
            session=session,
            sink=SimpleNamespace(),
            worker=SimpleNamespace(),
            bot_turn_state=SimpleNamespace(
                speaking=lambda: True,
                busy=lambda: True,
                has_spoken=lambda: True,
            ),
        )
        det._habibi_guard = SimpleNamespace(seen_speech=True)
        await det.on_voicemail_detected(_Proc())
        assert spoken == []
        assert session.extra.get("amd") != "voicemail"

    asyncio.run(_run())


def test_skill_clone_source_does_not_use_window_prompt() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1].parent / "Habibi" / "src" / "routes" / "agent-studio.skills.index.tsx"
    if not root.exists():
        root = Path(__file__).resolve().parents[2] / "Habibi" / "src" / "routes" / "agent-studio.skills.index.tsx"
    text = root.read_text(encoding="utf-8")
    assert "window.prompt" not in text
    assert "clonePending" in text
