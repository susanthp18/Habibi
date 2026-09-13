"""The Inbox's suggestion chips: the retrieval query built from a thread, the
noise it drops, and the refresh that writes the chips back. Carved out of
db_inbox, which is the thread itself.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy import text

from db_core import (
    _one,
    _rows,
)

logger = logging.getLogger(__name__)


def _db():
    """The ``db`` module object, resolved at call time: tests route
    ``db.engine`` through a savepoint proxy by setattr on the module."""
    import db as d

    return d


def _engine():
    return _db().engine


_INBOX_RAG_NOISE = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "hola",
        "thanks",
        "thank you",
        "thankyou",
        "ok",
        "okay",
        "k",
        "yes",
        "no",
        "yep",
        "nope",
        "bye",
        "good morning",
        "good afternoon",
        "good evening",
        "gm",
        "status probe",
    }
)
# Cosine floor for Inbox chips. Empirically on-domain insurance hits land ~0.45–0.60
# when the query is clean; mixed history used to sit just under 0.50 and look "empty".
INBOX_RAG_MIN_SCORE = 0.38
_INBOX_RAG_MAX_TURN_CHARS = 220
_INBOX_RAG_TEST_MARKERS = (
    "inbound test",
    "status probe",
    "test message",
    "webhook test",
    "from phone",
)
_INBOX_RAG_COLLECTIONS_HINTS = (
    "emi",
    "payment",
    "loan",
    "outstanding",
    "overdue",
    "due date",
    "promise",
    "ptp",
    "dpd",
    "installment",
    "instalment",
    "settlement",
    "waiver",
    "late fee",
    "npa",
)


def _is_inbox_rag_noise(text_value: str) -> bool:
    t = " ".join((text_value or "").lower().split()).strip(".,!? ")
    if not t:
        return True
    if t in _INBOX_RAG_NOISE:
        return True
    # Very short acknowledgements / phatic noise.
    if len(t) <= 16 and t.rstrip(".!") in _INBOX_RAG_NOISE:
        return True
    # Dev / webhook probe lines that dilute embedding queries.
    if any(m in t for m in _INBOX_RAG_TEST_MARKERS):
        return True
    return False


def _looks_like_pasted_draft(text_value: str) -> bool:
    """Skip agent pastes of prior RAG/LLM output — they poison the next retrieve."""
    raw = text_value or ""
    t = raw.lower()
    markers = (
        "from the context",
        "provided context",
        "i don't have any information",
        "i can only confirm",
        "source: **faq",
        "source: faq",
    )
    if any(m in t for m in markers):
        return True
    # Long markdown-ish blobs are almost never a live chat turn.
    if len(raw) > 280 and ("**" in raw or raw.count("\n") >= 3):
        return True
    return False


def _clip_inbox_rag_turn(text_value: str) -> str:
    t = " ".join((text_value or "").split())
    if len(t) <= _INBOX_RAG_MAX_TURN_CHARS:
        return t
    return t[: _INBOX_RAG_MAX_TURN_CHARS - 1] + "…"


def _is_questionish(text_value: str) -> bool:
    t = (text_value or "").strip().lower()
    if not t:
        return False
    if "?" in t:
        return True
    return t.startswith(
        ("how ", "what ", "when ", "where ", "why ", "can ", "could ", "should ", "do ", "does ", "is ", "are ")
    )


def _looks_collections_topic(text_value: str) -> bool:
    t = (text_value or "").lower()
    return any(h in t for h in _INBOX_RAG_COLLECTIONS_HINTS)


def _conversation_rag_query(conn: Any, conversation_id: str) -> str:
    """Build retrieve query focused on the latest customer question.

    Keeps the embedding tight: prefer customer turns, at most one short
    supporting turn, skip bot/greetings/test probes/pasted drafts. Account
    product is appended only when the primary turn is collections-related —
    otherwise "Personal Loan" pulls insurance queries off-domain.
    """
    row = _one(
        conn.execute(
            text(
                """
                SELECT c.name AS customer_name, p.name AS product
                FROM conversations cv
                JOIN customers c ON c.id = cv.customer_id
                LEFT JOIN LATERAL (
                  SELECT pr.name
                  FROM accounts a
                  JOIN products pr ON pr.id = a.product_id
                  WHERE a.customer_id = cv.customer_id
                  ORDER BY a.updated_at DESC NULLS LAST, a.created_at DESC NULLS LAST
                  LIMIT 1
                ) p ON true
                WHERE cv.id = :id
                """
            ),
            {"id": conversation_id},
        )
    )
    if not row:
        raise KeyError("conversation_not_found")

    msgs = _rows(
        conn.execute(
            text(
                """
                SELECT body, sender
                FROM messages
                WHERE conversation_id = :id
                ORDER BY created_at DESC NULLS LAST, id DESC
                LIMIT 20
                """
            ),
            {"id": conversation_id},
        )
    )
    chronological = list(reversed(msgs))
    # Bot turns are long templates and pollute agent-assist retrieval.
    label_map = {"customer": "Customer", "agent": "Agent"}
    substantive: list[tuple[str, str]] = []  # (label, body)
    for m in chronological:
        body = (m.get("body") or "").strip()
        sender = (m.get("sender") or "").lower()
        if sender not in label_map or not body:
            continue
        if _is_inbox_rag_noise(body) or _looks_like_pasted_draft(body):
            continue
        substantive.append((label_map[sender], body))

    recent = substantive[-6:]
    if not recent:
        fallback: list[tuple[str, str]] = []
        for m in chronological:
            body = (m.get("body") or "").strip()
            sender = (m.get("sender") or "").lower()
            if sender not in label_map or not body:
                continue
            if _looks_like_pasted_draft(body):
                continue
            fallback.append((label_map[sender], body))
        recent = fallback[-3:]
    if not recent:
        raise ValueError("conversation_has_no_messages")

    # Primary: latest customer question → latest customer turn → latest agent
    # question → latest turn. Customer intent beats agent typing for retrieval.
    primary_idx = len(recent) - 1
    for i in range(len(recent) - 1, -1, -1):
        if recent[i][0] == "Customer" and _is_questionish(recent[i][1]):
            primary_idx = i
            break
    else:
        for i in range(len(recent) - 1, -1, -1):
            if recent[i][0] == "Customer":
                primary_idx = i
                break
        else:
            for i in range(len(recent) - 1, -1, -1):
                if _is_questionish(recent[i][1]):
                    primary_idx = i
                    break

    primary = recent[primary_idx]
    # At most one supporting turn — prefer another nearby customer line.
    support: tuple[str, str] | None = None
    for i in range(len(recent) - 1, -1, -1):
        if i == primary_idx:
            continue
        label, body = recent[i]
        if label == "Customer":
            support = (label, body)
            break
    if support is None:
        for i in range(len(recent) - 1, -1, -1):
            if i == primary_idx:
                continue
            support = recent[i]
            break

    parts = [f"{primary[0]}: {_clip_inbox_rag_turn(primary[1])}"]
    if support is not None:
        parts.append(f"{support[0]}: {_clip_inbox_rag_turn(support[1])}")

    product = (row.get("product") or "").strip()
    if product and _looks_collections_topic(primary[1]):
        parts.append(f"Account product: {product}.")
    return "\n".join(parts)


def _chip_from_result(item: dict[str, Any]) -> str:
    """Full KB snippet for Inbox tiles (Show more must have real text, not a 140-char stub)."""
    title = (item.get("docTitle") or "").strip()
    heading = (item.get("heading") or "").strip()
    snip = ((item.get("snippet") or "").strip())
    # Preserve newlines in policy wording; collapse only runs of spaces/tabs.
    if snip:
        snip = re.sub(r"[ \t]+", " ", snip)
        snip = re.sub(r"\n{3,}", "\n\n", snip).strip()
    if len(snip) > 2400:
        snip = snip[:2397].rstrip() + "…"
    head_bits = [p for p in (title, heading) if p]
    head = " — ".join(head_bits)
    if head and snip:
        return f"{head}\n\n{snip}"
    return snip or head or "KB suggestion"


def refresh_conversation_suggestions(
    conversation_id: str,
    *,
    top_k: int = 4,
    include_draft_answer: bool = False,
) -> dict[str, Any]:
    """Run shared kb_retrieve → persist ai_response_suggestions for Inbox chips.

    Optional draft uses the same grounded chat path as Test Retrieval
    (`include_draft_answer` → kb_retrieve); no second rewrite pipeline.
    Weak matches below INBOX_RAG_MIN_SCORE are dropped (empty chips > junk).
    """
    import kb_rate_limit
    import kb_retrieve

    with _engine().connect() as conn:
        try:
            query = _conversation_rag_query(conn, conversation_id)
        except ValueError as exc:
            if str(exc) != "conversation_has_no_messages":
                raise
            # Not a bad request. A conversation with nothing to retrieve
            # against is an ordinary state — a voice call escalated into the
            # inbox keeps its turns in interaction_transcript, not messages, so
            # every poll of that thread 400'd. There is nothing to suggest, and
            # "nothing to suggest" is an empty list.
            return {
                "conversationId": conversation_id,
                "ragSuggestions": [],
                "draftAnswer": None,
                "chatModel": None,
                "latencyMs": 0,
                "logId": None,
            }

    # Over-fetch then score-gate so we can fill top_k after filtering.
    fetch_k = max(top_k * 2, 8)
    q_l = (query or "").lower()
    prefer_policy = any(
        k in q_l
        for k in (
            "exclu",
            "invalid",
            "not covered",
            "policy",
            "cover",
            "benefit",
            "travel",
            "protect360",
            "wording",
        )
    )
    retrieval: dict[str, Any] | None = None
    try:
        retrieval = kb_retrieve.retrieve(
            query=query,
            top_k=fetch_k,
            include_draft_answer=include_draft_answer,
            source="inbox",
            prefer_policy=prefer_policy,
        )
    except kb_rate_limit.RateLimitExceeded:
        # Not an outage — backpressure, and the caller has a 429 for it. The
        # broad handler below exists so a retrieval outage degrades to the last
        # persisted chips rather than blanking the panel; catching the throttle
        # with it meant a rate-limited poll returned 200 with stale chips and
        # no way for the operator to tell they were stale.
        raise
    except Exception:
        logger.exception("inbox_rag_retrieve_failed conversation=%s", conversation_id)
        retrieval = None
    if retrieval is None:
        # Fall through to persisted-chips path below.
        chips = []
        draft = None
        passed = []
    else:
        chips = []
        passed = [
            item
            for item in (retrieval.get("results") or [])
            if float(item.get("score") or 0.0) >= INBOX_RAG_MIN_SCORE
        ]
        # Don't persist a draft grounded on weak / off-topic hits.
        draft = (retrieval.get("draftAnswer") or "").strip() or None
        if not passed:
            draft = None
        for item in passed:
            chip = _chip_from_result(item)
            if chip and chip not in chips:
                chips.append(chip)
            if len(chips) >= top_k:
                break

    # Only replace persisted chips when we have a fresh pass set. An empty
    # retrieval (score-gate miss / transient embed blip) must not wipe the last
    # good suggestions — that made Inbox look permanently empty under a stale
    # worker or noisy query.
    with _engine().begin() as conn:
        if chips or draft:
            conn.execute(
                text(
                    """
                    DELETE FROM ai_response_suggestions
                    WHERE conversation_id = :id
                      AND COALESCE(source, '') IN ('kb', 'kb_draft')
                    """
                ),
                {"id": conversation_id},
            )
            if draft:
                conn.execute(
                    text(
                        """
                        INSERT INTO ai_response_suggestions (
                          id, conversation_id, interaction_id, transcript_turn_id,
                          suggestion_text, source, accepted, accepted_by_user_id,
                          accepted_at, created_at
                        ) VALUES (
                          :id, :conversation_id, NULL, NULL,
                          :suggestion_text, 'kb_draft', false, NULL,
                          NULL, now()
                        )
                        """
                    ),
                    {
                        "id": f"sug-{conversation_id}-{uuid.uuid4().hex[:8]}-draft",
                        "conversation_id": conversation_id,
                        "suggestion_text": draft,
                    },
                )
            for i, text_value in enumerate(chips):
                conn.execute(
                    text(
                        """
                        INSERT INTO ai_response_suggestions (
                          id, conversation_id, interaction_id, transcript_turn_id,
                          suggestion_text, source, accepted, accepted_by_user_id,
                          accepted_at, created_at
                        ) VALUES (
                          :id, :conversation_id, NULL, NULL,
                          :suggestion_text, 'kb', false, NULL,
                          NULL, now()
                        )
                        """
                    ),
                    {
                        "id": f"sug-{conversation_id}-{uuid.uuid4().hex[:8]}-{i}",
                        "conversation_id": conversation_id,
                        "suggestion_text": text_value,
                    },
                )
        else:
            # Fall back to last persisted chips so the UI does not go blank.
            existing = _rows(
                conn.execute(
                    text(
                        """
                        SELECT suggestion_text
                        FROM ai_response_suggestions
                        WHERE conversation_id = :id
                          AND COALESCE(source, '') = 'kb'
                        ORDER BY created_at DESC
                        LIMIT 5
                        """
                    ),
                    {"id": conversation_id},
                )
            )
            chips = [str(r["suggestion_text"]).strip() for r in existing if r.get("suggestion_text")]

    meta: dict[str, Any] = retrieval or {}
    logger.info(
        "inbox_rag_refreshed conversation=%s chips=%s passed=%s draft=%s min_score=%s latency_ms=%s",
        conversation_id,
        len(chips),
        len(passed),
        bool(draft),
        INBOX_RAG_MIN_SCORE,
        meta.get("latencyMs"),
    )
    thread = _db().get_conversation(conversation_id)
    if thread is None:
        raise KeyError(f"conversation {conversation_id} not found")
    return {
        "conversationId": conversation_id,
        "ragSuggestions": chips[:5],
        "draftAnswer": draft,
        "chatModel": meta.get("chatModel"),
        "latencyMs": meta.get("latencyMs"),
        "logId": meta.get("logId"),
        "thread": thread,
    }
