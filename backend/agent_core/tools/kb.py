"""The single ``search_knowledge_base`` handler shared by voice and WhatsApp/text.

Closes the last acceptance-criterion gap in ``pipecat_unification_plan.md`` §8.1:
every other overlapping tool already funnels through :mod:`agent_core.tools.domain`,
but KB retrieval kept two copies of the policy — the text path owned the intent
gate, query expansion and exclusion steering; the voice path owned node-scoped
product keys, snapshot pinning and the confidence threshold. Neither channel
benefited from the other's rules and they were free to drift.

This module owns all of it. The channel adapters keep only what is genuinely
channel-shaped: RTVI emission and Flows tuple shape on voice, ``ToolContext``
plumbing on text.

Divergence that is *real* stays expressible as parameters:

``prefer_policy``
    ``None`` derives it from what the customer asked (the text heuristics).
    Voice passes an explicit bool because its corpus scope is decided by the
    Flows node, not by the sentence.
``apply_intent_gate``
    Text-only. WhatsApp threads reach the KB tool from any intent, so a
    collections money question had to be structurally blocked from answering out
    of the insurance corpus. Voice is already node-scoped, so the gate would
    double-block a legitimate hub FAQ.
"""

from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from typing import Any, Callable

from agent_core.tools.domain import ToolResult

logger = logging.getLogger(__name__)

# Intents allowed to call search_knowledge_base (insurance/product corpus).
# Collections money questions must use CRM tools, not HL Assurance chunks.
KB_ALLOWED_INTENTS = frozenset({"product_faq", "upsell_opportunity"})

# Score below which the model must not answer from the snippets at all.
KB_CONFIDENCE_THRESHOLD = 0.70

# Score below which the question is recorded as a KB *content gap*.
#
# Deliberately a separate knob from KB_CONFIDENCE_THRESHOLD even though it
# defaults to the same value. They answer different questions: 0.70 is "may the
# model speak from these snippets", which is a safety call. Whether the corpus
# is missing something is a content call, and a near-miss at 0.68 is arguably
# the most interesting gap there is — the corpus almost has the answer. Tune
# KB_GAP_THRESHOLD down (~0.55) once the table has real traffic in it.
KB_GAP_THRESHOLD = KB_CONFIDENCE_THRESHOLD


def _gap_capture_enabled() -> bool:
    """Read at call time so the flag can be flipped without a redeploy."""
    return (os.getenv("KB_GAP_CAPTURE_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _gap_threshold() -> float:
    raw = (os.getenv("KB_GAP_THRESHOLD") or "").strip()
    if not raw:
        return KB_GAP_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        logger.warning("KB_GAP_THRESHOLD is not a number: %r — using default", raw)
        return KB_GAP_THRESHOLD
    return min(1.0, max(0.0, value))


def _emit_gap(
    sink: Callable[[dict[str, Any]], None] | None,
    *,
    question: str,
    intent: str | None,
    channel: str,
    interaction_id: str,
) -> None:
    """Record an unanswerable question, or hand it to a sink that will.

    Wrapped whole in try/except on purpose: gap accounting is analytics, and a
    failure here must never turn a working retrieval into a failed tool call
    that the customer hears about.

    ``sink`` exists for voice, where this runs inside the turn's latency budget
    — the model waits for the tool result before TTS — so the write is queued
    onto the CrmSink instead of done inline.
    """
    payload = {
        "question": question,
        "intent": intent,
        "channel": channel,
        "interaction_id": interaction_id,
    }
    try:
        if sink is not None:
            sink(payload)
            return
        import db

        db.record_kb_gap(**payload)
    except Exception:
        logger.warning("kb gap capture failed", exc_info=True)

# Retrieval shape per channel. Voice reads answers aloud, so it takes few, short
# snippets; text can carry a full exclusion list into the reply.
_DEFAULTS = {
    "voice": {"top_k": 3, "top_k_policy": 3, "snippet": 600, "snippet_policy": 600},
    "text": {"top_k": 6, "top_k_policy": 8, "snippet": 1400, "snippet_policy": 2000},
}

# Unambiguous product/insurance vocabulary — one of these alone opens the KB.
_PRODUCT_QUERY_HINTS = (
    "insurance",
    "policy",
    "coverage",
    "exclu",
    "benefit",
    "premium",
    "protect360",
    "covered",
    "policy wording",
    "terms and conditions",
    "travel cover",
    "travel insurance",
)

# Terms that occur just as naturally in a collections conversation ("payment
# plan", "I want to claim I already paid", "the terms of my loan"). On their own
# these must NOT open search_knowledge_base, or a money question gets answered
# out of the HL Assurance corpus. They count only alongside a strong signal.
_WEAK_PRODUCT_HINTS = (
    "claim",
    "plan",
    "terms",
    "invalid",
    "travel",
    "wording",
)
_PRODUCT_CONTEXT_TOKENS = (
    "insurance",
    "policy",
    "cover",
    "premium",
    "protect360",
    "assurance",
    "product",
    "add-on",
    "addon",
)

_POLICY_DETAIL_TOKENS = (
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

# Hoisted so the coverage and activity-eligibility classifiers cannot drift:
# both keyed off near-identical inline tuples before.
_ACTIVITY_TOKENS = (
    "scuba",
    "diving",
    "bungee",
    "rafting",
    "ski",
    "racing",
    "extreme",
    "underwater",
)
# _wants_coverage_detail also treats a generic "sport" as an activity mention.
_COVERAGE_ACTIVITY_TOKENS = _ACTIVITY_TOKENS + ("sport",)
_COVERAGE_VERB_TOKENS = ("cover", "covered", "allow", "permitted", "can i")
_ACTIVITY_VERB_TOKENS = _COVERAGE_VERB_TOKENS + ("claim",)
_COVERAGE_TOPIC_TOKENS = (
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


def query_looks_product(query: str) -> bool:
    t = (query or "").lower()
    if any(h in t for h in _PRODUCT_QUERY_HINTS):
        return True
    if any(h in t for h in _WEAK_PRODUCT_HINTS) and any(
        c in t for c in _PRODUCT_CONTEXT_TOKENS
    ):
        return True
    return False


def wants_policy_detail(query: str) -> bool:
    t = (query or "").lower()
    return any(h in t for h in _POLICY_DETAIL_TOKENS)


@lru_cache(maxsize=32)
def _stem_re(tokens: tuple[str, ...]) -> re.Pattern[str]:
    """Match each token as a word-initial stem, not as a bare substring.

    Plain ``in`` containment made short tokens fire on unrelated words: "ski"
    matched "asking"/"risk"/"whisky", "racing" matched "embracing", "cover"
    matched "discover" — so "am I asking whether medical is covered?" was
    classified as an extreme-activity eligibility question and steered into the
    exclusions corpus. Anchoring at \\b keeps the intended stem behaviour
    ("ski"→"skiing", "postpon"→"postponed", "cancel"→"cancellation") while
    dropping mid-word hits.
    """
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in tokens) + r")")


def _matches_any(text: str, tokens: tuple[str, ...]) -> bool:
    return bool(_stem_re(tokens).search(text))


def wants_coverage_detail(query: str) -> bool:
    """Coverage / benefits questions — should not be steered into exclusions-only retrieve."""
    t = (query or "").lower()
    if wants_policy_detail(t):
        return False
    # "Is scuba diving covered?" needs exclusions + conditions, not benefits-only.
    if _matches_any(t, _COVERAGE_ACTIVITY_TOKENS) and _matches_any(
        t, _COVERAGE_VERB_TOKENS
    ):
        return False
    return _matches_any(t, _COVERAGE_TOPIC_TOKENS)


def wants_activity_eligibility(query: str) -> bool:
    t = (query or "").lower()
    return _matches_any(t, _ACTIVITY_TOKENS) and _matches_any(t, _ACTIVITY_VERB_TOKENS)


def classify_kb_intent(customer_text: str, query: str) -> str:
    """One decision point for KB steering: "exclusions" | "coverage" | "none".

    Precedence is deliberate and unchanged: what the *customer* asked wins over
    the model's tool-arg phrasing, and a policy-detail query only steers to
    exclusions when the customer was not asking a coverage/activity question.
    """
    cust = customer_text or ""
    if (
        wants_policy_detail(cust)
        or wants_activity_eligibility(cust)
        or (
            wants_policy_detail(query)
            and not wants_coverage_detail(cust)
            and not wants_activity_eligibility(cust)
        )
    ):
        return "exclusions"
    if wants_coverage_detail(cust) or wants_coverage_detail(query):
        return "coverage"
    return "none"


def gate_allows(
    query: str,
    *,
    customer_text: str = "",
    intent: str | None = None,
    session_intent: str | None = None,
) -> tuple[bool, str]:
    """Structural gate: block collections money intents; allow product threads + queries."""
    intent = intent or ""
    session = session_intent or ""
    if intent in KB_ALLOWED_INTENTS:
        return True, intent
    if session in KB_ALLOWED_INTENTS:
        return True, session
    if query_looks_product(query) or query_looks_product(customer_text):
        return True, intent or session or "product_faq"
    # Still blocked for pure collections intents with no product signal.
    return False, intent or session or "unknown"


def expand_query(query: str, *, customer_text: str = "", product_hint: str | None = None) -> str:
    """Enrich vague follow-ups with product/topic context so ANN hits policy docs."""
    parts = [(query or "").strip()]
    if product_hint and product_hint.lower() not in (query or "").lower():
        parts.append(product_hint)
    # Steer by what the *customer* asked — not by noisy tool-arg padding.
    kind = classify_kb_intent(customer_text, query)
    if kind == "exclusions":
        parts.append("policy exclusions invalidation conditions not covered")
        if wants_activity_eligibility(customer_text) or wants_activity_eligibility(query):
            parts.append("leisure scuba diving underwater breathing apparatus conditions")
    elif kind == "coverage":
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


def _derive_prefer_policy(customer_text: str, expanded: str) -> bool:
    return (
        wants_policy_detail(customer_text)
        or wants_activity_eligibility(customer_text)
        or (wants_policy_detail(expanded) and not wants_coverage_detail(customer_text))
    )


def _kb_topics(results: list[dict[str, Any]], limit: int = 4) -> list[str]:
    """Distinct doc types behind the passages the model was shown.

    These become CustomerFeatures/CallSignals.kb_topics_queried. What a caller
    asked the knowledge base about is a buying signal the system was already
    collecting and discarding — someone reading up on top-up eligibility is
    telling you something a batch propensity model cannot know.
    """
    out: list[str] = []
    for r in results:
        topic = str(r.get("docType") or "").strip().lower()
        if topic and topic not in out:
            out.append(topic)
        if len(out) >= limit:
            break
    return out


def _record_product_interest(
    *,
    interaction_id: str,
    gate_intent: str,
    bot_id: str | None,
    snippet: str | None,
    topics: list[str] | None = None,
) -> bool:
    """A product KB answer is *interest*, not a pitch.

    This used to emit ``offer_presented`` and flip ``interactions.upsell_presented``
    for any product-corpus answer that returned hits — so a customer asking
    "what does my policy exclude?" was recorded as having been offered
    something. That inflated the presented rate against a denominator taken
    from the same event stream, and made the upsell funnel disagree with what
    the bot actually said.

    ``offer_presented`` now comes from exactly two places, both of which mean an
    offer was genuinely put to the customer: the offer engine when it speaks one
    (voice/tools.py, bot_tools.py) and capture_lead when a lead is written
    (agent_core/tools/domain.py).
    """
    try:
        import capture
        import db

        intent = (
            gate_intent
            if gate_intent in {"product_faq", "upsell_opportunity"}
            else "product_faq"
        )
        with db.engine.begin() as conn:
            capture.record_product_interest(
                conn,
                interaction_id=interaction_id,
                intent=intent,
                snippet=snippet,
                actor_bot_id=bot_id,
                topics=topics,
            )
        return True
    except Exception:
        logger.exception("kb product_interest analytics failed")
        return False


def _catalog_for_plan(kb_snapshot_id: str | None) -> list[dict[str, Any]]:
    """Products the corpus covers, for the planner's scope list. Never raises."""
    try:
        import kb_retrieve

        return kb_retrieve.catalog()
    except Exception:
        logger.warning("kb catalog lookup failed — planning without product scope",
                       exc_info=True)
        return []


def _catalog_result(
    *,
    plan: Any,
    gate_intent: str,
    kb_snapshot_id: str | None,
    interaction_id: str | None,
    bot_id: str | None,
    record_offer: bool,
    session_intent: str | None,
) -> ToolResult:
    """Answer a "what do you have?" question from the corpus itself.

    Returned in the same envelope as a passage answer so the channel adapters
    need no special case: ``results`` carries one entry per product with the
    product name as the title, and ``confident`` is true whenever the corpus is
    non-empty — there is no retrieval score to be unsure about, and the list is
    exactly as authoritative as the knowledge base is.
    """
    from agent_core.tools import kb_plan

    products = _catalog_for_plan(kb_snapshot_id)
    if plan.product_keys:
        wanted = {k.lower() for k in plan.product_keys}
        products = [p for p in products if str(p.get("productKey", "")).lower() in wanted]

    results = [
        {
            "docTitle": p.get("title"),
            "docType": "catalog",
            "heading": None,
            "snippet": p.get("title"),
            "score": None,
        }
        for p in products
    ]
    analytics: list[str] = []
    if (
        record_offer
        and results
        and interaction_id
        and (
            gate_intent in {"product_faq", "upsell_opportunity"}
            or (session_intent or "") in {"product_faq", "upsell_opportunity"}
        )
        and _record_product_interest(
            interaction_id=interaction_id,
            gate_intent=gate_intent,
            bot_id=bot_id,
            snippet=(plan.query or "")[:240] or None,
            topics=["catalog"],
        )
    ):
        analytics.append("product_interest")

    return ToolResult(
        ok=True,
        data={
            "available": True,
            "intent": gate_intent,
            "queryUsed": plan.query,
            "mode": kb_plan.MODE_CATALOG,
            "planSource": plan.source,
            "judgeSource": None,
            "unvetted": False,
            "judgeReason": None,
            "results": results,
            "chunkIds": [],
            "products": products,
            "topScore": 1.0 if products else 0.0,
            "confident": bool(products),
            "preferPolicy": False,
            "snapshotId": kb_snapshot_id,
        },
        analytics=analytics,
    )


def search_knowledge_base(
    *,
    query: str,
    channel: str,
    customer_text: str = "",
    intent: str | None = None,
    session_intent: str | None = None,
    product_hint: str | None = None,
    product_keys: list[str] | None = None,
    kb_snapshot_id: str | None = None,
    interaction_id: str | None = None,
    bot_id: str | None = None,
    apply_intent_gate: bool = True,
    should_expand_query: bool = True,
    prefer_policy: bool | None = None,
    top_k: int | None = None,
    snippet_chars: int | None = None,
    confidence_threshold: float = KB_CONFIDENCE_THRESHOLD,
    record_offer: bool = True,
    gap_sink: Callable[[dict[str, Any]], None] | None = None,
    recent: list[tuple[str, str]] | None = None,
    plan_budget_s: float | None = None,
) -> ToolResult:
    """Retrieve KB passages under the shared gate/steering/confidence policy.

    Synchronous like every other domain handler — the voice adapter wraps it in
    ``asyncio.to_thread`` so the audio path is never blocked.

    ``ok=False`` covers the recoverable cases the model can act on:
    ``empty_query``, ``retrieval_unavailable`` (bad/stale snapshot — must never
    silently widen to the whole corpus), and ``retrieval_failed``.
    """
    q = (query or "").strip() or (customer_text or "").strip()
    if not q:
        return ToolResult(ok=False, error="empty_query")

    defaults = _DEFAULTS.get(channel) or _DEFAULTS["text"]

    gate_intent = intent or session_intent or "unknown"
    if apply_intent_gate:
        allowed, gate_intent = gate_allows(
            q, customer_text=customer_text, intent=intent, session_intent=session_intent
        )
        if not allowed:
            return ToolResult(
                ok=True,
                data={
                    "available": False,
                    "reason": "kb_gated_for_intent",
                    "intent": gate_intent,
                    "message": (
                        "Knowledge base is not available for this collections intent. "
                        "Use get_customer_context / get_emi_schedule / get_payment_history "
                        "for money facts, or escalate_to_human for policy exceptions."
                    ),
                    "results": [],
                },
            )

    import kb_retrieve
    from agent_core.tools import kb_plan

    # The keyword derivation is now the *fallback*, not the decision. It is
    # computed first so a disabled planner, a saturated analysis lane or an
    # exhausted budget degrades to exactly the previous behaviour.
    expanded = (
        expand_query(q, customer_text=customer_text, product_hint=product_hint)
        if should_expand_query
        else q
    )
    keyword_prefer_policy = (
        prefer_policy
        if prefer_policy is not None
        else _derive_prefer_policy(customer_text, expanded)
    )

    deadline = kb_plan.Deadline(
        plan_budget_s if plan_budget_s is not None else kb_plan.budget_for(channel)
    )
    plan = kb_plan.plan_retrieval(
        # What the *caller* said drives the plan. The agent's own tool-arg
        # phrasing is passed separately as a hint and can no longer decide the
        # corpus on its own — that is how "what plans are available" ended up
        # retrieving exclusions, off the word "exclusions" in the tool args.
        customer_text=customer_text or q,
        tool_query=query or "",
        available_products=_catalog_for_plan(kb_snapshot_id),
        recent=recent,
        budget=deadline.remaining(),
        fallback=kb_plan.RetrievalPlan(
            query=expanded,
            product_keys=product_keys,
            prefer_policy=bool(keyword_prefer_policy),
            source=kb_plan.SOURCE_FALLBACK,
        ),
    )

    # A question about what the corpus *covers* has no passage to find. Answer
    # it from the document catalog and skip retrieval entirely — this is the
    # case that four consecutive refusals could not have fixed at any threshold.
    if plan.is_catalog:
        return _catalog_result(
            plan=plan,
            gate_intent=gate_intent,
            kb_snapshot_id=kb_snapshot_id,
            interaction_id=interaction_id,
            bot_id=bot_id,
            record_offer=record_offer,
            session_intent=session_intent,
        )

    expanded = plan.query or expanded
    prefer_policy = plan.prefer_policy
    if plan.product_keys:
        product_keys = plan.product_keys

    k = top_k or (defaults["top_k_policy"] if prefer_policy else defaults["top_k"])
    cap = snippet_chars or (
        defaults["snippet_policy"] if prefer_policy else defaults["snippet"]
    )

    try:
        raw = kb_retrieve.retrieve(
            query=expanded,
            top_k=k,
            include_draft_answer=False,
            source="voice" if channel == "voice" else "bot",
            interaction_id=interaction_id,
            prefer_policy=prefer_policy,
            product_keys=product_keys,
            kb_snapshot_id=kb_snapshot_id,
        )
    except ValueError as exc:
        # A bad/stale snapshot must not silently fall back to the whole corpus —
        # the Sandbox promised this call is pinned to it.
        logger.warning("kb retrieve rejected: %s", exc)
        # Fixed detail, matching domain.py: this dict reaches the model's
        # context and the Inspector, so a driver/DSN/snapshot-id fragment from
        # str(exc) would be something the bot could read aloud.
        return ToolResult(
            ok=False,
            error="retrieval_unavailable",
            data={"detail": "retrieval_unavailable"},
            spoken_summary="apologise and offer a callback for a specialist",
        )
    except Exception:
        logger.exception("kb retrieve failed")
        return ToolResult(
            ok=False,
            error="retrieval_failed",
            data={"detail": "retrieval_failed"},
            spoken_summary="apologise and offer a callback for a specialist",
        )

    rows = list(raw.get("results") or [])[:k]
    results = [
        {
            "docTitle": r.get("docTitle") or r.get("docId"),
            "docType": r.get("docType"),
            "heading": r.get("heading"),
            "snippet": (r.get("snippet") or "").strip()[:cap],
            "score": r.get("score"),
        }
        for r in rows
    ]
    # chunkIds line up index-for-index with results so an RTVI rag.hits event
    # can never report passages the model was not shown.
    chunk_ids = [str(r.get("chunkId") or r.get("id") or "") for r in rows]

    # Whether these passages answer the question is a judgment about their
    # content, not arithmetic on a cosine distance. The number this used to
    # compare had already been through a stack of hand-tuned BOOST_*/PENALTY_*
    # deltas, so "0.70" was a threshold on a quantity with no stable meaning —
    # and it refused a caller at 0.667 over a corpus that documented all ten
    # products they were asking about.
    verdict = kb_plan.judge_passages(
        question=customer_text or q,
        passages=results,
        budget=deadline.remaining(),
    )
    if verdict.source == kb_plan.SOURCE_LLM and verdict.keep:
        order = verdict.keep + [i for i in range(len(results)) if i not in verdict.keep]
        results = [results[i] for i in order]
        chunk_ids = [chunk_ids[i] for i in order]

    # A non-numeric score (driver quirk, hand-written FAQ row) must not raise
    # out of the turn loop. Reported for observability only — nothing gates on
    # it any more.
    try:
        top = float(results[0]["score"] or 0) if results else 0.0
    except (TypeError, ValueError):
        logger.warning("unusable retrieval score %r — treating as 0", results[0].get("score"))
        top = 0.0

    # Three distinct situations, three different right answers. Collapsing them
    # into one blanket "answer anyway" would either refuse callers whenever the
    # judge is switched off, or silently stop applying any check at all.
    if verdict.source == kb_plan.SOURCE_LLM:
        confident = verdict.answerable
    elif verdict.reason == "judge_disabled":
        # Switched off deliberately: fall back to the documented legacy rule
        # rather than to no check at all.
        confident = top >= confidence_threshold
    else:
        # Judge could not run (saturated, out of budget, malformed reply).
        # Fail OPEN by product decision — a busy analysis lane must not turn
        # into a refused caller. It does mean the model may speak from passages
        # nothing vetted, so surface it in the payload and log it rather than
        # letting it look like a clean pass.
        confident = True
        logger.warning(
            "kb answerability degraded (%s) — passages unvetted · interaction=%s",
            verdict.reason,
            interaction_id,
        )

    # The learning loop. This is the only place in the system that knows the bot
    # was asked something it could not answer, and until now that fact was
    # discarded — the KB-gap screen, the gap→FAQ links and POST /kb/gaps/{id}/link
    # all shipped against hand-seeded rows.
    #
    # Deliberately placed on the ok=True/available=True path only, and after the
    # intent gate. retrieval_unavailable and retrieval_failed return earlier, so
    # an Azure outage or a stale snapshot cannot manufacture hundreds of phantom
    # "gaps" — an infrastructure failure is not missing content. Same for
    # kb_gated_for_intent: a collections money question routed away from the
    # corpus is the gate working, not a hole in it.
    #
    # Requires interaction_id, which also excludes the two callers that reach
    # kb_retrieve.retrieve directly and never come through here: the speculative
    # prefetch in voice/kb_enrich.py and the operator's POST /kb/retrieve test
    # panel. Neither is a customer failing to get an answer.
    if interaction_id and _gap_capture_enabled() and (not results or top < _gap_threshold()):
        _emit_gap(
            gap_sink,
            # q, not `expanded` — the customer's own words are what an operator
            # needs to read on the gap screen to decide what to write.
            question=q,
            intent=gate_intent,
            channel=channel,
            interaction_id=interaction_id,
        )

    analytics: list[str] = []
    if (
        record_offer
        and results
        and interaction_id
        and (
            gate_intent in {"product_faq", "upsell_opportunity"}
            or (session_intent or "") in {"product_faq", "upsell_opportunity"}
        )
        and _record_product_interest(
            interaction_id=interaction_id,
            gate_intent=gate_intent,
            bot_id=bot_id,
            snippet=(query or "")[:240] or None,
            topics=_kb_topics(results),
        )
    ):
        # product_interest, not offer_presented: answering a policy question is
        # not making an offer, and conflating them made the upsell funnel report
        # a presentation rate the bot had not earned.
        analytics.append("product_interest")

    return ToolResult(
        ok=True,
        data={
            "available": True,
            "intent": gate_intent,
            "queryUsed": expanded,
            "results": results,
            "chunkIds": chunk_ids,
            "topScore": round(top, 3),
            "confident": confident,
            "preferPolicy": prefer_policy,
            "snapshotId": kb_snapshot_id,
            "latencyMs": raw.get("latencyMs"),
            "logId": raw.get("logId"),
            "mode": kb_plan.MODE_PASSAGE,
            "planSource": plan.source,
            "judgeSource": verdict.source,
            # True only when the judge could not run *and* we answered anyway.
            "unvetted": verdict.degraded and verdict.reason != "judge_disabled",
            "judgeReason": verdict.reason,
        },
        analytics=analytics,
    )
