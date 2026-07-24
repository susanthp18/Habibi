"""Bot tool catalog — CRM reads/writes + structurally gated KB retrieve."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

import db
from agent_core.intent import classify_intent, resolve_intent
from agent_core.tools import domain
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


# Intents allowed to call search_knowledge_base (insurance/product corpus).
# Collections money questions must use CRM tools, not HL Assurance chunks.
KB_ALLOWED_INTENTS = frozenset(
    {
        "product_faq",
        "upsell_opportunity",
    }
)

_PRODUCT_QUERY_HINTS = (
    "insurance",
    "policy",
    "coverage",
    "exclu",
    "invalid",
    "benefit",
    "claim",
    "premium",
    "protect360",
    "travel",
    "plan",
    "covered",
    "wording",
    "terms",
)


def _query_looks_product(query: str) -> bool:
    t = (query or "").lower()
    return any(h in t for h in _PRODUCT_QUERY_HINTS)


def _wants_policy_detail(query: str) -> bool:
    t = (query or "").lower()
    return any(
        h in t
        for h in (
            "exclu",
            "invalid",
            "not covered",
            "list all",
            "tell me all",
            "see and tell",
            "full list",
            "all details",
            "more details",
            "in detail",
            "complete list",
            "all conditions",
            "policy wording",
            "terms and conditions",
            "what voids",
            "when is it void",
        )
    )


def _wants_coverage_detail(query: str) -> bool:
    """Coverage / benefits questions — should not be steered into exclusions-only retrieve."""
    t = (query or "").lower()
    if _wants_policy_detail(t):
        return False
    # "Is scuba diving covered?" needs exclusions + conditions, not benefits-only.
    if any(
        a in t
        for a in (
            "scuba",
            "diving",
            "bungee",
            "rafting",
            "ski",
            "racing",
            "extreme",
            "sport",
        )
    ) and any(c in t for c in ("cover", "covered", "allow", "permitted", "can i")):
        return False
    return any(
        h in t
        for h in (
            "cover",
            "coverage",
            "benefit",
            "medical",
            "hospital",
            "cancel",
            "cancellation",
            "postpon",
            "baggage",
            "delay",
            "what does it",
            "include",
            "overseas",
        )
    )


def _wants_activity_eligibility(query: str) -> bool:
    t = (query or "").lower()
    return any(
        a in t
        for a in (
            "scuba",
            "diving",
            "bungee",
            "rafting",
            "ski",
            "racing",
            "extreme",
            "underwater",
        )
    ) and any(c in t for c in ("cover", "covered", "allow", "permitted", "can i", "claim"))

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
        "request_callback",
        "add_customer_note",
        "escalate_to_human",
        "check_product_eligibility",
        "capture_lead",
        "request_documents",
        "identify_customer",
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
        self.escalated = False
        self.escalate_reason: str | None = None


def _kb_gate_allows(ctx: ToolContext, query: str) -> tuple[bool, str]:
    """Structural gate: block collections money intents; allow product threads + product queries."""
    intent = ctx.intent or ""
    session = ctx.session_intent or ""
    if intent in KB_ALLOWED_INTENTS:
        return True, intent
    if session in KB_ALLOWED_INTENTS:
        return True, session
    if _query_looks_product(query) or _query_looks_product(ctx.customer_text):
        return True, intent or session or "product_faq"
    # Still blocked for pure collections intents with no product signal.
    return False, intent or session or "unknown"


def _expand_kb_query(ctx: ToolContext, query: str) -> str:
    """Enrich vague follow-ups with product/topic context so ANN hits policy docs."""
    parts = [query.strip()]
    if ctx.product_hint and ctx.product_hint.lower() not in query.lower():
        parts.append(ctx.product_hint)
    # Steer by what the *customer* asked — not by noisy tool-arg padding.
    cust = ctx.customer_text or ""
    if (
        _wants_policy_detail(cust)
        or _wants_activity_eligibility(cust)
        or (
            _wants_policy_detail(query)
            and not _wants_coverage_detail(cust)
            and not _wants_activity_eligibility(cust)
        )
    ):
        parts.append("policy exclusions invalidation conditions not covered")
        if _wants_activity_eligibility(cust) or _wants_activity_eligibility(query):
            parts.append("leisure scuba diving underwater breathing apparatus conditions")
    elif _wants_coverage_detail(cust) or _wants_coverage_detail(query):
        parts.append("benefits coverage section conditions")
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        key = p.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(p)
    return " — ".join(out)


def _tool_get_customer_context(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    customer = db.get_customer(ctx.customer_id)
    if not customer:
        raise KeyError("customer_not_found")
    return _compact_customer(customer)


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
    query = (args.get("query") or "").strip()
    if not query:
        # Fall back to the customer turn so follow-ups still retrieve.
        query = (ctx.customer_text or "").strip()
    if not query:
        raise ValueError("query_required")

    allowed, gate_intent = _kb_gate_allows(ctx, query)
    if not allowed:
        return {
            "available": False,
            "reason": "kb_gated_for_intent",
            "intent": gate_intent,
            "message": (
                "Knowledge base is not available for this collections intent. "
                "Use get_customer_context / get_emi_schedule / get_payment_history "
                "for money facts, or escalate_to_human for policy exceptions."
            ),
            "results": [],
        }

    expanded = _expand_kb_query(ctx, query)
    prefer_policy = (
        _wants_policy_detail(ctx.customer_text)
        or _wants_activity_eligibility(ctx.customer_text)
        or (
            _wants_policy_detail(expanded)
            and not _wants_coverage_detail(ctx.customer_text)
        )
    )
    import kb_retrieve

    raw = kb_retrieve.retrieve(
        query=expanded,
        top_k=8 if prefer_policy else 6,
        include_draft_answer=False,
        source="bot",
        prefer_policy=prefer_policy,
    )
    results = []
    for r in raw.get("results") or []:
        snippet = (r.get("snippet") or "").strip()
        # Cap high enough to carry real exclusion lists, not just one line.
        cap = 2000 if prefer_policy else 1400
        results.append(
            {
                "docTitle": r.get("docTitle") or r.get("docId"),
                "docType": r.get("docType"),
                "heading": r.get("heading"),
                "snippet": snippet[:cap],
                "score": r.get("score"),
            }
        )
    # Product KB answer with hits ⇒ upsell/cross-sell was presented (Phase 0/1).
    if results and ctx.interaction_id and (
        gate_intent in {"product_faq", "upsell_opportunity"}
        or (ctx.session_intent or "") in {"product_faq", "upsell_opportunity"}
    ):
        try:
            import capture

            with db.engine.begin() as conn:
                capture.record_offer_presented(
                    conn,
                    interaction_id=ctx.interaction_id,
                    product_id=None,
                    source="kb",
                    actor_bot_id=ctx.bot_id,
                )
                capture.touch_primary_intent(
                    conn,
                    ctx.interaction_id,
                    gate_intent
                    if gate_intent in {"product_faq", "upsell_opportunity"}
                    else "product_faq",
                )
        except Exception:
            logger.exception("mark_upsell_presented failed")
    return {
        "available": True,
        "intent": gate_intent,
        "queryUsed": expanded,
        "results": results,
        "logId": raw.get("logId"),
    }


def _tool_create_promise(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    idem = f"{ctx.job_id}:create_promise_to_pay"
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


def _tool_escalate(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    reason = (args.get("reason") or "escalated_by_bot").strip()
    db.escalate_conversation_to_human(ctx.conversation_id, reason=reason)
    ctx.escalated = True
    ctx.escalate_reason = reason
    return {"ok": True, "status": "needs_human", "reason": reason}


def _tool_check_product_eligibility(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Delegates to the shared handler so voice and WhatsApp apply identical rules."""
    result = domain.check_product_eligibility(
        customer_id=ctx.customer_id,
        product_id=(args.get("product_id") or "").strip(),
        interaction_id=ctx.interaction_id,
        bot_id=ctx.bot_id,
    )
    soft = _domain_soft_fail(result)
    if soft is not None:
        return soft
    return {"ok": True, **result.data}


def _tool_capture_lead(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Delegates to the shared handler (same eligibility gate, same lead row)."""
    result = domain.capture_lead(
        customer_id=ctx.customer_id,
        product_id=(args.get("product_id") or "").strip(),
        interaction_id=ctx.interaction_id,
        bot_id=ctx.bot_id,
        offer_amount=args.get("offer_amount"),
        summary=args.get("summary"),
        priority=args.get("priority"),
        source="bot_chat",
        customer_text=ctx.customer_text or "",
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


def _tool_identify_customer(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    """Verify/rebind the interaction to a customer by phone or account tail."""
    import capture
    import re

    if not ctx.interaction_id:
        raise ValueError("interaction_id_required")

    phone = (args.get("phone") or "").strip()
    account_tail = (args.get("account_tail") or "").strip()
    if not phone and not account_tail:
        raise ValueError("phone_or_account_tail_required")

    with db.engine.begin() as conn:
        matched = None
        method = "manual"
        if phone:
            digits = re.sub(r"\D", "", phone)
            matched = db._find_customer_by_phone(conn, digits)
            method = "phone_match"
        if matched is None and account_tail:
            matched = capture.find_customer_by_account_tail(conn, account_tail)
            method = "account_tail"
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


HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], dict[str, Any]]] = {
    "get_customer_context": _tool_get_customer_context,
    "get_payment_history": _tool_get_payment_history,
    "get_emi_schedule": _tool_get_emi_schedule,
    "search_knowledge_base": _tool_search_knowledge_base,
    "create_promise_to_pay": _tool_create_promise,
    "flag_dispute": _tool_flag_dispute,
    "request_callback": _tool_request_callback,
    "add_customer_note": _tool_add_note,
    "escalate_to_human": _tool_escalate,
    "check_product_eligibility": _tool_check_product_eligibility,
    "capture_lead": _tool_capture_lead,
    "request_documents": _tool_request_documents,
    "identify_customer": _tool_identify_customer,
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
        return True, result, latency
    except Exception as exc:
        logger.exception("tool %s failed", name)
        latency = int((time.perf_counter() - t0) * 1000)
        return False, {"error": str(exc)}, latency
