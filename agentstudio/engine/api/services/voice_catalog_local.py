"""Self-hosted voice catalog: list TTS voices straight from each provider.

AgentStudio replacement for the vendor's hosted voice proxy. It uses the
organization's own provider key (Models page) and returns the payload shape the
hosted proxy did: {"provider", "voices": [VoiceInfo...], "facets"}.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from typing import Any
from xml.sax.saxutils import escape, quoteattr

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


def _voice(voice_id, name, *, description=None, accent=None, gender=None, language=None,
           preview_url=None, styles=None):
    return {
        "styles": list(styles or []),
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


async def _azure_credentials(organization_id: int) -> tuple[str, str] | None:
    """The org's Azure Speech key and region: the TTS section first, then STT."""
    effective = (
        await get_resolved_ai_model_configuration(organization_id=organization_id)
    ).effective
    for section in (effective.tts, effective.stt):
        provider = getattr(section, "provider", None)
        if section is None or getattr(provider, "value", provider) != "azure_speech":
            continue
        key = getattr(section, "api_key", None)
        key = key[0] if isinstance(key, list) and key else key
        if key:
            return str(key), str(getattr(section, "region", None) or "eastus")
    return None


def _azure_tier(short_name: str, voice_type: str) -> str:
    if "HD" in short_name or voice_type.endswith("HD"):
        return "HD (premium rate)"
    return "Neural"


async def _azure(client: httpx.AsyncClient, key: str, region: str) -> list[dict]:
    r = await client.get(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
        headers={"Ocp-Apim-Subscription-Key": key},
    )
    r.raise_for_status()
    out = []
    for v in r.json():
        if str(v.get("Status") or "GA") == "Deprecated":
            continue
        short = str(v.get("ShortName") or "")
        styles = [st for st in (v.get("StyleList") or []) if st]
        detail = f"{_azure_tier(short, str(v.get('VoiceType') or ''))} · {v.get('LocaleName') or v.get('Locale')}"
        if styles:
            detail += f" · styles: {', '.join(styles)}"
        out.append(
            _voice(
                short,
                f"{v.get('LocalName') or v.get('DisplayName') or short} ({v.get('Locale')})",
                description=detail,
                accent=v.get("LocaleName"),
                gender=v.get("Gender"),
                language=v.get("Locale"),
                styles=styles,
            )
        )
    return out


# --- Delivery and preview ---------------------------------------------------

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")


def azure_delivery(config: Any) -> dict[str, str]:
    """Pipecat AzureTTSSettings for a voice's style, strength, pitch and volume.

    One mapping for live calls (service_factory) and previews, so the preview
    is what callers hear. Defaults are omitted: Azure's own neutral delivery.
    """
    out: dict[str, str] = {}
    style = str(getattr(config, "style", None) or "").strip()
    if style and _SAFE_TOKEN.match(style):
        out["style"] = style
        degree = float(getattr(config, "style_degree", None) or 1.0)
        if degree != 1.0:
            out["style_degree"] = f"{degree:.2f}"
    pitch = int(getattr(config, "pitch", None) or 0)
    if pitch:
        out["pitch"] = f"{pitch:+d}st"
    volume = int(getattr(config, "volume", None) or 100)
    if volume != 100:
        out["volume"] = f"{volume - 100:+d}%"
    return out


def azure_preview_ssml(*, voice: str, language: str | None, speed: float,
                       delivery: dict[str, str], text: str) -> str:
    """The SSML Pipecat's Azure service sends, for one sample sentence."""
    if not _SAFE_TOKEN.match(voice):
        raise HTTPException(status_code=400, detail="Invalid voice name")
    lang = language if language and _SAFE_TOKEN.match(language) else "-".join(voice.split("-")[:2])
    prosody = {"rate": f"{speed:.2f}"} | {k: delivery[k] for k in ("pitch", "volume") if k in delivery}
    attrs = " ".join(f"{k}={quoteattr(v)}" for k, v in prosody.items())
    body = f"<prosody {attrs}>{escape(text)}</prosody>"
    if "style" in delivery:
        degree = f" styledegree={quoteattr(delivery['style_degree'])}" if "style_degree" in delivery else ""
        body = f"<mstts:express-as style={quoteattr(delivery['style'])}{degree}>{body}</mstts:express-as>"
    return (
        "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        f"xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang={quoteattr(lang)}>"
        f"<voice name={quoteattr(voice)}>{body}</voice></speak>"
    )


PREVIEW_TEXT = (
    "Hello, this is a courtesy call about your account. "
    "I can help you with your payment today. Is now a good time?"
)
_PREVIEW_MAX_CHARS = 300
# ponytail: per-process LRU; previews repeat while someone tunes a voice.
# Move to Redis if several workers serve the studio and preview billing matters.
_preview_cache: "OrderedDict[tuple, bytes]" = OrderedDict()
_PREVIEW_CACHE_SIZE = 64


async def preview_voice(*, organization_id: int, provider: str, params: Any) -> bytes:
    """Speak a short sample with exactly the configured voice and delivery (MP3)."""
    if provider != "azure_speech":
        raise HTTPException(
            status_code=404,
            detail=f"Spoken previews are available for Azure voices; {provider} voices play their own sample.",
        )
    creds = await _azure_credentials(organization_id)
    if creds is None:
        raise HTTPException(status_code=400, detail="Save an Azure Speech key under Models to preview voices.")
    key, saved_region = creds
    region = str(getattr(params, "region", None) or saved_region)
    if not _SAFE_TOKEN.match(region):
        raise HTTPException(status_code=400, detail="Invalid region")
    text = (str(getattr(params, "text", None) or "").strip() or PREVIEW_TEXT)[:_PREVIEW_MAX_CHARS]
    speed = min(max(float(getattr(params, "speed", None) or 1.0), 0.5), 2.0)
    ssml = azure_preview_ssml(voice=str(params.voice), language=getattr(params, "language", None),
                              speed=speed, delivery=azure_delivery(params), text=text)
    cache_key = (organization_id, region, ssml)
    if cache_key in _preview_cache:
        _preview_cache.move_to_end(cache_key)
        return _preview_cache[cache_key]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await client.post(
            f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
            headers={
                "Ocp-Apim-Subscription-Key": key,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
                "User-Agent": "payint-voice-studio",
            },
            content=ssml.encode("utf-8"),
        )
    if r.status_code in (401, 403):
        raise HTTPException(status_code=400, detail=f"Azure rejected the saved key for region {region}.")
    if r.status_code == 400:
        raise HTTPException(
            status_code=400,
            detail="Azure could not speak this voice with these settings (check the voice supports the style).",
        )
    if r.status_code >= 300 or not r.content:
        raise HTTPException(status_code=502, detail=f"Azure Speech failed ({r.status_code}).")
    _preview_cache[cache_key] = r.content
    if len(_preview_cache) > _PREVIEW_CACHE_SIZE:
        _preview_cache.popitem(last=False)
    return r.content


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
    elif provider == "azure_speech":
        creds = await _azure_credentials(organization_id)
        if creds is None:
            raise HTTPException(status_code=400, detail="Save an Azure Speech key under Models to browse its voices.")
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            try:
                voices = await _azure(client, *creds)
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"Azure Speech rejected the voice list request ({e.response.status_code}).",
                ) from e
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
