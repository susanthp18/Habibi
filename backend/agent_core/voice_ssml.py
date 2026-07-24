"""VoiceConfig → SSML mapping — one voice definition for Prompt Studio + live calls.

Prompt Studio preview uses azure_speech.synthesize (REST/MP3).
Live voice uses Pipecat AzureTTSService with the same prosody params.
"""

from __future__ import annotations

from typing import Any

from azure_speech import build_ssml, resolve_azure_voice_name


def _coalesce(*vals: Any) -> Any:
    """First non-None value (0 is preserved, unlike ``or``). Last arg is the default."""
    for v in vals:
        if v is not None:
            return v
    return vals[-1]


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
        "speed": float(_coalesce(cfg.get("speed"), pv.get("speed"), 1.0)),
        "pitch": int(_coalesce(cfg.get("pitch"), pv.get("pitch"), 0)),
        "warmth": int(_coalesce(cfg.get("warmth"), pv.get("warmth"), 60)),
        "pauseMs": int(_coalesce(cfg.get("pauseMs"), pv.get("pauseMs"), 300)),
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
