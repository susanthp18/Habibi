"""Prefix-keyed replacement of developer blocks in the LLM context.

Two callers need the same operation — the KB enricher replacing its snippet
block, and the CRM card being re-injected after a write refreshes it — and both
get it wrong in the same way if written twice.

The rules that matter, both learned from real incidents:

1. **Re-read the message list at call time.** Every caller reaches this after an
   ``await`` (a thread hop for retrieval or a DB read). ``set_messages()``
   replaces the whole list, so filtering a snapshot taken *before* the await
   silently discards everything appended meanwhile — tool results, injected
   cards, idle-ladder frames.
2. **Evict by prefix, then insert.** Appending a fresh block without dropping
   the stale one leaves both in context. Once auto-summarisation folds them
   together the model sees two versions of the same "authoritative" fact and can
   assert the older one — the failure mode recorded at voice/bot.py for session
   VS-0D653BF9C3.

Entries are not guaranteed to be dicts: Pipecat's own message objects live in
the same list, so ``role`` is only probed on dicts rather than raising
AttributeError and killing the caller.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# First line of CallContext.crm_card(). Hoisted here so the enricher, the
# refresher and the tests all match on one literal.
CRM_CARD_PREFIX = "VERIFIED CUSTOMER FACTS"


def _is_developer_block(message: Any, prefix: str) -> bool:
    return (
        isinstance(message, dict)
        and message.get("role") == "developer"
        and isinstance(message.get("content"), str)
        and message["content"].startswith(prefix)
    )


def replace_developer_block(
    get_messages: Callable[[], list[Any] | None],
    set_messages: Callable[[list[Any]], None],
    *,
    prefix: str,
    message: dict[str, str],
) -> bool:
    """Evict any developer block starting with ``prefix``, then insert ``message``.

    Inserted just before the most recent ``user`` message so the model reads the
    facts as context for the turn it is about to answer, not as something said
    after it.

    Returns True if the context was rewritten. Never raises: both call sites are
    best-effort enrichment on the audio path, and neither should be able to kill
    a live call.
    """
    try:
        messages = list(get_messages() or [])
        cleaned = [m for m in messages if not _is_developer_block(m, prefix)]

        insert_at = len(cleaned)
        for i in range(len(cleaned) - 1, -1, -1):
            if isinstance(cleaned[i], dict) and cleaned[i].get("role") == "user":
                insert_at = i
                break

        cleaned.insert(insert_at, message)
        set_messages(cleaned)
        return True
    except Exception:
        logger.debug("developer block replace failed (prefix=%s)", prefix, exc_info=True)
        return False


def count_developer_blocks(messages: list[Any] | None, prefix: str) -> int:
    """How many blocks with this prefix are in the context — for tests and debug."""
    return sum(1 for m in (messages or []) if _is_developer_block(m, prefix))
