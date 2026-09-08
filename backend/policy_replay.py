"""Read-only policy replay. Writes only ``policy_replay_results``.

Refuses missing bindings, an unknown evaluator digest, or an incompatible
veto-stack version. Never mutates decision rows.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text

from agent_core import logging_contract
from agent_core.treatment import schema_ready

logger = logging.getLogger(__name__)

REFUSE_MISSING_BINDING = "missing_binding"
REFUSE_DIGEST = "unknown_evaluator_digest"
REFUSE_VETO_STACK = "incompatible_veto_stack"
REFUSE_SCHEMA = "schema_not_ready"


def replay(
    conn: Any,
    *,
    window_start: datetime,
    window_end: datetime,
    expected_digest: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Compare stored bindings in ``window`` against the current evaluator."""
    result_id = f"PRP-{uuid.uuid4().hex[:10].upper()}"
    current_digest = logging_contract.engine_image_digest()
    veto = logging_contract.VETO_STACK_VERSION
    status = "completed"
    reason: str | None = None
    compared = 0
    mismatched = 0

    if not schema_ready.w4_ready(conn):
        status, reason = "refused", REFUSE_SCHEMA
    elif expected_digest and expected_digest != current_digest:
        status, reason = "refused", REFUSE_DIGEST
    else:
        rows = conn.execute(
            text(
                """
                SELECT id, policy_binding, policy_binding_hash, veto_stack_version,
                       engine_image_digest
                FROM treatment_decisions
                WHERE created_at >= :start AND created_at < :end
                  AND (:tid IS NULL OR tenant_id = :tid)
                """
            ),
            {"start": window_start, "end": window_end, "tid": tenant_id},
        ).mappings().all()
        for row in rows:
            compared += 1
            if not row["policy_binding"] or not row["policy_binding_hash"]:
                status, reason = "refused", REFUSE_MISSING_BINDING
                break
            if row["veto_stack_version"] and row["veto_stack_version"] != veto:
                status, reason = "refused", REFUSE_VETO_STACK
                break
            if (
                row["engine_image_digest"]
                and expected_digest
                and row["engine_image_digest"] != expected_digest
            ):
                mismatched += 1
        else:
            if mismatched:
                status = "partial"

    payload = {
        "id": result_id,
        "status": status,
        "refusalReason": reason,
        "compared": compared,
        "mismatched": mismatched,
        "evaluatorDigest": current_digest,
        "vetoStackVersion": veto,
    }
    if schema_ready.has_table(conn, "policy_replay_results"):
        conn.execute(
            text(
                """
                INSERT INTO policy_replay_results (
                  id, tenant_id, window_start, window_end, requested_digest,
                  evaluator_digest, veto_stack_version, status, refusal_reason,
                  compared, mismatched, result
                ) VALUES (
                  :id, :tid, :start, :end, :requested, :digest, :veto,
                  :status, :reason, :compared, :mismatched, CAST(:result AS jsonb)
                )
                """
            ),
            {
                "id": result_id,
                "tid": tenant_id,
                "start": window_start,
                "end": window_end,
                "requested": expected_digest or current_digest,
                "digest": current_digest,
                "veto": veto,
                "status": status,
                "reason": reason,
                "compared": compared,
                "mismatched": mismatched,
                "result": __import__("json").dumps(payload),
            },
        )
    return payload
