"""Outbound webhook delivery — the contract a tenant's integration depends on.

Every test here uses a stubbed transport. Nothing in this file may make a
network call: the module under test exists to POST to arbitrary operator-supplied
URLs, and a test suite that actually did so would be a request forgery with a
green tick next to it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from typing import Any

import pytest
from sqlalchemy import text

import webhooks_dispatch as wd


def _park_foreign_pending(conn: Any) -> None:
    """Take pre-existing queued deliveries out of the claim's way.

    ``claim_next`` is oldest-first across the whole table, so a row committed by
    something else would be claimed ahead of the one under test and the failure
    would read as a claim bug. Rolled back with the fixture's transaction.
    """
    conn.execute(text("UPDATE webhook_deliveries SET status = 'success' WHERE status = 'pending'"))


def _endpoint(
    conn: Any,
    *,
    status: str = "active",
    events: tuple[str, ...] = ("promise.kept",),
    secret: str | None = "top-secret-value",
    max_attempts: int = 3,
    url: str = "https://hooks.example.com/crm",
) -> dict[str, Any]:
    """One webhook endpoint with its subscriptions and retry policy."""
    import db

    tenant = db.current_tenant()
    eid = f"wh-ut-{uuid.uuid4().hex[:8]}"
    secret_hash = hashlib.sha256(secret.encode()).hexdigest() if secret else None
    conn.execute(
        text(
            """
            INSERT INTO tenants (id, name, created_at, updated_at)
            VALUES (:id, :id, now(), now()) ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": tenant},
    )
    conn.execute(
        text(
            """
            INSERT INTO webhook_endpoints (
              id, tenant_id, target_system, url, status, signing_algorithm,
              secret_ref, secret_hash, name, created_at, updated_at
            ) VALUES (
              :id, :tenant, 'Custom', :url, :status, 'HMAC-SHA256',
              :ref, :hash, :id, now(), now()
            )
            """
        ),
        {
            "id": eid,
            "tenant": tenant,
            "url": url,
            "status": status,
            "ref": f"vault://local/{eid}",
            "hash": secret_hash,
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO webhook_retry_policies (
              id, endpoint_id, max_attempts, backoff_strategy, max_event_age_sec,
              created_at, updated_at
            ) VALUES (:id, :eid, :a, 'exponential', 86400, now(), now())
            """
        ),
        {"id": f"whr-ut-{uuid.uuid4().hex[:8]}", "eid": eid, "a": max_attempts},
    )
    for key in events:
        etid = f"evt-{key.replace('.', '-')}"
        conn.execute(
            text(
                """
                INSERT INTO event_types (id, name, description, created_at, updated_at)
                VALUES (:id, :name, :name, now(), now()) ON CONFLICT (name) DO NOTHING
                """
            ),
            {"id": etid, "name": key},
        )
        real = conn.execute(
            text("SELECT id FROM event_types WHERE name = :n"), {"n": key}
        ).scalar()
        conn.execute(
            text(
                """
                INSERT INTO webhook_subscriptions (endpoint_id, event_type_id, created_at)
                VALUES (:eid, :et, now()) ON CONFLICT DO NOTHING
                """
            ),
            {"eid": eid, "et": real},
        )
    return {"id": eid, "secret": secret, "secret_hash": secret_hash, "url": url}


def _delivery(conn: Any, delivery_id: str) -> dict[str, Any]:
    row = (
        conn.execute(
            text("SELECT * FROM webhook_deliveries WHERE id = :id"), {"id": delivery_id}
        )
        .mappings()
        .first()
    )
    assert row is not None, f"delivery {delivery_id} vanished"
    return dict(row)


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch):
    """Replace the HTTP seam and the DNS re-check. Records every call."""
    calls: list[dict[str, Any]] = []
    reply: dict[str, Any] = {"status": 200, "body": '{"ok":true}'}

    def _fake_post(url: str, *, headers: dict[str, str], body: str, timeout: float):
        calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        if isinstance(reply.get("raises"), Exception):
            raise reply["raises"]
        return int(reply["status"]), str(reply["body"])

    monkeypatch.setattr(wd, "_post", _fake_post)
    monkeypatch.setattr(wd, "resolve_public_host", lambda url: "203.0.113.10")
    return {"calls": calls, "reply": reply}


# --- subscription resolution ------------------------------------------------


def test_dispatch_queues_only_active_subscribed_endpoints(db_tx) -> None:
    subscribed = _endpoint(db_tx, events=("promise.kept",))
    _endpoint(db_tx, status="paused", events=("promise.kept",))
    _endpoint(db_tx, events=("promise.broken",))

    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    assert len(ids) == 1
    row = _delivery(db_tx, ids[0])
    assert row["endpoint_id"] == subscribed["id"]
    assert row["status"] == "pending"
    assert row["delivery_mode"] == "live"
    # Nothing has been attempted yet; the claim is what makes it attempt 1.
    assert row["attempt_number"] == 0


def test_dispatch_queues_one_row_per_subscribed_endpoint(db_tx) -> None:
    first = _endpoint(db_tx)
    second = _endpoint(db_tx)

    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    assert len(ids) == 2
    endpoints = {_delivery(db_tx, i)["endpoint_id"] for i in ids}
    assert endpoints == {first["id"], second["id"]}


def test_dispatch_on_an_unsubscribed_event_queues_nothing(db_tx) -> None:
    _endpoint(db_tx, events=("promise.kept",))
    assert wd.dispatch(db_tx, "payment.updated", {"intentId": "PI-1"}) == []


def test_dispatch_carries_the_event_envelope(db_tx) -> None:
    import db

    _endpoint(db_tx)
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1", "amount": 2500.0})
    payload = _delivery(db_tx, ids[0])["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert payload["event"] == "promise.kept"
    assert payload["tenant"] == db.current_tenant()
    assert payload["data"] == {"promiseId": "P-1", "amount": 2500.0}
    assert payload["at"]


def test_dispatch_never_raises_into_the_business_path(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A broken integration must not be able to roll back the payment that
    # triggered it. The failure is logged and the caller carries on.
    def _boom(*_args, **_kwargs):
        raise RuntimeError("subscription lookup exploded")

    monkeypatch.setattr(wd, "_endpoints_for", _boom)
    assert wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"}) == []


# --- signing ----------------------------------------------------------------


def test_signature_is_verifiable_by_a_holder_of_the_plaintext_secret(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    endpoint = _endpoint(db_tx)
    wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    assert wd.process_one(db.engine) is True

    sent = transport["calls"][0]
    signature = sent["headers"][wd.SIGNATURE_HEADER]
    timestamp = sent["headers"][wd.TIMESTAMP_HEADER]
    # The receiver holds the plaintext and derives the key exactly as the
    # module docstring documents. If this ever diverges, every receiver's
    # verification silently starts rejecting real events.
    key = hashlib.sha256(endpoint["secret"].encode()).hexdigest()
    expected = hmac.new(
        key.encode(), f"{timestamp}.{sent['body']}".encode(), hashlib.sha256
    ).hexdigest()
    assert hmac.compare_digest(expected, signature)


def test_signature_covers_the_timestamp_so_a_body_cannot_be_replayed() -> None:
    key = hashlib.sha256(b"top-secret-value").hexdigest()
    body = '{"event":"promise.kept"}'
    assert wd.sign(key, "1000", body) != wd.sign(key, "2000", body)


def test_delivery_headers_name_the_event_and_the_delivery(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx)
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    headers = transport["calls"][0]["headers"]
    assert headers[wd.EVENT_HEADER] == "promise.kept"
    # Receivers deduplicate on this, which is what makes an unconditional
    # requeue of a stuck claim safe.
    assert headers[wd.DELIVERY_HEADER] == ids[0]
    assert headers["Content-Type"] == "application/json"


def test_an_endpoint_with_no_secret_is_not_sent_unsigned(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx, secret=None)
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    assert transport["calls"] == []
    row = _delivery(db_tx, ids[0])
    assert "secret_unavailable" in (row["response_body"] or "")


# --- SSRF -------------------------------------------------------------------


def test_a_host_that_resolves_privately_is_not_posted_to(
    db_tx, monkeypatch: pytest.MonkeyPatch, transport
) -> None:
    import db

    _park_foreign_pending(db_tx)
    # Registration-time validation passed; DNS now answers with a private
    # address. This is the rebinding case _validate_webhook_url cannot cover.
    monkeypatch.setattr(
        wd,
        "resolve_public_host",
        lambda url: (_ for _ in ()).throw(ValueError("webhook_url_private_forbidden: 10.0.0.5")),
    )
    _endpoint(db_tx)
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    assert transport["calls"] == []
    assert "private_forbidden" in (_delivery(db_tx, ids[0])["response_body"] or "")


def test_resolve_public_host_rejects_a_private_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket as sock

    monkeypatch.setattr(
        wd.socket,
        "getaddrinfo",
        lambda *a, **k: [(sock.AF_INET, sock.SOCK_STREAM, 6, "", ("10.1.2.3", 443))],
    )
    with pytest.raises(ValueError, match="private_forbidden"):
        wd.resolve_public_host("https://hooks.example.com/crm")


def test_resolve_public_host_rejects_a_mixed_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket as sock

    # One private address among public ones is enough — the connect may land
    # on it.
    monkeypatch.setattr(
        wd.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (sock.AF_INET, sock.SOCK_STREAM, 6, "", ("203.0.113.7", 443)),
            (sock.AF_INET, sock.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(ValueError, match="private_forbidden"):
        wd.resolve_public_host("https://hooks.example.com/crm")


def test_resolve_public_host_requires_https() -> None:
    with pytest.raises(ValueError, match="https_required"):
        wd.resolve_public_host("http://hooks.example.com/crm")


# --- outcomes ---------------------------------------------------------------


def test_happy_path_records_a_real_status_and_latency(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx)
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    assert wd.process_one(db.engine) is True

    row = _delivery(db_tx, ids[0])
    assert row["status"] == "success"
    assert row["http_status"] == 200
    assert row["response_body"] == '{"ok":true}'
    assert row["attempt_number"] == 1
    assert row["next_retry_at"] is None
    assert row["latency_ms"] is not None
    # The claim is released whatever the outcome, or the row is stuck forever.
    assert row["locked_at"] is None and row["locked_by"] is None


def test_a_server_error_is_logged_and_left_retryable(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx, max_attempts=3)
    transport["reply"].update(status=503, body="upstream unavailable")
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    row = _delivery(db_tx, ids[0])
    # Still queue work, so still 'pending' — with the upstream's own words and
    # a scheduled next attempt rather than a silent disappearance.
    assert row["status"] == "pending"
    assert row["http_status"] == 503
    assert row["response_body"] == "upstream unavailable"
    assert row["next_retry_at"] is not None


def test_retries_stop_at_the_endpoint_retry_policy(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx, max_attempts=1)
    transport["reply"].update(status=500, body="boom")
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    row = _delivery(db_tx, ids[0])
    assert row["status"] == "server_err"
    assert row["attempt_number"] == 1
    assert row["next_retry_at"] is None


def test_a_client_error_is_terminal_without_burning_the_budget(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx, max_attempts=5)
    transport["reply"].update(status=422, body='{"error":"unknown event"}')
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    row = _delivery(db_tx, ids[0])
    # Re-sending identical bytes cannot change a 4xx. Four more attempts would
    # only delay the operator seeing the red row.
    assert row["status"] == "client_err"
    assert row["attempt_number"] == 1
    assert row["next_retry_at"] is None


def test_a_transport_exception_is_recorded_as_retryable(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx, max_attempts=3)
    transport["reply"]["raises"] = ConnectionError("connection refused")
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    row = _delivery(db_tx, ids[0])
    assert row["status"] == "pending"
    assert row["http_status"] == 0
    assert "connection refused" in (row["response_body"] or "")
    assert row["next_retry_at"] is not None


def test_a_long_response_body_is_truncated(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx)
    transport["reply"].update(status=200, body="x" * (wd.MAX_RESPONSE_BODY + 500))
    ids = wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    wd.process_one(db.engine)

    assert len(_delivery(db_tx, ids[0])["response_body"]) == wd.MAX_RESPONSE_BODY


def test_process_one_reports_an_empty_queue(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    assert wd.process_one(db.engine) is False
    assert transport["calls"] == []


def test_a_row_waiting_on_its_backoff_is_not_claimed_again(db_tx, transport) -> None:
    import db

    _park_foreign_pending(db_tx)
    _endpoint(db_tx, max_attempts=3)
    transport["reply"].update(status=503, body="later")
    wd.dispatch(db_tx, "promise.kept", {"promiseId": "P-1"})

    assert wd.process_one(db.engine) is True
    # next_retry_at is in the future, so the second pass finds nothing.
    assert wd.process_one(db.engine) is False
    assert len(transport["calls"]) == 1


# --- business emit sites ----------------------------------------------------


@pytest.fixture
def seeded_account(db_tx):
    """A real customer/account pair from the seed — promises have FKs to both."""
    import db

    row = (
        db_tx.execute(
            text(
                """
                SELECT a.id AS account_id, a.customer_id
                FROM accounts a
                JOIN customers c ON c.id = a.customer_id
                WHERE c.tenant_id = :t
                ORDER BY a.id LIMIT 1
                """
            ),
            {"t": db.current_tenant()},
        )
        .mappings()
        .first()
    )
    if row is None:
        pytest.skip("seed has no account to hang a promise on")
    return dict(row)


def _promise(conn: Any, account: dict[str, Any], *, amount: int, promised_at: str) -> str:
    import db

    pid = f"PRM-WHUT-{uuid.uuid4().hex[:8].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO promises (
              id, customer_id, account_id, owner_kind, owner_bot_id,
              amount, paid_amount, promised_at, status, reminder_status
            ) VALUES (
              :id, :c, :a, 'bot', :bot,
              :amount, 0, """
            + promised_at
            + """, 'upcoming', 'off'
            )
            """
        ),
        {
            "id": pid,
            "c": account["customer_id"],
            "a": account["account_id"],
            "bot": db.DEFAULT_BOT_ID,
            "amount": amount,
        },
    )
    return pid


def test_promise_kept_emits_when_a_payment_settles_a_promise(
    db_tx, seeded_account, monkeypatch
) -> None:
    import payments

    seen: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        payments.webhooks_dispatch,
        "dispatch",
        lambda conn, key, payload, **kw: (seen.append((key, payload)), [])[1],
    )
    pid = _promise(db_tx, seeded_account, amount=1000, promised_at="now() + interval '1 day'")

    payments.allocate_to_promises(
        db_tx, account_id=seeded_account["account_id"], amount=payments._money(1000)
    )

    kept = [p for key, p in seen if key == "promise.kept" and p["promiseId"] == pid]
    assert len(kept) == 1, f"expected one promise.kept for {pid}, saw {seen}"
    assert kept[0]["customerId"] == seeded_account["customer_id"]
    assert kept[0]["paidAmount"] == 1000.0


def test_a_partial_allocation_does_not_claim_the_promise_was_kept(
    db_tx, seeded_account, monkeypatch
) -> None:
    import payments

    seen: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        payments.webhooks_dispatch,
        "dispatch",
        lambda conn, key, payload, **kw: (seen.append((key, payload)), [])[1],
    )
    pid = _promise(db_tx, seeded_account, amount=1000, promised_at="now() + interval '1 day'")

    payments.allocate_to_promises(
        db_tx, account_id=seeded_account["account_id"], amount=payments._money(400)
    )

    assert [p for key, p in seen if key == "promise.kept" and p["promiseId"] == pid] == []


def test_promise_broken_emits_when_the_settler_auto_breaks_a_promise(
    db_tx, seeded_account, monkeypatch
) -> None:
    import db
    import promise_fulfillment

    seen: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        promise_fulfillment.webhooks_dispatch,
        "dispatch",
        lambda conn, key, payload, **kw: (seen.append((key, payload)), [])[1],
    )
    pid = _promise(db_tx, seeded_account, amount=3000, promised_at="now() - interval '2 days'")

    promise_fulfillment.settle_promises(db.engine)

    broken = [p for key, p in seen if key == "promise.broken" and p["promiseId"] == pid]
    assert len(broken) == 1, f"expected one promise.broken for {pid}, saw {seen}"
    assert broken[0]["customerId"] == seeded_account["customer_id"]
    assert broken[0]["accountId"] == seeded_account["account_id"]
