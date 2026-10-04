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
    # An engine that could not be read is not one with nothing to say: the
    # draft names it instead of reporting that no veto is in force.
    unavailable = [name for name, got in (("authority", authority), ("treatment", treatment)) if got is None]
    from agent_core.authority.policy import empty as authority_empty

    engines = {
        "authority": authority if authority is not None else authority_empty() | {"customerId": customer_id},
        "treatment": treatment if treatment is not None else dict(_TREATMENT_NONE),
        "liveQa": _latest_qa(pack),
        "unavailable": unavailable,
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
        from work_runtime import list_jobs

        return list_jobs(status="input_required", customer_id=customer_id, limit=20)
    except Exception:
        logger.exception("copilot approvals lookup failed")
        return []


def _authority(customer_id: str | None, interaction_id: str) -> dict[str, Any] | None:
    """The authority snapshot; None when it could not be read."""
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
        return None


_TREATMENT_NONE: dict[str, Any] = {
    "decisionId": None,
    "action": None,
    "channel": None,
    "rationale": None,
    "enacted": False,
    "enactedBy": None,
    "scheduledAt": None,
}


def _treatment(customer_id: str | None) -> dict[str, Any] | None:
    """The current treatment decision; None when it could not be read."""
    if not customer_id:
        return dict(_TREATMENT_NONE)
    try:
        import db

        with db.engine.connect() as conn:
            return _treatment_on(conn, customer_id)
    except Exception:
        logger.exception("copilot treatment lookup failed")
        return None


def _treatment_on(conn: Any, customer_id: str) -> dict[str, Any]:
    import db

    from agent_core.treatment import decisions

    # The same next best action the customer card shows: real, recent,
    # collections only. The latest row of any kind used to be read here,
    # simulated and weeks-old ones included.
    row = decisions.current(conn, customer_id=customer_id, tenant_id=db.current_tenant())
    if not row:
        return dict(_TREATMENT_NONE)
    return {
        "decisionId": row["id"],
        # A held decision is not a plan: its rationale says why it held.
        "action": "wait" if row.get("suppression_reason") else row.get("chosen_action"),
        "channel": None if row.get("suppression_reason") else row.get("chosen_channel"),
        "rationale": row.get("rationale"),
        "enacted": bool(row.get("enacted")),
        "enactedBy": row.get("enacted_by"),
        "scheduledAt": str(row["scheduled_at"]) if row.get("scheduled_at") else None,
    }


def evidence(
    conn: Any, *, interaction_id: str, customer_id: str | None, authority: dict[str, Any] | None
) -> str:
    """A version of what :func:`assemble` drafts from -- the authority and
    treatment decisions, the latest live-QA verdict and the approvals waiting
    on the customer, each as read -- so a page redrafts when one changes and
    never on an unchanged poll. Cheap: one connection, no examiner pack.
    ``authority`` is the caller's snapshot of the same decision."""
    import hashlib
    import json

    def read(what: str, fn: Any) -> Any:
        try:
            with conn.begin_nested():
                return fn()
        except Exception:
            logger.exception("copilot evidence: %s unreadable", what)
            return "unavailable"

    qa = read(
        "live QA",
        lambda: conn.execute(
            text(
                "SELECT id, verdict, recommended_action, reason, enacted FROM live_qa_decisions"
                " WHERE interaction_id = :id ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": interaction_id},
        ).mappings().first(),
    )
    basis = [
        authority,
        read("treatment", lambda: _treatment_on(conn, customer_id)) if customer_id else None,
        dict(qa) if qa and qa != "unavailable" else qa,
        _approvals_for(customer_id),
    ]
    return hashlib.sha1(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _latest_qa(pack: dict[str, Any]) -> dict[str, Any] | None:
    rows = pack.get("liveQa") or pack.get("qa") or []
    if isinstance(rows, list) and rows:
        return rows[-1] if isinstance(rows[-1], dict) else None
    if isinstance(rows, dict):
        return rows
    return None


_UNAVAILABLE_WORDS = {"authority": "the authority decision", "treatment": "the treatment plan"}


def _deterministic_draft(engines: dict[str, Any]) -> str:
    lines: list[str] = []
    missing = [_UNAVAILABLE_WORDS[name] for name in engines.get("unavailable") or []]
    if missing:
        lines.append(f"Couldn't load {' or '.join(missing)} — check it before offering anything.")
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
    elif missing and len(lines) == 1:
        lines.append("Stay with the current script.")
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
    """Analysis profile may rephrase. It may not drop a veto, nor the warning
    that an engine could not be read."""
    if engines.get("unavailable"):
        return draft
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
        # The agents' registry: a Voice Studio agent is registered under its
        # engine name when it first files a call. Agents have no skills now.
        with db.engine.connect() as conn:
            name = conn.execute(text("SELECT name FROM bots WHERE id = :id"), {"id": bot_id}).scalar()
        return {"botId": bot_id, "displayName": str(name or bot_id), "skills": []}
    except Exception:
        logger.exception("copilot card chip failed")
        return empty
