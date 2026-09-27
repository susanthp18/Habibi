"""Everything one call's pass needs, loaded once.

The stored transcript is masked at rest by regex (``capture_events``), so the
PII pass reads the words as spoken from the engine run, turn for turn
(``voice_studio.transcript_events`` is the order both were filed in). Calls
from other channels, and a run the engine no longer has, fall back to the
stored text: masking then only ever adds to what is already masked.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from call_intel.pii import Turn

logger = logging.getLogger(__name__)


@dataclass
class Call:
    interaction_id: str
    customer_id: str | None
    bot_id: str | None
    channel: str
    source_payload: dict[str, Any]
    turns: list[Turn]
    #: turn_index -> interaction_transcript.id
    turn_ids: dict[int, str]
    #: turn_index -> seconds into the call (as filed)
    turn_at: dict[int, float]
    #: The customer's own values, for CRM matching.
    crm: dict[str, list[str]] = field(default_factory=dict)
    #: Words never masked as a name: the agent's persona, the bank.
    allow_names: list[str] = field(default_factory=list)
    #: True when the words came from the engine rather than the masked store.
    raw: bool = False


class EngineUnavailable(RuntimeError):
    """The engine could not return a Voice Studio call's words."""


#: "I'm Kaia" / "I’m Kaia" (TTS text often carries a typographic apostrophe).
_PERSONA = re.compile(r"\b(?i:i am|i['’]m|this is|my name is)\s+([A-Z][\w-]+)")


def load(interaction_id: str) -> Call | None:
    import db

    with db.engine.connect() as conn:
        ix = conn.execute(
            text("SELECT id, customer_id, handler_bot_id, channel, source_payload "
                 "FROM interactions WHERE id = :id"),
            {"id": interaction_id},
        ).mappings().first()
        if ix is None:
            return None
        stored = conn.execute(
            text("SELECT id, turn_index, speaker, text, at_sec FROM interaction_transcript "
                 "WHERE interaction_id = :id ORDER BY turn_index"),
            {"id": interaction_id},
        ).mappings().all()
        customer = conn.execute(
            text("SELECT name, phone_primary, phone_alt, email, address, segment FROM customers WHERE id = :id"),
            {"id": ix["customer_id"]},
        ).mappings().first()
        accounts = conn.execute(
            text("SELECT id FROM accounts WHERE customer_id = :id"), {"id": ix["customer_id"]}
        ).scalars().all()
        bot_name = conn.execute(
            text("SELECT name FROM bots WHERE id = :id"), {"id": ix["handler_bot_id"]}
        ).scalar()

    payload = dict(ix["source_payload"] or {})
    turns = [Turn(int(r["turn_index"]), "bot" if r["speaker"] == "bot" else "customer", r["text"] or "")
             for r in stored]
    raw = False
    studio = payload.get("voiceStudio") or {}
    if studio.get("engineRunId"):
        spoken = _engine_turns(studio)
        if spoken is None:
            # Detecting on the masked store would find almost nothing and look
            # like a clean call: fail, and let the job retry.
            raise EngineUnavailable(f"engine run {studio['engineRunId']} unavailable")
        if len(spoken) == len(turns):
            turns, raw = spoken, True
        else:
            logger.warning("call_intel %s: engine has %s turns, PayInt %s; using the stored text",
                           interaction_id, len(spoken), len(turns))

    crm: dict[str, list[str]] = {}
    if customer and customer["segment"] != "sentinel":
        crm = {
            "name": [customer["name"]] if customer["name"] else [],
            "phone": [p for p in (customer["phone_primary"], customer["phone_alt"]) if p],
            "email": [customer["email"]] if customer["email"] else [],
            "address": [customer["address"]] if customer["address"] else [],
            "account": list(accounts),
        }

    from agent_core.prompt import bank_name

    allow = [*bank_name().split(), *str(bot_name or "").split()]
    first_bot = next((t.text for t in turns if t.speaker == "bot"), "")
    allow += _PERSONA.findall(first_bot)

    return Call(
        interaction_id=interaction_id,
        customer_id=ix["customer_id"],
        bot_id=ix["handler_bot_id"],
        channel=ix["channel"],
        source_payload=payload,
        turns=turns,
        turn_ids={int(r["turn_index"]): r["id"] for r in stored},
        turn_at={int(r["turn_index"]): float(r["at_sec"] or 0) for r in stored},
        crm=crm,
        allow_names=allow,
        raw=raw,
    )


def _engine_turns(studio: dict[str, Any]) -> list[Turn] | None:
    import voice_studio

    try:
        run = voice_studio.engine_call(
            "GET", f"/workflow/{studio['workflowId']}/runs/{studio['engineRunId']}") or {}
    except Exception:
        logger.exception("call_intel: engine run %s unavailable", studio.get("engineRunId"))
        return None
    events = voice_studio.transcript_events(((run.get("logs") or {}).get("realtime_feedback_events")) or [])
    return [
        Turn(i, "bot" if e["type"] == "rtf-bot-text" else "customer", voice_studio.spoken_text(e),
             (e.get("payload") or {}).get("language"))
        for i, e in enumerate(events)
    ]


def recording(interaction_id: str) -> tuple[str, bytes] | None:
    """(media id, WAV bytes) of the call's original recording."""
    from voice.recordings import _load_bytes, media_for_interaction

    media = media_for_interaction(interaction_id, variant="original")
    if media is None:
        return None
    return media["id"], _load_bytes(str(media["storage_ref"]))


def rules() -> dict[str, Any]:
    """The tenant's redaction rules: disabled types, custom patterns, model labels."""
    import db

    with db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, pii_type, enabled, pattern, model_label FROM redaction_rule_configs "
                 "WHERE tenant_id = :t"),
            {"t": db.current_tenant()},
        ).mappings().all()
    return {
        "disabled": [r["pii_type"] for r in rows if not r["enabled"] and r["pii_type"] != "custom"],
        "custom": [(r["id"], r["pattern"]) for r in rows if r["enabled"] and r["pattern"]],
        "labels": [r["model_label"] for r in rows if r["enabled"] and r["model_label"]],
    }
