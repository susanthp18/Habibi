"""Temporal-shaped work runtime.

Go/no-go (Phase 4 start, from the implementation spec): promote to Temporal
only if HITL must pause **days** across deploys. In this product legal/field
approvals are same-shift Floor signals, bounce chase is same-hour, and
``worker.py`` / ``bot_worker.py`` already drain Postgres. Adapter v1 is
Postgres job rows (survives API restart). Adapter v2 is not selected while
``TEMPORAL_ENABLED`` is off; turning the flag on without a Temporal cluster
fails closed — it does not fake a workflow.

The mouth never awaits these APIs. It speaks and enqueues.
"""

from __future__ import annotations

from work_runtime.api import query, signal, start_workflow
from work_runtime.keys import idempotency_key

__all__ = ["start_workflow", "signal", "query", "idempotency_key"]
