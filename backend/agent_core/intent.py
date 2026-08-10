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
    "help_capabilities": [
        "what can you do",
        "what do you do",
        "how can you help",
        "how can u help",
        "what are you able",
        "your capabilities",
        "what help can you",
        "what all can you",
        "how do you help",
        "what services",
        "help menu",
        "what can u do",
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

# Intents that must not inherit stale collections / product session state.
_SESSION_BREAK_INTENTS = frozenset({"help_capabilities", "greeting", "correction", "escalation"})

# Talking *about* the call is not a reason *for* the call. "What can you do?",
# "hello?", "no, I didn't ask that" are all meta — answer them, but do not file
# them as why the caller rang. On VS-6B252E0479 "asking what all you can do"
# was captured as the call goal and then drove both the balance-suppression
# rule and the idle re-engagement prompt for the rest of the call.
NON_GOAL_INTENTS = frozenset(_SESSION_BREAK_INTENTS | {"out_of_scope", "smalltalk"})

_CORRECTION_PHRASES = (
    "didn't ask",
    "didnt ask",
    "did not ask",
    "not what i asked",
    "not what i said",
    "not what i meant",
    "that's not what",
    "thats not what",
    "that is not what",
    "you misunderstood",
    "you missed",
    "wrong answer",
    "i asked about",
    "don't change the topic",
    "dont change the topic",
    "i never said",
)

_GREETING_EXACT = frozenset(
    {
        "hi",
        "hey",
        "hello",
        "hola",
        "namaste",
        "good morning",
        "good afternoon",
        "good evening",
        "hi there",
        "hey there",
        "hello there",
    }
)


def _normalize(text: str) -> str:
    return " ".join((text or "").lower().split()).strip(".,!? ")


def is_correction(text: str) -> bool:
    """True when the customer is rejecting the previous bot reply / topic."""
    t = _normalize(text)
    if not t:
        return False
    return any(p in t for p in _CORRECTION_PHRASES)


def is_greeting(text: str) -> bool:
    """Short social opener with no other substantive ask."""
    t = _normalize(text)
    if not t:
        return False
    if t in _GREETING_EXACT:
        return True
    words = t.split()
    if len(words) <= 3 and words[0] in {"hi", "hey", "hello"}:
        # "Hi Susanth" / "Hey there" — still a greeting.
        return True
    return False


def is_help_capabilities(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False
    for kw in INTENT_KEYWORDS["help_capabilities"]:
        if kw in t:
            return True
    # Bare "help" / "options" when the turn is short.
    if len(t.split()) <= 4 and t in {"help", "options", "menu", "help please"}:
        return True
    return False


def classify_intent(text: str) -> tuple[str, dict[str, float]]:
    """Score keyword intents; meta detectors win over keyword defaults."""
    # Corrections / help / greetings must beat the "no keyword → out_of_scope"
    # default — otherwise "what can you do" was classified as out_of_scope and
    # the model fell back to stale EMI/PTP context.
    if is_correction(text):
        scores = {k: 0.05 for k in INTENT_KEYWORDS}
        scores["help_capabilities"] = 0.05
        scores["correction"] = 0.9
        return "correction", scores
    if is_help_capabilities(text):
        scores = {k: 0.05 for k in INTENT_KEYWORDS}
        scores["help_capabilities"] = 0.9
        return "help_capabilities", scores
    if is_greeting(text):
        scores = {k: 0.05 for k in INTENT_KEYWORDS}
        scores["greeting"] = 0.9
        return "greeting", scores

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
    # Session-break intents always win — never inherit product/collections.
    if intent in _SESSION_BREAK_INTENTS:
        return intent, scores

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
