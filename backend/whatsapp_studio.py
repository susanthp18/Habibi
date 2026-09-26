"""WhatsApp replies from the PayInt Voice Studio agent.

The same engine agent that takes calls answers the WhatsApp thread, through the
engine's text-chat sessions: one engine session per conversation, kept in
``conversations.bot_state`` and replaced once it ends or the Inbox hands the
thread back to the bot. Everything around the reply stays PayInt's and is
unchanged: ingest and the job queue (``bot_jobs``), the policy gate, take-over,
persist-then-send (``bot_turn_write.send_reply``) and escalation.

Tool calls reach ``voice_studio.run_tool`` with this thread's interaction id
(``initial_context.interaction_id``), so a promise or a verification lands on
the WhatsApp interaction. A transfer to a person becomes an Inbox escalation.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.engine import Engine

import bot_conversation
import bot_jobs
import voice_studio
from agent_core import lexicon
from agent_core.clock import utc_now
from env_utils import env_str

logger = logging.getLogger(__name__)

OBJECTIVE = "whatsapp"
TRANSFER_TOOL = "transfer_to_human"


def enabled() -> bool:
    """On once Voice Studio is configured; WHATSAPP_BOT_ENGINE=legacy forces the old runtime."""
    choice = env_str("WHATSAPP_BOT_ENGINE", "").strip().lower()
    if choice:
        return choice == "studio"
    return voice_studio.configured()


def _initial_context(conv: dict[str, Any]) -> dict[str, Any]:
    name = str(conv.get("customer_name") or "")
    ctx = {
        "channel": "whatsapp",
        "direction": "inbound",
        "conversation_id": conv.get("id"),
        "interaction_id": conv.get("interaction_id"),
        "customer_id": conv.get("customer_id"),
        "account_id": conv.get("account_id"),
        "customer_name": name,
        "first_name": name.split(" ")[0] if name else None,
        "language": conv.get("language"),
    }
    return {k: v for k, v in ctx.items() if v not in (None, "")}


def _session_current(state: dict[str, Any]) -> bool:
    """Is the stored engine session still the thread's? Not after the Inbox
    returned the thread to the bot (``dialog_reset_at``)."""
    if not state.get("studio_run_id"):
        return False
    started = state.get("studio_started_at") or ""
    reset = bot_conversation.parse_dialog_reset_at(state)
    if reset is None:
        return True
    try:
        return datetime.fromisoformat(started) > reset
    except ValueError:
        return False


def _assistant_text(turns: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        str((t.get("assistant_message") or {}).get("text") or "").strip()
        for t in turns
        if str((t.get("assistant_message") or {}).get("text") or "").strip()
    )


def _asked_for_person(turns: list[dict[str, Any]]) -> bool:
    return any(
        e.get("type") == "tool_call_started" and (e.get("payload") or {}).get("function_name") == TRANSFER_TOOL
        for t in turns
        for e in (t.get("events") or [])
    )


def converse(conv: dict[str, Any], state: dict[str, Any], customer_text: str) -> tuple[str, bool]:
    """Send the customer's message to the thread's engine session (opening one
    if needed). Returns the agent's reply and whether it asked for a person.
    Updates ``state`` with the session."""
    new_turns: list[dict[str, Any]] = []
    run_id, workflow_id = state.get("studio_run_id"), state.get("studio_workflow_id")
    session = None
    if _session_current(state):
        try:
            session = voice_studio.engine_call("GET", f"/workflow/{workflow_id}/text-chat/sessions/{run_id}")
        except Exception:
            logger.info("whatsapp studio: session %s gone, opening a new one", run_id, exc_info=True)
        if session and session.get("is_completed"):
            session = None
    if session is None:
        import db

        with db.engine.connect() as c:
            agent = voice_studio.agent_for(c, OBJECTIVE, allow_default=False)
        if not agent:
            raise voice_studio.NotBound("no Voice Studio agent is bound for WhatsApp")
        workflow_id = agent["engine_workflow_id"]
        session = voice_studio.engine_call(
            "POST",
            f"/workflow/{workflow_id}/text-chat/sessions",
            json={
                "name": f"WA-{conv['id']}",
                "initial_context": _initial_context(conv),
                "annotations": {"channel": "whatsapp", "conversation_id": conv["id"]},
            },
            timeout=120,
        )
        new_turns.extend(session["session_data"]["turns"])
        state.update(
            {
                "studio_run_id": session["workflow_run_id"],
                "studio_workflow_id": workflow_id,
                "studio_started_at": utc_now().isoformat(),
                "studio_turns": 0,
            }
        )
    before = len(session["session_data"]["turns"])
    session = voice_studio.engine_call(
        "POST",
        f"/workflow/{workflow_id}/text-chat/sessions/{session['workflow_run_id']}/messages",
        json={"text": customer_text, "expected_revision": session["revision"]},
        timeout=120,
    )
    new_turns.extend(session["session_data"]["turns"][before:])
    state["studio_turns"] = int(state.get("studio_turns") or 0) + 1
    if session.get("is_completed"):
        state.pop("studio_run_id", None)  # the agent closed; the next message opens a new session
    # The reply only: on a new session the agent's opening line precedes it and
    # would greet the customer twice.
    reply = _assistant_text(new_turns[-1:]) or _assistant_text(new_turns)
    return reply, _asked_for_person(new_turns)


def handle_turn(engine: Engine, job: dict[str, Any]) -> None:
    """One WhatsApp bot turn answered by the engine agent."""
    import bot_runtime
    import bot_turn_write

    job_id, conversation_id = job["id"], job["conversation_id"]
    reuse = bot_runtime._reuse_prior_outbound(engine, job)
    if reuse is None:
        return
    reuse_outbound_id, reuse_body = reuse

    conv = bot_conversation.load_conversation(engine, conversation_id)
    if not conv:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "conversation_not_found")
        return
    import usage_meter

    usage_meter.retarget_attribution(conv.get("interaction_id"))
    gate = bot_conversation.policy_gate(engine, conv)
    if gate:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, gate)
        return
    customer_text, latest_msg_id = bot_conversation.latest_customer_text(engine, conversation_id)
    if not customer_text:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "no_customer_text")
        return
    try:
        bot_runtime.wa.mark_read_with_typing(message_id=bot_runtime._inbound_wamid(engine, latest_msg_id) or "")
    except Exception:
        logger.info("whatsapp typing indicator failed job=%s", job_id, exc_info=True)

    state = bot_conversation.bot_state(conv)
    t = bot_runtime.Turn(
        job=job, job_id=job_id, conversation_id=conversation_id,
        reuse_outbound_id=reuse_outbound_id, reuse_body=reuse_body, conv=conv,
        customer_text=customer_text, latest_msg_id=latest_msg_id, state=state,
        turn_count=int(state.get("turn_count") or 0) + 1, bundle={}, guardrails={},
        temperature=0.0, max_completion_tokens=0, turn_started_at=utc_now(),
    )
    if lexicon.is_abusive(customer_text):
        bot_runtime.notify_then_escalate(engine, t, reason="Customer used abusive language — escalated to human")
        return
    max_turns = int(voice_studio.guardrails_for(state.get("studio_workflow_id")).get("maxTurns") or 20)
    if _session_current(state) and int(state.get("studio_turns") or 0) >= max_turns:
        bot_runtime.notify_then_escalate(engine, t, reason="max_turns_exceeded")
        return

    generated_for = state.get("last_trigger_message_id")
    if reuse_body and latest_msg_id and latest_msg_id == generated_for:
        t.final_text = reuse_body  # a send that never reached Meta: resend the same words
    else:
        try:
            t.final_text, wants_person = converse(conv, state, customer_text)
        except voice_studio.NotBound as exc:
            with engine.begin() as conn:
                bot_jobs.mark_dead(conn, job, str(exc))
            return
        except Exception as exc:
            logger.exception("whatsapp studio turn failed job=%s", job_id)
            with engine.begin() as conn:
                bot_jobs.mark_failed_or_retry(conn, job, f"voice_studio:{str(exc)[:500]}")
            return
        state["last_trigger_message_id"] = latest_msg_id
        bot_conversation.save_bot_state(engine, conversation_id, state)
        if wants_person:
            bot_runtime.notify_then_escalate(engine, t, reason="Customer requested a human agent")
            return
        if not t.final_text:
            bot_runtime.notify_then_escalate(engine, t, reason="voice_studio_empty_reply")
            return

    if not bot_turn_write.send_reply(engine, t):
        return
    _persist(engine, t)


def _persist(engine: Engine, t: Any) -> None:
    """Thread state, both transcript turns, the rollup, and the job's close."""
    import capture
    import capture_events

    t.state.update(
        {
            "turn_count": t.turn_count,
            "last_trigger_message_id": t.latest_msg_id,
            "last_outbound_message_id": t.msg_id,
        }
    )
    bot_conversation.save_bot_state(engine, t.conversation_id, t.state)
    ix = t.conv.get("interaction_id") or t.fresh.get("interaction_id")
    if ix:
        try:
            with engine.begin() as conn:
                started_at = capture_events.interaction_started_at(conn, ix)
                capture_events.insert_transcript_turn(
                    conn, interaction_id=ix, speaker="customer", text_content=t.customer_text,
                    at_sec=capture_events.elapsed_seconds(
                        started_at, bot_conversation.message_sent_at(conn, t.latest_msg_id)
                    ),
                )
                capture_events.insert_transcript_turn(
                    conn, interaction_id=ix, speaker="bot", text_content=t.final_text,
                    at_sec=capture_events.elapsed_seconds(started_at, utc_now()),
                )
                capture.rollup_interaction(conn, ix, channel_hint="whatsapp", force_summary=False)
        except Exception:
            logger.exception("whatsapp transcript/rollup capture failed job=%s", t.job_id)
        voice_studio.flag_turns(
            ix, {**_initial_context(t.conv), "customer_id": t.fresh.get("customer_id") or t.conv.get("customer_id"),
                 "workflow_id": t.state.get("studio_workflow_id")},
            [(t.customer_text, t.final_text, 0.0)], channel="whatsapp", start_index=t.turn_count - 1,
        )
    with engine.begin() as conn:
        bot_jobs.mark_succeeded(conn, t.job_id, outbound_message_id=t.msg_id)
    logger.info("bot_turn (voice studio) succeeded job=%s message=%s", t.job_id, t.msg_id)
