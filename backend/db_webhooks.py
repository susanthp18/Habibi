"""Tenant webhooks: the event catalogue, endpoints, secrets, deliveries, test-fire and retry.

Carved from ops_screens.py. Dispatch itself is webhooks_dispatch.py.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse
from sqlalchemy import text
import db
import request_context
from agent_core.clock import utc_now
from db_core import _id

logger = logging.getLogger(__name__)


def _validate_webhook_url(url: str) -> str:
    """HTTPS-only public webhook targets — reject loopback / RFC1918 / link-local."""
    raw = (url or "").strip()
    if not raw:
        raise ValueError("webhook_url_required")
    parsed = urlparse(raw)
    if parsed.scheme != "https":
        raise ValueError("webhook_url_https_required")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("webhook_url_host_required")
    blocked = {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "metadata.google.internal",
    }
    if host in blocked or host.endswith(".local"):
        raise ValueError("webhook_url_private_forbidden")
    # Literal private / loopback / link-local addresses.
    #
    # NOTE: hostnames are deliberately *not* resolved here — DNS at validation
    # time is both a rebinding hazard (the name can resolve differently at send
    # time) and a blocking network call inside a request handler. Before real
    # webhook egress ships, the delivery worker must re-check the resolved
    # address immediately before connecting and pin it for the request.
    if _is_private_host_ip(host):
        raise ValueError("webhook_url_private_forbidden")
    return raw


def _is_private_host_ip(host: str) -> bool:
    """True when `host` is a literal address in a non-public range."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
    )


# UI event catalog → persisted event_types.name (same strings; seed may differ).
EVENT_CATALOG: list[dict[str, str]] = [
    {"key": "call.started", "category": "Calls", "description": "Caller connected to the voice bot."},
    {"key": "call.completed", "category": "Calls", "description": "Hangup with duration and disposition."},
    {"key": "call.summary.ready", "category": "Calls", "description": "Structured summary ready for CRM writeback."},
    {"key": "call.escalated", "category": "Calls", "description": "Bot triggered a human handoff."},
    {"key": "promise.created", "category": "Promises", "description": "Promise-to-pay captured."},
    {"key": "promise.kept", "category": "Promises", "description": "Promise marked kept."},
    {"key": "promise.broken", "category": "Promises", "description": "Promise marked broken."},
    {"key": "dispute.raised", "category": "Disputes", "description": "Dispute opened."},
    {"key": "dispute.resolved", "category": "Disputes", "description": "Dispute resolved or rejected."},
    {"key": "payment.updated", "category": "Payments", "description": "Payment status changed."},
    {"key": "payment.reversed", "category": "Payments", "description": "Payment reversed."},
    {"key": "consent.dnd.updated", "category": "Consent", "description": "DND / contact window changed."},
    {"key": "consent.opted_out", "category": "Consent", "description": "Customer opted out of a channel."},
    {"key": "bot.handoff", "category": "Bot", "description": "Bot→human handoff event."},
    {"key": "bot.compliance.flag", "category": "Bot", "description": "Compliance flag raised on a turn."},
]


def _mask_secret(present: bool) -> str:
    return "••••••••••••" if present else ""


def _ensure_event_type(conn: Any, key: str) -> str:
    """The `event_types` row for a catalogue event, created on first use.

    Only the catalogue: a subscription used to mint a row for any string the
    client sent, and that string then travelled verbatim into the delivery's
    `X-BigBound-Event` header.
    """
    if not any(e["key"] == key for e in EVENT_CATALOG):
        raise ValueError(f"unknown_event_type:{key}")
    eid = f"evt-{key.replace('.', '-')}"
    conn.execute(
        text(
            """
            INSERT INTO event_types (id, name, description, created_at, updated_at)
            VALUES (:id, :name, :desc, now(), now())
            ON CONFLICT (name) DO NOTHING
            """
        ),
        {"id": eid, "name": key, "desc": next((e["description"] for e in EVENT_CATALOG if e["key"] == key), key)},
    )
    row = conn.execute(text("SELECT id FROM event_types WHERE name = :n"), {"n": key}).fetchone()
    if row is None:
        raise RuntimeError(f"event_type_missing:{key}")
    return row[0]


def list_event_types() -> list[dict[str, Any]]:
    return [
        {
            "key": e["key"],
            "category": e["category"],
            "description": e["description"],
            "sample": {"event": e["key"], "tenant": db.current_tenant(), "at": utc_now().isoformat()},
        }
        for e in EVENT_CATALOG
    ]


def _endpoint_contract(conn: Any, endpoint_id: str) -> dict[str, Any] | None:
    row = db._one(
        conn.execute(
            text(
                """
                SELECT id, target_system, url, status, signing_algorithm, secret_ref,
                       secret_hash, created_at, name
                FROM webhook_endpoints
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {"id": endpoint_id, "tenant": db.current_tenant()},
        )
    )
    if row is None:
        return None

    headers = db._rows(
        conn.execute(
            text(
                """
                SELECT header_key AS key, header_value AS value
                FROM webhook_endpoint_headers
                WHERE endpoint_id = :id
                  -- Case-insensitive and including Authorization, matching the
                  -- write-side exclusion in _upsert_endpoint_children. The
                  -- exact-case list let a legacy row stored as
                  -- 'x-webhook-secret' (or any bearer token) be read back.
                  AND lower(header_key) NOT IN (
                        'x-webhook-secret-sha256', 'x-webhook-secret', 'authorization'
                      )
                ORDER BY header_key
                """
            ),
            {"id": endpoint_id},
        )
    )
    retry = db._one(
        conn.execute(
            text(
                """
                SELECT max_attempts, backoff_strategy, max_event_age_sec
                FROM webhook_retry_policies WHERE endpoint_id = :id
                """
            ),
            {"id": endpoint_id},
        )
    )
    events = [
        r["name"]
        for r in db._rows(
            conn.execute(
                text(
                    """
                    SELECT et.name
                    FROM webhook_subscriptions ws
                    JOIN event_types et ON et.id = ws.event_type_id
                    WHERE ws.endpoint_id = :id
                    ORDER BY et.name
                    """
                ),
                {"id": endpoint_id},
            )
        )
    ]
    created = row.get("created_at")
    created_ms = int(created.timestamp() * 1000) if isinstance(created, datetime) else int(time.time() * 1000)
    name = row.get("name") or row["target_system"] or endpoint_id
    secret_ref = row.get("secret_ref") or ""
    has_secret = bool(secret_ref or row.get("secret_hash"))
    return {
        "id": row["id"],
        "name": name,
        "url": row["url"],
        "target": row["target_system"],
        "status": row["status"],
        "events": events,
        "algo": row.get("signing_algorithm") or "HMAC-SHA256",
        "secret": _mask_secret(has_secret),
        "secretRef": secret_ref,
        "retry": {
            "attempts": int((retry or {}).get("max_attempts") or 3),
            "backoff": (retry or {}).get("backoff_strategy") or "exponential",
            "maxAgeHours": int(((retry or {}).get("max_event_age_sec") or 86400) // 3600),
        },
        "headers": headers,
        "createdAt": created_ms,
    }


def list_webhook_endpoints() -> list[dict[str, Any]]:
    # No blanket try/except: swallowing a database error here rendered the
    # Webhooks screen as "no endpoints configured", which reads as a
    # deliberate empty state. Let it surface as a 5xx instead.
    with db.engine.connect() as conn:
        ids = [
            r["id"]
            for r in db._rows(
                conn.execute(
                    text(
                        """
                        SELECT id FROM webhook_endpoints
                        WHERE tenant_id = :tenant
                        ORDER BY created_at DESC
                        """
                    ),
                    {"tenant": db.current_tenant()},
                )
            )
        ]
        return [ep for eid in ids if (ep := _endpoint_contract(conn, eid))]


def _upsert_endpoint_children(
    conn: Any,
    endpoint_id: str,
    *,
    events: list[str],
    headers: list[dict[str, str]],
    retry: dict[str, Any],
) -> None:
    conn.execute(text("DELETE FROM webhook_subscriptions WHERE endpoint_id = :id"), {"id": endpoint_id})
    for key in events:
        et_id = _ensure_event_type(conn, key)
        conn.execute(
            text(
                """
                INSERT INTO webhook_subscriptions (endpoint_id, event_type_id, created_at)
                VALUES (:eid, :et, now())
                ON CONFLICT DO NOTHING
                """
            ),
            {"eid": endpoint_id, "et": et_id},
        )
    conn.execute(text("DELETE FROM webhook_endpoint_headers WHERE endpoint_id = :id"), {"id": endpoint_id})
    for h in headers:
        key = (h.get("key") or "").strip()
        val = (h.get("value") or "").strip()
        if not key:
            continue
        # Never persist signing secrets as outbound headers.
        if key.lower() in {"x-webhook-secret-sha256", "x-webhook-secret", "authorization"}:
            continue
        conn.execute(
            text(
                """
                INSERT INTO webhook_endpoint_headers (id, endpoint_id, header_key, header_value, created_at)
                VALUES (:id, :eid, :k, :v, now())
                """
            ),
            {"id": _id("whh"), "eid": endpoint_id, "k": key, "v": val},
        )
    attempts = int(retry.get("attempts") or 3)
    backoff = retry.get("backoff") or "exponential"
    max_age = int(retry.get("maxAgeHours") or 24) * 3600
    conn.execute(text("DELETE FROM webhook_retry_policies WHERE endpoint_id = :id"), {"id": endpoint_id})
    conn.execute(
        text(
            """
            INSERT INTO webhook_retry_policies (
              id, endpoint_id, max_attempts, backoff_strategy, max_event_age_sec, created_at, updated_at
            ) VALUES (:id, :eid, :a, :b, :age, now(), now())
            """
        ),
        {"id": _id("whr"), "eid": endpoint_id, "a": attempts, "b": backoff, "age": max_age},
    )


def create_webhook_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    eid = payload.get("id") or f"wh_{uuid.uuid4().hex[:8]}"
    secret_plain = secrets.token_urlsafe(24)
    secret_ref = f"vault://local/{eid}"
    secret_hash = hashlib.sha256(secret_plain.encode()).hexdigest()
    url = _validate_webhook_url(str(payload.get("url") or ""))
    tenant = db.current_tenant()
    with db.engine.begin() as conn:
        # Ensure tenant exists for FK
        conn.execute(
            text(
                """
                INSERT INTO tenants (id, name, created_at, updated_at)
                VALUES (:id, :name, now(), now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": tenant, "name": tenant},
        )
        conn.execute(
            text(
                """
                INSERT INTO webhook_endpoints (
                  id, tenant_id, target_system, url, status, signing_algorithm,
                  secret_ref, secret_hash, name, created_at, updated_at
                ) VALUES (
                  :id, :tenant, :target, :url, 'active', :algo,
                  :secret_ref, :secret_hash, :name, now(), now()
                )
                """
            ),
            {
                "id": eid,
                "tenant": tenant,
                "target": payload.get("target") or "Custom",
                "url": url,
                "algo": payload.get("algo") or "HMAC-SHA256",
                "secret_ref": secret_ref,
                "secret_hash": secret_hash,
                "name": payload.get("name") or payload.get("target") or eid,
            },
        )
        _upsert_endpoint_children(
            conn,
            eid,
            events=list(payload.get("events") or []),
            headers=list(payload.get("headers") or []),
            retry=dict(payload.get("retry") or {}),
        )
        ep = _endpoint_contract(conn, eid)
    assert ep is not None
    ep["secretOnce"] = secret_plain
    ep["secret"] = _mask_secret(True)
    return ep


def patch_webhook_endpoint(endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    with db.engine.begin() as conn:
        sets: list[str] = []
        params: dict[str, Any] = {"id": endpoint_id, "tenant": db.current_tenant()}
        for col, key in [
            ("url", "url"),
            ("target_system", "target"),
            ("status", "status"),
            ("signing_algorithm", "algo"),
            ("name", "name"),
        ]:
            if key in payload and payload[key] is not None:
                sets.append(f"{col} = :{key}")
                val = payload[key]
                if key == "url":
                    val = _validate_webhook_url(str(val))
                params[key] = val
        if sets:
            sets.append("updated_at = now()")
            conn.execute(
                text(
                    f"UPDATE webhook_endpoints SET {', '.join(sets)} "
                    "WHERE id = :id AND tenant_id = :tenant"
                ),
                params,
            )
        cur = _endpoint_contract(conn, endpoint_id)
        if cur is None:
            raise KeyError("endpoint_not_found")
        if any(k in payload for k in ("events", "headers", "retry")):
            _upsert_endpoint_children(
                conn,
                endpoint_id,
                events=list(payload["events"]) if "events" in payload else list(cur.get("events") or []),
                headers=list(payload["headers"]) if "headers" in payload else list(cur.get("headers") or []),
                retry=dict(payload["retry"]) if "retry" in payload else dict(cur.get("retry") or {}),
            )
        ep = _endpoint_contract(conn, endpoint_id)
    if ep is None:
        raise KeyError("endpoint_not_found")
    return ep


def delete_webhook_endpoint(endpoint_id: str) -> None:
    with db.engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM webhook_endpoints WHERE id = :id AND tenant_id = :tenant"),
            {"id": endpoint_id, "tenant": db.current_tenant()},
        )
        if not result.rowcount:
            raise KeyError("endpoint_not_found")


def rotate_webhook_secret(endpoint_id: str) -> dict[str, Any]:
    secret_plain = secrets.token_urlsafe(24)
    secret_ref = f"vault://local/{endpoint_id}"
    secret_hash = hashlib.sha256(secret_plain.encode()).hexdigest()
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE webhook_endpoints
                SET secret_ref = :ref, secret_hash = :hash, updated_at = now()
                WHERE id = :id AND tenant_id = :tenant
                """
            ),
            {
                "id": endpoint_id,
                "tenant": db.current_tenant(),
                "ref": secret_ref,
                "hash": secret_hash,
            },
        )
        if not result.rowcount:
            raise KeyError("endpoint_not_found")
        conn.execute(
            text(
                """
                DELETE FROM webhook_endpoint_headers
                WHERE endpoint_id = :id
                  -- Case-insensitive and including Authorization, matching the
                  -- read-side filter in _endpoint_contract. Exact-case matching
                  -- let a legacy row stored as 'x-webhook-secret' survive a
                  -- rotation that is supposed to invalidate the old secret.
                  AND lower(header_key) IN (
                        'x-webhook-secret-sha256', 'x-webhook-secret', 'authorization'
                      )
                """
            ),
            {"id": endpoint_id},
        )
        ep = _endpoint_contract(conn, endpoint_id)
    assert ep is not None
    ep["secretOnce"] = secret_plain
    ep["secret"] = _mask_secret(True)
    return ep


def _delivery_contract(row: dict[str, Any], max_attempts: int = 3) -> dict[str, Any]:
    created = row.get("created_at")
    at_ms = int(created.timestamp() * 1000) if isinstance(created, datetime) else int(time.time() * 1000)
    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    return {
        "id": row["id"],
        "endpointId": row["endpoint_id"],
        "event": row.get("event_name") or "call.completed",
        "status": row["status"],
        "httpStatus": int(row.get("http_status") or 0),
        "latencyMs": int(row.get("latency_ms") or 0),
        "attempt": int(row.get("attempt_number") or 1),
        "maxAttempts": max_attempts,
        "at": at_ms,
        "payload": payload,
        "responseBody": row.get("response_body"),
        # 'live' or 'simulated'. The test-fire button does no egress, and a row
        # it produced must never be mistaken for a delivery that happened.
        "mode": row.get("delivery_mode") or "live",
    }


def list_webhook_deliveries(endpoint_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with db.engine.connect() as conn:
        params: dict[str, Any] = {"limit": limit, "tenant": db.current_tenant()}
        where = "WHERE e.tenant_id = :tenant"
        if endpoint_id:
            where += " AND d.endpoint_id = :eid"
            params["eid"] = endpoint_id
        rows = db._rows(
            conn.execute(
                text(
                    f"""
                    SELECT d.*, et.name AS event_name, rp.max_attempts
                    FROM webhook_deliveries d
                    JOIN webhook_endpoints e ON e.id = d.endpoint_id
                    LEFT JOIN event_types et ON et.id = d.event_type_id
                    LEFT JOIN webhook_retry_policies rp ON rp.endpoint_id = d.endpoint_id
                    {where}
                    ORDER BY d.created_at DESC
                    LIMIT :limit
                    """
                ),
                params,
            )
        )
    return [_delivery_contract(r, int(r.get("max_attempts") or 3)) for r in rows]


def test_fire_webhook(endpoint_id: str, event_key: str | None = None) -> dict[str, Any]:
    """The Integrations test-fire button. Simulated on purpose — no egress.

    This exists so the screen can be demonstrated without a receiver, and it is
    the ONLY path that still simulates. Real events go through
    ``webhooks_dispatch.dispatch``, and the row this writes is stamped
    ``delivery_mode='simulated'`` so the log distinguishes the two. It used to
    be the only producer of deliveries at all, which is how a system that had
    never sent a webhook came to have a delivery log full of 200s.
    """
    with db.engine.begin() as conn:
        ep = _endpoint_contract(conn, endpoint_id)
        if ep is None:
            raise KeyError("endpoint_not_found")
        if ep["status"] == "paused":
            raise ValueError("endpoint_paused")
        key = event_key or (ep["events"][0] if ep["events"] else "call.completed")
        et_id = _ensure_event_type(conn, key)
        host = urlparse(ep["url"]).hostname or ""
        # Simulated delivery — no real egress from this process (safe for demo/prod UI).
        ok = bool(host) and ep["status"] == "active"
        http_status = 200 if ok else 502
        status = "success" if ok else "server_err"
        # Deterministic digest, not hash(): PYTHONHASHSEED randomises str
        # hashing per process, so the same endpoint produced a different
        # persisted latency on every worker and every restart.
        latency = 40 + (
            int.from_bytes(hashlib.sha256(endpoint_id.encode()).digest()[:4], "big") % 180
        )
        did = _id("dlv")
        payload = {
            "event": key,
            "endpointId": endpoint_id,
            "tenant": db.current_tenant(),
            "test": True,
            "at": utc_now().isoformat(),
        }
        conn.execute(
            text(
                """
                INSERT INTO webhook_deliveries (
                  id, endpoint_id, event_type_id, payload, response_body,
                  http_status, attempt_number, latency_ms, status,
                  delivery_mode, created_at, updated_at, request_id
                ) VALUES (
                  :id, :eid, :et, CAST(:payload AS jsonb), :body,
                  :http, 1, :lat, :status,
                  'simulated', now(), now(), :rid
                )
                """
            ),
            {
                "rid": request_context.get_request_id(),
                "id": did,
                "eid": endpoint_id,
                "et": et_id,
                "payload": json.dumps(payload),
                "body": '{"ok":true,"mode":"simulated"}' if ok else '{"ok":false}',
                "http": http_status,
                "lat": latency,
                "status": status,
            },
        )
        row = {
            "id": did,
            "endpoint_id": endpoint_id,
            "event_name": key,
            "payload": payload,
            "response_body": '{"ok":true,"mode":"simulated"}' if ok else '{"ok":false}',
            "http_status": http_status,
            "attempt_number": 1,
            "latency_ms": latency,
            "status": status,
            "delivery_mode": "simulated",
            "created_at": utc_now(),
        }
    return _delivery_contract(row, ep["retry"]["attempts"])


def retry_webhook_delivery(delivery_id: str) -> dict[str, Any]:
    """Re-queue the ORIGINAL payload for real delivery.

    This used to select ``d.payload`` and then throw it away, calling the
    simulator instead — so "retry" re-simulated a different, synthetic event and
    reported success for something that had never been sent. The receiver that
    missed the payment notification still had not received it.

    One click, one attempt. ``attempt_number`` carries forward from the row
    being retried rather than resetting, so a delivery that already burned its
    automatic ladder does not silently start a fresh one: the worker settles it
    terminally and the operator decides whether to click again.
    """
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT d.endpoint_id, d.event_type_id, d.payload,
                           d.attempt_number, d.delivery_mode,
                           et.name AS event_name, e.status AS endpoint_status
                    FROM webhook_deliveries d
                    JOIN webhook_endpoints e ON e.id = d.endpoint_id
                    LEFT JOIN event_types et ON et.id = d.event_type_id
                    WHERE d.id = :id AND e.tenant_id = :tenant
                    """
                ),
                {"id": delivery_id, "tenant": db.current_tenant()},
            )
        )
    if row is None:
        raise KeyError("delivery_not_found")
    if row.get("endpoint_status") == "paused":
        raise ValueError("endpoint_paused")
    # A simulated row has no real payload behind it, so retrying one can only
    # mean firing the simulator again. Say so by staying on that path.
    if (row.get("delivery_mode") or "live") == "simulated":
        return test_fire_webhook(row["endpoint_id"], row.get("event_name"))

    payload = row.get("payload") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            payload = {}
    did = _id("dlv")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO webhook_deliveries (
                  id, endpoint_id, event_type_id, payload, attempt_number,
                  status, delivery_mode, created_at, updated_at, request_id
                ) VALUES (
                  :id, :eid, :et, CAST(:payload AS jsonb), :attempt,
                  'pending', 'live', now(), now(), :rid
                )
                """
            ),
            {
                "id": did,
                "eid": row["endpoint_id"],
                "et": row["event_type_id"],
                "payload": json.dumps(payload),
                "attempt": int(row.get("attempt_number") or 1),
                "rid": request_context.get_request_id(),
            },
        )
        fresh = db._one(
            conn.execute(
                text(
                    """
                    SELECT d.*, et.name AS event_name, rp.max_attempts
                    FROM webhook_deliveries d
                    LEFT JOIN event_types et ON et.id = d.event_type_id
                    LEFT JOIN webhook_retry_policies rp ON rp.endpoint_id = d.endpoint_id
                    WHERE d.id = :id
                    """
                ),
                {"id": did},
            )
        )
    assert fresh is not None
    return _delivery_contract(fresh, int(fresh.get("max_attempts") or 3))
