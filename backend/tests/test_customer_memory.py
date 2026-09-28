"""Cross-call customer memory (voice/memory.py).

The summariser writes free text that sits next to authoritative CRM facts in the
same context window. Session VS-0D653BF9C3 is on record for what happens when a
generic summary contradicts a live tool result. These tests pin the *structural*
defences — the ones that hold whether or not the model follows its instructions.
"""

from __future__ import annotations


# ------------------------------------------------------------------ constants


def test_closed_status_sets_match_the_real_check_constraints() -> None:
    """These were wrong before: document_requests has no "delivered" or
    "cancelled" status, so the filter matched nothing and every fulfilled
    request stayed on the CRM card as open work forever."""
    from agent_core.context import (
        CLOSED_CALLBACK_STATUSES,
        CLOSED_DISPUTE_STATUSES,
        CLOSED_DOCUMENT_STATUSES,
        CLOSED_PROMISE_STATUSES,
    )

    legal = {
        # sql/05 plus the `cancelled` that sql/52 (pass 7) added.
        "promises": {"upcoming", "due_today", "kept", "broken", "partial", "cancelled"},
        "disputes": {"new", "under_review", "awaiting_customer", "resolved", "rejected"},
        "document_requests": {"requested", "generating", "sent", "failed"},
        "callbacks": {
            "scheduled",
            "reminded",
            "in_progress",
            "completed",
            "missed",
            "rescheduled",
            "cancelled",
        },
    }
    assert CLOSED_PROMISE_STATUSES <= legal["promises"]
    assert CLOSED_DISPUTE_STATUSES <= legal["disputes"]
    assert CLOSED_DOCUMENT_STATUSES <= legal["document_requests"]
    assert CLOSED_CALLBACK_STATUSES <= legal["callbacks"]
    # Non-empty, or the "open work" filter silently matches everything.
    for s in (
        CLOSED_PROMISE_STATUSES,
        CLOSED_DISPUTE_STATUSES,
        CLOSED_DOCUMENT_STATUSES,
        CLOSED_CALLBACK_STATUSES,
    ):
        assert s
