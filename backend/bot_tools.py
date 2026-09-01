"""Bot tool catalog — CRM reads/writes + structurally gated KB retrieve."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Set as AbstractSet
from typing import Any, Callable

from sqlalchemy import text

import capture
import db
from agent_core.sentiment import estimate_sentiment
from agent_core.tools import domain
from agent_core.tools import kb as kb_tool
from agent_core.tools.catalog import CATALOG

logger = logging.getLogger(__name__)

# Domain soft failures the model can retry against — never raise these.
_CRM_HARD_FAIL = frozenset({"crm_write_failed"})


def _domain_soft_fail(result: domain.ToolResult) -> dict[str, Any] | None:
    """Return structured error payload for validation/soft fails; None if ok.

    Raises ValueError only for unexpected CRM write failures so execute_tool
    still logs a traceback for those.
    """
    if result.ok:
        return None
    err = result.error or "tool_failed"
    if err in _CRM_HARD_FAIL:
        raise ValueError(err)
    out: dict[str, Any] = {"ok": False, "error": err, **(result.data or {})}
    if result.spoken_summary:
        out["say"] = result.spoken_summary
    return out


# KB policy (gate, query steering, retrieval shape, confidence, analytics) lives
# in agent_core.tools.kb so voice and WhatsApp answer the same question the same
# way. Re-exported here because this module is the text channel's public surface.
KB_ALLOWED_INTENTS = kb_tool.KB_ALLOWED_INTENTS
_query_looks_product = kb_tool.query_looks_product
_wants_policy_detail = kb_tool.wants_policy_detail
_wants_coverage_detail = kb_tool.wants_coverage_detail
_wants_activity_eligibility = kb_tool.wants_activity_eligibility
_classify_kb_intent = kb_tool.classify_kb_intent


# Wire contract now comes from the shared catalog so voice and WhatsApp cannot
# drift apart again (they previously disagreed on promise_date/promisedDate,
# dispute_type/type, scheduled_at/scheduledAt, summary/transcriptSnippet).
# execute_tool() normalizes incoming args, so a model that still emits the old
# camelCase names keeps working.
TOOL_DEFINITIONS: list[dict[str, Any]] = CATALOG.openai_tools(
    [
        "get_customer_context",
        "get_payment_history",
        "get_emi_schedule",
        "search_knowledge_base",
        "create_promise_to_pay",
        "flag_dispute",
        "evaluate_authority",
        "apply_goodwill",
        "request_callback",
        "add_customer_note",
        "capture_nonpayment_reason",
        "set_contact_preference",
        "escalate_to_human",
        "handoff_to_agent",
        "recommend_next_offer",
        "check_product_eligibility",
        "capture_lead",
        "decline_offer",
        "request_documents",
        "ingest_customer_document",
        "identify_customer",
        "load_skill",
        "run_skill_script",
    ]
)



def _compact_customer(customer: dict[str, Any]) -> dict[str, Any]:
    contact = customer.get("contact") or {}
    account = customer.get("account") or {}
    consent = customer.get("consent") or []
    wa = next((c for c in consent if (c.get("channel") or "").lower() == "whatsapp"), None)
    promises = customer.get("promises") or []
    disputes = customer.get("disputes") or []
    return {
        "customerId": customer.get("id"),
        "name": customer.get("name"),
        "accountId": customer.get("accountId"),
        "outstanding": customer.get("outstanding"),
        "minimumDue": customer.get("minimumDue"),
        "dpd": account.get("dpd"),
        "product": account.get("product"),
        "bucket": account.get("bucket"),
        "dnd": bool(contact.get("dnd")),
        "preferredWindow": contact.get("preferredWindow"),
        "whatsappOptedIn": bool(wa.get("optedIn")) if wa else None,
        "openPromises": [
            {"id": p.get("id"), "amount": p.get("amount"), "promisedDate": p.get("promisedDate"), "status": p.get("status")}
            for p in promises[:3]
        ],
        "openDisputes": [
            {"id": d.get("id"), "type": d.get("type"), "status": d.get("status")}
            for d in disputes[:3]
            if (d.get("status") or "") not in {"resolved", "rejected"}
        ],
    }


class ToolContext:
    def __init__(
        self,
        *,
        job_id: str,
        conversation_id: str,
        customer_id: str,
        interaction_id: str | None,
        bot_id: str | None,
        customer_text: str,
        intent: str,
        session_intent: str | None = None,
        product_hint: str | None = None,
        sentiment: float | None = None,
    ) -> None:
        self.job_id = job_id
        self.conversation_id = conversation_id
        self.customer_id = customer_id
        self.interaction_id = interaction_id
        self.bot_id = bot_id
        self.customer_text = customer_text
        self.intent = intent
        self.session_intent = session_intent
        self.product_hint = product_hint
        # This turn's sentiment, already classified by the caller. None means
        # "nobody told us", and the tools fall back to the English lexicon —
        # which returns 0.00 for any Hindi or code-switched turn, so the offer
        # engine's sentiment floor would never suppress anything.
        self.sentiment = sentiment
        self.escalated = False
        self.escalate_reason: str | None = None
        # Offer engine bookkeeping for this turn — mirrors ToolState on voice so
        # both channels report outcomes against the same decision log.
        self.offer_decision_id: str | None = None
        self.offered_product_id: str | None = None
        self.offered_product_ids: set[str] = set()
        self.offer_declined = False
        self.offers_presented = 0
        self.authority_decision_id: str | None = None
        # Phase 2 skill intersection. None = legacy unrestricted catalog.
        # Frozen on purpose: the grant arrives from one owner and a caller that
        # could union onto it is how six competing tool formulas happened.
        self.allowed_tools: AbstractSet[str] | None = None
        self.active_skill: str | None = None
        self.attached_skills: list[Any] = []
        # The card this turn is actually running, straight from the deployed
        # bundle. The handoff allowlist reads it here rather than re-resolving
        # from the environment's BOT_ID, which is a different question and, on
        # a clone-card deployment, a different answer.
        self.agent_card: dict[str, Any] | None = None


def _tool_get_customer_context(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    customer = db.get_customer(ctx.customer_id)
    if not customer:
        raise KeyError("customer_not_found")
    out = _compact_customer(customer)
    try:
        # Through the connector registry, not straight at
        # first_party.paylink_status. The registry is where the approval
        # status, the allow-prefixes and the circuit breaker live, and a
        # context read — which happens on every customer the bot touches — is
        # exactly the place a draft, disabled or circuit-open paylink
        # connector must not be able to answer. A rejection degrades to a card
        # with no payLink, the same shape as MCP being switched off.
        from agent_core.connectors.persist import dispatch

        pay = dispatch("ext.paylink.get_status", customer_id=ctx.customer_id)
        if pay.get("ok") is not False and pay.get("status") and pay.get("status") != "none":
            out["payLink"] = pay
    except Exception:
        logger.exception("paylink prefetch failed")
    return out


def _tool_get_payment_history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    customer = db.get_customer(ctx.customer_id)
    if not customer:
        raise KeyError("customer_not_found")
    limit = int(args.get("limit") or 8)
    ledger = list(customer.get("ledger") or [])[:limit]
    return {"accountId": customer.get("accountId"), "entries": ledger}


def _tool_get_emi_schedule(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    customer = db.get_customer(ctx.customer_id)
    if not customer:
        raise KeyError("customer_not_found")
    limit = int(args.get("limit") or 6)
    emi = list(customer.get("emi") or [])[:limit]
    return {"accountId": customer.get("accountId"), "installments": emi}


def _tool_search_knowledge_base(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Thin adapter — gate, steering, retrieval and analytics live in agent_core.tools.kb.

    ``prefer_policy=None`` asks the shared handler to derive steering from the
    customer's own words, which is exactly what this channel did inline before.
    """
    result = kb_tool.search_knowledge_base(
        query=(args.get("query") or "").strip(),
        channel="text",
        # Fall back to the customer turn so follow-ups still retrieve.
        customer_text=ctx.customer_text or "",
        intent=ctx.intent,
        session_intent=ctx.session_intent,
        product_hint=ctx.product_hint,
        interaction_id=ctx.interaction_id,
        bot_id=ctx.bot_id,
    )
    if not result.ok:
        if result.error == "empty_query":
            raise ValueError("query_required")
        return {"ok": False, "error": result.error, **(result.data or {})}
    data = result.data
    if not data.get("available"):
        return data
    # Chunk plumbing stays voice-only (the Inspector consumes it), but the
    # confidence verdict must not be dropped: the shared handler scores every
    # retrieval against KB_CONFIDENCE_THRESHOLD and voice already refuses to
    # answer below it. Text was handed the same weak snippets with no directive
    # at all, so a 0.3-score passage read as ground truth on WhatsApp.
    confident = bool(data.get("confident"))
    return {
        "available": True,
        "intent": data["intent"],
        "queryUsed": data["queryUsed"],
        "results": data["results"],
        "confident": confident,
        "answer_policy": (
            "Answer ONLY from these snippets. If they do not actually answer "
            "what the customer asked, say so and offer request_callback rather "
            "than stretching a related passage into an answer."
            if confident
            else (
                "Retrieval was weak — do NOT answer from these snippets. Tell "
                "the customer a specialist will follow up and offer "
                "request_callback."
            )
        ),
        "logId": data.get("logId"),
    }


def _tool_create_promise(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    idem = f"{ctx.job_id}:create_promise_to_pay"
    # The model can omit a "required" property; a KeyError here would surface as
    # a raw traceback instead of a result the model can correct on the next turn.
    if args.get("amount") in (None, "") or not str(args.get("promise_date") or "").strip():
        return {"ok": False, "error": "amount_and_promise_date_required"}
    result = domain.create_promise_to_pay(
        customer_id=ctx.customer_id,
        amount=args["amount"],
        promised_date=args["promise_date"],
        interaction_id=ctx.interaction_id,
        channel="whatsapp",
        bot_id=ctx.bot_id,
        idempotency_key=idem,
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    return {
        "ok": True,
        "promise": {
            "id": result.data.get("promiseId"),
            "amount": result.data.get("amount"),
            "status": result.data.get("status"),
        },
        "confirmChannel": result.data.get("confirmChannel"),
        "phoneLast4": result.data.get("phoneLast4"),
        "payLinkSent": result.data.get("payLinkSent"),
        "suppressed": result.data.get("suppressed"),
        "say": result.spoken_summary,
    }


def _tool_flag_dispute(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    idem = f"{ctx.job_id}:flag_dispute"
    result = domain.flag_dispute(
        customer_id=ctx.customer_id,
        dispute_type=args.get("dispute_type") or "",
        amount=args.get("amount"),
        summary=args.get("summary") or ctx.customer_text[:240],
        interaction_id=ctx.interaction_id,
        priority="high",
        idempotency_key=idem,
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    return {
        "ok": True,
        "dispute": {
            "id": result.data.get("disputeId"),
            "status": result.data.get("status"),
            "type": result.data.get("type"),
        },
    }


def _tool_evaluate_authority(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = domain.evaluate_authority(
        customer_id=ctx.customer_id,
        fee_type=args.get("fee_type") or "late_fee",
        asked_amount=args.get("asked_amount"),
        interaction_id=ctx.interaction_id,
        identity_verified=True,
    )
    ctx.authority_decision_id = (result.data or {}).get("decisionId")
    return {"ok": True, **(result.data or {})}


def _tool_apply_goodwill(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = domain.apply_goodwill(
        decision_id=str(args.get("decision_id") or ctx.authority_decision_id or ""),
        amount=args.get("amount"),
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    return {"ok": True, **(result.data or {}), "say": result.spoken_summary}


def _tool_request_callback(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    result = domain.request_callback(
        customer_id=ctx.customer_id,
        reason=args.get("reason") or "general",
        scheduled_at=args.get("scheduled_at") or "",
        window_mins=args.get("window_mins") or 30,
        interaction_id=ctx.interaction_id,
        transcript_snippet=ctx.customer_text[:240],
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    return {
        "ok": True,
        "callback": {
            "id": result.data.get("callbackId"),
            "reason": result.data.get("reason"),
            "scheduledAt": result.data.get("scheduledAt"),
            "windowMins": result.data.get("windowMins"),
            "status": result.data.get("status"),
        },
    }


def _tool_add_note(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    db.add_customer_note(ctx.customer_id, {"text": args["text"], "pinned": bool(args.get("pinned"))})
    return {"ok": True}


def _tool_capture_nonpayment_reason(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Record why the customer has not paid, as a code.

    The code's real home is ``bot_tool_calls.args``, which the text runtime
    already persists and which the post-call Closer reads — so this handler's
    only job is to validate against the closed vocabulary and leave a note a
    human can read on the file. A reason outside the list is rejected rather
    than stored: the entire value of the field is that you can group by it.
    """
    from agent_core.tools.catalog import NONPAYMENT_REASONS

    reason = str(args.get("reason") or "").strip()
    if reason not in NONPAYMENT_REASONS:
        return {"error": "unknown_reason", "allowed": list(NONPAYMENT_REASONS)}
    note = str(args.get("verbatim") or "").strip()
    db.add_customer_note(
        ctx.customer_id,
        {"text": f"[reason: {reason}]" + (f" {note[:500]}" if note else "")},
    )
    return {"ok": True, "reason": reason}


def _tool_set_contact_preference(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Narrow the hours we may call this customer, because they said so.

    Same semantics as the voice handler and for the same reason: the window the
    dialler obeys is read from the consent record, so a restriction stated in
    chat has to land in the same column a restriction stated on the phone lands
    in, or the two channels disagree about the same borrower.
    """
    import contact_policy

    with db.engine.begin() as conn:
        outcome = contact_policy.narrow_window(
            conn,
            customer_id=ctx.customer_id,
            earliest_hour=args.get("earliest_hour"),
            latest_hour=args.get("latest_hour"),
            source="chat",
            note=str(args.get("verbatim") or "")[:500] or None,
        )
    if not outcome.get("ok"):
        return {"ok": False, "reason": outcome.get("reason")}
    return {"ok": True, "window": outcome.get("window")}


def _tool_escalate(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    reason = (args.get("reason") or "escalated_by_bot").strip()
    db.escalate_conversation_to_human(ctx.conversation_id, reason=reason)
    ctx.escalated = True
    ctx.escalate_reason = reason
    return {"ok": True, "status": "needs_human", "reason": reason}


def _handoff_allowlist(ctx: ToolContext) -> set[str]:
    """Which bots this turn is permitted to transfer to.

    Two ways this control used to evaporate. It resolved the card from the
    environment's ``BOT_ID`` rather than the card the turn was running, so a
    clone-card deployment enforced the wrong card's targets; and when the id
    resolved to no card at all it returned ``None``, which
    ``domain.handoff_to_agent`` reads as *unrestricted*. The check therefore
    disabled itself at precisely the moment identity was misconfigured.

    Resolution order is live card → built-in card → deny. Denying is the safe
    end: the model stays on topic and ``escalate_to_human`` is still there.
    """
    from agent_core.cards.defaults import card_for
    from agent_core.cards.schema import parse_card

    if ctx.agent_card:
        try:
            return set(parse_card(ctx.agent_card).handoff_targets())
        except Exception:
            logger.warning("handoff allowlist: live card unreadable, falling back to built-in")

    if ctx.bot_id:
        try:
            return set(card_for(ctx.bot_id).handoff_targets())
        except KeyError:
            logger.warning(
                "handoff allowlist: no card for bot_id=%s — denying every target", ctx.bot_id
            )
    return set()


def _tool_handoff_to_agent(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    target = str(args.get("target_bot_id") or "").strip()
    reason = str(args.get("reason") or "").strip()
    payload = args.get("payload")
    allowlist = _handoff_allowlist(ctx)
    result = domain.handoff_to_agent(
        interaction_id=ctx.interaction_id,
        from_bot_id=ctx.bot_id,
        target_bot_id=target,
        reason=reason,
        payload=str(payload) if payload is not None else None,
        allowlist=allowlist,
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    ctx.bot_id = target
    return result.to_llm()


def _tool_recommend_next_offer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Ask the engine what may be offered. Same pipeline as voice."""
    from agent_core.reco import engine as reco_engine
    from agent_core.reco.features import CallSignals

    result = reco_engine.recommend(
        customer_id=ctx.customer_id,
        interaction_id=ctx.interaction_id,
        channel="whatsapp",
        live=CallSignals(
            interaction_id=ctx.interaction_id,
            channel="whatsapp",
            intents_seen=(ctx.intent,) if ctx.intent else (),
            dominant_intent=ctx.session_intent or ctx.intent,
            sentiment_current=(
                ctx.sentiment
                if ctx.sentiment is not None
                else estimate_sentiment(ctx.customer_text or "")
            ),
            # Text has no PTP-before-pitch graph, so the commitment gate would
            # suppress every chat offer. The channel is asynchronous and
            # interruption-free, which is what that gate exists to protect
            # against on a live call.
            commitment_secured=True,
            escalation_flagged=ctx.escalated,
            offer_declined_this_call=ctx.offer_declined,
            offers_presented_this_call=ctx.offers_presented,
        ),
    )
    ctx.offer_decision_id = result.decision_id
    payload = result.to_tool_payload()
    if result.suppressed or not result.offers:
        payload["say"] = "do not mention any product; continue with the conversation"
        return payload

    top = result.top
    ctx.offered_product_id = top.product_id
    # Every returned offer is admissible, not just the top one — the model may
    # legitimately pick the second if the customer steers it there.
    ctx.offered_product_ids.update(o.product_id for o in result.offers)
    ctx.offers_presented += 1
    try:
        reco_engine.present(result.decision_id, top.product_id)
        domain.mark_upsell_presented(
            interaction_id=ctx.interaction_id,
            product_id=top.product_id,
            bot_id=ctx.bot_id,
        )
    except Exception:
        logger.exception("marking offer presented failed")
    payload["say"] = (
        "mention this ONE product in a single short sentence with the indicative "
        "amount, then ask if they would like a specialist to explain it"
    )
    return payload


def _tool_decline_offer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Record a refusal so the same product is not raised again."""
    from agent_core.reco import decisions

    ctx.offer_declined = True
    reason = (args.get("reason") or "").strip() or None
    if ctx.offer_decision_id:
        decisions.record_response(ctx.offer_decision_id, "declined")
    try:
        with db.engine.begin() as conn:
            capture.record_offer_declined(
                conn,
                interaction_id=ctx.interaction_id,
                customer_id=ctx.customer_id,
                product_id=ctx.offered_product_id,
                reason=reason,
                actor_bot_id=ctx.bot_id,
            )
    except Exception:
        logger.exception("record_offer_declined failed")
    return {"ok": True, "say": "acknowledge briefly and move on; do not raise it again"}


def _tool_check_product_eligibility(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Re-confirm an offer the engine already made. Cannot introduce a product."""
    product_id = (args.get("product_id") or "").strip()
    violation = domain.offer_sourcing_violation(product_id, ctx.offered_product_ids)
    if violation is not None:
        return _domain_soft_fail(violation) or {"ok": False, "error": "product_not_offered"}
    result = domain.check_product_eligibility(
        customer_id=ctx.customer_id,
        product_id=product_id,
        interaction_id=ctx.interaction_id,
        bot_id=ctx.bot_id,
        channel="whatsapp",
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    return {"ok": True, **result.data}


def _tool_capture_lead(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Delegates to the shared handler (same eligibility gate, same lead row)."""
    product_id = (args.get("product_id") or "").strip()
    offer_id = str(args.get("offer_id") or "").strip()
    decision_id = ctx.offer_decision_id
    if offer_id and ":" in offer_id:
        offer_decision, offer_product = offer_id.split(":", 1)
        if offer_product and offer_product != product_id:
            logger.warning(
                "capture_lead offer/product mismatch: offer=%s product=%s — trusting the offer",
                offer_id,
                product_id,
            )
            product_id = offer_product
        decision_id = offer_decision or decision_id

    violation = domain.offer_sourcing_violation(product_id, ctx.offered_product_ids)
    if violation is not None:
        return _domain_soft_fail(violation) or {"ok": False, "error": "product_not_offered"}

    result = domain.capture_lead(
        customer_id=ctx.customer_id,
        product_id=product_id,
        interaction_id=ctx.interaction_id,
        bot_id=ctx.bot_id,
        offer_amount=args.get("offer_amount"),
        summary=args.get("summary"),
        priority=args.get("priority"),
        source="bot_chat",
        customer_text=ctx.customer_text or "",
        channel="whatsapp",
        # Stable per (conversation, customer, product) so a retried job cannot
        # create a second identical lead.
        idempotency_key=f"chat-lead:{ctx.conversation_id}:{ctx.customer_id}:{product_id}",
        decision_id=decision_id,
        # Otherwise the lead is scored by the English lexicon and every lead
        # from a Hindi caller reaches the rep marked "neutral".
        sentiment_score=ctx.sentiment,
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    payload: dict[str, Any] = {"ok": True, **result.data}
    if result.deep_link:
        payload["deepLink"] = result.deep_link
    return payload


def _tool_request_documents(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Raise a document request — the tool voice already had and chat did not."""
    result = domain.request_documents(
        customer_id=ctx.customer_id,
        document_type=(args.get("document_type") or "").strip(),
        interaction_id=ctx.interaction_id,
        delivery_channel=args.get("delivery_channel"),
        period=args.get("period"),
        requested_via="bot_chat",
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    payload: dict[str, Any] = {"ok": True, **result.data}
    if result.deep_link:
        payload["deepLink"] = result.deep_link
    return payload


def _tool_ingest_customer_document(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agent_core.vision import ingest_customer_document

    result = ingest_customer_document(
        customer_id=ctx.customer_id,
        filename=(args.get("filename") or "").strip(),
        mime_type=(args.get("mime_type") or "").strip(),
        identity_verified=bool(ctx.customer_id) and ctx.customer_id != "UNKNOWN-CALLER",
        interaction_id=ctx.interaction_id,
        requested_via="bot_chat",
    )
    if not result.ok:
        return {"ok": False, "error": result.error}
    payload: dict[str, Any] = {"ok": True, **result.data}
    if result.deep_link:
        payload["deepLink"] = result.deep_link
    return payload


def _thread_phone_digits(conn: Any, conversation_id: str) -> str:
    """Digits of the phone number this WhatsApp thread is bound to.

    The inbound webhook resolves the customer from the sender's number, so the
    bound customer's phone is the number the peer demonstrably controls.
    """
    import re

    row = conn.execute(
        text(
            """
            SELECT c.phone_primary
            FROM conversations cv
            JOIN customers c ON c.id = cv.customer_id
            WHERE cv.id = :id
            """
        ),
        {"id": conversation_id},
    ).mappings().first()
    return re.sub(r"\D", "", str((row or {}).get("phone_primary") or ""))


def _tool_identify_customer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Verify/rebind the interaction to a customer by phone or account tail.

    Hard constraint: identification may only ever resolve to the customer who
    owns the number this thread is running on. The caller controls the WhatsApp
    number, nothing else — so a supplied phone must equal the thread's number,
    and an account tail (4 digits, trivially guessable) is accepted only as a
    *second factor* confirming that same customer. Without this, anyone could
    message the bot and enumerate account tails to read another customer's
    balance, EMI schedule and payment history.
    """
    import capture
    import re

    if not ctx.interaction_id:
        raise ValueError("interaction_id_required")

    phone = (args.get("phone") or "").strip()
    account_tail = (args.get("account_tail") or "").strip()
    if not phone and not account_tail:
        raise ValueError("phone_or_account_tail_required")

    with db.engine.begin() as conn:
        thread_digits = _thread_phone_digits(conn, ctx.conversation_id)
        matched = None
        method = "manual"
        if phone:
            digits = re.sub(r"\D", "", phone)
            method = "phone_match"
            if thread_digits and digits and digits[-10:] == thread_digits[-10:]:
                matched = db._find_customer_by_phone(conn, digits)
            else:
                logger.warning(
                    "identify_customer rejected phone not matching thread "
                    "conversation=%s",
                    ctx.conversation_id,
                )
        if matched is None and account_tail:
            method = "account_tail"
            candidate = capture.find_customer_by_account_tail(conn, account_tail)
            candidate_digits = re.sub(r"\D", "", str((candidate or {}).get("phone_primary") or ""))
            if (
                candidate is not None
                and thread_digits
                and candidate_digits
                and candidate_digits[-10:] == thread_digits[-10:]
            ):
                matched = candidate
            elif candidate is not None:
                logger.warning(
                    "identify_customer rejected account_tail for a customer that does "
                    "not own this thread's number conversation=%s",
                    ctx.conversation_id,
                )
        if matched is None:
            capture.record_identity_failed(
                conn,
                interaction_id=ctx.interaction_id,
                reason="no_customer_match",
                method=method,
                actor_bot_id=ctx.bot_id,
            )
            return {"ok": False, "error": "customer_not_found", "method": method}

        account_id = matched.get("account_id")
        result = capture.rebind_interaction_customer(
            conn,
            interaction_id=ctx.interaction_id,
            customer_id=matched["id"],
            method=method,
            account_id=account_id,
            actor_bot_id=ctx.bot_id,
        )
        # Subsequent tools in this turn see the rebound customer.
        ctx.customer_id = matched["id"]
        return {"ok": True, **result}


def _tool_load_skill(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agent_core.skills.runtime import load_skill

    slug = str(args.get("slug") or "").strip()
    include_refs = bool(args.get("include_references"))
    result = load_skill(slug, list(ctx.attached_skills or []), include_references=include_refs)
    if result.get("ok"):
        ctx.active_skill = slug
    return {k: v for k, v in result.items() if k != "message"} | (
        {"body_loaded": True} if result.get("ok") else {}
    )


def _tool_run_skill_script(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    from agent_core.skills.scripts import run_script

    name = str(args.get("name") or "").strip()
    payload = args.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return {"ok": False, "error": "payload_must_be_json_object"}
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload_must_be_object"}
    return run_script(name, payload)


HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], dict[str, Any]]] = {
    "get_customer_context": _tool_get_customer_context,
    "get_payment_history": _tool_get_payment_history,
    "get_emi_schedule": _tool_get_emi_schedule,
    "search_knowledge_base": _tool_search_knowledge_base,
    "create_promise_to_pay": _tool_create_promise,
    "flag_dispute": _tool_flag_dispute,
    "evaluate_authority": _tool_evaluate_authority,
    "apply_goodwill": _tool_apply_goodwill,
    "request_callback": _tool_request_callback,
    "add_customer_note": _tool_add_note,
    "capture_nonpayment_reason": _tool_capture_nonpayment_reason,
    "set_contact_preference": _tool_set_contact_preference,
    "escalate_to_human": _tool_escalate,
    "handoff_to_agent": _tool_handoff_to_agent,
    "recommend_next_offer": _tool_recommend_next_offer,
    "check_product_eligibility": _tool_check_product_eligibility,
    "capture_lead": _tool_capture_lead,
    "decline_offer": _tool_decline_offer,
    "request_documents": _tool_request_documents,
    "ingest_customer_document": _tool_ingest_customer_document,
    "identify_customer": _tool_identify_customer,
    "load_skill": _tool_load_skill,
    "run_skill_script": _tool_run_skill_script,
}


def execute_tool(ctx: ToolContext, name: str, arguments_json: str) -> tuple[bool, dict[str, Any], int]:
    t0 = time.perf_counter()
    try:
        args = json.loads(arguments_json or "{}")
        if not isinstance(args, dict):
            raise ValueError("tool_args_must_be_object")
    except json.JSONDecodeError as exc:
        latency = int((time.perf_counter() - t0) * 1000)
        return False, {"error": f"invalid_json_args: {exc}"}, latency

    if ctx.allowed_tools is not None and name not in ctx.allowed_tools:
        latency = int((time.perf_counter() - t0) * 1000)
        return False, {"error": "tool_not_on_card_or_skill", "tool": name}, latency

    if name.startswith("ext."):
        from agent_core.connectors.persist import dispatch

        try:
            # The model's own arguments travel with the call. Dropping them
            # meant every remote MCP tool with a second parameter ran on its
            # defaults — the caller asked for one invoice and got whatever the
            # remote picked.
            result = dispatch(name, customer_id=ctx.customer_id, args=args)
            latency = int((time.perf_counter() - t0) * 1000)
            ok = not (isinstance(result, dict) and result.get("ok") is False)
            return ok, result, latency
        except Exception:
            logger.exception("connector tool failed · %s", name)
            latency = int((time.perf_counter() - t0) * 1000)
            return False, {"error": "connector_call_failed"}, latency

    handler = HANDLERS.get(name)
    if handler is None:
        latency = int((time.perf_counter() - t0) * 1000)
        return False, {"error": f"unknown_tool: {name}"}, latency

    # Canonicalize to snake_case. A model replaying an older conversation may
    # still emit promisedDate / scheduledAt / productId; the catalog's aliases
    # map those onto the names the handlers below read.
    args = CATALOG.normalize(name, args)

    try:
        result = handler(ctx, args)
        latency = int((time.perf_counter() - t0) * 1000)
        if isinstance(result, dict) and result.get("ok") is False:
            logger.warning(
                "tool %s rejected · error=%s",
                name,
                result.get("error"),
            )
            return False, result, latency
        return True, result, latency
    except ValueError as exc:
        # Handlers raise ValueError with their own stable, model-facing codes
        # ("query_required", "phone_or_account_tail_required") — the model is
        # meant to read and correct those.
        logger.warning("tool %s rejected args · error=%s", name, exc)
        latency = int((time.perf_counter() - t0) * 1000)
        return False, {"error": str(exc)}, latency
    except Exception as exc:
        # Anything else is a driver/runtime failure whose str() can carry SQL
        # parameters, connection strings or stack context. It was returned to
        # the model *and* persisted to bot_tool_calls.error, which the Inbox
        # renders. Log it in full; hand back a stable code.
        logger.exception("tool %s failed", name)
        latency = int((time.perf_counter() - t0) * 1000)
        return False, {"error": f"tool_failed:{type(exc).__name__}"}, latency
