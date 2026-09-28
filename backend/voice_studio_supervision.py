"""Supervising live Voice Studio calls: listen, whisper, take over.

The engine does the audio (``integrations/supervisor``); PayInt decides who
may, records who did, and keeps the CRM honest about who is handling the call:

- **Listen** (``SUPERVISOR_READ``): a ``listen_in`` row per socket. The live
  transcript is masked for a supervisor without ``PII_RAW_READ``.
- **Whisper** (``SUPERVISOR_WRITE``): the Floor's existing whisper action is
  forwarded to the engine, which puts it in front of the agent's next reply.
- **Take over** (``SUPERVISOR_WRITE``): the Floor's ``barge`` action hands the
  call to the supervisor in the CRM (as it always did), and the takeover
  socket carries their voice. When the socket closes the engine hands the call
  back to the agent, and so does the CRM here.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

from sqlalchemy import text

logger = logging.getLogger(__name__)

SOCKET_PATH = re.compile(r"^/supervise/(\d+)/(listen|takeover)$")


def live_run(conn: Any, interaction_id: str) -> str | None:
    """The engine run of a Voice Studio call still in progress."""
    return conn.execute(text(
        "SELECT provider_call_id FROM voice_sessions WHERE interaction_id = :ix "
        "AND id LIKE 'VS-studio-%' AND status IN ('starting', 'live') "
        "ORDER BY started_at DESC NULLS LAST LIMIT 1"
    ), {"ix": interaction_id}).scalar()


def live_runs(conn: Any, interaction_ids: list[str]) -> dict[str, str]:
    if not interaction_ids:
        return {}
    rows = conn.execute(text(
        "SELECT DISTINCT ON (interaction_id) interaction_id, provider_call_id FROM voice_sessions "
        "WHERE interaction_id = ANY(:ids) AND id LIKE 'VS-studio-%' AND status IN ('starting', 'live') "
        "ORDER BY interaction_id, started_at DESC NULLS LAST"
    ), {"ids": interaction_ids}).all()
    return {str(r.interaction_id): str(r.provider_call_id) for r in rows if r.provider_call_id}


def whisper(interaction_id: str, note: str) -> bool | None:
    """Put the note in front of the agent on a live Voice Studio call.
    True: delivered; False: it is a Voice Studio call but the engine refused;
    None: not a live Voice Studio call (the caller handles it as before)."""
    import db
    import voice_studio

    with db.engine.connect() as conn:
        run_id = live_run(conn, interaction_id)
    if not run_id:
        return None
    try:
        voice_studio.engine_call("POST", f"/supervise/{run_id}/whisper", json={"text": note[:1000]})
        return True
    except Exception:
        logger.exception("voice studio whisper to run %s failed", run_id)
        return False


def _interaction_of_run(conn: Any, run_id: str) -> str | None:
    return conn.execute(
        text("SELECT interaction_id FROM voice_sessions WHERE id = :id"), {"id": f"VS-studio-{run_id}"}
    ).scalar()


def opened(actor: str, run_id: str, mode: str) -> dict[str, Any]:
    """A supervisor socket opened. Returns what ``closed`` needs."""
    import db

    ctx: dict[str, Any] = {"actor": actor, "run_id": run_id, "mode": mode}
    with db.engine.begin() as conn:
        ix = _interaction_of_run(conn, run_id)
        if not ix:  # an editor test call: nothing is filed, the gateway audit records it
            return ctx
        ctx["interaction_id"] = ix
        if mode == "listen":
            ctx["action_id"] = _record(conn, ix, actor, "listen_in")
        else:
            # The Floor's barge action already moved the call to the supervisor
            # in the CRM; the voice is now actually on the line.
            ctx["action_id"] = conn.execute(text(
                "UPDATE supervisor_actions SET audio_joined = true WHERE id = ("
                "  SELECT id FROM supervisor_actions WHERE interaction_id = :ix AND action = 'barge' "
                "  AND supervisor_user_id = :sup ORDER BY created_at DESC LIMIT 1) RETURNING id"
            ), {"ix": ix, "sup": actor}).scalar() or _record(conn, ix, actor, "barge", audio=True)
    return ctx


def closed(ctx: dict[str, Any]) -> None:
    """A supervisor socket closed. A takeover hands the call back to the agent
    (the engine does the same on its side), unless the call has ended."""
    import db

    ix = ctx.get("interaction_id")
    if ctx.get("mode") != "takeover" or not ix:
        return
    with db.engine.begin() as conn:
        bot = conn.execute(text(
            "SELECT target_bot_id FROM supervisor_actions WHERE interaction_id = :ix AND action = 'barge' "
            "AND target_bot_id IS NOT NULL ORDER BY created_at DESC LIMIT 1"
        ), {"ix": ix}).scalar()
        if not bot:
            return
        conn.execute(text(
            "UPDATE interactions SET handler_kind = 'bot', handler_bot_id = :bot, handler_user_id = NULL, "
            "updated_at = now() WHERE id = :ix AND status = 'active'"
        ), {"ix": ix, "bot": bot})
        conn.execute(text(
            "UPDATE interaction_handoffs SET completed_at = now() "
            "WHERE interaction_id = :ix AND to_user_id = :sup AND completed_at IS NULL"
        ), {"ix": ix, "sup": ctx["actor"]})


def _record(conn: Any, interaction_id: str, actor: str, action: str, *, audio: bool = False) -> str:
    import uuid

    row = conn.execute(
        text("SELECT handler_user_id, handler_bot_id FROM interactions WHERE id = :ix"), {"ix": interaction_id}
    ).first()
    action_id = f"sup-{uuid.uuid4().hex[:12]}"
    conn.execute(text(
        "INSERT INTO supervisor_actions (id, interaction_id, supervisor_user_id, action, target_user_id, "
        "target_bot_id, audio_joined, created_at) VALUES (:id, :ix, :sup, :action, :tuid, :tbid, :audio, now())"
    ), {"id": action_id, "ix": interaction_id, "sup": actor, "action": action,
        "tuid": row.handler_user_id if row else None, "tbid": row.handler_bot_id if row else None,
        "audio": audio})
    return action_id


def masker(can_see_raw: bool) -> Callable[[str], str] | None:
    """Masks the live transcript and tool arguments sent to a supervisor who
    may not see raw PII. The post-call record is masked properly by the call
    intelligence pass; this is the regex floor, applied as the words arrive."""
    if can_see_raw:
        return None
    from pii_redact import redact_text

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            return redact_text(value)
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    def mask(message: str) -> str:
        try:
            event = json.loads(message)
        except ValueError:
            return redact_text(message)
        if isinstance(event, dict) and "payload" in event:
            event["payload"] = scrub(event["payload"])
        return json.dumps(event)

    return mask


if __name__ == "__main__":
    m = masker(False)
    out = json.loads(m(json.dumps({"type": "rtf-user-transcription", "payload": {"text": "my card is 4111 1111 1111 1111"}})))
    assert "4111 1111 1111 1111" not in out["payload"]["text"], out
    assert masker(True) is None
    assert SOCKET_PATH.match("/supervise/42/takeover").groups() == ("42", "takeover")
    print("ok")
