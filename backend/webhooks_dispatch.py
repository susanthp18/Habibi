"""Outbound webhook delivery — the part that was never built.

``webhook_endpoints``, ``webhook_subscriptions``, ``webhook_retry_policies`` and
``webhook_deliveries`` all shipped, the Integrations screen manages them, and the
delivery log filled up with ``200 OK``. None of it left the process.
``ops_screens.test_fire_webhook`` derived the latency from a SHA-256 digest of
the endpoint id and wrote the literal body ``{"ok":true,"mode":"simulated"}``;
there was no HTTP client anywhere in the outbound webhook path, and no business
event ever produced a delivery row at all. A tenant who subscribed an endpoint to
``promise.kept`` got a healthy-looking log and not one event.

The design here is deliberately small:

* **A delivery is the unit of work.** There is no side jobs table. A row in
  ``webhook_deliveries`` starts ``pending``, gets claimed, gets POSTed, and
  settles — with ``attempt_number`` climbing across retries of the *same* row.
  The log the operator reads and the queue the worker drains are the same rows,
  so they cannot disagree about what happened.
* **dispatch() only enqueues**, inside the caller's transaction. A webhook must
  not be able to roll back a payment, and must not fire for a payment that
  rolled back.
* **The POST happens outside any transaction.** Holding a database transaction
  open across a call to someone else's server is how a slow endpoint becomes a
  database incident.

Signing
-------
The plaintext endpoint secret is deliberately never persisted: rotation returns
it once as ``secretOnce`` and stores only ``secret_hash`` =
``sha256(secret).hexdigest()``. So the HMAC key is that hash, not the secret
itself — a standard key derivation, and one the receiver can reproduce exactly,
because the receiver is the party that *has* the plaintext.

Receivers verify like this::

    key    = sha256(shared_secret.encode()).hexdigest()
    signed = f"{X-BigBound-Timestamp}.{raw_request_body}"
    expect = hmac.new(key.encode(), signed.encode(), sha256).hexdigest()
    hmac.compare_digest(expect, X-BigBound-Signature)

The timestamp is inside the signed string so a captured body cannot be replayed
under a fresh timestamp. An endpoint with no ``secret_hash`` at all is **not**
sent unsigned — it settles as a failure naming ``secret_unavailable``, and the
operator fixes it by rotating the secret.

SSRF
----
``ops_screens._validate_webhook_url`` checks the URL at registration time and
says in as many words that it cannot resolve DNS there — the name can resolve
differently by the time anything connects. This is the "anything connects", so
every host is resolved and re-checked immediately before the POST.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

#: Response bodies are evidence, not storage. Enough to read the upstream's
#: complaint, not enough for a chatty 500 page to bloat the delivery log.
MAX_RESPONSE_BODY = 2000

SIGNATURE_HEADER = "X-BigBound-Signature"
TIMESTAMP_HEADER = "X-BigBound-Timestamp"
EVENT_HEADER = "X-BigBound-Event"
DELIVERY_HEADER = "X-BigBound-Delivery"

#: A claim older than this belonged to a worker that is not coming back.
STALE_CLAIM_SECONDS = 300


def timeout_seconds() -> float:
    try:
        return max(1.0, float((os.getenv("WEBHOOK_DELIVERY_TIMEOUT_SEC") or "10").strip()))
    except ValueError:
        return 10.0


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _sid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


# --- signing ---------------------------------------------------------------


def sign(secret_hash: str, timestamp: str, body: str) -> str:
    """HMAC-SHA256 over ``{timestamp}.{body}``, keyed by the stored secret hash.

    See the module docstring for why the key is the hash and not the secret.
    """
    signed = f"{timestamp}.{body}"
    return hmac.new(secret_hash.encode(), signed.encode("utf-8"), hashlib.sha256).hexdigest()


# --- SSRF ------------------------------------------------------------------


def _is_private_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return True  # Unparseable is not a public address we are willing to POST to.
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_public_host(url: str) -> str:
    """Resolve the URL's host and reject anything not publicly routable.

    Registration-time validation cannot cover this: the name is allowed to
    resolve somewhere else by the time we connect, which is the whole rebinding
    attack. ``_validate_webhook_url`` says so where it declines to resolve.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("webhook_url_https_required")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("webhook_url_host_required")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"webhook_url_dns_failed: {exc}") from exc
    addrs = {str(info[4][0]) for info in infos}
    if not addrs:
        raise ValueError("webhook_url_dns_empty")
    # Every answer must be public. One private address in an otherwise public
    # answer set is enough for the connect to land on it.
    private = sorted(a for a in addrs if _is_private_ip(a))
    if private:
        raise ValueError(f"webhook_url_private_forbidden: {private[0]}")
    return sorted(addrs)[0]


# --- transport -------------------------------------------------------------


def _post(url: str, *, headers: dict[str, str], body: str, timeout: float) -> tuple[int, str]:
    """POST and return (http_status, response_text). The seam tests replace.

    httpx is imported lazily so that importing this module — which the worker
    and three business modules all do — does not pull in an HTTP client.
    """
    import httpx

    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.post(url, headers=headers, content=body.encode("utf-8"))
        return response.status_code, response.text


# --- enqueue ---------------------------------------------------------------


def _endpoints_for(conn: Connection, event_key: str, tenant_id: str) -> list[dict[str, Any]]:
    """Active endpoints of this tenant subscribed to the event.

    Paused and broken endpoints are skipped rather than queued-and-failed: a
    paused endpoint is an operator decision, and burning its retry budget while
    it is off would leave a wall of failures to read when it comes back.
    """
    rows = (
        conn.execute(
            text(
                """
                SELECT e.id, e.url, e.secret_hash, et.id AS event_type_id
                FROM webhook_endpoints e
                JOIN webhook_subscriptions ws ON ws.endpoint_id = e.id
                JOIN event_types et ON et.id = ws.event_type_id
                WHERE e.tenant_id = :tenant
                  AND e.status = 'active'
                  AND et.name = :event
                ORDER BY e.id
                """
            ),
            {"tenant": tenant_id, "event": event_key},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def dispatch(
    conn: Connection,
    event_key: str,
    payload: dict[str, Any],
    *,
    tenant_id: str | None = None,
) -> list[str]:
    """Queue one delivery per subscribed active endpoint. Returns delivery ids.

    Enqueue-only, and inside the caller's transaction on purpose: the event and
    its notification commit together or not at all.

    Never raises into the business path. An outbound integration problem is not
    a reason to fail a payment that already happened, so a failure here is
    logged and the caller carries on.
    """
    try:
        import db

        tenant = tenant_id or db.current_tenant()
        endpoints = _endpoints_for(conn, event_key, tenant)
        if not endpoints:
            return []
        body = {
            "event": event_key,
            "tenant": tenant,
            "at": datetime.now(timezone.utc).isoformat(),
            "data": payload,
        }
        ids: list[str] = []
        for ep in endpoints:
            did = _sid("dlv")
            conn.execute(
                text(
                    """
                    INSERT INTO webhook_deliveries (
                      id, endpoint_id, event_type_id, payload, attempt_number,
                      status, delivery_mode, created_at, updated_at
                    ) VALUES (
                      :id, :eid, :et, CAST(:payload AS jsonb), 0,
                      'pending', 'live', now(), now()
                    )
                    """
                ),
                {
                    "id": did,
                    "eid": ep["id"],
                    "et": ep["event_type_id"],
                    "payload": json.dumps(body),
                },
            )
            ids.append(did)
        logger.info("webhook dispatch event=%s queued=%d", event_key, len(ids))
        return ids
    except Exception:
        logger.exception("webhook dispatch failed event=%s", event_key)
        return []


# --- claim -----------------------------------------------------------------


def reclaim_stuck(conn: Connection) -> int:
    """Free rows whose claimer died mid-flight.

    Safe to requeue unconditionally: unlike a WhatsApp send there is no
    ambiguity worth preserving. A webhook receiver is expected to deduplicate on
    the delivery id, which is why it travels in a header.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STALE_CLAIM_SECONDS)
    result = conn.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET locked_at = NULL, locked_by = NULL, updated_at = now()
            WHERE status = 'pending' AND locked_at IS NOT NULL AND locked_at < :cutoff
            """
        ),
        {"cutoff": cutoff},
    )
    return result.rowcount or 0


def claim_next(conn: Connection) -> dict[str, Any] | None:
    """Take one due delivery, oldest first, with everything the POST needs."""
    row = (
        conn.execute(
            text(
                """
                SELECT d.id, d.endpoint_id, d.payload, d.attempt_number,
                       e.url, e.secret_hash, e.status AS endpoint_status,
                       et.name AS event_name,
                       COALESCE(rp.max_attempts, 3) AS max_attempts
                FROM webhook_deliveries d
                JOIN webhook_endpoints e ON e.id = d.endpoint_id
                LEFT JOIN event_types et ON et.id = d.event_type_id
                LEFT JOIN webhook_retry_policies rp ON rp.endpoint_id = d.endpoint_id
                WHERE d.status = 'pending'
                  AND d.locked_at IS NULL
                  AND (d.next_retry_at IS NULL OR d.next_retry_at <= now())
                ORDER BY d.created_at ASC
                FOR UPDATE OF d SKIP LOCKED
                LIMIT 1
                """
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    job = dict(row)
    worker = _worker_id()
    conn.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET attempt_number = attempt_number + 1,
                locked_at = now(),
                locked_by = :worker,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": job["id"], "worker": worker},
    )
    job["attempt_number"] = int(job.get("attempt_number") or 0) + 1
    job["locked_by"] = worker
    payload = job.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    job["payload"] = payload or {}
    return job


# --- settle ----------------------------------------------------------------


def _classify(http_status: int) -> str:
    if 200 <= http_status < 300:
        return "success"
    if 400 <= http_status < 500:
        return "client_err"
    return "server_err"


def settle(
    conn: Connection,
    job: dict[str, Any],
    *,
    http_status: int,
    latency_ms: int,
    body: str,
) -> str:
    """Record the outcome, and schedule a retry only when one can help.

    A 4xx is the receiver saying the request itself is wrong. Re-sending the
    identical bytes cannot change that answer, so it is terminal — burning the
    retry budget on it only delays the operator seeing a red row.
    """
    status = _classify(http_status)
    attempt = int(job.get("attempt_number") or 1)
    cap = max(1, int(job.get("max_attempts") or 3))
    retryable = status == "server_err" and attempt < cap
    next_retry = None
    if retryable:
        # Same ladder as whatsapp_outbound: cap the delay, not the exponent.
        delay = min(120, 2 ** min(attempt, 12))
        next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)
    conn.execute(
        text(
            """
            UPDATE webhook_deliveries
            SET status = :status,
                http_status = :http,
                latency_ms = :lat,
                response_body = :body,
                next_retry_at = :next_retry,
                locked_at = NULL,
                locked_by = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": job["id"],
            # A row waiting for its retry is still queue work, so it stays
            # 'pending'. Only a terminal outcome takes an error status.
            "status": "pending" if retryable else status,
            "http": http_status,
            "lat": latency_ms,
            "body": (body or "")[:MAX_RESPONSE_BODY],
            "next_retry": next_retry,
        },
    )
    return "pending" if retryable else status


# --- worker ----------------------------------------------------------------


def process_one(engine: Engine) -> bool:
    """Claim and deliver one webhook. Returns True if a delivery was claimed.

    The POST sits between two short transactions rather than inside one: a
    receiver that takes ten seconds to answer must not hold a row lock — or a
    connection — for ten seconds.
    """
    try:
        with engine.begin() as conn:
            reclaim_stuck(conn)
            job = claim_next(conn)
    except Exception:
        logger.exception("webhook claim failed")
        return False
    if not job:
        return False

    started = time.monotonic()
    http_status = 0
    body = ""
    try:
        secret_hash = (job.get("secret_hash") or "").strip()
        if not secret_hash:
            # Unsigned delivery is not a degraded mode, it is a different
            # security posture. Fail loudly; rotating the secret fixes it.
            raise ValueError("secret_unavailable: rotate the endpoint secret to enable signing")
        resolve_public_host(job["url"])
        raw = json.dumps(job["payload"], separators=(",", ":"), sort_keys=True)
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            EVENT_HEADER: str(job.get("event_name") or ""),
            DELIVERY_HEADER: str(job["id"]),
            TIMESTAMP_HEADER: timestamp,
            SIGNATURE_HEADER: sign(secret_hash, timestamp, raw),
        }
        http_status, body = _post(job["url"], headers=headers, body=raw, timeout=timeout_seconds())
    except Exception as exc:
        # No response means no HTTP status. 0 classifies as server_err, which is
        # right: a connection that never completed is worth another attempt, and
        # the reason lands in the body column where an operator reads it.
        http_status = 0
        body = f"{type(exc).__name__}: {exc}"
        logger.warning("webhook delivery %s failed: %s", job["id"], body[:200])

    latency_ms = int((time.monotonic() - started) * 1000)
    try:
        with engine.begin() as conn:
            settle(conn, job, http_status=http_status, latency_ms=latency_ms, body=body)
    except Exception:
        logger.exception("webhook settle failed delivery=%s", job["id"])
    return True
