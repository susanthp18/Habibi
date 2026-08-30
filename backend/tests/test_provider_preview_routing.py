"""Preview routing: who plays a voice, and what happens when they cannot.

Two bugs live here historically. The first was routing every voice to Azure, so
picking a Cartesia voice surfaced an Azure error for a voice that was never
Azure's. The second is subtler and was introduced by adding key rotation: once
Fish's key retired on a 402, the *next* call failed inside ``acquire()`` before
any HTTP status existed, and the fall-through to OpenRouter — which keyed off
the status — silently stopped happening.
"""

from __future__ import annotations

import pytest

import provider_tts
from agent_core.providers import fish_tts, pool as pool_mod


@pytest.fixture(autouse=True)
def _clean_pools():
    pool_mod.reset_pools()
    yield
    pool_mod.reset_pools()


# ------------------------------------------------------------- error taxonomy


def test_a_credential_fault_is_distinct_from_a_bad_request():
    """The distinction is what makes the fall-through correct rather than a way
    to hide a malformed request behind a second provider."""
    assert fish_tts.FishTTSError("x", status=402).credential_fault
    assert fish_tts.FishTTSError("x", status=429).credential_fault
    assert not fish_tts.FishTTSError("x", status=400).credential_fault
    assert not fish_tts.FishTTSError("x", status=422).credential_fault


def test_an_exhausted_pool_is_a_credential_fault_even_with_no_status():
    """The regression: after the key retires, the next call never reaches HTTP,
    so there is no status to inspect. Keying only on status disabled the
    fall-through from the second preview onward."""
    err = fish_tts.FishTTSError("fish: all 1 keys retired", credential_fault=True)
    assert err.status is None
    assert err.credential_fault


def test_fish_falls_through_to_openrouter_when_the_pool_is_exhausted(monkeypatch):
    called = {}

    def dead_fish(*_a, **_kw):
        raise fish_tts.FishTTSError("fish: all 1 keys retired", credential_fault=True)

    def ok_openrouter(body, **kwargs):
        called["voice"] = kwargs.get("voice")
        return b"AUDIO", {}

    monkeypatch.setattr(fish_tts, "synthesize", dead_fish)
    from agent_core.providers import openrouter_tts

    monkeypatch.setattr(openrouter_tts, "synthesize", ok_openrouter)

    audio, mime = provider_tts._fish("voice-123", "hello", {})
    assert audio == b"AUDIO"
    assert mime == "audio/mpeg"
    # The operator must hear the voice they picked, not a default.
    assert called["voice"] == "voice-123"


def test_a_malformed_fish_request_is_not_laundered_through_openrouter(monkeypatch):
    def bad_request(*_a, **_kw):
        raise fish_tts.FishTTSError("fish tts 400: bad payload", status=400)

    monkeypatch.setattr(fish_tts, "synthesize", bad_request)
    with pytest.raises(provider_tts.PreviewUnavailable) as exc:
        provider_tts._fish("v", "hello", {})
    assert "400" in str(exc.value)


# ------------------------------------------------------------------- cartesia


def test_cartesia_uses_a_model_that_is_not_sunsetted():
    """sonic-2 was hardcoded here. It is sunsetted: measured 2026-08-22 it
    returns 400 for every non-English voice, which made most of the 890-voice
    Cartesia picker unplayable."""
    assert provider_tts._CARTESIA_MODEL != "sonic-2"
    assert provider_tts._CARTESIA_MODEL == "sonic-3.5"


def test_cartesia_is_locale_aware():
    """Cartesia rejects a voice whose language the model does not support, so
    the request has to carry the language the catalog recorded."""
    assert "cartesia" in provider_tts._LOCALE_AWARE


@pytest.mark.parametrize("locale", ["und", "", None])
def test_an_unknown_locale_is_omitted_rather_than_sent(locale, monkeypatch):
    """"und" means the vendor gave no language. Sending it is a 400."""
    seen = {}

    def fake_call(_provider, fn):
        class R:
            status_code = 200
            content = b"A"

        def post(url, headers=None, json=None, timeout=None):
            seen.update(json)
            return R()

        monkeypatch.setattr(provider_tts.httpx, "post", post)
        return fn("key")

    monkeypatch.setattr(provider_tts, "_call", fake_call)
    provider_tts._cartesia("v1", "hello", {}, locale or "")
    assert "language" not in seen


def test_a_real_locale_is_sent(monkeypatch):
    seen = {}

    def fake_call(_provider, fn):
        class R:
            status_code = 200
            content = b"A"

        def post(url, headers=None, json=None, timeout=None):
            seen.update(json)
            return R()

        monkeypatch.setattr(provider_tts.httpx, "post", post)
        return fn("key")

    monkeypatch.setattr(provider_tts, "_call", fake_call)
    provider_tts._cartesia("v1", "hello", {}, "ar")
    assert seen["language"] == "ar"
    assert seen["model_id"] == "sonic-3.5"


def test_cartesia_sends_no_speed_control(monkeypatch):
    """sonic-3.5 validates __experimental_controls.speed to [-1.0, 1.0] and then
    ignores it — measured n=5, the extremes differ by less than run-to-run
    variance. Sending it would back a UI knob that changes nothing.

    Asserted on the payload rather than the source: a speed the vendor drops
    is invisible in the response, so only the request can show it is absent.
    """
    seen = {}

    def fake_call(_provider, fn):
        class R:
            status_code = 200
            content = b"A"

        def post(url, headers=None, json=None, timeout=None):
            seen.update(json)
            return R()

        monkeypatch.setattr(provider_tts.httpx, "post", post)
        return fn("key")

    monkeypatch.setattr(provider_tts, "_call", fake_call)
    provider_tts._cartesia("v1", "hello", {"speed": 0.5}, "en")
    assert "__experimental_controls" not in seen["voice"]
    assert "speed" not in seen


# ---------------------------------------------------------------- key faulting


def test_a_key_fault_response_retires_but_a_bad_request_does_not():
    import httpx

    class R:
        def __init__(self, code):
            self.status_code = code
            self.text = "err"

    with pytest.raises(pool_mod.KeyRejected):
        provider_tts._check("X", R(429))

    with pytest.raises(provider_tts.PreviewUnavailable):
        provider_tts._check("X", R(400))

    # Success is a no-op.
    assert provider_tts._check("X", R(200)) is None
    assert httpx  # keep the import meaningful for linters
