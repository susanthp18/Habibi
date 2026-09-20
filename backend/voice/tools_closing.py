"""Voice tools -- pausing and escalating to a human.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.
from agent_core.tools.pipecat_compat import NO_RESPONSE, flows_tool_options

from agent_core.tools.catalog import (
    CATALOG,
)

from voice.tool_state import (
    ToolBuildContext,
    _transfer_mode,
)

logger = logging.getLogger(__name__)


def compliance_inbox_flag(detail: str | None, last_customer_text: str | None) -> str:
    """Inbox flag for a ``compliance`` escalation.

    The last utterance is often "okay" after the legal threat; the tool detail
    (``legal_mention`` / ``abuse_detected``) is what actually fired.
    """
    from agent_core import lexicon

    detail_l = str(detail or "").lower()
    last = str(last_customer_text or "").lower()
    if "legal" in detail_l or lexicon.is_legal_threat(last):
        return "legal-threat"
    if "abuse" in detail_l or lexicon.is_abusive(last):
        return "abusive-language"
    return "compliance"


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _node = ctx._node
    _sink_call = ctx._sink_call
    _spec = ctx._spec
    bot_id = ctx.bot_id
    rtvi = ctx.rtvi
    session = ctx.session
    sink = ctx.sink
    state = ctx.state


    # ----------------------------------------------------------- call control

    @flows_tool_options(cancel_on_interruption=False)
    async def pause_for_caller(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Caller asked to hold / wait a moment.

        Acknowledges, then relaxes the user-idle timeout so the silence ladder
        does not nudge them while they are away (docs: UserIdleTimeoutUpdateFrame).
        """
        from pipecat.frames.frames import TTSSpeakFrame, UserIdleTimeoutUpdateFrame

        worker = getattr(flow_manager, "worker", None) or getattr(flow_manager, "_worker", None)
        session.extra["on_hold"] = True
        if worker is not None:
            try:
                await worker.queue_frame(
                    TTSSpeakFrame("Of course, take your time.", append_to_context=False)
                )
            except TypeError:
                await worker.queue_frame(TTSSpeakFrame("Of course, take your time."))
            # Relax idle while they are away (edge #17).
            await worker.queue_frame(UserIdleTimeoutUpdateFrame(timeout=45.0))
        # NO_RESPONSE, not None. This tool has already SAID "Of course, take
        # your time." — a second inference here produces something to say over
        # the top of that, on a turn whose entire purpose is silence. Returning
        # NO_RESPONSE in the next-node slot keeps the current node and completes
        # the call with run_llm=False (pipecat flows/manager.py).
        #
        # NO_RESPONSE is mutually exclusive with transitioning: it OCCUPIES the
        # next-node slot. That is why the begin_* hops cannot use it, whatever
        # the plan document says — for those, NodeConfig.respond_immediately is
        # the equivalent control.
        return {
            "ok": True,
            "holding": True,
            "say": "wait quietly until they return; do not ask new questions yet",
        }, NO_RESPONSE

    async def _escalate_to_human_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Queue a human agent (Inbox) or warm-transfer on Twilio PSTN.

        Default ``VOICE_HANDOFF_MODE=callback_queue``: open an Inbox thread and
        tell the model a human will CALL BACK — never "connecting you now".

        When mode is ``warm`` and ``session.extra.call_sid`` is set (Twilio),
        redirect the live call into a conference and dial SUPERVISOR_CALLBACK_PHONE.
        """
        args = CATALOG.normalize("escalate_to_human", args)
        session.extra.pop("escalate_nudge_pending", None)
        # The spec marks reason required, but escalation is the one path that
        # must never fail closed on a missing argument — an un-escalated abusive
        # or legal-threat call is worse than a mis-labelled one.
        reason = str(args.get("reason") or "customer_requested")
        detail = args.get("detail")
        if state.escalated:
            # A second call on the same call -- the model repeating itself, or
            # a retried tool turn -- must not open a second Inbox thread, file
            # a second handoff or dial the supervisor twice. The first one is
            # in motion; say so and stay on the closing node.
            return {
                "ok": True,
                "escalated": True,
                "already_escalated": True,
                "reason": reason,
                "say": "the handoff is already in motion; reassure briefly and stop talking",
            }, _node("escalate_close")
        # Suppresses the offer engine and the close probe for the rest of the
        # call. Pitching a product to someone being handed to a human — usually
        # because they are angry or have threatened legal action — turns a
        # complaint into a regulatory one.
        state.escalated = True
        if "hardship" in reason.lower():
            session.extra["upsell_blocked"] = "hardship"
        ix = session.interaction_id
        assignee_name: str | None = None
        team_name: str | None = None
        conversation_id: str | None = None
        mode = _transfer_mode()
        call_sid = (session.extra or {}).get("call_sid")
        warm_ok = mode == "warm" and bool(call_sid)

        if ix:
            # One DB round-trip: handoff + note + routing + inbox + live alert.
            try:
                import db

                card = (state.call_context.customer_card if state.call_context else {}) or {}
                dpd_raw = state.dpd
                if dpd_raw is None:
                    dpd_raw = card.get("dpd")
                try:
                    dpd_val = int(dpd_raw or 0)
                except (TypeError, ValueError):
                    dpd_val = 0

                product_val = card.get("product") or "PL"

                avg = None
                if sink is not None and hasattr(sink, "current_avg_sentiment"):
                    try:
                        avg = sink.current_avg_sentiment()
                    except Exception:
                        avg = None
                sentiment = "neutral"
                if avg is not None:
                    try:
                        avg_f = float(avg)
                        if avg_f <= -0.35:
                            sentiment = "angry"
                        elif avg_f < 0:
                            sentiment = "frustrated"
                        elif avg_f >= 0.25:
                            sentiment = "positive"
                    except (TypeError, ValueError):
                        pass

                route_ctx = {
                    "channel": "voice",
                    "intent": (reason or "customer_requested").strip().lower(),
                    "sentiment": sentiment,
                    "verification_status": (
                        "verified" if session.identity_verified else "failed"
                    ),
                    "overdue_amount": float(session.outstanding),
                    "turn_count": int(session.turn_index or 0),
                    "guardrail_flag": (detail or "none"),
                    "consent_dnd": bool(card.get("dnd")),
                    "dpd": dpd_val,
                    "product": product_val,
                }
                # `reason` is CATALOG-normalised to ESCALATION_REASONS above;
                # this used to branch on "abuse", "legal", "angry" and
                # "verify_failed" too, which the enum cannot produce, so those
                # arms were unreachable and the routing they described never
                # happened. The lexicon decides which compliance flag it was.
                reason_l = (reason or "").lower()
                if reason_l == "hardship":
                    route_ctx["intent"] = "hardship"
                elif reason_l == "dispute":
                    route_ctx["intent"] = "dispute"
                elif reason_l == "compliance":
                    last = str(_sink_call("last_customer_text", "") or "")
                    route_ctx["guardrail_flag"] = compliance_inbox_flag(detail, last)
                elif reason_l == "sentiment_drop":
                    route_ctx["sentiment"] = "angry"
                elif reason_l in {"verification_failed", "verify_failed"}:
                    route_ctx["verification_status"] = "failed"
                    route_ctx["turn_count"] = max(4, int(route_ctx["turn_count"]))

                note = None
                if detail and session.identity_verified and session.customer_id:
                    note = f"[escalation] {detail}"[:2000]

                esc = await asyncio.to_thread(
                    db.escalate_voice_interaction,
                    interaction_id=ix,
                    reason=reason,
                    bot_id=bot_id,
                    customer_id=session.customer_id,
                    note_text=note,
                    route_context=route_ctx,
                )
                assignee_name = esc.get("assigneeName")
                team_name = esc.get("teamName")
                conversation_id = esc.get("conversationId")
            except Exception:
                logger.exception("escalate routing/inbox failed (non-fatal)")

        warm_meta: dict[str, Any] = {}
        if warm_ok:
            try:
                from voice import telephony

                warm_meta = await asyncio.to_thread(
                    telephony.warm_transfer,
                    str(call_sid),
                    reason=reason,
                )
                mode = "warm"
            except Exception:
                logger.exception("warm transfer failed — falling back to callback_queue")
                mode = "callback_queue"
                warm_ok = False

        await rtvi.handoff_status(
            mode=mode,
            state="bridged" if warm_ok else "queued",
            reason=reason,
            assignee=assignee_name,
            team=team_name,
            conversation_id=conversation_id,
        )
        await rtvi.lifecycle(phase="escalating", reason=reason)
        who = assignee_name or team_name
        if warm_ok:
            say = (
                "tell the caller you are connecting them to a human agent now; "
                "keep it to one short sentence, then stop talking"
            )
        else:
            say = (
                "reassure briefly that a human agent will CALL THEM BACK — do not "
                "say you are connecting or transferring them now"
            )
            if who:
                say = (
                    f"reassure briefly that {who} will CALL THEM BACK — do not "
                    "say you are connecting or transferring them now"
                )
        return {
            "ok": True,
            "escalated": True,
            "reason": reason,
            "transfer_mode": mode,
            "assignee": assignee_name,
            "team": team_name,
            "conversationId": conversation_id,
            **({"warm": warm_meta} if warm_meta else {}),
            "say": say,
        }, _node("escalate_close")

    escalate_to_human = _spec("escalate_to_human",
        _escalate_to_human_handler
    )

    return {
        "pause_for_caller": pause_for_caller,
        "escalate_to_human": escalate_to_human,
    }
