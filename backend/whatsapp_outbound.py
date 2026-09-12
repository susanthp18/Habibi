"""SKIP LOCKED queue for agent WhatsApp outbound sends.

Agent replies must not block the CRM HTTP path on Meta Graph latency.
API inserts messages as delivery_status='sending', enqueues a job here, and
returns immediately. bot_worker drains both bot_turn_jobs and this queue.
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
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError

import bot_jobs

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


_DECISION_COL: bool | None = None


def _jobs_have_decision_id(conn: Connection) -> bool:
    global _DECISION_COL
    if _DECISION_COL is not None:
        return _DECISION_COL
    try:
        found = conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'whatsapp_outbound_jobs'
                  AND column_name = 'decision_id'
                """
            )
        ).first()
        _DECISION_COL = found is not None
    except Exception:
        _DECISION_COL = False
    return _DECISION_COL


def enqueue_agent_send(
    conn: Connection,
    *,
    message_id: str,
    conversation_id: str,
    customer_id: str | None,
    to_phone: str,
    body: str,
    preview_url: bool = False,
    template_name: str | None = None,
    template_lang: str | None = None,
    template_params: list[str] | None = None,
    purpose: str | None = None,
    source: str | None = None,
    decision_id: str | None = None,
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
    params_json = json.dumps(template_params) if template_params is not None else None
    has_decision = _jobs_have_decision_id(conn)
    cols = """
                      id, message_id, conversation_id, customer_id,
                      to_phone, body, preview_url, template_name, template_lang,
                      template_params, purpose, source, status
    """
    vals = """
                      :id, :message_id, :conversation_id, :customer_id,
                      :to_phone, :body, :preview_url, :template_name, :template_lang,
                      CAST(:template_params AS jsonb), :purpose, :source, 'queued'
    """
    payload = {
        "id": jid,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "customer_id": customer_id,
        "to_phone": to_phone,
        "body": body,
        "preview_url": bool(preview_url),
        "template_name": template_name,
        "template_lang": template_lang,
        "template_params": params_json,
        "purpose": purpose,
        "source": source,
    }
    if has_decision:
        cols += ", decision_id"
        vals += ", :decision_id"
        payload["decision_id"] = decision_id
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    f"""
                    INSERT INTO whatsapp_outbound_jobs (
                    {cols}
                    ) VALUES (
                    {vals}
                    )
                    """
                ),
                payload,
            )
    except IntegrityError as exc:
        # A concurrent enqueue for the same message already won. Detect via
        # SQLSTATE 23505 rather than the constraint name in the driver's message
        # text, which is not part of any stable contract.
        if bot_jobs._is_unique_violation(exc):
            row = conn.execute(
                text(
                    "SELECT id, status FROM whatsapp_outbound_jobs WHERE message_id = :message_id LIMIT 1"
                ),
                {"message_id": message_id},
            ).fetchone()
            if row:
                return dict(row._mapping)
            # Unique violation on some other constraint (or the row vanished) —
            # nothing safe to return, so surface it.
        raise
    logger.info(
        "whatsapp_outbound enqueued job=%s message=%s conversation=%s",
        jid,
        message_id,
        conversation_id,
    )
    _warn_if_queue_is_not_draining(conn)
    return {"id": jid, "status": "queued"}


#: A queued job older than this, at the moment a new one is enqueued, means
#: nothing is consuming the queue. Generous enough that a slow provider call or
#: a retry backoff does not trip it.
_STALE_QUEUE_SECONDS = 120


def _warn_if_queue_is_not_draining(conn: Connection) -> None:
    """Say so when a send is being queued into a queue nobody is reading.

    ``send_conversation_message`` returns 200 as soon as the row is written, so
    an agent whose reply is never posted gets no signal at all — not from the
    API, not from the composer. An operator ran the API without ``bot_worker``,
    took over a conversation, sent two replies, and watched a customer not
    receive them; the only trace was two rows sitting at ``queued``.

    Cheap enough to run here: agent sends are human-paced, and this is one
    indexed aggregate. Never raises — a diagnostic that can fail a send is
    worse than no diagnostic.
    """
    try:
        row = conn.execute(
            text(
                """
                SELECT count(*) AS n,
                       COALESCE(EXTRACT(EPOCH FROM (now() - min(created_at))), 0) AS oldest_s
                  FROM whatsapp_outbound_jobs
                 WHERE status = 'queued'
                   -- Claimable only. A job deferred by contact policy sits
                   -- queued with a far-future run_after *by design*, and
                   -- counting it here would report a stalled worker every time
                   -- a borrower was inside their cooling-off window.
                   AND (run_after IS NULL OR run_after <= now())
                """
            )
        ).fetchone()
        if row is None:
            return
        oldest = float(row._mapping["oldest_s"] or 0)
        if oldest >= _STALE_QUEUE_SECONDS:
            logger.warning(
                "whatsapp_outbound queue is not draining — %s job(s) queued, oldest %.0fs. "
                "Nothing will be delivered until `python -m bot_worker` is running.",
                int(row._mapping["n"] or 0),
                oldest,
            )
    except Exception:
        logger.debug("outbound queue staleness check failed", exc_info=True)


def reclaim_stuck_jobs(conn: Connection) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_running_seconds())
    # POST already attempted — do not requeue (duplicate-send risk); dead-letter instead.
    dead = conn.execute(
        text(
            """
            UPDATE whatsapp_outbound_jobs
            SET status = 'dead',
                locked_at = NULL,
                locked_by = NULL,
                error = COALESCE(error, '') || ' [dead: stuck after post_attempt]',
                updated_at = now()
            WHERE status = 'running'
              AND post_attempted_at IS NOT NULL
              AND COALESCE(locked_at, updated_at) < :cutoff
            """
        ),
        {"cutoff": cutoff},
    )
    requeued = conn.execute(
        text(
            """
            UPDATE whatsapp_outbound_jobs
            SET status = 'queued',
                locked_at = NULL,
                locked_by = NULL,
                error = COALESCE(error, '') || ' [requeued: stuck running]',
                updated_at = now()
            WHERE status = 'running'
              AND post_attempted_at IS NULL
              AND COALESCE(locked_at, updated_at) < :cutoff
            """
        ),
        {"cutoff": cutoff},
    )
    return (dead.rowcount or 0) + (requeued.rowcount or 0)


def claim_next_job(conn: Connection) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT id, message_id, conversation_id, customer_id,
                   to_phone, body, attempt, post_attempted_at,
                   preview_url, template_name, template_lang, template_params,
                   purpose, source,
                   -- `created_at` bounds how long a deferral is worth holding.
                   created_at,
                   -- `decision_id` was never selected, so `job.get("decision_id")`
                   -- was always None: the treatment session key fell through to
                   -- the conversation id, and `_finalize_treatment_send` — which
                   -- reads it to attribute a send back to the decision that
                   -- asked for it — has silently no-opped on every message since
                   -- the column was added.
                   decision_id
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


def _finalize_treatment_send(
    conn: Connection, job: dict[str, Any], *, provider_ref: str | None
) -> None:
    decision_id = (job.get("decision_id") or "").strip()
    if not decision_id:
        return
    try:
        from agent_core.treatment import attempts, decisions, reservations

        decisions.mark_enacted(
            decision_id, ref=f"whatsapp:{provider_ref or job.get('id')}", conn=conn
        )
        row = attempts.for_decision(conn, decision_id)
        if row:
            attempts.set_state(
                conn, row["id"], attempts.STATE_SENT, provider_ref=provider_ref
            )
        reservations.commit(conn, None)
        conn.execute(
            text(
                """
                UPDATE contact_reservations
                SET state = 'committed',
                    provider_ref = COALESCE(:ref, provider_ref),
                    updated_at = now()
                WHERE decision_id = :id AND state = 'held'
                """
            ),
            {"id": decision_id, "ref": provider_ref},
        )
    except Exception:
        logger.exception("treatment finalize failed for decision=%s", decision_id)


def _persistable_error(exc: BaseException) -> str:
    """Error text safe to store on the job row and emit to logs.

    ``wa.send_text_message`` already raises ``ValueError`` carrying a code from
    :func:`whatsapp._classify_send_error`, which strips the Graph body (recipient
    number, message text, token fragments). Anything else reaching the catch-all
    is a driver or runtime error whose ``str()`` can echo SQL parameters — i.e.
    customer data — into ``whatsapp_outbound_jobs.error``, which the Inbox reads.
    Keep the classifier's message; reduce the rest to its type.
    """
    if isinstance(exc, ValueError):
        return str(exc)
    return f"whatsapp_send_failed:internal:{type(exc).__name__}"


#: How long past its moment a queued message is still worth delivering.
#:
#: A promise-to-pay confirmation two hours late is still the confirmation the
#: borrower is waiting for. A nudge whose window has closed is a message about
#: something that already happened, and sending it late is worse than not
#: sending it: it is what "why is this bank messaging me about last Tuesday"
#: looks like from the other side.
_PURPOSE_TTL = {
    "statutory": timedelta(days=2),
    "in_session": timedelta(hours=4),
    "outreach": timedelta(days=1),
}
_DEFAULT_TTL = timedelta(days=1)


def _defer(conn: Connection, job: dict[str, Any], decision: Any) -> str:
    """Reschedule to the instant the policy next allows, or cancel if too late.

    Rides `status='queued'` with a far-future `run_after` — the column exists,
    is indexed (ix_whatsapp_outbound_jobs_status_run_after) and is already
    honoured by `claim_next_job`, so a deferral needs no new status and no
    migration.

    `attempt` is deliberately left alone. A policy deferral is not an attempt at
    anything; counting it would walk the job toward the dead-letter cap for
    waiting, which is the whole bug in miniature.
    """
    when = decision.next_allowed_at
    created = job.get("created_at")
    ttl = _PURPOSE_TTL.get((job.get("purpose") or "").strip(), _DEFAULT_TTL)
    if created is not None:
        if getattr(created, "tzinfo", None) is None:
            created = created.replace(tzinfo=timezone.utc)
        if when > created + ttl:
            logger.info(
                "whatsapp_outbound job=%s cancelled — %s until %s, past its %s TTL",
                job["id"],
                decision.reason,
                when.isoformat(),
                ttl,
            )
            return cancel(conn, job, f"{decision.reason}:expired_before_window")
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
        {
            "id": job["id"],
            "error": f"deferred: {decision.reason}",
            "run_after": when,
        },
    )
    logger.info(
        "whatsapp_outbound job=%s deferred to %s (%s)",
        job["id"],
        when.isoformat(),
        decision.reason,
    )
    return "queued"


def cancel(conn: Connection, job: dict[str, Any], reason: str) -> str:
    """Stop trying. The refusal will not expire, so retrying is noise.

    Dead-lettered rather than given a status of its own: `dead` already means
    "a human decides what happens next", which is exactly right for a message we
    are declining to send on consent grounds, and the check constraint has never
    carried a `cancelled`.
    """
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
        {"id": job["id"], "error": reason[:2000]},
    )
    return "dead"


def mark_failed_or_retry(conn: Connection, job: dict[str, Any], error: str) -> str:
    """Decide retry vs dead-letter for a failed send.

    WhatsApp Cloud API has no client-supplied idempotency key, so any error
    where Meta *may* already have accepted the message (read timeout, 429, 5xx)
    must not be retried — a retry double-sends to the customer. Those are
    dead-lettered for reconciliation. Only errors that provably happened before
    the request reached Meta (connection refused, DNS failure) and deterministic
    configuration errors are retried.
    """
    import whatsapp as wa

    attempt = int(job.get("attempt") or 1)
    cap = max_attempts()
    # Read from the row, not the claim-time copy: `post_attempted_at` is
    # stamped after the claim, and it is the one fact that decides whether a
    # retry is safe. Once a request has gone out, any send-phase failure that
    # is not a provable pre-send rejection may have reached Meta — a driver
    # error while recording the result, a JSON body we could not parse — and
    # a retry is a second message to the borrower.
    attempted = conn.execute(
        text("SELECT post_attempted_at FROM whatsapp_outbound_jobs WHERE id = :id"),
        {"id": job["id"]},
    ).scalar()
    sent_phase = str(error or "").startswith("whatsapp_send_failed:")
    ambiguous = wa.is_ambiguous_transport_error(error) or (
        attempted is not None and sent_phase and not wa.is_definite_client_error(error)
    )
    if ambiguous:
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
            {"id": job["id"], "error": f"ambiguous_transport: {error}"[:2000]},
        )
        logger.warning(
            "whatsapp_outbound job=%s parked for reconciliation (send may have "
            "reached Meta) err=%s",
            job["id"],
            error[:200],
        )
        return "dead"
    if wa.is_definite_client_error(error):
        # Config/token/4xx: the request never left as a valid send, and no
        # amount of backoff changes the outcome. Burning `cap` attempts here
        # only delays the operator noticing.
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
        logger.warning(
            "whatsapp_outbound job=%s dead-lettered (non-retryable) err=%s",
            job["id"],
            error[:200],
        )
        return "dead"
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

    # Cap the delay, not the exponent. Bounding the exponent at 5 capped the
    # backoff at 32s, so the 120s ceiling was never reached and a hard upstream
    # outage was retried nearly four times more often than intended. The
    # exponent is still bounded (at a value well past the cap) so a runaway
    # attempt counter cannot compute an enormous power.
    delay_sec = min(120, 2 ** min(attempt, 12))
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
        # Permanent: the message row will not reappear, so this must not go
        # through the retry ladder and burn `cap` attempts (and `cap` backoff
        # windows) before an operator sees it.
        with engine.begin() as conn:
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
                {"id": job["id"], "error": "message_not_found"[:2000]},
            )
        logger.error(
            "whatsapp_outbound job=%s dead: message %s no longer exists",
            job["id"],
            message_id,
        )
        return
    delivery = (row._mapping.get("delivery_status") or "").strip().lower()
    if delivery in {"sent", "delivered", "read"}:
        with engine.begin() as conn:
            mark_succeeded(conn, job["id"], provider_ref=row._mapping.get("provider_ref"))
        return

    import contact_policy

    purpose = (job.get("purpose") or "").strip()
    if purpose not in {"outreach", "statutory", "in_session"}:
        purpose = "statutory" if (job.get("template_name") or job.get("preview_url")) else "in_session"
    source = (job.get("source") or "").strip() or (
        "ptp_confirm" if purpose == "statutory" else "inbox_reply"
    )
    with engine.begin() as conn:
        decision = contact_policy.admit(
            conn,
            customer_id=job.get("customer_id"),
            channel="whatsapp",
            purpose=purpose,
            session_key=job.get("decision_id") or job.get("conversation_id"),
            source=source,
            related_id=job.get("message_id") or job.get("id"),
            actor_kind="system",
            endpoint=to_phone,
        )
        if not decision.allowed:
            # A policy verdict is not a transport error, and this is the line
            # that treated it as one. `mark_failed_or_retry` classifies against
            # the `whatsapp_send_failed:*` vocabulary Meta produces; a reason
            # like `cooling_off` matches nothing there, falls through to
            # "attempt >= cap", and dead-letters. Cooling-off is 120 minutes and
            # the ladder tops out at 120 seconds, so the job could never survive
            # to the retry that would have worked. 18 of 29 outbound messages
            # died this way, none of them for a reason the borrower would
            # recognise as a failure.
            #
            # Every sibling caller of `admit` already routes refusals away from
            # its retry ladder (written_followup, outbound.gate, treatment.enact,
            # promise_fulfillment). This was the one that did not.
            if decision.deferrable and _defer(conn, job, decision) == "queued":
                logger.info(
                    "whatsapp_outbound deferred job=%s reason=%s",
                    job["id"],
                    decision.reason,
                )
                return
            # Either the refusal is a property of the customer — DND, a
            # withdrawn consent, a settled account, an unverified endpoint, none
            # of which expire — or it was deferrable and outlived its purpose's
            # TTL. Both stop here, and both leave the message row sitting in
            # `sending` unless it is closed out.
            if not decision.deferrable:
                cancel(conn, job, decision.reason or "contact_policy")
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
            conn.execute(
                text("UPDATE conversations SET updated_at = now() WHERE id = :id"),
                {"id": job["conversation_id"]},
            )
            logger.info(
                "whatsapp_outbound blocked job=%s reason=%s",
                job["id"],
                decision.reason,
            )
            return

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE whatsapp_outbound_jobs
                SET post_attempted_at = COALESCE(post_attempted_at, now()),
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job["id"]},
        )

    try:
        template_name = (job.get("template_name") or "").strip()
        if template_name:
            params = job.get("template_params") or []
            if isinstance(params, str):
                try:
                    params = json.loads(params)
                except json.JSONDecodeError:
                    params = []
            send_resp = wa.send_template_message(
                to_phone=to_phone,
                template_name=template_name,
                template_lang=(job.get("template_lang") or "en_US"),
                body_params=list(params) if params else None,
            )
        else:
            send_resp = wa.send_text_message(
                to_phone=to_phone,
                body=body,
                preview_url=bool(job.get("preview_url")),
            )
        provider_ref = wa.extract_wamid(send_resp)
    except Exception as exc:
        err = _persistable_error(exc)
        logger.warning(
            "whatsapp_outbound send failed job=%s err=%s", job["id"], err, exc_info=True
        )
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
        _finalize_treatment_send(conn, job, provider_ref=provider_ref)
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
            status = mark_failed_or_retry(conn, job, _persistable_error(exc))
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
