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
from datetime import date, datetime
from typing import Any

from agent_core.tools.catalog import CALLBACK_REASONS, CATALOG, DISPUTE_TYPES

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

    def to_llm(self) -> dict[str, Any]:
        """Payload handed back to the model — deliberately compact."""
        out: dict[str, Any] = {"ok": self.ok, **self.data}
        if self.error:
            out["error"] = self.error
        if self.spoken_summary:
            out["say"] = self.spoken_summary
        return out


def _link(tool_name: str, entity_id: str | None) -> str | None:
    spec = CATALOG.get(tool_name)
    return spec.link_for(entity_id) if spec else None


def _entity(tool_name: str) -> str | None:
    spec = CATALOG.get(tool_name)
    return spec.entity if spec else None


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


def _parse_scheduled_at(raw: str) -> str | None:
    """Accept ISO datetime (with optional Z); return canonical string or None."""
    when = (raw or "").strip()
    if not when:
        return None
    try:
        datetime.fromisoformat(when.replace("Z", "+00:00"))
    except Exception:
        return None
    return when


def _clamp_window_mins(window_mins: Any) -> int:
    try:
        window = int(window_mins if window_mins is not None else 30)
    except (TypeError, ValueError):
        window = 30
    return max(15, min(120, window))


# ---------------------------------------------------------------------------
# Upsell
# ---------------------------------------------------------------------------


def check_product_eligibility(
    *,
    customer_id: str,
    product_id: str,
    interaction_id: str | None = None,
    bot_id: str | None = None,
) -> ToolResult:
    """Evaluate live eligibility and record the check as a commercial event."""
    import capture
    import db
    from sqlalchemy import text

    pid = (product_id or "").strip()
    if not pid:
        return ToolResult(ok=False, error="product_id_required")

    with db.engine.begin() as conn:
        product = (
            conn.execute(
                text("SELECT id, name, roi FROM products WHERE id = :id"), {"id": pid}
            )
            .mappings()
            .first()
        )
        if product is None:
            return ToolResult(
                ok=False,
                error="product_not_found",
                data={"productId": pid},
            )
        flags = capture.evaluate_product_eligibility(
            conn, customer_id=customer_id, product_id=pid
        )
        block = capture.eligibility_blocks_capture(flags)
        capture.record_eligibility_checked(
            conn,
            interaction_id=interaction_id,
            customer_id=customer_id,
            product_id=pid,
            flags=flags,
            blocked=block,
            actor_bot_id=bot_id,
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
) -> ToolResult:
    """Re-check eligibility, then write the lead row and its commercial events."""
    import capture
    import db
    from agent_core.sentiment import estimate_sentiment, sentiment_label
    from sqlalchemy import text

    pid = (product_id or "").strip()
    if not pid:
        return ToolResult(ok=False, error="product_id_required")

    with db.engine.begin() as conn:
        product = (
            conn.execute(
                text("SELECT id, name, roi FROM products WHERE id = :id"), {"id": pid}
            )
            .mappings()
            .first()
        )
        if product is None:
            return ToolResult(ok=False, error="product_not_found", data={"productId": pid})
        flags = capture.evaluate_product_eligibility(
            conn, customer_id=customer_id, product_id=pid
        )
        block = capture.eligibility_blocks_capture(flags)
        capture.record_eligibility_checked(
            conn,
            interaction_id=interaction_id,
            customer_id=customer_id,
            product_id=pid,
            flags=flags,
            blocked=block,
            actor_bot_id=bot_id,
        )
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

    text_for_sentiment = summary or customer_text or ""
    score = estimate_sentiment(text_for_sentiment)
    prio = priority if priority in {"low", "normal", "high"} else "normal"

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
        "estimatedValue": offer_amount,
        "priority": prio,
        "eligibilityFlags": flags,
    }
    lead = db.create_lead(payload)
    lead_id = str(lead.get("id")) if lead.get("id") else None

    try:
        with db.engine.begin() as conn:
            capture.record_lead_captured(
                conn,
                interaction_id=interaction_id,
                lead_id=lead_id,
                product_id=pid,
                actor_bot_id=bot_id,
            )
            if interaction_id:
                capture.record_offer_presented(
                    conn,
                    interaction_id=interaction_id,
                    product_id=pid,
                    source="capture_lead",
                    actor_bot_id=bot_id,
                )
    except Exception:
        # The lead row is the durable artifact; analytics events must not undo it.
        logger.exception("lead_captured event failed")

    return ToolResult(
        ok=True,
        data={
            "leadId": lead_id,
            "stage": lead.get("stage"),
            "productId": pid,
            "productName": product.get("name"),
        },
        spoken_summary="confirm briefly that a specialist will share the details",
        entity=_entity("capture_lead"),
        entity_id=lead_id,
        deep_link=_link("capture_lead", lead_id),
        analytics=["upsell_presented", "lead_captured"],
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
) -> ToolResult:
    """Raise a document request row that Operations fulfils."""
    import db

    dtype = (document_type or "").strip()
    if not dtype:
        return ToolResult(ok=False, error="document_type_required")

    payload: dict[str, Any] = {
        "customerId": customer_id,
        "accountId": account_id,
        "interactionId": interaction_id,
        "docType": dtype,
        "requestedVia": requested_via,
    }
    if delivery_channel:
        payload["deliveryChannel"] = delivery_channel
    if period:
        payload["period"] = period

    try:
        row = db.create_document_request(payload)
    except Exception as exc:
        logger.exception("create_document_request failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": str(exc)},
            spoken_summary="apologise and offer a callback so an agent can send it",
        )

    doc_id = str(row.get("id")) if row.get("id") else None
    return ToolResult(
        ok=True,
        data={
            "documentRequestId": doc_id,
            "documentType": row.get("docType") or dtype,
            "deliveryChannel": row.get("deliveryChannel"),
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
        except KeyError:
            # Some environments reject ownerBotId — retry without it.
            payload.pop("ownerBotId", None)
            row = db.create_promise(payload, idempotency_key=idempotency_key)
    except Exception as exc:
        logger.exception("create_promise failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": str(exc)},
            spoken_summary="apologise and offer a callback or human agent",
        )

    promise_id = str(row.get("id")) if row.get("id") else None
    if interaction_id:
        try:
            with db.engine.begin() as conn:
                capture.mark_ptp_captured(conn, interaction_id)
        except Exception:
            logger.exception("mark_ptp_captured failed")

    return ToolResult(
        ok=True,
        data={
            "promiseId": promise_id,
            "amount": row.get("amount", amt),
            "promisedDate": date_s,
            "status": row.get("status"),
        },
        spoken_summary="confirm the amount and date back to them",
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
    except Exception as exc:
        logger.exception("create_dispute failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": str(exc)},
            spoken_summary="apologise and offer a callback or human agent",
        )

    dispute_id = str(row.get("id")) if row.get("id") else None
    return ToolResult(
        ok=True,
        data={
            "disputeId": dispute_id,
            "type": row.get("type") or dtype,
            "status": row.get("status"),
        },
        spoken_summary="a specialist will follow up",
        entity=_entity("flag_dispute"),
        entity_id=dispute_id,
        deep_link=_link("flag_dispute", dispute_id),
        analytics=["dispute_flagged"],
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
        row = db.create_callback(payload)
    except Exception as exc:
        logger.exception("create_callback failed")
        return ToolResult(
            ok=False,
            error="crm_write_failed",
            data={"detail": str(exc)},
            spoken_summary="apologise and offer to try again or connect to an agent",
        )

    callback_id = str(row.get("id")) if row.get("id") else None
    return ToolResult(
        ok=True,
        data={
            "callbackId": callback_id,
            "reason": reason_n,
            "windowMins": window,
            "scheduledAt": when,
            "status": row.get("status") if isinstance(row, dict) else None,
        },
        spoken_summary="confirm the callback time briefly",
        entity=_entity("request_callback"),
        entity_id=callback_id,
        deep_link=_link("request_callback", callback_id),
        analytics=["callback_requested"],
    )
