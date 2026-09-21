"""The language switch must not drop the caller's audio (Phase 2.6).

Stock Pipecat 1.6.0 closes the push stream and nulls ``_audio_stream`` before
building the replacement; ``run_stt`` writes only ``if self._audio_stream:``,
so every frame in that window is discarded -- on a switch that fires precisely
because the caller has just started a sentence in the new language.
"""

from __future__ import annotations

import asyncio

import pytest

from voice.stt_service import OverlappedAzureSTTService


class _Signal:
    def __init__(self) -> None:
        self.connected = 0
        self.disconnected = False

    def connect(self, _cb):
        self.connected += 1

    def disconnect_all(self):
        self.disconnected = True


class _Recognizer:
    def __init__(self, **_kw) -> None:
        self.recognizing = _Signal()
        self.recognized = _Signal()
        self.canceled = _Signal()
        self.started = False
        self.stopped = False

    def start_continuous_recognition_async(self):
        self.started = True

    def stop_continuous_recognition_async(self):
        self.stopped = True


class _Stream:
    def __init__(self, *_a, **_kw) -> None:
        self.closed = False
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        if self.closed:
            raise AssertionError("wrote to a closed stream")
        self.writes.append(data)

    def close(self) -> None:
        self.closed = True


class _Svc(OverlappedAzureSTTService):
    """The subclass with the SDK and the base __init__ stubbed out."""

    def __init__(self) -> None:  # noqa: D107
        self._speech_config = type("C", (), {"speech_recognition_language": "en-IN"})()
        self._audio_stream = _Stream()
        self._speech_recognizer = _Recognizer()
        self._sample_rate = 16000

    @property
    def sample_rate(self):
        return self._sample_rate

    def _on_handle_recognizing(self, *_a): ...
    def _on_handle_recognized(self, *_a): ...
    def _on_handle_canceled(self, *_a): ...


@pytest.fixture
def patched(monkeypatch):
    import azure.cognitiveservices.speech as speech
    import azure.cognitiveservices.speech.audio as audio

    monkeypatch.setattr(speech, "SpeechRecognizer", _Recognizer)
    monkeypatch.setattr(audio, "PushAudioInputStream", _Stream)
    monkeypatch.setattr(audio, "AudioStreamFormat", lambda **kw: object())
    monkeypatch.setattr(audio, "AudioConfig", lambda **kw: object())
    return _Svc()


def test_the_stream_is_never_none_during_a_swap(patched):
    """The whole point. A None stream is a dropped frame."""
    svc = patched
    seen: list[object] = []

    original = svc._swap_recognizer

    async def watched():
        # Snapshot the stream at the moment the new recogniser is being built.
        seen.append(svc._audio_stream)
        await original()
        seen.append(svc._audio_stream)

    svc._swap_recognizer = watched
    asyncio.run(svc._swap_recognizer())

    assert all(s is not None for s in seen), "audio would have been dropped"


def test_the_old_recognizer_is_retired_only_after_the_new_one_starts(patched):
    svc = patched
    old_recognizer = svc._speech_recognizer
    old_stream = svc._audio_stream

    asyncio.run(svc._swap_recognizer())

    assert svc._speech_recognizer is not old_recognizer
    assert svc._audio_stream is not old_stream
    assert svc._speech_recognizer.started, "the replacement was never started"
    assert old_recognizer.stopped, "the old recogniser was left running"
    assert old_stream.closed, "the old stream was leaked"


def test_a_late_result_from_the_old_recognizer_cannot_land(patched):
    """It would arrive through the same callbacks, in the locale the caller
    just switched away from."""
    svc = patched
    old = svc._speech_recognizer
    asyncio.run(svc._swap_recognizer())
    assert old.recognizing.disconnected
    assert old.recognized.disconnected
    assert old.canceled.disconnected


def test_a_failed_swap_keeps_the_caller_audible(patched, monkeypatch):
    """Degrade to 'wrong language', never to 'no transcription'."""
    import azure.cognitiveservices.speech as speech

    def boom(**_kw):
        raise RuntimeError("azure unavailable")

    monkeypatch.setattr(speech, "SpeechRecognizer", boom)

    svc = patched
    live_recognizer = svc._speech_recognizer
    live_stream = svc._audio_stream

    asyncio.run(svc._swap_recognizer())

    assert svc._speech_recognizer is live_recognizer
    assert svc._audio_stream is live_stream
    assert not live_stream.closed
    live_stream.write(b"still hearing them")


def test_the_new_recognizer_is_wired_to_the_same_callbacks(patched):
    svc = patched
    asyncio.run(svc._swap_recognizer())
    new = svc._speech_recognizer
    assert new.recognizing.connected == 1
    assert new.recognized.connected == 1
    assert new.canceled.connected == 1


def test_it_subclasses_the_real_service_so_settings_stay_identical():
    from pipecat.services.azure.stt import AzureSTTService

    assert issubclass(OverlappedAzureSTTService, AzureSTTService)
    # Only the reconnect is replaced; everything else is inherited.
    overridden = {
        n for n, v in vars(OverlappedAzureSTTService).items() if callable(v)
    }
    assert overridden == {
        "_update_settings",
        "_swap_recognizer",
        "__init__",
        "_apply_segmentation_silence",
        "start",
        "run_stt",
        "_preopen",
        "_await_preopen",
    }, overridden
