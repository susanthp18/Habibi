"""Fish Audio direct API — the voice library and the expressive controls.

Distinct from :mod:`agent_core.providers.openrouter_tts`, and deliberately so.
The OpenRouter passthrough exposes only OpenAI-standard fields and has *no voice
list*: one default voice, and ``voice: ""`` is a 400. The direct API is a
different product surface — 1,000 voices via ``GET /model``, real ``prosody``,
a latency mode, chunking controls, and the ``[bracket]`` emotion markers.

Everything here comes from https://api.fish.audio/openapi.json, the vendor's own
machine-readable contract, rather than a prose docs page. That matters: the
OpenRouter route *documented* prosody support and silently ignored it, which is
how a knob ends up in a UI doing nothing.

Emotion markers
---------------
S2 takes ``[square brackets]``; legacy S1 took ``(parentheses)``. Tags are
directions, not speech — they never appear in the audio. Placement is meaning:
a sentence-level emotion belongs at the start, while tone and effect markers
apply from wherever they sit onward. The vendor accepts free-form descriptions
(``[laughing nervously]``), so :data:`EMOTION_TAGS` is a starting palette, not a
closed enum — the UI must let an operator type their own.

One caution worth keeping next to the feature: on a regulated collections line,
``[angry]`` and ``[shouting]`` are the delivery the compliance layer exists to
catch. The palette ships whole; whether a given agent may use the aggressive end
of it is a guardrail decision, not a TTS one.
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.fish.audio"

#: The model is selected by a ``model:`` **header**, not a body field, and the
#: free promotion is a *separate model id* rather than a discount on the paid
#: one. Sending ``s2.1-pro`` bills API credit — which is a balance distinct from
#: platform credit — so an account with a valid key and a funded platform wallet
#: still 402s. Verified 2026-08-22 on the same key: ``s2.1-pro`` -> 402,
#: ``s2.1-pro-free`` -> 200.
#:
#: The free tier is not a stripped model: PCM at a requested sample_rate, the
#: voice library, [bracket] emotion markers and real prosody all work on it
#: (speed 0.5 vs 2.0 measured a 4.1x duration ratio).
#:
#: **Free through 2026-08-31**, per Fish's announcement, already extended once
#: from 2026-07-24. When it lapses this will start failing; set
#: ``FISH_TTS_MODEL=s2.1-pro`` and fund API credit at fish.audio/app/developers,
#: or let the OpenRouter fall-through carry previews. Fair-use, no SLA, and
#: requests may be used to improve the model — fine for a demo, a decision to
#: revisit before production.
DEFAULT_MODEL = "s2.1-pro-free"
_TIMEOUT = 90.0

#: Grouped for the picker. Sourced from Fish's emotion-control reference; the
#: API also accepts arbitrary descriptions, so treat this as the common set.
EMOTION_TAGS: dict[str, tuple[str, ...]] = {
    "emotion": (
        "happy", "sad", "angry", "excited", "calm", "nervous", "confident",
        "surprised", "satisfied", "delighted", "scared", "worried", "upset",
        "frustrated", "depressed", "empathetic", "embarrassed", "disgusted",
        "moved", "proud", "relaxed", "grateful", "curious", "sarcastic",
    ),
    "advanced": (
        "disdainful", "unhappy", "anxious", "hysterical", "indifferent",
        "uncertain", "doubtful", "confused", "disappointed", "regretful",
        "guilty", "ashamed", "jealous", "envious", "hopeful", "optimistic",
        "pessimistic", "nostalgic", "lonely", "bored", "contemptuous",
        "sympathetic", "compassionate", "determined", "resigned",
    ),
    "tone": (
        "in a hurry tone", "shouting", "screaming", "whispering", "soft tone",
        "emphasis",
    ),
    "effect": (
        "laughing", "chuckling", "sobbing", "crying loudly", "sighing",
        "groaning", "panting", "gasping", "yawning", "snoring", "clear throat",
    ),
    "scene": (
        "audience laughing", "background laughter", "crowd laughing", "break",
        "long-break",
    ),
}

#: Vendor guidance: more than three stacked emotions on one sentence degrades
#: rather than compounds.
MAX_TAGS_PER_SENTENCE = 3

_TAG_RE = re.compile(r"\[([^\[\]]{1,80})\]")


class FishTTSError(RuntimeError):
    """A Fish synthesis failure.

    ``credential_fault`` separates "this key cannot pay for the call" from "this
    request was wrong", and the distinction is load-bearing: the former is what
    makes the OpenRouter fall-through correct, the latter would make it a way to
    hide a bug. It is true both for a key-fault status and for an exhausted
    pool, because once the key is retired the *next* call fails before any
    status exists — which silently disabled the fall-through when only the
    status was consulted.
    """

    def __init__(
        self, message: str, *, status: int | None = None, credential_fault: bool = False
    ) -> None:
        super().__init__(message)
        self.status = status
        self.credential_fault = credential_fault or (
            status is not None and status in (401, 402, 403, 429)
        )


def base_url() -> str:
    return (os.getenv("FISH_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def default_model() -> str:
    return (os.getenv("FISH_TTS_MODEL") or DEFAULT_MODEL).strip()


def _key(session_id: str | None = None, tenant_id: str | None = None) -> str:
    from agent_core.providers import pool as pool_mod

    return pool_mod.get_pool("fish").acquire(session_id, tenant_id=tenant_id)


def strip_tags(text: str) -> str:
    """Text with markers removed — what the caller actually hears.

    Used for character counting and for anything that must reason about the
    spoken words (compliance scan, transcript), since a tag is a stage
    direction and never reaches the audio.
    """
    return _TAG_RE.sub("", text or "").strip()


def find_tags(text: str) -> list[str]:
    return [m.group(1).strip() for m in _TAG_RE.finditer(text or "")]


# ----------------------------------------------------------------- the library


def list_voices(
    *,
    page_size: int = 100,
    max_pages: int = 10,
    language: str | None = None,
    self_only: bool = False,
) -> list[dict[str, Any]]:
    """Page through ``GET /model`` — the voice library.

    This is the fix for listing *the model* instead of *the voices*: the
    catalog previously held one row called "Fish S2.1 Pro (default)", which is
    the engine, not something anybody would pick from a voice picker.
    """
    key = _key()
    out: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params: dict[str, Any] = {
            "page_size": page_size,
            "page_number": page,
            "self": str(self_only).lower(),
            "sort_by": "score",
        }
        if language:
            params["language"] = language
        r = httpx.get(
            f"{base_url()}/model",
            headers={"Authorization": f"Bearer {key}"},
            params=params,
            timeout=_TIMEOUT,
        )
        if r.status_code >= 400:
            raise FishTTSError(f"fish /model {r.status_code}: {r.text[:200]}", status=r.status_code)
        body = r.json()
        items = body.get("items") or []
        out.extend(items)
        if len(items) < page_size:
            break
    return out


# --------------------------------------------------------------------- speech


def _clamp(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


#: Vendor bounds, from api.fish.audio/openapi.json (TTSRequest). Enforced here
#: as well as in the UI schema: params_schema tells a *picker* what to render,
#: and anything reaching this function through the API, a stored binding, or a
#: replayed request never passed through that picker. An out-of-range value is
#: a 422 from Fish, which on the live audio path is a silent turn.
_BOUNDS: dict[str, tuple[float, float, float]] = {
    "temperature": (0.0, 1.0, 0.7),
    "top_p": (0.0, 1.0, 0.7),
    "repetition_penalty": (0.0, 2.0, 1.2),
    "speed": (0.5, 2.0, 1.0),
    "volume": (-20.0, 20.0, 0.0),
}

_LATENCY_MODES = ("low", "normal", "balanced")
_FORMATS = ("wav", "pcm", "mp3", "opus")


def build_payload(
    body_text: str, p: dict[str, Any], *, reference_id: str | None = None
) -> dict[str, Any]:
    """The /v1/tts request body for ``body_text`` under ``p``, clamped to spec.

    Shared by :func:`synthesize` and :class:`FishTTSService` so the preview an
    operator auditions and the audio a caller hears are built the same way — the
    two drifting apart is how a voice ships sounding unlike its audition.
    """
    fmt = str(p.get("format", "mp3")).lower()
    if fmt not in _FORMATS:
        fmt = "mp3"
    latency = str(p.get("latency", "normal")).lower()
    if latency not in _LATENCY_MODES:
        latency = "normal"

    payload: dict[str, Any] = {
        "text": body_text,
        "format": fmt,
        "chunk_length": int(_clamp(p.get("chunk_length", 300), 100, 300, 300)),
        "normalize": bool(p.get("normalize", True)),
        "latency": latency,
        "temperature": _clamp(p.get("temperature", 0.7), *_BOUNDS["temperature"]),
        "top_p": _clamp(p.get("top_p", 0.7), *_BOUNDS["top_p"]),
        "repetition_penalty": _clamp(
            p.get("repetition_penalty", 1.2), *_BOUNDS["repetition_penalty"]
        ),
    }
    if fmt == "mp3":
        # Only meaningful for mp3, and the vendor takes an enum, not a range.
        bitrate = int(_clamp(p.get("mp3_bitrate", 128), 64, 192, 128))
        payload["mp3_bitrate"] = min((64, 128, 192), key=lambda b: abs(b - bitrate))
    if p.get("sample_rate"):
        payload["sample_rate"] = int(p["sample_rate"])
    if reference_id:
        payload["reference_id"] = reference_id

    # prosody is a nested object here and genuinely works — unlike the same
    # field sent through OpenRouter, which is dropped.
    speed = p.get("speed")
    volume = p.get("volume")
    if speed is not None or volume is not None:
        payload["prosody"] = {
            "speed": _clamp(speed if speed is not None else 1.0, *_BOUNDS["speed"]),
            "volume": _clamp(volume if volume is not None else 0.0, *_BOUNDS["volume"]),
        }
    return payload


def synthesize(
    text: str,
    *,
    reference_id: str | None = None,
    params: dict[str, Any] | None = None,
    session_id: str | None = None,
    tenant_id: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """POST /v1/tts. Returns (audio_bytes, metadata).

    ``reference_id`` is the voice — a model id from the library. Omitted, the
    service uses its default speaker.
    """
    body_text = (text or "").strip()
    if not body_text:
        raise ValueError("text must not be empty")

    p = dict(params or {})
    payload = build_payload(body_text, p, reference_id=reference_id)

    from agent_core.providers import pool as pool_mod

    # The last key-fault status, kept so an exhausted pool still surfaces *why*.
    # ``provider_tts._fish`` keys its fall-through to OpenRouter off this status,
    # so collapsing it to a bare "no keys" would silently disable that path.
    last_status: dict[str, int] = {}

    t0 = time.perf_counter()

    def attempt(key: str) -> httpx.Response:
        try:
            r = httpx.post(
                f"{base_url()}/v1/tts",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    # Selects s2.1-pro vs legacy s1; the bracket-vs-parenthesis
                    # emotion syntax differs between them.
                    "model": default_model(),
                },
                json=payload,
                timeout=_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            raise FishTTSError(f"fish tts transport error: {exc}") from exc

        if pool_mod.is_key_fault(r.status_code):
            last_status["status"] = r.status_code
            raise pool_mod.KeyRejected(
                pool_mod.reason_for_status(r.status_code), status=r.status_code
            )
        return r

    try:
        r = pool_mod.call_with_rotation(
            "fish", attempt, session_id=session_id, tenant_id=tenant_id
        )
    except pool_mod.NoKeysAvailable as exc:
        # Every key spent, or retired by an earlier call. Either way this is a
        # credential problem, so the caller may fall through to another route.
        raise FishTTSError(
            str(exc), status=last_status.get("status"), credential_fault=True
        ) from exc

    latency_ms = int((time.perf_counter() - t0) * 1000)

    if r.status_code >= 400:
        raise FishTTSError(f"fish tts {r.status_code}: {r.text[:300]}", status=r.status_code)
    if not r.content:
        raise FishTTSError("fish tts returned an empty body")

    tags = find_tags(body_text)
    logger.info(
        "fish tts ok · voice=%s · chars=%d · tags=%d · bytes=%d · latency_ms=%d",
        reference_id or "(default)",
        len(body_text),
        len(tags),
        len(r.content),
        latency_ms,
    )
    return r.content, {
        "model": default_model(),
        "referenceId": reference_id,
        "format": payload["format"],
        "bytes": len(r.content),
        "latencyMs": latency_ms,
        "spokenCharacters": len(strip_tags(body_text)),
        "tags": tags,
    }

