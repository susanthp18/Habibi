"""Persona presets, the TTS voice catalog, its price tiers and sync runs.

One module of the ``db_prompt_studio`` package (was one 3,400-line file).
Call sites stay ``db.*``; the package re-exports every name.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db_prompt_studio.common import (
    _db,
)

logger = logging.getLogger(__name__)

def list_persona_presets() -> list[dict[str, Any]]:
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    _as_dict = _mod._as_dict
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, config
                    FROM persona_presets
                    WHERE tenant_id = :tenant_id
                    ORDER BY CASE id
                      WHEN 'empathetic' THEN 1
                      WHEN 'firm' THEN 2
                      WHEN 'compliance' THEN 3
                      WHEN 'upsell' THEN 4
                      ELSE 99
                    END, id
                    """
                ),
                {"tenant_id": _tenant()},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            cfg = _as_dict(r.get("config"))
            traits_in = cfg.get("traits") if isinstance(cfg.get("traits"), dict) else {}
            traits = {
                "empathy": int(traits_in.get("empathy", 50)),
                "firmness": int(traits_in.get("firmness", 50)),
                "formality": int(traits_in.get("formality", 50)),
                "verbosity": int(traits_in.get("verbosity", 50)),
                "upsell": int(traits_in.get("upsell", 20)),
            }
            out.append(
                {
                    "id": r["id"],
                    "label": str(cfg.get("label") or r.get("name") or r["id"]),
                    "description": str(cfg.get("description") or ""),
                    "traits": traits,
                    "promptTemplate": str(cfg.get("promptTemplate") or ""),
                }
            )
        return out

def list_tts_voice_provider_counts() -> list[dict[str, Any]]:
    """Voice count per provider, for the catalog's provider filter chips.

    Counts respect the same visibility rules as the default catalog query
    (picker-enabled, not removed, GA) so a chip reading "24" and the list that
    opens when you click it cannot disagree. Premium is *included* here on
    purpose: the chip tells you the provider exists, the premium toggle governs
    what the list then shows.
    """
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT COALESCE(provider_id, 'azure') AS provider_id, count(*) AS n
                FROM tts_voice_catalog
                WHERE enabled_for_picker = true
                  AND removed_at IS NULL
                  AND status = 'GA'
                GROUP BY 1
                ORDER BY 2 DESC
                """
            )
        ).mappings().all()
    return [{"providerId": r["provider_id"], "count": int(r["n"])} for r in rows]

def list_tts_voice_locale_counts(*, limit: int = 60) -> list[dict[str, Any]]:
    """Voice count per locale, for the catalog's locale picker.

    The picker used to carry a hardcoded India-only preset list (en-IN, hi-IN,
    ta, te, kn, mr, bn). Once the catalog holds ~140 locales that list is not a
    shortcut, it is a filter that hides most of the catalog from the operator.
    Deriving from the data means a locale appears the moment a voice for it does.
    """
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.locale,
                       max(c.locale_name) AS locale_name,
                       count(*) AS n
                FROM tts_voice_catalog c
                WHERE c.enabled_for_picker = true
                  AND c.removed_at IS NULL
                  AND c.status = 'GA'
                  AND c.locale <> ''
                GROUP BY c.locale
                ORDER BY count(*) DESC, c.locale
                LIMIT :limit
                """
            ),
            {"limit": max(1, min(int(limit or 60), 400))},
        ).mappings().all()
    return [
        {
            "locale": r["locale"],
            "localeName": r["locale_name"] or r["locale"],
            "count": int(r["n"]),
        }
        for r in rows
    ]

def list_tts_voices() -> list[dict[str, Any]]:
    """Legacy studio alias rows (priya/…); picker uses tts_voice_catalog instead.

    Kept for optional ShortName resolution when an old draft still stores a
    studio alias as voiceId. Deployments no longer FK to this table.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    _as_dict = _mod._as_dict
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, config, enabled
                    FROM tts_voices
                    WHERE enabled = true AND tenant_id = :tenant_id
                    ORDER BY CASE id
                      WHEN 'priya' THEN 1
                      WHEN 'anjali' THEN 2
                      WHEN 'neha' THEN 3
                      WHEN 'ravi' THEN 4
                      WHEN 'arjun' THEN 5
                      WHEN 'kabir' THEN 6
                      ELSE 99
                    END, name, id
                    """
                ),
                {"tenant_id": _tenant()},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            cfg = _as_dict(r.get("config"))
            gender = cfg.get("gender") or "Female"
            if gender not in ("Female", "Male"):
                gender = "Female"
            out.append(
                {
                    "id": r["id"],
                    "name": r["name"] or r["id"],
                    "gender": gender,
                    "accent": str(cfg.get("accent") or ""),
                    "duration": str(cfg.get("duration") or "0:03"),
                    "azureVoiceName": cfg.get("azureVoiceName"),
                }
            )
        return out

def resolve_prompt_azure_voice(voice: dict[str, Any] | None) -> str:
    """Resolve Prompt Studio voice config → Azure ShortName."""
    _mod = _db()
    _as_dict = _mod._as_dict
    from azure_speech import looks_like_azure_short_name, resolve_azure_voice_name

    data = _as_dict(voice)
    short = str(data.get("azureVoiceName") or data.get("shortName") or "").strip()
    if short:
        return short
    voice_id = str(data.get("voiceId") or "").strip()
    if looks_like_azure_short_name(voice_id):
        return voice_id
    db_name: str | None = None
    if voice_id:
        for v in list_tts_voices():
            if v["id"] == voice_id:
                db_name = v.get("azureVoiceName")
                break
    return resolve_azure_voice_name(voice_id or None, db_azure_name=db_name)

def voice_locale_facts(voice: Any, persona: Any) -> tuple[str, str | None, list[str]]:
    """(the short name that will speak, its catalog locale, the card's tags).

    The three inputs G15 needs, resolved in one place so the compile preview and
    publish cannot disagree about them. The short name comes from
    ``resolve_prompt_azure_voice`` rather than ``voice.voiceId`` because that is
    what seeds ``AgentTuning.tts.voice`` — the gate has to judge the voice that
    will actually speak, not the one the row happens to carry.

    Locale is ``None`` when the catalog cannot resolve the id; the gate skips on
    that rather than guessing, since the runtime falls back to a different voice
    entirely in that case.
    """
    _mod = _db()
    _as_dict = _mod._as_dict
    from agent_core import languages

    cfg = _as_dict(voice)
    short = resolve_prompt_azure_voice(cfg) if cfg else ""
    entry = get_tts_voice_catalog_entry(short) if short else None
    locale = str((entry or {}).get("locale") or "").strip() or None
    p = _as_dict(persona)
    fallbacks = p.get("fallbackLanguages")
    names = [p.get("language"), *(fallbacks if isinstance(fallbacks, list) else [])]
    tags: list[str] = []
    for name in names:
        tag = languages.tag_for(str(name)) if name else None
        if tag and tag not in tags:
            tags.append(tag)
    return short, locale, tags

def voice_provider_facts(
    short_name: str, locale: str | None, bot_id: str | None
) -> tuple[str | None, set[str] | None]:
    """(the vendor that voice needs, the vendors this bot has bound) for G17.

    Kept out of :func:`voice_locale_facts` so its arity — and the four tests
    that unpack it — stay as they are.

    ``locale`` is the resolution signal, exactly as G15 uses it: when the
    catalog cannot resolve the id there is no honest provider to name, and the
    runtime speaks a fallback voice whose vendor is not the stored id's.

    Bindings are collected across *all* locales rather than through
    ``resolve_chain``, which filters to one. A superset is the fail-safe
    direction here: the gate then only refuses a voice whose vendor is bound
    nowhere for TTS, never one that is merely bound under another locale.
    """
    if not short_name or not locale:
        return None, None
    from provider_tts import provider_for_voice

    _mod = _db()
    try:
        provider = provider_for_voice(short_name)
    except Exception:
        logger.exception("provider lookup failed for voice %s", short_name)
        return None, None
    try:
        with _mod.engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT DISTINCT m.provider_id AS provider_id
                      FROM agent_provider_bindings b
                      JOIN provider_models m ON m.id = b.provider_model_id
                     WHERE b.tenant_id = :tenant
                       AND b.slot = 'tts'
                       AND b.enabled
                       AND m.enabled
                       AND (b.bot_id IS NULL OR b.bot_id = :bot)
                    """
                ),
                {"tenant": _mod.current_tenant(), "bot": bot_id},
            ).mappings().all()
    except Exception:
        # An unmigrated database has no bindings table; the gate skips on None
        # rather than refusing every publish.
        logger.exception("tts binding lookup failed for bot %s", bot_id)
        return provider, None
    return provider, {str(r["provider_id"]) for r in rows}

def _map_catalog_row(r: dict[str, Any], *, include_raw: bool = False) -> dict[str, Any]:
    _mod = _db()
    _as_dict = _mod._as_dict
    styles = r.get("styles")
    if not isinstance(styles, list):
        styles = []
    model_series = r.get("model_series")
    if not isinstance(model_series, list):
        model_series = []
    personalities = r.get("personalities")
    if not isinstance(personalities, list):
        personalities = []
    scenarios = r.get("scenarios")
    if not isinstance(scenarios, list):
        scenarios = []
    out: dict[str, Any] = {
        "shortName": r["short_name"],
        "displayName": r.get("display_name") or r["short_name"],
        "localName": r.get("local_name") or "",
        "gender": r.get("gender") or "Neutral",
        "locale": r.get("locale") or "",
        "localeName": r.get("locale_name") or "",
        "voiceType": r.get("voice_type") or "Neural",
        "status": r.get("status") or "GA",
        "priceTier": r.get("price_tier") or "standard",
        "providerId": r.get("provider_id") or "azure",
        "isPremium": bool(r.get("is_premium")),
        "approxUsdPer1MChars": (
            float(r["approx_usd"]) if r.get("approx_usd") is not None else None
        ),
        "styles": [str(s) for s in styles],
        "personalities": [str(s) for s in personalities],
        "scenarios": [str(s) for s in scenarios],
        "wordsPerMinute": r.get("words_per_minute"),
        "sampleRateHertz": r.get("sample_rate_hertz"),
        "modelSeries": [str(s) for s in model_series],
        "removedAt": r["removed_at"].isoformat() if r.get("removed_at") else None,
        "enabledForPicker": bool(r.get("enabled_for_picker", True)),
    }
    if include_raw:
        out["raw"] = _as_dict(r.get("raw"))
    return out

def list_tts_voice_catalog(
    *,
    q: str | None = None,
    locale: str | None = None,
    gender: str | None = None,
    status: str | None = "GA",
    price_tier: str | None = None,
    provider_id: str | None = None,
    include_premium: bool = False,
    include_removed: bool = False,
    limit: int = 60,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Filtered TTS catalog for the Voice picker.

    ``provider_id`` filters server-side rather than in the browser: the list is
    keyset-paginated, so a client-side provider filter would only ever filter
    the page already fetched and would report counts for a subset.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    from tts_catalog_sync import DEFAULT_VOICE, last_synced_at

    limit = max(1, min(int(limit or 60), 200))
    clauses = ["c.enabled_for_picker = true"]
    params: dict[str, Any] = {"limit": limit}
    if not include_removed:
        clauses.append("c.removed_at IS NULL")
    if not include_premium:
        clauses.append("c.is_premium = false")
    if status:
        clauses.append("c.status = :status")
        params["status"] = status
    if gender:
        clauses.append("lower(c.gender) = lower(:gender)")
        params["gender"] = gender
    if price_tier:
        clauses.append("c.price_tier = :price_tier")
        params["price_tier"] = price_tier
    if provider_id:
        # Rows synced before the registry have NULL provider_id and are Azure
        # by construction, so azure must match them too or the default provider
        # filter would hide 774 voices.
        if provider_id == "azure":
            clauses.append("(c.provider_id = :provider_id OR c.provider_id IS NULL)")
        else:
            clauses.append("c.provider_id = :provider_id")
        params["provider_id"] = provider_id
    if locale:
        loc = locale.strip()
        if loc.endswith("-") or loc.endswith("*"):
            clauses.append("c.locale ILIKE :locale_prefix")
            params["locale_prefix"] = loc.rstrip("*") + "%"
        else:
            clauses.append("c.locale = :locale")
            params["locale"] = loc
    if q:
        clauses.append(
            "("
            "c.short_name ILIKE :q OR c.display_name ILIKE :q OR c.local_name ILIKE :q "
            "OR c.locale_name ILIKE :q OR c.locale ILIKE :q"
            ")"
        )
        params["q"] = f"%{q.strip()}%"
    if cursor:
        clauses.append(
            "(c.locale, c.display_name, c.short_name) > "
            "(SELECT locale, display_name, short_name FROM tts_voice_catalog WHERE short_name = :cursor)"
        )
        params["cursor"] = cursor

    where = " AND ".join(clauses)
    with engine.connect() as conn:
        total = (
            conn.execute(
                text(f"SELECT count(*)::int AS n FROM tts_voice_catalog c WHERE {where}"),
                {k: v for k, v in params.items() if k != "limit"},
            )
            .mappings()
            .first()
        )
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT c.*, t.approx_usd_per_1m_chars AS approx_usd
                    FROM tts_voice_catalog c
                    LEFT JOIN tts_price_tiers t ON t.tier = c.price_tier
                    WHERE {where}
                    ORDER BY c.locale, c.display_name, c.short_name
                    LIMIT :limit
                    """
                ),
                params,
            )
        )
    items = [_map_catalog_row(r) for r in rows]
    next_cursor = items[-1]["shortName"] if len(items) == limit else None
    synced = last_synced_at(engine)
    return {
        "items": items,
        "total": int(total["n"]) if total else 0,
        "nextCursor": next_cursor,
        "lastSyncedAt": synced.isoformat() if synced else None,
        "defaultVoice": DEFAULT_VOICE,
        "premiumHiddenByDefault": True,
    }

def get_tts_voice_catalog_entry(short_name: str) -> dict[str, Any] | None:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    sn = (short_name or "").strip()
    if not sn:
        return None
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT c.*, t.approx_usd_per_1m_chars AS approx_usd
                    FROM tts_voice_catalog c
                    LEFT JOIN tts_price_tiers t ON t.tier = c.price_tier
                    WHERE c.short_name = :sn
                    """
                ),
                {"sn": sn},
            )
        )
    return _map_catalog_row(row, include_raw=True) if row else None

def list_tts_price_tiers() -> list[dict[str, Any]]:
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT tier, label, approx_usd_per_1m_chars, is_premium, notes
                    FROM tts_price_tiers
                    ORDER BY CASE tier
                      WHEN 'standard' THEN 1
                      WHEN 'hd_flash' THEN 2
                      WHEN 'hd' THEN 3
                      WHEN 'turbo' THEN 4
                      ELSE 99
                    END
                    """
                )
            )
        )
    return [
        {
            "tier": r["tier"],
            "label": r["label"],
            "approxUsdPer1MChars": (
                float(r["approx_usd_per_1m_chars"])
                if r.get("approx_usd_per_1m_chars") is not None
                else None
            ),
            "isPremium": bool(r["is_premium"]),
            "notes": r.get("notes") or "",
        }
        for r in rows
    ]

def tts_catalog_is_populated() -> bool:
    """True when the Azure voice catalog has been synced at least once."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.connect() as conn:
        return bool(_one(conn.execute(text("SELECT 1 FROM tts_voice_catalog LIMIT 1"))))

def get_tts_voice_warning(short_name: str | None) -> dict[str, Any] | None:
    """Warn when selected voice is missing / removed / deprecated.

    Returns None when the catalog has never been synced. An empty table means
    "no catalog data", not "Azure removed every voice" — and because the caller
    rewrites ``tts.voice`` to ``fallbackVoice``, judging on no data silently
    forced every call onto the default voice regardless of what the operator
    picked in Prompt Studio or the Tuning Studio.
    """
    from tts_catalog_sync import DEFAULT_VOICE

    sn = (short_name or "").strip()
    if not sn:
        return None
    entry = get_tts_voice_catalog_entry(sn)
    if entry is None:
        # The fallback cannot be "missing" — rewriting it to itself is noise,
        # and reporting it as broken is misleading in the Studio's voice picker.
        if sn == DEFAULT_VOICE or not tts_catalog_is_populated():
            return None
        return {
            "shortName": sn,
            "code": "missing",
            "message": f"Voice {sn} is not in the catalog; runtime will use {DEFAULT_VOICE}.",
            "fallbackVoice": DEFAULT_VOICE,
        }
    if entry.get("removedAt"):
        return {
            "shortName": sn,
            "code": "removed",
            "message": f"Voice {sn} was removed from Azure; runtime will use {DEFAULT_VOICE}.",
            "fallbackVoice": DEFAULT_VOICE,
        }
    if str(entry.get("status") or "").lower() == "deprecated":
        return {
            "shortName": sn,
            "code": "deprecated",
            "message": f"Voice {sn} is deprecated; consider switching to {DEFAULT_VOICE}.",
            "fallbackVoice": DEFAULT_VOICE,
        }
    return None

def _tts_sync_run_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None

    def _ts(value: Any) -> str | None:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    return {
        "id": row["id"],
        "startedAt": _ts(row.get("started_at")),
        "finishedAt": _ts(row.get("finished_at")),
        "source": row.get("source"),
        "fetchedCount": int(row.get("fetched_count") or 0),
        "upserted": int(row.get("upserted") or 0),
        "softRemoved": int(row.get("soft_removed") or 0),
        "unchanged": int(row.get("unchanged") or 0),
        "error": row.get("error"),
        "region": row.get("region") or "",
    }

def latest_tts_sync_run() -> dict[str, Any] | None:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.connect() as conn:
        row = _one(
            conn.execute(
                text(
                    """
                    SELECT id, started_at, finished_at, source, fetched_count, upserted,
                           soft_removed, unchanged, error, region
                    FROM tts_voice_sync_runs
                    ORDER BY started_at DESC
                    LIMIT 1
                    """
                )
            )
        )
    return _tts_sync_run_row(row)

def list_tts_sync_runs(*, limit: int = 20) -> list[dict[str, Any]]:
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    lim = max(1, min(int(limit or 20), 100))
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, started_at, finished_at, source, fetched_count, upserted,
                           soft_removed, unchanged, error, region
                    FROM tts_voice_sync_runs
                    ORDER BY started_at DESC
                    LIMIT :lim
                    """
                ),
                {"lim": lim},
            )
        )
    out: list[dict[str, Any]] = []
    for row in rows:
        mapped = _tts_sync_run_row(row)
        if mapped:
            out.append(mapped)
    return out
