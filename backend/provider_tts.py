"""Synthesize a preview for a voice from *any* provider.

``/tts/preview`` called ``azure_speech.synthesize`` directly, which was correct
while the catalog held only Azure voices. Once Cartesia, Deepgram and OpenRouter
rows appeared, selecting one of them still routed to Azure: the short_name
(``cartesia:db6b0ed5-…``) failed Azure's voice resolution and the UI surfaced an
Azure error for a voice that was never Azure's. A picker that lists a voice it
cannot play is worse than one that does not list it.

The provider is read from the catalog row rather than guessed from the name
prefix, so the row is the single source of truth for who owns a voice — the same
rule the binding layer follows.

Each adapter returns raw audio plus its own content type. They are *not*
normalised to one codec: re-encoding server-side to make the responses uniform
would cost latency on a control the operator taps repeatedly, and every browser
in scope plays both mp3 and wav.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from sqlalchemy import text

import tts_preview_cache

logger = logging.getLogger(__name__)

_TIMEOUT = 60.0


class PreviewUnavailable(RuntimeError):
    """This voice cannot be auditioned, with a reason fit to show an operator."""


def voice_row(short_name: str) -> tuple[str, str]:
    """``(provider_id, locale)`` for ``short_name``. Azure for legacy rows.

    Rows written before the provider registry have ``provider_id IS NULL`` and
    are Azure by construction, so NULL means azure rather than unknown.

    The locale travels with the provider because some vendors need it on the
    request: Cartesia rejects a non-English voice unless the model supports the
    language, and picking the model is only possible if you know which language
    the voice is.
    """
    import db as dbmod

    with dbmod.engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT COALESCE(provider_id, 'azure') AS provider_id, "
                "COALESCE(locale, '') AS locale "
                "FROM tts_voice_catalog WHERE short_name = :sn"
            ),
            {"sn": short_name},
        ).mappings().first()
    if not row:
        return "azure", ""
    return str(row["provider_id"]), str(row["locale"] or "")


def provider_for_voice(short_name: str) -> str:
    """Which vendor owns ``short_name``. See :func:`voice_row`."""
    return voice_row(short_name)[0]


def _call(provider: str, fn: Any) -> tuple[bytes, str]:
    """Run ``fn(key)`` against ``provider``'s pool, rotating past spent keys.

    This used to hand back a single key and let each adapter fail on it. With
    pooled free-tier accounts that made the pool decorative: the first key to
    429 stayed at the head of the rotation and every later preview failed on it.
    """
    from agent_core.providers import pool as pool_mod

    pool = pool_mod.get_pool(provider)
    if len(pool) == 0:
        raise PreviewUnavailable(
            f"No API key configured for {provider}. Add one in Integrations."
        )
    try:
        return pool_mod.call_with_rotation(provider, fn)
    except pool_mod.NoKeysAvailable as exc:
        raise PreviewUnavailable(f"{provider}: {exc}") from exc


def _check(provider: str, r: httpx.Response) -> None:
    """Raise the right error for a failed response.

    A key fault becomes :class:`~agent_core.providers.pool.KeyRejected` so the
    rotation driver retires that key and retries on the next one; anything else
    is our request being wrong, which no other key would fix.
    """
    from agent_core.providers import pool as pool_mod

    if r.status_code < 400:
        return
    if pool_mod.is_key_fault(r.status_code):
        raise pool_mod.KeyRejected(
            pool_mod.reason_for_status(r.status_code), status=r.status_code
        )
    raise PreviewUnavailable(f"{provider} {r.status_code}: {r.text[:200]}")


# ---------------------------------------------------------------- adapters


#: Cartesia's current model. ``sonic-2`` was hardcoded here and is **sunsetted**
#: — measured 2026-08-22 against the live API, it returns 400 for every
#: non-English voice ("Model sunsetted" or "Invalid language for model") and
#: only still answers for English. Since the catalog holds 890 Cartesia voices
#: across many languages, most of the provider's picker was unplayable.
_CARTESIA_MODEL = "sonic-3.5"


def _cartesia(
    voice_id: str, body: str, params: dict[str, Any], locale: str = ""
) -> tuple[bytes, str]:
    payload: dict[str, Any] = {
        "model_id": _CARTESIA_MODEL,
        "transcript": body,
        "voice": {"mode": "id", "id": voice_id},
        "output_format": {
            "container": "mp3",
            "encoding": "mp3",
            "sample_rate": 44100,
            "bit_rate": 128000,
        },
    }
    # Cartesia takes a bare language code ("ar", "sv"), which the sync stores as
    # the catalog locale. Verified to change the audio, so it is not decoration.
    # "und" means the vendor gave no language; sending it is a 400.
    lang = (locale or "").split("-")[0].strip().lower()
    if lang and lang != "und":
        payload["language"] = lang
    # No speed control is sent. sonic-3.5 validates
    # __experimental_controls.speed to a float in [-1.0, 1.0] and then ignores
    # it — measured n=5 per setting, the extremes differ by less than the
    # run-to-run variance of the model. Sending it would put a knob in the UI
    # that changes nothing. See PARAM_CARTESIA_TTS in the registry.

    def attempt(key: str) -> tuple[bytes, str]:
        r = httpx.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={
                "X-API-Key": key,
                "Cartesia-Version": "2024-11-13",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_TIMEOUT,
        )
        _check("Cartesia", r)
        return r.content, "audio/mpeg"

    return _call("cartesia", attempt)


def _deepgram(model: str, body: str, _params: dict[str, Any]) -> tuple[bytes, str]:
    def attempt(key: str) -> tuple[bytes, str]:
        r = httpx.post(
            "https://api.deepgram.com/v1/speak",
            params={"model": model},
            headers={"Authorization": f"Token {key}", "Content-Type": "application/json"},
            json={"text": body},
            timeout=_TIMEOUT,
        )
        _check("Deepgram", r)
        return r.content, "audio/mpeg"

    return _call("deepgram", attempt)


def _openrouter(_ref: str, body: str, params: dict[str, Any]) -> tuple[bytes, str]:
    from agent_core.providers import openrouter_tts

    try:
        audio, _meta = openrouter_tts.synthesize(body, params=params)
    except openrouter_tts.OpenRouterTTSError as exc:
        raise PreviewUnavailable(str(exc)) from exc
    return audio, "audio/mpeg"


def _elevenlabs(voice_id: str, body: str, _params: dict[str, Any]) -> tuple[bytes, str]:
    def attempt(key: str) -> tuple[bytes, str]:
        r = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            json={"text": body, "model_id": "eleven_multilingual_v2"},
            timeout=_TIMEOUT,
        )
        _check("ElevenLabs", r)
        return r.content, "audio/mpeg"

    return _call("elevenlabs", attempt)


def _fish(voice_id: str, body: str, params: dict[str, Any]) -> tuple[bytes, str]:
    """Fish direct, falling through to the OpenRouter route on a billing failure.

    The direct API is the better surface — real prosody, latency mode, the
    emotion markers — but synthesis needs API credit, which is billed
    separately from platform credit and currently 402s. Listing voices does not.

    Rather than show a 402 for a voice the catalog just offered, fall through:
    the OpenRouter route accepts the *same* Fish library voice ids and the same
    [bracket] emotion tags, verified against both endpoints. The operator hears
    the voice they picked; only the controls narrow.
    """
    from agent_core.providers import fish_tts, openrouter_tts

    try:
        audio, _meta = fish_tts.synthesize(body, reference_id=voice_id, params=params)
        return audio, "audio/mpeg"
    except fish_tts.FishTTSError as exc:
        # Fall through only on a credential fault — spent, unfunded, unscoped,
        # or a pool already retired by an earlier call. A malformed request must
        # surface, not be laundered through a second provider.
        if not exc.credential_fault:
            raise PreviewUnavailable(str(exc)) from exc
        logger.info(
            "fish direct unavailable (%s) — falling through to openrouter for voice=%s",
            exc.status or "no keys",
            voice_id,
        )

    try:
        # Only the OpenAI-standard subset survives this hop; prosody/latency are
        # dropped by OpenRouter, so they are not forwarded and cannot mislead.
        audio, _meta = openrouter_tts.synthesize(
            body,
            voice=voice_id,
            params={k: params[k] for k in ("speed", "temperature", "top_p", "repetition_penalty") if k in params},
        )
    except openrouter_tts.OpenRouterTTSError as exc:
        raise PreviewUnavailable(
            f"Fish direct has no API credit and the OpenRouter fallback failed: {exc}"
        ) from exc
    return audio, "audio/mpeg"


_ADAPTERS = {
    "fish": _fish,
    "cartesia": _cartesia,
    "deepgram": _deepgram,
    "openrouter": _openrouter,
    "elevenlabs": _elevenlabs,
}

#: Adapters that take the voice's locale as a fourth argument. Kept as a set
#: rather than giving every adapter the parameter, so a provider that does not
#: use language cannot quietly start receiving one it would forward wrongly.
_LOCALE_AWARE = frozenset({"cartesia"})


def _cache_salt(provider: str) -> str:
    """Per-provider state that changes the audio but is not one of ``params``.

    Only Fish has any today: its model is chosen by an env-selected HTTP header,
    and the free promo model becomes unavailable after 2026-08-31. Without the
    model in the key, flipping ``FISH_TTS_MODEL`` would keep serving takes from
    the old model with nothing on screen to explain why they sound the same.
    """
    if provider == "fish":
        try:
            from agent_core.providers import fish_tts

            return fish_tts.default_model()
        except Exception:  # noqa: BLE001 - a salt is best-effort, never fatal
            return ""
    return ""


def synthesize(
    *,
    short_name: str,
    text_body: str,
    params: dict[str, Any] | None = None,
    force_fresh: bool = False,
) -> tuple[bytes, str, dict[str, Any]]:
    """Audition ``short_name``. Returns (audio, content_type, metadata).

    Identical requests return identical audio, because auditioning is a
    comparison task and these vendors are sampling-based: playing A, then B,
    then A again gave three different performances and no way to choose. See
    :mod:`tts_preview_cache` for the measurements.

    ``force_fresh`` skips the read and takes a new sample — and then *stores*
    it, so the new take becomes the one this voice keeps returning. A re-roll
    that did not overwrite would leave the operator comparing a take they can
    no longer hear.

    Azure is deliberately *not* handled here — it keeps its own path in
    ``main.tts_preview`` because that path also carries its own synthesis cache
    and the removed-voice fallback, neither of which the other providers have.
    """
    provider, locale = voice_row(short_name)
    adapter = _ADAPTERS.get(provider)
    if adapter is None:
        raise PreviewUnavailable(f"No preview adapter for provider {provider!r}")

    # short_name is namespaced "{provider}:{ref}" by the multi-provider sync.
    ref = short_name.split(":", 1)[1] if ":" in short_name else short_name

    cache_key = tts_preview_cache.key(
        provider=provider,
        voice=short_name,
        # The *truncated* text the adapter will actually send, not what the
        # caller typed — keying on the untruncated text would make two requests
        # that synthesize identical audio miss each other.
        text=text_body,
        params=params or {},
        salt=_cache_salt(provider),
    )
    if not force_fresh:
        hit = tts_preview_cache.get(cache_key)
        if hit is not None:
            audio, mime = hit
            logger.info(
                "provider preview · provider=%s · voice=%s · bytes=%d · cache=hit",
                provider,
                short_name,
                len(audio),
            )
            return audio, mime, {
                "provider": provider,
                "voiceName": short_name,
                "latencyMs": 0,
                "bytes": len(audio),
                "cacheHit": True,
            }

    t0 = time.perf_counter()
    # Only the adapters that need the voice's language take it; the rest either
    # detect it from the text (Fish) or are single-language (Deepgram Aura).
    if provider in _LOCALE_AWARE:
        audio, mime = adapter(ref, text_body, params or {}, locale)
    else:
        audio, mime = adapter(ref, text_body, params or {})
    latency_ms = int((time.perf_counter() - t0) * 1000)

    if not audio:
        raise PreviewUnavailable(f"{provider} returned no audio")

    # Stored on a re-roll too: the freshest take is the one this voice should
    # keep returning, so a later A/B is against what the operator last heard.
    tts_preview_cache.put(cache_key, audio, mime)

    logger.info(
        "provider preview · provider=%s · voice=%s · bytes=%d · latency_ms=%d · cache=%s",
        provider,
        short_name,
        len(audio),
        latency_ms,
        "reroll" if force_fresh else "miss",
    )
    return audio, mime, {
        "provider": provider,
        "voiceName": short_name,
        "latencyMs": latency_ms,
        "bytes": len(audio),
        "cacheHit": False,
    }
