"""Channel-agnostic domain handlers shared by voice and WhatsApp/text.

These are the *single* implementations the unification plan calls for: identical
eligibility rules, identical lead rows, identical document requests regardless of
which channel the customer used. They stay **synchronous** because the WhatsApp
worker and the API both run on threads; the voice bot wraps them in
``asyncio.to_thread`` so the audio path is never blocked.

Every handler returns a :class:`ToolResult` so the caller can uniformly derive:
  * what to say (``spoken_summary``)
  * what the UI should deep-link to (``entity`` / ``entity_id`` / ``deep_link``)
  * which analytics flags fired (``analytics``)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import date
from typing import Any

from agent_core.tools.catalog import (
    CALLBACK_REASONS,
    CATALOG,
    DISPUTE_TYPES,
    LEAD_PRIORITIES,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """Uniform tool outcome across channels (plan §4)."""

    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    spoken_summary: str | None = None
    entity: str | None = None
    entity_id: str | None = None
    deep_link: str | None = None
    analytics: list[str] = field(default_factory=list)
    error: str | None = None

    def __post_init__(self) -> None:
        # Normalize here rather than at every read site. Callers were split
        # between `result.data.get(...)` and `(result.data or {})`, so an
        # explicit `data=None` from any future handler would have raised
        # AttributeError on the voice audio path in exactly the sites that
        # skipped the guard.
        if self.data is None:
            self.data = {}
        if self.analytics is None:
            self.analytics = []

    def to_llm(self) -> dict[str, Any]:
        """Payload handed back to the model — deliberately compact.

        Canonical ``ok`` / ``error`` / ``say`` win over handler data keys.
        """
        out: dict[str, Any] = {**self.data}
        out["ok"] = self.ok
        if self.error:
            out["error"] = self.error
        else:
            out.pop("error", None)
        if self.spoken_summary:
            out["say"] = self.spoken_summary
        else:
            out.pop("say", None)
        return out


def _link(tool_name: str, entity_id: str | None) -> str | None:
    spec = CATALOG.get(tool_name)
    return spec.link_for(entity_id) if spec else None


def _entity(tool_name: str) -> str | None:
    spec = CATALOG.get(tool_name)
    return spec.entity if spec else None


def _row_field(row: Any, key: str, default: Any = None) -> Any:
    """Read a field off a db.create_* result without assuming it is a mapping.

    The create_* helpers return a mapping today, but a driver/schema change that
    makes one return None must surface as a structured CRM failure, not an
    AttributeError escaping into the turn loop. Every read of a create_* result
    goes through here — a single direct ``.get()`` alongside it re-opens the
    hole the guard exists to close.
    """
    if isinstance(row, Mapping):
        value = row.get(key, default)
        return default if value is None else value
    return default


def _row_id_or_failure(
    row: Any, *, what: str, spoken: str
) -> tuple[str | None, "ToolResult | None"]:
    """Resolve a create_* result's ``id``, or the CRM failure to return instead.

    :func:`_row_field` already keeps a ``None`` row from raising, but the caller
    then reported ``ok=True`` with a null entity id and a deep link pointing
    nowhere — the model told the customer the record was created while nothing
    referenced it. A write with no id is a failed write.
    """
    raw = _row_field(row, "id")
    if raw:
        return str(raw), None
    logger.error("%s returned no id row=%r", what, row)
    return None, ToolResult(
        ok=False,
        error="crm_write_failed",
        data={"detail": "crm_write_failed"},
        spoken_summary=spoken,
    )


def _parse_promise_date(raw: str) -> str | None:
    """Normalize to YYYY-MM-DD or return None if invalid."""
    s = (raw or "").strip()
    if not s:
        return None
    if "T" in s:
        s = s.split("T", 1)[0]
    try:
        date.fromisoformat(s)
    except ValueError:
        return None
    return s


def _promise_date_is_past(date_s: str) -> bool:
    """Is this promised day already behind us, in the tenant's own timezone?

    The pay link generated for a promise expires at the promised day + 1,
    23:59 IST. A date in the past therefore mints a link that is already dead —
    the customer receives a URL the next settle tick breaks, and the CRM
    records a promise that was unkeepable the moment it was written. Today is
    still a real promise: the link lives until tomorrow night.
    """
    from agent_core import clock

    try:
        promised = date.fromisoformat(date_s)
    except ValueError:
        return False
    return promised < clock.now_local().date()


def _parse_scheduled_at(raw: str) -> str | None:
    """Accept an ISO datetime; return a canonical UTC instant, or None.

    This used to return the model's string verbatim, so what got stored
    depended entirely on whether the model happened to attach an offset and
    which one it guessed. On a live call it emitted ``12:30:00+00:00`` while
    saying "12:30 PM" — five and a half hours apart for an India-facing
    product. A naive value is now read as tenant-local (see agent_core.clock),
    which is what the model means when it echoes a wall-clock time back to the
    caller, and everything is normalised to an explicit instant before storage.
    """
    from agent_core import clock

    when = clock.to_instant(raw)
    if when is None:
        return None
    return clock.utc_isoformat(when)


def _clamp_window_mins(window_mins: Any) -> int:
    try:
        window = int(window_mins if window_mins is not None else 30)
    except (TypeError, ValueError):
        window = 30
    return max(15, min(120, window))


# ---------------------------------------------------------------------------
# Upsell
# ---------------------------------------------------------------------------

# Sentinel flags list distinguishing "transaction failed" from "product absent"
# — both return product=None, but only one is a CRM write failure.
_ELIGIBILITY_FAILED: list[dict[str, Any]] = [{"__failed__": True}]


def _check_and_record_eligibility(
    *,
    customer_id: str,
    product_id: str,
    interaction_id: str | None,
    bot_id: str | None,
    channel: str | None = None,
    record_event: bool = True,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
    """Look up the product, evaluate eligibility, and record the check.

    Shared by check_product_eligibility and capture_lead so the two cannot
    drift apart. Returns ``(product, flags, block)``; ``product`` is None when
    the product id does not exist, and ``flags`` is :data:`_ELIGIBILITY_FAILED`
    when the transaction itself failed — the sibling handlers all convert a CRM
    write failure into a structured result, so this one must not be the single
    path that lets an exception escape into the turn loop.

    ``record_event=False`` re-runs the evaluation without emitting a second
    ``eligibility_checked`` event. capture_lead deliberately re-checks (consent
    can change between the pitch and the yes) but the funnel should not count
    that as a separate check — one conversation, one recorded check.

    Only inactive products are hidden: a lead captured against a product that
    was later switched off must still resolve its name for display.
    """
    import capture
    import db
    from sqlalchemy import text

    try:
        with db.engine.begin() as conn:
            product = (
                conn.execute(
                    text(
                        "SELECT id, name, roi, category, ticket_min, ticket_max, is_active"
                        " FROM products WHERE id = :id"
                    ),
                    {"id": product_id},
                )
                .mappings()
                .first()
            )
            if product is None or not product.get("is_active", True):
                return None, [], None
            flags = capture.evaluate_product_eligibility(
                conn, customer_id=customer_id, product_id=product_id, channel=channel
            )
            block = capture.eligibility_blocks_capture(flags)
            if record_event:
                capture.record_eligibility_checked(
                    conn,
                    interaction_id=interaction_id,
                    customer_id=customer_id,
                    product_id=product_id,
                    flags=flags,
                    blocked=block,
                    actor_bot_id=bot_id,
                )
    except Exception:
        logger.exception(
            "eligibility check failed customer=%s product=%s", customer_id, product_id
        )
        return None, _ELIGIBILITY_FAILED, None
    return dict(product), list(flags), block


def offer_sourcing_violation(
    product_id: str, offered_product_ids: "set[str] | frozenset[str] | None"
) -> ToolResult | None:
    """Refuse a product the offer engine did not put on the table.

    The prompt tells the model not to name a product ``recommend_next_offer``
    did not return. This makes it true. A prompt line is not a control: the
    model only has to hallucinate one plausible id — and the ids are guessable
    English slugs — to pitch something nobody approved, to a customer who may
    hold it already, be barred from it, or have refused it last month.

    ``None``/empty means the engine has not run at all this session, which is
    itself the violation: nothing may be pitched before it has.
    """
    if offered_product_ids and product_id in offered_product_ids:
        return None
    return ToolResult(
        ok=False,
        error="product_not_offered",
        data={
            "productId": product_id,
            "allowed": sorted(offered_product_ids or ()),
        },
        spoken_summary=(
            "do not mention this product; call recommend_next_offer and only "
            "discuss what it returns"
        ),
    )


def _eligibility_failure_result(product_id: str) -> ToolResult:
    return ToolResult(
        ok=False,
        error="crm_write_failed",
        data={"detail": "crm_write_failed", "productId": product_id},
        spoken_summary="apologise and offer a callback so an agent can follow up",
    )


def check_product_eligibility(
    *,
    customer_id: str,
    product_id: str,
    interaction_id: str | None = None,
    bot_id: str | None = None,
    channel: str | None = None,
) -> ToolResult:
    """Evaluate live eligibility and record the check as a commercial event."""
    pid = (product_id or "").strip()
    if not pid:
        return ToolResult(ok=False, error="product_id_required")

    product, flags, block = _check_and_record_eligibility(
        customer_id=customer_id,
        product_id=pid,
        interaction_id=interaction_id,
        bot_id=bot_id,
        channel=channel,
    )
    if flags is _ELIGIBILITY_FAILED:
        return _eligibility_failure_result(pid)
    if product is None:
        return ToolResult(
            ok=False,
            error="product_not_found",
            data={"productId": pid},
        )

    eligible = block is None
    return ToolResult(
        ok=True,
        data={
            "productId": pid,
            "productName": product.get("name"),
            "eligible": eligible,
            "blockReason": block,
            "flags": [
                {
                    "label": f.get("label"),
                    "passed": f.get("passed"),
                    "reason": f.get("reason"),
                    "status": f.get("status"),
                }
                for f in flags
            ],
        },
        spoken_summary=(
            "mention the product in one short sentence and ask if they want details"
            if eligible
            else "do not pitch this product; move on without explaining the internal reason"
        ),
        analytics=["eligibility_checked"],
    )


def _suggested_amount(
    product: Mapping[str, Any] | dict[str, Any], offer_amount: float | None
) -> float | None:
    """Clamp an offered amount into the product's ticket band, or fall back to
    the band's floor.

    ``estimated_value`` drives every money figure on the pipeline board, and it
    was simply whatever optional argument the model happened to pass — so a
    model that omitted it produced a NULL that rendered as ₹NaN subtotals and
    crashed the lead card outright.
    """
    lo = product.get("ticket_min")
    hi = product.get("ticket_max")
    try:
        lo_f = float(lo) if lo is not None else None
        hi_f = float(hi) if hi is not None else None
    except (TypeError, ValueError):
        lo_f = hi_f = None

    if offer_amount is not None:
        try:
            amount = float(offer_amount)
        except (TypeError, ValueError):
            amount = None
        if amount is not None and amount > 0:
            if lo_f is not None:
                amount = max(amount, lo_f)
            if hi_f is not None:
                amount = min(amount, hi_f)
            return amount
    return lo_f


def capture_lead(
    *,
    customer_id: str,
    product_id: str,
    interaction_id: str | None = None,
    bot_id: str | None = None,
    offer_amount: float | None = None,
    summary: str | None = None,
    priority: str | None = None,
    source: str = "bot_chat",
    customer_text: str = "",
    channel: str | None = None,
    idempotency_key: str | None = None,
    decision_id: str | None = None,
    sentiment_score: float | None = None,
) -> ToolResult:
    """Re-check eligibility, then write the lead row and its commercial events.

    ``sentiment_score`` lets a channel that has already classified the turn pass
    it in. Without it the lead is scored by the English lexicon, so every lead
    captured from a Hindi caller lands on the rep's queue marked "neutral".
    """
    import capture
    import db
    from agent_core.sentiment import estimate_sentiment, sentiment_label

    pid = (product_id or "").strip()
    if not pid:
        return ToolResult(ok=False, error="product_id_required")

    # Re-check rather than trust the earlier probe: consent can change between
    # the pitch and the yes. record_event=False so the funnel counts one check
    # per conversation, not two.
    product, flags, block = _check_and_record_eligibility(
        customer_id=customer_id,
        product_id=pid,
        interaction_id=interaction_id,
        bot_id=bot_id,
        channel=channel,
        record_event=False,
    )
    if flags is _ELIGIBILITY_FAILED:
        return _eligibility_failure_result(pid)
    if product is None:
        return ToolResult(ok=False, error="product_not_found", data={"productId": pid})
    if block:
        return ToolResult(
            ok=False,
            error="eligibility_blocked",
            data={"blockReason": block, "productId": pid},
            spoken_summary=(
                "do not capture interest for this product; thank them and move on "
                "without explaining the internal reason"
            ),
        )

    # Already-open lead for this product: acknowledge it warmly instead of
    # stacking a second row that puts two reps on the same call.
    try:
        with db.engine.connect() as conn:
            existing = db.find_open_lead(conn, customer_id, pid)
    except Exception:
        logger.exception("duplicate lead lookup failed customer=%s product=%s", customer_id, pid)
        existing = None
    if existing:
        return ToolResult(
            ok=True,
            data={
                "leadId": existing["id"],
                "duplicate": True,
                "stage": existing.get("stage"),
                "productId": pid,
                "productName": product.get("name"),
            },
            spoken_summary=(
                "confirm this is already noted and a specialist will follow up — "
                "do not take the details again"
            ),
            entity=_entity("capture_lead"),
            entity_id=existing["id"],
            deep_link=_link("capture_lead", existing["id"]),
        )

    # The customer's own words are the whole value of the snippet: it is the
    # most prominent field on the lead card and the rep's only context. Falling
    # back to a generic string threw that away whenever the model omitted a
    # summary — which also silently scored sentiment as neutral.
    text_for_sentiment = (summary or "").strip() or (customer_text or "").strip()
    score = (
        float(sentiment_score)
        if sentiment_score is not None
        else estimate_sentiment(text_for_sentiment)
    )
    prio = priority if priority in LEAD_PRIORITIES else "normal"
    amount = _suggested_amount(product, offer_amount)

    payload: dict[str, Any] = {
        "customerId": customer_id,
        "productId": pid,
        "interactionId": interaction_id,
        "source": source,
        "stage": "interested",
        "sentimentAtCapture": sentiment_label(score),
        "sentimentScore": round(float(score), 3),
        "transcriptSnippet": (text_for_sentiment or f"Interest in {product.get('name')}")[:400],
        "offerAmount": offer_amount,
        "offerRoi": product.get("roi"),
        "estimatedValue": amount,
        "priority": prio,
        "eligibilityFlags": flags,
        "channel": channel,
        # Attribution for the funnel event create_lead now emits on every
        # path. Without it a bot capture would be logged as a system actor.
        "actorBotId": bot_id,
    }
    # Same CRM-write failure contract as the sibling handlers: the model gets a
    # structured result it can speak around instead of an exception escaping
    # into the turn loop.
    analytics: list[str] = []
    try:
        lead = db.create_lead(payload, idempotency_key=idempotency_key, emitted=analytics)
    except ValueError as exc:
        # Race: another writer captured the same product between the lookup
        # above and this insert. The advisory lock in create_lead makes this the
        # authoritative answer, so treat it the same way as the pre-check.
        detail = str(exc)
        if detail.startswith("duplicate_open_lead:"):
            existing_id = detail.split(":", 1)[1]
            return ToolResult(
                ok=True,
                data={"leadId": existing_id, "duplicate": True, "productId": pid},
                spoken_summary="confirm this is already noted and a specialist will follow up",
                entity=_entity("capture_lead"),
                entity_id=existing_id,
                deep_link=_link("capture_lead", existing_id),
            )
        logger.exception("create_lead rejected customer=%s product=%s", customer_id, pid)
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": "crm_write_failed", "productId": pid},
            spoken_summary="apologise and offer a callback so an agent can follow up",
        )
    except Exception:
        logger.exception("create_lead failed customer=%s product=%s", customer_id, pid)
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": "crm_write_failed", "productId": pid},
            spoken_summary="apologise and offer a callback so an agent can follow up",
        )
    lead_id, failure = _row_id_or_failure(
        lead,
        what="create_lead",
        spoken="apologise and offer a callback so an agent can follow up",
    )
    if failure is not None:
        return failure

    # Report only the events that actually landed: Bot Analytics reads this
    # list, and claiming an upsell_presented whose row was never written makes
    # the funnel disagree with the commercial-events table it is derived from.
    # Each event is committed independently so a failure in the second does not
    # retract the first — clearing the list wholesale reported a lead_captured
    # that HAD been written as if it had not.
    #
    # `lead_captured` is no longer emitted here. It is emitted inside
    # create_lead, which is the one path every capture goes through; doing it
    # in both places wrote the event twice for a bot capture and not at all for
    # a human one. `analytics` carries out what actually landed in there.
    if interaction_id:
        try:
            with db.engine.begin() as conn:
                capture.record_offer_presented(
                    conn,
                    interaction_id=interaction_id,
                    product_id=pid,
                    source="capture_lead",
                    actor_bot_id=bot_id,
                )
            analytics.append("upsell_presented")
        except Exception:
            logger.exception("offer_presented event failed for %s", lead_id)

    # Close the loop on the recommendation that produced this lead. Without it
    # the decision log has no outcome label and nothing can be trained on it.
    if decision_id:
        try:
            from agent_core.reco import decisions

            decisions.attach_lead(decision_id, lead_id=lead_id, response="interested")
        except Exception:
            logger.exception("attach_lead failed for decision %s", decision_id)

    return ToolResult(
        ok=True,
        data={
            "leadId": lead_id,
            "stage": _row_field(lead, "stage"),
            "productId": pid,
            "productName": product.get("name"),
        },
        spoken_summary="confirm briefly that a specialist will share the details",
        entity=_entity("capture_lead"),
        entity_id=lead_id,
        deep_link=_link("capture_lead", lead_id),
        analytics=analytics,
    )


def mark_upsell_presented(
    *, interaction_id: str | None, product_id: str | None = None, bot_id: str | None = None
) -> None:
    """Flag that an offer was spoken even when the customer declined.

    Bot Analytics counts presentation, not just conversion — without this the
    voice channel shows a 0% upsell-presented rate whenever callers say no.
    """
    if not interaction_id:
        return
    try:
        import capture
        import db

        with db.engine.begin() as conn:
            capture.record_offer_presented(
                conn,
                interaction_id=interaction_id,
                product_id=product_id,
                source="voice_upsell",
                actor_bot_id=bot_id,
            )
    except Exception:
        logger.exception("mark_upsell_presented failed")


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def request_documents(
    *,
    customer_id: str,
    document_type: str,
    interaction_id: str | None = None,
    account_id: str | None = None,
    delivery_channel: str | None = None,
    period: str | None = None,
    requested_via: str = "bot_chat",
    idempotency_key: str | None = None,
) -> ToolResult:
    """Raise a document request row that Operations fulfils."""
    import db
    from agent_core.tools.catalog import DOCUMENT_CHANNELS, DOCUMENT_TYPES

    dtype = (document_type or "").strip()
    if not dtype:
        return ToolResult(ok=False, error="document_type_required")
    if dtype not in DOCUMENT_TYPES:
        return ToolResult(ok=False, error="invalid_document_type")
    channel = (delivery_channel or "").strip() or None
    if channel and channel not in DOCUMENT_CHANNELS:
        return ToolResult(ok=False, error="invalid_delivery_channel")

    payload: dict[str, Any] = {
        "customerId": customer_id,
        "accountId": account_id,
        "interactionId": interaction_id,
        "docType": dtype,
        "requestedVia": requested_via,
    }
    if channel:
        payload["deliveryChannel"] = channel
    if period:
        payload["period"] = period

    try:
        row = db.create_document_request(payload, idempotency_key=idempotency_key)
    except Exception:
        logger.exception("create_document_request failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": "crm_write_failed"},
            spoken_summary="apologise and offer a callback so an agent can send it",
        )

    doc_id, failure = _row_id_or_failure(
        row,
        what="create_document_request",
        spoken="apologise and offer a callback so an agent can send it",
    )
    if failure is not None:
        return failure
    return ToolResult(
        ok=True,
        data={
            "documentRequestId": doc_id,
            "documentType": _row_field(row, "docType") or dtype,
            "deliveryChannel": _row_field(row, "deliveryChannel"),
        },
        spoken_summary="confirm which document was requested and how it will arrive",
        entity=_entity("request_documents"),
        entity_id=doc_id,
        deep_link=_link("request_documents", doc_id),
        analytics=["document_requested"],
    )


# ---------------------------------------------------------------------------
# Collections CRM writes (PTP / dispute / callback)
# ---------------------------------------------------------------------------


def create_promise_to_pay(
    *,
    customer_id: str,
    amount: float,
    promised_date: str,
    interaction_id: str | None = None,
    account_id: str | None = None,
    channel: str = "voice",
    bot_id: str | None = None,
    idempotency_key: str | None = None,
) -> ToolResult:
    """Write a promise-to-pay row and flag the interaction for analytics."""
    import capture
    import db

    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return ToolResult(ok=False, error="invalid_amount")
    if amt <= 0:
        return ToolResult(ok=False, error="amount_out_of_range")
    date_s = _parse_promise_date(str(promised_date or ""))
    if not date_s:
        return ToolResult(ok=False, error="invalid_promise_date")
    if _promise_date_is_past(date_s):
        return ToolResult(ok=False, error="promise_date_in_past")

    ch = channel if channel in {"voice", "whatsapp", "sms", "email", "chat"} else "voice"
    payload: dict[str, Any] = {
        "customerId": customer_id,
        "amount": amt,
        "promisedDate": date_s,
        "channel": ch,
        "interactionId": interaction_id,
    }
    if account_id:
        payload["accountId"] = account_id
    if bot_id:
        payload["ownerBotId"] = bot_id

    try:
        try:
            row = db.create_promise(payload, idempotency_key=idempotency_key)
        except db.OwnerBotNotFound:
            # This environment has no row for the configured bot — retry with a
            # human owner. Narrow on purpose: a bare `except KeyError` also
            # swallowed genuine missing-payload-key bugs and resubmitted them.
            logger.warning("create_promise: unknown ownerBotId %s — retrying unowned", bot_id)
            payload.pop("ownerBotId", None)
            row = db.create_promise(payload, idempotency_key=idempotency_key)
    except Exception:
        logger.exception("create_promise failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": "crm_write_failed"},
            spoken_summary="apologise and offer a callback or human agent",
        )

    promise_id, failure = _row_id_or_failure(
        row,
        what="create_promise",
        spoken="apologise and offer a callback or human agent",
    )
    if failure is not None:
        return failure
    if interaction_id:
        try:
            with db.engine.begin() as conn:
                capture.mark_ptp_captured(conn, interaction_id)
        except Exception:
            logger.exception("mark_ptp_captured failed")

    fulfillment = (row or {}).get("_fulfillment") or {}
    spoken = (row or {}).get("_spoken") or "confirm the amount and date back to them"
    return ToolResult(
        ok=True,
        data={
            "promiseId": promise_id,
            "amount": _row_field(row, "amount", amt),
            "promisedDate": date_s,
            "status": _row_field(row, "status"),
            "confirmChannel": fulfillment.get("confirmChannel"),
            "phoneLast4": fulfillment.get("phoneLast4"),
            "payLinkSent": bool(fulfillment.get("payLinkSent")),
            "suppressed": bool(fulfillment.get("suppressed")),
        },
        spoken_summary=spoken,
        entity=_entity("create_promise_to_pay"),
        entity_id=promise_id,
        deep_link=_link("create_promise_to_pay", promise_id),
        analytics=["ptp_captured"],
    )


def flag_dispute(
    *,
    customer_id: str,
    dispute_type: str,
    interaction_id: str | None = None,
    account_id: str | None = None,
    amount: float | None = None,
    summary: str | None = None,
    priority: str | None = None,
    idempotency_key: str | None = None,
) -> ToolResult:
    """Open a dispute for human review."""
    import db

    dtype = (dispute_type or "").strip().lower()
    if dtype not in DISPUTE_TYPES:
        return ToolResult(
            ok=False,
            error="invalid_dispute_type",
            data={"allowed": list(DISPUTE_TYPES)},
        )

    prio = priority if priority in {"low", "normal", "high"} else (
        "high" if dtype == "fraud" else "normal"
    )
    payload: dict[str, Any] = {
        "customerId": customer_id,
        "type": dtype,
        "amount": amount,
        "transcriptSnippet": (str(summary) if summary else "")[:500] or None,
        "interactionId": interaction_id,
        "priority": prio,
    }
    if account_id:
        payload["accountId"] = account_id

    try:
        row = db.create_dispute(payload, idempotency_key=idempotency_key)
    except Exception:
        logger.exception("create_dispute failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": "crm_write_failed"},
            spoken_summary="apologise and offer a callback or human agent",
        )

    dispute_id, failure = _row_id_or_failure(
        row,
        what="create_dispute",
        spoken="apologise and offer a callback or human agent",
    )
    if failure is not None:
        return failure
    return ToolResult(
        ok=True,
        data={
            "disputeId": dispute_id,
            "type": _row_field(row, "type") or dtype,
            "status": _row_field(row, "status"),
        },
        spoken_summary="a specialist will follow up",
        entity=_entity("flag_dispute"),
        entity_id=dispute_id,
        deep_link=_link("flag_dispute", dispute_id),
        analytics=["dispute_flagged"],
    )


def evaluate_authority(
    *,
    customer_id: str,
    fee_type: str | None = None,
    asked_amount: float | None = None,
    interaction_id: str | None = None,
    account_id: str | None = None,
    identity_verified: bool = True,
) -> ToolResult:
    """Ask the matrix. Never raises into the caller."""
    from agent_core.authority import recommend_authority

    result = recommend_authority(
        customer_id=customer_id,
        account_id=account_id,
        interaction_id=interaction_id,
        fee_type=fee_type or "late_fee",
        asked_amount=asked_amount,
        identity_verified=identity_verified,
    )
    payload = result.to_tool_payload()
    return ToolResult(
        ok=True,
        data=payload,
        spoken_summary=payload.get("say"),
    )


def apply_goodwill(
    *,
    decision_id: str,
    amount: float | None = None,
    dispute_id: str | None = None,
) -> ToolResult:
    from agent_core.authority import enact as authority_enact
    from agent_core.authority.enact import AuthorityError

    try:
        posted = authority_enact.apply_goodwill(
            decision_id=decision_id,
            amount=amount,
            dispute_id=dispute_id,
        )
    except AuthorityError as exc:
        reason = str(exc)
        return ToolResult(
            ok=False,
            error=reason,
            spoken_summary=(
                "do not confirm a waiver; log a fee_waiver dispute and offer a specialist"
                if reason in {"shadow_mode", "verdict_escalate", "amount_above_cap"}
                else "apologise and offer a specialist callback"
            ),
        )
    except Exception:
        logger.exception("apply_goodwill failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            spoken_summary="apologise and offer a specialist callback",
        )
    return ToolResult(
        ok=True,
        data=posted,
        spoken_summary="confirm the goodwill reversal briefly, without offering more",
        entity="dispute",
        entity_id=posted.get("disputeId"),
        analytics=["goodwill_applied"],
    )


def request_callback(
    *,
    customer_id: str,
    scheduled_at: str,
    interaction_id: str | None = None,
    account_id: str | None = None,
    reason: str | None = None,
    window_mins: int | None = 30,
    priority: str | None = None,
    transcript_snippet: str | None = None,
    idempotency_key: str | None = None,
) -> ToolResult:
    """Schedule a human callback."""
    import db

    when = _parse_scheduled_at(str(scheduled_at or ""))
    if not when:
        return ToolResult(ok=False, error="invalid_scheduled_at")

    window = _clamp_window_mins(window_mins)
    reason_raw = (reason or "general").strip() or "general"
    reason_n = reason_raw if reason_raw in CALLBACK_REASONS else "general"
    prio = priority if priority in {"low", "normal", "high"} else "normal"
    payload: dict[str, Any] = {
        "customerId": customer_id,
        "reason": reason_n,
        "scheduledAt": when,
        "windowMins": window,
        "interactionId": interaction_id,
        "priority": prio,
    }
    if account_id:
        payload["accountId"] = account_id
    if transcript_snippet:
        payload["transcriptSnippet"] = str(transcript_snippet)[:240]

    try:
        row = db.create_callback(payload, idempotency_key=idempotency_key)
    except Exception:
        logger.exception("create_callback failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": "crm_write_failed"},
            spoken_summary="apologise and offer to try again or connect to an agent",
        )

    callback_id, failure = _row_id_or_failure(
        row,
        what="create_callback",
        spoken="apologise and offer to try again or connect to an agent",
    )
    if failure is not None:
        return failure
    return ToolResult(
        ok=True,
        data={
            "callbackId": callback_id,
            "reason": reason_n,
            "windowMins": window,
            "scheduledAt": when,
            "status": _row_field(row, "status"),
        },
        spoken_summary="confirm the callback time briefly",
        entity=_entity("request_callback"),
        entity_id=callback_id,
        deep_link=_link("request_callback", callback_id),
        analytics=["callback_requested"],
    )


def handoff_to_agent(
    *,
    interaction_id: str | None,
    from_bot_id: str | None,
    target_bot_id: str,
    reason: str,
    payload: str | None = None,
    allowlist: set[str] | frozenset[str] | None = None,
) -> ToolResult:
    """Typed agent-to-agent transfer. Prose cannot activate this.

    ``allowlist`` is the publishing card's handoff targets. A missing
    interaction is a soft fail — the model can still speak, but no row moves.
    """
    target = (target_bot_id or "").strip()
    reason_n = (reason or "").strip() or "specialist_needed"
    if not target:
        return ToolResult(ok=False, error="target_bot_required", spoken_summary="stay on this topic")
    if allowlist is not None and target not in allowlist:
        return ToolResult(
            ok=False,
            error="handoff_not_allowlisted",
            data={"targetBotId": target},
            spoken_summary="stay on this topic; do not say you are transferring",
        )
    if not interaction_id:
        return ToolResult(
            ok=False,
            error="no_interaction",
            spoken_summary="stay on this topic",
        )
    try:
        import db

        row = db.handoff_to_agent(
            interaction_id=interaction_id,
            from_bot_id=from_bot_id,
            target_bot_id=target,
            reason=reason_n,
            payload=payload,
        )
    except KeyError:
        return ToolResult(
            ok=False,
            error="bot_not_found",
            data={"targetBotId": target},
            spoken_summary="stay on this topic",
        )
    except ValueError as exc:
        return ToolResult(
            ok=False,
            error=str(exc),
            data={"targetBotId": target},
            spoken_summary="stay on this topic; do not say you are transferring",
        )
    except Exception:
        logger.exception("handoff_to_agent failed ix=%s target=%s", interaction_id, target)
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            spoken_summary="apologise and continue; do not claim a transfer happened",
        )
    return ToolResult(
        ok=True,
        data={
            "fromBotId": row.get("fromBotId"),
            "targetBotId": row.get("targetBotId"),
            "reason": reason_n,
        },
        spoken_summary="one short sentence that a specialist will continue, then stop",
        analytics=["agent_handoff"],
    )
