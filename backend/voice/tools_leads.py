"""Voice tools -- leads and document requests.

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

from agent_core.tools import ToolResult
from agent_core.tools.catalog import (
    CATALOG,
    DOCUMENT_TYPES,
)
from agent_core.tools import domain

from voice.tool_state import (
    ToolBuildContext,
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
    state = ctx.state
    upsell_node = ctx.upsell_node
    _sink_call = ctx._sink_call


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

    return {
        "capture_lead": capture_lead,
        "request_documents": request_documents,
    }
