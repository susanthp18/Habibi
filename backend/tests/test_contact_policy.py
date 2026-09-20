"""Cross-channel contact policy — fail-closed cap, statutory still sends."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent_core import clock
import db
import pytest
from sqlalchemy import text

IST = ZoneInfo("Asia/Kolkata")


def _today_ist() -> datetime.date:
    """A day inside the seeded Mon–Sat consent window.

    Sunday must not be why outreach is refused once ``_prep`` stops nulling
    ``allowed_days``. Roll back one day rather than invent a calendar.
    """
    d = clock.today_local()
    if d.isoweekday() == 7:
        return d - timedelta(days=1)
    return d


def _noon(day: datetime.date | None = None) -> datetime:
    """Inside the seeded 11:00–18:00 window of the first customer by id."""
    d = day or _today_ist()
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=IST)


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


def _prep(
    db_tx, monkeypatch: pytest.MonkeyPatch, *, cid: str | None = None
) -> str:
    _require_ledger(db_tx)
    monkeypatch.setenv("CONTACT_DAILY_CAP", "3")
    monkeypatch.setenv("CONTACT_WEEKLY_CAP", "8")
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "0")
    monkeypatch.setenv("CONTACT_SESSION_WINDOW_MINUTES", "30")
    if cid is None:
        cid = f"CU-CP-{uuid4().hex[:10].upper()}"
        db_tx.execute(
            text(
                """
                INSERT INTO customers (id, tenant_id, name, risk, timezone)
                VALUES (:id, :t, 'contact-policy', 'low', 'Asia/Kolkata')
                """
            ),
            {"id": cid, "t": db.current_tenant()},
        )
    else:
        db_tx.execute(
            text("UPDATE customers SET timezone = 'Asia/Kolkata' WHERE id = :id"),
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
                ON CONFLICT (consent_id, channel, purpose)
                DO UPDATE SET status = 'opted_in', weekly_frequency_cap = 8,
                              used_this_week = 0, captured_at = now()
                """
            ),
            {"id": f"{cr['id']}-{ch}", "cr": cr["id"], "ch": ch},
        )
    # Published tenant rules may only lower the env cap. Seeded books often
    # ship daily_cap=1, which would make CONTACT_DAILY_CAP=3 unreachable.
    # DELETE is a no-op under RLS / a different kind spelling; the accessors
    # are what admit() actually reads.
    db_tx.execute(
        text("DELETE FROM policy_rules WHERE kind IN ('daily_cap', 'weekly_cap')")
    )
    import policy_rules

    monkeypatch.setattr(policy_rules.RuleSet, "daily_cap", lambda self: None)
    monkeypatch.setattr(
        policy_rules.RuleSet, "weekly_cap", lambda self, channel=None: None
    )
    policy_rules.reset_cache()
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
        now=_noon(),
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


def test_opt_out_writer_is_what_admit_enforces(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Capture and enforcement have to meet in one process.

    Every other opted-out borrower in this file is fabricated by raw SQL, so a
    writer that stored the wrong channel, purpose or consent id would leave the
    suite green. The operator payload says ``call``; the dialler asks for
    ``voice``. Those have to be the same row.
    """
    import db as dbmod

    cid = _prep(db_tx, monkeypatch)
    dbmod.opt_out(cid, {"channel": "call", "source": "Agent", "note": "seam test"})

    voice = _admit(db_tx, cid, channel="voice", session_key="oo-v", related_id="oo-v")
    assert voice.allowed is False
    assert voice.reason == "channel_opted_out"

    # A call-only opt-out must not close WhatsApp. Writing ``all``, or writing
    # the voice row under purpose ``promotional`` only, would make this fail.
    whatsapp = _admit(
        db_tx, cid, channel="whatsapp", session_key="oo-wa", related_id="oo-wa"
    )
    assert whatsapp.allowed is True


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
    # `_admit` stamps `_today_ist()` (Sunday rolls back). The consent list
    # reads wall-clock today, so outreachToday is a different counter on Sunday.
    if clock.today_local().isoweekday() != 7:
        assert rec["outreachToday"] >= 1
    assert rec["dailyCap"] == 3


def test_due_reminder_blocked_when_capped(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    # The reminder send uses wall-clock now, not `_noon()`. Opening the window
    # here keeps this test about the cap; the window branch is pinned elsewhere.
    db_tx.execute(
        text(
            """
            UPDATE consent_records
            SET allowed_hours = '00:00-24:00 IST', allowed_days = 'Sun-Sat'
            WHERE customer_id = :id
            """
        ),
        {"id": cid},
    )
    db_tx.execute(
        text("UPDATE customers SET preferred_window = '00:00-24:00 IST' WHERE id = :id"),
        {"id": cid},
    )
    for i in range(3):
        assert _admit(db_tx, cid, session_key=f"d{i}", related_id=f"d{i}").allowed
    # One open promise per account: an account that already carries one
    # refuses a second (promise_already_open), which is not what this tests.
    acct = db_tx.execute(
        text(
            """
            SELECT a.id FROM accounts a
             WHERE a.customer_id = :id
               AND NOT EXISTS (
                 SELECT 1 FROM promises p
                  WHERE p.account_id = a.id AND p.status IN ('upcoming', 'due_today')
               )
             LIMIT 1
            """
        ),
        {"id": cid},
    ).scalar()
    if not acct:
        pytest.skip("no account without an open promise")
    row = db_tx.execute(text("SELECT to_regclass('public.payment_intents') AS t")).mappings().first()
    if not row or not row["t"]:
        pytest.skip("payment_intents missing")
    from agent_core.tools import create_promise_to_pay
    import promise_fulfillment

    result = create_promise_to_pay(
        customer_id=cid,
        amount=50.0,
        promised_date=(clock.today_local() + timedelta(days=5)).isoformat(),
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
    prepared = promise_fulfillment._prepare_reminder(
        db_tx,
        {"id": rid, "promise_id": pid, "channel": "sms", "kind": "due"},
        now=_noon(),
    )
    assert prepared["outcome"] == "refused"
    assert prepared["reason"] == "daily_cap"


def test_a_day_range_parses_whatever_dash_it_was_typed_with():
    """`Mon–Sat` and `Mon-Sat` are the same consent, and must parse the same.

    The hours parser skips its separator with `.*?`, so this database already
    holds both `10:00-19:00 IST` and `10:00–19:00 IST` in allowed_hours and
    nobody noticed. The day parser split on an ASCII hyphen, so an en-dashed
    range missed the range branch entirely, fell through to the token split,
    matched the leading `mon` and returned Monday alone.

    That fails closed — a customer who consented to six days is contacted on
    one — so it raises nothing and shows up only as a queue that never drains.
    """
    import contact_policy

    ascii_range = contact_policy.parse_allowed_days("Mon-Sat")
    assert ascii_range == [1, 2, 3, 4, 5, 6]
    for dash in ("–", "—"):  # en dash, em dash
        assert contact_policy.parse_allowed_days(f"Mon{dash}Sat") == ascii_range

    # A wrapping range and a comma list must not regress with the substitution.
    assert contact_policy.parse_allowed_days("Fri–Mon") == [5, 6, 0, 1]
    assert contact_policy.parse_allowed_days("Mon, Wed, Fri") == [1, 3, 5]


def _boom_load_customer(_conn, _customer_id):
    raise RuntimeError("consent table is on fire")


@pytest.mark.parametrize("purpose", ("outreach", "statutory", "in_session"))
def test_evaluate_fails_closed_when_consent_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, purpose: str
) -> None:
    """A consent-table read error is a refusal, for every purpose.

    The previous branch admitted non-outreach sends when the database blipped,
    contradicting this module's fail-closed contract. An in-flight WhatsApp
    thread is not permission to skip the gate.
    """
    import contact_policy

    monkeypatch.setattr(contact_policy, "_load_customer", _boom_load_customer)
    d = contact_policy.evaluate(
        None,
        customer_id="CUST-UNREADABLE",
        channel="whatsapp",
        purpose=purpose,
    )
    assert d.allowed is False
    assert d.reason == contact_policy.REASON_UNREADABLE


@pytest.mark.parametrize("purpose", ("outreach", "statutory", "in_session"))
def test_admit_fails_closed_when_consent_is_unreadable(
    db_tx, monkeypatch: pytest.MonkeyPatch, purpose: str
) -> None:
    """Fault-inject `_load_customer`: the send is refused and the ledger is quiet.

    `in_session` is the WhatsApp-reply path (`bot_runtime` / `whatsapp_outbound`).
    `admit` still swallows the exception — it never raises — so the caller's
    own `except` stays unreachable; the refusal is the `Decision`.
    """
    cid = _prep(db_tx, monkeypatch)
    import contact_policy

    monkeypatch.setattr(contact_policy, "_load_customer", _boom_load_customer)
    before = db_tx.execute(
        text("SELECT count(*) FROM contact_events WHERE customer_id = :id"),
        {"id": cid},
    ).scalar()
    d = _admit(
        db_tx,
        cid,
        channel="whatsapp",
        purpose=purpose,
        session_key="wa-reply",
        related_id="msg-unreadable",
        source="bot_reply",
    )
    assert d.allowed is False
    assert d.reason == contact_policy.REASON_UNREADABLE
    after = db_tx.execute(
        text("SELECT count(*) FROM contact_events WHERE customer_id = :id"),
        {"id": cid},
    ).scalar()
    assert int(after or 0) == int(before or 0)


def test_repeat_dial_increments_the_frequency_ledger(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two operator dials ten seconds apart are two counted touches.

    Session coalescing is for a conversation thread (one session_key, many
    messages). A reserved attempt is not a thread. Each "Call now" click
    reserves a fresh attempt id and must consume its own cap slot — otherwise
    the daily cap of 3 records one ring for a thirty-minute burst.
    """
    cid = _prep(db_tx, monkeypatch)
    first_at = _noon()
    first = _admit(
        db_tx,
        cid,
        channel="voice",
        session_key="CA-1",
        related_id="CA-1",
        source="voice_outbound",
        now=first_at,
    )
    second = _admit(
        db_tx,
        cid,
        channel="voice",
        session_key="CA-2",
        related_id="CA-2",
        source="voice_outbound",
        now=first_at + timedelta(seconds=10),
    )
    assert first.allowed and second.allowed
    assert first.touch_counted and second.touch_counted
    counted = db_tx.execute(
        text(
            """
            SELECT count(*) FROM contact_events
            WHERE customer_id = :id AND outcome = 'allowed' AND touch_counted
              AND related_id IN ('CA-1', 'CA-2')
            """
        ),
        {"id": cid},
    ).scalar()
    assert int(counted) == 2
    third = _admit(
        db_tx,
        cid,
        channel="voice",
        session_key="CA-3",
        related_id="CA-3",
        source="voice_outbound",
        now=first_at + timedelta(seconds=20),
    )
    fourth = _admit(
        db_tx,
        cid,
        channel="voice",
        session_key="CA-4",
        related_id="CA-4",
        source="voice_outbound",
        now=first_at + timedelta(seconds=30),
    )
    assert third.allowed and third.touch_counted
    assert not fourth.allowed
    assert fourth.reason == "daily_cap"


def test_dial_endpoints_key_the_attempt_not_the_customer() -> None:
    """The two HTTP dial paths must not pass customer_id as session_key.

    Cadence and campaigns already key the attempt. The endpoints used the
    borrower, which is what turned coalescing into a cap bypass.
    """
    import inspect

    from routers import telephony as telephony_routes

    from routers import outbound as outbound_routes

    import db_outbound

    # Neither handler owns a transaction: the gates live in persistence.
    for fn in (
        telephony_routes.twilio_voice_outbound,
        outbound_routes.demo_outbound_call,
        db_outbound.reserve_operator_attempt,
        db_outbound.reserve_demo_attempt,
    ):
        src = inspect.getsource(fn)
        assert "session_key=customer_id" not in src
        assert "contact_policy.admit(" not in src
    # The session key is the attempt's own, set inside `outbound.gate` —
    # the endpoints no longer compose the gate by hand at all.
    for fn in (db_outbound.reserve_operator_attempt, db_outbound.reserve_demo_attempt):
        assert "outbound.gate(" in inspect.getsource(fn)


def _consent_columns(db_tx, cid: str) -> dict:
    row = db_tx.execute(
        text(
            """
            SELECT c.dnd, c.preferred_window, cr.dnd_registry, cr.allowed_days, cr.allowed_hours
            FROM customers c
            LEFT JOIN consent_records cr ON cr.customer_id = c.id
            WHERE c.id = :id
            """
        ),
        {"id": cid},
    ).mappings().first()
    assert row is not None
    return dict(row)


def _set_channel_status(db_tx, cid: str, channel: str, status: str) -> None:
    db_tx.execute(
        text(
            """
            UPDATE channel_consents cc
            SET status = :status
            FROM consent_records cr
            WHERE cc.consent_id = cr.id AND cr.customer_id = :id AND cc.channel = :ch
            """
        ),
        {"id": cid, "ch": channel, "status": status},
    )


def test_prep_does_not_null_dnd_or_window_columns(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fixture used to wipe the columns the rest of this file is testing."""
    cid = _customer(db_tx)
    before = _consent_columns(db_tx, cid)
    prepared = _prep(db_tx, monkeypatch, cid=cid)
    assert prepared == cid
    assert _consent_columns(db_tx, cid) == before


def test_a_dnd_borrower_is_refused(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    db_tx.execute(text("UPDATE customers SET dnd = true WHERE id = :id"), {"id": cid})
    d = _admit(db_tx, cid, session_key="dnd", related_id="dnd")
    assert d.allowed is False
    assert d.reason == "customer_dnd"


def test_a_channel_on_dnd_is_refused(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    _set_channel_status(db_tx, cid, "whatsapp", "dnd")
    d = _admit(db_tx, cid, session_key="ch-dnd", related_id="ch-dnd")
    assert d.allowed is False
    assert d.reason == "channel_dnd"


def test_expired_channel_consent_is_refused(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _prep(db_tx, monkeypatch)
    _set_channel_status(db_tx, cid, "whatsapp", "expired")
    d = _admit(db_tx, cid, session_key="expired", related_id="expired")
    assert d.allowed is False
    assert d.reason == "channel_expired"


def test_outreach_outside_the_allowed_window_is_refused(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _prep(db_tx, monkeypatch)
    db_tx.execute(
        text(
            "UPDATE consent_records SET allowed_hours = '11:00-18:00 IST' WHERE customer_id = :id"
        ),
        {"id": cid},
    )
    db_tx.execute(
        text("UPDATE customers SET preferred_window = '11:00-18:00 IST' WHERE id = :id"),
        {"id": cid},
    )
    d = _admit(
        db_tx,
        cid,
        session_key="win",
        related_id="win",
        now=_noon().replace(hour=10),
    )
    assert d.allowed is False
    assert d.reason == "outside_allowed_window"


def test_a_second_touch_inside_cooling_off_is_refused(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _prep(db_tx, monkeypatch)
    monkeypatch.setenv("CONTACT_COOLING_OFF_MINUTES", "120")
    first = _admit(db_tx, cid, session_key="cool-1", related_id="cool-1")
    assert first.allowed
    second = _admit(db_tx, cid, session_key="cool-2", related_id="cool-2")
    assert second.allowed is False
    assert second.reason == "cooling_off"


def test_the_weekly_cap_fires_before_the_daily_cap(
    db_tx, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_prep`` used to set weekly=8 against daily=3, so this branch never ran."""
    cid = _prep(db_tx, monkeypatch)
    db_tx.execute(
        text(
            """
            UPDATE channel_consents cc
            SET weekly_frequency_cap = 1
            FROM consent_records cr
            WHERE cc.consent_id = cr.id AND cr.customer_id = :id AND cc.channel = 'whatsapp'
            """
        ),
        {"id": cid},
    )
    first = _admit(db_tx, cid, session_key="wk-1", related_id="wk-1")
    assert first.allowed
    second = _admit(db_tx, cid, session_key="wk-2", related_id="wk-2")
    assert second.allowed is False
    assert second.reason == "weekly_cap"


def test_a_settled_borrower_is_refused_outreach(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    import contact_policy

    """WS8: no paid/settled refusal existed, so cadence kept dialling a
    cured borrower to exhaustion. Outreach is refused `settled`; a statutory
    notice still goes."""
    cid = _prep(db_tx, monkeypatch, cid=_customer(db_tx))
    db_tx.execute(text("UPDATE accounts SET outstanding = 0 WHERE customer_id = :id"), {"id": cid})
    refused = _admit(db_tx, cid, session_key="settled-1", related_id="settled-1")
    assert refused.allowed is False
    assert refused.reason == contact_policy.REASON_SETTLED
    notice = _admit(db_tx, cid, channel="sms", purpose="statutory", session_key="s-1", related_id="s-1")
    assert notice.reason != contact_policy.REASON_SETTLED


def test_a_lead_with_no_accounts_is_not_settled(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    import contact_policy

    cid = _prep(db_tx, monkeypatch)
    # A sweep claim from an earlier test (or the dev stack's own treatment
    # sweep) still references this borrower's accounts; the claim is not what
    # this test is about, so it goes first, inside the rolled-back transaction.
    db_tx.execute(
        text(
            "DELETE FROM treatment_sweep_claims WHERE account_id IN "
            "(SELECT id FROM accounts WHERE customer_id = :id)"
        ),
        {"id": cid},
    )
    db_tx.execute(text("DELETE FROM accounts WHERE customer_id = :id"), {"id": cid})
    assert _admit(db_tx, cid, session_key="lead-1", related_id="lead-1").reason != contact_policy.REASON_SETTLED


def test_the_weekly_cap_is_read_under_the_day_lock(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    """WS8: cooling-off and the weekly count ran before `_reserve_day` took
    the borrower's lock, so two concurrent admits at the cap both read
    `cap - 1` and were both admitted. The reads now sit inside the lock; the
    day row is locked before the weekly count is taken."""
    import inspect

    import contact_policy

    src = inspect.getsource(contact_policy.admit)
    assert (
        src.index("contact_ledger.lock_day(")
        < src.index("_week_counted(")
        < src.index("contact_ledger.increment_day(")
    )


def test_the_ledger_counts_the_week_the_gate_counts(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    import contact_policy

    """WS8: ledger_usage counted a rolling UTC 7 days while the gate counted
    from local midnight six days ago -- the Consent list and the refusal
    disagreed at the edge of the week."""
    cid = _prep(db_tx, monkeypatch)
    first = _admit(db_tx, cid, session_key="ledger-1", related_id="ledger-1")
    assert first.allowed
    usage = contact_policy.ledger_usage(db_tx, [cid])[cid]
    gate_n = contact_policy._week_counted(
        db_tx, cid, "whatsapp", now=_noon(), tz=contact_policy._zone("Asia/Kolkata")
    )
    assert usage["byChannel"].get("whatsapp", 0) == gate_n
