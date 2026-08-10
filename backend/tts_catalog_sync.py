"""Sync Azure Speech voices/list into tts_voice_catalog.

Sources: live Azure API, offline JSON dump (utf-8-sig), or admin trigger.
Never hard-deletes rows — soft-removes when missing from the fetch.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text

from env_loader import load_env

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-IN-AartiNeural"
_REPO_JSON = Path(__file__).resolve().parent.parent / "azure_tts_voices.json"


def derive_price_tier(short_name: str, voice_type: str | None = None) -> str:
    """Map Azure ShortName / VoiceType → display price tier."""
    sn = (short_name or "").strip()
    vt = (voice_type or "").strip()
    if "DragonHD" in sn or ":Dragon" in sn:
        return "hd"
    if vt == "NeuralHD":
        return "hd"
    if "HDFlash" in sn or sn.endswith("Flash") or "MAI-Voice" in sn:
        return "hd_flash"
    if "Turbo" in sn:
        return "turbo"
    return "standard"


def is_premium_tier(tier: str) -> bool:
    return (tier or "standard") != "standard"


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_azure_voice(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Flatten one Azure voices/list object into a catalog row dict."""
    short = str(raw.get("ShortName") or "").strip()
    if not short:
        return None
    tags = raw.get("VoiceTag") if isinstance(raw.get("VoiceTag"), dict) else {}
    voice_type = str(raw.get("VoiceType") or "Neural").strip() or "Neural"
    tier = derive_price_tier(short, voice_type)
    styles = _as_list(raw.get("StyleList") or tags.get("StyleList"))
    return {
        "short_name": short,
        "display_name": str(raw.get("DisplayName") or short).strip() or short,
        "local_name": str(raw.get("LocalName") or raw.get("DisplayName") or "").strip(),
        "gender": str(raw.get("Gender") or "Neutral").strip() or "Neutral",
        "locale": str(raw.get("Locale") or "").strip() or "und",
        "locale_name": str(raw.get("LocaleName") or "").strip(),
        "voice_type": voice_type,
        "status": str(raw.get("Status") or "GA").strip() or "GA",
        "sample_rate_hertz": _int_or_none(raw.get("SampleRateHertz")),
        "words_per_minute": _int_or_none(raw.get("WordsPerMinute")),
        "styles": [str(s) for s in styles if str(s).strip()],
        "model_series": [str(x) for x in _as_list(tags.get("ModelSeries")) if str(x).strip()],
        "personalities": [
            str(x) for x in _as_list(tags.get("VoicePersonalities")) if str(x).strip()
        ],
        "scenarios": [
            str(x) for x in _as_list(tags.get("TailoredScenarios")) if str(x).strip()
        ],
        "price_tier": tier,
        "is_premium": is_premium_tier(tier),
        "raw": raw,
    }


def fetch_azure_voices(*, key: str | None = None, region: str | None = None) -> list[dict[str, Any]]:
    load_env()
    speech_key = (key or os.getenv("AZURE_SPEECH_KEY") or "").strip()
    speech_region = (region or os.getenv("AZURE_SPEECH_REGION") or "").strip()
    if not speech_key or not speech_region:
        raise RuntimeError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION required for Azure sync")
    url = f"https://{speech_region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
    with httpx.Client(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        resp = client.get(url, headers={"Ocp-Apim-Subscription-Key": speech_key})
        resp.raise_for_status()
        data = resp.json()
    if not isinstance(data, list):
        raise RuntimeError("Azure voices/list did not return a list")
    return [x for x in data if isinstance(x, dict)]


def load_voices_json(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    with p.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise RuntimeError(f"JSON catalog must be a list: {p}")
    return [x for x in data if isinstance(x, dict)]


def catalog_count(engine: Any) -> int:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT count(*)::int AS n FROM tts_voice_catalog")).mappings().first()
        return int(row["n"]) if row else 0


def last_synced_at(engine: Any) -> datetime | None:
    with engine.connect() as conn:
        row = (
            conn.execute(
                text(
                    """
                    SELECT finished_at
                    FROM tts_voice_sync_runs
                    WHERE finished_at IS NOT NULL AND error IS NULL
                    ORDER BY finished_at DESC
                    LIMIT 1
                    """
                )
            )
            .mappings()
            .first()
        )
        return row["finished_at"] if row else None


def run_sync(
    engine: Any,
    *,
    source: str = "azure",
    json_path: str | Path | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Upsert catalog from Azure or JSON. Soft-remove missing ShortNames."""
    if source not in ("azure", "json_import", "admin"):
        raise ValueError(f"invalid sync source: {source}")

    load_env()
    speech_region = (region or os.getenv("AZURE_SPEECH_REGION") or "").strip()
    run_id = f"tvsync-{uuid.uuid4().hex[:12]}"
    started = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO tts_voice_sync_runs (
                  id, started_at, source, region
                ) VALUES (:id, :started, :source, :region)
                """
            ),
            {
                "id": run_id,
                "started": started,
                "source": "admin" if source == "admin" else source,
                "region": speech_region,
            },
        )

    error: str | None = None
    fetched: list[dict[str, Any]] = []
    try:
        if source == "json_import" or (source == "admin" and json_path):
            path = Path(json_path) if json_path else _REPO_JSON
            fetched = load_voices_json(path)
            effective_source = "json_import" if source == "json_import" else "admin"
        elif source == "admin":
            # Prefer Azure; fall back to bundled JSON if Azure fails.
            try:
                fetched = fetch_azure_voices(region=speech_region or None)
                effective_source = "admin"
            except Exception as azure_exc:
                logger.warning("admin Azure sync failed, trying JSON: %s", azure_exc)
                if _REPO_JSON.is_file():
                    fetched = load_voices_json(_REPO_JSON)
                    effective_source = "admin"
                else:
                    raise
        else:
            fetched = fetch_azure_voices(region=speech_region or None)
            effective_source = "azure"

        rows = [normalize_azure_voice(v) for v in fetched]
        rows = [r for r in rows if r]
        seen = {r["short_name"] for r in rows}
        # Soft-removal is only trustworthy when `fetched` is a complete Azure
        # listing. The bundled azure_tts_voices.json fallback is a partial
        # snapshot — marking everything outside it as removed would empty the
        # voice picker the moment the Azure call fails.
        full_fetch = effective_source == "azure"

        upserted = 0
        unchanged = 0
        with engine.begin() as conn:
            # One prefetch instead of a SELECT per voice: the Azure catalog is
            # ~600 rows and this ran on every sync.
            prior = {
                str(row["short_name"]): dict(row)
                for row in conn.execute(
                    text(
                        """
                        SELECT short_name, display_name, status, price_tier, removed_at
                        FROM tts_voice_catalog
                        """
                    )
                )
                .mappings()
                .all()
            }
            # Classify against the prefetch first, then write every row in one
            # executemany: the per-row execute() was ~600 round-trips per sync.
            params: list[dict[str, Any]] = []
            for r in rows:
                existing = prior.get(r["short_name"])
                params.append(
                    {
                        **r,
                        "styles": json.dumps(r["styles"]),
                        "model_series": json.dumps(r["model_series"]),
                        "personalities": json.dumps(r["personalities"]),
                        "scenarios": json.dumps(r["scenarios"]),
                        "raw": json.dumps(r["raw"]),
                    }
                )
                if existing is None or existing.get("removed_at") is not None:
                    upserted += 1
                elif (
                    existing.get("display_name") != r["display_name"]
                    or existing.get("status") != r["status"]
                    or existing.get("price_tier") != r["price_tier"]
                ):
                    upserted += 1
                else:
                    unchanged += 1

            if params:
                conn.execute(
                    text(
                        """
                        INSERT INTO tts_voice_catalog (
                          short_name, display_name, local_name, gender, locale, locale_name,
                          voice_type, status, sample_rate_hertz, words_per_minute,
                          styles, model_series, personalities, scenarios,
                          price_tier, is_premium, raw,
                          first_seen_at, last_seen_at, removed_at, enabled_for_picker
                        ) VALUES (
                          :short_name, :display_name, :local_name, :gender, :locale, :locale_name,
                          :voice_type, :status, :sample_rate_hertz, :words_per_minute,
                          CAST(:styles AS jsonb), CAST(:model_series AS jsonb),
                          CAST(:personalities AS jsonb), CAST(:scenarios AS jsonb),
                          :price_tier, :is_premium, CAST(:raw AS jsonb),
                          now(), now(), NULL, true
                        )
                        ON CONFLICT (short_name) DO UPDATE SET
                          display_name = EXCLUDED.display_name,
                          local_name = EXCLUDED.local_name,
                          gender = EXCLUDED.gender,
                          locale = EXCLUDED.locale,
                          locale_name = EXCLUDED.locale_name,
                          voice_type = EXCLUDED.voice_type,
                          status = EXCLUDED.status,
                          sample_rate_hertz = EXCLUDED.sample_rate_hertz,
                          words_per_minute = EXCLUDED.words_per_minute,
                          styles = EXCLUDED.styles,
                          model_series = EXCLUDED.model_series,
                          personalities = EXCLUDED.personalities,
                          scenarios = EXCLUDED.scenarios,
                          price_tier = EXCLUDED.price_tier,
                          is_premium = EXCLUDED.is_premium,
                          raw = EXCLUDED.raw,
                          last_seen_at = now(),
                          removed_at = NULL
                        """
                    ),
                    params,
                )

            soft_removed = 0
            # Guard against a truncated fetch wiping the catalog: require a full
            # Azure listing AND a result set that is not a large regression on
            # what we already had. A genuine Azure deprecation removes a handful
            # of voices, never 20%+ in one run.
            live_prior = sum(1 for row in prior.values() if row.get("removed_at") is None)
            plausible = live_prior == 0 or len(seen) >= live_prior * 0.8
            if seen and full_fetch and plausible:
                result = conn.execute(
                    text(
                        """
                        UPDATE tts_voice_catalog
                        SET removed_at = now()
                        WHERE removed_at IS NULL
                          AND NOT (short_name = ANY(CAST(:names AS text[])))
                        """
                    ),
                    {"names": list(seen)},
                )
                soft_removed = int(result.rowcount or 0)
            elif seen and not plausible:
                logger.warning(
                    "tts catalog soft-removal skipped: fetched %s voices vs %s live "
                    "in catalog — refusing to mark the difference removed",
                    len(seen),
                    live_prior,
                )

            conn.execute(
                text(
                    """
                    UPDATE tts_voice_sync_runs
                    SET finished_at = now(),
                        source = :source,
                        fetched_count = :fetched,
                        upserted = :upserted,
                        soft_removed = :soft_removed,
                        unchanged = :unchanged,
                        error = NULL,
                        region = :region
                    WHERE id = :id
                    """
                ),
                {
                    "id": run_id,
                    "source": effective_source if source != "admin" else "admin",
                    "fetched": len(rows),
                    "upserted": upserted,
                    "soft_removed": soft_removed,
                    "unchanged": unchanged,
                    "region": speech_region,
                },
            )

        summary = {
            "id": run_id,
            "source": "admin" if source == "admin" else effective_source,
            "fetchedCount": len(rows),
            "upserted": upserted,
            "softRemoved": soft_removed,
            "unchanged": unchanged,
            "error": None,
            "region": speech_region,
            "defaultVoice": DEFAULT_VOICE,
        }
        logger.info(
            "tts catalog sync ok run=%s fetched=%s upserted=%s soft_removed=%s",
            run_id,
            len(rows),
            upserted,
            soft_removed,
        )
        return summary
    except Exception as exc:
        error = str(exc)
        logger.exception("tts catalog sync failed run=%s", run_id)
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE tts_voice_sync_runs
                        SET finished_at = now(), error = :error
                        WHERE id = :id
                        """
                    ),
                    {"id": run_id, "error": error[:2000]},
                )
        except Exception:
            # The sync usually failed *because* the database is unreachable;
            # letting the bookkeeping write raise here would replace the real
            # error with a secondary one and skip the documented summary.
            logger.exception("tts sync run bookkeeping update failed run=%s", run_id)
        return {
            "id": run_id,
            "source": source,
            "fetchedCount": 0,
            "upserted": 0,
            "softRemoved": 0,
            "unchanged": 0,
            "error": error,
            "region": speech_region,
            "defaultVoice": DEFAULT_VOICE,
        }


def ensure_catalog_seeded(engine: Any) -> dict[str, Any] | None:
    """Boot helper: sync once if catalog is empty."""
    try:
        if catalog_count(engine) > 0:
            return None
    except Exception:
        logger.warning("tts catalog count failed (table may not exist yet)", exc_info=True)
        return None

    load_env()
    key = (os.getenv("AZURE_SPEECH_KEY") or "").strip()
    region = (os.getenv("AZURE_SPEECH_REGION") or "").strip()
    if key and region:
        logger.info("tts catalog empty — seeding from Azure")
        return run_sync(engine, source="azure")
    if _REPO_JSON.is_file():
        logger.info("tts catalog empty — seeding from %s", _REPO_JSON)
        return run_sync(engine, source="json_import", json_path=_REPO_JSON)
    logger.warning("tts catalog empty and no Azure creds / JSON dump available")
    return None
