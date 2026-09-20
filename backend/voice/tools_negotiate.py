"""Voice tools -- promises to pay and disputes.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.

from agent_core.tools.catalog import (
    CATALOG,
)
from agent_core.tools import domain
from voice import persist
from voice.session import to_money

from voice.tool_state import (
    ToolBuildContext,
    _transfer_mode,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _announce = ctx._announce
    _node = ctx._node
    _require_customer = ctx._require_customer
    _schedule_context_refresh = ctx._schedule_context_refresh
    _spec = ctx._spec
    bot_id = ctx.bot_id
    rtvi = ctx.rtvi
    session = ctx.session
    state = ctx.state
    upsell_node = ctx.upsell_node



    # ---------------------------------------------------------- CRM writes

    async def _create_ptp_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Record the customer's promise to pay."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("create_promise_to_pay", args)
        try:
            amt = float(args.get("amount") or "")
        except (TypeError, ValueError):
            return {"error": "invalid_amount"}, None
        # Over-balance stays voice-side — needs session.outstanding. Compare in
        # Decimal so the 5% tolerance is exact at the boundary.
        outstanding = session.outstanding
        if amt <= 0:
            return {"error": "amount_out_of_range"}, None
        try:
            amt_dec = to_money(amt)
        except Exception:  # pragma: no cover - to_money never raises
            amt_dec = Decimal("0.00")
        if outstanding > 0 and amt_dec > outstanding * Decimal("1.05"):
            return {
                "error": "amount_out_of_range",
                "outstandingInr": float(outstanding),
            }, None

        promised_raw = str(args.get("promise_date") or "")
        promised_key = promised_raw.strip().split("T", 1)[0]
        # Stable key so retries / double tool-calls don't insert duplicate PTPs.
        #
        # Scoped to the CARRIER CALL, not the interaction row. A Twilio
        # media-stream reconnect makes ``start_voice_call`` mint a brand-new
        # interaction (voice/persist.py does a plain INSERT), so an
        # interaction-scoped key handed the same borrower commitment a
        # different key after the reconnect and inserted a second
        # money-relevant row — the one carrier event idempotency exists for.
        # ``provider_call_id`` (Twilio CallSid / SmallWebRTC call id) survives
        # the reconnect; it is unset only for local/sandbox sessions, which
        # fall back to the interaction id as before.
        #
        # The key is consumed by ``agent_core.tools.domain.create_promise_to_pay``
        # -> ``db.create_promise`` -> ``db._idempotent_response``: an exact
        # string lookup on (tenant_id, endpoint, key). Nothing parses the key,
        # so the new scope cannot collide with the old scheme — CallSids and
        # interaction ids are disjoint id spaces — and there is NO migration:
        # rows minted under the old format keep their keys, they simply stop
        # matching. The only cost is a call already in flight at deploy time,
        # whose replay would insert once more; that is the pre-existing
        # behaviour, not a regression.
        call_scope = session.provider_call_id or session.interaction_id or "no-ix"
        idem = f"voice-ptp:{call_scope}:{cid}:{amt:.2f}:{promised_key}"

        try:
            result = await asyncio.to_thread(
                domain.create_promise_to_pay,
                customer_id=cid,
                amount=amt,
                promised_date=promised_raw,
                interaction_id=session.interaction_id,
                account_id=session.account_id,
                channel="voice",
                bot_id=bot_id,
                idempotency_key=idem,
            )
            if not result.ok:
                return {
                    "error": result.error or "crm_write_failed",
                    **(result.data or {}),
                    "say": result.spoken_summary
                    or "apologise and offer a callback or human agent",
                }, None
            # Writes `promises`, which the CRM card renders under open work.
            await _announce(result, "create_promise_to_pay", inject_delta=False)
            _schedule_context_refresh("create_promise_to_pay")
            # Unlocks the upsell. Under legacy the graph enforced this by making
            # gated_upsell reachable only from here; under hub the flag is the
            # enforcement (see _check_eligibility_handler).
            state.commitment_secured = True
            return (
                {
                    "ok": True,
                    "promiseId": result.data.get("promiseId"),
                    "amount": amt,
                    "promisedDate": result.data.get("promisedDate"),
                    "confirmChannel": result.data.get("confirmChannel"),
                    "phoneLast4": result.data.get("phoneLast4"),
                    "payLinkSent": result.data.get("payLinkSent"),
                    "suppressed": result.data.get("suppressed"),
                    "say": result.spoken_summary
                    or "confirm the amount and date back to them",
                },
                # hub: stay on the hub — that is the point of merging. legacy:
                # hop to the dedicated upsell node.
                _node(upsell_node) if upsell_node else None,
            )
        except Exception as exc:
            logger.exception("create_promise failed")
            return {
                "error": "crm_write_failed",
                "detail": str(exc),
                "say": "apologise and offer a callback or human agent",
            }, None

    create_promise_to_pay = _spec("create_promise_to_pay", 
        _create_ptp_handler
    )

    async def _revise_ptp_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Move the open promise because the customer asked."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("revise_promise_to_pay", args)
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return {"error": "reason_required"}, None
        call_scope = session.provider_call_id or session.interaction_id or "no-ix"
        idem = f"voice-ptp-revise:{call_scope}:{cid}:{args.get('amount')}:{args.get('promise_date')}"
        try:
            result = await asyncio.to_thread(
                domain.revise_promise_to_pay,
                customer_id=cid,
                reason=reason,
                amount=args.get("amount"),
                promise_date=args.get("promise_date"),
                note=args.get("note"),
                interaction_id=session.interaction_id,
                account_id=session.account_id,
                idempotency_key=idem,
            )
            if not result.ok:
                return {
                    "error": result.error or "crm_write_failed",
                    **(result.data or {}),
                    "say": result.spoken_summary or "apologise and offer a callback or human agent",
                }, None
            await _announce(result, "revise_promise_to_pay", inject_delta=False)
            _schedule_context_refresh("revise_promise_to_pay")
            state.commitment_secured = True
            return {"ok": True, **(result.data or {}), "say": result.spoken_summary}, None
        except Exception as exc:
            logger.exception("revise_promise_to_pay failed")
            return {
                "error": "crm_write_failed",
                "detail": str(exc),
                "say": "apologise and offer a callback or human agent",
            }, None

    revise_promise_to_pay = _spec("revise_promise_to_pay", _revise_ptp_handler)

    async def _flag_dispute_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Flag a payment dispute for human review."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("flag_dispute", args)
        dispute_type = str(args.get("dispute_type") or "")
        amount = args.get("amount")
        # Stable key so a duplicated tool call does not open two disputes on the
        # same grievance (the plumbing already existed in domain.flag_dispute;
        # voice was the only write tool besides PTP that never passed one).
        #
        # Scoped to the CARRIER CALL, not the interaction row — same reasoning
        # as ``_create_ptp_handler`` above: a media-stream reconnect mints a new
        # interaction, so an interaction-scoped key let the reconnect re-open
        # the same grievance. ``provider_call_id`` survives the reconnect and is
        # unset only for local/sandbox sessions, which fall back to the
        # interaction id exactly as before.
        call_scope = session.provider_call_id or session.interaction_id or "no-ix"
        idem = (
            f"voice-dispute:{call_scope}:"
            f"{cid}:{dispute_type}:{'na' if amount is None else f'{float(amount):.2f}'}"
        )

        try:
            result = await asyncio.to_thread(
                domain.flag_dispute,
                customer_id=cid,
                dispute_type=dispute_type,
                interaction_id=session.interaction_id,
                account_id=session.account_id,
                amount=amount,
                summary=str(args["summary"]) if args.get("summary") else None,
                idempotency_key=idem,
            )
            if not result.ok:
                return {
                    "error": result.error or "crm_write_failed",
                    **(result.data or {}),
                    "say": result.spoken_summary
                    or "apologise and offer a callback or human agent",
                }, None
            if session.interaction_id:
                await asyncio.to_thread(
                    persist.record_handoff,
                    interaction_id=session.interaction_id,
                    reason="dispute",
                    bot_id=bot_id,
                )
            # Writes `disputes`, which the CRM card renders under open work.
            await _announce(result, "flag_dispute", inject_delta=False)
            _schedule_context_refresh("flag_dispute")
            await rtvi.handoff_status(mode=_transfer_mode(), state="queued", reason="dispute")
            return (
                {
                    "ok": True,
                    "disputeId": result.data.get("disputeId"),
                    "type": result.data.get("type"),
                    "transfer_mode": _transfer_mode(),
                    "say": "confirm the dispute is logged; a specialist will follow up",
                },
                _node("escalate_close"),
            )
        except Exception as exc:
            logger.exception("create_dispute failed")
            return {
                "error": "crm_write_failed",
                "detail": str(exc),
                "say": "apologise and offer a callback or human agent",
            }, None

    flag_dispute = _spec("flag_dispute", _flag_dispute_handler)

    return {
        "create_promise_to_pay": create_promise_to_pay,
        "revise_promise_to_pay": revise_promise_to_pay,
        "flag_dispute": flag_dispute,
    }
