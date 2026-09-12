"""Voice tools -- callbacks, notes, non-payment reasons and contact preferences.

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
from agent_core.tools.pipecat_compat import NO_RESPONSE

from agent_core.tools.catalog import (
    CATALOG,
    NONPAYMENT_REASONS,
)
from agent_core.tools import domain

from voice.tool_state import (
    ToolBuildContext,
    HARDSHIP_UPSELL_REASONS,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _announce = ctx._announce
    _node = ctx._node
    _require_customer = ctx._require_customer
    _spec = ctx._spec
    session = ctx.session
    spoke_this_response = ctx.spoke_this_response
    state = ctx.state
    upsell_node = ctx.upsell_node


    async def _request_callback_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Schedule a callback for the verified customer."""
        cid, err = _require_customer()
        if err:
            return err, None

        args = CATALOG.normalize("request_callback", args)
        scheduled_at = str(args.get("scheduled_at") or "")
        # Raw (not parsed) scheduled_at: the key must be derivable before the
        # domain call, and an identical retry carries an identical string.
        #
        # Scoped to the CARRIER CALL, not the interaction row — see
        # ``_create_ptp_handler``. A reconnect mints a new interaction, which
        # under an interaction-scoped key booked the caller a second callback
        # for the same slot. ``provider_call_id`` survives it; sessions without
        # one fall back to the interaction id, unchanged.
        call_scope = session.provider_call_id or session.interaction_id or "no-ix"
        idem = (
            f"voice-callback:{call_scope}:"
            f"{cid}:{scheduled_at.strip()}"
        )

        try:
            result = await asyncio.to_thread(
                domain.request_callback,
                customer_id=cid,
                scheduled_at=scheduled_at,
                interaction_id=session.interaction_id,
                account_id=session.account_id,
                reason=args.get("reason"),
                window_mins=args.get("window_mins"),
                idempotency_key=idem,
            )
            if not result.ok:
                return {
                    "error": result.error or "crm_write_failed",
                    **(result.data or {}),
                    "say": result.spoken_summary
                    or "apologise and offer to try again or connect to an agent",
                }, None
            # Deliberately no _schedule_context_refresh: CallContext.open_work
            # omits callbacks on purpose (agent_core/context.py — db.get_customer
            # does not carry them, and an always-empty section would cost tokens
            # to say nothing). A refresh here would re-read the CRM and change
            # nothing, so the delta message stays instead.
            await _announce(result, "request_callback")
            # A booked callback is a commitment too — it unlocks the upsell on
            # the same terms a PTP does.
            state.commitment_secured = True
            return (
                {
                    "ok": True,
                    "callbackId": result.data.get("callbackId"),
                    "reason": result.data.get("reason"),
                    "windowMins": result.data.get("windowMins"),
                    "say": result.spoken_summary or "confirm the callback time briefly",
                },
                # hub has no wrap_up node: the hub's own task message covers
                # closing, and the model calls end_call when the caller is done.
                _node("wrap_up") if upsell_node else None,
            )
        except Exception as exc:
            logger.exception("create_callback failed")
            return {
                "error": "crm_write_failed",
                "detail": str(exc),
                "say": "apologise and offer to try again or connect to an agent",
            }, None

    request_callback = _spec("request_callback", 
        _request_callback_handler
    )

    async def _add_customer_note_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Add an internal note on the verified customer's file."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("add_customer_note", args)
        body = str(args.get("text") or "").strip()
        if not body:
            return {"error": "empty_note"}, None
        import db

        payload: dict[str, Any] = {"text": body[:2000]}
        if args.get("pinned") is not None:
            payload["pinned"] = bool(args.get("pinned"))
        try:
            await asyncio.to_thread(db.add_customer_note, cid, payload)
        except Exception as exc:
            logger.exception("add_customer_note failed")
            return {"error": "crm_write_failed", "detail": str(exc)}, None

        # A note is agent-facing; the caller never hears it. If the model
        # already acknowledged in this same response ("Right, I'll note that
        # down.") a second inference just produces filler. If it called the
        # tool silently, we still need it to say something — suppressing
        # unconditionally would leave dead air.
        if spoke_this_response is not None and spoke_this_response():
            return {"ok": True}, NO_RESPONSE
        return {"ok": True, "say": "confirm briefly that you have noted it"}, None

    add_customer_note = _spec("add_customer_note", 
        _add_customer_note_handler
    )

    # ------------------------------------------------- why they have not paid

    #: Reasons that make any product offer inappropriate until a PTP lands.
    #: Pitching to somebody who has just declared hardship is the conduct
    #: failure that ends a bank pilot, and it costs nothing to make impossible.
    _HARDSHIP_REASONS = HARDSHIP_UPSELL_REASONS

    async def _capture_nonpayment_reason_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Record why the borrower has not paid, as a code.

        The largest analytical gap in the product: the system could say an
        account was 45 DPD with two bounces and never that the borrower lost
        their job in June. The code goes on the session so the Closer can read
        it off the audit row, and `income_loss` / `medical` latch the upsell
        interlock immediately rather than at wrap-up — the offer node is
        reachable before post-call processing ever runs.
        """
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("capture_nonpayment_reason", args)
        reason = str(args.get("reason") or "").strip()
        if reason not in NONPAYMENT_REASONS:
            return {"error": "unknown_reason", "allowed": list(NONPAYMENT_REASONS)}, None

        session.extra["nonpayment_reason"] = reason
        if reason in _HARDSHIP_REASONS:
            session.extra["upsell_blocked"] = reason

        note = str(args.get("verbatim") or "").strip()
        if note:
            import db

            try:
                await asyncio.to_thread(
                    db.add_customer_note,
                    cid,
                    {"text": f"[reason: {reason}] {note[:500]}"},
                )
            except Exception:
                # The note is a convenience for a human reading the file; the
                # code is the thing that matters and it is already captured.
                logger.exception("nonpayment reason note failed")

        # Never read back to the caller. "I have recorded that you lost your
        # job" is a sentence no borrower wants to hear said back to them, and
        # the acknowledgement belongs in whatever the agent was already saying.
        if spoke_this_response is not None and spoke_this_response():
            return {"ok": True, "reason": reason}, NO_RESPONSE
        return {
            "ok": True,
            "reason": reason,
            "say": (
                "acknowledge what they said briefly and with empathy, then continue"
            ),
        }, None

    capture_nonpayment_reason = _spec(
        "capture_nonpayment_reason", _capture_nonpayment_reason_handler
    )

    async def _set_contact_preference_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Record a calling-hours restriction the borrower just stated.

        RBI para 100Y allows the statutory 08:00-19:00 window to move *"unless
        the borrower has asked otherwise"*, and the veto path has always
        intersected the statutory window with the consent one. Nothing wrote the
        consent one. So "please don't ring me before ten" was heard, agreed to,
        and then contradicted by the next morning's dial.

        ``contact_policy.narrow_window`` refuses to widen, which is why the tool
        description tells the model not to call this when a borrower says we may
        call any time: a hallucinated loosening would delete a real restriction,
        and no log line makes that acceptable.
        """
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("set_contact_preference", args)

        def _write() -> dict[str, Any]:
            import contact_policy
            import db as dbmod

            with dbmod.engine.begin() as conn:
                return contact_policy.narrow_window(
                    conn,
                    customer_id=cid,
                    earliest_hour=args.get("earliest_hour"),
                    latest_hour=args.get("latest_hour"),
                    source="voice",
                    note=str(args.get("verbatim") or "")[:500] or None,
                )

        try:
            outcome = await asyncio.to_thread(_write)
        except Exception:
            logger.exception("set_contact_preference failed")
            return {"error": "preference_not_recorded"}, None

        if not outcome.get("ok"):
            if outcome.get("reason") == "window_would_be_empty":
                # They have described a window with nothing in it, which is a
                # request to stop rather than a preference. Say so out loud and
                # let the opt-out path handle it deliberately.
                return {
                    "ok": False,
                    "reason": outcome.get("reason"),
                    "say": (
                        "check whether they would prefer we stop calling "
                        "altogether, and if so tell them you will arrange it"
                    ),
                }, None
            return {"ok": False, "reason": outcome.get("reason")}, None

        # No session breadcrumb. The durable record is the consent row plus the
        # activity line `narrow_window` writes, and a `session.extra` key that
        # nothing reads is the same species of dead configuration this whole
        # round of work exists to remove.
        window = outcome.get("window") or []
        if spoke_this_response is not None and spoke_this_response():
            return {"ok": True, "window": window}, NO_RESPONSE
        return {
            "ok": True,
            "window": window,
            "say": "confirm briefly that you have noted it, then carry on",
        }, None

    set_contact_preference = _spec(
        "set_contact_preference", _set_contact_preference_handler
    )

    return {
        "request_callback": request_callback,
        "add_customer_note": add_customer_note,
        "capture_nonpayment_reason": capture_nonpayment_reason,
        "set_contact_preference": set_contact_preference,
    }
