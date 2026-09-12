"""Prompt versions: mapping, listing, create/patch, restore-as-draft, discard.

One module of the ``db_prompt_studio`` package (was one 3,400-line file).
Call sites stay ``db.*``; the package re-exports every name.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import text

from db_prompt_studio.common import (
    _compiled_select,
    _db,
)
from db_prompt_studio.voices import (
    get_tts_voice_warning,
    resolve_prompt_azure_voice,
)
from db_prompt_studio.deployments import (
    DEFAULT_BOT_ID,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Persona & Prompt Studio (PS-1 reads)
# ---------------------------------------------------------------------------

_DEFAULT_PERSONA = {
    "traits": {"empathy": 82, "firmness": 40, "formality": 55, "verbosity": 60, "upsell": 20},
    "language": "English",
    "fallbackLanguages": ["Hindi"],
}

_DEFAULT_VOICE = {
    "voiceId": "priya",
    "azureVoiceName": "en-IN-AartiNeural",
    "speed": 1.0,
    "pitch": 0,
    "warmth": 62,
    "pauseMs": 320,
    "sampleText": "Hello Rahul, this is a courtesy call from HDFC about your EMI. Do you have a minute?",
}

_DEFAULT_AZURE_TTS_VOICE = "en-IN-AartiNeural"

_DEFAULT_GUARDRAILS = {
    "prohibited": ["guarantee", "police", "arrest", "threaten", "family will pay", "harassment"],
    "escalateAbuse": True,
    "escalateLegal": True,
    "neverQuoteRate": True,
    "neverPromiseWaiver": True,
    "alwaysDiscloseRecording": True,
    "refusePoliticsReligion": True,
    "maxTurns": 20,
    "maxSeconds": 480,
}

def _prompt_persona(raw: Any) -> dict[str, Any]:
    _mod = _db()
    _as_dict = _mod._as_dict
    data = _as_dict(raw)
    traits_in = data.get("traits") if isinstance(data.get("traits"), dict) else {}
    base = _DEFAULT_PERSONA["traits"]
    traits = {
        "empathy": int(traits_in.get("empathy", base["empathy"])),
        "firmness": int(traits_in.get("firmness", base["firmness"])),
        "formality": int(traits_in.get("formality", base["formality"])),
        "verbosity": int(traits_in.get("verbosity", base["verbosity"])),
        "upsell": int(traits_in.get("upsell", base["upsell"])),
    }
    fallback = data.get("fallbackLanguages")
    if not isinstance(fallback, list):
        fallback = list(_DEFAULT_PERSONA["fallbackLanguages"])
    return {
        "traits": traits,
        "language": str(data.get("language") or _DEFAULT_PERSONA["language"]),
        "fallbackLanguages": [str(x) for x in fallback],
    }

def _prompt_voice(raw: Any) -> dict[str, Any]:
    # Local, like every other agent_core.tuning use in this module. The module
    # itself imports nothing from db, so this is convention rather than a cycle.
    _mod = _db()
    _as_dict = _mod._as_dict
    from agent_core.tuning import normalize_tts_params

    data = _as_dict(raw)
    return {
        "voiceId": str(data.get("voiceId") or _DEFAULT_VOICE["voiceId"]),
        "azureVoiceName": str(
            data.get("azureVoiceName")
            or data.get("shortName")
            or _DEFAULT_VOICE.get("azureVoiceName")
            or _DEFAULT_AZURE_TTS_VOICE
        ).strip()
        or _DEFAULT_AZURE_TTS_VOICE,
        "speed": float(data.get("speed", _DEFAULT_VOICE["speed"])),
        "pitch": int(data.get("pitch", _DEFAULT_VOICE["pitch"])),
        "warmth": int(data.get("warmth", _DEFAULT_VOICE["warmth"])),
        "pauseMs": int(data.get("pauseMs", _DEFAULT_VOICE["pauseMs"])),
        "sampleText": str(data.get("sampleText") or _DEFAULT_VOICE["sampleText"]),
        "style": (str(data["style"]).strip() if data.get("style") else None),
        # Provider-specific TTS controls (Fish temperature, Cartesia speed, ...).
        # This function is a whitelist, so a key it does not name is dropped —
        # which is how the Voice tab's model controls used to reach the preview
        # and nothing else. Sanitised by the same helper `normalize_tuning`
        # uses, so what is stored and what is folded into AgentTuning agree.
        "params": normalize_tts_params(data.get("params")),
    }

def _prompt_guardrails(raw: Any) -> dict[str, Any]:
    _mod = _db()
    _as_dict = _mod._as_dict
    data = _as_dict(raw)
    prohibited = data.get("prohibited")
    if not isinstance(prohibited, list):
        prohibited = list(_DEFAULT_GUARDRAILS["prohibited"])
    return {
        "prohibited": [str(x) for x in prohibited],
        "escalateAbuse": bool(data.get("escalateAbuse", _DEFAULT_GUARDRAILS["escalateAbuse"])),
        "escalateLegal": bool(data.get("escalateLegal", _DEFAULT_GUARDRAILS["escalateLegal"])),
        "neverQuoteRate": bool(data.get("neverQuoteRate", _DEFAULT_GUARDRAILS["neverQuoteRate"])),
        "neverPromiseWaiver": bool(data.get("neverPromiseWaiver", _DEFAULT_GUARDRAILS["neverPromiseWaiver"])),
        "alwaysDiscloseRecording": bool(
            data.get("alwaysDiscloseRecording", _DEFAULT_GUARDRAILS["alwaysDiscloseRecording"])
        ),
        "refusePoliticsReligion": bool(
            data.get("refusePoliticsReligion", _DEFAULT_GUARDRAILS["refusePoliticsReligion"])
        ),
        "maxTurns": int(data.get("maxTurns", _DEFAULT_GUARDRAILS["maxTurns"])),
        "maxSeconds": int(data.get("maxSeconds", _DEFAULT_GUARDRAILS["maxSeconds"])),
    }

def _prompt_version_status(raw: Any) -> str:
    s = str(raw or "archived")
    return s if s in {"draft", "published", "archived"} else "archived"

def _prompt_flow(raw: Any) -> dict[str, Any]:
    """The stored graph if it can be read, the sentinel plus a flag if it cannot.

    Degrading to `{}` alone would be the same failure this codebase keeps
    finding: an unreadable graph and a card that never authored one would render
    identically, as an empty canvas over "No authored flow". `flowUnreadable`
    is what lets the studio say which of the two it is looking at.
    """
    if not isinstance(raw, dict):
        return {"flow": {}, "flowUnreadable": False}
    if not raw:
        return {"flow": {}, "flowUnreadable": False}
    import flow_graph

    try:
        flow_graph.parse_graph(raw)
    except Exception:
        logger.warning("prompt version holds an unreadable flow graph; serving it as empty")
        return {"flow": {}, "flowUnreadable": True}
    return {"flow": raw, "flowUnreadable": False}

def _refuses_flow_write(
    conn: Any, version_id: str, flow_val: Any, payload: dict[str, Any]
) -> bool:
    """True when this write would erase an unreadable graph by accident.

    Only one shape is refused: the *empty sentinel* landing on a column that
    does not parse, without ``replaceUnreadable``. That is exactly the autosave
    path — ``_prompt_flow`` serves ``{}`` for an unreadable row, the response
    model materialises it into ``{version:1,globalTools:[],nodes:[],edges:[]}``,
    the editor stores that non-null object, and the "omit when null" protection
    then does not apply. One keystroke in the prompt tab and the corrupt row is
    gone, along with the only signal that it was ever there.

    A real graph still overwrites freely: recovering by loading the built-in
    script must not need a flag. Starting from blank does, because that write is
    indistinguishable on the wire from the accident.
    """
    if payload.get("replaceUnreadable"):
        return False
    import flow_graph

    if isinstance(flow_val, dict) and flow_val and not flow_graph.is_unauthored(flow_val):
        return False
    stored = _db()._one(
        conn.execute(
            text("SELECT flow FROM prompt_versions WHERE id = :id"), {"id": version_id}
        )
    )
    raw = (stored or {}).get("flow")
    if not isinstance(raw, dict) or not raw:
        return False
    try:
        flow_graph.parse_graph(raw)
    except Exception:
        return True
    return False

def _map_prompt_version(r: dict[str, Any]) -> dict[str, Any]:
    from agent_core.tuning import default_tuning, normalize_tuning

    label = r.get("label") or r.get("id") or ""
    created = r.get("created_at")
    raw_tuning = r.get("tuning")
    tuning = normalize_tuning(raw_tuning) if isinstance(raw_tuning, dict) and raw_tuning else default_tuning()
    return {
        "id": r["id"],
        "label": str(label),
        "author": r.get("author_name") or "Unknown",
        "status": _prompt_version_status(r.get("status")),
        "createdAt": created if isinstance(created, str) else (created.isoformat() if created else ""),
        "summary": r.get("summary") or "",
        "prompt": r.get("prompt") or "",
        "persona": _prompt_persona(r.get("persona")),
        "voice": _prompt_voice(r.get("voice")),
        "guardrails": _prompt_guardrails(r.get("guardrails")),
        "tuning": tuning,
        # Authored conversation graph; '{}' on every version that predates flow
        # authoring, which flow_graph.parse_graph reads as "no graph".
        #
        # Checked here rather than handed straight to the response model. That
        # model's `flow` is a FlowGraph with extra="forbid", so ONE row holding
        # an unknown key or an out-of-vocabulary enum — a hand-edited row, or a
        # write from a newer build — raised ResponseValidationError, and that is
        # a 500 on GET /prompt-versions for the whole bot. Every version becomes
        # unreadable because one of them is, and the studio has no way in at
        # all: no history, no editor, no diff, and no way to discard the row
        # that caused it.
        **_prompt_flow(r.get("flow")),
        "botId": r.get("bot_id") or DEFAULT_BOT_ID,
        "agentCard": r.get("agent_card") if isinstance(r.get("agent_card"), dict) else {},
        "compiled": (
            r.get("compiled")
            if isinstance(r.get("compiled"), dict) and r.get("compiled").get("bundle_hash")
            else None
        ),
    }

def list_prompt_versions(
    *,
    limit: int | None = None,
    offset: int | None = None,
    bot_id: str | None = None,
) -> list[dict[str, Any]]:
    """Version history newest-first — editor rail. Grows with every draft."""
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    where = "WHERE p.bot_id = :bot_id" if bot_id else ""
    params: dict[str, Any] = {"limit": page, "offset": skip}
    if bot_id:
        params["bot_id"] = bot_id
    with engine.connect() as conn:
        compiled = _compiled_select(conn)
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at, {compiled},
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    {where}
                    ORDER BY p.created_at DESC, p.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                params,
            )
        )
        return [_map_prompt_version(r) for r in rows]

def get_published_prompt_version(bot_id: str | None = None) -> dict[str, Any] | None:
    """Editor live badge — must match active prod deployment (invariant)."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    bid = (bot_id or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    with engine.connect() as conn:
        compiled = _compiled_select(conn)
        r = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at, {compiled},
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.status = 'published' AND p.bot_id = :bot_id
                    LIMIT 1
                    """
                ),
                {"bot_id": bid},
            )
        )
        return _map_prompt_version(r) if r else None

def get_prompt_version(version_id: str) -> dict[str, Any] | None:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    with engine.connect() as conn:
        compiled = _compiled_select(conn)
        r = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at, {compiled},
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.id = :id
                    """
                ),
                {"id": version_id},
            )
        )
        return _map_prompt_version(r) if r else None

_PROMPT_VERSION_SELECT = """
    SELECT
      p.id, p.label, p.summary, p.status, p.prompt,
      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
      p.bot_id, p.agent_card, p.created_at,
      COALESCE(u.name, 'Unknown') AS author_name
    FROM prompt_versions p
    LEFT JOIN users u ON u.id = p.author_user_id
"""

def _prompt_id_from_label(label: str | None) -> str:
    _mod = _db()
    _id = _mod._id
    if label:
        slug = re.sub(r"[^a-zA-Z0-9]+", "_", label.strip()).strip("_").lower()
        if slug:
            return slug
    return _id("pv").lower()

def _fetch_prompt_version(conn: Any, version_id: str) -> dict[str, Any] | None:
    _mod = _db()
    _one = _mod._one
    r = _one(
        conn.execute(
            text(_PROMPT_VERSION_SELECT + " WHERE p.id = :id"),
            {"id": version_id},
        )
    )
    return _map_prompt_version(r) if r else None

def create_prompt_version(payload: dict[str, Any]) -> dict[str, Any]:
    """Insert a draft prompt version with validated jsonb payloads."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _actor_user_id = _mod._actor_user_id
    _jsonb = _mod._jsonb
    _as_dict = _mod._as_dict
    from agent_core.tuning import apply_voice_config_overlay, default_tuning

    label = (payload.get("label") or "").strip() or None
    version_id = _prompt_id_from_label(label)
    voice = _prompt_voice(payload.get("voice"))
    # Seed draft.tuning from Prompt Studio voice sliders (one source of truth).
    draft_tuning = apply_voice_config_overlay(
        default_tuning(),
        voice_name=resolve_prompt_azure_voice(voice),
        speed=float(voice.get("speed", 1.0)),
        pitch=int(voice.get("pitch", 0)),
        warmth=int(voice.get("warmth", 60)),
        params=voice.get("params"),
        style=voice.get("style") or None,
    )
    with engine.begin() as conn:
        # Avoid colliding with an existing id (e.g. republish of same label slug).
        if _one(conn.execute(text("SELECT 1 FROM prompt_versions WHERE id = :id"), {"id": version_id})):
            version_id = f"{version_id}-{uuid.uuid4().hex[:6]}"
        bot_id = str(payload.get("botId") or payload.get("bot_id") or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
        if not _one(conn.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": bot_id})):
            raise KeyError(f"bot_not_found:{bot_id}")
        card_raw = payload.get("agentCard") if "agentCard" in payload else payload.get("agent_card")
        if card_raw is None:
            # Inherit this bot's current card before reaching for the on-disk
            # first-party default. Autosave and publish both create versions
            # without an agentCard, so jumping straight to card_dump reset every
            # authored skill/tool edit on a first-party bot, and wiped the card
            # outright on a tenant clone (card_dump raises for those ids).
            inherited = _one(
                conn.execute(
                    text(
                        """
                        SELECT agent_card FROM prompt_versions
                         WHERE bot_id = :bot_id
                           AND status IN ('published', 'draft')
                           AND agent_card IS NOT NULL
                           AND agent_card <> '{}'::jsonb
                         ORDER BY (status = 'published') DESC, created_at DESC, id DESC
                         LIMIT 1
                        """
                    ),
                    {"bot_id": bot_id},
                )
            )
            card_raw = _as_dict((inherited or {}).get("agent_card")) or None
        if card_raw is None:
            try:
                from agent_core.cards.defaults import card_dump as _card_dump

                card_raw = _card_dump(bot_id)
            except KeyError:
                card_raw = {}
        conn.execute(
            text(
                """
                INSERT INTO prompt_versions (
                  id, tenant_id, bot_id, author_user_id, status, prompt, persona, voice,
                  guardrails, tuning, flow, agent_card, label, summary, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :bot_id, :author, 'draft', :prompt,
                  CAST(:persona AS jsonb), CAST(:voice AS jsonb), CAST(:guardrails AS jsonb),
                  CAST(:tuning AS jsonb), CAST(:flow AS jsonb), CAST(:agent_card AS jsonb),
                  :label, :summary, now(), now()
                )
                """
            ),
            {
                "id": version_id,
                "tenant_id": _tenant(),
                "bot_id": bot_id,
                "author": _actor_user_id(),
                "prompt": payload["prompt"],
                "persona": _jsonb(payload["persona"]),
                "voice": _jsonb(voice),
                "guardrails": _jsonb(payload["guardrails"]),
                "tuning": _jsonb(draft_tuning),
                # Absent flow stores '{}', which parse_graph reads as "no graph"
                # and the runtime treats as "use the built-in flow".
                "flow": _jsonb(payload.get("flow") or {}),
                "agent_card": _jsonb(card_raw if isinstance(card_raw, dict) else {}),
                "label": label,
                "summary": payload.get("summary") or "",
            },
        )
        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row

def patch_prompt_version(version_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Update draft fields only — raises ValueError if not a draft."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _jsonb = _mod._jsonb
    _as_dict = _mod._as_dict
    _tenant = _mod._tenant
    with engine.begin() as conn:
        # Scoped: this lookup is the gate for everything below it, so a
        # cross-tenant id takes the not-found path instead of reaching a
        # write. The card-level writes in this module already scope; the
        # version-level ones did not.
        existing = _one(
            conn.execute(
                text(
                    "SELECT id, status, voice, tuning FROM prompt_versions "
                    "WHERE id = :id AND tenant_id = :t"
                ),
                {"id": version_id, "t": _tenant()},
            )
        )
        if not existing:
            raise KeyError(f"prompt_version_not_found: {version_id}")
        if existing["status"] != "draft":
            raise ValueError("prompt_version_not_draft")

        sets: list[str] = []
        params: dict[str, Any] = {"id": version_id}
        if "label" in payload and payload["label"] is not None:
            sets.append("label = :label")
            params["label"] = str(payload["label"]).strip() or None
        if payload.get("prompt") is not None:
            sets.append("prompt = :prompt")
            params["prompt"] = payload["prompt"]
        if payload.get("persona") is not None:
            sets.append("persona = CAST(:persona AS jsonb)")
            params["persona"] = _jsonb(payload["persona"])
        if payload.get("voice") is not None:
            from agent_core.tuning import apply_voice_config_overlay, normalize_tuning

            voice = _prompt_voice(payload["voice"])
            sets.append("voice = CAST(:voice AS jsonb)")
            params["voice"] = _jsonb(voice)
            # Keep draft.tuning in sync with VoicePanel sliders (publish reads this).
            folded = apply_voice_config_overlay(
                normalize_tuning(_as_dict(existing.get("tuning"))),
                voice_name=resolve_prompt_azure_voice(voice),
                speed=float(voice.get("speed", 1.0)),
                pitch=int(voice.get("pitch", 0)),
                warmth=int(voice.get("warmth", 60)),
                params=voice.get("params"),
                style=voice.get("style") or None,
            )
            sets.append("tuning = CAST(:tuning AS jsonb)")
            params["tuning"] = _jsonb(folded)
        if payload.get("guardrails") is not None:
            sets.append("guardrails = CAST(:guardrails AS jsonb)")
            params["guardrails"] = _jsonb(payload["guardrails"])
        if payload.get("summary") is not None:
            sets.append("summary = :summary")
            params["summary"] = payload["summary"]
        if "tuning" in payload and payload["tuning"] is not None:
            from agent_core.tuning import normalize_tuning

            # Explicit Tuning Studio / Promote write wins over voice fold above
            # when both arrive in one patch (rare).
            sets = [s for s in sets if not s.startswith("tuning =")]
            sets.append("tuning = CAST(:tuning AS jsonb)")
            params["tuning"] = _jsonb(normalize_tuning(payload["tuning"]))
        # Key present vs omitted, not truthiness: an explicit {} means "no
        # authored graph" (use the built-in script). A missing key leaves the
        # stored graph alone so a save that never opened the flow tab cannot
        # wipe one.
        if "flow" in payload:
            flow_val = payload["flow"]
            if hasattr(flow_val, "model_dump"):
                flow_val = flow_val.model_dump()
            if _refuses_flow_write(conn, version_id, flow_val, payload):
                # 409 through _handle_write's ValueError mapping, like every
                # other refusal in this module.
                raise ValueError("flow_unreadable_not_replaced")
            sets.append("flow = CAST(:flow AS jsonb)")
            params["flow"] = _jsonb(flow_val or {})
        card_val = payload["agentCard"] if "agentCard" in payload else payload.get("agent_card") if "agent_card" in payload else None
        if "agentCard" in payload or "agent_card" in payload:
            if hasattr(card_val, "model_dump"):
                card_val = card_val.model_dump()
            sets.append("agent_card = CAST(:agent_card AS jsonb)")
            params["agent_card"] = _jsonb(card_val if isinstance(card_val, dict) else {})
        if not sets:
            row = _fetch_prompt_version(conn, version_id)
            assert row is not None
            return row
        sets.append("updated_at = now()")
        conn.execute(
            text(f"UPDATE prompt_versions SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row

def _restorable_voice(raw: Any) -> dict[str, Any]:
    """The stored voice, normalised to something that can actually speak.

    Restore copied the jsonb verbatim, which is the one write path that never
    ran the voice through ``_prompt_voice``. A version carrying a hand-edited or
    legacy id therefore produced a draft whose Voice tab named one voice and
    whose runtime spoke the fallback — and the draft could then be published in
    that state. The catalog check on top of the whitelist is what turns an id
    nothing can resolve into the same fallback the picker already displays.

    Provider controls go with it. ``style`` and ``params`` are the vocabulary of
    the provider that owns the missing voice; carried onto an Azure fallback
    they are noise the SSML preview would try to honour.
    """
    voice = _prompt_voice(raw)
    warning = get_tts_voice_warning(resolve_prompt_azure_voice(voice))
    if warning and warning.get("code") in {"missing", "removed"} and warning.get("fallbackVoice"):
        fallback = str(warning["fallbackVoice"])
        voice["voiceId"] = fallback
        voice["azureVoiceName"] = fallback
        voice["style"] = None
        voice["params"] = {}
    return voice

def restore_prompt_version_as_draft(version_id: str) -> dict[str, Any]:
    """Copy any version into a new draft — never mutates live published/deployment."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _actor_user_id = _mod._actor_user_id
    _jsonb = _mod._jsonb
    _as_dict = _mod._as_dict
    from agent_core.tuning import normalize_tuning

    with engine.begin() as conn:
        source = _one(
            conn.execute(
                text(
                    """
                    SELECT id, label, prompt, persona, voice, guardrails, tuning, flow,
                           bot_id, agent_card
                    FROM prompt_versions WHERE id = :id AND tenant_id = :t
                    """
                ),
                {"id": version_id, "t": _tenant()},
            )
        )
        if not source:
            raise KeyError(f"prompt_version_not_found: {version_id}")

        new_id = f"{source['id']}-r-{uuid.uuid4().hex[:6]}"
        src_label = source.get("label") or source["id"]
        tuning_json = _jsonb(normalize_tuning(_as_dict(source.get("tuning"))))
        conn.execute(
            text(
                """
                INSERT INTO prompt_versions (
                  id, tenant_id, bot_id, author_user_id, status, prompt, persona, voice,
                  guardrails, tuning, flow, agent_card, label, summary, created_at, updated_at
                ) VALUES (
                  :id, :tenant_id, :bot_id, :author, 'draft', :prompt,
                  CAST(:persona AS jsonb), CAST(:voice AS jsonb), CAST(:guardrails AS jsonb),
                  CAST(:tuning AS jsonb), CAST(:flow AS jsonb), CAST(:agent_card AS jsonb),
                  :label, :summary, now(), now()
                )
                """
            ),
            {
                "id": new_id,
                "tenant_id": _tenant(),
                "bot_id": source.get("bot_id") or DEFAULT_BOT_ID,
                "author": _actor_user_id(),
                "prompt": source["prompt"],
                "persona": _jsonb(_as_dict(source.get("persona"))),
                "voice": _jsonb(_restorable_voice(source.get("voice"))),
                "guardrails": _jsonb(_as_dict(source.get("guardrails"))),
                "tuning": tuning_json,
                # Carried across: a restore that dropped the graph would produce
                # a draft that is not actually the version it claims to restore.
                "flow": _jsonb(_as_dict(source.get("flow"))),
                "agent_card": _jsonb(_as_dict(source.get("agent_card"))),
                # The source's label, carried. NULL here made a publish of the
                # restored draft stamp a row id as the version label.
                "label": source.get("label"),
                "summary": f"restored from {src_label}",
            },
        )
        row = _fetch_prompt_version(conn, new_id)
    assert row is not None
    return row

def discard_prompt_version(version_id: str) -> dict[str, Any]:
    """Archive a draft only — never touches published / deployments."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    with engine.begin() as conn:
        # Scoped: this lookup is the gate for everything below it, so a
        # cross-tenant id takes the not-found path instead of reaching a
        # write. The card-level writes in this module already scope; the
        # version-level ones did not.
        existing = _one(
            conn.execute(
                text(
                    "SELECT id, status FROM prompt_versions "
                    "WHERE id = :id AND tenant_id = :t"
                ),
                {"id": version_id, "t": _tenant()},
            )
        )
        if not existing:
            raise KeyError(f"prompt_version_not_found: {version_id}")
        if existing["status"] != "draft":
            raise ValueError("prompt_version_not_draft")
        conn.execute(
            text(
                """
                UPDATE prompt_versions
                SET status = 'archived', updated_at = now()
                WHERE id = :id AND status = 'draft'
                """
            ),
            {"id": version_id},
        )
        row = _fetch_prompt_version(conn, version_id)
    assert row is not None
    return row
