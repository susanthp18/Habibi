"""One owner for the regulated dial, and what it makes impossible.

Every dial site used to compose ``reserve → admit → suppress → place`` by hand,
and two of the seven wrote the steps in the other order. ``outbound.gate`` is
now the only place the three gate steps meet (``test_outbound_gate_contract``
proves that by AST); this file proves what the composition *does*:

* a refused gate is a suppressed row — including at the bounce site, which used
  to admit first and leave nothing behind;
* one idempotency key is one attempt, and the key is released only by a
  refusal or a provably-unplaced dial, never by one that may have rung;
* carrier I/O happens after the transaction that decided it — the bounce SMS
  and the PTP reminder no longer send under a row lock, so a rollback cannot
  turn one message into two;
* a second settlement is not swallowed as a replay, and a cure that fails is
  reported rather than committed half-done.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

import db
import db_inbox
import outbound

IST = ZoneInfo("Asia/Kolkata")
TEST_PHONE = "919655282324"


def _a_customer(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id, a.id AS account_id
            FROM customers c
            JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer with an account")
    return dict(row)


def _open_the_gate(conn, monkeypatch: pytest.MonkeyPatch, customer_id: str) -> None:
    """Consent in, DND off, any hour, no caps — so a refusal is one we made."""
    monkeypatch.setenv("CONTACT_DAILY_CAP", "50")
    monkeypatch.setenv("CONTACT_WEEKLY_CAP", "50")
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    conn.execute(
        text(
            "UPDATE customers SET dnd = false, timezone = 'Asia/Kolkata', "
            "preferred_window = NULL, phone_primary = :p WHERE id = :id"
        ),
        {"id": customer_id, "p": TEST_PHONE},
    )
    conn.execute(
        text("INSERT INTO consent_records (id, customer_id) VALUES (:id, :cid) ON CONFLICT (customer_id) DO NOTHING"),
        {"id": f"CR-{customer_id}", "cid": customer_id},
    )
    conn.execute(
        text("UPDATE consent_records SET dnd_registry = false, allowed_days = NULL, allowed_hours = NULL WHERE customer_id = :id"),
        {"id": customer_id},
    )
    cr = conn.execute(
        text("SELECT id FROM consent_records WHERE customer_id = :id"), {"id": customer_id}
    ).scalar()
    for ch in ("voice", "sms", "whatsapp"):
        conn.execute(
            text(
                """
                INSERT INTO channel_consents
                  (id, consent_id, channel, status, weekly_frequency_cap, used_this_week, captured_at)
                VALUES (:id, :cr, :ch, 'opted_in', 50, 0, now())
                ON CONFLICT (consent_id, channel, purpose)
                DO UPDATE SET status = 'opted_in', weekly_frequency_cap = 50, captured_at = now()
                """
            ),
            {"id": f"{cr}-{ch}", "cr": cr, "ch": ch},
        )


def _noon() -> datetime:
    return datetime(2026, 8, 13, 12, 0, tzinfo=IST).astimezone(timezone.utc)


def _attempt(conn, attempt_id: str) -> dict:
    row = conn.execute(
        text("SELECT state, suppressed_reason, idempotency_key, provider_error FROM call_attempts WHERE id = :id"),
        {"id": attempt_id},
    ).mappings().first()
    assert row is not None
    return dict(row)


# ---------------------------------------------------------------------------
# gate(): the composition
# ---------------------------------------------------------------------------


def test_a_refused_gate_is_a_suppressed_row(db_tx, monkeypatch) -> None:
    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    db_tx.execute(text("UPDATE customers SET dnd = true WHERE id = :id"), {"id": cust["id"]})

    gated = outbound.gate(
        db_tx,
        admit={"source": "test", "actor_kind": "human", "now": _noon()},
        customer_id=cust["id"],
        to_phone=TEST_PHONE,
        objective="dpd_reminder",
        account_id=cust["account_id"],
    )

    assert not gated.allowed
    assert gated.reason == "customer_dnd"
    row = _attempt(db_tx, gated.attempt["id"])
    assert row["state"] == "suppressed"
    assert row["suppressed_reason"] == "customer_dnd"


def test_the_same_key_is_one_attempt(db_tx, monkeypatch) -> None:
    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    key = f"test:{uuid.uuid4().hex}"
    common = dict(
        admit={"source": "test", "actor_kind": "human", "now": _noon()},
        customer_id=cust["id"],
        to_phone=TEST_PHONE,
        objective="dpd_reminder",
        account_id=cust["account_id"],
    )

    first = outbound.gate(db_tx, idempotency_key=key, **common)
    second = outbound.gate(db_tx, idempotency_key=key, **common)

    assert first.allowed and not first.existing
    assert second.existing and not second.allowed
    assert second.attempt["id"] == first.attempt["id"]
    n = db_tx.execute(
        text("SELECT count(*) FROM call_attempts WHERE idempotency_key = :k"), {"k": key}
    ).scalar()
    assert n == 1
    # The second call ran no gate: one counted touch, not two.
    touches = db_tx.execute(
        text("SELECT count(*) FROM contact_events WHERE session_key = :sk"),
        {"sk": first.attempt["id"]},
    ).scalar()
    assert touches == 1


def test_a_refusal_releases_the_key_so_the_next_try_reserves_afresh(db_tx, monkeypatch) -> None:
    """A suppressed attempt was never made. The cadence retries the same rung
    two hours later under the same key; finding the refusal and stopping
    would strand the ladder."""
    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    db_tx.execute(text("UPDATE customers SET dnd = true WHERE id = :id"), {"id": cust["id"]})
    key = f"test:{uuid.uuid4().hex}"
    common = dict(
        admit={"source": "test", "actor_kind": "human", "now": _noon()},
        customer_id=cust["id"],
        to_phone=TEST_PHONE,
        objective="dpd_reminder",
        account_id=cust["account_id"],
    )

    refused = outbound.gate(db_tx, idempotency_key=key, **common)
    assert not refused.allowed
    assert _attempt(db_tx, refused.attempt["id"])["idempotency_key"] is None

    db_tx.execute(text("UPDATE customers SET dnd = false WHERE id = :id"), {"id": cust["id"]})
    again = outbound.gate(db_tx, idempotency_key=key, **common)
    assert again.allowed and not again.existing
    assert again.attempt["id"] != refused.attempt["id"]


def test_a_waived_refusal_is_returned_not_suppressed(db_tx, monkeypatch) -> None:
    """The demo handset. The refusal is still the gate's answer; the caller is
    told why it is dialling anyway, and the row can go on to `place`."""
    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    midnight = datetime(2026, 8, 13, 0, 30, tzinfo=IST).astimezone(timezone.utc)

    gated = outbound.gate(
        db_tx,
        admit={"source": "test", "actor_kind": "human", "now": midnight},
        waivable=frozenset({"outside_calling_hours"}),
        customer_id=cust["id"],
        to_phone=TEST_PHONE,
        objective="dpd_reminder",
        account_id=cust["account_id"],
    )

    assert gated.waived and gated.allowed
    assert gated.reason == "outside_calling_hours"
    assert _attempt(db_tx, gated.attempt["id"])["state"] == "reserved"


def test_consent_is_never_waivable(db_tx, monkeypatch) -> None:
    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    db_tx.execute(text("UPDATE customers SET dnd = true WHERE id = :id"), {"id": cust["id"]})

    gated = outbound.gate(
        db_tx,
        admit={"source": "test", "actor_kind": "human", "now": _noon()},
        waivable=frozenset({"outside_calling_hours"}),
        customer_id=cust["id"],
        to_phone=TEST_PHONE,
        objective="dpd_reminder",
        account_id=cust["account_id"],
    )
    assert not gated.allowed and not gated.waived
    assert _attempt(db_tx, gated.attempt["id"])["state"] == "suppressed"


def test_a_bare_number_reserves_nothing_and_is_refused(db_tx) -> None:
    gated = outbound.gate(
        db_tx,
        admit={"source": "test", "actor_kind": "human"},
        customer_id=None,
        to_phone=TEST_PHONE,
        objective="manual_outbound",
    )
    assert gated.attempt is None
    assert not gated.allowed
    assert gated.reason == "no_customer"


# ---------------------------------------------------------------------------
# place(): ambiguity is decided at the carrier boundary
# ---------------------------------------------------------------------------


class _Rest(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(f"twilio {status}")
        self.status = status


@pytest.mark.parametrize(
    ("exc", "reason", "key_kept"),
    [
        (_Rest(503), outbound.AMBIGUOUS_REASON, True),
        (_Rest(429), outbound.AMBIGUOUS_REASON, True),
        (_Rest(400), "dial_failed", False),
        (TimeoutError("read timed out"), outbound.AMBIGUOUS_REASON, True),
        (ConnectionError("refused"), "dial_failed", False),
    ],
)
def test_place_classifies_the_carrier_failure(db_tx, monkeypatch, exc, reason, key_kept) -> None:
    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    monkeypatch.setenv("OUTBOUND_MAX_IN_FLIGHT", "50")
    import platform_switches

    monkeypatch.setattr(platform_switches, "outbound_enabled", lambda: True)

    def _boom(**_):
        raise exc

    monkeypatch.setattr("voice.twilio_ops.start_outbound_call", _boom)
    key = f"test:{uuid.uuid4().hex}"
    gated = outbound.gate(
        db_tx,
        idempotency_key=key,
        admit={"source": "test", "actor_kind": "human", "now": _noon()},
        customer_id=cust["id"],
        to_phone=TEST_PHONE,
        objective="dpd_reminder",
        account_id=cust["account_id"],
    )
    assert gated.allowed

    result = outbound.place(db.engine, gated.attempt, to_phone=TEST_PHONE)

    assert result["placed"] is False
    assert result["reason"] == reason
    row = _attempt(db_tx, gated.attempt["id"])
    assert row["state"] == "failed"
    assert (row["idempotency_key"] == key) is key_kept


# ---------------------------------------------------------------------------
# The bounce site: gated on its own transaction, sent after commit
# ---------------------------------------------------------------------------


def _bounce_payload(account_id: str, now: datetime) -> dict:
    return {
        "accountId": account_id,
        "source": "sandbox",
        "sourceRef": f"NACH-{uuid.uuid4().hex}",
        "amount": 1500.0,
        "reason": "insufficient_funds",
        "occurredAt": now.isoformat(),
    }


def test_ingest_decides_and_deliver_sends(db_tx, monkeypatch) -> None:
    """The SMS is not sent inside `ingest`. It is returned, and `deliver`
    sends it — after the caller has committed, in production."""
    import payment_events as pe
    from tests.test_payment_events import _opt_out

    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    monkeypatch.setenv("BOUNCE_VOICE_ENABLED", "false")
    _opt_out(db_tx, cust["id"], ("whatsapp",))
    sent: list[dict] = []
    monkeypatch.setattr("twilio_sms.configured", lambda: True)
    monkeypatch.setattr("twilio_sms.send", lambda **kw: sent.append(kw) or {"sid": "SM-1"})
    now = _noon()

    out = pe.ingest(db_tx, _bounce_payload(cust["account_id"], now), now=now)

    assert sent == [], "ingest sent an SMS inside the transaction"
    assert [d["kind"] for d in out["deferred"]] == ["sms"]
    before = db_tx.execute(
        text("SELECT first_touch_at, status FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert before["first_touch_at"] is None

    pe.deliver(db.engine, out["deferred"])

    assert len(sent) == 1
    after = db_tx.execute(
        text("SELECT first_touch_at, first_touch_channel, status FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert after["first_touch_channel"] == "sms"
    assert after["first_touch_at"] is not None
    assert after["status"] == "in_progress"


def test_a_failed_sms_leaves_the_case_open_with_its_reason(db_tx, monkeypatch) -> None:
    import payment_events as pe
    from tests.test_payment_events import _opt_out

    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    monkeypatch.setenv("BOUNCE_VOICE_ENABLED", "false")
    _opt_out(db_tx, cust["id"], ("whatsapp",))
    monkeypatch.setattr("twilio_sms.configured", lambda: True)

    def _boom(**_):
        raise RuntimeError("carrier down")

    monkeypatch.setattr("twilio_sms.send", _boom)
    now = _noon()

    out = pe.ingest(db_tx, _bounce_payload(cust["account_id"], now), now=now)
    pe.deliver(db.engine, out["deferred"])

    event = db_tx.execute(
        text("SELECT first_touch_at, status, suppression_reason FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["first_touch_at"] is None
    assert event["status"] == "open"
    assert event["suppression_reason"] == "sms_send_failed"


def test_a_refused_bounce_dial_leaves_a_suppressed_attempt(db_tx, monkeypatch) -> None:
    """The hole WP-028 named: this site admitted first and reserved nothing."""
    import payment_events as pe
    from tests.test_payment_events import _opt_out

    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    monkeypatch.setenv("BOUNCE_VOICE_ENABLED", "true")
    _opt_out(db_tx, cust["id"], ("whatsapp", "sms"))
    # Voice refused for a reason that is about *them*: the voice channel
    # itself is opted out, while the customer is otherwise contactable.
    _opt_out(db_tx, cust["id"], ("voice",))
    now = _noon()

    out = pe.ingest(db_tx, _bounce_payload(cust["account_id"], now), now=now)
    pe.deliver(db.engine, out["deferred"])

    row = db_tx.execute(
        text(
            """
            SELECT state, suppressed_reason FROM call_attempts
            WHERE customer_id = :cid AND objective = 'bounce_cure'
            ORDER BY reserved_at DESC LIMIT 1
            """
        ),
        {"cid": cust["id"]},
    ).mappings().first()
    assert row is not None, "the refused dial left no attempt row"
    assert row["state"] == "suppressed"
    assert row["suppressed_reason"]


# ---------------------------------------------------------------------------
# PTP reminders: claim, commit, send, record
# ---------------------------------------------------------------------------


def _reminder(conn, monkeypatch, cust: dict, *, channel: str = "sms") -> tuple[str, str]:
    import promise_fulfillment as pf

    promise_id = f"PTP-T-{uuid.uuid4().hex[:8].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO promises
              (id, customer_id, account_id, owner_kind, owner_bot_id, amount, promised_at,
               status, reminder_status, channel)
            VALUES (:id, :cid, :aid, 'bot', 'kaia-v2-4', 500, now() + interval '3 days',
                    'upcoming', 'queued', 'voice')
            """
        ),
        {"id": promise_id, "cid": cust["id"], "aid": cust["account_id"]},
    )
    pf.create_pay_intent(
        conn,
        tenant_id=cust["tenant_id"],
        customer_id=cust["id"],
        account_id=cust["account_id"],
        amount=Decimal("500.00"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        promise_id=promise_id,
    )
    rid = f"PRM-T-{uuid.uuid4().hex[:8].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO promise_reminders (id, promise_id, channel, kind, scheduled_at, status)
            VALUES (:id, :pid, :ch, 'due', now() - interval '1 minute', 'queued')
            """
        ),
        {"id": rid, "pid": promise_id, "ch": channel},
    )
    return promise_id, rid


def _reminder_row(conn, rid: str) -> dict:
    row = conn.execute(
        text("SELECT status, sending_at, attempts, scheduled_at, provider_delivery_id FROM promise_reminders WHERE id = :id"),
        {"id": rid},
    ).mappings().first()
    assert row is not None
    return dict(row)


def test_a_reminder_is_sent_under_a_lease_and_closed_after(db_tx, monkeypatch) -> None:
    import promise_fulfillment as pf

    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    db_tx.execute(text("UPDATE promise_reminders SET status = 'sent' WHERE status IN ('queued','scheduled')"))
    _pid, rid = _reminder(db_tx, monkeypatch, cust)
    seen: list[dict] = []

    def _send(**kw):
        # At send time the claim is on the row: lease held, attempt counted.
        seen.append(_reminder_row(db_tx, rid))
        return {"sid": "SM-r"}

    monkeypatch.setattr("twilio_sms.send", _send)
    monkeypatch.setattr("twilio_sms.configured", lambda: True)
    # Noon IST, inside the calling window, so the gate is not what decides.
    import contact_policy

    real_admit = contact_policy.admit
    monkeypatch.setattr(
        contact_policy, "admit", lambda conn, **kw: real_admit(conn, **{**kw, "now": _noon()})
    )

    assert pf.process_one_reminder(db.engine) is True

    assert len(seen) == 1
    assert seen[0]["sending_at"] is not None
    assert seen[0]["attempts"] == 1
    after = _reminder_row(db_tx, rid)
    assert after["status"] == "sent"
    assert after["sending_at"] is None


def test_a_leased_reminder_is_not_claimed_twice(db_tx, monkeypatch) -> None:
    import promise_fulfillment as pf

    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    db_tx.execute(text("UPDATE promise_reminders SET status = 'sent' WHERE status IN ('queued','scheduled')"))
    _pid, rid = _reminder(db_tx, monkeypatch, cust)
    db_tx.execute(
        text("UPDATE promise_reminders SET sending_at = now() WHERE id = :id"), {"id": rid}
    )
    sent: list[dict] = []
    monkeypatch.setattr("twilio_sms.send", lambda **kw: sent.append(kw) or {"sid": "SM-r"})

    assert pf.process_one_reminder(db.engine) is False
    assert sent == []


def test_a_lost_lease_is_marked_not_retried(db_tx, monkeypatch) -> None:
    """The SMS may have gone out. Sending it again is the one thing worse
    than not knowing."""
    import promise_fulfillment as pf

    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    db_tx.execute(text("UPDATE promise_reminders SET status = 'sent' WHERE status IN ('queued','scheduled')"))
    _pid, rid = _reminder(db_tx, monkeypatch, cust)
    db_tx.execute(
        text("UPDATE promise_reminders SET sending_at = now() - interval '1 hour' WHERE id = :id"),
        {"id": rid},
    )
    sent: list[dict] = []
    monkeypatch.setattr("twilio_sms.send", lambda **kw: sent.append(kw) or {"sid": "SM-r"})

    pf.process_one_reminder(db.engine)

    assert sent == []
    row = _reminder_row(db_tx, rid)
    assert row["status"] == "failed"
    assert row["provider_delivery_id"] == "stuck_after_send"


def test_a_policy_refusal_is_a_deferral_not_a_failure(db_tx, monkeypatch) -> None:
    import promise_fulfillment as pf

    cust = _a_customer(db_tx)
    _open_the_gate(db_tx, monkeypatch, cust["id"])
    db_tx.execute(text("UPDATE promise_reminders SET status = 'sent' WHERE status IN ('queued','scheduled')"))
    db_tx.execute(text("UPDATE customers SET dnd = true WHERE id = :id"), {"id": cust["id"]})
    _pid, rid = _reminder(db_tx, monkeypatch, cust)
    sent: list[dict] = []
    monkeypatch.setattr("twilio_sms.send", lambda **kw: sent.append(kw) or {"sid": "SM-r"})

    assert pf.process_one_reminder(db.engine) is True

    assert sent == []
    row = _reminder_row(db_tx, rid)
    assert row["status"] == "scheduled"
    assert row["provider_delivery_id"] == "customer_dnd"
    assert row["scheduled_at"] > datetime.now(timezone.utc) + timedelta(hours=1)


# ---------------------------------------------------------------------------
# Payments: a second settlement is not a replay; a failed cure is reported
# ---------------------------------------------------------------------------


def _intent(conn, cust: dict) -> dict:
    import promise_fulfillment as pf

    return pf.create_pay_intent(
        conn,
        tenant_id=cust["tenant_id"],
        customer_id=cust["id"],
        account_id=cust["account_id"],
        amount=Decimal("250.00"),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        interaction_id=None,
    )


def test_a_second_settlement_with_a_new_reference_is_refused(db_tx) -> None:
    import payments

    cust = _a_customer(db_tx)
    intent = _intent(db_tx, cust)

    first = payments.record_payment(db_tx, intent_id=intent["id"], amount=250, provider_ref="pay_A")
    assert first["status"] == "paid"
    replay = payments.record_payment(db_tx, intent_id=intent["id"], amount=250, provider_ref="pay_A")
    assert replay["idempotent"] is True

    with pytest.raises(ValueError, match="duplicate_settlement"):
        payments.record_payment(db_tx, intent_id=intent["id"], amount=250, provider_ref="pay_B")


def test_a_failed_cure_is_reported_and_the_payment_still_posts(db_tx, monkeypatch) -> None:
    import payment_events as pe
    import payments

    cust = _a_customer(db_tx)
    intent = _intent(db_tx, cust)

    def _boom(conn, **kw):
        conn.execute(text("UPDATE accounts SET dpd = 999 WHERE id = :id"), {"id": cust["account_id"]})
        raise RuntimeError("cure exploded half-way")

    monkeypatch.setattr(pe, "cure_for_account", _boom)

    result = payments.record_payment(db_tx, intent_id=intent["id"], amount=250, provider_ref="pay_C")

    assert result["ok"] is True
    assert result["cureFailed"] is True
    assert result["curedEvents"] == []
    status = db_tx.execute(
        text("SELECT status FROM payment_intents WHERE id = :id"), {"id": intent["id"]}
    ).scalar()
    assert status == "paid"
    # The half-done cure rolled back to its savepoint: the write it made
    # before raising is gone.
    dpd = db_tx.execute(
        text("SELECT dpd FROM accounts WHERE id = :id"), {"id": cust["account_id"]}
    ).scalar()
    assert int(dpd) != 999


def test_an_expired_pay_link_reads_as_expired(db_tx) -> None:
    import payments

    cust = _a_customer(db_tx)
    intent = _intent(db_tx, cust)
    db_tx.execute(
        text("UPDATE payment_intents SET expires_at = now() - interval '1 day' WHERE id = :id"),
        {"id": intent["id"]},
    )

    loaded = payments.load_intent_by_token(db_tx, intent["public_token"])

    assert loaded is not None
    assert loaded["status"] == "expired"
    assert (
        db_tx.execute(
            text("SELECT status FROM payment_intents WHERE id = :id"), {"id": intent["id"]}
        ).scalar()
        == "expired"
    )


# ---------------------------------------------------------------------------
# WhatsApp: an error after the request went out is never a retry
# ---------------------------------------------------------------------------


def test_a_post_send_internal_error_is_dead_lettered(db_tx) -> None:
    import whatsapp_outbound as wo

    cust = _a_customer(db_tx)
    conv = db_inbox._open_whatsapp_conversation(db_tx, cust["id"])
    mid = f"MSG-T-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender, body, delivery_status)
            VALUES (:id, :conv, 'bot', 'hi', 'sending')
            """
        ),
        {"id": mid, "conv": conv},
    )
    jid = f"WAJ-T-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO whatsapp_outbound_jobs
              (id, message_id, conversation_id, customer_id, to_phone, body, status, attempt, post_attempted_at)
            VALUES (:id, :mid, :conv, :cid, :phone, 'hi', 'running', 1, now())
            """
        ),
        {"id": jid, "mid": mid, "conv": conv, "cid": cust["id"], "phone": TEST_PHONE},
    )
    job = {"id": jid, "message_id": mid, "conversation_id": conv, "attempt": 1}

    status = wo.mark_failed_or_retry(db_tx, job, "whatsapp_send_failed:internal:OperationalError")

    assert status == "dead"
    row = db_tx.execute(
        text("SELECT status, error FROM whatsapp_outbound_jobs WHERE id = :id"), {"id": jid}
    ).mappings().first()
    assert row["status"] == "dead"
    assert "ambiguous" in row["error"]


def test_a_pre_send_internal_error_still_retries(db_tx) -> None:
    import whatsapp_outbound as wo

    cust = _a_customer(db_tx)
    conv = db_inbox._open_whatsapp_conversation(db_tx, cust["id"])
    mid = f"MSG-T-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO messages (id, conversation_id, sender, body, delivery_status)
            VALUES (:id, :conv, 'bot', 'hi', 'sending')
            """
        ),
        {"id": mid, "conv": conv},
    )
    jid = f"WAJ-T-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO whatsapp_outbound_jobs
              (id, message_id, conversation_id, customer_id, to_phone, body, status, attempt)
            VALUES (:id, :mid, :conv, :cid, :phone, 'hi', 'running', 1)
            """
        ),
        {"id": jid, "mid": mid, "conv": conv, "cid": cust["id"], "phone": TEST_PHONE},
    )
    job = {"id": jid, "message_id": mid, "conversation_id": conv, "attempt": 1}

    status = wo.mark_failed_or_retry(db_tx, job, "whatsapp_send_failed:internal:OperationalError")

    assert status == "queued"


# ---------------------------------------------------------------------------
# decline_offer: the record decides `ok`
# ---------------------------------------------------------------------------


def test_decline_offer_reports_a_failed_write(monkeypatch) -> None:
    import bot_tools
    import capture

    def _boom(conn, **kw):
        raise RuntimeError("crm down")

    monkeypatch.setattr(capture, "record_offer_declined", _boom)
    ctx = bot_tools.ToolContext(
        job_id="JOB-T",
        conversation_id="CONV-T",
        customer_id="CUST-T",
        interaction_id="INT-T",
        bot_id="kaia-v2-4",
        customer_text="no thanks",
        intent="decline",
    )

    out = bot_tools._tool_decline_offer(ctx, {"reason": "not now"})

    assert out["ok"] is False
    assert out["error"] == "crm_write_failed"
    # The borrower still said no: the in-call latch holds either way.
    assert ctx.offer_declined is True


def test_voice_decline_offer_reports_a_failed_write_too(monkeypatch) -> None:
    """The voice twin of the test above. The voice handler swallowed the
    failed persist and told the model ``ok=True, "do not raise it again"`` --
    so the next call offered it afresh because nothing was written. The
    in-call latch still holds; the record says what happened."""
    import asyncio

    import capture
    from voice import tools as voice_tools
    from voice.session import VoiceSession

    def _boom(conn, **kw):
        raise RuntimeError("crm down")

    monkeypatch.setattr(capture, "record_offer_declined", _boom)
    session = VoiceSession(session_id=f"VS-{uuid.uuid4().hex[:8].upper()}")
    session.customer_id = "CUST-T"
    session.identity_verified = True
    session.interaction_id = "INT-T"
    state, tools = voice_tools.build_tools(
        session,
        bot_id=None,
        start_recording=None,
        nodes={},
        allowed_tool_names=set(voice_tools.CATALOG.specs) | set(voice_tools.ALWAYS_ON),
    )

    result, _next = asyncio.run(tools["decline_offer"].handler({"reason": "not now"}, None))

    assert result["ok"] is False
    assert result["error"] == "crm_write_failed"
    assert state.offer_declined is True
