"""Postgres SKIP LOCKED queue for WhatsApp / shared bot turns.

Contract matches whatsapp_reply_bot_plan.md §4 — broker-swappable later (Arq).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

import pii_redact
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

from pg_errors import PG_UNIQUE_VIOLATION, is_unique_violation as _is_unique_violation  # noqa: F401

logger = logging.getLogger(__name__)

# Cap the accumulated `error` text so repeated reclaims cannot grow the column
# without bound.
MAX_JOB_ERROR_CHARS = 2000

# How many advisory-lock misses claim_next_job walks past before reporting an
# empty queue. Bounded so a heavily contended queue cannot spin the worker.
_CLAIM_ATTEMPTS = 3


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
    except IntegrityError as exc:
        # Unique violation on trigger_provider_ref under concurrent Meta retries.
        # Match on SQLSTATE, not the constraint name in the message text: the
        # text is driver- and locale-dependent, and a substring match would also
        # swallow an unrelated FK/NOT NULL violation mentioning the same name.
        if trigger_provider_ref and _is_unique_violation(exc):
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


def reclaim_stuck_jobs(conn: Connection) -> list[dict[str, str]]:
    """Recover jobs whose worker died mid-run.

    Bounded by ``attempt``: a job at or past BOT_JOB_MAX_ATTEMPTS is
    dead-lettered instead of being re-queued forever (a poison turn would
    otherwise occupy the single-flight slot for its conversation indefinitely).
    The accumulated ``error`` text is truncated so repeated reclaims cannot grow
    the column without bound.

    Returns the jobs transitioned straight to ``dead`` so the caller can
    escalate their conversations. Without this the customer's last message
    simply never got a reply and nothing surfaced in the Inbox — the
    mark_failed_or_retry path escalates, this one used to go silent.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_running_seconds())
    result = conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = CASE WHEN attempt >= :cap THEN 'dead' ELSE 'queued' END,
                locked_at = NULL,
                locked_by = NULL,
                error = left(
                  COALESCE(error, '') || CASE
                    WHEN attempt >= :cap THEN ' [dead: stuck running, attempts exhausted]'
                    ELSE ' [requeued: stuck running]'
                  END,
                  :max_error
                ),
                updated_at = now()
            WHERE status = 'running' AND COALESCE(locked_at, updated_at) < :cutoff
            RETURNING id, conversation_id, status
            """
        ),
        {
            "cutoff": cutoff,
            "cap": max_attempts(),
            "max_error": MAX_JOB_ERROR_CHARS,
        },
    )
    return [
        {"id": r["id"], "conversationId": r["conversation_id"]}
        for r in result.mappings().all()
        if r["status"] == "dead"
    ]


def claim_next_job(conn: Connection) -> dict[str, Any] | None:
    """Claim one queued job with single-flight per conversation (no unique index).

    Skips conversations that already have a running job. After claim, supersedes
    sibling queued jobs so a burst gets one coalesced reply.
    """
    # Two steps on purpose. Putting pg_try_advisory_xact_lock() in the WHERE of
    # the scan let Postgres evaluate it for candidate rows it then discarded via
    # ORDER BY / SKIP LOCKED / LIMIT, so a worker ended up holding transaction
    # advisory locks on conversations it never claimed — blocking other workers
    # from claiming those until this transaction committed. The CTE pins exactly
    # one row, and only that row's conversation is locked.
    #
    # The lock verdict comes back with the row rather than filtering it out: a
    # candidate whose conversation another worker already holds used to make the
    # whole query return nothing, so the worker concluded the queue was empty
    # and slept while other conversations had jobs waiting. Retry a bounded
    # number of times, excluding the conversations that lost the race.
    row = None
    skip: list[str] = []
    for _ in range(_CLAIM_ATTEMPTS):
        candidate = conn.execute(
            text(
                """
                WITH candidate AS (
                    SELECT j.id, j.conversation_id, j.interaction_id, j.customer_id,
                           j.trigger_message_id, j.trigger_provider_ref, j.channel,
                           j.attempt, j.outbound_message_id, j.error
                    FROM bot_turn_jobs j
                    WHERE j.status = 'queued'
                      AND (j.run_after IS NULL OR j.run_after <= now())
                      AND j.conversation_id <> ALL(:skip)
                      AND NOT EXISTS (
                        SELECT 1 FROM bot_turn_jobs r
                        WHERE r.conversation_id = j.conversation_id
                          AND r.status = 'running'
                      )
                    ORDER BY j.created_at ASC
                    FOR UPDATE OF j SKIP LOCKED
                    LIMIT 1
                )
                SELECT *,
                       pg_try_advisory_xact_lock(hashtext(conversation_id)) AS claimed
                FROM candidate
                """
            ),
            {"skip": skip},
        ).fetchone()
        if candidate is None:
            return None
        if candidate._mapping["claimed"]:
            row = candidate
            break
        skip.append(candidate._mapping["conversation_id"])
    if row is None:
        return None

    job = dict(row._mapping)
    job.pop("claimed", None)  # lock verdict, not a job column
    worker = _worker_id()
    conn.execute(
        text(
            """
            UPDATE bot_turn_jobs
            SET status = 'running',
                attempt = attempt + 1,
                locked_at = now(),
                locked_by = :locked_by,
                updated_at = now()
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
              AND COALESCE(m.delivery_status, '') = 'failed'
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
        {"id": job_id, "error": (reason or "")[:MAX_JOB_ERROR_CHARS]},
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
            {"id": job["id"], "error": error[:MAX_JOB_ERROR_CHARS]},
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
        {"id": job["id"], "error": error[:MAX_JOB_ERROR_CHARS], "run_after": run_after},
    )
    return "queued"


def record_tool_call(
    conn: Connection,
    *,
    job_id: str | None = None,
    conversation_id: str | None = None,
    interaction_id: str | None = None,
    transcript_turn_id: str | None = None,
    channel: str | None = None,
    tool_name: str,
    args: dict[str, Any],
    result_ok: bool,
    error: str | None = None,
    result_preview: str | None = None,
    latency_ms: int | None = None,
    agent_id: str | None = None,
    skill_id: str | None = None,
    connector_id: str | None = None,
) -> str:
    """Audit one CRM tool call, on any channel.

    ``job_id``/``conversation_id`` are the WhatsApp/text identity;
    ``interaction_id``/``transcript_turn_id`` are the voice one. At least one of
    ``job_id`` or ``interaction_id`` must be present — a tool call nobody can
    attribute is not an audit record, and the table's CHECK enforces it.

    Voice tool calls were previously not recorded here at all, so the audit
    trail covered WhatsApp and nothing else.
    """
    if not job_id and not interaction_id:
        raise ValueError("record_tool_call requires job_id or interaction_id")

    # Redaction happens here, not at the call sites.
    #
    # It used to live in voice/persist._audit_args and was applied on the voice
    # path alone, so WhatsApp (bot_runtime), MCP (its own raw INSERT) and the
    # sandbox wrote arguments and results verbatim. `identify_customer` is a
    # text-channel-only spec taking `phone` and `account_tail` -- exactly what
    # voice withholds -- and it landed in a column the Inbox renders.
    #
    # Four executors each remembering to call a helper is how that happened. One
    # function writes this row; putting it here means a fifth channel cannot get
    # it wrong, and `result_preview` -- which is bigger and leakier than the
    # arguments, being what the CRM sent back -- is covered by construction too.
    args = pii_redact.audit_args(tool_name, args)
    result_preview = pii_redact.audit_preview(result_preview)

    tid = f"BTC-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO bot_tool_calls (
              id, job_id, conversation_id, interaction_id, transcript_turn_id,
              channel, tool_name, args,
              result_ok, error, result_preview, latency_ms,
              agent_id, skill_id, connector_id
            ) VALUES (
              :id, :job_id, :conversation_id, :interaction_id, :transcript_turn_id,
              :channel, :tool_name, CAST(:args AS jsonb),
              :result_ok, :error, :result_preview, :latency_ms,
              :agent_id, :skill_id, :connector_id
            )
            """
        ),
        {
            "id": tid,
            "job_id": job_id,
            "conversation_id": conversation_id,
            "interaction_id": interaction_id,
            "transcript_turn_id": transcript_turn_id,
            "channel": channel,
            "tool_name": tool_name,
            "args": json.dumps(args or {}),
            "result_ok": result_ok,
            "error": (error or "")[:MAX_JOB_ERROR_CHARS] if error else None,
            "result_preview": (result_preview or "")[:MAX_JOB_ERROR_CHARS] if result_preview else None,
            "latency_ms": latency_ms,
            "agent_id": agent_id,
            "skill_id": skill_id,
            "connector_id": connector_id,
        },
    )
    return tid


def process_one(engine: Engine) -> bool:
    """Claim + run one bot turn. Returns True if a job was claimed."""
    import bot_runtime

    with engine.begin() as conn:
        reclaimed_dead = reclaim_stuck_jobs(conn)
        job = claim_next_job(conn)

    # Escalate before taking the next turn: a dead-lettered job means the
    # customer is waiting on a reply that is never coming.
    for dead in reclaimed_dead:
        try:
            import db

            db.escalate_conversation_to_human(
                dead["conversationId"],
                reason=f"bot_turn_dead: reclaim exhausted attempts (job {dead['id']})",
            )
        except Exception:
            logger.exception(
                "reclaimed dead-letter escalate failed conversation=%s",
                dead.get("conversationId"),
            )

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
