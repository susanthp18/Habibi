"""Same-call barge and whisper drain.

Barge reuses ``twilio_ops.warm_transfer_to_supervisor``. Listen stays
transcript-only. Whisper is a coach note injected into the next bot turn.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)


def provider_call_id(interaction_id: str, *, conn: Any | None = None) -> str | None:
    """Twilio CallSid for a live session, or None (sandbox / WhatsApp / ended)."""
    if not interaction_id:
        return None
    sql = """
        SELECT provider_call_id
        FROM voice_sessions
        WHERE interaction_id = :iid
          AND status IN ('starting', 'live')
          AND transport = 'twilio'
          AND provider_call_id IS NOT NULL
        ORDER BY started_at DESC NULLS LAST
        LIMIT 1
    """
    try:
        if conn is not None:
            row = conn.execute(text(sql), {"iid": interaction_id}).mappings().first()
        else:
            import db

            with db.engine.connect() as owned:
                row = owned.execute(text(sql), {"iid": interaction_id}).mappings().first()
        if not row:
            return None
        sid = (row.get("provider_call_id") or "").strip()
        return sid or None
    except Exception:
        logger.exception("live_qa provider_call_id lookup failed for %s", interaction_id)
        return None


def barge_audio(interaction_id: str, *, reason: str = "supervisor_barge") -> dict[str, Any]:
    """Take over the live Twilio call. Never raises.

    Returns ``{audio: true, ...}`` on success, ``{audio: false, reason}`` when
    there is no media plane or Twilio fails. CRM reassignment is the caller's
    job — a failed dial must not roll back a supervisor who already owns the
    case in Handoff.
    """
    call_sid = provider_call_id(interaction_id)
    if not call_sid:
        return {"audio": False, "reason": "no_call_sid"}
    try:
        from voice import twilio_ops

        meta = twilio_ops.warm_transfer_to_supervisor(call_sid, reason=reason)
        return {"audio": True, "reason": None, **meta}
    except Exception as exc:
        logger.exception("live_qa barge audio failed for %s", interaction_id)
        return {"audio": False, "reason": str(exc)[:240] or "twilio_failed"}


def consume_whispers(interaction_id: str) -> list[str]:
    """Unconsumed whisper notes for this call, marked consumed. Never raises."""
    if not interaction_id:
        return []
    try:
        import db

        with db.engine.begin() as conn:
            rows = db._rows(
                conn.execute(
                    text(
                        """
                        UPDATE supervisor_actions
                        SET consumed_at = now()
                        WHERE id IN (
                          SELECT id FROM supervisor_actions
                          WHERE interaction_id = :iid
                            AND action = 'whisper'
                            AND consumed_at IS NULL
                            AND note IS NOT NULL
                          ORDER BY created_at
                          FOR UPDATE SKIP LOCKED
                        )
                        RETURNING note
                        """
                    ),
                    {"iid": interaction_id},
                )
            )
        notes = [str(r["note"]).strip() for r in rows if r.get("note")]
        return [n for n in notes if n]
    except Exception:
        logger.exception("live_qa consume_whispers failed for %s", interaction_id)
        return []


def whisper_correction(note: str):
    """Shape a supervisor whisper as the turn-critic Correction the injector expects."""
    from agent_core.turn_critic import SEVERITY_HIGH, Correction

    text_note = (note or "").strip()[:280]
    if not text_note:
        return None
    return Correction(
        kind="whisper",
        severity=SEVERITY_HIGH,
        source="supervisor",
        directive=(
            "Floor supervisor whisper (follow this on your next reply, do not "
            f"read it out): {text_note}"
        ),
    )
