"""Cross-channel contact policy — fail-closed cap, statutory still sends."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> datetime.date:
    return datetime.now(IST).date()


def _noon(day: datetime.date | None = None) -> datetime:
    d = day or _today_ist()
    return datetime(d.year, d.month, d.day, 10, 0, tzinfo=IST)


def _require_ledger(db_tx) -> None:
    row = db_tx.execute(text("SELECT to_regclass('public.contact_events') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("contact_events missing — apply alembic 20260813_0066")


def _customer(db_tx) -> str:
    row = db_tx.execute(
        text(
            """
            SELECT id FROM customers
            WHERE id <> 'UNKNOWN-CALLER'
            ORDER BY id
            LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        pytest.skip("no customers seeded")
    return row["id"]


def _prep(db_tx, monkeypatch: pytest.MonkeyPatch) -> str:
    _require_ledger(db_tx)
    monkeypatch.setenv("CONTACT_DAILY_CAP", "3")
    monkeypatch.setenv("CONTACT_WEEKLY_CAP", "8")
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    monkeypatch.setenv("CONTACT_SESSION_WINDOW_MINUTES", "30")
    cid = _customer(db_tx)
    db_tx.execute(
        text(
            """
            UPDATE customers
            SET dnd = false, timezone = 'Asia/Kolkata'
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
    for ch in ("voice", "whatsapp", "sms", "email"):
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
    return cid


def _admit(db_tx, cid: str, **kwargs):
    import contact_policy

    noon = kwargs.pop("now", _noon())
    return contact_policy.admit(
        db_tx,
        customer_id=cid,
        channel=kwargs.get("channel", "whatsapp"),
        purpose=kwargs.get("purpose", "outreach"),
        session_key=kwargs.get("session_key"),
        source=kwargs.get("source", "test"),
        related_id=kwargs.get("related_id"),
        actor_kind="system",
        now=noon,
    )


def test_fourth_outreach_denied(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    allowed = []
    for i in range(4):
        d = _admit(db_tx, cid, session_key=f"s{i}", related_id=f"r{i}")
        allowed.append(d.allowed)
    assert allowed[:3] == [True, True, True]
    assert allowed[3] is False
    assert _admit(db_tx, cid, session_key="s3", related_id="r3").reason == "daily_cap"
    n = db_tx.execute(
        text("SELECT outreach_sessions FROM contact_day_counters WHERE customer_id = :id"),
        {"id": cid},
    ).scalar()
    assert int(n) == 3


def test_statutory_still_sends_after_cap(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    for i in range(3):
        assert _admit(db_tx, cid, session_key=f"o{i}", related_id=f"o{i}").allowed
    blocked = _admit(db_tx, cid, session_key="o3", related_id="o3")
    assert not blocked.allowed
    statutory = _admit(
        db_tx,
        cid,
        purpose="statutory",
        session_key="ptp-1",
        related_id="intent-1",
        source="ptp_confirm",
    )
    assert statutory.allowed
    later = _admit(db_tx, cid, session_key="o4", related_id="o4")
    assert not later.allowed


def test_voice_hours(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    ok = _admit(
        db_tx,
        cid,
        channel="voice",
        session_key="v1",
        related_id="v1",
        now=datetime(_today_ist().year, _today_ist().month, _today_ist().day, 10, 0, tzinfo=IST),
    )
    assert ok.allowed
    late = _admit(
        db_tx,
        cid,
        channel="voice",
        session_key="v2",
        related_id="v2",
        now=datetime(_today_ist().year, _today_ist().month, _today_ist().day, 19, 1, tzinfo=IST),
    )
    assert not late.allowed
    assert late.reason == "outside_calling_hours"
    early = _admit(
        db_tx,
        cid,
        channel="voice",
        session_key="v3",
        related_id="v3",
        now=datetime(_today_ist().year, _today_ist().month, _today_ist().day, 7, 59, tzinfo=IST),
    )
    assert not early.allowed


def test_whatsapp_opt_out_statutory_falls_to_sms(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    db_tx.execute(
        text(
            """
            UPDATE channel_consents cc
            SET status = 'opted_out'
            FROM consent_records cr
            WHERE cc.consent_id = cr.id AND cr.customer_id = :id AND cc.channel = 'whatsapp'
            """
        ),
        {"id": cid},
    )
    wa = _admit(
        db_tx,
        cid,
        channel="whatsapp",
        purpose="statutory",
        session_key="ptp",
        related_id="wa",
        source="ptp_confirm",
    )
    assert not wa.allowed
    assert wa.reason == "channel_opted_out"
    sms = _admit(
        db_tx,
        cid,
        channel="sms",
        purpose="statutory",
        session_key="ptp",
        related_id="sms",
        source="ptp_confirm",
    )
    assert sms.allowed


def test_session_coalesce_one_touch(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    a = _admit(db_tx, cid, session_key="thread-1", related_id="m1")
    b = _admit(db_tx, cid, session_key="thread-1", related_id="m2")
    c = _admit(db_tx, cid, session_key="thread-1", related_id="m3")
    assert a.allowed and b.allowed and c.allowed
    assert a.touch_counted is True
    assert b.touch_counted is False
    assert c.coalesced or not c.touch_counted
    n = db_tx.execute(
        text("SELECT outreach_sessions FROM contact_day_counters WHERE customer_id = :id"),
        {"id": cid},
    ).scalar()
    assert int(n) == 1


def test_outbound_without_customer_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTACT_DAILY_CAP", "3")
    import contact_policy

    d = contact_policy.evaluate(
        None,
        customer_id=None,
        channel="voice",
        purpose="outreach",
    )
    assert not d.allowed
    assert d.reason == "no_customer"


def test_used_this_week_matches_ledger(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    assert _admit(db_tx, cid, channel="sms", session_key="u1", related_id="u1").touch_counted
    import db as dbmod

    rows = dbmod.list_consent()
    rec = next((r for r in rows if r["customerId"] == cid), None)
    assert rec is not None
    sms = next(c for c in rec["channels"] if c["channel"] == "sms")
    assert sms["usedThisWeek"] >= 1
    assert rec["outreachToday"] >= 1
    assert rec["dailyCap"] == 3


def test_due_reminder_blocked_when_capped(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    for i in range(3):
        assert _admit(db_tx, cid, session_key=f"d{i}", related_id=f"d{i}").allowed
    acct = db_tx.execute(
        text("SELECT id FROM accounts WHERE customer_id = :id LIMIT 1"),
        {"id": cid},
    ).scalar()
    if not acct:
        pytest.skip("no account")
    row = db_tx.execute(text("SELECT to_regclass('public.payment_intents') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("payment_intents missing")
    from agent_core.tools import create_promise_to_pay
    import promise_fulfillment

    result = create_promise_to_pay(
        customer_id=cid,
        amount=50.0,
        promised_date="2026-09-01",
        account_id=acct,
        channel="voice",
        idempotency_key="ptp-cap-reminder",
    )
    assert result.ok
    pid = result.data["promiseId"]
    existing = db_tx.execute(
        text(
            """
            SELECT id FROM promise_reminders
            WHERE promise_id = :pid AND kind = 'due'
            LIMIT 1
            """
        ),
        {"pid": pid},
    ).mappings().first()
    rid = existing["id"] if existing else "PRM-DUE-CAP"
    if not existing:
        db_tx.execute(
            text(
                """
                INSERT INTO promise_reminders (id, promise_id, channel, kind, scheduled_at, status)
                VALUES (:id, :pid, 'sms', 'due', now(), 'queued')
                """
            ),
            {"id": rid, "pid": pid},
        )
    else:
        db_tx.execute(
            text("UPDATE promise_reminders SET channel = 'sms', status = 'queued', scheduled_at = now() WHERE id = :id"),
            {"id": rid},
        )
    ok, err = promise_fulfillment._send_reminder_copy(
        db_tx,
        {"id": rid, "promise_id": pid, "channel": "sms", "kind": "due"},
    )
    assert ok is False
    assert err == "daily_cap"
