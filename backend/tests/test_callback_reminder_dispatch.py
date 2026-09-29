"""Callback reminders are delivered by the system, or recorded as not sent.

A reminder used to be a row and a label: the client posted ``sent``, the
callback went to ``reminded``, and nothing ever read ``callback_reminders`` to
deliver one. ``callback_reminders.process_one`` is the drain; these pin that
``sent`` is written only after a provider accepted the message, and that every
other outcome is ``failed`` with the reason on the row.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

import callback_reminders
import compliance_copy
import contact_policy
import db

PHONE = "919000000001"
CONTACTS = {
    "issuer": "Test Bank",
    "officer": {"name": "R Menon", "phone": "18001234567"},
}


def _noon() -> datetime:
    return datetime(2026, 8, 13, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(timezone.utc)


def _due_reminder(conn, monkeypatch: pytest.MonkeyPatch, channel: str) -> dict:
    """A callback two hours out with a reminder due now, and a gate that is open."""
    cust = conn.execute(
        text(
            """
            SELECT c.id, a.id AS account_id FROM customers c
            JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER' AND a.outstanding > 0
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if cust is None:
        pytest.skip("no seeded customer with a balance")
    cid = cust["id"]
    monkeypatch.setenv("CONTACT_DAILY_CAP", "50")
    monkeypatch.setenv("CONTACT_WEEKLY_CAP", "50")
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    # Inside the calling window whatever the wall clock says.
    real_admit = contact_policy.admit
    monkeypatch.setattr(contact_policy, "admit", lambda conn, **kw: real_admit(conn, **{**kw, "now": _noon()}))
    monkeypatch.setattr(compliance_copy, "tenant_contacts", lambda *a, **k: CONTACTS)
    conn.execute(
        text(
            "UPDATE customers SET dnd = false, timezone = 'Asia/Kolkata', preferred_window = NULL, "
            "phone_primary = :p WHERE id = :id"
        ),
        {"id": cid, "p": PHONE},
    )
    conn.execute(
        text("INSERT INTO consent_records (id, customer_id) VALUES (:id, :cid) ON CONFLICT (customer_id) DO NOTHING"),
        {"id": f"CR-{cid}", "cid": cid},
    )
    conn.execute(
        text(
            "UPDATE consent_records SET dnd_registry = false, allowed_days = NULL, allowed_hours = NULL, "
            "expires_at = NULL WHERE customer_id = :id"
        ),
        {"id": cid},
    )
    consent = conn.execute(text("SELECT id FROM consent_records WHERE customer_id = :id"), {"id": cid}).scalar()
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
        {"id": f"{consent}-{channel}", "cr": consent, "ch": channel},
    )
    # Only this test's reminder is due.
    conn.execute(text("UPDATE callback_reminders SET status = 'off' WHERE status IN ('scheduled', 'queued')"))
    tag = uuid.uuid4().hex[:8].upper()
    conn.execute(
        text(
            """
            INSERT INTO callbacks (id, customer_id, account_id, reason, scheduled_at, window_mins, status)
            VALUES (:id, :cid, :aid, 'general', now() + interval '2 hours', 30, 'scheduled')
            """
        ),
        {"id": f"CB-T-{tag}", "cid": cid, "aid": cust["account_id"]},
    )
    # Back-dated: under db_tx, now() is the fixture's start.
    conn.execute(
        text(
            """
            INSERT INTO callback_reminders (id, callback_id, channel, scheduled_at, status)
            VALUES (:id, :cb, :ch, now() - interval '5 minutes', 'scheduled')
            """
        ),
        {"id": f"CBR-T-{tag}", "cb": f"CB-T-{tag}", "ch": channel},
    )
    return {"customer": cid, "callback": f"CB-T-{tag}", "reminder": f"CBR-T-{tag}"}


def _reminder(conn, rid: str) -> dict:
    return dict(
        conn.execute(
            text("SELECT status, sent_at, attempted_at, message_id, failure_reason FROM callback_reminders WHERE id = :id"),
            {"id": rid},
        ).mappings().one()
    )


def _callback_status(conn, cb: str) -> str:
    return conn.execute(text("SELECT status FROM callbacks WHERE id = :id"), {"id": cb}).scalar()


def _sms_carrier(monkeypatch: pytest.MonkeyPatch, send) -> None:
    monkeypatch.setattr("twilio_sms.configured", lambda: True)
    monkeypatch.setattr("twilio_sms.send", send)


def test_a_due_sms_reminder_is_sent_after_its_claim_and_the_callback_is_reminded(db_tx, monkeypatch) -> None:
    ids = _due_reminder(db_tx, monkeypatch, "sms")
    seen: list[dict] = []

    def _send(**kw):
        # The carrier is called with the lease committed, not under the claim.
        seen.append({**kw, "row": _reminder(db_tx, ids["reminder"])})
        return {"sid": "SM-test"}

    _sms_carrier(monkeypatch, _send)

    assert callback_reminders.process_one(db.engine) is True

    assert len(seen) == 1
    assert seen[0]["to_phone"] == PHONE and seen[0]["related_id"] == ids["reminder"]
    assert "Grievance officer: R Menon" in seen[0]["body"]
    assert seen[0]["row"]["status"] == "queued" and seen[0]["row"]["attempted_at"] is not None
    row = _reminder(db_tx, ids["reminder"])
    assert row["status"] == "sent" and row["sent_at"] is not None and row["failure_reason"] is None
    assert _callback_status(db_tx, ids["callback"]) == "reminded"


@pytest.mark.parametrize("accepted", [True, False])
def test_a_whatsapp_reminder_is_sent_only_when_meta_accepts_it(db_tx, monkeypatch, accepted) -> None:
    import whatsapp_outbound

    ids = _due_reminder(db_tx, monkeypatch, "whatsapp")
    tag = ids["reminder"]
    # Inside Meta's 24-hour window: the customer wrote an hour ago.
    db_tx.execute(
        text(
            "INSERT INTO interactions (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel, status) "
            "VALUES (:id, :t, :c, 'bot', (SELECT id FROM bots ORDER BY id LIMIT 1), 'whatsapp', 'active')"
        ),
        {"id": f"IX-{tag}", "t": db.current_tenant(), "c": ids["customer"]},
    )
    db_tx.execute(
        text(
            "INSERT INTO conversations (id, interaction_id, customer_id, status, channel, updated_at) "
            "VALUES (:id, :ix, :c, 'bot', 'whatsapp', now() + interval '1 minute')"
        ),
        {"id": f"CV-{tag}", "ix": f"IX-{tag}", "c": ids["customer"]},
    )
    db_tx.execute(
        text(
            "INSERT INTO messages (id, conversation_id, sender, body, sent_at) "
            "VALUES (:id, :cv, 'customer', 'hi', now() - interval '1 hour')"
        ),
        {"id": f"MSG-IN-{tag}", "cv": f"CV-{tag}"},
    )

    assert callback_reminders.process_one(db.engine) is True

    handed = _reminder(db_tx, ids["reminder"])
    assert handed["status"] == "queued" and handed["message_id"]
    assert _callback_status(db_tx, ids["callback"]) == "scheduled"

    def _meta(**_kw):
        if not accepted:
            raise ValueError("whatsapp_send_failed:400:131047")
        return {"messages": [{"id": "wamid.test"}]}

    monkeypatch.setattr("whatsapp.send_text_message", _meta)
    job = db_tx.execute(
        text("SELECT * FROM whatsapp_outbound_jobs WHERE message_id = :m"), {"m": handed["message_id"]}
    ).mappings().one()
    whatsapp_outbound.handle_job(db.engine, dict(job))

    assert callback_reminders.process_one(db.engine) is True

    row = _reminder(db_tx, ids["reminder"])
    if accepted:
        assert row["status"] == "sent" and row["sent_at"] is not None
        assert _callback_status(db_tx, ids["callback"]) == "reminded"
    else:
        assert row["status"] == "failed" and row["sent_at"] is None
        assert row["failure_reason"] == "whatsapp_send_failed:400:131047"
        assert _callback_status(db_tx, ids["callback"]) == "scheduled"


def test_a_reminder_the_contact_policy_refuses_is_not_sent(db_tx, monkeypatch) -> None:
    ids = _due_reminder(db_tx, monkeypatch, "sms")
    db_tx.execute(text("UPDATE customers SET dnd = true WHERE id = :id"), {"id": ids["customer"]})
    _sms_carrier(monkeypatch, lambda **_kw: pytest.fail("a refused reminder reached the carrier"))

    assert callback_reminders.process_one(db.engine) is True

    row = _reminder(db_tx, ids["reminder"])
    assert row["status"] == "failed" and row["failure_reason"] == "customer_dnd"
    assert row["sent_at"] is None
    assert _callback_status(db_tx, ids["callback"]) == "scheduled"
    ledger = db_tx.execute(
        text("SELECT outcome, reason FROM contact_events WHERE source = 'callback_reminder' AND related_id = :r"),
        {"r": ids["reminder"]},
    ).mappings().one()
    assert dict(ledger) == {"outcome": "denied", "reason": "customer_dnd"}


def test_a_carrier_rejection_is_recorded_without_the_number(db_tx, monkeypatch) -> None:
    from voice.twilio_ops import CarrierRejected

    ids = _due_reminder(db_tx, monkeypatch, "sms")

    def _reject(**_kw):
        raise CarrierRejected(f"21211: the 'To' number +{PHONE} is not valid")

    _sms_carrier(monkeypatch, _reject)

    assert callback_reminders.process_one(db.engine) is True

    row = _reminder(db_tx, ids["reminder"])
    assert row["status"] == "failed" and row["failure_reason"] == "CarrierRejected"
    assert row["sent_at"] is None
    assert _callback_status(db_tx, ids["callback"]) == "scheduled"


def test_a_client_cannot_declare_a_reminder_sent(db_tx, monkeypatch) -> None:
    from pydantic import ValidationError

    from schemas import ReminderCreateRequest

    ids = _due_reminder(db_tx, monkeypatch, "sms")
    with pytest.raises(ValidationError):
        ReminderCreateRequest(channel="sms", status="sent")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid_reminder_status"):
        db.add_callback_reminder(ids["callback"], {"channel": "sms", "status": "sent"})

    queued = db.add_callback_reminder(ids["callback"], {"channel": "sms"})
    assert queued["status"] == "queued"
    assert _reminder(db_tx, queued["id"])["status"] == "scheduled"
    assert _callback_status(db_tx, ids["callback"]) == "scheduled"
