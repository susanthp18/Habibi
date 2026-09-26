"""Self-hosted voice catalog: list TTS voices straight from each provider.

AgentStudio replacement for the vendor's hosted voice proxy. It uses the
organization's own provider key (Models page) and returns the payload shape the
hosted proxy did: {"provider", "voices": [VoiceInfo...], "facets"}.
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException

from api.services.configuration.ai_model_configuration import (
    get_resolved_ai_model_configuration,
)

_TIMEOUT = httpx.Timeout(15.0)
_CARTESIA_VERSION = "2026-03-01"  # the version pipecat's Cartesia service speaks


async def _provider_key(organization_id: int, provider: str) -> str | None:
    """The org's saved key for this provider, from any configured section."""
    effective = (
        await get_resolved_ai_model_configuration(organization_id=organization_id)
    ).effective
    for section in (effective.tts, effective.stt, effective.llm, effective.embeddings):
        section_provider = getattr(section, "provider", None)
        if section is not None and getattr(section_provider, "value", section_provider) == provider:
            key = getattr(section, "api_key", None)
            if isinstance(key, list):
                key = key[0] if key else None
            if key:
                return key
    return None


def _voice(voice_id, name, *, description=None, accent=None, gender=None, language=None, preview_url=None):
    return {
        "voice_id": str(voice_id),
        "name": str(name or voice_id),
        "description": description,
        "accent": accent,
        "gender": (gender or "").lower() or None,
        "language": language,
        "preview_url": preview_url,
    }


async def _elevenlabs(client: httpx.AsyncClient, key: str) -> list[dict]:
    r = await client.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key})
    r.raise_for_status()
    out = []
    for v in r.json().get("voices", []):
        labels = v.get("labels") or {}
        out.append(
            _voice(
                v["voice_id"],
                v.get("name"),
                description=v.get("description") or labels.get("description"),
                accent=labels.get("accent"),
                gender=labels.get("gender"),
                language=labels.get("language"),
                preview_url=v.get("preview_url"),
            )
        )
    return out


async def _cartesia(client: httpx.AsyncClient, key: str) -> list[dict]:
    headers = {"X-API-Key": key, "Cartesia-Version": _CARTESIA_VERSION}
    out, cursor = [], None
    for _ in range(20):  # 100 per page; bounded
        params = {"limit": 100, **({"starting_after": cursor} if cursor else {})}
        r = await client.get("https://api.cartesia.ai/voices", headers=headers, params=params)
        r.raise_for_status()
        body = r.json()
        page = body.get("data", []) if isinstance(body, dict) else body
        for v in page:
            out.append(
                _voice(
                    v["id"],
                    v.get("name"),
                    description=v.get("description"),
                    gender=v.get("gender"),
                    language=v.get("language"),
                    preview_url=v.get("preview_file_url"),
                )
            )
        if not (isinstance(body, dict) and body.get("has_more") and page):
            break
        cursor = page[-1]["id"]
    return out


async def _deepgram(client: httpx.AsyncClient, key: str) -> list[dict]:
    r = await client.get(
        "https://api.deepgram.com/v1/models", headers={"Authorization": f"Token {key}"}
    )
    r.raise_for_status()
    out = []
    for m in r.json().get("tts", []):
        meta = m.get("metadata") or {}
        tags = [t.lower() for t in meta.get("tags") or []]
        languages = m.get("languages") or []
        out.append(
            _voice(
                m.get("canonical_name") or m.get("name"),
                m.get("name"),
                description=", ".join(meta.get("tags") or []) or None,
                accent=meta.get("accent"),
                gender="female" if "feminine" in tags else "male" if "masculine" in tags else None,
                language=languages[0] if languages else None,
                preview_url=meta.get("sample"),
            )
        )
    return out


def _sarvam(model: str | None) -> list[dict]:
    from pipecat.services.sarvam.tts import get_speakers_for_model

    return [_voice(s, s.title(), language="hi-IN") for s in get_speakers_for_model(model or "bulbul:v3")]


async def list_voices(
    *,
    organization_id: int,
    provider: str,
    model: str | None = None,
    language: str | None = None,
    q: str | None = None,
    gender: str | None = None,
    accent: str | None = None,
) -> dict:
    if provider == "sarvam":
        voices = _sarvam(model)
    else:
        fetch = {"elevenlabs": _elevenlabs, "cartesia": _cartesia, "deepgram": _deepgram}.get(provider)
        if fetch is None:
            raise HTTPException(
                status_code=404,
                detail=f"Voice browsing is not available for {provider}; enter the voice ID directly.",
            )
        key = await _provider_key(organization_id, provider)
        if not key:
            raise HTTPException(
                status_code=400,
                detail=f"Save a {provider} API key under Models to browse its voices.",
            )
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                voices = await fetch(client, key)
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"{provider} rejected the voice list request ({e.response.status_code}).",
                ) from e

    facets = {
        "genders": sorted({v["gender"] for v in voices if v["gender"]}),
        "accents": sorted({v["accent"] for v in voices if v["accent"]}),
        "languages": sorted({v["language"] for v in voices if v["language"]}),
    }

    def keep(v: dict) -> bool:
        if gender and (v["gender"] or "") != gender.lower():
            return False
        if accent and (v["accent"] or "").lower() != accent.lower():
            return False
        if language and not (v["language"] or "").lower().startswith(language.lower()[:2]):
            return False
        if q and q.lower() not in f"{v['name']} {v['description'] or ''}".lower():
            return False
        return True

    return {"provider": provider, "voices": [v for v in voices if keep(v)], "facets": facets}
