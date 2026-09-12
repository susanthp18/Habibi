"""Voice tools -- promises, disputes, authority, callbacks, notes, preferences.

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
from agent_core.tools.pipecat_compat import NO_RESPONSE

from agent_core.tools.catalog import (
    CATALOG,
    NONPAYMENT_REASONS,
)
from agent_core.tools import domain
from voice import persist
from voice.session import to_money

from voice.tool_state import (
    ToolBuildContext,
    HARDSHIP_UPSELL_REASONS,
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
    spoke_this_response = ctx.spoke_this_response
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
            amt = float(args.get("amount"))
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
            # Hardship still latches the pitch until they commit — that is the
            # conduct rule. Once a PTP is on the book the offer node may run.
            # Mission-level forbids stay; those are not hardship.
            if session.extra.get("upsell_blocked") in HARDSHIP_UPSELL_REASONS:
                session.extra.pop("upsell_blocked", None)
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

    async def _evaluate_authority_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("evaluate_authority", args)
        try:
            result = await asyncio.to_thread(
                domain.evaluate_authority,
                customer_id=cid,
                fee_type=str(args.get("fee_type") or "late_fee"),
                asked_amount=args.get("asked_amount"),
                interaction_id=session.interaction_id,
                account_id=session.account_id,
                identity_verified=True,
            )
        except Exception:
            logger.exception("evaluate_authority failed")
            return {
                "verdict": "escalate",
                "suppressed": True,
                "apply": False,
                "say": "do not quote a waiver or settlement figure; escalate",
            }, None
        payload = dict(result.data or {})
        cap = payload.get("approvedAmount") or payload.get("capAmount")
        try:
            state.authority_cap = float(cap) if cap is not None else None
        except (TypeError, ValueError):
            state.authority_cap = None

        # The mission's authority profile, applied on top. The matrix decides
        # what policy permits for this account; the profile is a second and
        # narrower bound this particular call was sent out under — a pre-due
        # courtesy call has no business conceding what a broken-promise chase
        # might. It can only ever lower, which is what stops a card authoring
        # itself more discretion than the matrix would grant.
        #
        # The in-memory payload is what the Mouth quotes. apply_goodwill re-reads
        # approved_amount from the row, so the ceiling has to land there too
        # or a pre-due courtesy Mission posts the un-narrowed matrix figure.
        _mission = session.extra.get("mission")
        _profile = (_mission or {}).get("authorityProfile") if isinstance(_mission, dict) else None
        if _profile and state.authority_cap is not None:
            from agent_core.authority import config as _authority_config
            from agent_core.authority import decisions as _authority_decisions

            ceiling = _authority_config.profile_ceiling(_profile)
            if ceiling is not None and ceiling < state.authority_cap:
                decision_id = payload.get("decisionId")
                if decision_id:
                    try:
                        await asyncio.to_thread(
                            _authority_decisions.bind_ceiling,
                            str(decision_id),
                            ceiling=ceiling,
                            profile=_profile,
                        )
                    except Exception:
                        logger.exception(
                            "authority mission ceiling persist failed for %s",
                            decision_id,
                        )
                        return {
                            "verdict": "escalate",
                            "suppressed": True,
                            "apply": False,
                            "say": (
                                "do not quote a waiver or settlement figure; escalate"
                            ),
                        }, None
                logger.info(
                    "authority narrowed by mission profile %s: %s -> %s",
                    _profile,
                    state.authority_cap,
                    ceiling,
                )
                state.authority_cap = ceiling
                payload["approvedAmount"] = ceiling
                payload["capAmount"] = ceiling
                payload["narrowedBy"] = _profile
                if ceiling <= 0:
                    payload["verdict"] = "escalate"
                    payload["say"] = (
                        "do not quote any waiver or settlement figure on this "
                        "call; offer to have a colleague call them back"
                    )
        if state.authority_cap is not None:
            session.extra["max_waiver_inr"] = state.authority_cap
        if result.spoken_summary:
            payload.setdefault("say", result.spoken_summary)
        await _announce(result, "evaluate_authority", inject_delta=False)
        # Snapshot lands on the CRM card so later turns cannot invent a larger figure.
        _schedule_context_refresh("evaluate_authority")
        return payload, None

    evaluate_authority = _spec("evaluate_authority", _evaluate_authority_handler)

    async def _apply_goodwill_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("apply_goodwill", args)
        # The decision id comes from the model's own call, never from a slot
        # on the session: under run_in_parallel two evaluate_authority calls
        # overwrote one slot, and the second waiver posted against the first
        # verdict. The spec marks it required; the model has it because it
        # was the one that received it.
        decision_id = str(args.get("decision_id") or "")
        if not decision_id:
            return {
                "error": "missing_decision",
                "say": "call evaluate_authority before applying goodwill",
            }, None
        try:
            result = await asyncio.to_thread(
                domain.apply_goodwill,
                decision_id=decision_id,
                amount=args.get("amount"),
            )
        except Exception:
            logger.exception("apply_goodwill failed")
            return {
                "error": "crm_write_failed",
                "say": "apologise and offer a specialist callback",
            }, None
        if not result.ok:
            return {
                "error": result.error or "apply_failed",
                "say": result.spoken_summary
                or "do not confirm a waiver; offer a specialist callback",
            }, None
        await _announce(result, "apply_goodwill", inject_delta=False)
        _schedule_context_refresh("apply_goodwill")
        return {
            "ok": True,
            **(result.data or {}),
            "say": result.spoken_summary or "confirm the goodwill reversal briefly",
        }, None

    apply_goodwill = _spec("apply_goodwill", _apply_goodwill_handler)

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
        "create_promise_to_pay": create_promise_to_pay,
        "flag_dispute": flag_dispute,
        "evaluate_authority": evaluate_authority,
        "apply_goodwill": apply_goodwill,
        "request_callback": request_callback,
        "add_customer_note": add_customer_note,
        "capture_nonpayment_reason": capture_nonpayment_reason,
        "set_contact_preference": set_contact_preference,
    }
