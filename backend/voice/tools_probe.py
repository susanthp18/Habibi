"""Voice tools -- declining an offer and the close probe.

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
)

from voice.tool_state import (
    ToolBuildContext,
    _PROBE_SENTIMENT_FLOOR,
)

logger = logging.getLogger(__name__)


def build(ctx: ToolBuildContext) -> dict[str, Any]:
    """The tools of this section, keyed by the variable name build_tools used."""
    _node = ctx._node
    _spec = ctx._spec
    bot_id = ctx.bot_id
    session = ctx.session
    spoke_this_response = ctx.spoke_this_response
    state = ctx.state
    _live_signals = ctx._live_signals
    _sink_call = ctx._sink_call


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
            import capture_events
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
                    capture_events.record_offer_declined(
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
                        # Per-session A/B arm, read from session.extra.
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
            import capture_events
            import db

            with db.engine.begin() as conn:
                capture_events.record_close_probe(
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

    # Read by another section, through the same scope object.
    ctx._close_probe_node = _close_probe_node

    return {
        "decline_offer": decline_offer,
    }
