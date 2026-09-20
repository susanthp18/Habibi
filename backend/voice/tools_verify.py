"""Voice tools -- identity verification.

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

from agent_core.context import CallContext
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

PREFETCH_ID_KEY = "_crm_prefetch_id"
PREFETCH_TASK_KEY = "_crm_prefetch_task"


def load_context_and_memory(
    *,
    channel: str,
    customer_id: str,
    interaction_id: str | None,
    account_id: str | None,
    session_id: str | None,
    kb_snapshot_id: str | None,
    bot_id: str | None,
    persona: dict[str, Any] | None,
) -> tuple[Any, Any]:
    """CRM spine + cross-call memory. One thread hop. Does not inject."""
    loaded = CallContext.load_for_customer(
        channel=channel,
        customer_id=customer_id,
        interaction_id=interaction_id,
        account_id=account_id,
        session_id=session_id,
        kb_snapshot_id=kb_snapshot_id,
        bot_id=bot_id,
        persona=persona,
        # The load is gated on this flag; the *injection* is gated on a
        # matching verify. Prefetch is not proof (D3: ANI identifies, last-4
        # verifies).
        identity_verified=True,
    )
    mem = None
    try:
        from voice import config as voice_config
        from voice import memory as voice_memory

        if voice_config.voice_memory():
            mem = voice_memory.load_memory(customer_id)
    except Exception:
        logger.debug("customer_memory read failed (non-fatal)", exc_info=True)
    return loaded, mem


def start_crm_prefetch(
    session: Any,
    *,
    customer_id: str,
    channel: str,
    interaction_id: str | None,
    account_id: str | None,
    kb_snapshot_id: str | None,
    bot_id: str | None,
    persona: dict[str, Any] | None,
) -> None:
    """Begin the card load for a known customer. Never injects."""
    cid = (customer_id or "").strip()
    if not cid:
        return
    drop_crm_prefetch(session)
    session.extra[PREFETCH_ID_KEY] = cid
    session.extra[PREFETCH_TASK_KEY] = asyncio.create_task(
        asyncio.to_thread(
            load_context_and_memory,
            channel=channel,
            customer_id=cid,
            interaction_id=interaction_id,
            account_id=account_id,
            session_id=session.session_id,
            kb_snapshot_id=kb_snapshot_id,
            bot_id=bot_id,
            persona=persona,
        )
    )


def drop_crm_prefetch(session: Any) -> None:
    """Forget a prefetch so a wrong-party card cannot be injected later."""
    extra = getattr(session, "extra", None)
    if not isinstance(extra, dict):
        return
    task = extra.pop(PREFETCH_TASK_KEY, None)
    extra.pop(PREFETCH_ID_KEY, None)
    if task is not None and not task.done():
        task.cancel()


async def take_crm_prefetch(session: Any, customer_id: str) -> tuple[Any, Any] | None:
    """Return the prefetched card only if it is this customer and the load worked."""
    extra = getattr(session, "extra", None)
    if not isinstance(extra, dict):
        return None
    pref_id = extra.get(PREFETCH_ID_KEY)
    task = extra.get(PREFETCH_TASK_KEY)
    if pref_id != customer_id or task is None:
        drop_crm_prefetch(session)
        return None
    try:
        result = await task
    except Exception:
        logger.debug("crm prefetch failed", exc_info=True)
        drop_crm_prefetch(session)
        return None
    extra.pop(PREFETCH_TASK_KEY, None)
    extra.pop(PREFETCH_ID_KEY, None)
    if not isinstance(result, tuple) or len(result) != 2:
        return None
    return result


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
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
    state = ctx.state

    def _outbound_leg() -> bool:
        """ANI identifies an inbound caller; it does not verify them."""
        direction = str(
            session.extra.get("call_direction") or session.extra.get("call_type") or ""
        ).strip().lower()
        if direction == "inbound":
            return False
        if direction == "outbound":
            return True
        return bool(session.extra.get("attempt_id"))


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
        prefer_customer_id: str | None = None
        # Reject hallucinated / placeholder values before burning an attempt.
        if method_n == "phone_match":
            if len(digits) < 4:
                # Outbound we already dialled this number. A first-name confirm
                # against the mission / bound customer is enough — last-4 is
                # the inbound second factor, not a ceremony we invented for
                # someone we called.
                outbound = _outbound_leg()
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
                if _outbound_leg():
                    prefer_customer_id = session.customer_id or None
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
            prefer_customer_id=prefer_customer_id,
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
            drop_crm_prefetch(session)
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
        prefetched = await take_crm_prefetch(session, match["customerId"])
        if prefetched is not None:
            ctx, mem_row = prefetched
        else:
            ctx, mem_row = await asyncio.to_thread(
                load_context_and_memory,
                channel=channel,
                customer_id=match["customerId"],
                interaction_id=ix,
                account_id=match.get("accountId"),
                session_id=session.session_id,
                kb_snapshot_id=kb_snapshot_id,
                bot_id=bot_id,
                persona=persona,
            )
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

    return {
        "verify_identity": verify_identity,
    }
