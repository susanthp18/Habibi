"""Voice tools -- product eligibility and the next offer.

One section of the voice tool set: the handlers that used to be closures
inside ``voice.tools.build_tools``. ``build(ctx)`` receives the closure
scope as a ``ToolBuildContext`` and unpacks the names it reads, so every
handler body below is byte-for-byte what it was -- a move, pinned by
``tests/test_voice_tool_schemas_snapshot.py``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, cast

# Not `from pipecat.flows import ...` directly: this module is the trunk the
# built-in flow export hangs off, and the API image has no pipecat. See
# agent_core/tools/pipecat_compat.py — under pipecat these are pipecat's own
# objects and nothing about a call changes.

from agent_core.tools import ToolResult
from agent_core.tools.catalog import (
    CATALOG,
)
from agent_core.tools import domain

from voice.tool_state import (
    ToolBuildContext,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _node = ctx._node
    _require_customer = ctx._require_customer
    _spec = ctx._spec
    bot_id = ctx.bot_id
    session = ctx.session
    sink = ctx.sink
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
        return cast("Callable[[dict[str, Any]], None] | None", fn if callable(fn) else None)

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
                        # Per-session A/B arm, read from session.extra.
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
        top = result.top
        if top is not None:
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

    # Read by another section, through the same scope object.
    ctx._gap_sink = _gap_sink
    ctx._live_signals = _live_signals
    ctx._sink_call = _sink_call

    return {
        "recommend_next_offer": recommend_next_offer,
        "check_product_eligibility": check_product_eligibility,
    }
