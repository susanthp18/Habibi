"""Keyword intent classifier — shared across sandbox, WhatsApp, and voice."""

from __future__ import annotations

INTENT_KEYWORDS: dict[str, list[str]] = {
    "balance_query": ["balance", "outstanding", "how much", "what do i owe", "dues", "emi", "late fee", "penalty"],
    "dispute": ["dispute", "didn't make", "not me", "unauthorised", "unauthorized", "wrong charge", "chargeback"],
    "hardship": ["job", "lost", "cannot pay", "can't pay", "difficult", "hardship", "defer", "restructure", "tenure"],
    "waiver_request": ["waive", "waiver", "remove fee", "cancel fee", "goodwill"],
    "payment_intent": ["pay", "settle", "clear", "upi", "link", "net banking", "netbanking"],
    "product_faq": [
        "insurance",
        "policy",
        "coverage",
        "claim",
        "premium",
        "ncd",
        "benefit",
        "car protect",
        "health cover",
        "what does it cover",
        "exclusion",
        "exclusions",
        "invalid",
        "not covered",
        "terms and conditions",
        "policy wording",
        "travel protect",
        "protect360",
        "plan",
        "plans",
        "covered",
    ],
    "upsell_opportunity": ["top-up", "top up", "offer", "credit limit", "upgrade", "add-on"],
    "escalation": [
        "manager",
        "supervisor",
        "court",
        "legal",
        "lawyer",
        "ombudsman",
        "police",
        "call a human",
        "talk to human",
        "speak to human",
        "real person",
        "human agent",
        "customer care",
    ],
    "out_of_scope": ["wrong number", "who is this"],
}

# Short/vague turns that continue a prior product FAQ thread.
_FOLLOWUP_DETAIL = (
    "tell me all",
    "list all",
    "see and tell",
    "full list",
    "all of them",
    "all details",
    "more details",
    "go deeper",
    "check and tell",
    "look and tell",
    "yeah better",
    "yes better",
    "please list",
    "give me all",
    "what else",
    "anything else",
    "elaborate",
    "in detail",
    "complete list",
)

_PRODUCT_SESSION_INTENTS = frozenset({"product_faq", "upsell_opportunity"})


def classify_intent(text: str) -> tuple[str, dict[str, float]]:
    t = (text or "").lower()
    scores: dict[str, float] = {}
    total = 0.0
    for key, kws in INTENT_KEYWORDS.items():
        s = float(sum(1 for kw in kws if kw in t))
        scores[key] = s
        total += s
    if total <= 0:
        for key in INTENT_KEYWORDS:
            scores[key] = 0.35 if key == "out_of_scope" else 0.09
    else:
        for key in scores:
            scores[key] = scores[key] / total
    top = max(scores, key=scores.get)
    return top, scores


def is_detail_followup(text: str) -> bool:
    t = " ".join((text or "").lower().split())
    if not t:
        return False
    if any(p in t for p in _FOLLOWUP_DETAIL):
        return True
    # Ultra-short acknowledgements / nudges after a product answer.
    return len(t) <= 40 and t in {
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "sure",
        "please",
        "go ahead",
        "continue",
        "all",
        "full",
        "details",
    }


def resolve_intent(
    text: str,
    *,
    prior_intent: str | None = None,
) -> tuple[str, dict[str, float]]:
    """Classify intent, carrying forward product FAQ across short follow-ups."""
    intent, scores = classify_intent(text)
    prior = (prior_intent or "").strip()
    if prior in _PRODUCT_SESSION_INTENTS and is_detail_followup(text):
        # Keep the product thread alive so KB retrieve is not gated off.
        scores = dict(scores)
        scores[prior] = max(float(scores.get(prior) or 0.0), 0.85)
        return prior, scores
    if intent == "out_of_scope" and prior in _PRODUCT_SESSION_INTENTS and (text or "").strip():
        # Ambiguous short turn in an active product thread — stay on product.
        if len((text or "").split()) <= 12:
            scores = dict(scores)
            scores[prior] = max(float(scores.get(prior) or 0.0), 0.7)
            return prior, scores
    return intent, scores
