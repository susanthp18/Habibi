"""What each queued CrmSink job becomes in the database. The sink drains its
queue onto a thread and hands every job here; nothing in this module touches
the audio pipeline.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from pii_redact import redact_text
from voice import persist

if TYPE_CHECKING:
    from voice.crm_sink import CrmSink, _Job

logger = logging.getLogger(__name__)


def _session_waiver_cap(session: Any) -> float | None:
    extra = getattr(session, "extra", None) or {}
    raw = extra.get("max_waiver_inr")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def handle(sink: "CrmSink", job: _Job) -> None:
    """One queued job, off the audio thread: the CRM write it names."""
    p = job.payload
    if job.kind == "kb_gap":
        # Handled before the interaction_id guard below: the payload carries
        # the id the tool call actually used, and a gap is worth recording
        # even on a session whose interaction row never materialised.
        import db

        try:
            db.record_kb_gap(
                question=str(p.get("question") or ""),
                intent=p.get("intent"),
                channel=p.get("channel") or "voice",
                interaction_id=p.get("interaction_id"),
            )
        except Exception:
            logger.warning("kb gap write failed", exc_info=True)
        return

    ix = sink.session.interaction_id
    if not ix:
        sink._note_dropped(job.kind)
        return
    if job.kind == "tool_call":
        persist.record_voice_tool_call(
            interaction_id=ix,
            turn_index=int(p.get("turn_index") or 0),
            tool_name=str(p.get("tool_name") or ""),
            result_ok=bool(p.get("result_ok")),
            error=p.get("error"),
            latency_ms=p.get("latency_ms"),
            args=p.get("args") if isinstance(p.get("args"), dict) else None,
        )
        return
    if job.kind == "live_alert":
        persist.append_live_alert(
            interaction_id=ix,
            kind=str(p.get("alert_kind") or "escalation"),
            reason=str(p.get("reason") or ""),
        )
        return
    if job.kind == "live_qa_barge":
        sink._auto_barge(ix, str(p.get("reason") or "live_qa"))
        return
    if job.kind == "customer_turn":
        persist.append_transcript_turn(
            interaction_id=ix,
            turn_index=int(p["turn_index"]),
            speaker="customer",
            text_content=p["text"],
            at_sec=float(p["at_sec"]),
            sentiment_delta=float(p["score"]),
            intent=p.get("intent"),
            intent_score=p.get("intent_score"),
        )
        persist.append_sentiment_point(
            interaction_id=ix,
            at_sec=float(p["at_sec"]),
            score=float(p["score"]),
            label=p.get("label"),
        )
        if p.get("intent"):
            try:
                import capture
                import capture_events
                import db as _db

                with _db.engine.begin() as conn:
                    capture.touch_primary_intent(conn, ix, str(p["intent"]))
                    if str(p["intent"]) in capture.PRODUCT_INTENTS:
                        capture_events.record_product_interest(
                            conn,
                            interaction_id=ix,
                            intent=str(p["intent"]),
                            snippet=redact_text(str(p.get("text") or ""))[:240],
                        )
            except Exception:
                logger.exception("touch_primary_intent failed")
        persist.heartbeat(sink.session.session_id)
    elif job.kind == "bot_turn":
        persist.append_transcript_turn(
            interaction_id=ix,
            turn_index=int(p["turn_index"]),
            speaker="bot",
            text_content=p["text"],
            at_sec=float(p["at_sec"]),
            ttfb_ms=p.get("ttfb_ms"),
            ttfa_ms=p.get("ttfa_ms"),
            tokens=p.get("tokens"),
            stt_ttfb_ms=p.get("stt_ttfb_ms"),
            llm_ttfb_ms=p.get("llm_ttfb_ms"),
            tts_ttfb_ms=p.get("tts_ttfb_ms"),
            user_turn_ms=p.get("user_turn_ms"),
            tool_ms=p.get("tool_ms"),
            aggregation_ms=p.get("aggregation_ms"),
        )
        if p.get("interrupted"):
            persist.append_interaction_flag(
                interaction_id=ix,
                flag="barge_in",
                severity="low",
            )
        flags = persist.evaluate_and_flag_bot_turn(
            interaction_id=ix,
            customer_text=p.get("customer_text") or "",
            bot_text=p["text"],
            intent=p.get("intent") or "out_of_scope",
            guardrails=sink.guardrails,
            turn_index=int(p["turn_index"]),
            elapsed_seconds=float(p.get("at_sec") or 0),
            customer_bot_exchanges=int(p.get("customer_bot_exchanges") or 0),
            identity_verified=bool(sink.session.identity_verified),
            third_party=bool((sink.session.extra or {}).get("third_party")),
            channel="voice",
            customer_id=sink.session.customer_id,
            account_id=sink.session.account_id,
            max_waiver_inr=_session_waiver_cap(sink.session),
            # A rehearsal reaches no customer, and an inbound caller chose
            # the hour themselves. Without these the RBI calling-window
            # check fired on turn 1 of a 20:43 sandbox call and spent a
            # high-severity self-correction before anyone had spoken.
            direction=str(
                (sink.session.extra or {}).get("call_direction") or sink.call_direction
            ),
            simulated=sink.simulated_call,
            recording_disclosed=bool(p.get("recording_disclosed")),
        )
        sink._drain_whispers()
        if "live-qa-auto-barge" in flags:
            sink.enqueue("live_qa_barge", reason=next(
                (f for f in flags if f in {
                    "hours-breach",
                    "third-party-leak",
                    "identity-before-verify",
                    "authority-cap-exceeded",
                    "auto-escalate",
                    "opt-out-ignored",
                }),
                "live_qa",
            ))
        # The flags used to stop here, in a database row nobody reads until
        # the QA review. Hand them to the critic so the next turn can
        # actually change.
        #
        # This is deliberately a lighter trigger than the `detect_bot_loop`
        # tripwire on the enqueue side: that one needs three near-identical
        # turns at 0.92 similarity and escalates the call to a human. The
        # critic fires on two at 0.82 and merely nudges — the intent being
        # to break the loop before it earns an escalation.
        sink.enqueue_critique(
            bot_text=p["text"],
            user_text=p.get("customer_text") or "",
            guardrail_flags=flags,
            recent_bot_turns=list(p.get("prior_bot_turns") or []),
        )
        persist.heartbeat(sink.session.session_id)
    elif job.kind == "complete":
        if sink._completed:
            return
        sink._completed = True
        persist.complete_voice_call(
            session_id=sink.session.session_id,
            interaction_id=ix,
            status=str(p.get("status") or "completed"),
            latency_ms=p.get("latency_ms"),
            rag_hits=int(p.get("rag_hits") or 0),
            avg_sentiment=p.get("avg_sentiment"),
            summary=p.get("summary"),
            disposition=p.get("disposition"),
            # What actually ran, per slot, including a substituted STT
            # language -- on the interaction, not only in a log line.
            providers=sink.session.extra.get("providers") or None,
        )
        # Off audio path — serialize turns after CRM close.
        try:
            exported = persist.export_transcript_json(
                interaction_id=ix,
                session_id=sink.session.session_id,
            )
            if exported:
                logger.info(
                    "transcript export · interaction=%s · media=%s · turns=%s",
                    ix,
                    exported.get("mediaId"),
                    exported.get("turnCount"),
                )
        except Exception:
            logger.exception("transcript export failed · interaction=%s", ix)

        try:
            from voice.redaction_export import ensure_redaction_record

            ensure_redaction_record(ix)
        except Exception:
            logger.exception("redaction record upsert failed · interaction=%s", ix)

        # Cross-call memory. Deliberately AFTER complete_voice_call, in its
        # own try/except, so a slow or failing summariser can never block
        # call closure. This whole handler already runs in asyncio.to_thread
        # off the audio path, and azure_openai.chat_complete is synchronous,
        # so there is nothing to await here.
        sink._write_customer_memory(ix, p)
    elif job.kind == "heartbeat":
        persist.heartbeat(sink.session.session_id)
