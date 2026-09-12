"""Voice tools -- greet, disclose, verify: who is on the line.

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
from agent_core.tools.pipecat_compat import flows_tool_options

from agent_core.context import CallContext
from agent_core.intent import NON_GOAL_INTENTS
from agent_core.tools.catalog import (
    CATALOG,
)
from voice import persist
from voice.names import first_names_match
from voice.session import to_money

from voice.tool_state import (
    ToolBuildContext,
    _VERIFY_METHODS,
    _account_tail,
    _transfer_mode,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _FALLBACK_GREETING = ctx._FALLBACK_GREETING
    _node = ctx._node
    _spec = ctx._spec
    bot_id = ctx.bot_id
    channel = ctx.channel
    hub_node = ctx.hub_node
    inject_developer = ctx.inject_developer
    kb_snapshot_id = ctx.kb_snapshot_id
    persona = ctx.persona
    rtvi = ctx.rtvi
    session = ctx.session
    spoke_this_response = ctx.spoke_this_response
    start_recording = ctx.start_recording
    state = ctx.state


    @flows_tool_options(cancel_on_interruption=False)
    async def disclose_recording(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Confirm the recording disclosure was spoken to the caller.

        Call this immediately after stating that the call is being recorded.
        """
        ix = session.interaction_id
        if not ix:
            return {"error": "no_interaction"}, None
        # This tool asserts that the caller HEARD the disclosure, and that
        # assertion becomes a compliance record. The model is supposed to speak
        # the greeting in the same reply as the call, and usually does — but on
        # VS-18FE21E37A it emitted the tool call with no text at all. Nothing
        # was said, the next node was listen-first, and the call sat mute for 77
        # seconds while the database recorded a disclosure that never happened.
        #
        # So say it here. This is the opening turn of a phone call: there is no
        # caller utterance to fall back on and no later turn that repairs it,
        # which makes it the one place a scripted line is more trustworthy than
        # an instruction.
        if spoke_this_response is not None and not spoke_this_response():
            # Same handle pause_for_caller speaks through — the FlowManager does
            # not expose the pipeline task directly.
            worker = getattr(flow_manager, "worker", None) or getattr(
                flow_manager, "_worker", None
            )
            if worker is None:
                logger.error("no worker to speak through — call will open silent")
            else:
                from pipecat.frames.frames import TTSSpeakFrame

                logger.warning(
                    "greeting was silent — model called disclose_recording without "
                    "speaking; delivering the disclosure directly"
                )
                try:
                    await worker.queue_frame(
                        TTSSpeakFrame(_FALLBACK_GREETING, append_to_context=False)
                    )
                except TypeError:
                    await worker.queue_frame(TTSSpeakFrame(_FALLBACK_GREETING))
                except Exception:
                    logger.exception("fallback greeting failed — call may open silent")
        if not state.disclosure_done:
            await asyncio.to_thread(
                persist.record_disclosure,
                interaction_id=ix,
                label="Recording disclosure",
                rule_id="rule-recording",
                read_at_sec=session.at_sec(),
                bot_id=bot_id,
            )
            state.disclosure_done = True
            # Close the loop deterministically rather than hoping the prompt
            # holds. The obligation is once-per-call, the tool is the moment it
            # is satisfied, and a standing developer note is the only signal
            # that survives every later node transition and context summary.
            # Without it a call disclosed at the greeting and then said it
            # twice more, four minutes apart (VS-92CDE3F088).
            if inject_developer is not None:
                try:
                    await inject_developer(
                        [
                            {
                                "role": "developer",
                                "content": (
                                    "The recording disclosure has been made and "
                                    "logged for this call. It is satisfied. Never "
                                    "state, repeat or re-confirm that the call is "
                                    "recorded again for the rest of this call, "
                                    "even if an instruction elsewhere says to "
                                    "always disclose it."
                                ),
                            }
                        ]
                    )
                except Exception:
                    logger.debug("disclosure note injection failed", exc_info=True)
            if start_recording is not None:
                try:
                    await start_recording()
                except Exception:
                    logger.exception("start_recording failed (non-fatal)")
        await rtvi.lifecycle(phase="disclosed", reason="recording_disclosure")
        # discover_intent asks what the caller needs before the verification
        # ceremony. `or _node("verify_identity")` is not defensive noise: a
        # caller that built tools with an older node registry would otherwise
        # get None back from _node and strand the call on the greeting.
        return {"ok": True, "disclosed": True}, (
            _node("discover_intent") or _node("verify_identity")
        )

    async def _capture_call_goal_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        args = CATALOG.normalize("capture_call_goal", args)
        goal = str(args.get("goal_summary") or "").strip()
        if not goal:
            return (
                {"error": "empty_goal", "say": "ask what they need, then call again"},
                None,
            )
        goal = goal[:200]

        # Intent classification, best available *now*. The LLM understanding for
        # this turn runs on the CrmSink analysis queue and usually lands a turn
        # or two later — _handle_understanding upgrades call_goal_intent when it
        # does. Until then the keyword baseline stands, which is the same
        # keyword-first / LLM-refines contract analyze_turn uses internally.
        intent: str | None = None
        try:
            from agent_core.understanding import keyword_understanding

            cached = session.understanding
            if cached is not None and session.understanding_turn_index >= session.turn_index:
                intent = getattr(cached, "intent", None)
            else:
                intent = keyword_understanding(goal).intent
        except Exception:
            logger.debug("call goal intent classification failed", exc_info=True)

        # A question about the call is not a reason for the call. Reuse the
        # classifier already running on every turn rather than pattern-matching
        # the phrasing: whatever it labels as meta stays unrecorded, the model
        # answers it, and discover_intent keeps listening for the real reason.
        if intent in NON_GOAL_INTENTS:
            return (
                {
                    "ok": False,
                    "reason": "not_a_call_goal",
                    "intent": intent,
                    "say": (
                        "answer their question directly, then ask what they "
                        "actually need help with today"
                    ),
                },
                None,
            )

        session.call_goal = goal
        session.call_goal_intent = intent
        session.call_goal_turn_index = session.turn_index

        await rtvi.lifecycle(phase="goal_captured", reason=goal)
        return (
            {"ok": True, "goal": goal, "say": "acknowledge briefly, then verify them"},
            _node("verify_identity"),
        )

    capture_call_goal = _spec("capture_call_goal", _capture_call_goal_handler)

    # ------------------------------------------------------------- identity

    async def _verify_identity_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Verify caller identity before any account details are shared."""
        ix = session.interaction_id
        if not ix:
            return {"error": "no_interaction"}, None

        # Re-entry guard. Nothing stopped an already-verified caller from
        # reaching this handler again — a model that re-asks for digits, an STT
        # mishear the caller corrects, a hop back through the verify node — and
        # every re-entry burned an attempt. Three of them routed a borrower who
        # had *already passed* verification to terminate_politely with a
        # `verification_failed` handoff: a hang-up on a verified customer.
        # An identity that is bound to this interaction is settled; re-asserting
        # it costs nothing and must never cost an attempt.
        if session.identity_verified and session.customer_id:
            return (
                {
                    "ok": True,
                    "alreadyVerified": True,
                    "verified": True,
                    "customerName": state.customer_name,
                    "attempts": state.verify_attempts,
                    "say": "confirm they are already verified and continue",
                },
                _node(hub_node),
            )

        args = CATALOG.normalize("verify_identity", args)
        method_n = str(args.get("method") or "").strip().lower()
        value = str(args.get("value") or "")
        if method_n not in _VERIFY_METHODS:
            return {
                "error": "unsupported_method",
                "allowed": list(_VERIFY_METHODS),
            }, None

        raw = value.strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        lookup_method = method_n
        lookup_value = value
        # Reject hallucinated / placeholder values before burning an attempt.
        if method_n == "phone_match":
            if len(digits) < 4:
                # Outbound we already dialled this number. A first-name confirm
                # against the mission / bound customer is enough — last-4 is
                # the inbound second factor, not a ceremony we invented for
                # someone we called.
                outbound = session.extra.get("call_direction") == "outbound" or bool(
                    session.extra.get("attempt_id")
                )
                mission = session.extra.get("mission")
                mission = mission if isinstance(mission, dict) else {}
                expected = (
                    state.customer_name
                    or session.extra.get("expected_customer_name")
                    or mission.get("customerName")
                    or mission.get("firstName")
                )
                bound_id = session.customer_id or mission.get("customerId")
                if (
                    outbound
                    and expected
                    and bound_id
                    and first_names_match(raw, str(expected))
                ):
                    lookup_method = "manual"
                    lookup_value = str(bound_id)
                else:
                    return {
                        "ok": False,
                        "error": "need_digits",
                        "hint": "ask_caller_for_last_4_mobile_digits",
                        "say": "ask only for the last 4 digits of their registered mobile",
                    }, None
            else:
                lookup_value = digits[-10:] if len(digits) > 10 else digits
        elif method_n == "account_tail":
            if len(digits) < 4 and len(raw) < 4:
                return {
                    "ok": False,
                    "error": "need_account_tail",
                    "hint": "ask_caller_for_last_4_of_account",
                    "say": "ask for the last 4 digits of their account number",
                }, None
            lookup_value = digits[-4:] if len(digits) >= 4 else raw

        state.verify_attempts += 1
        match = await asyncio.to_thread(
            persist.lookup_customer_for_verify,
            method=lookup_method,
            value=lookup_value,
        )
        if not match:
            await asyncio.to_thread(
                persist.record_identity_verification,
                interaction_id=ix,
                customer_id=session.customer_id or persist.unknown_caller_id(),
                method=method_n,
                status="failed",
                attempt_count=state.verify_attempts,
                failure_reason="no_match",
            )
            if state.verify_attempts >= 3:
                await asyncio.to_thread(
                    persist.record_handoff,
                    interaction_id=ix,
                    reason="verification_failed",
                    bot_id=bot_id,
                )
                await rtvi.handoff_status(
                    mode=_transfer_mode(), state="queued", reason="verification_failed"
                )
                return (
                    {
                        "ok": False,
                        "attempts": state.verify_attempts,
                        "error": "verification_failed_max_attempts",
                        "say": "apologise — you cannot share details without verification",
                    },
                    _node("terminate_politely"),
                )
            return (
                {
                    "ok": False,
                    "attempts": state.verify_attempts,
                    "remaining": 3 - state.verify_attempts,
                    "error": "no_match",
                    "say": "say the digits did not match and ask them to try again",
                },
                None,
            )

        await asyncio.to_thread(
            persist.bind_customer_to_interaction,
            interaction_id=ix,
            customer_id=match["customerId"],
            account_id=match.get("accountId"),
        )
        await asyncio.to_thread(
            persist.record_identity_verification,
            interaction_id=ix,
            customer_id=match["customerId"],
            method=method_n,
            status="verified",
            attempt_count=state.verify_attempts,
        )
        session.customer_id = match["customerId"]
        session.account_id = match.get("accountId")
        session.identity_verified = True

        # Right-party contact, recorded against the dial that produced it.
        # RPC rate is the metric every collections floor actually manages and
        # the product had no way to compute it: the only evidence a verification
        # ever happened lived on the interaction, and an interaction only exists
        # once media connects. On an outbound leg the attempt is the thing being
        # measured, so the fact belongs there too.
        #
        # Fire-and-forget: a bookkeeping write must never fail a verification
        # the caller has already passed.
        _attempt = session.extra.get("attempt_id")
        if _attempt:

            def _mark_rpc() -> None:
                import db as _db
                import outbound as _outbound

                with _db.engine.begin() as conn:
                    _outbound.mark(conn, str(_attempt), right_party=True, answered_by="human")

            try:
                await asyncio.to_thread(_mark_rpc)
            except Exception:
                logger.debug("right-party mark failed", exc_info=True)
        session.outstanding = to_money(match.get("outstanding"))
        state.minimum_due = match.get("minimumDue")
        state.dpd = match.get("dpd")
        state.customer_name = match.get("name")

        # Load the CRM spine once, then inject it as a developer card so the
        # model stops having to call get_account_position to know basic facts
        # (unification plan §3 injection rule 2).
        #
        # Cross-call memory is read in the SAME thread hop: it is one extra
        # query against an already-open pool, and a second to_thread would add a
        # round-trip class to the verification turn for no benefit.
        def _load_context_and_memory():
            loaded = CallContext.load_for_customer(
                channel=channel,
                customer_id=match["customerId"],
                interaction_id=ix,
                account_id=match.get("accountId"),
                session_id=session.session_id,
                kb_snapshot_id=kb_snapshot_id,
                bot_id=bot_id,
                persona=persona,
                # Set before the load, not after: load_for_customer only reads
                # the CRM for a verified identity.
                identity_verified=True,
            )
            mem = None
            try:
                from voice import config as voice_config
                from voice import memory as voice_memory

                if voice_config.voice_memory():
                    mem = voice_memory.load_memory(match["customerId"])
            except Exception:
                logger.debug("customer_memory read failed (non-fatal)", exc_info=True)
            return loaded, mem

        ctx, mem_row = await asyncio.to_thread(_load_context_and_memory)
        state.call_context = ctx
        if inject_developer:
            try:
                # Ordering is load-bearing: the authoritative CRM card first,
                # the background memory second — and the memory block's own
                # header says the card wins in any conflict.
                messages = [ctx.crm_card_message()]
                if mem_row is not None:
                    from voice import config as voice_config
                    from voice import memory as voice_memory

                    mem_msg = voice_memory.memory_message(
                        mem_row, max_age_days=voice_config.voice_memory_max_age_days()
                    )
                    if mem_msg:
                        messages.append(mem_msg)
                await inject_developer(messages)
            except Exception:
                logger.exception("CRM card injection failed (non-fatal)")
        await rtvi.lifecycle(phase="verified", reason=method_n)
        await rtvi.identity_verified(
            customer_name=match.get("name"),
            customer_id=session.customer_id,
            method=method_n,
        )
        await rtvi.context_card(ctx.crm_card())

        result: dict[str, Any] = {
            "ok": True,
            "customerName": match.get("name"),
            "verified": True,
            "say": "acknowledge verification briefly, then continue",
        }
        tail = match.get("accountTail") or _account_tail(match.get("accountId"))
        if tail:
            result["accountTail"] = tail
        return result, _node(hub_node)

    verify_identity = _spec("verify_identity", _verify_identity_handler)

    @flows_tool_options(cancel_on_interruption=False)
    async def refuse_verification(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Caller refuses to verify identity, or says they are not the account holder.

        After two refusals, or if they are a third party, end politely.
        """
        state.verify_refusals += 1
        ix = session.interaction_id
        if state.verify_refusals >= 2:
            if ix:
                await asyncio.to_thread(
                    persist.record_handoff,
                    interaction_id=ix,
                    reason="verification_failed",
                    bot_id=bot_id,
                )
            return (
                {
                    "ok": False,
                    "refused": True,
                    "say": "explain verification is required and end politely",
                },
                _node("terminate_politely"),
            )
        return (
            {
                "ok": False,
                "refused": True,
                "remaining_refusals": 1,
                "say": (
                    "briefly explain why verification is required for account "
                    "privacy, then ask again for last 4 mobile digits"
                ),
            },
            None,
        )

    @flows_tool_options(cancel_on_interruption=False)
    async def not_account_holder(flow_manager) -> tuple[Any, dict[str, Any] | None]:
        """Caller says they are not the account holder / third party."""
        session.extra["third_party"] = True
        # The other half of right-party contact. An attempt that reached a
        # human who is not the borrower is fully paid for and worth zero, and
        # until the two were told apart every connect looked like a success.
        _attempt = session.extra.get("attempt_id")
        if _attempt:

            def _mark_wrong_party() -> None:
                import db as _db
                import outbound as _outbound

                with _db.engine.begin() as conn:
                    _outbound.mark(conn, str(_attempt), right_party=False, answered_by="human")

            try:
                await asyncio.to_thread(_mark_wrong_party)
            except Exception:
                logger.debug("wrong-party mark failed", exc_info=True)
        ix = session.interaction_id
        if ix:
            await asyncio.to_thread(
                persist.record_handoff,
                interaction_id=ix,
                reason="verification_failed",
                bot_id=bot_id,
            )
        # Inbound and outbound end differently, and the difference matters.
        # Inbound: a stranger rang *us* about someone else's account, so
        # "I can only discuss this with the holder" is the whole answer.
        # Outbound: we rang *them*, and this person now knows a bank called
        # about a specific individual. Saying we can only discuss "the account"
        # has already confirmed there is one. The third_party node exists to say
        # materially less than that.
        outbound_leg = str(session.extra.get("objective") or "").strip() != ""
        landing = _node("third_party") if outbound_leg else None
        return (
            {
                "ok": True,
                "thirdParty": True,
                "say": (
                    "do not confirm or deny that an account exists; say only that "
                    "it is a personal matter for the account holder"
                    if outbound_leg
                    else "explain you can only discuss the account with the holder; "
                    "suggest the holder call from their registered number"
                ),
            },
            landing or _node("terminate_politely"),
        )

    return {
        "disclose_recording": disclose_recording,
        "capture_call_goal": capture_call_goal,
        "verify_identity": verify_identity,
        "refuse_verification": refuse_verification,
        "not_account_holder": not_account_holder,
    }
