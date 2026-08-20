"""Floor copilot — engine-grounded draft, not a transcript paraphrase.

Whisper text is assembled from live QA, the authority snapshot, and the latest
treatment plan. Analysis-profile wording is optional polish; a veto in those
engines cannot be talked away.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

_VETO_MARKERS = (
    "do not",
    "must not",
    "escalate",
    "hold",
    "cap",
    "forbidden",
)


def assemble(interaction_id: str) -> dict[str, Any] | None:
    """Engine snapshot + deterministic draft. No analysis-profile call."""
    from agent_core.live_qa.pack import build_pack

    pack = build_pack(interaction_id)
    if pack is None:
        return None
    customer_id = pack.get("customerId")
    authority = _authority(customer_id, interaction_id)
    treatment = _treatment(customer_id)
    engines = {
        "authority": authority,
        "treatment": treatment,
        "liveQa": _latest_qa(pack),
    }
    draft = _deterministic_draft(engines)
    return {
        "interactionId": interaction_id,
        "customerId": customer_id,
        "whisperDraft": draft,
        "engineDraft": draft,
        "engines": engines,
        "vetoes": _vetoes(engines),
        "card": _card_chip(interaction_id),
        "approvals": _approvals_for(customer_id),
    }


def build(interaction_id: str) -> dict[str, Any] | None:
    pack = assemble(interaction_id)
    if pack is None:
        return None
    pack["whisperDraft"] = _maybe_polish(pack["engineDraft"], pack["engines"])
    return pack


def iter_events(
    interaction_id: str, *, pack: dict[str, Any] | None = None
) -> Iterator[dict[str, Any]]:
    """AG-UI-style stream: pack (engines + approval form) first, then whisper tokens.

    The mouth never waits on this. Handoff consumes it. Analysis polish is
    optional; a veto in the engine draft cannot be talked away.
    """
    if pack is None:
        pack = assemble(interaction_id)
    if pack is None:
        yield {"type": "error", "detail": "interaction_not_found"}
        return
    yield {"type": "pack", **pack, "streaming": True}
    polished = _maybe_polish(pack["engineDraft"], pack["engines"])
    for chunk in _tokenise(polished):
        yield {"type": "token", "text": chunk}
    yield {
        "type": "done",
        "whisperDraft": polished,
        "engineDraft": pack["engineDraft"],
        "vetoes": pack["vetoes"],
    }


def _tokenise(text: str) -> list[str]:
    if not text:
        return []
    parts = re.findall(r"\S+\s*", text)
    return parts or [text]


def _approvals_for(customer_id: str | None) -> list[dict[str, Any]]:
    if not customer_id:
        return []
    try:
        from work_runtime.adapter_pg import list_jobs

        return list_jobs(status="input_required", customer_id=customer_id, limit=20)
    except Exception:
        logger.exception("copilot approvals lookup failed")
        return []


def _authority(customer_id: str | None, interaction_id: str) -> dict[str, Any]:
    if not customer_id:
        from agent_core.authority.policy import empty

        return empty()
    try:
        import db
        from agent_core.authority import policy as authority_policy

        with db.engine.connect() as conn:
            return authority_policy.snapshot(
                conn,
                customer_id=customer_id,
                tenant_id=db.current_tenant(),
                interaction_id=interaction_id,
            )
    except Exception:
        logger.exception("copilot authority snapshot failed")
        from agent_core.authority.policy import empty

        return empty() | {"customerId": customer_id}


def _treatment(customer_id: str | None) -> dict[str, Any]:
    empty = {
        "decisionId": None,
        "action": None,
        "channel": None,
        "rationale": None,
        "enacted": False,
        "enactedBy": None,
        "scheduledAt": None,
    }
    if not customer_id:
        return empty
    try:
        import db

        with db.engine.connect() as conn:
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT id, chosen_action, chosen_channel, rationale,
                               enacted, enacted_by, scheduled_at
                          FROM treatment_decisions
                         WHERE customer_id = :cid
                         ORDER BY created_at DESC
                         LIMIT 1
                        """
                    ),
                    {"cid": customer_id},
                )
            )
        if not row:
            return empty
        return {
            "decisionId": row["id"],
            "action": row.get("chosen_action"),
            "channel": row.get("chosen_channel"),
            "rationale": row.get("rationale"),
            "enacted": bool(row.get("enacted")),
            "enactedBy": row.get("enacted_by"),
            "scheduledAt": str(row["scheduled_at"]) if row.get("scheduled_at") else None,
        }
    except Exception:
        logger.exception("copilot treatment lookup failed")
        return empty


def _latest_qa(pack: dict[str, Any]) -> dict[str, Any] | None:
    rows = pack.get("liveQa") or pack.get("qa") or []
    if isinstance(rows, list) and rows:
        return rows[-1] if isinstance(rows[-1], dict) else None
    if isinstance(rows, dict):
        return rows
    return None


def _deterministic_draft(engines: dict[str, Any]) -> str:
    lines: list[str] = []
    auth = engines.get("authority") or {}
    talk = (auth.get("talkTrack") or "").strip()
    if talk:
        lines.append(talk)
    elif auth.get("status") and auth["status"] not in {"none"}:
        label = auth.get("reasonLabel") or auth.get("reason") or auth["status"]
        lines.append(f"Authority: {label}.")
    qa = engines.get("liveQa") or {}
    rec = (qa.get("recommendedAction") or qa.get("recommended_action") or "").strip()
    if rec:
        lines.append(f"Live QA: {rec.replace('_', ' ')}.")
    treat = engines.get("treatment") or {}
    action = treat.get("action")
    if action and action != "wait":
        when = treat.get("scheduledAt") or "when due"
        lines.append(f"Next treatment: {action} ({when}).")
        if treat.get("rationale"):
            lines.append(str(treat["rationale"])[:240])
    if not lines:
        lines.append("Stay with the current script. No engine veto is in force.")
    return " ".join(lines)


def _vetoes(engines: dict[str, Any]) -> list[str]:
    out: list[str] = []
    auth = engines.get("authority") or {}
    if auth.get("status") in {"escalate", "cap"} or (auth.get("verdict") or "") in {
        "escalate",
        "cap",
    }:
        out.append(auth.get("reasonLabel") or auth.get("reason") or "authority_veto")
    treat = engines.get("treatment") or {}
    if str(treat.get("action") or "") in {"field_visit", "legal_notice"}:
        out.append(f"treatment:{treat['action']}")
    return out


def _maybe_polish(draft: str, engines: dict[str, Any]) -> str:
    """Analysis profile may rephrase. It may not drop a veto."""
    try:
        import azure_openai

        vetoes = _vetoes(engines)
        system = (
            "You rewrite a supervisor whisper for a live collections call. "
            "Keep every constraint in the engine draft. Do not add a waiver, "
            "settlement, or product the engines did not name. Under 40 words."
        )
        result = azure_openai.chat_with_tools(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": draft},
            ],
            tools=None,
            temperature=0.0,
            max_completion_tokens=120,
            profile=azure_openai.PROFILE_ANALYSIS,
        )
        text_out = ""
        if isinstance(result, dict):
            text_out = str(result.get("content") or result.get("text") or "")
        elif isinstance(result, str):
            text_out = result
        text_out = text_out.strip()
        if not text_out:
            return draft
        lowered = text_out.lower()
        for marker in _VETO_MARKERS:
            if marker in draft.lower() and marker not in lowered and vetoes:
                return draft
        return text_out
    except Exception:
        return draft


def _card_chip(interaction_id: str) -> dict[str, Any]:
    empty: dict[str, Any] = {"botId": None, "displayName": None, "skills": []}
    try:
        import db

        with db.engine.connect() as conn:
            row = db._one(
                conn.execute(
                    text("SELECT handler_bot_id FROM interactions WHERE id = :id"),
                    {"id": interaction_id},
                )
            )
        bot_id = (row or {}).get("handler_bot_id")
        if not bot_id:
            return empty
        display = str(bot_id)
        skills: list[str] = []
        try:
            from agent_core.deployment import load_active_bundle

            bundle = load_active_bundle(bot_id=bot_id)
            card = bundle.get("agentCard") or {}
            ident = card.get("identity") if isinstance(card.get("identity"), dict) else {}
            display = str(ident.get("display_name") or ident.get("displayName") or bot_id)
            for item in card.get("skills") or []:
                if not isinstance(item, dict):
                    continue
                sid = item.get("skill_id") or item.get("skillId")
                if sid:
                    skills.append(str(sid))
        except Exception:
            logger.exception("copilot card load failed")
        return {"botId": bot_id, "displayName": display, "skills": skills[:3]}
    except Exception:
        logger.exception("copilot card chip failed")
        return empty
