"""Remaining voice-latency leftovers after Phase 3.

Each test pins one cluster from the grounded leftovers plan: hangup silence,
STT per-call pre-open, filler-after-barge, bundle hash cache, first-clause TTS,
Smart Turn cpu_count, off-aggregator summarisation, tripwire split, setup clock.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import StartFrame

from agent_core.tuning import default_tuning, normalize_tuning
from voice.bot_handlers import should_skip_filler
from voice.bot_pipeline import (
    context_needs_summary,
    emit_first_token_traces,
    summarise_context_after_assistant_turn,
)
from voice.first_clause import FirstClauseTextAggregator
from voice.stt_service import OverlappedAzureSTTService
from voice.turn_probe import SpokeThisResponseProbe


# --------------------------------------------------------------- cluster 1 hangup


def test_transport_params_send_no_silence_after_endframe():
    from pipecat.evals.transport import EvalTransportParams
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams

    from voice.asterisk_ws import asterisk_transport_params
    from voice.bot import transport_params

    ctors = transport_params()
    eval_p = ctors["eval"]()
    twilio_p = ctors["twilio"]()
    webrtc_p = ctors["webrtc"]()
    assert isinstance(eval_p, EvalTransportParams)
    assert isinstance(twilio_p, FastAPIWebsocketParams)
    assert isinstance(webrtc_p, TransportParams)
    assert eval_p.audio_out_end_silence_secs == 0
    assert twilio_p.audio_out_end_silence_secs == 0
    assert webrtc_p.audio_out_end_silence_secs == 0
    asterisk_p = asterisk_transport_params(SimpleNamespace(optimal_frame_size=640))
    assert asterisk_p.audio_out_end_silence_secs == 0


# --------------------------------------------------------------- cluster 2 STT pre-open


class _Stt(OverlappedAzureSTTService):
    def __init__(self) -> None:  # noqa: D107
        self._speech_recognizer = object()
        self._preopen_task = None
        self.writes: list[bytes] = []

    async def run_parent(self, audio):
        self.writes.append(audio)
        yield None


@pytest.fixture
def stt_stubs(monkeypatch):
    async def _noop_start(self, frame):
        return None

    monkeypatch.setattr(OverlappedAzureSTTService.__bases__[0], "start", _noop_start)

    async def _parent_run(self, audio):
        async for frame in self.run_parent(audio):
            yield frame

    monkeypatch.setattr(OverlappedAzureSTTService.__bases__[0], "run_stt", _parent_run)
    return None


def test_stt_start_does_not_wait_on_handshake_and_run_stt_opens_once(stt_stubs, monkeypatch):
    from voice import stt_service

    opens: list[int] = []
    entered = threading.Event()
    release = threading.Event()

    class _Conn:
        def open(self, _ok):
            opens.append(1)
            entered.set()
            assert release.wait(timeout=2), "run_stt never joined the pre-open"

    class FakeConnection:
        @staticmethod
        def from_recognizer(_s):
            return _Conn()

    monkeypatch.setattr(stt_service, "Connection", FakeConnection)
    svc = _Stt()

    async def go():
        t0 = time.monotonic()
        await svc.start(StartFrame())
        assert (time.monotonic() - t0) < 0.2, "start() blocked on handshake"
        assert svc._preopen_task is not None
        for _ in range(50):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set(), "pre-open never reached Connection.open"
        assert not svc._preopen_task.done()

        synth = asyncio.create_task(_drain_stt(svc, b"\x00\x01"))
        await asyncio.sleep(0.05)
        assert len(opens) == 1, "run_stt started a second open while pre-open was live"
        assert not synth.done()
        release.set()
        frames = await synth
        await svc._preopen_task
        return frames

    frames = asyncio.run(go())
    assert len(opens) == 1
    assert svc.writes == [b"\x00\x01"]
    assert frames == [None]


async def _drain_stt(svc, audio):
    return [f async for f in svc.run_stt(audio)]


# --------------------------------------------------------------- cluster 3 filler


def test_filler_skipped_when_interrupted_or_tts_busy():
    probe = SpokeThisResponseProbe()
    probe._interrupted = True
    tts = SimpleNamespace(_processing_text=False, _playing_context_id=None)
    assert should_skip_filler(probe, tts) is True

    probe = SpokeThisResponseProbe()
    tts = SimpleNamespace(_processing_text=True, _playing_context_id=None)
    assert should_skip_filler(probe, tts) is True

    probe = SpokeThisResponseProbe()
    tts = SimpleNamespace(_processing_text=False, _playing_context_id="ctx")
    assert should_skip_filler(probe, tts) is True

    probe = SpokeThisResponseProbe()
    tts = SimpleNamespace(_processing_text=False, _playing_context_id=None)
    assert should_skip_filler(probe, tts) is False


# --------------------------------------------------------------- cluster 4 bundle cache


def test_bundle_cache_skips_parity_on_same_hash(monkeypatch):
    from agent_core import deployment

    deployment.clear_bundle_cache()
    seen: list[str] = []

    def _parity(bundle):
        seen.append(bundle["bundleHash"])
        bundle["prompt"] = "compiled:" + bundle["bundleHash"]

    monkeypatch.setattr(deployment, "_dual_compute_parity", _parity)

    first = {"botId": "b1", "deploymentId": "d1", "bundleHash": "h1", "prompt": "live"}
    second = {"botId": "b1", "deploymentId": "d1", "bundleHash": "h1", "prompt": "live"}
    third = {"botId": "b1", "deploymentId": "d1", "bundleHash": "h2", "prompt": "live"}
    deployment._install_compiled(first, bot_id="b1", environment="production")
    deployment._install_compiled(second, bot_id="b1", environment="production")
    deployment._install_compiled(third, bot_id="b1", environment="production")
    assert seen == ["h1", "h2"]
    assert second["prompt"] == "compiled:h1"
    deployment.clear_bundle_cache()


# --------------------------------------------------------------- cluster 5 first clause


def test_first_clause_flushes_on_comma_then_waits_for_sentence():
    async def go():
        agg = FirstClauseTextAggregator()
        chunks = []
        async for item in agg.aggregate(
            "Sure, I can look that up for you right away."
        ):
            chunks.append(item.text)
        leftover = await agg.flush()
        if leftover and leftover.text:
            chunks.append(leftover.text)
        return chunks

    chunks = asyncio.run(go())
    assert chunks[0] == "Sure,"
    assert any("look that up" in c for c in chunks[1:])
    assert not any(c.endswith("away.") and c.startswith("Sure") for c in chunks), (
        "the rest of the sentence was released with the first clause"
    )


def test_default_aggregation_stays_sentence():
    assert default_tuning()["tts"]["text_aggregation_mode"] == "SENTENCE"
    assert normalize_tuning({})["tts"]["text_aggregation_mode"] == "SENTENCE"


# --------------------------------------------------------------- cluster 6 defaults


def test_stop_secs_default_is_one_point_five():
    assert default_tuning()["turn"]["stop_secs"] == pytest.approx(1.5)
    assert normalize_tuning({})["turn"]["stop_secs"] == pytest.approx(1.5)
    t = default_tuning()
    t["turn"]["stop_timeout_secs"] = 0.1
    assert normalize_tuning(t)["turn"]["stop_timeout_secs"] == pytest.approx(2.0)


# --------------------------------------------------------------- cluster 7 cpu_count


def test_smart_turn_builder_passes_cpu_count_two(monkeypatch):
    from voice import analyzer_pool
    from voice.tuning_apply import build_smart_turn_analyzer

    seen: dict = {}

    class _Fake:
        def __init__(self, *, params, cpu_count=1):
            seen["cpu_count"] = cpu_count
            seen["params"] = params

    monkeypatch.setattr(
        "pipecat.audio.turn.smart_turn.local_smart_turn_v3.LocalSmartTurnAnalyzerV3",
        _Fake,
    )
    monkeypatch.setattr(analyzer_pool, "take", lambda key, build: build())
    build_smart_turn_analyzer({})
    assert seen["cpu_count"] == 2


# --------------------------------------------------------------- cluster 8 summarisation


class _Ctx:
    def __init__(self, messages):
        self._messages = messages

    @property
    def messages(self):
        return self._messages

    def set_messages(self, messages):
        self._messages = list(messages)

    def get_messages(self):
        return list(self._messages)


def test_tool_in_progress_does_not_summarise():
    ctx = _Ctx(
        [{"role": "system", "content": "x"}]
        + [{"role": "user", "content": f"m{i}"} for i in range(40)]
        + [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "get_account_position"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "IN_PROGRESS"},
        ]
    )
    assert context_needs_summary(ctx) is False


def test_long_completed_exchange_summarises_off_task(monkeypatch):
    ctx = _Ctx(
        [{"role": "system", "content": "role"}]
        + [{"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i} " * 20} for i in range(40)]
    )
    assert context_needs_summary(ctx) is True
    monkeypatch.setattr(
        "voice.bot_pipeline._run_collections_summary", lambda _t: "Caller asked about balance."
    )
    asyncio.run(summarise_context_after_assistant_turn(ctx))
    roles = [m.get("role") for m in ctx.messages]
    assert "Conversation summary: Caller asked about balance." in (
        ctx.messages[1].get("content") if len(ctx.messages) > 1 else ""
    )
    assert roles[0] == "system"


# --------------------------------------------------------------- cluster 9 tripwire split


def test_hold_awaits_but_language_does_not_block(monkeypatch):
    from voice.crm_sink import CrmSink
    from voice.session import VoiceSession

    monkeypatch.setattr("voice.persist.score_customer_text", lambda t: (0.0, "neutral"))
    sink = CrmSink(VoiceSession(session_id="VS-TW", interaction_id="IX-TW"))
    hold_entered = asyncio.Event()
    hold_release = asyncio.Event()
    lang_started = asyncio.Event()
    lang_still_running = []

    async def on_hold():
        hold_entered.set()
        await hold_release.wait()

    async def on_language(_lang):
        lang_started.set()
        lang_still_running.append(True)
        await asyncio.sleep(5)
        lang_still_running.append(False)

    sink.configure_live_handlers(on_hold=on_hold, on_language=on_language)

    class _Agg:
        def __init__(self):
            self.handlers = {}

        def event_handler(self, name):
            def wrap(fn):
                self.handlers[name] = fn
                return fn

            return wrap

    user, assistant = _Agg(), _Agg()
    sink.attach_aggregators(user, assistant)

    async def go():
        hold_task = asyncio.create_task(
            user.handlers["on_user_turn_stopped"](
                None, None, SimpleNamespace(content="ruko zara")
            )
        )
        await asyncio.wait_for(hold_entered.wait(), timeout=1)
        assert not hold_task.done(), "hold must still be awaited before the handler returns"
        hold_release.set()
        await asyncio.wait_for(hold_task, timeout=1)

        lang_task = asyncio.create_task(
            user.handlers["on_user_turn_stopped"](
                None, None, SimpleNamespace(content="namaste kya haal")
            )
        )
        await asyncio.wait_for(lang_task, timeout=1)
        await asyncio.wait_for(lang_started.wait(), timeout=1)
        assert lang_still_running == [True], "language switch was awaited on the aggregator"

    asyncio.run(go())


# --------------------------------------------------------------- cluster 10 setup clock


def test_first_tts_tags_waited_from_ws_or_setup():
    seen: list[tuple[str, dict]] = []

    def trace(name: str, **fields):
        seen.append((name, fields))

    emit_first_token_traces(trace, text="Hello", waited_s=1.5, waited_from="ws")
    assert seen[0][1]["waited_from"] == "ws"
    assert seen[0][1]["waited_s"] == 1.5

    seen.clear()
    emit_first_token_traces(trace, text="Hello", waited_s=0.4, waited_from="setup")
    assert seen[0][1]["waited_from"] == "setup"
