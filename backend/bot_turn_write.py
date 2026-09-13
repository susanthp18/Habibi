"""The write half of a text turn: persist-then-send, then the state save,
both transcript turns, the trace and the job's close. Carved out of
bot_runtime; ``Turn`` is its input.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.engine import Engine

import bot_conversation
import bot_jobs
import whatsapp as wa
from agent_core import perception
from agent_core.clock import utc_now
from agent_core.sentiment import sentiment_label

if TYPE_CHECKING:
    from bot_runtime import Turn

logger = logging.getLogger(__name__)


def send_reply(engine: Engine, t: Turn) -> bool:
    """Persist-then-send. ``t.msg_id`` and ``t.fresh`` on ``True``; ``False`` when the
    turn was cancelled at the final take-over check or the number is undeliverable."""
    job_id = t.job_id
    conversation_id = t.conversation_id
    reuse_outbound_id = t.reuse_outbound_id
    final_text = t.final_text

    # Final take-over race check immediately before persist/send.
    fresh = bot_conversation.load_conversation(engine, conversation_id)
    gate = "conversation_missing" if fresh is None else bot_conversation.policy_gate(engine, fresh)
    if fresh is None or gate:
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, gate or "conversation_missing")
        return False

    if reuse_outbound_id:
        msg_id = reuse_outbound_id
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE messages
                    SET body = :body,
                        delivery_status = 'sending',
                        provider_ref = NULL,
                        sent_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": msg_id, "body": final_text},
            )
    else:
        msg_id = bot_conversation.persist_outbound_sending(
            engine,
            conversation_id=conversation_id,
            job_id=job_id,
            body=final_text,
        )

    to_phone = wa.normalize_phone(fresh.get("phone_primary"))
    if not to_phone:
        # No deliverable number on the customer record. This is not a transport
        # failure — retrying and escalating would both be noise.
        bot_conversation.finalize_outbound(
            engine,
            message_id=msg_id,
            provider_ref=None,
            delivery_status="failed",
            customer_id=fresh.get("customer_id"),
            conversation_id=conversation_id,
            body=final_text,
        )
        with engine.begin() as conn:
            bot_jobs.mark_cancelled(conn, job_id, "missing_recipient")
        logger.warning(
            "bot_turn outbound has no recipient phone job=%s conversation=%s",
            job_id,
            conversation_id,
        )
        return False
    try:
        send_resp = wa.send_text_message(to_phone=to_phone, body=final_text)
        provider_ref = wa.extract_wamid(send_resp)
        bot_conversation.finalize_outbound(
            engine,
            message_id=msg_id,
            provider_ref=provider_ref,
            delivery_status="sent",
            customer_id=fresh.get("customer_id"),
            conversation_id=conversation_id,
            body=final_text,
        )
    except Exception as exc:
        err_str = str(exc)
        if wa.is_ambiguous_transport_error(err_str):
            # Meta may have accepted the POST. Leave the row in 'sending' so the
            # next pass takes the "stuck sending" branch and parks it for manual
            # reconciliation instead of re-POSTing a possible duplicate.
            logger.warning(
                "bot_turn outbound ambiguous transport error — leaving 'sending' "
                "for reconciliation job=%s message=%s err=%s",
                job_id,
                msg_id,
                err_str[:200],
            )
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(
                    conn, job_id, f"outbound_ambiguous_transport:{err_str[:500]}"
                )
            return False
        bot_conversation.finalize_outbound(
            engine,
            message_id=msg_id,
            provider_ref=None,
            delivery_status="failed",
            customer_id=fresh.get("customer_id"),
            conversation_id=conversation_id,
            body=final_text,
        )
        if wa.is_definite_client_error(err_str):
            with engine.begin() as conn:
                bot_jobs.mark_cancelled(conn, job_id, err_str[:2000])
            logger.warning(
                "bot_turn outbound client error (no retry) job=%s err=%s",
                job_id,
                err_str[:200],
            )
            return False
        raise RuntimeError(f"whatsapp_send_failed:{exc}") from exc

    t.fresh = fresh
    t.msg_id = msg_id
    return True


def persist_turn(engine: Engine, t: Turn) -> None:
    """The state save, both transcript turns, the trace backfill, live QA, and the job's close."""
    job_id = t.job_id
    conversation_id = t.conversation_id
    conv = t.conv
    customer_text = t.customer_text
    latest_msg_id = t.latest_msg_id
    state = t.state
    turn_count = t.turn_count
    guardrails = t.guardrails
    turn_started_at = t.turn_started_at
    understanding = t.understanding
    intent = t.intent
    intent_scores = t.intent_scores
    sentiment = t.sentiment
    final_text = t.final_text
    flow_walker = t.flow_walker
    fresh = t.fresh
    msg_id = t.msg_id

    state.update(
        {
            "turn_count": turn_count,
            "last_intent": intent,
            "last_intent_scores": intent_scores,
            "last_sentiment": sentiment_label(sentiment),
            "last_trigger_message_id": latest_msg_id,
            "last_outbound_message_id": msg_id,
        }
    )
    if flow_walker is not None and flow_walker.current is not None:
        # Where the script is, so the next inbound message resumes here rather
        # than re-greeting a thread that is four turns in.
        state["flow_node"] = flow_walker.current.key
    bot_conversation.save_bot_state(engine, conversation_id, state)

    # Phase 1 gap-fix: WhatsApp previously never wrote interaction_transcript,
    # so rollup/upsell flags could not work like voice. Persist both turns here
    # (bot_worker path — never on the webhook request).
    ix = conv.get("interaction_id") or fresh.get("interaction_id")
    if ix:
        try:
            import capture
            import capture_events

            top_score = float(intent_scores.get(intent) or 0.0) if intent_scores else None
            with engine.begin() as conn:
                # `at_sec` is the offset every timing view is keyed on, and both
                # turns were written at a literal 0 — so the entire WhatsApp
                # channel read as one instantaneous exchange while looking
                # perfectly well-formed. Stamp the customer turn from the
                # message being replied to, and the bot turn from now.
                started_at = capture_events.interaction_started_at(conn, ix)
                customer_turn_index = capture_events.insert_transcript_turn(
                    conn,
                    interaction_id=ix,
                    speaker="customer",
                    text_content=customer_text,
                    at_sec=capture_events.elapsed_seconds(
                        started_at, bot_conversation.message_sent_at(conn, latest_msg_id)
                    ),
                    sentiment_delta=float(sentiment) if sentiment is not None else None,
                    intent=intent,
                    intent_score=top_score,
                )
                # W9: the same classification, kept as provenance-tagged facts
                # instead of only as three untyped columns on the row above.
                # Written here rather than beside `analyze_turn` because this is
                # where the turn index exists — a fact keyed to a different
                # index than the transcript row joins to nothing. Records
                # nothing on a database without 0119, and never raises.
                perception.record_turn_for_interaction(
                    conn,
                    interaction_id=ix,
                    turn_index=customer_turn_index,
                    understanding=understanding,
                    turn_text=customer_text,
                    latency_ms=understanding.latency_ms,
                )
                # Let the bot turn allocate its own index too. Passing t_idx + 1
                # with ON CONFLICT DO NOTHING silently dropped the reply if any
                # other writer had taken that index; MAX()+1 inside the same
                # transaction already sees the customer turn above, so ordering
                # is preserved either way.
                capture_events.insert_transcript_turn(
                    conn,
                    interaction_id=ix,
                    speaker="bot",
                    text_content=final_text,
                    at_sec=capture_events.elapsed_seconds(started_at, utc_now()),
                )
                # Backfill this turn's tool calls and retrievals with the turn
                # they belong to. Deliberately a backfill rather than a reorder:
                # bot_tool_calls rows are written inside the tool loop, long
                # before the transcript row for the turn exists, and moving that
                # write would change the turn loop's failure semantics.
                #
                # The id is read back via a subquery, never constructed —
                # capture's canonical-id rename is savepoint-guarded and can be
                # skipped, leaving `{ix}-T-next-{uuid}` on the row.
                conn.execute(
                    text(
                        """
                        UPDATE bot_tool_calls
                           SET transcript_turn_id = (
                                 SELECT id FROM interaction_transcript
                                  WHERE interaction_id = :ix AND turn_index = :ti
                               ),
                               interaction_id = :ix,
                               channel = 'whatsapp'
                         WHERE job_id = :job_id AND transcript_turn_id IS NULL
                        """
                    ),
                    {"ix": ix, "ti": customer_turn_index, "job_id": job_id},
                )
                conn.execute(
                    text(
                        """
                        UPDATE retrieval_logs
                           SET transcript_turn_id = (
                                 SELECT id FROM interaction_transcript
                                  WHERE interaction_id = :ix AND turn_index = :ti
                               )
                         WHERE interaction_id = :ix
                           AND transcript_turn_id IS NULL
                           AND created_at >= :turn_started
                        """
                    ),
                    {"ix": ix, "ti": customer_turn_index, "turn_started": turn_started_at},
                )
                capture.rollup_interaction(conn, ix, channel_hint="whatsapp", force_summary=False)
        except Exception:
            logger.exception("whatsapp transcript/rollup capture failed job=%s", job_id)
        try:
            from agent_core.tools.gates import interaction_identity_verified
            from voice import persist as voice_persist

            voice_persist.evaluate_and_flag_bot_turn(
                interaction_id=ix,
                customer_text=customer_text,
                bot_text=final_text,
                intent=intent or "out_of_scope",
                guardrails=guardrails if isinstance(guardrails, dict) else {},
                turn_index=int(turn_count or 0),
                elapsed_seconds=0,
                customer_bot_exchanges=int(turn_count or 0),
                # A resolved sender is not a verified one -- the same rule the
                # tool gate and the authority engine already apply on this
                # channel (bot_tools._identity_verified).
                identity_verified=interaction_identity_verified(
                    interaction_id=ix, customer_id=fresh.get("customer_id")
                ),
                third_party=False,
                channel="whatsapp",
                customer_id=fresh.get("customer_id"),
            )
        except Exception:
            logger.exception("whatsapp live_qa failed job=%s", job_id)

    with engine.begin() as conn:
        bot_jobs.mark_succeeded(conn, job_id, outbound_message_id=msg_id)
    logger.info("bot_turn succeeded job=%s message=%s", job_id, msg_id)
