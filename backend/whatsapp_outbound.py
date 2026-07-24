"""SKIP LOCKED queue for agent WhatsApp outbound sends.

Agent replies must not block the CRM HTTP path on Meta Graph latency.
API inserts messages as delivery_status='sending', enqueues a job here, and
returns immediately. bot_worker drains both bot_turn_jobs and this queue.
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


def max_attempts() -> int:
    try:
        return max(1, int((os.getenv("WHATSAPP_OUTBOUND_MAX_ATTEMPTS") or "5").strip()))
    except ValueError:
        return 5


def stale_running_seconds() -> int:
    try:
        return max(60, int((os.getenv("WHATSAPP_OUTBOUND_STALE_RUNNING_SEC") or "180").strip()))
    except ValueError:
        return 180


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _job_id() -> str:
    return f"WAO-{uuid.uuid4().hex[:12].upper()}"


def enqueue_agent_send(
    conn: Connection,
    *,
    message_id: str,
    conversation_id: str,
    customer_id: str | None,
    to_phone: str,
    body: str,
) -> dict[str, Any]:
    """Enqueue (or return existing) outbound job for a pre-inserted 'sending' message."""
    existing = conn.execute(
        text(
            """
            SELECT id, status FROM whatsapp_outbound_jobs
            WHERE message_id = :message_id
            LIMIT 1
            """
        ),
        {"message_id": message_id},
    ).fetchone()
    if existing:
        return dict(existing._mapping)

    jid = _job_id()
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    """
                    INSERT INTO whatsapp_outbound_jobs (
                      id, message_id, conversation_id, customer_id,
                      to_phone, body, status
                    ) VALUES (
                      :id, :message_id, :conversation_id, :customer_id,
                      :to_phone, :body, 'queued'
                    )
                    """
                ),
                {
                    "id": jid,
                    "message_id": message_id,
                    "conversation_id": conversation_id,
                    "customer_id": customer_id,
                    "to_phone": to_phone,
                    "body": body,
                },
            )
    except Exception as exc:
        if "uq_whatsapp_outbound_jobs_message_id" in str(exc):
            row = conn.execute(
                text(
                    "SELECT id, status FROM whatsapp_outbound_jobs WHERE message_id = :message_id LIMIT 1"
                ),
                {"message_id": message_id},
            ).fetchone()
            if row:
                return dict(row._mapping)
        raise
    logger.info(
        "whatsapp_outbound enqueued job=%s message=%s conversation=%s",
        jid,
        message_id,
        conversation_id,
    )
    return {"id": jid, "status": "queued"}


def reclaim_stuck_jobs(conn: Connection) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_running_seconds())
    result = conn.execute(
        text(
            """
            UPDATE whatsapp_outbound_jobs
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
    row = conn.execute(
        text(
            """
            SELECT id, message_id, conversation_id, customer_id,
                   to_phone, body, attempt
            FROM whatsapp_outbound_jobs
            WHERE status = 'queued'
              AND (run_after IS NULL OR run_after <= now())
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
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
            UPDATE whatsapp_outbound_jobs
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
    return job


def mark_succeeded(conn: Connection, job_id: str, *, provider_ref: str | None) -> None:
    conn.execute(
        text(
            """
            UPDATE whatsapp_outbound_jobs
            SET status = 'succeeded',
                provider_ref = COALESCE(:provider_ref, provider_ref),
                locked_at = NULL,
                locked_by = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": job_id, "provider_ref": provider_ref},
    )


def mark_failed_or_retry(conn: Connection, job: dict[str, Any], error: str) -> str:
    attempt = int(job.get("attempt") or 1)
    cap = max_attempts()
    if attempt >= cap:
        conn.execute(
            text(
                """
                UPDATE whatsapp_outbound_jobs
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

    delay_sec = min(120, 2 ** min(attempt, 5))
    run_after = datetime.now(timezone.utc) + timedelta(seconds=delay_sec)
    conn.execute(
        text(
            """
            UPDATE whatsapp_outbound_jobs
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


def handle_job(engine: Engine, job: dict[str, Any]) -> None:
    """Send via Meta Graph and update the messages row."""
    import whatsapp as wa

    message_id = job["message_id"]
    to_phone = job["to_phone"]
    body = job["body"]

    # Idempotent: if another worker already marked sent, succeed quietly.
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT delivery_status, provider_ref
                FROM messages WHERE id = :id
                """
            ),
            {"id": message_id},
        ).fetchone()
    if row is None:
        with engine.begin() as conn:
            mark_failed_or_retry(conn, job, "message_not_found")
        return
    delivery = (row._mapping.get("delivery_status") or "").strip().lower()
    if delivery in {"sent", "delivered", "read"}:
        with engine.begin() as conn:
            mark_succeeded(conn, job["id"], provider_ref=row._mapping.get("provider_ref"))
        return

    try:
        send_resp = wa.send_text_message(to_phone=to_phone, body=body)
        provider_ref = wa.extract_wamid(send_resp)
    except Exception as exc:
        err = str(exc)
        logger.warning("whatsapp_outbound send failed job=%s err=%s", job["id"], err)
        with engine.begin() as conn:
            status = mark_failed_or_retry(conn, job, err)
            if status == "dead":
                conn.execute(
                    text(
                        """
                        UPDATE messages
                        SET delivery_status = 'failed'
                        WHERE id = :id AND COALESCE(delivery_status, '') = 'sending'
                        """
                    ),
                    {"id": message_id},
                )
                # Touch conversation so inbox deltas pick up the failure.
                conn.execute(
                    text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
                    {"id": job["conversation_id"]},
                )
        return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE messages
                SET delivery_status = 'sent',
                    provider_ref = COALESCE(:ref, provider_ref)
                WHERE id = :id
                """
            ),
            {"id": message_id, "ref": provider_ref},
        )
        conn.execute(
            text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
            {"id": job["conversation_id"]},
        )
        mark_succeeded(conn, job["id"], provider_ref=provider_ref)
    logger.info(
        "whatsapp_outbound sent job=%s message=%s provider_ref=%s",
        job["id"],
        message_id,
        provider_ref,
    )


def process_one(engine: Engine) -> bool:
    """Claim + run one outbound send. Returns True if a job was claimed."""
    with engine.begin() as conn:
        reclaim_stuck_jobs(conn)
        job = claim_next_job(conn)
    if not job:
        return False
    try:
        handle_job(engine, job)
    except Exception as exc:
        logger.exception("whatsapp_outbound crashed job=%s", job.get("id"))
        with engine.begin() as conn:
            status = mark_failed_or_retry(conn, job, str(exc))
            if status == "dead":
                conn.execute(
                    text(
                        """
                        UPDATE messages
                        SET delivery_status = 'failed'
                        WHERE id = :id AND COALESCE(delivery_status, '') = 'sending'
                        """
                    ),
                    {"id": job["message_id"]},
                )
                conn.execute(
                    text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
                    {"id": job["conversation_id"]},
                )
    return True
