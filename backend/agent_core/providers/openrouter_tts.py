"""OpenRouter TTS — Fish Audio S2.1 Pro over the OpenAI-compatible speech API.

Pipecat ships no OpenRouter audio service, so this is ours. It is deliberately
small: one POST to ``/audio/speech``, bytes back.

Everything below was established by probing the live endpoint on 2026-08-21
rather than read off a vendor page, because the two disagree in ways that
matter:

``speed`` works; Fish's own prosody controls do not.
    ``{"speed": 0.5}`` at the top level produced 1.94x the duration and
    ``{"speed": 2.0}`` produced 0.51x. The documented Fish paths —
    ``provider.options.prosody`` and the ``X-Fish-*`` headers — moved duration
    by 7% and 6%, i.e. sampling noise. They are the direct fish.audio API
    surface and do not survive the OpenRouter hop.

``voice: ""`` is a 400, not a default.
    The endpoint validates a minimum length of 1 and rejects the empty string
    with a ZodError. There is no public voice list for this model through
    OpenRouter, so the field is *omitted* to get the default voice.

Unknown fields are accepted silently.
    A made-up parameter returns 200. That means a typo'd knob cannot be
    detected at the wire — which is exactly why ``params_schema`` in the
    registry is an allowlist, and why this module drops anything not in it.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "fish-audio/s2.1-pro-free:free"

#: Fields the speech endpoint honours. Anything else is dropped rather than
#: forwarded: the endpoint 200s on unknown keys, so forwarding a typo would
#: produce audio that silently ignored the setting the operator just moved.
_ALLOWED_BODY_FIELDS = frozenset(
    {"speed", "temperature", "top_p", "repetition_penalty"}
)

_FORMATS = frozenset({"mp3", "pcm"})


class OpenRouterTTSError(RuntimeError):
    """The speech call failed. Carries the upstream status for the caller."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def base_url() -> str:
    return (os.getenv("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def default_model() -> str:
    return (os.getenv("OPENROUTER_TTS_MODEL") or DEFAULT_MODEL).strip()


def synthesize(
    text: str,
    *,
    model: str | None = None,
    voice: str | None = None,
    response_format: str = "mp3",
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
    timeout_s: float = 90.0,
) -> tuple[bytes, dict[str, Any]]:
    """Synthesize ``text``. Returns (audio_bytes, metadata).

    ``params`` is filtered against :data:`_ALLOWED_BODY_FIELDS`; dropped keys
    are logged, never sent.
    """
    from agent_core.providers import pool as pool_mod

    body_text = (text or "").strip()
    if not body_text:
        raise ValueError("text must not be empty")

    fmt = (response_format or "mp3").lower()
    if fmt not in _FORMATS:
        raise ValueError(f"response_format must be one of {sorted(_FORMATS)}")

    payload: dict[str, Any] = {
        "model": (model or default_model()),
        "input": body_text,
        "response_format": fmt,
    }

    # Omit `voice` unless a real id is supplied. Sending "" is a 400 here, and
    # a 400 on the default path would make the model look broken.
    v = (voice or "").strip()
    if v:
        payload["voice"] = v

    if params:
        dropped = sorted(set(params) - _ALLOWED_BODY_FIELDS)
        if dropped:
            logger.debug("openrouter tts: dropped unsupported params %s", dropped)
        for k in _ALLOWED_BODY_FIELDS & set(params):
            if params[k] is not None:
                payload[k] = params[k]

    # Last key-fault status, preserved so an exhausted pool still says why
    # rather than collapsing every cause into a bare "no keys available".
    last_status: dict[str, int] = {}

    t0 = time.perf_counter()

    def attempt(key: str) -> httpx.Response:
        try:
            r = httpx.post(
                f"{base_url()}/audio/speech",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=timeout_s,
            )
        except httpx.HTTPError as exc:
            raise OpenRouterTTSError(f"openrouter tts transport error: {exc}") from exc

        # Expected end state for a free key. Retiring it means the next session
        # gets a live one instead of re-discovering the same exhaustion per call.
        if pool_mod.is_key_fault(r.status_code):
            last_status["status"] = r.status_code
            raise pool_mod.KeyRejected(
                pool_mod.reason_for_status(r.status_code), status=r.status_code
            )
        return r

    try:
        response = pool_mod.call_with_rotation(
            "openrouter", attempt, session_id=session_id, tenant_id=tenant_id
        )
    except pool_mod.NoKeysAvailable as exc:
        raise OpenRouterTTSError(str(exc), status=last_status.get("status")) from exc

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if response.status_code >= 400:
        detail = response.text[:300]
        raise OpenRouterTTSError(
            f"openrouter tts {response.status_code}: {detail}",
            status=response.status_code,
        )

    audio = response.content
    if not audio:
        raise OpenRouterTTSError("openrouter tts returned an empty body")

    logger.info(
        "openrouter tts ok · model=%s · chars=%d · bytes=%d · latency_ms=%d",
        payload["model"],
        len(body_text),
        len(audio),
        latency_ms,
    )
    return audio, {
        "model": payload["model"],
        "format": fmt,
        "bytes": len(audio),
        "latencyMs": latency_ms,
        "characters": len(body_text),
    }


class OpenRouterTTSService:
    """Placeholder for the live Pipecat pipeline.

    The registry stores a ``service_class`` for every model so the factory never
    has to special-case a slug. This model has no streaming integration yet —
    :func:`synthesize` is a request/response call, which suits the Voice tab's
    preview but not a barge-in-capable audio pipeline.

    Constructing it raises rather than returning a half-working object: a TTS
    service that yields no frames would surface as a silent call, which is the
    hardest failure to diagnose from a transcript.
    """

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError(
            "OpenRouter TTS has no streaming Pipecat integration. It is available "
            "for preview/audition via agent_core.providers.openrouter_tts."
            "synthesize(); bind a streaming provider for live calls."
        )
