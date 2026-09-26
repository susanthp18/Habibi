"""Self-hosted transcription for uploaded recordings.

AgentStudio replacement for the vendor's hosted /stt/transcribe. It sends the
file to the organization's own speech-to-text provider (Models > Transcriber)
and returns {"transcript", "duration_seconds", "provider"}.
"""

from __future__ import annotations

import json

import httpx
from fastapi import HTTPException

from api.services.configuration.ai_model_configuration import (
    get_resolved_ai_model_configuration,
)

_TIMEOUT = httpx.Timeout(120.0)


def _first_key(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _locale(language: str) -> str:
    return language if "-" in language else {"en": "en-US", "hi": "hi-IN"}.get(language, language)


async def transcribe(
    *, organization_id: int, audio: bytes, filename: str, content_type: str, language: str
) -> dict:
    stt = (await get_resolved_ai_model_configuration(organization_id=organization_id)).effective.stt
    if stt is None:
        raise HTTPException(status_code=400, detail="Configure a transcriber under Models first.")
    provider = getattr(stt.provider, "value", stt.provider)
    key = _first_key(getattr(stt, "api_key", None))
    model = getattr(stt, "model", None)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        try:
            if provider == "deepgram":
                r = await client.post(
                    "https://api.deepgram.com/v1/listen",
                    params={"model": model or "nova-3", "language": language, "smart_format": "true"},
                    headers={"Authorization": f"Token {key}", "Content-Type": content_type},
                    content=audio,
                )
                r.raise_for_status()
                body = r.json()
                alt = body["results"]["channels"][0]["alternatives"][0]
                return {
                    "transcript": alt.get("transcript", ""),
                    "duration_seconds": (body.get("metadata") or {}).get("duration"),
                    "provider": provider,
                }
            if provider == "azure_speech":
                region = getattr(stt, "region", None)
                r = await client.post(
                    f"https://{region}.api.cognitive.microsoft.com/speechtotext/transcriptions:transcribe",
                    params={"api-version": "2024-11-15"},
                    headers={"Ocp-Apim-Subscription-Key": key},
                    files={
                        "audio": (filename, audio, content_type),
                        "definition": (None, json.dumps({"locales": [_locale(language)]}), "application/json"),
                    },
                )
                r.raise_for_status()
                body = r.json()
                phrases = body.get("combinedPhrases") or [{}]
                return {
                    "transcript": phrases[0].get("text", ""),
                    "duration_seconds": (body.get("durationMilliseconds") or 0) / 1000 or None,
                    "provider": provider,
                }
            if provider == "openai":
                base = (getattr(stt, "base_url", None) or "https://api.openai.com/v1").rstrip("/")
                r = await client.post(
                    f"{base}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {key}"},
                    data={"model": model or "whisper-1", "language": language.split("-")[0]},
                    files={"file": (filename, audio, content_type)},
                )
                r.raise_for_status()
                return {"transcript": r.json().get("text", ""), "duration_seconds": None, "provider": provider}
            if provider == "elevenlabs":
                r = await client.post(
                    "https://api.elevenlabs.io/v1/speech-to-text",
                    headers={"xi-api-key": key},
                    data={"model_id": model or "scribe_v1", "language_code": language.split("-")[0]},
                    files={"file": (filename, audio, content_type)},
                )
                r.raise_for_status()
                return {"transcript": r.json().get("text", ""), "duration_seconds": None, "provider": provider}
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=502,
                detail=f"{provider} rejected the transcription request ({e.response.status_code}).",
            ) from e

    raise HTTPException(
        status_code=400,
        detail=f"Transcribing uploads is not supported for {provider}; type the transcript instead.",
    )
