"""Persona & Prompt Studio reads and writes.

Peeled from ``db.py`` (WP-036 peel 10). Reads and writes move together:
seventeen internal write→read edges make splitting them a mistake. Call
sites stay ``db.*`` via a bottom-of-file re-export. Reach the engine
through :func:`_db`, never ``from db_core import engine``: the ``db_tx``
fixture wraps ``db.engine``, and a name bound from ``db_core`` bypasses
that proxy.

``list_bot_ids``, ``_iso_ts``, ``get_latest_eval_report`` and
``_latest_twin_gate_report`` stay on ``db.py`` (inbox / eval). This
module reaches them through ``_db()``.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
import uuid
from typing import Any

from sqlalchemy import text

_FROZEN_TOOLS_COL: bool | None = None
_CHAIN_HEADS_TABLE: bool | None = None
_COMPILED_COL: bool | None = None
_BUNDLE_HASH_COL: bool | None = None


def _column_exists(conn: Any, table: str, column: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = :t AND column_name = :c
            """
        ),
        {"t": table, "c": column},
    ).first()
    return bool(row)


def _frozen_tools_select(conn: Any) -> str:
    """``d.frozen_tools`` once migrated; NULL alias until then so SELECTs do not 500."""
    global _FROZEN_TOOLS_COL
    if _FROZEN_TOOLS_COL is None:
        _FROZEN_TOOLS_COL = _column_exists(conn, "bot_deployments", "frozen_tools")
    return "d.frozen_tools" if _FROZEN_TOOLS_COL else "NULL::jsonb AS frozen_tools"


def _compiled_select(conn: Any) -> str:
    global _COMPILED_COL
    if _COMPILED_COL is None:
        _COMPILED_COL = _column_exists(conn, "prompt_versions", "compiled")
    return "p.compiled" if _COMPILED_COL else "NULL::jsonb AS compiled"


def _bundle_hash_select(conn: Any) -> str:
    global _BUNDLE_HASH_COL
    if _BUNDLE_HASH_COL is None:
        _BUNDLE_HASH_COL = _column_exists(conn, "bot_deployments", "bundle_hash")
    return "d.bundle_hash" if _BUNDLE_HASH_COL else "NULL::text AS bundle_hash"


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


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


def list_agent_studio_cards(*, include_archived: bool = False) -> list[dict[str, Any]]:
    """Fleet index: first-party mouths plus tenant clones. Not a fifth first-party.

    Reachability is stamped here rather than per card: it is a property of the
    whole handoff graph, and a single card cannot know whether anything routes
    to it.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    _iso_ts = _mod._iso_ts
    from agent_core.cards.defaults import FIRST_PARTY_BOTS, card_dump
    from agent_core.cards.routing import entry_bindings_by_bot, reachability, resolve_entry

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for bot_id, name, version in FIRST_PARTY_BOTS:
        out.append(_agent_studio_card_summary(bot_id, name, version, card_dump))
        seen.add(bot_id)
    where = "" if include_archived else " AND archived_at IS NULL"
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT id, name, version, archived_at FROM bots
                     WHERE tenant_id = :tenant{where}
                     ORDER BY name, id
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    for r in rows:
        if r["id"] in seen:
            continue
        summary = _agent_studio_card_summary(
            r["id"], r["name"], r.get("version") or "1.0", card_dump
        )
        summary["archivedAt"] = _iso_ts(r.get("archived_at"))
        out.append(summary)
        seen.add(r["id"])

    # The channel default: the fleet index is asking which card is the root of
    # routing, not which number was dialled.
    entry = resolve_entry("voice")
    bound = entry_bindings_by_bot()
    # A retired card cannot carry traffic, so its handoffs are not a path: leaving
    # them in made a card look reachable through an agent that no longer answers.
    routes = reachability(
        [
            (c["botId"], c.get("publishedCard") or {})
            for c in out
            if not c.get("archivedAt")
        ],
        entry=entry,
        entries=bound,
        # A card holding its own active deployment is addressable by bot_id, so
        # it seeds the walk too. deploymentStatus is already computed per card.
        deployed=[c["botId"] for c in out if c.get("deploymentStatus") == "live"],
    )
    for card in out:
        card["entryBotId"] = entry
        card["entryBindings"] = bound.get(card["botId"], [])
        card["reachability"] = (
            "archived" if card.get("archivedAt") else routes.get(card["botId"], "unreachable")
        )
    return out


def _studio_card_versions(bot_id: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """(published, newest draft) for one bot, from one snapshot.

    Two separate calls let a concurrent publish land between them and produce a
    summary whose published id and card came from different rows.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT
                      p.id, p.label, p.summary, p.status, p.prompt,
                      p.persona, p.voice, p.guardrails, p.tuning, p.flow,
                      p.bot_id, p.agent_card, p.created_at,
                      COALESCE(u.name, 'Unknown') AS author_name
                    FROM prompt_versions p
                    LEFT JOIN users u ON u.id = p.author_user_id
                    WHERE p.bot_id = :bot_id AND p.status IN ('published', 'draft')
                    ORDER BY p.created_at DESC, p.id DESC
                    """
                ),
                {"bot_id": bot_id},
            )
        )
    pub = next((r for r in rows if r["status"] == "published"), None)
    draft = next((r for r in rows if r["status"] == "draft"), None)
    return (
        _map_prompt_version(pub) if pub else None,
        _map_prompt_version(draft) if draft else None,
    )


def _worst_eval_status(bot_id: str, get_latest_eval_report) -> str:
    red = (get_latest_eval_report(bot_id=bot_id, kind="redteam") or {}).get("status")
    reg = (get_latest_eval_report(bot_id=bot_id, kind="regression") or {}).get("status")
    statuses = [str(s) for s in (red, reg) if s]
    if any(s in {"fail", "error"} for s in statuses):
        return "fail"
    if any(s == "pass" for s in statuses):
        return "pass"
    return statuses[0] if statuses else "skipped"


def _agent_studio_card_summary(  # noqa: PLR0913 - one row of a wide summary
    bot_id: str,
    name: str,
    version: str,
    card_dump,
    *,
    versions: tuple[dict[str, Any] | None, dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    _mod = _db()
    get_latest_eval_report = _mod.get_latest_eval_report
    from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS

    published, draft = versions if versions is not None else _studio_card_versions(bot_id)
    dep = get_active_deployment(bot_id=bot_id, environment="production")

    def _card_of(row: dict[str, Any] | None) -> dict[str, Any] | None:
        raw = (row or {}).get("agentCard")
        return raw if isinstance(raw, dict) and raw else None

    published_card = _card_of(published)
    # The editor PATCHes the draft, so the draft is what it must read back.
    # Returning the published card here is what made every Skills/Connectors
    # toggle snap back: the write landed on the draft, the refetch returned the
    # published row, and the UI reverted. It also left every cloned card — which
    # has a draft and no published row — showing an empty card.
    card = _card_of(draft) or published_card
    source = "draft" if _card_of(draft) else ("published" if published_card else "default")
    if card is None:
        try:
            card = card_dump(bot_id)
        except KeyError:
            # Not first-party and no version yet. An empty card is unauthorable,
            # which made a bot row with no prompt version a dead end in the
            # editor; a scaffold gives it something real to edit.
            from agent_core.cards.defaults import scaffold_card

            card = scaffold_card(bot_id, name)
            source = "scaffold"
    identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
    tools = card.get("tools") if isinstance(card.get("tools"), dict) else {}
    skill_rows = card.get("skills") if isinstance(card.get("skills"), list) else []
    if not skill_rows:
        try:
            from agent_core.skills.defaults import CARD_SKILLS

            skill_rows = [
                {"skill_id": slug, "version": "1", "pin": "exact"}
                for slug in CARD_SKILLS.get(bot_id, ())
            ]
            if skill_rows:
                card = {**card, "skills": skill_rows}
        except Exception:
            skill_rows = []
    if dep:
        status = "live"
    elif published:
        status = "published"
    elif draft:
        status = "draft"
    else:
        status = "empty"
    return {
        "botId": bot_id,
        "name": identity.get("display_name") or name,
        "version": version,
        "slug": identity.get("slug") or bot_id,
        "purpose": identity.get("purpose") or "",
        "channels": identity.get("channels") or [],
        "skills": [
            s.get("skill_id")
            for s in skill_rows
            if isinstance(s, dict) and s.get("skill_id")
        ],
        "toolCount": len(tools.get("include") or []),
        "evalStatus": _worst_eval_status(bot_id, get_latest_eval_report),
        # None, not 100: a card with no active deployment takes no traffic, and
        # claiming 100% made every unpublished clone look live on the fleet index.
        "trafficPct": (dep or {}).get("trafficPct") if dep else None,
        "deploymentStatus": status,
        "lastPublish": (dep or {}).get("publishedAt"),
        "promptVersionId": (published or {}).get("id"),
        "draftVersionId": (draft or {}).get("id"),
        "hasDraft": draft is not None,
        # What the editor edits vs what production is running — the Ship tab and
        # the fleet badge need to tell those apart.
        "cardSource": source,
        # Explicit rather than inferred: the fleet guessed first-party from
        # cardSource == "default", but a first-party card with a published row
        # reports "published", so its Archive button enabled and then 409'd.
        "isFirstParty": bot_id in FIRST_PARTY_BOT_IDS,
        # Always present: set here rather than only on the tenant branch of
        # list_agent_studio_cards, which left first-party rows without the key
        # while the single-card endpoint always had it.
        "archivedAt": None,
        "agentCard": card,
        "publishedCard": published_card or {},
    }


def _handoff_edges() -> list[tuple[str, Any]]:
    """(bot_id, card) for every bot, from the draft when there is one.

    Only the handoff arrays matter here, but the card column is one read either
    way and parsing it in Python keeps the closure logic in one place.
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
                    SELECT DISTINCT ON (p.bot_id) p.bot_id, p.agent_card
                      FROM prompt_versions p
                      JOIN bots b ON b.id = p.bot_id
                     WHERE p.status IN ('published', 'draft')
                       AND b.archived_at IS NULL
                       AND b.tenant_id = :tenant
                     ORDER BY p.bot_id, (p.status = 'published') DESC, p.created_at DESC
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    return [(r["bot_id"], _as_dict(r.get("agent_card"))) for r in rows]


def _live_deployment_bot_ids() -> list[str]:
    """Cards carrying an active production deployment.

    These are addressable by bot_id whether or not anything hands off to them —
    agent_core/deployment.py resolves ``bot_id or DEFAULT_BOT_ID`` — so they
    seed the reachability walk alongside the configured entry card.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _tenant = _mod._tenant
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT d.bot_id
                      FROM bot_deployments d
                      JOIN bots b ON b.id = d.bot_id
                     WHERE d.status = 'active'
                       AND d.environment = 'production'
                       AND b.archived_at IS NULL
                       AND b.tenant_id = :tenant
                    """
                ),
                {"tenant": _tenant()},
            )
        )
    return [r["bot_id"] for r in rows]


def get_agent_studio_card(bot_id: str) -> dict[str, Any] | None:
    """One card by id — without building the whole fleet to throw it away."""
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _iso_ts = _mod._iso_ts
    from agent_core.cards.defaults import FIRST_PARTY_BOTS, card_dump
    from agent_core.cards.routing import entry_bindings_by_bot, reachability, resolve_entry

    bid = (bot_id or "").strip()
    if not bid:
        return None
    archived_at = None
    summary: dict[str, Any] | None = None
    for fp_id, name, version in FIRST_PARTY_BOTS:
        if fp_id == bid:
            summary = _agent_studio_card_summary(bid, name, version, card_dump)
            break
    if summary is None:
        with engine.connect() as conn:
            row = _one(
                conn.execute(
                    text(
                        """
                        SELECT id, name, version, archived_at FROM bots
                         WHERE id = :id AND tenant_id = :tenant
                        """
                    ),
                    {"id": bid, "tenant": _tenant()},
                )
            )
        if not row:
            return None
        archived_at = _iso_ts(row.get("archived_at"))
        summary = _agent_studio_card_summary(
            bid, row["name"], row.get("version") or "1.0", card_dump
        )
    summary["archivedAt"] = archived_at

    # The channel default: the fleet index is asking which card is the root of
    # routing, not which number was dialled.
    entry = resolve_entry("voice")
    bound = entry_bindings_by_bot()
    edges = {b: c for b, c in _handoff_edges()}
    edges[bid] = summary["agentCard"]  # unsaved-but-loaded card wins for this one
    summary["entryBotId"] = entry
    summary["entryBindings"] = bound.get(bid, [])
    summary["reachability"] = (
        "archived"
        if archived_at
        else reachability(
            list(edges.items()), entry=entry, entries=bound, deployed=_live_deployment_bot_ids()
        ).get(bid, "unreachable")
    )
    return summary


def policy_engines() -> list[dict[str, Any]]:
    """The engines the mouth cannot unbind, and the mode each runs in now.

    Env-driven and legitimately `shadow` on a stack that is still earning
    trust -- which six card lozenges reading "required" could never say."""
    from agent_core.authority import config as authority
    from agent_core.cards.schema import POLICY_ENGINES
    from agent_core.live_qa import config as live_qa
    from agent_core.reco import config as reco
    from agent_core.treatment import config as treatment

    modes = {
        "reco": (reco.mode(), "RECO_MODE"),
        "treatment": (treatment.mode(), "TREATMENT_MODE"),
        "authority": (authority.mode(), "AUTHORITY_MODE"),
        "live_qa": (live_qa.mode(), "LIVE_QA_BARGE_MODE"),
    }
    out = []
    for key, label, tool in POLICY_ENGINES:
        mode, source = modes.get(key, ("always", None))
        out.append({"key": key, "label": label, "tool": tool, "mode": mode, "source": source})
    return out


def list_entry_bindings() -> list[dict[str, Any]]:
    from agent_core.cards.routing import list_entry_bindings as _list

    return _list()


def set_entry_binding(payload: dict[str, Any]) -> dict[str, Any]:
    """Author which card answers a channel (or a dialled number), on the record.

    The bot must hold an active production deployment: a binding to a card
    nothing can serve is a number that rings into silence."""
    from agent_core import change_log
    from agent_core.cards.routing import upsert_entry_binding

    _mod = _db()
    _tenant = _mod._tenant
    bot_id = str(payload.get("botId") or payload.get("bot_id") or "").strip()
    if bot_id not in _live_deployment_bot_ids():
        raise ValueError("entry_binding_target_not_live")
    with _mod.engine.begin() as conn:
        row = upsert_entry_binding(
            channel=str(payload.get("channel") or ""),
            address=payload.get("address"),
            bot_id=bot_id,
            note=str(payload.get("note") or ""),
            enabled=bool(payload.get("enabled", True)),
            conn=conn,
        )
        change_log.record_entry_binding(
            conn,
            tenant_id=_tenant(),
            actor_user_id=_mod._actor_user_id() or "system",
            entry_id=_mod._id("AUD"),
            bot_id=bot_id,
            binding=row,
        )
    return row


def remove_entry_binding(binding_id: str) -> dict[str, Any]:
    from agent_core import change_log
    from agent_core.cards.routing import delete_entry_binding

    _mod = _db()
    with _mod.engine.begin() as conn:
        row = delete_entry_binding(binding_id, conn=conn)
        if row is None:
            raise KeyError(f"entry_binding_not_found: {binding_id}")
        change_log.record_entry_binding(
            conn,
            tenant_id=_mod._tenant(),
            actor_user_id=_mod._actor_user_id() or "system",
            entry_id=_mod._id("AUD"),
            bot_id=str(row["bot_id"]),
            binding=row,
            removed=True,
        )
    return row


def archive_agent_studio_card(bot_id: str) -> dict[str, Any]:
    """Retire a tenant card. Never deletes — the row is referenced by audit.

    ``bots.id`` is a foreign key on interactions, eval_reports, activity_events
    and a2a_tasks. A DELETE would cascade the deployments and NULL the audit
    trail of every call the agent ever handled, so retirement is a timestamp.

    Refused when the card is first-party (re-seeded on boot) or when it is the
    runtime entry point — inbound traffic would resolve to a retired bot.

    A live production deployment is retired here rather than refused. It used to
    be a third guard, which made the whole feature unreachable: publish always
    leaves an active deployment and rollback only swaps which one is active, so
    no card that had ever shipped could be retired. Taking no traffic *is* what
    archiving means, so retiring the deployment is the operation, not a side
    effect. Restore does not redeploy — publish again to bring the card back.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    from agent_core.cards.defaults import FIRST_PARTY_BOT_IDS
    from agent_core.cards.routing import is_entry_card

    bid = (bot_id or "").strip()
    if not bid:
        raise ValueError("bot_id_required")
    if bid in FIRST_PARTY_BOT_IDS:
        raise ValueError("first_party_card_not_archivable")
    if is_entry_card(bid):
        raise ValueError("entry_card_not_archivable")
    with engine.begin() as conn:
        updated = conn.execute(
            text(
                """
                UPDATE bots SET archived_at = now(), updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND archived_at IS NULL
                """
            ),
            {"id": bid, "t": _tenant()},
        ).rowcount
        if updated:
            retired = _one(
                conn.execute(
                    text(
                        """
                        SELECT id FROM bot_deployments
                         WHERE bot_id = :id AND environment = 'production'
                           AND status = 'active'
                         LIMIT 1
                        """
                    ),
                    {"id": bid},
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE bot_deployments
                       SET status = 'retired', updated_at = now()
                     WHERE bot_id = :id AND environment = 'production'
                       AND status = 'active'
                    """
                ),
                {"id": bid},
            )
            from agent_core import change_log

            change_log.record_archive(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=bid,
                retired_deployment_id=(retired or {}).get("id"),
            )
    if not updated:
        raise KeyError(f"agent_card_not_found_or_archived:{bid}")
    return {"ok": True, "botId": bid, "archived": True}


def restore_agent_studio_card(bot_id: str) -> dict[str, Any]:
    """Undo an archive. The card returns exactly as it was left.

    Recorded in the change log for the same reason the archive is: an agent
    reappearing on the roster is a configuration change, and a chain that logs
    only the retirement reads as though the card is still retired.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    bid = (bot_id or "").strip()
    if not bid:
        raise ValueError("bot_id_required")
    with engine.begin() as conn:
        # Read before the UPDATE nulls it — the archived window is the fact the
        # entry exists to carry, and afterwards it is gone.
        archived_at = _one(
            conn.execute(
                text(
                    """
                    SELECT archived_at FROM bots
                     WHERE id = :id AND tenant_id = :t AND archived_at IS NOT NULL
                    """
                ),
                {"id": bid, "t": _tenant()},
            )
        )
        updated = conn.execute(
            text(
                """
                UPDATE bots SET archived_at = NULL, updated_at = now()
                 WHERE id = :id AND tenant_id = :t AND archived_at IS NOT NULL
                """
            ),
            {"id": bid, "t": _tenant()},
        ).rowcount
        if updated:
            from agent_core import change_log

            change_log.record_restore(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=bid,
                archived_at=(archived_at or {}).get("archived_at"),
            )
    if not updated:
        raise KeyError(f"archived_card_not_found:{bid}")
    return {"ok": True, "botId": bid, "archived": False}


def agent_change_log(bot_id: str | None = None, *, limit: int = 50) -> dict[str, Any]:
    """Publish / rollback / archive history, plus the chain-integrity verdict.

    ``chain`` is reported alongside the entries rather than on a separate call:
    a change log whose integrity you have to remember to check separately is one
    nobody checks.
    """
    _mod = _db()
    engine = _mod.engine
    _tenant = _mod._tenant
    from agent_core import change_log

    with engine.connect() as conn:
        return {
            "entries": change_log.read_entries(
                conn, tenant_id=_tenant(), bot_id=bot_id, limit=limit
            ),
            "total": change_log.count_entries(conn, tenant_id=_tenant(), bot_id=bot_id),
            "chain": change_log.verify_chain(conn, tenant_id=_tenant()),
        }


def compile_agent_studio_card(
    bot_id: str,
    *,
    prompt_version_id: str | None = None,
    card_raw: dict[str, Any] | None = None,
    flow: Any = None,
    traffic_pct: int | None = None,
    auto_rollback: list[str] | None = None,
    voice: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _mod = _db()
    list_bot_ids = _mod.list_bot_ids
    _latest_twin_gate_report = _mod._latest_twin_gate_report
    get_latest_eval_report = _mod.get_latest_eval_report
    from agent_core.cards.compile import compile_card
    from agent_core.tools.catalog import CATALOG

    published, draft = _studio_card_versions(bot_id)
    explicit = get_prompt_version(prompt_version_id) if prompt_version_id else None
    if prompt_version_id and explicit is None:
        raise KeyError(f"prompt_version_not_found: {prompt_version_id}")
    if explicit and explicit.get("botId") != bot_id:
        raise ValueError("prompt_version_bot_mismatch")
    card = card_raw if isinstance(card_raw, dict) and card_raw else None
    if card is None:
        # Compile preview must gate what publish will actually ship, and publish
        # ships the draft. Falling straight to published reported a green compile
        # for a draft whose card had not been checked.
        for row in (explicit, draft, published):
            candidate = (row or {}).get("agentCard")
            if isinstance(candidate, dict) and candidate:
                card = candidate
                break
    # No card on any version is what the compiler is told: G0 reports the
    # legacy mouth. It used to be handed the first-party constant instead,
    # which gated a card nobody had stored.
    card = card or {}
    graph = flow if flow is not None else ((explicit or draft or published or {}).get("flow") or {})
    # Same precedence the card itself follows: preview what publish will ship,
    # which is the draft. The caller may pass the editor's unsaved voice and
    # persona instead — without that the preview gates the last autosave, and
    # G15 is exactly the gate an operator would trip between two of them.
    mouth = explicit or draft or published or {}
    voice_short, voice_locale, card_locales = voice_locale_facts(
        voice if voice is not None else mouth.get("voice"),
        persona if persona is not None else mouth.get("persona"),
    )
    voice_provider, bound_tts = voice_provider_facts(voice_short, voice_locale, bot_id)
    attached = None
    try:
        from agent_core.cards.schema import is_authored, parse_card
        from agent_core.skills.persist import packs_for_skill_refs

        raw = card if isinstance(card, dict) else {}
        if is_authored(raw):
            attached = []
            parsed = parse_card(raw)
            attached = packs_for_skill_refs(parsed.skills)
    except Exception:
        pass
    version_id = mouth.get("id")
    # The identity of what is about to ship: a report filed against the same
    # content on any row counts, one filed against different content on this
    # row does not.
    from agent_core.eval.provenance import content_key as _content_key

    candidate_key = _content_key(
        card=card,
        flow=graph,
        prompt=mouth.get("prompt"),
        persona=persona if persona is not None else mouth.get("persona"),
        guardrails=mouth.get("guardrails"),
        voice=voice if voice is not None else mouth.get("voice"),
        tuning=mouth.get("tuning"),
        skill_packs=attached or [],
    )

    def _report(kind: str) -> dict[str, Any] | None:
        by_content = get_latest_eval_report(bot_id=bot_id, kind=kind, content_key=candidate_key)
        if by_content is not None:
            if by_content.get("prompt_version_id") != version_id:
                by_content = {**by_content, "cached": True}
            return by_content
        return get_latest_eval_report(bot_id=bot_id, kind=kind, prompt_version_id=version_id)

    report = compile_card(
        bot_id=bot_id,
        card_raw=card,
        flow=graph,
        catalog_names=set(CATALOG.specs),
        known_bot_ids=list_bot_ids(),
        eval_report=_report("regression"),
        redteam_report=_report("redteam"),
        twin_report=_latest_twin_gate_report(),
        outbound_report=_report("outbound"),
        content_key=candidate_key,
        attached_skills=attached,
        # Without these the preview read the card's stored experiment while
        # publish used the Ship tab's, so G12 reported "full ship" green and the
        # very next call 422'd on "canary split requires auto_rollback".
        traffic_pct=traffic_pct,
        auto_rollback=auto_rollback,
        voice_short_name=voice_short,
        voice_locale=voice_locale,
        card_locales=card_locales,
        voice_provider=voice_provider,
        bound_tts_providers=bound_tts,
        prompt=mouth.get("prompt"),
        prompt_guardrails=mouth.get("guardrails") if isinstance(mouth.get("guardrails"), dict) else {},
    )
    from agent_core.fleet.compile import compile_bundle, fleet_gates

    # Warn-level, and appended rather than folded into `compile_card` because
    # they need the merged graph, which only exists once the members are known.
    report.gates.extend(
        fleet_gates(
            primary_bot_id=bot_id,
            card_raw=card if isinstance(card, dict) else {},
            flow=graph if isinstance(graph, dict) else {},
            members=_fleet_members(card),
        )
    )

    bundle = compile_bundle(
        report=report,
        prompt=str(mouth.get("prompt") or ""),
        persona=mouth.get("persona") if isinstance(mouth.get("persona"), dict) else {},
        guardrails=mouth.get("guardrails") if isinstance(mouth.get("guardrails"), dict) else {},
        flow=graph if isinstance(graph, dict) else {},
        prompt_version_id=version_id,
        attached_skills=attached,
        source_ids={"bot_id": bot_id, "prompt_version_id": str(version_id or "")},
        members=_fleet_members(card),
    )
    return report.model_copy(
        update={"bundle": bundle.model_dump(mode="json"), "doors_merging": doors_merging(bot_id)}
    ).model_dump()


def doors_merging(bot_id: str) -> list[str]:
    """Published cards whose compiled bundle contains ``bot_id``'s subgraph.

    Read from `compiled.entry_by_specialist` -- what was actually merged -- and
    not from the handoff graph. The graph cannot answer this: `insurance-v1` and
    `collections-clone-9ff4b6` both hand off to cards the other also reaches, so
    "the owning door" is not a single value, and a function returning the first
    match would be picking by sort order.

    Publishing a member has to refresh every bundle that merged it, or the
    door keeps serving that member's old flow; this is how the publish path
    finds them.
    """
    bid = (bot_id or "").strip()
    if not bid:
        return []
    _mod = _db()
    with _mod.engine.connect() as conn:
        if not _column_exists(conn, "prompt_versions", "compiled"):
            return []
        rows = _mod._rows(
            conn.execute(
                text(
                    """
                    SELECT bot_id
                      FROM prompt_versions
                     WHERE status = 'published' AND tenant_id = :t
                       AND compiled -> 'entry_by_specialist' ? :b
                    """
                ),
                {"t": _mod._tenant(), "b": bid},
            )
        )
    return sorted(str(r["bot_id"]) for r in rows if str(r["bot_id"]) != bid)


def recompile_published_bundle(bot_id: str) -> dict[str, Any]:
    """Fill in `prompt_versions.compiled` for a card that is already live.

    `compiled` is NULL on every published row, because the column landed after
    they were published and only `publish_prompt_version` writes it. While it is
    NULL, `deployment._dual_compute_parity` returns at its first guard: no parity
    is logged, and `fleet_enabled()` is never even reached. So the compiled
    artefact cannot be trusted before it is switched on, because nothing has
    ever compared it to the live path.

    **This is not a republish, and the difference matters.**
    `publish_prompt_version` archives the live row, inserts a new
    `bot_deployments` row, re-snapshots frozen connector tools, re-applies the
    tuning overlay and rewrites the card through `model_dump`. Running it on an
    unchanged card is therefore a real production swap of the deployment every
    inbound call resolves, and it would rewrite the card in the same motion.
    This writes two columns and changes no row's identity: `compiled` on the
    published version, and `bundle_hash` on the deployment that is already
    active. Reversal is `UPDATE prompt_versions SET compiled = NULL`.

    Compile members before the door: `_fleet_members` reads each member's
    *published* row, so a door compiled first would merge whatever those rows
    held at the time.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _jsonb = _mod._jsonb
    _tenant = _mod._tenant

    with engine.connect() as conn:
        live = _one(
            conn.execute(
                text(
                    "SELECT id FROM prompt_versions "
                    " WHERE bot_id = :b AND status = 'published' AND tenant_id = :t "
                    " LIMIT 1"
                ),
                {"b": bot_id, "t": _tenant()},
            )
        )
    if live is None:
        raise KeyError(f"no_published_version: {bot_id}")

    # Named explicitly. `compile_agent_studio_card(bot_id)` with no version
    # resolves the *draft* when there is one -- correct for a preview, wrong
    # here: it would stamp the column the runtime reads with an artefact
    # compiled from a card nobody has published.
    report = compile_agent_studio_card(bot_id, prompt_version_id=str(live["id"]))
    bundle = report.get("bundle") or {}
    bundle_hash = str(bundle.get("bundle_hash") or "")
    version_id = str(bundle.get("prompt_version_id") or "")
    if not bundle_hash or not version_id:
        raise ValueError(f"no compiled bundle for {bot_id}")

    with engine.begin() as conn:
        if not _column_exists(conn, "prompt_versions", "compiled"):
            raise RuntimeError("prompt_versions.compiled does not exist")
        row = _one(
            conn.execute(
                text(
                    "SELECT id, status FROM prompt_versions "
                    "WHERE id = :id AND tenant_id = :t"
                ),
                {"id": version_id, "t": _tenant()},
            )
        )
        if row is None:
            raise KeyError(f"prompt_version_not_found: {version_id}")
        if row["status"] != "published":
            # Only the live row. A draft's bundle is what the preview is for,
            # and stamping one here would put an artefact nothing serves into
            # the column the runtime reads.
            raise ValueError(f"prompt_version_not_published: {version_id}")

        conn.execute(
            text(
                "UPDATE prompt_versions SET compiled = CAST(:c AS jsonb), "
                "updated_at = now() WHERE id = :id AND tenant_id = :t"
            ),
            {"c": _jsonb(bundle), "id": version_id, "t": _tenant()},
        )
        deployments = 0
        if _column_exists(conn, "bot_deployments", "bundle_hash"):
            # No tenant predicate here, and it is not an omission:
            # `bot_deployments` has no `tenant_id` column -- it reaches its
            # tenant through `bot_id`, which is how `rls.plan` derives its
            # policy at depth 1. `version_id` was matched against a
            # tenant-scoped `prompt_versions` row three statements above, so
            # the row this updates is already known to be ours.
            deployments = conn.execute(
                text(
                    "UPDATE bot_deployments SET bundle_hash = :h "
                    " WHERE prompt_version_id = :pv AND status = 'active'"
                ),
                {"h": bundle_hash, "pv": version_id},
            ).rowcount

    return {
        "botId": bot_id,
        "promptVersionId": version_id,
        "bundleHash": bundle_hash,
        "deploymentsStamped": int(deployments or 0),
    }


def _fleet_members(card_raw: Any) -> list[dict[str, Any]]:
    """The published card and flow of every agent this one hands off to.

    The fleet is already declared — it is the card's handoff allowlist — so an
    author never types a namespace and there is no second place for the roster
    to drift from. A target with no published version is skipped rather than
    guessed at; it simply contributes no subgraph, and the hop into it stays a
    ledger row.
    """
    from agent_core.cards import routing

    out: list[dict[str, Any]] = []
    for target in sorted(set(routing.handoff_targets(card_raw))):
        try:
            published = get_published_prompt_version(target)
        except Exception:
            logger.debug("fleet member lookup failed for %s", target, exc_info=True)
            continue
        if not published:
            continue
        out.append(
            {
                "bot_id": target,
                "card": published.get("agentCard") or {},
                "flow": published.get("flow") if isinstance(published.get("flow"), dict) else {},
            }
        )
    return out


def get_effective_contract(bot_id: str) -> dict[str, Any]:
    """Published artefact if persisted, else a dry-run compile of the draft."""
    published = get_published_prompt_version(bot_id)
    stored = (published or {}).get("compiled") if isinstance(published, dict) else None
    if isinstance(stored, dict) and stored.get("bundle_hash"):
        return {
            "source": "published",
            "botId": bot_id,
            "promptVersionId": published.get("id") if published else None,
            "compiled": stored,
        }
    dumped = compile_agent_studio_card(bot_id)
    compiled = dumped.get("bundle") if isinstance(dumped.get("bundle"), dict) else {}
    if not compiled.get("bundle_hash"):
        raise KeyError("effective_contract_unavailable")
    return {
        "source": "preview",
        "botId": bot_id,
        "promptVersionId": compiled.get("prompt_version_id"),
        "compiled": compiled,
        "gates": dumped.get("gates") or [],
    }


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


def list_bot_deployments(
    *,
    environment: str | None = None,
    status: str | None = None,
    bot_id: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Runtime deployments — authoritative for what runs.

    Paged: this table gains a row on every publish, so it grows with release
    cadence rather than staying at the handful the demo has.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _as_dict = _mod._as_dict
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    clauses = ["1=1"]
    params: dict[str, Any] = {}
    if environment in ("sandbox", "production"):
        clauses.append("d.environment = :environment")
        params["environment"] = environment
    if status in ("active", "rolled_back", "retired"):
        clauses.append("d.status = :status")
        params["status"] = status
    if bot_id:
        clauses.append("d.bot_id = :bot_id")
        params["bot_id"] = bot_id
    where = " AND ".join(clauses)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                      d.tts_voice_id, d.environment, d.status,
                      d.published_at, d.rollback_deployment_id, d.voice_config,
                      d.tuning,
                      COALESCE(u.name, d.published_by_user_id) AS published_by
                    FROM bot_deployments d
                    LEFT JOIN users u ON u.id = d.published_by_user_id
                    WHERE {where}
                    ORDER BY d.published_at DESC NULLS LAST, d.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": clamp_list_limit(limit), "offset": clamp_offset(offset)},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            published = r.get("published_at")
            out.append(
                {
                    "id": r["id"],
                    "botId": r["bot_id"],
                    "promptVersionId": r["prompt_version_id"],
                    "kbSnapshotId": r.get("kb_snapshot_id"),
                    "ttsVoiceId": r.get("tts_voice_id"),
                    "environment": r["environment"],
                    "status": r["status"],
                    "publishedBy": r.get("published_by"),
                    "publishedAt": (
                        published
                        if isinstance(published, str)
                        else (published.isoformat() if published else None)
                    ),
                    "rollbackDeploymentId": r.get("rollback_deployment_id"),
                    "voiceConfig": _as_dict(r.get("voice_config")),
                    "tuning": _as_dict(r.get("tuning")),
                }
            )
        return out


# ---------------------------------------------------------------------------
# Persona & Prompt Studio — writes (PS-2)
# Live-config invariant: active prod deployment.prompt_version_id
# must equal the single prompt_versions row with status='published'.
# ---------------------------------------------------------------------------

DEFAULT_BOT_ID = os.getenv("BOT_ID", "kaia-v2-4")

def _active_deployment_sql(conn: Any) -> str:
    frozen = _frozen_tools_select(conn)
    bundle = _bundle_hash_select(conn)
    return f"""
    SELECT
      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
      d.tts_voice_id, d.environment, d.status,
      d.published_at, d.rollback_deployment_id, d.voice_config, d.tuning,
      d.traffic_pct, d.shadow, d.eval_report_id, {frozen}, {bundle},
      COALESCE(u.name, d.published_by_user_id) AS published_by
    FROM bot_deployments d
    LEFT JOIN users u ON u.id = d.published_by_user_id
    WHERE d.bot_id = :bot_id
      AND d.environment = :environment
      AND d.status = 'active'
    ORDER BY d.published_at DESC NULLS LAST, d.id DESC
    LIMIT 1
"""


def _fetch_active_deployment_row(
    conn: Any,
    *,
    bot_id: str,
    environment: str,
) -> dict[str, Any] | None:
    """Raw active deployment row inside an open connection/transaction."""
    _mod = _db()
    _one = _mod._one
    return _one(
        conn.execute(
            text(_active_deployment_sql(conn)),
            {"bot_id": bot_id, "environment": environment},
        )
    )


def get_active_deployment(
    bot_id: str | None = None,
    environment: str = "production",
) -> dict[str, Any] | None:
    """Authoritative runtime loader. One active row per (bot, env) expected.

    Multi-bot: filtered by bot_id. One published prompt per bot.
    """
    _mod = _db()
    engine = _mod.engine
    bid = (bot_id or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    env = environment if environment in ("sandbox", "production") else "production"
    with engine.connect() as conn:
        row = _fetch_active_deployment_row(conn, bot_id=bid, environment=env)
        return _map_bot_deployment_row(row) if row else None


def get_deployment(deployment_id: str) -> dict[str, Any] | None:
    """Load a deployment by id, including retired baselines used by canary split."""
    _mod = _db()
    engine = _mod.engine
    with engine.connect() as conn:
        return _fetch_bot_deployment(conn, deployment_id)


def _latest_kb_snapshot_id(conn: Any) -> str | None:
    """Newest snapshot by created_at — bookkeeping only (retrieve stays live)."""
    _mod = _db()
    _one = _mod._one
    row = _one(
        conn.execute(
            text(
                """
                SELECT id FROM kb_snapshots
                ORDER BY created_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            )
        )
    )
    return row["id"] if row else None

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


def _map_bot_deployment_row(r: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _as_dict = _mod._as_dict
    from agent_core.tuning import default_tuning, normalize_tuning

    published = r.get("published_at")
    raw_tuning = _as_dict(r.get("tuning"))
    tuning = normalize_tuning(raw_tuning) if raw_tuning else default_tuning()
    return {
        "id": r["id"],
        "botId": r["bot_id"],
        "promptVersionId": r["prompt_version_id"],
        "kbSnapshotId": r.get("kb_snapshot_id"),
        "ttsVoiceId": r.get("tts_voice_id"),
        "environment": r["environment"],
        "status": r["status"],
        "publishedBy": r.get("published_by"),
        "publishedAt": (
            published if isinstance(published, str) else (published.isoformat() if published else None)
        ),
        "rollbackDeploymentId": r.get("rollback_deployment_id"),
        "voiceConfig": _as_dict(r.get("voice_config")),
        "tuning": tuning,
        "trafficPct": int(r.get("traffic_pct") or 100),
        "shadow": bool(r.get("shadow")),
        "evalReportId": r.get("eval_report_id"),
        "frozenTools": (
            list(r["frozen_tools"])
            if isinstance(r.get("frozen_tools"), list)
            else (r.get("frozen_tools") if r.get("frozen_tools") is not None else None)
        ),
        "bundleHash": r.get("bundle_hash"),
    }


def _fetch_bot_deployment(conn: Any, deployment_id: str) -> dict[str, Any] | None:
    _mod = _db()
    _one = _mod._one
    frozen = _frozen_tools_select(conn)
    bundle = _bundle_hash_select(conn)
    r = _one(
        conn.execute(
            text(
                f"""
                SELECT
                  d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                  d.tts_voice_id, d.environment, d.status,
                  d.published_at, d.rollback_deployment_id, d.voice_config, d.tuning,
                  d.traffic_pct, d.shadow, d.eval_report_id, {frozen}, {bundle},
                  COALESCE(u.name, d.published_by_user_id) AS published_by
                FROM bot_deployments d
                LEFT JOIN users u ON u.id = d.published_by_user_id
                WHERE d.id = :id
                """
            ),
            {"id": deployment_id},
        )
    )
    return _map_bot_deployment_row(r) if r else None


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


def _change_log_components(
    conn: Any, version_id: str, target: dict[str, Any], summary: str
) -> dict[str, Any]:
    """The version as the change log hashes it.

    Read back rather than taken from ``target``: the publishing transaction
    rewrites ``agent_card`` (the shipped experiment) and ``tuning`` before this
    point, so the in-memory copy is stale and the digest would describe a
    version that was never live.
    """
    _mod = _db()
    _one = _mod._one
    row = _one(
        conn.execute(
            text(
                """
                SELECT id, label, prompt, persona, voice, guardrails, flow, agent_card
                  FROM prompt_versions WHERE id = :id
                """
            ),
            {"id": version_id},
        )
    ) or {}
    return {**dict(row), "label": row.get("label") or target.get("label"), "summary": summary}


def publish_prompt_version(
    version_id: str,
    summary: str = "",
    *,
    kb_snapshot_id: str | None = None,
    tuning: dict[str, Any] | None = None,
    traffic_pct: int | None = None,
    shadow: bool = False,
    auto_rollback: list[str] | None = None,
) -> dict[str, Any]:
    """Archive current published → promote draft → swap active prod deployment.

    kb_snapshot_id: explicit Sandbox pin wins; else prior active snap, else latest.
    tuning: explicit AgentTuning from Sandbox Promote; else prior deployment tuning.
    """
    _mod = _db()
    engine = _mod.engine

    with engine.begin() as conn:
        frozen = _freeze(
            conn, version_id, traffic_pct=traffic_pct, auto_rollback=auto_rollback, shadow=shadow
        )
        compiled = _compile(conn, frozen)
        deployed = _deploy(
            conn, frozen, compiled, kb_snapshot_id=kb_snapshot_id, tuning=tuning, summary=summary
        )
        _record(conn, frozen, compiled, deployed)
        row = _fetch_prompt_version(conn, version_id)
    bot_id = frozen.bot_id
    assert row is not None

    # A member's new flow is not live until the bundle that merged it is rebuilt
    # -- the door serves `compiled.fleet_flow`, so without this it keeps speaking
    # the member's previous graph. Outside the transaction above because
    # `recompile_published_bundle` opens its own, and best-effort because a
    # failure here must not roll back a publish that already succeeded: a stale
    # bundle is what the parity logger reports, a half-published card is not.
    for door in doors_merging(bot_id):
        try:
            recompile_published_bundle(door)
        except Exception:
            logger.exception("could not refresh the fleet bundle owned by %s", door)
    return row


@dataclasses.dataclass(frozen=True)
class _Frozen:
    """The draft as ``_freeze`` read and locked it: every value the later
    publish phases take from the row and its bot rather than from the caller."""

    version_id: str
    target: dict[str, Any]
    bot_id: str
    known_bots: set[str]
    card_raw: dict[str, Any]
    attached: list[Any] | None
    pct: int
    triggers: list[str]
    shadow: bool
    cert_ok: bool | None
    uid: str | None
    has_publish: bool
    voice_short: str
    voice_locale: str | None
    card_locales: list[str]
    voice_provider: Any
    bound_tts: Any
    candidate_key: str


@dataclasses.dataclass(frozen=True)
class _Compiled:
    report: Any
    shipped_card: dict[str, Any]
    compiled_dump: dict[str, Any]
    bundle_hash: str


@dataclasses.dataclass(frozen=True)
class _Deployed:
    dep_id: str
    note: str
    previously_published: dict[str, Any] | None


def _freeze(
    conn: Any,
    version_id: str,
    *,
    traffic_pct: int | None,
    auto_rollback: list[str] | None,
    shadow: bool,
) -> _Frozen:
    """Load and lock the draft; refuse a non-draft or an archived bot; read
    the facts the compile needs (known bots, attached skills, experiment,
    actor, mouth columns, content key)."""
    _mod = _db()
    _rows = _mod._rows
    _one = _mod._one
    _tenant = _mod._tenant
    _actor_user_id = _mod._actor_user_id

    target = _one(
        conn.execute(
            text(
                """
                SELECT id, status, voice, persona, label, tuning, flow, bot_id, agent_card,
                       prompt, guardrails
                FROM prompt_versions WHERE id = :id AND tenant_id = :t
                """
            ),
            {"id": version_id, "t": _tenant()},
        )
    )
    if not target:
        raise KeyError(f"prompt_version_not_found: {version_id}")
    if target["status"] != "draft":
        raise ValueError("prompt_version_not_draft")

    bot_id = str(target.get("bot_id") or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    archived = _one(
        conn.execute(
            text("SELECT archived_at FROM bots WHERE id = :id"),
            {"id": bot_id},
        )
    )
    if archived and archived.get("archived_at") is not None:
        raise ValueError("bot_archived")
    # Serialize publish/rollback for this bot+env (single-active invariant).
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"{bot_id}:production"},
    )

    # Tenant-scoped: this is G5's allowlist of legal handoff targets.
    known_bots = {
        r["id"]
        for r in _rows(
            conn.execute(
                text("SELECT id FROM bots WHERE tenant_id = :t"),
                {"t": _tenant()},
            )
        )
    }
    card_raw = target.get("agent_card") if isinstance(target.get("agent_card"), dict) else {}
    attached = None
    try:
        from agent_core.cards.schema import is_authored, parse_card
        from agent_core.skills.persist import packs_for_skill_refs

        if is_authored(card_raw):
            attached = []
            parsed = parse_card(card_raw)
            attached = packs_for_skill_refs(parsed.skills)
    except Exception:
        pass
    exp = card_raw.get("experiment") if isinstance(card_raw.get("experiment"), dict) else {}
    pct = traffic_pct if traffic_pct is not None else int(exp.get("traffic_pct") or 100)
    triggers = auto_rollback if auto_rollback is not None else list(exp.get("auto_rollback") or [])
    a2a_raw = card_raw.get("a2a") if isinstance(card_raw.get("a2a"), dict) else {}
    cert_ok = None
    if a2a_raw.get("expose"):
        try:
            from agent_core.a2a import partner_has_cert

            cert_ok = partner_has_cert(bot_id)
        except Exception:
            cert_ok = False
    import authz as _authz

    uid = _actor_user_id()
    has_publish = bool(uid and _authz.has_permission(uid, _authz.AGENT_PUBLISH))
    voice_short, voice_locale, card_locales = voice_locale_facts(
        target.get("voice"), target.get("persona")
    )
    voice_provider, bound_tts = voice_provider_facts(voice_short, voice_locale, bot_id)
    # Same identity the preview and the suite run used -- computed from the
    # mapped row (normalised voice/tuning/flow), not the raw columns, or
    # the three keys would not agree on the same content.
    from agent_core.eval.provenance import content_key_for_version

    candidate_key = content_key_for_version(get_prompt_version(version_id) or {})
    return _Frozen(
        version_id=version_id,
        target=target,
        bot_id=bot_id,
        known_bots=known_bots,
        card_raw=card_raw,
        attached=attached,
        pct=pct,
        triggers=triggers,
        shadow=bool(shadow),
        cert_ok=cert_ok,
        uid=uid,
        has_publish=has_publish,
        voice_short=voice_short,
        voice_locale=voice_locale,
        card_locales=card_locales,
        voice_provider=voice_provider,
        bound_tts=bound_tts,
        candidate_key=candidate_key,
    )


def _compile(conn: Any, f: _Frozen) -> _Compiled:
    """compile_card + the fleet gates + assert_publishable; fold the shipped
    experiment back into the card; compile_bundle -> bundle hash."""
    _mod = _db()
    _jsonb = _mod._jsonb
    _latest_twin_gate_report = _mod._latest_twin_gate_report
    get_latest_eval_report = _mod.get_latest_eval_report
    version_id, target, bot_id, card_raw = f.version_id, f.target, f.bot_id, f.card_raw
    known_bots, attached, pct, triggers, shadow = f.known_bots, f.attached, f.pct, f.triggers, f.shadow
    candidate_key, cert_ok, has_publish = f.candidate_key, f.cert_ok, f.has_publish
    voice_short, voice_locale, card_locales = f.voice_short, f.voice_locale, f.card_locales
    voice_provider, bound_tts = f.voice_provider, f.bound_tts

    # Compiler: flow + Agent Card gates. Empty card is legacy (G0 skipped).
    from agent_core.cards.compile import compile_card, assert_publishable as _assert_card
    from agent_core.tools.catalog import CATALOG as _CATALOG

    def _report(kind: str) -> dict[str, Any] | None:
        by_content = get_latest_eval_report(bot_id=bot_id, kind=kind, content_key=candidate_key)
        if by_content is not None:
            if by_content.get("prompt_version_id") != version_id:
                by_content = {**by_content, "cached": True}
            return by_content
        return get_latest_eval_report(bot_id=bot_id, kind=kind, prompt_version_id=version_id)

    report = compile_card(
        bot_id=bot_id,
        card_raw=card_raw,
        flow=target.get("flow"),
        catalog_names=set(_CATALOG.specs),
        known_bot_ids=known_bots,
        eval_report=_report("regression"),
        redteam_report=_report("redteam"),
        twin_report=_latest_twin_gate_report(),
        outbound_report=_report("outbound"),
        content_key=candidate_key,
        attached_skills=attached,
        traffic_pct=pct,
        auto_rollback=triggers,
        has_publish=has_publish,
        a2a_cert_ok=cert_ok,
        voice_short_name=voice_short,
        voice_locale=voice_locale,
        card_locales=card_locales,
        voice_provider=voice_provider,
        bound_tts_providers=bound_tts,
        shadow=bool(shadow),
        prompt=target.get("prompt"),
        prompt_guardrails=(
            target.get("guardrails") if isinstance(target.get("guardrails"), dict) else {}
        ),
    )
    # The fleet gates run here, before the assert, rather than alongside
    # `compile_bundle` further down. They are warn-level today so this
    # changes no publish outcome -- which is the point of wiring them now:
    # when G-F2/G-F6/G-F15 are promoted to blocking, the promotion is a
    # status change in one function and not new plumbing on the publish
    # path.
    from agent_core.fleet.compile import fleet_gates as _fleet_gates

    report.gates.extend(
        _fleet_gates(
            primary_bot_id=bot_id,
            card_raw=card_raw if isinstance(card_raw, dict) else {},
            flow=target.get("flow") if isinstance(target.get("flow"), dict) else {},
            members=_fleet_members(card_raw),
        )
    )
    _assert_card(report)
    # Fold the shipped experiment back into the card. The deployment row
    # recorded the split, but the card kept whatever it was authored with —
    # so the Studio's Ship tab, which reads the card, showed 100% after a
    # 40% canary and would silently re-ship at full traffic on the next
    # publish. Only valid triggers are stored: CardExperiment types them as
    # a Literal, so an unknown one would make the card unparseable.
    shipped_card = card_raw
    try:
        from agent_core.cards.compile import _ROLLBACK_TRIGGERS
        from agent_core.cards.schema import is_authored as _is_authored

        if _is_authored(card_raw):
            shipped_exp = {
                "traffic_pct": int(pct),
                "shadow": bool(shadow),
                "auto_rollback": [t for t in triggers if t in _ROLLBACK_TRIGGERS],
            }
            if (card_raw.get("experiment") or {}) != shipped_exp:
                shipped_card = {**card_raw, "experiment": shipped_exp}
                conn.execute(
                    text(
                        """
                        UPDATE prompt_versions
                        SET agent_card = CAST(:card AS jsonb), updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": version_id, "card": _jsonb(shipped_card)},
                )
    except Exception:
        logger.exception("could not persist the shipped experiment onto the card")
    # Compile the persisted artifact from the exact card that is about to
    # become live. Ship controls can rewrite ``experiment`` above; hashing
    # the pre-rewrite card would make the deployment point at a contract
    # that production never ran.
    from agent_core.cards.compile import CompileReport
    from agent_core.fleet.compile import compile_bundle

    shipped_report = CompileReport.model_validate(
        {**report.model_dump(mode="json"), "card": shipped_card}
    )
    compiled_bundle = compile_bundle(
        report=shipped_report,
        prompt=str(target.get("prompt") or ""),
        persona=target.get("persona") if isinstance(target.get("persona"), dict) else {},
        guardrails=target.get("guardrails") if isinstance(target.get("guardrails"), dict) else {},
        flow=target.get("flow") if isinstance(target.get("flow"), dict) else {},
        prompt_version_id=version_id,
        attached_skills=attached,
        source_ids={"bot_id": bot_id, "prompt_version_id": version_id},
        members=_fleet_members(shipped_card),
    )
    compiled_dump = compiled_bundle.model_dump(mode="json")
    bundle_hash = compiled_bundle.bundle_hash
    try:
        from agent_core.skills.persist import sync_attachments_from_card

        sync_attachments_from_card(version_id, card_raw)
    except Exception:
        logger.exception("skill attachment sync failed")
    return _Compiled(
        report=report,
        shipped_card=shipped_card,
        compiled_dump=compiled_dump,
        bundle_hash=bundle_hash,
    )


def _deploy(
    conn: Any,
    f: _Frozen,
    c: _Compiled,
    *,
    kb_snapshot_id: str | None,
    tuning: dict[str, Any] | None,
    summary: str,
) -> _Deployed:
    """Resolve voice, tuning and KB snapshot against the prior production
    deployment; archive the live version, promote the draft, swap the
    ``bot_deployments`` row."""
    _mod = _db()
    _one = _mod._one
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    _jsonb = _mod._jsonb
    _as_dict = _mod._as_dict
    from sqlalchemy.exc import IntegrityError
    from agent_core.tuning import apply_voice_config_overlay, default_tuning, normalize_tuning

    version_id, target, bot_id, card_raw = f.version_id, f.target, f.bot_id, f.card_raw
    pct, triggers, shadow = f.pct, f.triggers, f.shadow
    shipped_card, compiled_dump, bundle_hash = c.shipped_card, c.compiled_dump, c.bundle_hash

    note = (summary or "").strip()
    voice = _prompt_voice(target.get("voice"))
    # Column stores Azure ShortName (no FK to legacy tts_voices aliases).
    if tuning is not None:
        early = normalize_tuning(tuning)
        tts_voice_id = str((early.get("tts") or {}).get("voice") or "").strip() or None
    else:
        tts_voice_id = None
    if not tts_voice_id:
        tts_voice_id = resolve_prompt_azure_voice(voice) or _DEFAULT_AZURE_TTS_VOICE

    prior = _fetch_active_deployment_row(
        conn, bot_id=bot_id, environment="production"
    )
    resolved_snap = kb_snapshot_id
    if not resolved_snap:
        resolved_snap = prior.get("kb_snapshot_id") if prior else None
    if not resolved_snap:
        resolved_snap = _latest_kb_snapshot_id(conn)
    if resolved_snap and not _one(
        conn.execute(text("SELECT 1 FROM kb_snapshots WHERE id = :id"), {"id": resolved_snap})
    ):
        raise ValueError(f"kb_snapshot_not_found: {resolved_snap}")

    voice_config = _as_dict(prior.get("voice_config")) if prior else {}
    # Keep voice_config.azureVoiceName aligned with the authoritative ShortName.
    voice_config = {
        **voice_config,
        **{
            k: voice.get(k)
            for k in ("speed", "pitch", "warmth", "pauseMs", "sampleText", "style", "params")
            if k in voice
        },
        "azureVoiceName": tts_voice_id,
        "voiceId": tts_voice_id,
    }
    if tuning is not None:
        # Sandbox Promote — Tuning Studio payload is authoritative.
        resolved_tuning = normalize_tuning(tuning)
    else:
        prior_tuning = _as_dict(prior.get("tuning")) if prior else {}
        target_tuning = _as_dict(target.get("tuning"))
        seed = target_tuning or prior_tuning
        resolved_tuning = normalize_tuning(seed) if seed else default_tuning()
        # Prompt Studio publish: fold voice sliders into AgentTuning.tts once
        # so runtime never needs the warmth/speed/pitch overlay.
        resolved_tuning = apply_voice_config_overlay(
            resolved_tuning,
            voice_name=tts_voice_id,
            speed=float(voice.get("speed", 1.0)),
            pitch=int(voice.get("pitch", 0)),
            warmth=int(voice.get("warmth", 60)),
            params=voice.get("params"),
            style=voice.get("style") or None,
        )

    conn.execute(
        text(
            """
            UPDATE prompt_versions
            SET tuning = CAST(:tuning AS jsonb), updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": version_id, "tuning": _jsonb(resolved_tuning)},
    )

    # Captured while it is still the live row — the change log diffs the
    # incoming version against the one it replaces, and the next statement
    # archives it.
    previously_published = _one(
        conn.execute(
            text(
                """
                SELECT id, label, prompt, persona, voice, guardrails, flow, agent_card
                  FROM prompt_versions
                 WHERE bot_id = :bot_id AND status = 'published'
                 LIMIT 1
                """
            ),
            {"bot_id": bot_id},
        )
    )

    try:
        conn.execute(
            text(
                """
                UPDATE prompt_versions
                SET status = 'archived', updated_at = now()
                WHERE status = 'published' AND bot_id = :bot_id
                """
            ),
            {"bot_id": bot_id},
        )
        compiled_sql = ""
        compiled_params: dict[str, Any] = {"id": version_id, "summary": note}
        if _column_exists(conn, "prompt_versions", "compiled"):
            compiled_sql = ", compiled = CAST(:compiled AS jsonb)"
            compiled_params["compiled"] = _jsonb(compiled_dump)
        conn.execute(
            text(
                f"""
                UPDATE prompt_versions
                SET status = 'published',
                    summary = CASE WHEN :summary = '' THEN summary ELSE :summary END,
                    updated_at = now()
                    {compiled_sql}
                WHERE id = :id AND status = 'draft'
                """
            ),
            compiled_params,
        )
        # Force unique-index check before we leave the transaction half-done.
        promoted = _one(
            conn.execute(
                text("SELECT id, status FROM prompt_versions WHERE id = :id"),
                {"id": version_id},
            )
        )
        if not promoted or promoted["status"] != "published":
            raise ValueError("publish_failed")

        if prior:
            conn.execute(
                text(
                    """
                    UPDATE bot_deployments
                    SET status = 'retired', updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": prior["id"]},
            )

        dep_id = _id("DEP")
        frozen_names: list[str] = []
        try:
            from agent_core.connectors.persist import bound_tool_names
            from agent_core.cards.schema import is_authored as _authored_card, parse_card as _parse_card

            snap_card = shipped_card if isinstance(shipped_card, dict) else card_raw
            if _authored_card(snap_card):
                frozen_names = sorted(
                    bound_tool_names([c.model_dump() for c in _parse_card(snap_card).connectors])
                )
        except Exception:
            logger.exception("could not snapshot connector tools for deployment")
            frozen_names = []
        frozen_sql = ""
        frozen_val = ""
        params = {
            "id": dep_id,
            "bot_id": bot_id,
            "prompt_version_id": version_id,
            "kb_snapshot_id": resolved_snap,
            "tts_voice_id": tts_voice_id,
            "actor": _actor_user_id(),
            "rollback_id": prior["id"] if prior else None,
            "voice_config": _jsonb(voice_config),
            "tuning": _jsonb(resolved_tuning),
            "traffic_pct": pct,
            "shadow": False,
        }
        if _column_exists(conn, "bot_deployments", "frozen_tools"):
            frozen_sql = ", frozen_tools"
            frozen_val = ", CAST(:frozen AS jsonb)"
            params["frozen"] = _jsonb(frozen_names)
        if _column_exists(conn, "bot_deployments", "bundle_hash"):
            frozen_sql += ", bundle_hash"
            frozen_val += ", :bundle_hash"
            params["bundle_hash"] = bundle_hash
        conn.execute(
            text(
                f"""
                INSERT INTO bot_deployments (
                  id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                  environment, status, published_by_user_id, published_at,
                  rollback_deployment_id, voice_config, tuning,
                  traffic_pct, shadow{frozen_sql}, created_at, updated_at
                ) VALUES (
                  :id, :bot_id, :prompt_version_id, :kb_snapshot_id, :tts_voice_id,
                  'production', 'active', :actor, now(),
                  :rollback_id, CAST(:voice_config AS jsonb), CAST(:tuning AS jsonb),
                  :traffic_pct, :shadow{frozen_val}, now(), now()
                )
                """
            ),
            params,
        )
        try:
            from agent_core.canary import record_experiment

            record_experiment(
                conn,
                bot_id=bot_id,
                canary_deployment_id=dep_id,
                baseline_deployment_id=prior["id"] if prior else None,
                traffic_pct=pct,
                shadow=bool(shadow),
                auto_rollback=list(triggers or []),
            )
        except Exception:
            logger.exception("canary experiment record failed")
    except IntegrityError as exc:
        raise ValueError("publish_conflict") from exc
    return _Deployed(dep_id=dep_id, note=note, previously_published=previously_published)


def _record(conn: Any, f: _Frozen, c: _Compiled, d: _Deployed) -> None:
    """The change log entry for the publish that just happened."""
    _mod = _db()
    _tenant = _mod._tenant
    _id = _mod._id
    from sqlalchemy.exc import IntegrityError

    version_id, target, bot_id, uid = f.version_id, f.target, f.bot_id, f.uid
    pct, triggers, shadow, report = f.pct, f.triggers, f.shadow, c.report
    dep_id, note, previously_published = d.dep_id, d.note, d.previously_published

    try:
        # Change log — inside the transaction on purpose. A record that can
        # be lost when the process dies mid-publish is worse than none,
        # because it looks complete. Not wrapped in try/except for the same
        # reason: if the agent's configuration history cannot be written,
        # the configuration must not change either.
        from agent_core import change_log

        change_log.record_publish(
            conn,
            tenant_id=_tenant(),
            actor_user_id=uid or "system",
            entry_id=_id("AUD"),
            bot_id=bot_id,
            version=_change_log_components(conn, version_id, target, note),
            previous_version=previously_published,
            deployment_id=dep_id,
            traffic_pct=pct,
            shadow=bool(shadow),
            auto_rollback=list(triggers or []),
            report=report,
        )
    except IntegrityError as exc:
        raise ValueError("publish_conflict") from exc


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


def rollback_bot_deployment(deployment_id: str) -> dict[str, Any]:
    """Re-activate a prior prod deployment and re-publish its prompt version.

    Re-publish is mandatory so the live-config invariant never splits.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    _jsonb = _mod._jsonb
    _as_dict = _mod._as_dict
    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        target = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                      d.tts_voice_id, d.environment, d.status, d.voice_config, d.tuning
                    FROM bot_deployments d
                    JOIN prompt_versions pv ON pv.id = d.prompt_version_id
                    WHERE d.id = :id AND pv.tenant_id = :t
                    """
                ),
                {"id": deployment_id, "t": _tenant()},
            )
        )
        if not target:
            raise KeyError(f"bot_deployment_not_found: {deployment_id}")
        if target["environment"] != "production":
            raise ValueError("rollback_requires_production_deployment")
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"{target['bot_id']}:{target['environment']}"},
        )
        if target["status"] == "active":
            raise ValueError("deployment_already_active")

        prompt_version_id = target["prompt_version_id"]
        pv = _one(
            conn.execute(
                text("SELECT id FROM prompt_versions WHERE id = :id"),
                {"id": prompt_version_id},
            )
        )
        if not pv:
            raise KeyError(f"prompt_version_not_found: {prompt_version_id}")

        version_row = _one(
            conn.execute(
                text(
                    """
                    SELECT prompt, guardrails, flow, agent_card, voice, persona
                      FROM prompt_versions WHERE id = :id
                    """
                ),
                {"id": prompt_version_id},
            )
        )
        from agent_core.cards.compile import compile_card, assert_publishable as _assert_card
        from agent_core.tools.catalog import CATALOG as _CATALOG
        import authz as _authz

        uid = _actor_user_id()
        has_publish = bool(uid and _authz.has_permission(uid, _authz.AGENT_PUBLISH))
        card_raw = version_row.get("agent_card") if version_row else {}
        if not isinstance(card_raw, dict):
            card_raw = {}
        attached = None
        try:
            from agent_core.cards.schema import is_authored, parse_card
            from agent_core.skills.persist import packs_for_skill_refs

            if is_authored(card_raw):
                attached = []
                parsed = parse_card(card_raw)
                attached = packs_for_skill_refs(parsed.skills)
        except Exception:
            pass
        # Tenant-scoped: this is G5's allowlist of legal handoff targets.
        known_bots = {
            r["id"]
            for r in _mod._rows(
                conn.execute(
                    text("SELECT id FROM bots WHERE tenant_id = :t"),
                    {"t": _tenant()},
                )
            )
        }
        voice_short, voice_locale, card_locales = voice_locale_facts(
            (version_row or {}).get("voice"), (version_row or {}).get("persona")
        )
        voice_provider, bound_tts = voice_provider_facts(
            voice_short, voice_locale, target["bot_id"]
        )
        report = compile_card(
            bot_id=target["bot_id"],
            card_raw=card_raw,
            flow=(version_row or {}).get("flow"),
            catalog_names=set(_CATALOG.specs),
            known_bot_ids=known_bots,
            attached_skills=attached,
            has_publish=has_publish,
            skip_eval_gates=True,
            prompt=(version_row or {}).get("prompt"),
            prompt_guardrails=(
                (version_row or {}).get("guardrails")
                if isinstance((version_row or {}).get("guardrails"), dict)
                else {}
            ),
            voice_short_name=voice_short,
            voice_locale=voice_locale,
            card_locales=card_locales,
            voice_provider=voice_provider,
            bound_tts_providers=bound_tts,
        )
        _assert_card(report)

        current = _fetch_active_deployment_row(
            conn, bot_id=target["bot_id"], environment="production"
        )

        try:
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'archived', updated_at = now()
                    WHERE status = 'published' AND bot_id = :bot_id
                    """
                ),
                {"bot_id": target["bot_id"]},
            )
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'published', updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": prompt_version_id},
            )
            if current:
                conn.execute(
                    text(
                        """
                        UPDATE bot_deployments
                        SET status = 'rolled_back', updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": current["id"]},
                )

            # Insert a fresh active row pointing at the rolled-back config
            # (keeps history; links rollback_deployment_id to the prior active).
            new_id = _id("DEP")
            # The executable contract of the version being restored, carried
            # forward. Guarded the same way publish guards it, so an unmigrated
            # database keeps working. Omitted, `frozen_tools` came back NULL,
            # `_map_bot_deployment` turned that into `[]`, and `effective_tools`
            # took the frozen branch and unioned nothing — every connector tool
            # silently disappeared from a rolled-back deployment.
            carried: dict[str, Any] = {}
            carry_sql = ""
            carry_val = ""
            for column in ("frozen_tools", "bundle_hash"):
                if not _column_exists(conn, "bot_deployments", column):
                    continue
                prior_value = _one(
                    conn.execute(
                        text(f"SELECT {column} AS v FROM bot_deployments WHERE id = :id"),
                        {"id": deployment_id},
                    )
                )
                carry_sql += f", {column}"
                if column == "frozen_tools":
                    carry_val += ", CAST(:frozen AS jsonb)"
                    carried["frozen"] = _jsonb((prior_value or {}).get("v"))
                else:
                    carry_val += ", :bundle_hash"
                    carried["bundle_hash"] = (prior_value or {}).get("v")
            conn.execute(
                text(
                    f"""
                    INSERT INTO bot_deployments (
                      id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                      environment, status, published_by_user_id, published_at,
                      rollback_deployment_id, voice_config, tuning{carry_sql},
                      created_at, updated_at
                    ) VALUES (
                      :id, :bot_id, :prompt_version_id, :kb_snapshot_id, :tts_voice_id,
                      'production', 'active', :actor, now(),
                      :rollback_id, CAST(:voice_config AS jsonb), CAST(:tuning AS jsonb){carry_val},
                      now(), now()
                    )
                    """
                ),
                {
                    "id": new_id,
                    "bot_id": target["bot_id"],
                    "prompt_version_id": prompt_version_id,
                    "kb_snapshot_id": target.get("kb_snapshot_id"),
                    "tts_voice_id": target.get("tts_voice_id"),
                    "actor": _actor_user_id(),
                    "rollback_id": current["id"] if current else deployment_id,
                    "voice_config": _jsonb(_as_dict(target.get("voice_config"))),
                    "tuning": _jsonb(_as_dict(target.get("tuning"))),
                    # Carried from the deployment being restored, because they
                    # describe *that* version. Omitted, `frozen_tools` came back
                    # NULL, `_map_bot_deployment` turned that into `[]`, and
                    # `effective_tools` took the frozen branch and unioned
                    # nothing — every connector tool silently disappeared from a
                    # rolled-back deployment.
                    **carried,
                },
            )

            # A rollback changes what callers hear exactly as much as a publish
            # does, so it belongs in the same chain.
            from agent_core import change_log

            # The gates the re-shipped version passed at its publish, from the
            # bundle stored on it. A rollback recorded no verdict at all before.
            compiled = _as_dict(
                conn.execute(
                    text("SELECT compiled FROM prompt_versions WHERE id = :id"),
                    {"id": prompt_version_id},
                ).scalar()
            )
            change_log.record_rollback(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=target["bot_id"],
                to_deployment_id=new_id,
                from_deployment_id=current["id"] if current else None,
                version_id=prompt_version_id,
                report=compiled,
            )
            try:
                from agent_core.canary import close_running_experiments

                close_running_experiments(
                    conn,
                    bot_id=target["bot_id"],
                    environment="production",
                    reason="deployment_rollback",
                )
            except Exception:
                logger.exception("could not close running experiments after deployment rollback")
        except IntegrityError as exc:
            raise ValueError("publish_conflict") from exc

        row = _fetch_bot_deployment(conn, new_id)
    assert row is not None
    return row
