"""Live usage metering → usage_events → billing_usage_daily.

Records billable Azure OpenAI / Speech units at call time using env-driven
USD list prices converted to INR. Daily facts are upserted so /billing reads
real spend instead of synthetic seed burn.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from env_loader import load_env

logger = logging.getLogger(__name__)

# Azure list prices (USD) — overridable via env. Defaults match public PAYG rates
# for the deployments this app uses (chat mini-class + text-embedding-3-small +
# Speech neural TTS / standard STT). See Azure OpenAI / Speech pricing pages.
_DEFAULTS = {
    "USD_INR_FX": "86.0",
    # Chat: GPT-5-mini / gpt-4o-mini class — $ / 1M tokens
    "PRICE_CHAT_INPUT_USD_PER_1M": "0.25",
    "PRICE_CHAT_OUTPUT_USD_PER_1M": "2.00",
    # Embeddings: text-embedding-3-small — $ / 1M tokens
    "PRICE_EMBED_USD_PER_1M": "0.02",
    # Azure Speech neural TTS — $ / 1M characters
    "PRICE_TTS_USD_PER_1M_CHARS": "15.0",
    # Azure Speech standard STT — $ / hour → we bill per minute
    "PRICE_STT_USD_PER_HOUR": "1.0",
}

SERVICE_CHAT = "llm_chat"
SERVICE_EMBED = "llm_embed"
SERVICE_STT = "stt_az"
SERVICE_TTS = "tts_az"


def _env_float(name: str) -> float:
    load_env()
    raw = (os.getenv(name) or _DEFAULTS.get(name) or "0").strip()
    try:
        return float(raw)
    except ValueError:
        return float(_DEFAULTS.get(name, "0"))


def fx_rate() -> float:
    return max(1.0, _env_float("USD_INR_FX"))


def chat_cost_inr(*, prompt_tokens: int, completion_tokens: int) -> float:
    fx = fx_rate()
    pin = _env_float("PRICE_CHAT_INPUT_USD_PER_1M")
    pout = _env_float("PRICE_CHAT_OUTPUT_USD_PER_1M")
    usd = (prompt_tokens / 1_000_000.0) * pin + (completion_tokens / 1_000_000.0) * pout
    return round(usd * fx, 6)


def embed_cost_inr(*, prompt_tokens: int) -> float:
    fx = fx_rate()
    p = _env_float("PRICE_EMBED_USD_PER_1M")
    return round((prompt_tokens / 1_000_000.0) * p * fx, 6)


def tts_cost_inr(*, chars: int) -> float:
    fx = fx_rate()
    p = _env_float("PRICE_TTS_USD_PER_1M_CHARS")
    return round((chars / 1_000_000.0) * p * fx, 6)


def stt_cost_inr(*, minutes: float) -> float:
    fx = fx_rate()
    p = _env_float("PRICE_STT_USD_PER_HOUR")
    return round((minutes / 60.0) * p * fx, 6)


def unit_cost_book_inr() -> dict[str, dict[str, Any]]:
    """Catalog rows for billing_services — INR unit costs derived from USD list × FX."""
    fx = fx_rate()
    # Blended chat display rate assumes ~70% input / 30% output mix.
    pin = _env_float("PRICE_CHAT_INPUT_USD_PER_1M")
    pout = _env_float("PRICE_CHAT_OUTPUT_USD_PER_1M")
    chat_per_1k_usd = ((0.7 * pin) + (0.3 * pout)) / 1000.0
    embed_per_1k_usd = _env_float("PRICE_EMBED_USD_PER_1M") / 1000.0
    tts_per_1k_usd = _env_float("PRICE_TTS_USD_PER_1M_CHARS") / 1000.0
    stt_per_min_usd = _env_float("PRICE_STT_USD_PER_HOUR") / 60.0
    return {
        SERVICE_CHAT: {
            "name": "Azure OpenAI Chat",
            "provider": "Azure",
            "category": "LLM",
            "unit": "1K tokens",
            "unit_cost_inr": round(chat_per_1k_usd * fx, 4),
            "color": "#3b82f6",
        },
        SERVICE_EMBED: {
            "name": "Azure OpenAI Embeddings",
            "provider": "Azure",
            "category": "LLM",
            "unit": "1K tokens",
            "unit_cost_inr": round(embed_per_1k_usd * fx, 4),
            "color": "#6366f1",
        },
        SERVICE_STT: {
            "name": "Azure Speech STT",
            "provider": "Azure",
            "category": "Voice",
            "unit": "minute",
            "unit_cost_inr": round(stt_per_min_usd * fx, 4),
            "color": "#0ea5e9",
        },
        SERVICE_TTS: {
            "name": "Azure Speech TTS",
            "provider": "Azure",
            "category": "Voice",
            "unit": "1K chars",
            "unit_cost_inr": round(tts_per_1k_usd * fx, 4),
            "color": "#14b8a6",
        },
    }


def estimate_stt_minutes(audio_bytes: int, content_type: str | None = None) -> float:
    """Rough duration from compressed audio size when Azure simple STT omits Duration."""
    if audio_bytes <= 0:
        return 0.01
    ct = (content_type or "").lower()
    # Opus/webm ~16 kbps ≈ 2000 B/s; wav 16kHz mono 16-bit ≈ 32000 B/s
    if "wav" in ct or "wave" in ct or "pcm" in ct:
        seconds = audio_bytes / 32000.0
    else:
        seconds = audio_bytes / 2000.0
    return max(0.01, round(seconds / 60.0, 4))


def _engine():
    import db as dbmod

    return dbmod.engine


def _tenant_id() -> str:
    return (os.getenv("TENANT_ID") or "hdfc.retail").strip() or "hdfc.retail"


def _env_name() -> str:
    load_env()
    raw = (os.getenv("BILLING_ENV") or os.getenv("APP_ENV") or "production").strip().lower()
    return "sandbox" if raw in {"sandbox", "dev", "development", "local"} else "production"


def record_usage(
    *,
    service_id: str,
    units: float,
    cost_inr: float,
    meta: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    environment: str | None = None,
    occurred_at: datetime | None = None,
    source_ref: str | None = None,
) -> None:
    """Insert a usage event and upsert the matching billing_usage_daily row."""
    if units <= 0 and cost_inr <= 0:
        return
    tid = tenant_id or _tenant_id()
    env = environment or _env_name()
    when = occurred_at or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    day = when.date()
    event_id = f"ue-{uuid.uuid4().hex[:16]}"
    daily_id = f"bu-{service_id}-{tid}-{env}-{day.isoformat()}"
    meta_json = json.dumps(meta or {})

    try:
        with _engine().begin() as conn:
            # Ensure service exists (price book may have updated unit cost).
            book = unit_cost_book_inr().get(service_id)
            if book:
                conn.execute(
                    text(
                        """
                        INSERT INTO billing_services (
                          id, name, unit, unit_cost_inr, provider, category, color
                        ) VALUES (
                          :id, :name, :unit, :unit_cost_inr, :provider, :category, :color
                        )
                        ON CONFLICT (id) DO UPDATE SET
                          name = EXCLUDED.name,
                          unit = EXCLUDED.unit,
                          unit_cost_inr = EXCLUDED.unit_cost_inr,
                          provider = EXCLUDED.provider,
                          category = EXCLUDED.category,
                          color = EXCLUDED.color,
                          updated_at = now()
                        """
                    ),
                    {"id": service_id, **book},
                )

            conn.execute(
                text(
                    """
                    INSERT INTO usage_events (
                      id, tenant_id, environment, service_id, units, cost_inr,
                      meta, occurred_at, source_ref
                    ) VALUES (
                      :id, :tenant_id, :environment, :service_id, :units, :cost_inr,
                      CAST(:meta AS jsonb), :occurred_at, :source_ref
                    )
                    """
                ),
                {
                    "id": event_id,
                    "tenant_id": tid,
                    "environment": env,
                    "service_id": service_id,
                    "units": float(units),
                    "cost_inr": float(cost_inr),
                    "meta": meta_json,
                    "occurred_at": when,
                    "source_ref": source_ref,
                },
            )
            conn.execute(
                text(
                    """
                    INSERT INTO billing_usage_daily (
                      id, service_id, tenant_id, environment, usage_date, units, cost_inr
                    ) VALUES (
                      :id, :service_id, :tenant_id, :environment, :usage_date, :units, :cost_inr
                    )
                    ON CONFLICT (service_id, tenant_id, environment, usage_date) DO UPDATE SET
                      units = billing_usage_daily.units + EXCLUDED.units,
                      cost_inr = billing_usage_daily.cost_inr + EXCLUDED.cost_inr
                    """
                ),
                {
                    "id": daily_id,
                    "service_id": service_id,
                    "tenant_id": tid,
                    "environment": env,
                    "usage_date": day.isoformat(),
                    "units": float(units),
                    "cost_inr": round(float(cost_inr), 4),
                },
            )
    except Exception:
        # Metering must never break product paths.
        logger.exception(
            "usage_meter_failed service=%s units=%s cost_inr=%s",
            service_id,
            units,
            cost_inr,
        )


def record_chat_usage(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    total_tokens: int | None = None,
    model: str | None = None,
    source_ref: str | None = None,
) -> None:
    pt = int(prompt_tokens or 0)
    ct = int(completion_tokens or 0)
    if pt <= 0 and ct <= 0 and total_tokens:
        # Fallback split when only total is known.
        pt = int(total_tokens * 0.7)
        ct = int(total_tokens) - pt
    total = pt + ct
    if total <= 0:
        return
    cost = chat_cost_inr(prompt_tokens=pt, completion_tokens=ct)
    record_usage(
        service_id=SERVICE_CHAT,
        units=round(total / 1000.0, 6),
        cost_inr=cost,
        meta={
            "promptTokens": pt,
            "completionTokens": ct,
            "model": model,
        },
        source_ref=source_ref,
    )


def record_embed_usage(
    *,
    prompt_tokens: int | None,
    deployment: str | None = None,
    batch_size: int | None = None,
    source_ref: str | None = None,
) -> None:
    pt = int(prompt_tokens or 0)
    if pt <= 0:
        return
    record_usage(
        service_id=SERVICE_EMBED,
        units=round(pt / 1000.0, 6),
        cost_inr=embed_cost_inr(prompt_tokens=pt),
        meta={"promptTokens": pt, "deployment": deployment, "batchSize": batch_size},
        source_ref=source_ref,
    )


def record_tts_usage(
    *,
    chars: int,
    voice: str | None = None,
    cache_hit: bool = False,
    source_ref: str | None = None,
) -> None:
    if cache_hit or chars <= 0:
        return
    record_usage(
        service_id=SERVICE_TTS,
        units=round(chars / 1000.0, 6),
        cost_inr=tts_cost_inr(chars=chars),
        meta={"chars": chars, "voice": voice},
        source_ref=source_ref,
    )


def record_stt_usage(
    *,
    audio_bytes: int,
    content_type: str | None = None,
    minutes: float | None = None,
    language: str | None = None,
    source_ref: str | None = None,
) -> None:
    mins = minutes if minutes is not None else estimate_stt_minutes(audio_bytes, content_type)
    if mins <= 0:
        return
    record_usage(
        service_id=SERVICE_STT,
        units=round(mins, 6),
        cost_inr=stt_cost_inr(minutes=mins),
        meta={
            "audioBytes": audio_bytes,
            "minutesEstimated": minutes is None,
            "language": language,
            "contentType": content_type,
        },
        source_ref=source_ref,
    )


def sync_price_book(conn: Any | None = None) -> None:
    """Upsert metered Azure services with current env-derived INR unit costs."""
    book = unit_cost_book_inr()

    def _upsert(c: Any) -> None:
        for sid, row in book.items():
            c.execute(
                text(
                    """
                    INSERT INTO billing_services (
                      id, name, unit, unit_cost_inr, provider, category, color
                    ) VALUES (
                      :id, :name, :unit, :unit_cost_inr, :provider, :category, :color
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      name = EXCLUDED.name,
                      unit = EXCLUDED.unit,
                      unit_cost_inr = EXCLUDED.unit_cost_inr,
                      provider = EXCLUDED.provider,
                      category = EXCLUDED.category,
                      color = EXCLUDED.color,
                      updated_at = now()
                    """
                ),
                {"id": sid, **row},
            )

    if conn is not None:
        _upsert(conn)
        return
    with _engine().begin() as c:
        _upsert(c)
