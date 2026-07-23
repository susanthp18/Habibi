"""Postgres SKIP LOCKED queue for WhatsApp / shared bot turns.

Contract matches whatsapp_reply_bot_plan.md §4 — broker-swappable later (Arq).
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)


def bot_runtime_enabled() -> bool:
    return (os.getenv("BOT_RUNTIME_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}


def bot_environment() -> str:
    return (os.getenv("BOT_ENVIRONMENT") or "production").strip() or "production"


def max_attempts() -> int:
    try:
        return max(1, int((os.getenv("BOT_JOB_MAX_ATTEMPTS") or "5").strip()))
    except ValueError:
        return 5


def stale_running_seconds() -> int:
    try:
        return max(60, int((os.getenv("BOT_JOB_STALE_RUNNING_SEC") or "300").strip()))
    except ValueError:
        return 300


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _job_id() -> str:
    return f"BTJ-{uuid.uuid4().hex[:12].upper()}"


def enqueue_bot_turn(
    conn: Connection,
    *,
    conversation_id: str,
    customer_id: str,
    trigger_message_id: str,
    trigger_provider_ref: str | None,
    interaction_id: str | None = None,
    channel: str = "whatsapp",
) -> dict[str, Any] | None:
    """Insert a queued job in the same txn as inbound ingest. Idempotent on provider_ref."""
    if not bot_runtime_enabled():
        return None
    if trigger_provider_ref:
        existing = conn.execute(
            text(
                """
                SELECT id, status FROM bot_turn_jobs
                WHERE trigger_provider_ref = :ref
                LIMIT 1
                """
            ),
            {"ref": trigger_provider_ref},
        ).fetchone()
        if existing:
            return dict(existing._mapping)

    jid = _job_id()
    try:
        # Savepoint: a unique violation here otherwise aborts the shared ingest
        # transaction, and the recovery SELECT below would fail on the same conn.
        with conn.begin_nested():
            conn.execute(
                text(
                    """
                    INSERT INTO bot_turn_jobs (
                      id, conversation_id, interaction_id, customer_id,
                      trigger_message_id, trigger_provider_ref, channel, status
                    ) VALUES (
                      :id, :conversation_id, :interaction_id, :customer_id,
                      :trigger_message_id, :trigger_provider_ref, :channel, 'queued'
                    )
                    """
                ),
                {
                    "id": jid,
                    "conversation_id": conversation_id,
                    "interaction_id": interaction_id,
                    "customer_id": customer_id,
                    "trigger_message_id": trigger_message_id,
                    "trigger_provider_ref": trigger_provider_ref,
                    "channel": channel,
                },
            )
    except Exception as exc:
        # Unique violation on trigger_provider_ref under concurrent Meta retries.
        if trigger_provider_ref and "uq_bot_turn_jobs_trigger_provider_ref" in str(exc):
            row = conn.execute(
                text("SELECT id, status FROM bot_turn_jobs WHERE trigger_provider_ref = :ref LIMIT 1"),
                {"ref": trigger_provider_ref},
            ).fetchone()
            return dict(row._mapping) if row else None
        raise
    logger.info(
        "bot_turn enqueued job=%s conversation=%s message=%s",
        jid,
        conversation_id,
        trigger_message_id,
    )
    return {"id": jid, "status": "queued"}


def reclaim_stuck_jobs(conn: Connection) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_running_seconds())
    result = conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'queued',
                locked_at = NULL,
                locked_by = NULL,
                error = COALESCE(error, '') || ' [requeued: stuck running]',
                updated_at = now()
            WHERE status = 'running' AND COALESCE(locked_at, updated_at) < :cutoff
            """
        ),
        {"cutoff": cutoff},
    )
    return result.rowcount or 0


def claim_next_job(conn: Connection) -> dict[str, Any] | None:
    """Claim one queued job with single-flight per conversation (no unique index).

    Skips conversations that already have a running job. After claim, supersedes
    sibling queued jobs so a burst gets one coalesced reply.
    """
    row = conn.execute(
        text(
            """
            SELECT j.id, j.conversation_id, j.interaction_id, j.customer_id,
                   j.trigger_message_id, j.trigger_provider_ref, j.channel,
                   j.attempt, j.outbound_message_id
            FROM bot_turn_jobs j
            WHERE j.status = 'queued'
              AND (j.run_after IS NULL OR j.run_after <= now())
              AND NOT EXISTS (
                SELECT 1 FROM bot_turn_jobs r
                WHERE r.conversation_id = j.conversation_id
                  AND r.status = 'running'
              )
            ORDER BY j.created_at ASC
            FOR UPDATE OF j SKIP LOCKED
            LIMIT 1
            """
        )
    ).fetchone()
    if row is None:
        return None

    job = dict(row._mapping)
    worker = _worker_id()
    conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'running',
                attempt = attempt + 1,
                locked_at = now(),
                locked_by = :locked_by,
                updated_at = now(),
                error = NULL
            WHERE id = :id
            """
        ),
        {"id": job["id"], "locked_by": worker},
    )
    job["attempt"] = int(job.get("attempt") or 0) + 1
    job["locked_by"] = worker

    # Coalesce: later queued siblings for this conversation won't run separately.
    conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'superseded',
                superseded_by_job_id = :id,
                updated_at = now()
            WHERE conversation_id = :conversation_id
              AND status = 'queued'
              AND id <> :id
            """
        ),
        {"id": job["id"], "conversation_id": job["conversation_id"]},
    )
    # Drop draft outbound rows from superseded jobs (never reached WhatsApp).
    conn.execute(
        text(
            """
            DELETE FROM messages m
            USING bot_turn_jobs j
            WHERE j.conversation_id = :conversation_id
              AND j.superseded_by_job_id = :id
              AND m.bot_turn_job_id = j.id
              AND COALESCE(m.delivery_status, '') IN ('sending', 'failed')
            """
        ),
        {"id": job["id"], "conversation_id": job["conversation_id"]},
    )
    return job


def mark_succeeded(conn: Connection, job_id: str, *, outbound_message_id: str | None = None) -> None:
    conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'succeeded',
                outbound_message_id = COALESCE(:outbound_message_id, outbound_message_id),
                locked_at = NULL,
                locked_by = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": job_id, "outbound_message_id": outbound_message_id},
    )


def mark_cancelled(conn: Connection, job_id: str, reason: str) -> None:
    conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'cancelled',
                error = :error,
                locked_at = NULL,
                locked_by = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": job_id, "error": reason},
    )


def mark_failed_or_retry(conn: Connection, job: dict[str, Any], error: str) -> str:
    """Backoff retry or dead-letter. Returns final status."""
    attempt = int(job.get("attempt") or 1)
    cap = max_attempts()
    if attempt >= cap:
        conn.execute(
            text(
                """
                UPDATE bot_turn_jobs
                SET status = 'dead',
                    error = :error,
                    locked_at = NULL,
                    locked_by = NULL,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job["id"], "error": error[:2000]},
        )
        return "dead"

    delay_sec = min(300, 2 ** min(attempt, 6))
    run_after = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
    conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'queued',
                error = :error,
                run_after = :run_after,
                locked_at = NULL,
                locked_by = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": job["id"], "error": error[:2000], "run_after": run_after},
    )
    return "queued"


def record_tool_call(
    conn: Connection,
    *,
    job_id: str,
    conversation_id: str,
    tool_name: str,
    args: dict[str, Any],
    result_ok: bool,
    error: str | None = None,
    result_preview: str | None = None,
    latency_ms: int | None = None,
) -> str:
    tid = f"BTC-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO bot_tool_calls (
              id, job_id, conversation_id, tool_name, args,
              result_ok, error, result_preview, latency_ms
            ) VALUES (
              :id, :job_id, :conversation_id, :tool_name, CAST(:args AS jsonb),
              :result_ok, :error, :result_preview, :latency_ms
            )
            """
        ),
        {
            "id": tid,
            "job_id": job_id,
            "conversation_id": conversation_id,
            "tool_name": tool_name,
            "args": __import__("json").dumps(args or {}),
            "result_ok": result_ok,
            "error": (error or "")[:2000] if error else None,
            "result_preview": (result_preview or "")[:2000] if result_preview else None,
            "latency_ms": latency_ms,
        },
    )
    return tid


def process_one(engine: Engine) -> bool:
    """Claim + run one bot turn. Returns True if a job was claimed."""
    import bot_runtime

    with engine.begin() as conn:
        reclaim_stuck_jobs(conn)
        job = claim_next_job(conn)
    if not job:
        return False

    try:
        bot_runtime.handle_turn(engine, job)
    except Exception as exc:
        logger.exception("bot_turn failed job=%s", job.get("id"))
        with engine.begin() as conn:
            status = mark_failed_or_retry(conn, job, str(exc))
        if status == "dead":
            try:
                import db

                db.escalate_conversation_to_human(
                    job["conversation_id"],
                    reason=f"bot_turn_dead: {exc}",
                )
            except Exception:
                logger.exception("dead-letter escalate failed conversation=%s", job.get("conversation_id"))
    return True


def drain_queue(engine: Engine, *, limit: int = 50) -> int:
    n = 0
    for _ in range(limit):
        if not process_one(engine):
            break
        n += 1
    return n
