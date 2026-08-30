"""Pull non-Azure voices into ``tts_voice_catalog``.

The Voice tab showed one provider because the catalog held one provider's rows.
``tts_catalog_sync`` speaks Azure's ``voices/list``; nothing spoke anyone else's,
so Cartesia, Deepgram, ElevenLabs and OpenRouter had a registry entry, a chip,
and zero voices behind it.

The table already had the right shape — ``short_name`` / ``display_name`` /
``locale`` / ``gender`` / ``styles`` is provider-neutral — so this writes into
the same table rather than starting a parallel one. Every existing endpoint,
filter and screen therefore works on the new rows without knowing they arrived.

Three shape decisions worth stating, because each vendor disagrees with the
others:

**``short_name`` is namespaced.** Cartesia and ElevenLabs identify voices by
UUID, which is meaningless in a picker and could collide across vendors. Rows
are keyed ``{provider}:{id}`` so the primary key stays unique and a human
reading a binding can tell which vendor it points at.

**A missing locale is ``und``, not ``en-US``.** Cartesia returns a language like
``en``; Deepgram's Aura voices are English-only; Fish auto-detects from the text
and has no locale at all. Guessing ``en-US`` for the last case would put a
multilingual model under an English filter and hide it from every other locale.

**Fish gets exactly one row.** OpenRouter exposes no voice list for it and
rejects ``voice: ""``, so the honest catalog entry is the single default voice —
not an empty provider that looks broken.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx
from sqlalchemy import text

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0


def _has_key(provider: str) -> bool:
    """Whether ``provider`` has any key left to try."""
    from agent_core.providers import pool as pool_mod

    pool = pool_mod.get_pool(provider)
    if len(pool) == 0:
        return False
    return pool.stats().available > 0


def _get(
    provider: str,
    url: str,
    *,
    headers: Any,
    params: dict[str, Any] | None = None,
) -> Any:
    """GET ``url`` with key rotation. Returns ``None`` when no key works.

    ``headers`` is a callable taking the key, because every vendor spells the
    auth header differently. A spent key retires here rather than being handed
    back for the next sync to rediscover — a sync that quietly returned zero
    voices was indistinguishable from a provider with no voices, which is how
    an exhausted key reads as an empty catalog.
    """
    from agent_core.providers import pool as pool_mod

    if not _has_key(provider):
        return None

    def attempt(key: str) -> Any:
        r = httpx.get(url, headers=headers(key), params=params, timeout=_TIMEOUT)
        if pool_mod.is_key_fault(r.status_code):
            raise pool_mod.KeyRejected(
                pool_mod.reason_for_status(r.status_code), status=r.status_code
            )
        r.raise_for_status()
        return r

    try:
        return pool_mod.call_with_rotation(provider, attempt)
    except pool_mod.NoKeysAvailable as exc:
        # Never fatal: one provider's exhausted quota must not abort a sync the
        # other providers can still contribute to.
        logger.warning("%s voices: skipped — %s", provider, exc)
        return None


# ----------------------------------------------------------------- adapters


def fetch_cartesia() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    page: str | None = None
    # Paginated: without following next_page the picker would show the first 30
    # voices and silently claim that is the catalog.
    for _ in range(20):
        params: dict[str, Any] = {"limit": 100}
        if page:
            params["starting_after"] = page
        r = _get(
            "cartesia",
            "https://api.cartesia.ai/voices/",
            headers=lambda k: {"X-API-Key": k, "Cartesia-Version": "2024-11-13"},
            params=params,
        )
        if r is None:
            break
        body = r.json()
        rows = body.get("data") or []
        for v in rows:
            lang = (v.get("language") or "").strip() or "und"
            out.append(
                {
                    "short_name": f"cartesia:{v.get('id')}",
                    "display_name": v.get("name") or str(v.get("id"))[:8],
                    "local_name": "",
                    "gender": (v.get("gender") or "Neutral").title(),
                    "locale": lang,
                    "locale_name": lang,
                    "provider_id": "cartesia",
                    "styles": [],
                    "raw": v,
                }
            )
        if not body.get("has_more"):
            break
        page = body.get("next_page")
        if not page:
            break
    return out


def fetch_deepgram() -> list[dict[str, Any]]:
    r = _get(
        "deepgram",
        "https://api.deepgram.com/v1/models",
        headers=lambda k: {"Authorization": f"Token {k}"},
    )
    if r is None:
        return []
    out: list[dict[str, Any]] = []
    for v in r.json().get("tts") or []:
        langs = v.get("languages") or []
        # Prefer the specific tag ("en-US") over the bare one ("en") when the
        # vendor returns both, so the locale filter can actually narrow.
        locale = next((x for x in langs if "-" in x), (langs[0] if langs else "und"))
        meta = v.get("metadata") or {}
        out.append(
            {
                "short_name": f"deepgram:{v.get('canonical_name') or v.get('name')}",
                "display_name": (v.get("name") or "").replace("aura-2-", "").title()
                or str(v.get("canonical_name")),
                "local_name": "",
                "gender": (meta.get("gender") or "Neutral").title(),
                "locale": locale,
                "locale_name": locale,
                "provider_id": "deepgram",
                "styles": list(meta.get("tags") or []),
                "raw": v,
            }
        )
    return out


def fetch_elevenlabs() -> list[dict[str, Any]]:
    # Observed with the supplied key: the token lacks `voices_read`, so this
    # 401s. `_get` treats that as a key fault — it retires the key with the
    # reason attached, so the Integrations screen names the scope problem
    # instead of the sync silently reporting a provider with no voices — and
    # returns None rather than aborting the providers that do have voices.
    r = _get(
        "elevenlabs",
        "https://api.elevenlabs.io/v1/voices",
        headers=lambda k: {"xi-api-key": k},
    )
    if r is None:
        return []
    out: list[dict[str, Any]] = []
    for v in r.json().get("voices") or []:
        labels = v.get("labels") or {}
        out.append(
            {
                "short_name": f"elevenlabs:{v.get('voice_id')}",
                "display_name": v.get("name") or "",
                "local_name": "",
                "gender": (labels.get("gender") or "Neutral").title(),
                "locale": "und",
                "locale_name": "Multilingual",
                "provider_id": "elevenlabs",
                "styles": [s for s in (labels.get("use_case"), labels.get("description")) if s],
                "raw": v,
            }
        )
    return out


def fetch_openrouter() -> list[dict[str, Any]]:
    """One row: the model's default voice.

    OpenRouter publishes no voice list for S2.1 Pro and 400s on ``voice: ""``,
    so a single default entry is the whole truth. ``locale='und'`` because the
    model detects language from the text — filing it under en-US would hide it
    from every non-English filter, which is the opposite of what it is good at.
    """
    from agent_core.providers import openrouter_tts

    if not _has_key("openrouter"):
        return []
    model = openrouter_tts.default_model()
    return [
        {
            "short_name": f"openrouter:{model}",
            "display_name": "Fish S2.1 Pro (default)",
            "local_name": "",
            "gender": "Neutral",
            "locale": "und",
            "locale_name": "Multilingual (80+)",
            "provider_id": "openrouter",
            "styles": [],
            "raw": {"model": model, "note": "generative; steered by sampler settings"},
        }
    ]


def fetch_fish() -> list[dict[str, Any]]:
    """The Fish voice *library* — 1,000 voices, not one row for the engine.

    The catalog previously held a single "Fish S2.1 Pro (default)" entry, which
    is the model, not something anyone would pick from a voice picker. GET
    /model is free even when synthesis credit is exhausted, so the library
    populates regardless of billing state.
    """
    from agent_core.providers import fish_tts

    if not _has_key("fish"):
        return []
    try:
        voices = fish_tts.list_voices(page_size=100, max_pages=5)
    except fish_tts.FishTTSError:
        logger.exception("fish voice list failed")
        return []

    out: list[dict[str, Any]] = []
    for v in voices:
        langs = v.get("languages") or []
        tags = [str(t) for t in (v.get("tags") or [])]
        # Gender is a tag, not a field, on Fish. Absent means absent — do not
        # guess, or the gender filter starts lying about most of the library.
        gender = next(
            (t.title() for t in tags if t.lower() in ("male", "female", "neutral")),
            "Neutral",
        )
        out.append(
            {
                "short_name": f"fish:{v.get('_id')}",
                "display_name": (v.get("title") or str(v.get("_id"))[:8])[:120],
                "local_name": "",
                "gender": gender,
                "locale": (langs[0] if langs else "und"),
                "locale_name": ", ".join(langs) if langs else "Multilingual",
                "provider_id": "fish",
                # Tags double as the "styles" column — they are what
                # distinguishes one library voice from another.
                "styles": tags[:8],
                "raw": {
                    "id": v.get("_id"),
                    "likes": v.get("like_count"),
                    "languages": langs,
                    "tags": tags,
                    "description": (v.get("description") or "")[:400],
                },
            }
        )
    return out


ADAPTERS = {
    "fish": fetch_fish,
    "cartesia": fetch_cartesia,
    "deepgram": fetch_deepgram,
    "elevenlabs": fetch_elevenlabs,
    "openrouter": fetch_openrouter,
}


# ------------------------------------------------------------------ persist


def run_sync(engine: Any, *, providers: list[str] | None = None) -> dict[str, int]:
    """Upsert each provider's voices. Returns {provider: rows_written}.

    One provider failing does not abort the rest: a 401 on ElevenLabs must not
    cost you Cartesia's catalog.
    """
    targets = providers or list(ADAPTERS)
    counts: dict[str, int] = {}

    for slug in targets:
        adapter = ADAPTERS.get(slug)
        if adapter is None:
            continue
        try:
            rows = adapter()
        except Exception:  # noqa: BLE001
            logger.exception("voice sync failed · provider=%s", slug)
            counts[slug] = 0
            continue

        if not rows:
            counts[slug] = 0
            continue

        with engine.begin() as conn:
            for row in rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO tts_voice_catalog (
                          short_name, display_name, local_name, gender, locale,
                          locale_name, voice_type, status, styles, provider_id,
                          raw, last_seen_at
                        ) VALUES (
                          :short_name, :display_name, :local_name, :gender, :locale,
                          :locale_name, 'Neural', 'GA', CAST(:styles AS jsonb),
                          :provider_id, CAST(:raw AS jsonb), now()
                        )
                        ON CONFLICT (short_name) DO UPDATE SET
                          display_name = EXCLUDED.display_name,
                          gender       = EXCLUDED.gender,
                          locale       = EXCLUDED.locale,
                          locale_name  = EXCLUDED.locale_name,
                          styles       = EXCLUDED.styles,
                          provider_id  = EXCLUDED.provider_id,
                          raw          = EXCLUDED.raw,
                          removed_at   = NULL,
                          last_seen_at = now()
                        """
                    ),
                    {
                        **row,
                        "styles": json.dumps(row.get("styles") or []),
                        "raw": json.dumps(row.get("raw") or {}),
                    },
                )
        counts[slug] = len(rows)
        logger.info("voice sync · provider=%s · rows=%d", slug, len(rows))

    return counts


if __name__ == "__main__":  # pragma: no cover - operator entry point
    import env_loader

    env_loader.load_env()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    import db

    print(run_sync(db.engine))
