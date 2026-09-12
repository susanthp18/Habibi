"""Temporal-shaped work runtime.

Go/no-go (Phase 4 start, from the implementation spec): promote to Temporal
only if HITL must pause **days** across deploys. In this product legal/field
approvals are same-shift Floor signals, bounce chase is same-hour, and
``worker.py`` / ``bot_worker.py`` already drain Postgres — so the answer is no,
and the runtime is Postgres job rows that survive an API restart.

That answer is why there is no adapter seam here any more. A ``WorkRuntime``
Protocol, a ``TEMPORAL_ENABLED`` selector and a second adapter whose every
method raised were carried for a promotion this product had already declined.
``api.py`` names the one adapter; callers reach ``api.py``.

The mouth never awaits these APIs. It speaks and enqueues.
"""

from __future__ import annotations

from work_runtime.api import (
    claim_next,
    finish,
    list_jobs,
    park_input_required,
    query,
    signal,
    start_workflow,
    upsert_job,
)
from work_runtime.keys import idempotency_key

__all__ = [
    "start_workflow",
    "signal",
    "query",
    "list_jobs",
    "claim_next",
    "finish",
    "park_input_required",
    "upsert_job",
    "idempotency_key",
]
