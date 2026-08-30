"""Previewing one voice twice must play the same audio twice.

Auditioning is a comparison: play A, play B, play A again, choose. That only
works if A is the same both times, and it was not — ``/tts/preview`` cached only
the Azure path, so every click on a Cartesia, Deepgram or Fish voice took a
fresh sample from a generative model. Measured 2026-08-22 over three identical
requests, the returned audio length varied by 6% (Cartesia), 23% (Fish) and 39%
(Deepgram): different performances, not encoder noise.

These tests pin the cache that fixes it, and the two properties that make a
cache safe rather than merely fast: the key covers everything that changes the
audio, and it covers nothing that does not.
"""

from __future__ import annotations

import os
import time

import pytest

import provider_tts
import tts_preview_cache as cache


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    """Every test gets its own directory, and no sweep runs unless asked."""
    monkeypatch.setattr(cache, "_CACHE_DIR", tmp_path / "tts-preview")
    monkeypatch.setattr(cache, "_last_sweep", time.monotonic())
    monkeypatch.delenv("TTS_PREVIEW_CACHE", raising=False)
    return tmp_path


def k(**over):
    base = dict(provider="fish", voice="fish:abc", text="hello", params={}, salt="")
    base.update(over)
    return cache.key(**base)


# --------------------------------------------------------------- round trip


def test_put_then_get_returns_the_same_bytes_and_mime():
    cache.put(k(), b"\x00\x01audio", "audio/mpeg")
    assert cache.get(k()) == (b"\x00\x01audio", "audio/mpeg")


def test_get_on_an_unknown_key_is_a_miss_not_an_error():
    assert cache.get(k(text="never synthesized")) is None


def test_a_second_put_replaces_the_take():
    """A re-roll overwrites. Leaving the old entry would make the take the
    operator just heard unreachable while still being what a later A/B replays."""
    cache.put(k(), b"first", "audio/mpeg")
    cache.put(k(), b"second", "audio/mpeg")
    assert cache.get(k()) == (b"second", "audio/mpeg")


# ------------------------------------------------------- what the key covers


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "cartesia"),
        ("voice", "fish:other"),
        ("text", "different line"),
        ("params", {"temperature": 0.2}),
        ("salt", "s2.1-pro"),
    ],
)
def test_anything_that_changes_the_audio_changes_the_key(field, value):
    assert k() != k(**{field: value})


def test_the_fish_model_is_in_the_key_via_salt():
    """Fish's model is an env-selected HTTP header, and the free promo model
    stops working after 2026-08-31. Without the salt, flipping FISH_TTS_MODEL
    would keep replaying takes from the old model with nothing to explain it."""
    assert k(salt="s2.1-pro-free") != k(salt="s2.1-pro")


def test_param_order_does_not_change_the_key():
    a = k(params={"temperature": 0.7, "top_p": 0.5})
    b = k(params={"top_p": 0.5, "temperature": 0.7})
    assert a == b


def test_int_and_float_spellings_of_one_setting_share_a_key():
    """JSON from a browser has no int/float distinction, so `speed: 1` and
    `speed: 1.0` are one setting. Keyed apart, nudging a slider and putting it
    back would hand the operator a different performance."""
    assert k(params={"speed": 1}) == k(params={"speed": 1.0})


def test_a_bool_does_not_collide_with_a_number():
    """`bool` is a subclass of `int` in Python: canonicalising naively turns
    `normalize: True` into the same key material as a numeric 1."""
    assert k(params={"normalize": True}) != k(params={"normalize": 1})


def test_null_params_are_dropped_rather_than_keyed():
    """An absent control and one explicitly sent as null are the same request."""
    assert k(params={"style": None, "speed": 1}) == k(params={"speed": 1})


def test_surrounding_whitespace_in_the_text_is_not_a_new_take():
    assert k(text="hello") == k(text="  hello  ")


def test_nested_params_are_canonicalised_too():
    a = k(params={"prosody": {"speed": 1, "volume": 0}})
    b = k(params={"prosody": {"volume": 0.0, "speed": 1.0}})
    assert a == b


def test_the_version_prefix_invalidates_every_entry_at_once(monkeypatch):
    before = k()
    monkeypatch.setattr(cache, "_VERSION", "99")
    assert k() != before


# ----------------------------------------------------------- failure modes


def test_a_truncated_entry_reads_as_a_miss_not_a_broken_player():
    """A crash mid-write must cost one re-synthesis, not hand a half file to an
    <audio> element."""
    key = k()
    cache.put(key, b"audio", "audio/mpeg")
    cache._path(key).write_bytes(b"audio/mpeg")  # header, no newline, no body
    assert cache.get(key) is None


def test_an_entry_with_a_header_but_no_audio_reads_as_a_miss():
    key = k()
    cache.put(key, b"audio", "audio/mpeg")
    cache._path(key).write_bytes(b"audio/mpeg\n")
    assert cache.get(key) is None


def test_empty_audio_is_never_stored():
    cache.put(k(), b"", "audio/mpeg")
    assert cache.get(k()) is None


def test_a_mime_with_a_newline_cannot_corrupt_the_entry():
    """The mime comes from a vendor response header, so it is not ours to trust:
    a newline in it would make every later read of this entry unparseable."""
    cache.put(k(), b"audio", "audio/mpeg\nX-Injected: 1")
    got = cache.get(k())
    assert got == (b"audio", "audio/mpeg")


def test_a_cache_dir_that_is_actually_a_file_does_not_fail_the_preview(tmp_path, monkeypatch):
    """The realistic version: something already occupies the cache path, so
    mkdir raises. The audio is already synthesized by the time we try to store
    it — failing the request over a failed write would be absurd."""
    blocked = tmp_path / "occupied"
    blocked.write_text("not a directory")
    monkeypatch.setattr(cache, "_CACHE_DIR", blocked)
    cache.put(k(), b"audio", "audio/mpeg")  # must not raise
    assert cache.get(k()) is None


def test_no_cache_failure_of_any_kind_escapes(monkeypatch):
    """The backstop, stated directly. `put` and `get` promise never to raise,
    and the promise has to hold for the failure nobody predicted — not only for
    the OSError subclasses that were thought of in advance."""
    monkeypatch.setattr(cache, "_CACHE_DIR", None)
    cache.put(k(), b"audio", "audio/mpeg")
    assert cache.get(k()) is None


def test_the_cache_can_be_switched_off_for_reproducing_a_vendor_issue(monkeypatch):
    monkeypatch.setenv("TTS_PREVIEW_CACHE", "0")
    cache.put(k(), b"audio", "audio/mpeg")
    assert cache.get(k()) is None
    monkeypatch.setenv("TTS_PREVIEW_CACHE", "1")
    assert cache.get(k()) is None  # the disabled put really did not write


# -------------------------------------------------------------- eviction


def test_entries_past_the_age_cap_are_swept(monkeypatch):
    monkeypatch.setattr(cache, "_MAX_AGE_S", 1)
    key = k()
    cache.put(key, b"audio", "audio/mpeg")
    old = time.time() - 3600
    os.utime(cache._path(key), (old, old))
    cache.evict()
    assert cache.get(key) is None


def test_the_cache_is_bounded_by_total_size_oldest_first(monkeypatch):
    monkeypatch.setattr(cache, "_MAX_BYTES", 300)
    keys = [k(text=f"line {i}") for i in range(4)]
    for i, key in enumerate(keys):
        cache.put(key, b"x" * 200, "audio/mpeg")
        # Distinct mtimes, so "oldest first" is well defined rather than
        # dependent on filesystem timestamp granularity.
        stamp = time.time() - (100 - i)
        os.utime(cache._path(key), (stamp, stamp))
    cache.evict()
    survivors = [key for key in keys if cache.get(key) is not None]
    assert survivors, "eviction removed everything"
    assert keys[0] not in survivors, "the oldest entry should go first"
    assert keys[-1] in survivors, "the newest entry should survive"


# ------------------------------------------------- provider_tts integration


@pytest.fixture
def stub_provider(monkeypatch):
    """A fake Cartesia that counts vendor calls and never repeats itself."""
    calls = {"n": 0}

    def fake_voice_row(short_name):
        return "cartesia", "en-US"

    def fake_adapter(ref, body, params, locale=""):
        calls["n"] += 1
        return f"take-{calls['n']}".encode(), "audio/mpeg"

    monkeypatch.setattr(provider_tts, "voice_row", fake_voice_row)
    monkeypatch.setitem(provider_tts._ADAPTERS, "cartesia", fake_adapter)
    return calls


def test_the_same_request_twice_plays_the_same_take(stub_provider):
    """The bug, stated as a test: this returned take-1 then take-2."""
    first = provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")
    second = provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")

    assert first[0] == second[0] == b"take-1"
    assert stub_provider["n"] == 1, "the vendor was called twice for one take"
    assert first[2]["cacheHit"] is False
    assert second[2]["cacheHit"] is True


def test_changing_a_control_takes_a_new_sample(stub_provider):
    """Otherwise the cache would turn every tuning knob into a knob that does
    nothing — the exact failure the cache is meant to make visible."""
    provider_tts.synthesize(short_name="cartesia:v1", text_body="hi", params={"speed": 1.0})
    provider_tts.synthesize(short_name="cartesia:v1", text_body="hi", params={"speed": 1.4})
    assert stub_provider["n"] == 2


def test_returning_to_a_previous_setting_replays_that_take(stub_provider):
    """What makes A/B on a slider a comparison instead of two samples."""
    a1 = provider_tts.synthesize(short_name="cartesia:v1", text_body="hi", params={"speed": 1.0})
    provider_tts.synthesize(short_name="cartesia:v1", text_body="hi", params={"speed": 1.4})
    a2 = provider_tts.synthesize(short_name="cartesia:v1", text_body="hi", params={"speed": 1.0})
    assert a1[0] == a2[0]
    assert stub_provider["n"] == 2


def test_force_fresh_takes_a_new_sample_and_keeps_it(stub_provider):
    """A re-roll that did not overwrite would leave the operator comparing
    against a take they can no longer hear."""
    provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")
    rolled = provider_tts.synthesize(short_name="cartesia:v1", text_body="hello", force_fresh=True)
    replay = provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")

    assert rolled[0] == b"take-2"
    assert replay[0] == b"take-2", "the re-rolled take should become the stored one"
    assert replay[2]["cacheHit"] is True
    assert stub_provider["n"] == 2


def test_a_cache_hit_reports_no_latency(stub_provider):
    provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")
    meta = provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")[2]
    assert meta["latencyMs"] == 0


def test_two_voices_never_share_an_entry(stub_provider):
    a = provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")
    b = provider_tts.synthesize(short_name="cartesia:v2", text_body="hello")
    assert a[0] != b[0]


def test_a_vendor_returning_no_audio_is_an_error_and_is_not_cached(monkeypatch):
    monkeypatch.setattr(provider_tts, "voice_row", lambda s: ("cartesia", "en-US"))
    monkeypatch.setitem(
        provider_tts._ADAPTERS, "cartesia", lambda *a, **kw: (b"", "audio/mpeg")
    )
    with pytest.raises(provider_tts.PreviewUnavailable):
        provider_tts.synthesize(short_name="cartesia:v1", text_body="hello")
    assert cache.get(k(provider="cartesia", voice="cartesia:v1", text="hello")) is None


def test_the_fish_salt_is_the_configured_model(monkeypatch):
    monkeypatch.setenv("FISH_TTS_MODEL", "s2.1-pro")
    assert provider_tts._cache_salt("fish") == "s2.1-pro"
    monkeypatch.delenv("FISH_TTS_MODEL")
    assert provider_tts._cache_salt("fish") == "s2.1-pro-free"


def test_only_fish_carries_a_salt():
    """A salt is per-provider state outside `params`. Nobody else has any, and
    inventing one would split the cache for no reason."""
    assert provider_tts._cache_salt("cartesia") == ""
    assert provider_tts._cache_salt("deepgram") == ""


# ------------------------------------------------- the registry's claim


def test_sampling_is_declared_for_the_engines_measured_to_vary():
    """The studio offers "new take" only where it means something. These flags
    are what decides that, so a wrong one is either a missing control or a
    control that visibly does nothing."""
    from agent_core.providers import registry

    expected = {
        ("azure", "azure-neural"): False,
        ("cartesia", "sonic-3.5"): True,
        ("deepgram", "aura-2-thalia-en"): True,
        ("fish", "s2.1-pro"): True,
    }
    for (provider, model_id), want in expected.items():
        spec = registry.find_model(provider, model_id)
        assert spec is not None, f"{provider}:{model_id} missing from the registry"
        assert spec.sampling is want, f"{provider}:{model_id} sampling should be {want}"
