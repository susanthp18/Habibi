"""P1 bounce-to-contact — ingest, statutory pay-link, cure, no night autodial."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

IST = ZoneInfo("Asia/Kolkata")


def _require_events(db_tx) -> None:
    row = db_tx.execute(text("SELECT to_regclass('public.payment_events') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("payment_events missing — apply alembic 20260813_0067")


def _customer_account(db_tx) -> tuple[str, str]:
    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id
            FROM customers c
            JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id
            LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        pytest.skip("no customer+account seeded")
    return row["id"], row["account_id"]


def _prep(db_tx, monkeypatch: pytest.MonkeyPatch) -> tuple[str, str]:
    _require_events(db_tx)
    monkeypatch.setenv("CONTACT_DAILY_CAP", "3")
    monkeypatch.setenv("CONTACT_WEEKLY_CAP", "8")
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    monkeypatch.setenv("BOUNCE_VOICE_ENABLED", "false")
    monkeypatch.setenv("WHATSAPP_BOUNCE_TEMPLATE_NAME", "bounce_notice")
    monkeypatch.setenv("WHATSAPP_BOUNCE_TEMPLATE_LANG", "en_US")
    cid, aid = _customer_account(db_tx)
    db_tx.execute(
        text(
            """
            UPDATE customers
            SET dnd = false, timezone = 'Asia/Kolkata',
                phone_primary = COALESCE(NULLIF(phone_primary, ''), '+919800000001')
            WHERE id = :id
            """
        ),
        {"id": cid},
    )
    db_tx.execute(
        text(
            """
            UPDATE consent_records
            SET dnd_registry = false, allowed_days = NULL, allowed_hours = NULL
            WHERE customer_id = :id
            """
        ),
        {"id": cid},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO consent_records (id, customer_id)
            VALUES (:id, :cid)
            ON CONFLICT (customer_id) DO NOTHING
            """
        ),
        {"id": f"CR-{cid}", "cid": cid},
    )
    cr = db_tx.execute(
        text("SELECT id FROM consent_records WHERE customer_id = :id"),
        {"id": cid},
    ).mappings().first()
    assert cr
    for ch in ("voice", "whatsapp", "sms", "email"):
        db_tx.execute(
            text(
                """
                INSERT INTO channel_consents
                  (id, consent_id, channel, status, weekly_frequency_cap, used_this_week, captured_at)
                VALUES
                  (:id, :cr, :ch, 'opted_in', 8, 0, now())
                ON CONFLICT (consent_id, channel)
                DO UPDATE SET status = 'opted_in', weekly_frequency_cap = 8, captured_at = now()
                """
            ),
            {"id": f"{cr['id']}-{ch}", "cr": cr["id"], "ch": ch},
        )
    return cid, aid


def _opt_out(db_tx, customer_id: str, channels: tuple[str, ...]) -> None:
    db_tx.execute(
        text(
            """
            UPDATE channel_consents cc
            SET status = 'opted_out', captured_at = now()
            FROM consent_records cr
            WHERE cc.consent_id = cr.id
              AND cr.customer_id = :cid
              AND cc.channel = ANY(:channels)
            """
        ),
        {"cid": customer_id, "channels": list(channels)},
    )


def _seed_emi(db_tx, account_id: str, *, amount: float = 1500.0, due: datetime | None = None) -> str:
    emi_id = f"EMI-T-{uuid.uuid4().hex[:10].upper()}"
    due = due or datetime(2026, 8, 12, 0, 0, tzinfo=IST)
    db_tx.execute(
        text(
            """
            INSERT INTO emi_installments (
              id, account_id, installment_index, due_date, amount, status
            ) VALUES (
              :id, :aid, :idx, :due, :amount, 'upcoming'
            )
            """
        ),
        {
            "id": emi_id,
            "aid": account_id,
            "idx": int(uuid.uuid4().int % 10_000_000),
            "due": due,
            "amount": amount,
        },
    )
    return emi_id


def _ingest(db_tx, account_id: str, *, now: datetime, **extra):
    import payment_events as pe

    payload = {
        "accountId": account_id,
        "source": extra.pop("source", "sandbox"),
        "sourceRef": extra.pop("sourceRef", f"NACH-{uuid.uuid4().hex}"),
        "amount": extra.pop("amount", 1500.0),
        "reason": extra.pop("reason", "insufficient_funds"),
        "occurredAt": extra.pop("occurredAt", now.isoformat()),
        **extra,
    }
    return pe.ingest(db_tx, payload, now=now), payload["sourceRef"] if "sourceRef" not in extra else payload


def test_midnight_ingest_opens_case_and_sends_digital(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, aid = _prep(db_tx, monkeypatch)
    emi_id = _seed_emi(db_tx, aid)
    now = datetime(2026, 8, 13, 0, 12, tzinfo=IST)
    out, _ref = _ingest(db_tx, aid, now=now, emiId=emi_id)
    assert out["ok"] and not out["idempotent"]
    event = db_tx.execute(
        text("SELECT * FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event is not None
    assert event["status"] == "in_progress"
    assert event["first_touch_channel"] in {"whatsapp", "sms"}
    assert event["first_touch_at"] is not None
    assert event["next_voice_at"] is None
    emi = db_tx.execute(
        text("SELECT status FROM emi_installments WHERE id = :id"),
        {"id": emi_id},
    ).mappings().first()
    assert emi["status"] == "overdue"
    dpd = db_tx.execute(text("SELECT dpd FROM accounts WHERE id = :id"), {"id": aid}).scalar()
    assert int(dpd) >= 1
    wi = db_tx.execute(
        text("SELECT 1 FROM work_items WHERE entity_type = 'bounce' AND entity_id = :id"),
        {"id": out["eventId"]},
    ).fetchone()
    assert wi is not None
    n_voice = db_tx.execute(
        text(
            """
            SELECT count(*) FROM contact_events
            WHERE customer_id = :cid AND channel = 'voice' AND source = 'bounce_voice'
            """
        ),
        {"cid": cid},
    ).scalar()
    assert int(n_voice) == 0


def test_duplicate_source_ref_idempotent(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _cid, aid = _prep(db_tx, monkeypatch)
    emi_id = _seed_emi(db_tx, aid)
    now = datetime(2026, 8, 13, 10, 0, tzinfo=IST)
    ref = f"NACH-{uuid.uuid4().hex}"
    first, _ = _ingest(db_tx, aid, now=now, emiId=emi_id, sourceRef=ref)
    second, _ = _ingest(db_tx, aid, now=now, emiId=emi_id, sourceRef=ref)
    assert first["eventId"] == second["eventId"]
    assert second["idempotent"] is True
    n = db_tx.execute(
        text("SELECT count(*) FROM payment_events WHERE account_id = :aid AND source_ref = :ref"),
        {"aid": aid, "ref": ref},
    ).scalar()
    assert int(n) == 1
    intents = db_tx.execute(
        text("SELECT count(*) FROM payment_intents WHERE payment_event_id = :id"),
        {"id": first["eventId"]},
    ).scalar()
    assert int(intents) == 1


def test_whatsapp_opt_out_falls_to_sms(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, aid = _prep(db_tx, monkeypatch)
    _opt_out(db_tx, cid, ("whatsapp",))
    sent: list[dict] = []
    monkeypatch.setattr("twilio_sms.configured", lambda: True)
    monkeypatch.setattr("twilio_sms.send", lambda **kw: sent.append(kw) or {"sid": "SM-test"})
    emi_id = _seed_emi(db_tx, aid)
    now = datetime(2026, 8, 13, 10, 0, tzinfo=IST)
    out, _ = _ingest(db_tx, aid, now=now, emiId=emi_id)
    event = db_tx.execute(
        text("SELECT first_touch_channel FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["first_touch_channel"] == "sms"
    assert sent
    reasons = [
        r[0]
        for r in db_tx.execute(
            text(
                """
                SELECT channel FROM contact_events
                WHERE customer_id = :cid AND source = 'bounce_notice'
                ORDER BY occurred_at, id
                """
            ),
            {"cid": cid},
        ).fetchall()
    ]
    assert "whatsapp" in reasons and "sms" in reasons


def test_both_digital_blocked_no_voice_when_disabled(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, aid = _prep(db_tx, monkeypatch)
    _opt_out(db_tx, cid, ("whatsapp", "sms"))
    monkeypatch.setenv("BOUNCE_VOICE_ENABLED", "false")
    emi_id = _seed_emi(db_tx, aid)
    now = datetime(2026, 8, 13, 10, 0, tzinfo=IST)
    out, _ = _ingest(db_tx, aid, now=now, emiId=emi_id)
    event = db_tx.execute(
        text("SELECT * FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["status"] == "open"
    assert event["first_touch_at"] is None
    assert event["suppression_reason"]
    assert event["next_voice_at"] is None
    n_voice = db_tx.execute(
        text(
            """
            SELECT count(*) FROM contact_events
            WHERE customer_id = :cid AND source = 'bounce_voice'
            """
        ),
        {"cid": cid},
    ).scalar()
    assert int(n_voice) == 0


def test_voice_last_resort_inside_hours(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, aid = _prep(db_tx, monkeypatch)
    _opt_out(db_tx, cid, ("whatsapp", "sms"))
    monkeypatch.setenv("BOUNCE_VOICE_ENABLED", "true")
    calls: list[str] = []
    monkeypatch.setattr(
        "voice.twilio_ops.start_outbound_call",
        lambda *, to, custom=None: calls.append(to) or {"callSid": "CA-t", "to": to, "status": "queued"},
    )
    emi_id = _seed_emi(db_tx, aid)
    now = datetime(2026, 8, 13, 10, 0, tzinfo=IST)
    out, _ = _ingest(db_tx, aid, now=now, emiId=emi_id)
    event = db_tx.execute(
        text("SELECT * FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["first_touch_channel"] == "voice"
    assert calls


def test_voice_last_resort_night_schedules_then_worker_fires(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid, aid = _prep(db_tx, monkeypatch)
    _opt_out(db_tx, cid, ("whatsapp", "sms"))
    monkeypatch.setenv("BOUNCE_VOICE_ENABLED", "true")
    calls: list[str] = []
    monkeypatch.setattr(
        "voice.twilio_ops.start_outbound_call",
        lambda *, to, custom=None: calls.append(to) or {"callSid": "CA-t", "to": to, "status": "queued"},
    )
    emi_id = _seed_emi(db_tx, aid)
    now = datetime(2026, 8, 13, 0, 12, tzinfo=IST)
    out, _ = _ingest(db_tx, aid, now=now, emiId=emi_id)
    event = db_tx.execute(
        text("SELECT * FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["first_touch_at"] is None
    assert event["next_voice_at"] is not None
    nxt = event["next_voice_at"]
    if getattr(nxt, "tzinfo", None) is None:
        from datetime import timezone as tz

        nxt = nxt.replace(tzinfo=tz.utc)
    assert nxt.astimezone(IST).hour == 8
    assert not calls

    db_tx.execute(
        text("UPDATE payment_events SET next_voice_at = now() - interval '1 minute' WHERE id = :id"),
        {"id": out["eventId"]},
    )
    import db as dbmod
    import payment_events as pe

    assert pe.process_one_voice(dbmod.engine) is True
    event = db_tx.execute(
        text("SELECT first_touch_channel FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["first_touch_channel"] == "voice"
    assert calls


def test_statutory_bounce_sends_after_daily_cap(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid, aid = _prep(db_tx, monkeypatch)
    import contact_policy

    noon = datetime(2026, 8, 13, 10, 0, tzinfo=IST)
    for i in range(3):
        d = contact_policy.admit(
            db_tx,
            customer_id=cid,
            channel="whatsapp",
            purpose="outreach",
            session_key=f"cap-{i}",
            source="test",
            related_id=f"cap-{i}",
            now=noon,
        )
        assert d.allowed
    blocked = contact_policy.admit(
        db_tx,
        customer_id=cid,
        channel="whatsapp",
        purpose="outreach",
        session_key="cap-3",
        source="test",
        related_id="cap-3",
        now=noon,
    )
    assert not blocked.allowed
    emi_id = _seed_emi(db_tx, aid)
    out, _ = _ingest(db_tx, aid, now=noon, emiId=emi_id)
    event = db_tx.execute(
        text("SELECT status, first_touch_channel FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["status"] == "in_progress"
    assert event["first_touch_channel"] in {"whatsapp", "sms"}


def test_record_payment_cures_bounce(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _cid, aid = _prep(db_tx, monkeypatch)
    emi_id = _seed_emi(db_tx, aid, amount=1500.0)
    now = datetime(2026, 8, 13, 10, 0, tzinfo=IST)
    out, _ = _ingest(db_tx, aid, now=now, emiId=emi_id, amount=1500.0)
    import payments

    paid = payments.record_payment(
        db_tx,
        intent_id=out["intentId"],
        amount=Decimal("1500"),
        provider_ref="test-bounce-cure",
    )
    assert paid["ok"]
    event = db_tx.execute(
        text("SELECT status FROM payment_events WHERE id = :id"),
        {"id": out["eventId"]},
    ).mappings().first()
    assert event["status"] == "cured"
    emi = db_tx.execute(
        text("SELECT status FROM emi_installments WHERE id = :id"),
        {"id": emi_id},
    ).mappings().first()
    assert emi["status"] == "paid"
    wi = db_tx.execute(
        text("SELECT 1 FROM work_items WHERE entity_type = 'bounce' AND entity_id = :id"),
        {"id": out["eventId"]},
    ).fetchone()
    assert wi is None


def test_missing_account_raises(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    _prep(db_tx, monkeypatch)
    import payment_events as pe

    before = db_tx.execute(text("SELECT count(*) FROM payment_events")).scalar()
    with pytest.raises(ValueError, match="account_required"):
        pe.ingest(
            db_tx,
            {
                "accountId": "AC-DOES-NOT-EXIST",
                "source": "sandbox",
                "sourceRef": f"NACH-{uuid.uuid4().hex}",
                "amount": 100,
            },
            now=datetime(2026, 8, 13, 10, 0, tzinfo=IST),
        )
    after = db_tx.execute(text("SELECT count(*) FROM payment_events")).scalar()
    assert int(after) == int(before)
