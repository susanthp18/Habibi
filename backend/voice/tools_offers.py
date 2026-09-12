"""Voice tools -- eligibility, offers, the close probe, leads, documents.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.
from agent_core.tools.pipecat_compat import NO_RESPONSE

from agent_core.tools import ToolResult
from agent_core.tools.catalog import (
    CATALOG,
    DOCUMENT_TYPES,
)
from agent_core.tools import domain

from voice.tool_state import (
    ToolBuildContext,
    _PROBE_SENTIMENT_FLOOR,
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
    session = ctx.session
    sink = ctx.sink
    spoke_this_response = ctx.spoke_this_response
    state = ctx.state
    upsell_node = ctx.upsell_node


    # --------------------------------------------------------------- upsell

    async def _check_eligibility_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Evaluate upsell eligibility against live account state."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("check_product_eligibility", args)
        product_id = str(args.get("product_id") or "").strip()
        if not product_id:
            return {"error": "product_id_required"}, None

        # This tool re-confirms an offer the engine already made; it cannot be
        # used to shop for one.
        violation = domain.offer_sourcing_violation(product_id, state.offered_product_ids)
        if violation is not None:
            return violation.to_llm(), None

        # THE ordering guard. Under legacy this was structural — gated_upsell
        # was only reachable from a successful create_promise_to_pay. The hub
        # advertises this tool alongside the PTP tool, so the constraint has to
        # be re-stated in code; a prompt line is not enough to stop the model
        # pitching insurance to a caller who has committed to nothing.
        # Deliberately refuses BEFORE calling domain.check_product_eligibility,
        # so no eligibility_checked analytics event is recorded either.
        if upsell_node is None and not state.commitment_secured:
            return {
                "eligible": False,
                "error": "upsell_not_unlocked",
                "say": (
                    "do not pitch anything; keep helping with the account "
                    "until a payment or callback is agreed"
                ),
            }, None

        try:
            result: ToolResult = await asyncio.to_thread(
                domain.check_product_eligibility,
                customer_id=cid,
                product_id=product_id,
                interaction_id=session.interaction_id,
                bot_id=bot_id,
                channel="voice",
            )
        except Exception as exc:
            logger.exception("check_product_eligibility failed")
            return {"error": "eligibility_failed", "detail": str(exc)}, None

        if result.ok:
            state.last_product_id = product_id
            # Corpus scope follows a SUCCESSFUL engagement. Setting it before the
            # call meant one hallucinated product id switched the KB off
            # collections for the rest of the conversation, so every later
            # money question was answered from the product corpus.
            state.product_scope = "product"
        # Deliberately NOT marking upsell_presented here. Passing an eligibility
        # check is not a pitch — the model may still decide not to make one, and
        # counting it inflated the presented rate against a denominator taken
        # from the commercial-events table. It is marked when a lead is captured
        # (domain.capture_lead) or when the offer is actually spoken
        # (_recommend_next_offer_handler).
        return result.to_llm(), None

    check_product_eligibility = _spec("check_product_eligibility", 
        _check_eligibility_handler
    )

    def _sink_call(name: str, default: Any) -> Any:
        """Read an optional metric off the CRM sink.

        The sink is absent in unit tests and in any caller that builds tools
        without a pipeline, so every read is optional — a missing sink degrades
        the offer decision, it must not break it.
        """
        if sink is None:
            return default
        fn = getattr(sink, name, None)
        if not callable(fn):
            return default
        try:
            value = fn()
        except Exception:
            logger.debug("sink.%s failed", name, exc_info=True)
            return default
        return default if value is None else value

    def _gap_sink() -> Callable[[dict[str, Any]], None] | None:
        """Queue KB-gap writes onto the CrmSink rather than writing inline.

        The KB handler runs in ``asyncio.to_thread``, so it is off the Pipecat
        pipeline — but it is still inside the turn's latency budget: the model
        waits for this tool result before it can speak. kb_retrieve already does
        one inline INSERT there; a second is avoidable, and a gap counter is the
        least urgent write in the system.

        Returns None when there is no sink (unit tests, tools built without a
        pipeline), which makes the shared handler fall back to writing inline —
        correct, because in those contexts there is no queue to defer to.
        """
        if sink is None:
            return None
        fn = getattr(sink, "enqueue_kb_gap", None)
        return fn if callable(fn) else None

    def _live_signals():
        """Snapshot of what THIS call knows, for the offer engine.

        The in-process flags (commitment secured, already declined, escalated)
        cannot be read back out of the transcript, and they are exactly the ones
        that decide whether an offer is appropriate at all.
        """
        from agent_core.reco.features import CallSignals

        # The sink's rolling average is built from the keyword scorer, which
        # returns 0.00 for any Hindi or code-switched turn — so the engine's
        # sentiment floor would never suppress an offer to a caller who is
        # audibly upset in Hindi. Prefer the classified score for the current
        # turn; fall back to the rolling average when it has not landed.
        understanding = session.understanding
        current = (
            float(understanding.sentiment)
            if understanding is not None
            else float(_sink_call("current_sentiment", 0.0))
        )

        return CallSignals(
            interaction_id=session.interaction_id,
            channel="voice",
            sentiment_current=current,
            sentiment_trend=float(_sink_call("sentiment_trend", 0.0)),
            customer_turns=int(_sink_call("customer_turns", 0)),
            commitment_secured=state.commitment_secured,
            escalation_flagged=state.escalated,
            dispute_opened=state.dispute_opened,
            offer_declined_this_call=state.offer_declined,
            offers_presented_this_call=state.offers_presented,
        )

    async def _recommend_next_offer_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Ask the engine what may be offered. The model does not choose."""
        cid, err = _require_customer()
        if err:
            return err, None

        # Hardship interlock. A borrower who has just told us they lost their
        # job or are in hospital must not then be pitched a top-up loan, and a
        # prompt instruction is not an interlock — it is a request. This is a
        # hard stop in the tool the offer has to come through, so no node,
        # phrasing or model can route around it. Latched for the rest of the
        # call: a reason given at turn four still binds at turn forty.
        blocked = session.extra.get("upsell_blocked")
        if blocked:
            logger.info("upsell suppressed for %s · reason=%s", cid, blocked)
            return {
                "suppressed": True,
                "reason": "hardship_declared",
                "say": (
                    "do not mention any product or offer; move the conversation "
                    "on without explaining why"
                ),
            }, None

        try:
            from agent_core.reco import engine as reco_engine
            import db

            def _run():
                with db.engine.begin() as conn:
                    return reco_engine.recommend(
                        customer_id=cid,
                        conn=conn,
                        interaction_id=session.interaction_id,
                        channel="voice",
                        live=_live_signals(),
                        # Per-session A/B arm, same override pattern as flowGraph.
                        # Absent, the engine buckets the customer by RECO_AB_SPLIT.
                        variant=session.extra.get("recoVariant"),
                    )

            result = await asyncio.to_thread(_run)
        except Exception as exc:
            # Never let the offer engine break the call. No offer is always a
            # valid outcome; an exception on the audio path is not.
            logger.exception("recommend_next_offer failed")
            return {
                "offers": [],
                "suppressed": True,
                "suppressionReason": "engine_error",
                "detail": str(exc),
                "say": "do not mention any product; continue with the call",
            }, None

        state.offer_decision_id = result.decision_id
        # §9.7: scored on the call, never spoken on it. `to_tool_payload` names
        # no product on any path, so a scored offer and a suppressed one are
        # indistinguishable from the model's side of the boundary — which they
        # must be, or the difference is itself the pitch.
        #
        # `present()` and `mark_upsell_presented` used to fire here, on the
        # theory that "about to be spoken" is when an offer counts as presented.
        # They belong to the promotional sender now: `presented` means delivered
        # on the promotional series, and consuming campaign quota for something
        # nobody was ever told about is how a campaign reports reach it did not
        # have.
        payload = result.to_tool_payload()
        if result.offers:
            top = result.top
            state.offered_product_id = top.product_id
            state.offered_product_ids.update(o.product_id for o in result.offers)

        # Leave the upsell step here, in code, rather than returning to the
        # model and asking it to notice that there is nothing to say. That round
        # trip is a whole extra inference — and it is silent, because there is
        # nothing to say while it happens. On VS-92CDE3F088 it cost three
        # chained inferences (recommend → return_to_position → hub) and seven
        # seconds of dead line before the caller gave up and spoke. Now that no
        # offer is ever spoken, this is the only path.
        #
        # Only when this node exists as a separate step: under the merged hub
        # graph there is nowhere to go and staying put is correct.
        if upsell_node:
            return payload, _node("wrap_up")
        return payload, None

    recommend_next_offer = _spec("recommend_next_offer", 
        _recommend_next_offer_handler
    )

    async def _decline_offer_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Record a refusal.

        A decline is a data point, not an absence of one: it labels the decision
        log, feeds the per-product cool-down so we do not raise the same thing
        again, and separates "asked and refused" from "never asked" in the
        funnel. It also latches off any further offer on this call.
        """
        args = CATALOG.normalize("decline_offer", args)
        state.offer_declined = True
        reason = str(args.get("reason") or "").strip() or None
        product_id = state.offered_product_id or state.last_product_id

        async def _persist() -> None:
            import capture
            import db

            if state.offer_decision_id:
                from agent_core.reco import decisions

                await asyncio.to_thread(
                    decisions.record_response, state.offer_decision_id, "declined"
                )
            cid = session.customer_id
            if not cid:
                return

            def _write() -> None:
                with db.engine.begin() as conn:
                    capture.record_offer_declined(
                        conn,
                        interaction_id=session.interaction_id,
                        customer_id=cid,
                        product_id=product_id,
                        reason=reason,
                        actor_bot_id=bot_id,
                    )

            await asyncio.to_thread(_write)

        try:
            await _persist()
        except Exception:
            # The in-call latch above holds either way: the borrower said no
            # and this call will not raise it again. But the *record* did not
            # happen, and telling the model it did -- "do not raise it again"
            # on ok=True -- is the same lie the text path stopped telling
            # (bot_tools._tool_decline_offer): the next call would offer it
            # afresh because nothing was written. The tool says what happened.
            logger.exception("decline_offer bookkeeping failed")
            return {"ok": False, "error": "crm_write_failed", "declined": True}, None

        # Nothing to say back — the model already heard the "no". A second
        # inference here just produces filler on top of it.
        if spoke_this_response is not None and spoke_this_response():
            return {"ok": True}, NO_RESPONSE
        return {
            "ok": True,
            "say": "acknowledge briefly and move on; do not raise it again",
        }, None

    decline_offer = _spec("decline_offer", _decline_offer_handler)

    # ----------------------------------------------------------- close probe

    def _probe_suppressed() -> str | None:
        """Why the end-of-call "anything else?" must not be asked, or None.

        Every reason here is about the state of the *call*, not the customer's
        commercial value. Asking a caller who has just been escalated, or who is
        disputing a charge, whether they want anything else reads as tone-deaf
        at best.
        """
        if state.close_probe_done:
            return "already_asked"
        if state.escalated:
            return "escalated"
        if state.dispute_opened:
            return "dispute_open"
        if not session.identity_verified:
            # Never verified: we do not know who this is, and the call is ending
            # for a reason (refusal, third party, failed attempts).
            return "unverified"
        # local_key, because on a merged graph the cursor reads
        # `insurance-v1/terminate_politely` and a flat comparison never matches.
        from flow_graph import local_key as _local

        if _local(state.current_node or "") in {"terminate_politely", "escalate_close"}:
            return "terminal_state"
        if float(_sink_call("current_sentiment", 0.0)) < _PROBE_SENTIMENT_FLOOR:
            return "sentiment_below_floor"
        # An abandoned or hostile call — two turns is barely a conversation.
        # None means the sink is absent and the count is genuinely unknown; as
        # everywhere else in this pipeline, unknown does not block.
        turns = _sink_call("customer_turns", None)
        if turns is not None and int(turns) < 2:
            return "too_few_turns"
        return None

    async def _prepare_close_probe() -> None:
        """Score an offer at the close. It is logged; it is never spoken.

        This used to build the sentence the model would read out. §9.7 makes
        that unlawful inside a recorded collections call, so what is left is
        the half that was always the point: the close is the one moment in a
        servicing contact where a cross-sell can be *scored* without
        interrupting anything, and the decision row is what the offer corpus
        has never had. Delivery happens later, on the promotional series,
        against a current suitability finding.
        """
        cid = session.customer_id
        if not cid:
            return
        # Already pitched or already refused something on this call — asking
        # again is pressure, not service.
        if state.offer_declined or state.offers_presented > 0:
            return

        try:
            from agent_core.reco import engine as reco_engine
            import db

            def _run():
                with db.engine.begin() as conn:
                    return reco_engine.recommend(
                        customer_id=cid,
                        conn=conn,
                        interaction_id=session.interaction_id,
                        channel="voice",
                        live=_live_signals(),
                        # Per-session A/B arm, same override pattern as flowGraph.
                        # Absent, the engine buckets the customer by RECO_AB_SPLIT.
                        variant=session.extra.get("recoVariant"),
                    )

            result = await asyncio.to_thread(_run)
        except Exception:
            logger.exception("close-probe recommendation failed")
            return

        if result.suppressed or not result.offers:
            return

        # Scored, logged, and not spoken. The close was the last place an offer
        # reached the model without passing through `to_tool_payload` -- it read
        # `top.talk_track` and `top.name` straight off the result and folded a
        # ready-phrased sentence into the pre_close prompt. §9.7: the offer is
        # scored on the call and it is never spoken on it, so what survives here
        # is the decision row, which is the thing this corpus was missing.
        state.offer_decision_id = result.decision_id
        # Kept so `capture_lead` can still tie an inbound "actually, tell me
        # about that" to the decision that scored it, rather than refusing it
        # as un-offered.
        state.offered_product_id = result.top.product_id
        state.offered_product_ids.update(o.product_id for o in result.offers)

    async def _record_close_probe(with_offer: bool) -> None:
        ix = session.interaction_id
        if not ix:
            return

        def _write() -> None:
            import capture
            import db

            with db.engine.begin() as conn:
                capture.record_close_probe(
                    conn,
                    interaction_id=ix,
                    with_offer=with_offer,
                    product_id=state.offered_product_id if with_offer else None,
                    actor_bot_id=bot_id,
                )

        try:
            await asyncio.to_thread(_write)
        except Exception:
            logger.exception("close probe event failed")

    async def _close_probe_node() -> dict[str, Any] | None:
        """Enter the probe once, or return None to let the caller go terminal.

        Latches ``close_probe_done`` BEFORE the node is built, so a model that
        somehow re-enters the closing path cannot ask twice.
        """
        reason = _probe_suppressed()
        if reason is not None:
            logger.debug("close probe skipped: %s", reason)
            return None
        state.close_probe_done = True
        await _prepare_close_probe()
        node = _node("pre_close")
        if node is None:
            # Registry miss (tools built without a graph) — fall through to the
            # caller's normal terminal rather than dropping the call.
            return None
        # Always without an offer now, and the constant says so rather than a
        # variable that could only ever be empty.
        await _record_close_probe(False)
        return node

    async def _capture_lead_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Capture upsell interest as a real CRM lead."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("capture_lead", args)
        product_id = str(args.get("product_id") or state.last_product_id or "").strip()
        if not product_id:
            return {"error": "product_id_required"}, None

        offer_amount = args.get("offer_amount")
        try:
            offer_amount = float(offer_amount) if offer_amount is not None else None
        except (TypeError, ValueError):
            offer_amount = None

        # An offerId ties the captured lead to the offer that was actually
        # pitched. Without it the model could pitch A and capture B and nothing
        # would notice; the id is "<decisionId>:<productId>", so it also
        # cross-checks the product.
        offer_id = str(args.get("offer_id") or "").strip()
        decision_id = state.offer_decision_id
        if offer_id and ":" in offer_id:
            offer_decision, offer_product = offer_id.split(":", 1)
            if offer_product and offer_product != product_id:
                logger.warning(
                    "capture_lead offer/product mismatch: offer=%s product=%s — "
                    "trusting the offer",
                    offer_id,
                    product_id,
                )
                product_id = offer_product
            decision_id = offer_decision or decision_id

        violation = domain.offer_sourcing_violation(product_id, state.offered_product_ids)
        if violation is not None:
            return violation.to_llm(), None

        # The customer's own words, not an empty string. This was hardcoded to
        # "" so the snippet fell back to a generic "Interest in <product>" and
        # sentiment scored neutral no matter what they said.
        customer_text = str(_sink_call("last_customer_text", ""))

        try:
            result: ToolResult = await asyncio.to_thread(
                domain.capture_lead,
                customer_id=cid,
                product_id=product_id,
                interaction_id=session.interaction_id,
                bot_id=bot_id,
                offer_amount=offer_amount,
                summary=args.get("summary"),
                priority=args.get("priority"),
                source="bot_voice",
                customer_text=customer_text,
                channel="voice",
                # Stable key so a retried or duplicated tool call cannot put two
                # identical leads in the pipeline — the contract the sibling CRM
                # writes have had all along.
                # Carrier-call scope, like the four sibling writes: an
                # interaction-scoped key made a lead from a second call on
                # the same interaction a replay of the first.
                idempotency_key=(
                    f"voice-lead:{session.provider_call_id or session.interaction_id or 'no-ix'}"
                    f":{cid}:{product_id}"
                ),
                decision_id=decision_id,
                # Otherwise the lead is scored by the English lexicon and every
                # lead from a Hindi caller reaches the rep marked "neutral".
                sentiment_score=(
                    session.understanding.sentiment
                    if session.understanding is not None
                    else None
                ),
            )
        except Exception as exc:
            logger.exception("capture_lead failed")
            return {
                "error": "crm_write_failed",
                "detail": str(exc),
                "say": "apologise and offer to have a specialist call them",
            }, None

        await _announce(result, "capture_lead")
        if result.ok:
            state.upsell_presented = True
            return result.to_llm(), _node("wrap_up") if upsell_node else None
        return result.to_llm(), None

    capture_lead = _spec("capture_lead", _capture_lead_handler)

    # ------------------------------------------------------------ documents

    async def _request_documents_handler(
        args: dict[str, Any],
        flow_manager,
    ) -> tuple[Any, dict[str, Any] | None]:
        """Raise a document request the Operations queue fulfils."""
        cid, err = _require_customer()
        if err:
            return err, None
        args = CATALOG.normalize("request_documents", args)
        doc_type = str(args.get("document_type") or "").strip().lower()
        if doc_type not in DOCUMENT_TYPES:
            return {"error": "invalid_document_type", "allowed": list(DOCUMENT_TYPES)}, None

        period = args.get("period")
        # A duplicated tool call here means the caller gets the same statement
        # generated and emailed twice.
        #
        # Scoped to the CARRIER CALL, not the interaction row — see
        # ``_create_ptp_handler``. A reconnect mints a new interaction, so an
        # interaction-scoped key sent the statement a second time when the
        # model re-raised the request after the drop. ``provider_call_id``
        # survives the reconnect; without one we fall back to the interaction
        # id as before.
        call_scope = session.provider_call_id or session.interaction_id or "no-ix"
        idem = (
            f"voice-doc:{call_scope}:"
            f"{cid}:{doc_type}:{str(period).strip() if period else 'na'}"
        )

        try:
            result: ToolResult = await asyncio.to_thread(
                domain.request_documents,
                customer_id=cid,
                document_type=doc_type,
                interaction_id=session.interaction_id,
                account_id=session.account_id,
                delivery_channel=args.get("delivery_channel"),
                period=period,
                requested_via="bot_voice",
                idempotency_key=idem,
            )
        except Exception as exc:
            logger.exception("request_documents failed")
            return {"error": "crm_write_failed", "detail": str(exc)}, None

        # Writes `document_requests`, which the CRM card renders under open work.
        await _announce(result, "request_documents", inject_delta=False)
        _schedule_context_refresh("request_documents")
        return result.to_llm(), None

    request_documents = _spec("request_documents", 
        _request_documents_handler
    )

    # Read by a later section, through the same scope object.
    ctx._close_probe_node = _close_probe_node
    ctx._gap_sink = _gap_sink
    ctx._sink_call = _sink_call

    return {
        "recommend_next_offer": recommend_next_offer,
        "check_product_eligibility": check_product_eligibility,
        "capture_lead": capture_lead,
        "decline_offer": decline_offer,
        "request_documents": request_documents,
    }
