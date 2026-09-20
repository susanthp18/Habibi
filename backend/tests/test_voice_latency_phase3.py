"""Phase 3 remaining caller-time latency defects.

Each test pins a code fault rather than a tuning choice: setup hops that ran
in series, a greeting that waited on a customer existence check, a TTS
handshake that blocked Flow init, and Connection.open colliding with synthesis.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import StartFrame, TTSAudioRawFrame

from voice import bot_flow, tts_pool


def _call(*, call_type: str = "inbound", attempt_id: str | None = None, **extra_body):
    body = {"call_type": call_type, **extra_body}
    if attempt_id is not None:
        body["attempt_id"] = attempt_id
    call_data = SimpleNamespace(
        from_number="+919876543210",
        to_number="+911140000000",
        body=body,
        provider="twilio",
        call_id="CA-1",
    )
    return SimpleNamespace(
        runner_args=SimpleNamespace(
            call_data=call_data,
            transport_type="twilio",
            body=None,
            session_id=None,
        )
    )


def _stub_bundle(monkeypatch, seen: dict):
    def fake_bundle(**kwargs):
        seen.update(kwargs)
        return {
            "deploymentId": "D-1",
            "botId": kwargs.get("bot_id") or "default-bot",
            "prompt": "Be brief.",
            "persona": {},
            "guardrails": {},
            "voice": {},
            "voiceConfig": {},
            "ttsVoiceId": None,
            "tuning": {},
        }

    monkeypatch.setattr(bot_flow, "load_active_bundle", fake_bundle)
    monkeypatch.setattr(bot_flow, "_system_instruction_from_bundle", lambda *_a, **_k: "sys")
    monkeypatch.setattr(bot_flow, "CrmSink", lambda *_a, **_k: SimpleNamespace())


# --------------------------------------------------------------- 3.3 resolve_call


def test_attempt_bot_id_wins_over_entry_and_ani(monkeypatch):
    """Identity before canary: the attempt row's mouth is the one that answers."""
    seen: dict = {}
    _stub_bundle(monkeypatch, seen)
    entry_calls: list = []
    caller_calls: list = []

    monkeypatch.setattr(
        bot_flow,
        "_attempt_cohort",
        lambda _id: {"customer_id": "C-from-attempt", "bot_id": "bot-from-attempt"},
    )
    monkeypatch.setattr(bot_flow, "_entry_bot", lambda addr: entry_calls.append(addr) or "bot-from-entry")
    monkeypatch.setattr(
        bot_flow,
        "_caller_match",
        lambda ani: caller_calls.append(ani) or {"customerId": "C-from-ani"},
    )
    monkeypatch.setattr(bot_flow, "_load_mission_row", lambda _id: None)

    call = _call(call_type="outbound", attempt_id="ATT-1")
    asyncio.run(bot_flow.resolve_call(call))

    assert seen["bot_id"] == "bot-from-attempt"
    assert seen["customer_id"] == "C-from-attempt"
    assert entry_calls == [], "entry ran even though the attempt already named the mouth"
    # ANI at this stage is skipped once the attempt has a customer; the later
    # pstn_customer lookup may still fire, which is identity for verify, not routing.


def test_ani_and_entry_run_concurrently_when_both_unset(monkeypatch):
    """Two independent DB hops used to sit in series on the silent line."""
    seen: dict = {}
    _stub_bundle(monkeypatch, seen)
    caller_entered = threading.Event()
    entry_entered = threading.Event()

    def fake_caller(_ani):
        caller_entered.set()
        assert entry_entered.wait(timeout=2), "entry did not start while ANI was in flight"
        return {"customerId": "C-ani"}

    def fake_entry(_addr):
        entry_entered.set()
        assert caller_entered.wait(timeout=2), "ANI did not start while entry was in flight"
        return "bot-from-entry"

    monkeypatch.setattr(bot_flow, "_caller_match", fake_caller)
    monkeypatch.setattr(bot_flow, "_entry_bot", fake_entry)

    call = _call(call_type="inbound")
    asyncio.run(bot_flow.resolve_call(call))

    assert seen["bot_id"] == "bot-from-entry"
    assert seen["customer_id"] == "C-ani"


def test_mission_io_starts_during_resolve_and_load_mission_does_not_reload(monkeypatch):
    seen: dict = {}
    _stub_bundle(monkeypatch, seen)
    loads: list[str] = []

    def fake_load(attempt_id: str):
        loads.append(attempt_id)
        return {"decisionId": None, "customerName": "Ada"}

    monkeypatch.setattr(bot_flow, "_attempt_cohort", lambda _id: {"customer_id": "C-1", "bot_id": "bot-1"})
    monkeypatch.setattr(bot_flow, "_load_mission_row", fake_load)
    monkeypatch.setattr(bot_flow, "_entry_bot", lambda _a: "unused")
    monkeypatch.setattr(bot_flow, "_caller_match", lambda _a: None)

    call = _call(call_type="outbound", attempt_id="ATT-9")
    asyncio.run(bot_flow.resolve_call(call))
    assert getattr(call, "_mission_io_task", None) is not None
    asyncio.run(bot_flow.load_mission(call))

    assert loads == ["ATT-9"], "load_mission started a second mission read"
    assert call.session.extra.get("mission", {}).get("customerName") == "Ada"


# --------------------------------------- 3.3 greeting does not wait on customer


def test_initialize_does_not_await_resolve_known_customer() -> None:
    """The existence check used to sit in front of FlowManager.initialize."""
    from tests.voice_tools_source import handlers_source

    src = handlers_source()
    start = src.index("async def on_client_connected")
    init = src.index("await flow_manager.initialize", start)
    connect = src[start:init]
    assert "resolve_known_customer" not in connect
    bind = src[src.index("async def _bind_crm_session(") : start]
    assert "resolve_known_customer" in bind


# --------------------------------------------------------------- 3.3 TTS interlock


class _Tts(tts_pool.KeepAliveAzureTTSService):
    """KeepAlive methods without Azure SDK construction."""

    def __init__(self) -> None:  # noqa: D107
        self._speech_synthesizer = object()
        self._preopen_task = None
        self._sample_rate = 16000
        self._cumulative_audio_offset = 0.0
        self.synth_calls: list[str] = []

    @property
    def sample_rate(self):
        return self._sample_rate

    def _construct_ssml(self, text: str) -> str:
        return f"<speak>{text}</speak>"

    async def _azure(self, text, context_id):
        self.synth_calls.append(text)
        yield TTSAudioRawFrame(
            audio=b"\x00\x01" * 8,
            sample_rate=self.sample_rate,
            num_channels=1,
            context_id=context_id,
        )


@pytest.fixture
def tts_stubs(monkeypatch):
    async def _noop_start(self, frame):
        return None

    monkeypatch.setattr(tts_pool.AzureTTSService, "start", _noop_start)
    monkeypatch.setattr(
        tts_pool.AzureTTSService,
        "run_tts",
        lambda self, text, context_id: self._azure(text, context_id),
        raising=False,
    )
    monkeypatch.setenv("VOICE_TTS_PHRASE_CACHE", "0")
    return None


def test_tts_start_does_not_wait_on_handshake_and_run_tts_opens_once(tts_stubs, monkeypatch):
    """start() used to await Connection.open (5s ceiling) in front of Flow init.

    run_tts must join that task, never call open() itself — that collision is
    the 41s deadlock.
    """
    opens: list[int] = []
    entered = threading.Event()
    release = threading.Event()

    class _Conn:
        def open(self, _ok):
            opens.append(1)
            entered.set()
            assert release.wait(timeout=2), "run_tts never joined the pre-open"

    class FakeConnection:
        @staticmethod
        def from_speech_synthesizer(_s):
            return _Conn()

    monkeypatch.setattr(tts_pool, "Connection", FakeConnection)

    svc = _Tts()

    async def go():
        t0 = time.monotonic()
        await svc.start(StartFrame())
        start_waited = time.monotonic() - t0
        assert start_waited < 0.2, f"start() blocked on handshake for {start_waited:.2f}s"
        assert svc._preopen_task is not None

        for _ in range(50):
            if entered.is_set():
                break
            await asyncio.sleep(0.02)
        assert entered.is_set(), "pre-open never reached Connection.open"
        assert not svc._preopen_task.done()

        synth = asyncio.create_task(_drain(svc, "hello"))
        await asyncio.sleep(0.05)
        assert len(opens) == 1, "run_tts started a second open while pre-open was live"
        release.set()
        frames = await synth
        await svc._preopen_task
        return frames

    frames = asyncio.run(go())
    assert len(opens) == 1
    assert svc.synth_calls == ["hello"]
    assert frames and isinstance(frames[0], TTSAudioRawFrame)


async def _drain(svc, text):
    return [f async for f in svc.run_tts(text, "ctx")]
