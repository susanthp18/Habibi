"""Voice catalog: TTS voices, TTS/STT previews.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import asyncio
import db

from fastapi import APIRouter
from fastapi import (
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from schemas import (
    SttTranscribeResponse,
    TtsCatalogListResponse,
    TtsCatalogVoiceItem,
    TtsPreviewRequest,
    TtsPriceTierResponse,
    TtsLocaleCountResponse,
    TtsProviderCountResponse,
    TtsSyncRunResponse,
    TtsVoiceResponse,
    TtsVoiceWarning,
)

from api_support import _read_upload_capped, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/tts-voices", response_model=list[TtsVoiceResponse])
def list_tts_voices():
    return db.list_tts_voices()

@router.get("/tts-voices/catalog", response_model=TtsCatalogListResponse)
def list_tts_voice_catalog(
    q: str | None = Query(default=None),
    locale: str | None = Query(default=None),
    gender: str | None = Query(default=None),
    status: str | None = Query(default="GA"),
    price_tier: str | None = Query(default=None),
    providerId: str | None = Query(default=None),
    include_premium: bool = Query(default=False),
    include_removed: bool = Query(default=False),
    limit: int = Query(default=60, ge=1, le=200),
    cursor: str | None = Query(default=None),
):
    """Synced Azure TTS catalog — primary source for Voice picker."""
    return db.list_tts_voice_catalog(
        q=q,
        locale=locale,
        gender=gender,
        status=status,
        price_tier=price_tier,
        provider_id=providerId,
        include_premium=include_premium,
        include_removed=include_removed,
        limit=limit,
        cursor=cursor,
    )

@router.get("/tts-voices/catalog/sync-runs", response_model=list[TtsSyncRunResponse])
def list_tts_sync_runs(limit: int = Query(default=20, ge=1, le=100)):
    """Recent catalog sync runs for the Voice Studio freshness strip."""
    return db.list_tts_sync_runs(limit=limit)

@router.get("/tts-voices/catalog/{short_name}", response_model=TtsCatalogVoiceItem)
def get_tts_voice_catalog_entry(short_name: str):
    row = db.get_tts_voice_catalog_entry(short_name)
    if not row:
        raise HTTPException(status_code=404, detail="voice_not_found")
    return row

@router.get("/tts-voices/pricing", response_model=list[TtsPriceTierResponse])
def list_tts_pricing():
    return db.list_tts_price_tiers()

@router.get("/tts-voices/catalog-warning", response_model=TtsVoiceWarning | None)
def tts_voice_warning(shortName: str = Query(...)):
    return db.get_tts_voice_warning(shortName)

@router.post("/tts-voices/catalog/sync", response_model=TtsSyncRunResponse)
def sync_tts_voice_catalog():
    """Admin refresh — pull Azure voices/list (JSON fallback).

    When API-key auth is configured, require Admin / perm-admin-write so
    arbitrary keys cannot hammer Azure. Local/dev with auth off stays open.
    """
    from tts_catalog_sync import run_sync

    return run_sync(db.engine, source="admin")

# Audio bytes by design (the vendor's content type, cache headers). Listed in
# tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.post("/tts/preview", response_class=Response)
def tts_preview(payload: TtsPreviewRequest):
    """TTS preview. Azure keeps its cached path; other vendors dispatch out.

    The catalog is multi-vendor now, so a preview request can name a
    Cartesia, Deepgram or OpenRouter voice. Those used to fall through to
    Azure resolution and surface an Azure error for a voice that was never
    Azure's — a picker that lists a voice it cannot play.

    Azure stays inline rather than moving into provider_tts because this
    path also carries the synthesis cache and the removed-voice fallback,
    neither of which the other providers have.
    """
    import azure_speech

    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text_required")
    if len(text) > 500:
        text = text[:500].rstrip() + "…"

    short = (payload.shortName or payload.azureVoiceName or "").strip()

    if short:
        import provider_tts

        provider = provider_tts.provider_for_voice(short)
        if provider != "azure":
            try:
                audio, mime, meta = provider_tts.synthesize(
                    short_name=short,
                    text_body=text,
                    # `params` last: a model-declared `speed` is the control the
                    # operator actually turned, and it must win over the
                    # Azure-shaped `speed` field that every request carries a
                    # default for.
                    params={"speed": payload.speed, **(payload.params or {})},
                    force_fresh=payload.fresh,
                )
            except provider_tts.PreviewUnavailable as exc:
                # 422 not 500: the request was well formed, this voice just
                # cannot be auditioned right now (no key, quota, vendor 4xx).
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return Response(
                content=audio,
                media_type=mime,
                headers={
                    "X-Tts-Provider": str(meta["provider"]),
                    "X-Tts-Voice": str(meta["voiceName"]),
                    "X-Tts-Latency-Ms": str(meta["latencyMs"]),
                    # Was the literal "miss" — there was no cache on this path
                    # at all, so the header was accurate and useless. Same
                    # HIT/MISS casing as the Azure branch below, because the
                    # client reads one header for both.
                    "X-Tts-Cache": "HIT" if meta["cacheHit"] else "MISS",
                },
            )
    voice_id = (payload.voiceId or "").strip()
    azure_name: str | None = short or None
    if not azure_name and voice_id:
        if azure_speech.looks_like_azure_short_name(voice_id):
            azure_name = voice_id
        else:
            for v in db.list_tts_voices():
                if v["id"] == voice_id:
                    azure_name = v.get("azureVoiceName")
                    break
    try:
        resolved = azure_speech.resolve_azure_voice_name(
            voice_id or short or None, db_azure_name=azure_name
        )
        # Stale / removed voice → fall back for preview without failing the UI.
        warning = db.get_tts_voice_warning(resolved)
        if warning and warning.get("fallbackVoice"):
            resolved = warning["fallbackVoice"]
        result = azure_speech.synthesize(
            text,
            voice_name=resolved,
            speed=payload.speed,
            pitch=payload.pitch,
            warmth=payload.warmth,
            pause_ms=payload.pauseMs,
            force_fresh=payload.fresh,
            style=payload.style,
        )
    except azure_speech.AzureSpeechConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    headers = {
        "X-TTS-Cache": "HIT" if result["cacheHit"] else "MISS",
        "X-TTS-Voice": result["voiceName"],
        "X-TTS-Latency-Ms": str(result["latencyMs"]),
        "Cache-Control": "private, max-age=3600",
    }
    return Response(content=result["audio"], media_type=result["contentType"], headers=headers)

@router.post("/stt/transcribe", response_model=SttTranscribeResponse)
async def stt_transcribe(
    file: UploadFile = File(...),
    language: str = Form(default="en-IN"),
):
    """Azure Speech STT — multipart audio (webm/wav/mp3). Audio is not persisted.

    File read is async; sync Azure Speech REST runs in a worker thread so this
    async route does not block the event loop.
    """
    import azure_speech

    audio = await _read_upload_capped(file)
    if not audio:
        raise HTTPException(status_code=400, detail="empty_audio")
    content_type = (file.content_type or "application/octet-stream").split(";")[0].strip()
    lang = (language or "en-IN").strip() or "en-IN"
    try:
        result = await asyncio.to_thread(
            azure_speech.transcribe,
            audio,
            content_type=content_type,
            language=lang,
        )
    except azure_speech.AzureSpeechConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result

@router.get("/tts-voices/catalog-provider-counts", response_model=list[TtsProviderCountResponse])
def tts_voice_provider_counts():
    """Per-provider voice counts for the catalog filter chips.

    Dash-separated rather than `/catalog/provider-counts`: the latter would be
    captured by the `/tts-voices/catalog/{short_name}` route declared above and
    looked up as a voice named "provider-counts". Same reason
    `/tts-voices/catalog-warning` is spelled that way.
    """
    return db.list_tts_voice_provider_counts()

@router.get("/tts-voices/catalog-locale-counts", response_model=list[TtsLocaleCountResponse])
def tts_voice_locale_counts(limit: int = Query(default=60, ge=1, le=400)):
    """Locales present in the catalog, most-voices-first, for the locale picker."""
    return db.list_tts_voice_locale_counts(limit=limit)

