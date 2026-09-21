"""Cached audio for the fixed spoken assets (Phase 2.4).

The filler exists to mask tool latency, so paying an Azure round trip to make
it audible is dead weight in the gap it was invented to fill. The risk is that
cached audio fires no Azure word-boundary callbacks, and the word-timing
sequencer has had a duplication bug before -- so the cache advances the
cumulative offset itself. On by default; ``VOICE_TTS_PHRASE_CACHE=0`` is the kill switch.
"""

from __future__ import annotations

import asyncio

import pytest
from pipecat.frames.frames import TTSAudioRawFrame

from voice import tts_pool
from voice.config import voice_tts_phrase_cache
from voice.natural import _FILLERS, is_cacheable_phrase


class _Svc(tts_pool.KeepAliveAzureTTSService):
    """The cache layer over a stubbed Azure synthesis."""

    def __init__(self) -> None:  # noqa: D107
        self._sample_rate = 16000
        self._cumulative_audio_offset = 0.0
        self.synth_calls: list[str] = []
        self._ssml_voice = "neerja"

    @property
    def sample_rate(self):
        return self._sample_rate

    def _construct_ssml(self, text: str) -> str:
        return f"<speak voice={self._ssml_voice}>{text}</speak>"

    async def _azure(self, text, context_id):
        self.synth_calls.append(text)
        for chunk in (b"\x01\x02" * 80, b"\x03\x04" * 80):
            yield TTSAudioRawFrame(
                audio=chunk, sample_rate=self.sample_rate, num_channels=1, context_id=context_id
            )


@pytest.fixture(autouse=True)
def _cache_on(monkeypatch):
    tts_pool.clear_phrase_cache()
    monkeypatch.setenv("VOICE_TTS_PHRASE_CACHE", "1")
    # super().run_tts inside the cache layer resolves to this. Stubbing the real
    # base means the cache is exercised exactly as it ships.
    monkeypatch.setattr(
        tts_pool.AzureTTSService,
        "run_tts",
        lambda self, text, context_id: self._azure(text, context_id),
        raising=False,
    )
    yield
    tts_pool.clear_phrase_cache()


def _drain(svc, text):
    async def go():
        return [f async for f in svc.run_tts(text, "ctx")]

    return asyncio.run(go())


@pytest.fixture
def svc():
    return _Svc()


FILLER = next(iter(next(iter(_FILLERS.values()))))


def test_the_flag_is_on_by_default(monkeypatch):
    monkeypatch.delenv("VOICE_TTS_PHRASE_CACHE", raising=False)
    assert voice_tts_phrase_cache() is True


def test_only_the_fixed_phrases_are_cacheable():
    assert is_cacheable_phrase(FILLER)
    assert not is_cacheable_phrase("Your outstanding balance is 4,200 rupees.")
    assert not is_cacheable_phrase("")


def test_a_filler_is_synthesised_once_then_replayed(svc):
    first = _drain(svc, FILLER)
    second = _drain(svc, FILLER)

    assert svc.synth_calls == [FILLER], "the cached phrase was re-synthesised"
    assert [f.audio for f in first] == [f.audio for f in second]


def test_a_model_authored_reply_is_never_cached(svc):
    reply = "You have 4,200 rupees outstanding."
    _drain(svc, reply)
    _drain(svc, reply)
    assert svc.synth_calls == [reply, reply], "a unique sentence was cached"


def test_a_voice_change_invalidates_the_clip(svc):
    _drain(svc, FILLER)
    svc._ssml_voice = "aarti"
    _drain(svc, FILLER)
    assert svc.synth_calls == [FILLER, FILLER], "a stale voice was served"


def test_word_timings_stay_honest_across_a_replay(svc):
    """Azure's boundary callbacks drive the cumulative offset and a replay fires
    none, so the NEXT real synthesis would be offset by the filler's length."""
    _drain(svc, FILLER)
    after_real = svc._cumulative_audio_offset
    svc._cumulative_audio_offset = 0.0

    _drain(svc, FILLER)
    # 2 chunks x 160 bytes = 320 bytes, 16-bit mono at 16kHz = 0.01s
    assert svc._cumulative_audio_offset == pytest.approx(320 / (2 * 16000))
    assert after_real == 0.0, "the stub fires no callbacks, as Azure would not"


def test_the_cache_is_bounded(svc, monkeypatch):
    monkeypatch.setattr(tts_pool, "_PCM_CACHE_MAX", 2)
    monkeypatch.setattr("voice.natural.is_cacheable_phrase", lambda _t: True)
    for i in range(5):
        _drain(svc, f"phrase {i}")
    assert len(tts_pool._PCM_CACHE) <= 2


def test_disabling_the_flag_always_synthesises(svc, monkeypatch):
    monkeypatch.setenv("VOICE_TTS_PHRASE_CACHE", "0")
    _drain(svc, FILLER)
    _drain(svc, FILLER)
    assert svc.synth_calls == [FILLER, FILLER]
