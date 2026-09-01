"""Clerk agent — event-driven chase, same domain handlers, HITL that survives restart.

The mouth never awaits this module. Bounce ingest and broken-PTP settlement
enqueue a job; ``bot_worker`` drains it. Field/legal/goodwill park as
``input_required`` instead of cancelling into a retry loop.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from agent_core.treatment import actions as A
from agent_core.treatment import enact as treatment_enact
from work_runtime import idempotency_key, start_workflow
from work_runtime.adapter_pg import claim_next, finish, park_input_required

logger = logging.getLogger(__name__)

BOUNCE = "bounce_chase"
BROKEN_PTP = "broken_ptp"
DOC_SLA = "doc_sla"
CALLBACK = "callback_diary"
AUTHORITY_HITL = "authority_hitl"

HITL_ACTIONS = frozenset({A.FIELD_VISIT, A.LEGAL_NOTICE, "apply_goodwill"})

WORKFLOW_BY_TRIGGER = {
    "bounce": BOUNCE,
    "broken_ptp": BROKEN_PTP,
}


def enqueue_chase(
    *,
    workflow_type: str,
    trigger_ref: str,
    customer_id: str | None,
    decision_id: str | None = None,
    action: str | None = None,
    extra: dict[str, Any] | None = None,
    conn: Any | None = None,
) -> dict[str, Any] | None:
    """Idempotent enqueue. Missing tables must not take down bounce ingest."""
    try:
        payload = {
            "triggerRef": trigger_ref,
            "decisionId": decision_id,
            "action": action,
            **(extra or {}),
        }
        return start_workflow(
            workflow_type=workflow_type,
            payload=payload,
            customer_id=customer_id,
            idempotency_key=idempotency_key(
                workflow_type=workflow_type, trigger_ref=trigger_ref
            ),
            conn=conn,
        )
    except Exception:
        logger.exception("clerk enqueue failed type=%s ref=%s", workflow_type, trigger_ref)
        return None


def enqueue_from_treatment(
    *,
    trigger_kind: str,
    trigger_ref: str,
    customer_id: str | None,
    decision_id: str | None,
    action: str | None,
    conn: Any | None = None,
) -> dict[str, Any] | None:
    wf = WORKFLOW_BY_TRIGGER.get(trigger_kind)
    if not wf or not trigger_ref:
        return None
    return enqueue_chase(
        workflow_type=wf,
        trigger_ref=trigger_ref,
        customer_id=customer_id,
        decision_id=decision_id,
        action=action,
        conn=conn,
    )


def process_one() -> bool:
    """Drain one submitted/working clerk job. Never blocks a voice turn."""
    job = claim_next()
    if job is None:
        return False
    jid = job["id"]
    try:
        result = _run(job)
        finish(jid, ok=True, result=result)
    except _Parked:
        return True
    except Exception as exc:
        logger.exception("clerk job %s failed", jid)
        finish(jid, ok=False, error=str(exc)[:500])
    return True


class _Parked(Exception):
    """Job is waiting on a Floor signal. Not a failure."""


def _defer_hitl_plan(decision_id: str | None) -> None:
    """Keep claim_due from cancelling a parked field/legal plan."""
    if not decision_id:
        return
    import db

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE treatment_decisions
                   SET scheduled_at = now() + interval '30 days'
                 WHERE id = :id AND enacted IS FALSE AND outcome IS NULL
                """
            ),
            {"id": decision_id},
        )


def _run(job: dict[str, Any]) -> dict[str, Any]:
    payload = job.get("payload") or {}
    wf = str(job.get("workflowType") or "")
    if wf == "a2a_remote":
        return _finish_a2a_remote(payload)
    if wf in {DOC_SLA, CALLBACK}:
        return {"noted": True, "workflowType": wf, "ref": payload.get("triggerRef")}

    action = str(payload.get("action") or "")
    if action in HITL_ACTIONS or wf == AUTHORITY_HITL:
        if job.get("approvedBy"):
            return {"parked": False, "approved": True, "action": action, "enactedBy": "human"}
        _defer_hitl_plan(payload.get("decisionId"))
        park_input_required(job["id"], action or "supervisor_approval")
        raise _Parked()

    if action in {A.WAIT, ""}:
        return {"skipped": True, "reason": "wait"}

    decision_id = payload.get("decisionId")
    if not decision_id:
        return {"skipped": True, "reason": "no_decision"}

    import db
    from agent_core.treatment import config as treatment_config
    from agent_core.treatment import decisions

    if treatment_config.mode() != treatment_config.MODE_LIVE:
        return {"skipped": True, "reason": "not_live", "decisionId": decision_id}

    with db.engine.begin() as conn:
        row = decisions.claim_by_id(conn, str(decision_id))
        if row is None:
            existing = conn.execute(
                text("SELECT enacted, enacted_ref FROM treatment_decisions WHERE id = :id"),
                {"id": decision_id},
            ).mappings().first()
            if existing and existing["enacted"]:
                return {
                    "alreadyEnacted": True,
                    "decisionId": decision_id,
                    "ref": existing.get("enacted_ref"),
                }
            return {"skipped": True, "reason": "decision_gone", "decisionId": decision_id}
        acted, note = treatment_enact.enact_one(conn, row, enacted_by="clerk_agent")
    return {
        "acted": acted,
        "note": note,
        "decisionId": decision_id,
        "enactedBy": "clerk_agent",
    }


def _finish_a2a_remote(payload: dict[str, Any]) -> dict[str, Any]:
    """Complete an A2A task off the audio path. Never imports voice."""
    import db

    task_id = str(payload.get("taskId") or "").strip()
    if not task_id:
        return {"skipped": True, "reason": "no_task"}
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE a2a_tasks
                   SET status = 'completed',
                       output = CAST(:out AS jsonb),
                       updated_at = now()
                 WHERE id = :id AND status IN ('submitted','working')
                """
            ),
            {"id": task_id, "out": db._jsonb({"ok": True, "via": "work_runtime"})},
        )
    return {"taskId": task_id, "completed": True, "via": "work_runtime"}


def sweep_overdue() -> int:
    """Doc SLA + due callbacks → jobs. Idempotent per entity id."""
    import db

    n = 0
    try:
        with db.engine.connect() as conn:
            docs = db._rows(
                conn.execute(
                    text(
                        """
                        SELECT id, customer_id FROM document_requests
                         WHERE status = 'requested'
                           AND sla_due_at IS NOT NULL
                           AND sla_due_at <= now()
                         ORDER BY sla_due_at
                         LIMIT 20
                        """
                    )
                )
            )
            followups = db._rows(
                conn.execute(
                    text(
                        """
                        SELECT id, customer_id FROM followups
                         WHERE status = 'open'
                           AND due_at IS NOT NULL
                           AND due_at <= now()
                         ORDER BY due_at
                         LIMIT 20
                        """
                    )
                )
            )
    except Exception:
        logger.exception("clerk sweep query failed")
        return 0
    for row in docs:
        if enqueue_chase(
            workflow_type=DOC_SLA,
            trigger_ref=row["id"],
            customer_id=row.get("customer_id"),
            extra={"documentId": row["id"]},
        ):
            n += 1
    for row in followups:
        if enqueue_chase(
            workflow_type=CALLBACK,
            trigger_ref=row["id"],
            customer_id=row.get("customer_id"),
            extra={"followupId": row["id"]},
        ):
            n += 1
    return n
