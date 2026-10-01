"""The written confirmation says what happened, once, with the final terms.

Codex review of run 90: a WhatsApp confirmation with no template to send it was
recorded "sent" with nothing queued, and one sent from the queue left the pay
intent reading "suppressed". And a caller who moves the date back and forth on
one call must not get a message per change.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import contact_policy
import db
import promise_fulfillment as pf
import voice_studio
from agent_core import clock


def _customer(db_tx) -> tuple[str, str]:
    row = db_tx.execute(text(
        "SELECT c.id, a.id AS account_id FROM customers c JOIN accounts a ON a.customer_id = c.id "
        "WHERE c.id <> 'UNKNOWN-CALLER' AND c.phone_primary IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM promises p WHERE p.account_id = a.id AND p.status IN ('upcoming','due_today')) "
        "AND COALESCE(a.outstanding, 0) > 10000 ORDER BY c.id LIMIT 1"
    )).mappings().first()
    if row is None:
        pytest.skip("no account without an open promise")
    return row["id"], row["account_id"]


def _day(n: int) -> str:
    return (clock.today_local() + timedelta(days=n)).isoformat()


def _admit(allowed: bool = True, reason: str | None = None):
    return lambda *a, **k: SimpleNamespace(allowed=allowed, reason=reason, deferrable=False)


@pytest.fixture
def no_template(monkeypatch):
    """Outside Meta's 24-hour window, with no approved template configured."""
    monkeypatch.setattr(pf, "_inside_service_window", lambda *a, **k: False)
    monkeypatch.setattr(pf, "resolve_template", lambda *a, **k: ("", ""))


def _promise(db_tx, monkeypatch, *, blocked: str) -> str:
    monkeypatch.setattr(pf, "_channel_blocked", lambda consent, channel: channel == blocked)
    customer_id, account_id = _customer(db_tx)
    return db.create_promise({"customerId": customer_id, "accountId": account_id, "amount": 800,
                              "promisedDate": _day(4)}, idempotency_key=f"wa-{uuid.uuid4().hex}")["id"]


def _whatsapp_row(db_tx, pid: str) -> dict:
    rid = f"PRM-T-{uuid.uuid4().hex[:8]}"
    db_tx.execute(text("UPDATE promise_reminders SET status = 'off' WHERE promise_id = :p AND kind = 'confirm'"),
                  {"p": pid})
    db_tx.execute(text("INSERT INTO promise_reminders (id, promise_id, channel, kind, scheduled_at, status) "
                       "VALUES (:id, :p, 'whatsapp', 'confirm', now(), 'scheduled')"), {"id": rid, "p": pid})
    return {"id": rid, "promise_id": pid, "channel": "whatsapp", "kind": "confirm"}


def _jobs(db_tx, pid: str) -> int:
    customer = db_tx.execute(text("SELECT customer_id FROM promises WHERE id = :p"), {"p": pid}).scalar()
    return db_tx.execute(text("SELECT count(*) FROM whatsapp_outbound_jobs WHERE customer_id = :c "
                              "AND source = 'ptp_confirm'"), {"c": customer}).scalar()


def test_a_whatsapp_row_with_no_template_goes_by_sms_not_nowhere(db_tx, monkeypatch, no_template) -> None:
    monkeypatch.setattr(contact_policy, "admit", _admit())
    pid = _promise(db_tx, monkeypatch, blocked="none")
    before = _jobs(db_tx, pid)
    prepared = pf._prepare_reminder(db_tx, _whatsapp_row(db_tx, pid))
    assert prepared["outcome"] == "send" and prepared["channel"] == "sms", prepared
    assert _jobs(db_tx, pid) == before


def test_with_sms_blocked_too_it_fails_with_its_reason(db_tx, monkeypatch, no_template) -> None:
    monkeypatch.setattr(contact_policy, "admit", _admit())
    pid = _promise(db_tx, monkeypatch, blocked="sms")
    before = _jobs(db_tx, pid)
    prepared = pf._prepare_reminder(db_tx, _whatsapp_row(db_tx, pid))
    assert prepared == {"outcome": "failed", "reason": "whatsapp_template_missing"}
    assert _jobs(db_tx, pid) == before


def test_a_whatsapp_row_the_policy_refuses_is_deferred_not_queued(db_tx, monkeypatch) -> None:
    monkeypatch.setattr(contact_policy, "admit", _admit())
    pid = _promise(db_tx, monkeypatch, blocked="sms")
    monkeypatch.setattr(pf, "_inside_service_window", lambda *a, **k: True)
    monkeypatch.setattr(contact_policy, "admit", _admit(False, "cooling_off"))
    before = _jobs(db_tx, pid)
    prepared = pf._prepare_reminder(db_tx, _whatsapp_row(db_tx, pid))
    assert prepared == {"outcome": "refused", "reason": "cooling_off"}
    assert _jobs(db_tx, pid) == before


def test_a_deferred_confirmation_once_sent_reads_sent_everywhere(db_tx, monkeypatch) -> None:
    """defer -> prepare -> send -> record -> snapshot (Codex, run 90)."""
    monkeypatch.setattr(contact_policy, "admit",
                        _admit(False, contact_policy.REASON_WINDOW_DEFERRED_STATUTORY))
    pid = _promise(db_tx, monkeypatch, blocked="whatsapp")
    assert pf.snapshot(db_tx, pid).suppressed is True
    row = db_tx.execute(text("SELECT id, promise_id, channel, kind FROM promise_reminders "
                             "WHERE promise_id = :p AND kind = 'confirm' AND status = 'scheduled'"),
                        {"p": pid}).mappings().one()

    monkeypatch.setattr(contact_policy, "admit", _admit())  # morning
    prepared = pf._prepare_reminder(db_tx, dict(row))
    assert prepared["outcome"] == "send"
    pf._record_reminder(db_tx, dict(row), ok=True, err=None, provider_delivery_id=f"SM{uuid.uuid4().hex}",
                        channel=prepared["channel"], body=prepared["body"])

    snap = pf.snapshot(db_tx, pid)
    assert (snap.pay_link_sent, snap.suppressed, snap.suppression_reason, snap.confirm_channel) == \
        (True, False, None, "sms")


def _call_ctx(customer_id: str, account_id: str) -> dict:
    return {"workflow_run_id": 900000 + uuid.uuid4().int % 99999, "workflow_id": 4, "agent_id": 4,
            "direction": "outbound", "customer_id": customer_id, "account_id": account_id}


def _live(db_tx, ix: str, status: str = "live") -> None:
    db_tx.execute(text("INSERT INTO voice_sessions (id, interaction_id, transport, status) "
                       "VALUES (:id, :ix, 'twilio', :s)"), {"id": f"VS-T-{uuid.uuid4().hex[:8]}", "ix": ix, "s": status})


def _confirms(db_tx, pid: str) -> list[dict]:
    return [dict(r) for r in db_tx.execute(text(
        "SELECT id, promise_id, channel, kind, status, after_call_interaction_id, scheduled_at, sending_at, "
        "provider_delivery_id FROM promise_reminders WHERE promise_id = :p AND kind = 'confirm' "
        "ORDER BY created_at, id"), {"p": pid}).mappings()]


@pytest.fixture
def on_a_call(db_tx, monkeypatch):
    """A promise made on a live call, confirmed by SMS; every contact admitted."""
    import policy_rules

    monkeypatch.setattr(contact_policy, "admit", _admit())
    monkeypatch.setattr(pf, "_channel_blocked", lambda consent, channel: channel == "whatsapp")
    monkeypatch.setattr(voice_studio, "_require_verified", lambda *_a, **_k: None)
    monkeypatch.setattr(policy_rules, "PTP_MAX_REVISIONS", 10)  # several changes; the cap is not under test
    customer_id, account_id = _customer(db_tx)
    ctx = _call_ctx(customer_id, account_id)
    out = voice_studio.run_tool("promise_to_pay", {**ctx, "amount": 5000, "date": _day(6)})
    assert out["ok"] is True, out
    pid = out["promiseId"]
    ix = db_tx.execute(text("SELECT interaction_id FROM promises WHERE id = :p"), {"p": pid}).scalar()
    _live(db_tx, ix)
    first = _confirms(db_tx, pid)[0]
    prepared = pf._prepare_reminder(db_tx, first)
    assert prepared["outcome"] == "send"  # the first goes while they are on the line
    pf._record_reminder(db_tx, first, ok=True, err=None, channel="sms", body=prepared["body"])
    # now() is the test transaction's start: a later send must read as later.
    db_tx.execute(text("UPDATE promise_reminders SET sent_at = now() - interval '1 hour' WHERE id = :id"),
                  {"id": first["id"]})
    return SimpleNamespace(ctx=ctx, pid=pid, ix=ix)


def _change(ctx: dict, day: str) -> dict:
    out = voice_studio.run_tool("promise_to_pay", {**ctx, "amount": 5000, "date": day, "reason": "other"})
    assert out["ok"] is True, out
    return out


def test_moving_the_date_back_and_forth_on_a_call_sends_the_final_terms_once(db_tx, on_a_call) -> None:
    ctx, pid, ix = on_a_call.ctx, on_a_call.pid, on_a_call.ix
    _change(ctx, _day(7))
    out = _change(ctx, _day(8))
    held = [r for r in _confirms(db_tx, pid) if r["status"] == "scheduled"]
    assert len(held) == 1 and held[0]["after_call_interaction_id"] == ix
    assert held[0]["scheduled_at"] > clock.utc_now() + timedelta(minutes=20)
    assert "after our call" in str(out)
    assert pf.snapshot(db_tx, pid).after_call is True  # a later read still says so

    db_tx.execute(text("UPDATE voice_sessions SET status = 'ended' WHERE interaction_id = :ix"), {"ix": ix})
    assert pf.release_after_call(db_tx, ix) == 1
    prepared = pf._prepare_reminder(db_tx, held[0])
    assert prepared["outcome"] == "send"
    assert date.fromisoformat(_day(8)).strftime("%d %b") in prepared["body"]
    pf._record_reminder(db_tx, held[0], ok=True, err=None, channel="sms", body=prepared["body"])
    assert pf.snapshot(db_tx, pid).after_call is False

    # Next call: they move it and move it back. Nothing new to tell them.
    db_tx.execute(text("UPDATE promise_reminders SET sent_at = now() - interval '30 minutes' WHERE id = :id"),
                  {"id": held[0]["id"]})
    call_b = voice_studio.ensure_interaction(900000 + uuid.uuid4().int % 99999, ctx)
    _live(db_tx, call_b)
    for day in (_day(9), _day(8)):
        _change({**ctx, "workflow_run_id": ctx["workflow_run_id"] + 1}, day)
    again = [r for r in _confirms(db_tx, pid) if r["status"] == "scheduled"]
    assert len(again) == 1
    assert pf._prepare_reminder(db_tx, again[0]) == {"outcome": "unchanged"}


def test_filing_an_earlier_call_does_not_release_a_later_calls_hold(db_tx, on_a_call) -> None:
    """Codex: a promise made on call A and changed on call B -- filing A released B's hold."""
    ctx, pid, call_a = on_a_call.ctx, on_a_call.pid, on_a_call.ix
    db_tx.execute(text("UPDATE voice_sessions SET status = 'ended' WHERE interaction_id = :ix"), {"ix": call_a})
    later = {**ctx, "workflow_run_id": ctx["workflow_run_id"] + 1}
    call_b = voice_studio.ensure_interaction(later["workflow_run_id"], later)
    _live(db_tx, call_b)
    _change(later, _day(9))
    held = [r for r in _confirms(db_tx, pid) if r["status"] == "scheduled"]
    assert len(held) == 1 and held[0]["after_call_interaction_id"] == call_b

    assert pf.release_after_call(db_tx, call_a) == 0
    assert pf.release_after_call(db_tx, call_b) == 1


def test_a_confirmation_sent_now_replaces_an_older_one_still_pending(db_tx, monkeypatch) -> None:
    """Codex: a WhatsApp resend left the evening's deferred confirmation scheduled too."""
    monkeypatch.setattr(contact_policy, "admit",
                        _admit(False, contact_policy.REASON_WINDOW_DEFERRED_STATUTORY))
    pid = _promise(db_tx, monkeypatch, blocked="sms")
    assert [r["status"] for r in _confirms(db_tx, pid)] == ["scheduled"]

    monkeypatch.setattr(contact_policy, "admit", _admit())
    monkeypatch.setattr(pf, "_inside_service_window", lambda *a, **k: True)
    pf.fulfill(db_tx, pid, resend=True)
    rows = _confirms(db_tx, pid)
    assert [(r["channel"], r["status"]) for r in rows] == [("whatsapp", "off"), ("whatsapp", "queued")]
    assert rows[1]["sending_at"] is not None  # handed to WhatsApp, awaiting Meta


def _whatsapp_confirm(db_tx, monkeypatch) -> tuple[str, dict]:
    monkeypatch.setattr(contact_policy, "admit", _admit())
    monkeypatch.setattr(pf, "_inside_service_window", lambda *a, **k: True)
    pid = _promise(db_tx, monkeypatch, blocked="sms")
    rows = _confirms(db_tx, pid)
    assert [(r["channel"], r["status"]) for r in rows] == [("whatsapp", "queued")]
    return pid, rows[0]


def _intent(db_tx, pid: str) -> str:
    return db_tx.execute(text("SELECT status FROM payment_intents WHERE promise_id = :p"), {"p": pid}).scalar()


def test_a_whatsapp_confirmation_reads_sent_only_once_meta_accepts_it(db_tx, monkeypatch) -> None:
    pid, row = _whatsapp_confirm(db_tx, monkeypatch)
    db_tx.execute(text("UPDATE messages SET delivery_status = 'sent' WHERE id = :m"),
                  {"m": row["provider_delivery_id"]})
    pf._settle_whatsapp(db_tx)
    assert _confirms(db_tx, pid)[0]["status"] == "sent" and _intent(db_tx, pid) == "sent"

    # Meta's later receipt: failed after all.
    db_tx.execute(text("UPDATE messages SET delivery_status = 'failed' WHERE id = :m"),
                  {"m": row["provider_delivery_id"]})
    pf._settle_whatsapp(db_tx)
    assert _confirms(db_tx, pid)[0]["status"] == "failed"
    assert _intent(db_tx, pid) == "created"  # same link, no longer read as delivered


def test_a_whatsapp_confirmation_whose_job_dies_is_not_left_confirmed(db_tx, monkeypatch) -> None:
    """Codex: a failed Meta send updated the message and job, never the reminder or intent."""
    pid, row = _whatsapp_confirm(db_tx, monkeypatch)
    assert _intent(db_tx, pid) == "sent"
    db_tx.execute(text("UPDATE whatsapp_outbound_jobs SET status = 'dead', error = 'whatsapp_send_failed:131026' "
                       "WHERE message_id = :m"), {"m": row["provider_delivery_id"]})
    assert pf._settle_whatsapp(db_tx) == 1
    after = _confirms(db_tx, pid)[0]
    assert after["status"] == "failed" and after["sending_at"] is None
    assert _intent(db_tx, pid) == "created"


def test_a_template_confirmation_records_what_the_template_said_parts_and_all(db_tx, monkeypatch) -> None:
    """Codex: the template carried total, last date and link; the record claimed the parts."""
    monkeypatch.setattr(pf, "resolve_template", lambda *a, **k: ("payint_payment_link", "en"))
    pid = _promise(db_tx, monkeypatch, blocked="none")
    promise = pf._load_promise(db_tx, pid)
    intent = dict(db_tx.execute(text("SELECT * FROM payment_intents WHERE promise_id = :p"), {"p": pid}).mappings().one())
    parts = [{"amount": 300, "date": _day(2)}, {"amount": 500, "date": _day(4)}]
    mid, body = pf._enqueue_whatsapp(db_tx, promise=promise, intent=intent, to_phone="+910000000000",
                                     body="(composed)", use_template=True, parts=parts)
    params = db_tx.execute(text("SELECT template_params FROM whatsapp_outbound_jobs WHERE message_id = :m"),
                           {"m": mid}).scalar()
    assert body == pf._TEMPLATE_BODIES["confirm"].format(*params)  # the record is the transmission
    terms = pf._terms(amount=intent["amount"], promised_at=promise["promised_at"], parts=parts)
    assert "(Rs 300 by" in params[1] and pf._terms_said(body, terms)
    assert not pf._terms_said(body, pf._terms(amount=intent["amount"], promised_at=promise["promised_at"]))


def _queued(db_tx, related: str) -> list[dict]:
    return [dict(r) for r in db_tx.execute(text(
        "SELECT id, kind, status, scheduled_at, context FROM written_followups WHERE related_id = :r"),
        {"r": related}).mappings()]


def test_a_booked_callback_owes_one_written_copy_however_often_it_is_asked(db_tx, monkeypatch) -> None:
    """Codex: two concurrent requests both passed the 'once' check and both sent."""
    customer_id, account_id = _customer(db_tx)
    ctx = _call_ctx(customer_id, account_id)
    when = f"{_day(2)}T16:30:00+05:30"
    out = voice_studio.run_tool("request_callback", {**ctx, "when": when})
    assert out["ok"] is True and out["writtenConfirmation"] is True, out
    rows = _queued(db_tx, out["callbackId"])
    assert len(rows) == 1 and rows[0]["kind"] == "callback_confirm" and rows[0]["status"] == "scheduled"
    again = voice_studio.run_tool("request_callback", {**ctx, "when": when})
    assert again["alreadyBooked"] is True and again["writtenConfirmation"] is True
    import written_followup

    # The second insert of the same booking is refused by the unique key itself.
    assert written_followup.queue(db_tx, customer_id=customer_id, kind="callback_confirm",
                                  related_id=out["callbackId"]) is False
    assert len(_queued(db_tx, out["callbackId"])) == 1


def test_an_outside_hours_copy_waits_for_messaging_hours(db_tx, monkeypatch) -> None:
    """Codex: a window-deferred callback/dispute copy was dropped."""
    import compliance_copy
    import written_followup

    morning = clock.utc_now() + timedelta(hours=10)
    monkeypatch.setattr(contact_policy, "admit", lambda *a, **k: SimpleNamespace(
        allowed=False, reason=contact_policy.REASON_WINDOW_DEFERRED_STATUTORY, deferrable=True,
        next_allowed_at=morning))
    monkeypatch.setattr(written_followup, "_channel_blocked", lambda *a: False)
    monkeypatch.setattr(pf, "_inside_service_window", lambda *a, **k: True)
    monkeypatch.setattr(compliance_copy, "written_footer", lambda *a, **k: "Grievance officer: A Officer, 1800 000 000.")
    customer_id, _ = _customer(db_tx)
    ref = f"DSP-T-{uuid.uuid4().hex[:8]}"
    assert written_followup.queue(db_tx, customer_id=customer_id, kind="dispute_ref", related_id=ref,
                                  context={"reference": ref})
    db_tx.execute(text("UPDATE written_followups SET scheduled_at = now() - interval '1 minute' "
                       "WHERE related_id = :r"), {"r": ref})
    assert written_followup.process_one(db.engine) is True
    row = _queued(db_tx, ref)[0]
    assert row["status"] == "scheduled" and abs((row["scheduled_at"] - morning).total_seconds()) < 1

    # Morning: admitted, handed to WhatsApp, and sent once Meta accepts it.
    monkeypatch.setattr(contact_policy, "admit", _admit())
    db_tx.execute(text("UPDATE written_followups SET scheduled_at = now() - interval '1 minute' "
                       "WHERE related_id = :r"), {"r": ref})
    assert written_followup.process_one(db.engine) is True
    handed = db_tx.execute(text("SELECT status, channel, message_id FROM written_followups WHERE related_id = :r"),
                           {"r": ref}).mappings().one()
    assert (handed["status"], handed["channel"]) == ("queued", "whatsapp") and handed["message_id"]
    db_tx.execute(text("UPDATE messages SET delivery_status = 'sent' WHERE id = :m"), {"m": handed["message_id"]})
    written_followup.process_one(db.engine)
    assert _queued(db_tx, ref)[0]["status"] == "sent"


def test_a_callback_outside_the_window_uses_its_template_on_the_customers_clock(db_tx, monkeypatch) -> None:
    import compliance_copy
    import written_followup

    monkeypatch.setattr(contact_policy, "admit", _admit())
    monkeypatch.setattr(written_followup, "_channel_blocked", lambda *a: False)
    monkeypatch.setattr(pf, "_inside_service_window", lambda *a, **k: False)
    monkeypatch.setattr(pf, "resolve_template", lambda name, lang: (
        ("payint_callback_booked", "en") if name == "WHATSAPP_CALLBACK_TEMPLATE_NAME" else ("", "")))
    monkeypatch.setattr(compliance_copy, "written_footer", lambda *a, **k: "Grievance officer: A Officer, 1800 000 000.")
    customer_id, _ = _customer(db_tx)
    db_tx.execute(text("UPDATE customers_pii SET timezone = 'Asia/Kolkata' WHERE id = :c"), {"c": customer_id})
    done = written_followup.send(db_tx, customer_id=customer_id, kind="callback_confirm",
                                 context={"callbackAt": f"{_day(2)}T11:00:00+00:00"})
    assert done.sent and done.channel == "whatsapp", done
    job = db_tx.execute(text("SELECT template_name, template_params FROM whatsapp_outbound_jobs "
                             "WHERE message_id = :m"), {"m": done.message_id}).mappings().one()
    assert job["template_name"] == "payint_callback_booked"
    brand, when, officer = job["template_params"]
    assert "4:30 PM" in when  # 11:00 UTC is 16:30 in India
    assert officer == "A Officer, 1800 000 000"
