"""VoiceConfig → SSML mapping — one voice definition for Prompt Studio + live calls.

Prompt Studio preview uses azure_speech.synthesize (REST/MP3).
Live voice uses Pipecat AzureTTSService with the same prosody params.
"""

from __future__ import annotations

import math
from typing import Any

from azure_speech import build_ssml, resolve_azure_voice_name


def _num(*vals: Any, default: float) -> float:
    """First value that coerces to a finite float, else ``default``."""
    for v in vals:
        if v is None:
            continue
        try:
            n = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(n):
            return n
    return default


def voice_params_from_config(
    voice_config: dict[str, Any] | None = None,
    *,
    voice: dict[str, Any] | None = None,
    tts_voice_id: str | None = None,
    db_azure_name: str | None = None,
) -> dict[str, Any]:
    """Normalize deployment/prompt voice fields into synthesize/build_ssml kwargs."""
    cfg = dict(voice_config or {})
    # Prompt-version `voice` jsonb is a secondary source (studio drafts).
    pv = dict(voice or {})
    voice_id = (
        tts_voice_id
        or cfg.get("voiceId")
        or pv.get("voiceId")
        or None
    )
    azure_name = resolve_azure_voice_name(voice_id, db_azure_name=db_azure_name)
    return {
        "voiceId": voice_id,
        "voiceName": azure_name,
        # Deployment config and prompt-version `voice` are both persisted jsonb,
        # so a hand-edited or legacy row can carry "1.1" — or "fast". Raw
        # float()/int() raised out of prompt rendering; fall back like the rest
        # of the tuning surface does.
        "speed": _num(cfg.get("speed"), pv.get("speed"), default=1.0),
        "pitch": int(_num(cfg.get("pitch"), pv.get("pitch"), default=0)),
        "warmth": int(_num(cfg.get("warmth"), pv.get("warmth"), default=60)),
        "pauseMs": int(_num(cfg.get("pauseMs"), pv.get("pauseMs"), default=300)),
    }


def build_voice_ssml(
    text: str,
    *,
    voice_config: dict[str, Any] | None = None,
    voice: dict[str, Any] | None = None,
    tts_voice_id: str | None = None,
    db_azure_name: str | None = None,
    lang: str = "en-IN",
) -> str:
    """Build SSML from studio/deployment voice settings."""
    params = voice_params_from_config(
        voice_config,
        voice=voice,
        tts_voice_id=tts_voice_id,
        db_azure_name=db_azure_name,
    )
    return build_ssml(
        text,
        voice_name=params["voiceName"],
        speed=params["speed"],
        pitch=params["pitch"],
        warmth=params["warmth"],
        pause_ms=params["pauseMs"],
        lang=lang,
    )
