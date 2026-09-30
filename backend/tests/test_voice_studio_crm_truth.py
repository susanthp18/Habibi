"""What a Voice Studio call writes into the CRM is true (run 88, 30 Sep).

The promise itself was right; around it the audit trail named a person for
the bot's writes, the reminder kept a superseded date, the written
confirmation lacked the parts and a failed SMS read "sent", a broken promise
was offered as still open, and the call was analysed while it was still live.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import text

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


@pytest.fixture
def by_sms(monkeypatch):
    """Confirmations go by SMS and every contact is admitted: the channel and
    the contact policy are not what these tests are about."""
    import contact_policy

    monkeypatch.setattr(pf, "_channel_blocked", lambda consent, channel: channel == "whatsapp")
    monkeypatch.setattr(contact_policy, "admit", lambda *a, **k: SimpleNamespace(allowed=True, reason=None))


def _call(db_tx, customer_id: str, account_id: str) -> dict:
    return {"workflow_run_id": 900000 + uuid.uuid4().int % 99999, "workflow_id": 4, "agent_id": 4,
            "direction": "outbound", "customer_id": customer_id, "account_id": account_id}


def _due(db_tx, promise_id: str) -> dict[str, str]:
    rows = db_tx.execute(text(
        "SELECT due_on, status FROM promise_reminders WHERE promise_id = :p AND kind = 'due'"
    ), {"p": promise_id}).all()
    return {r.due_on.isoformat(): r.status for r in rows}


def test_a_promise_in_parts_is_written_as_the_agent_and_reminded_on_each_day(db_tx, monkeypatch, by_sms) -> None:
    monkeypatch.setattr(voice_studio, "_require_verified", lambda *_a, **_k: None)
    customer_id, account_id = _customer(db_tx)
    ctx = _call(db_tx, customer_id, account_id)
    parts = [{"amount": 2500, "date": _day(2)}, {"amount": 2500, "date": _day(6)}]
    out = voice_studio.run_tool("promise_to_pay", {**ctx, "amount": 5000, "date": _day(6), "parts": parts})
    assert out["ok"] is True, out
    pid = out["promiseId"]

    actors = db_tx.execute(text(
        "SELECT DISTINCT actor_kind, actor_user_id, actor_bot_id FROM activity_events "
        "WHERE entity_type = 'promise' AND entity_id = :p"
    ), {"p": pid}).all()
    assert [tuple(a) for a in actors] == [("bot", None, "voice-studio-4")]
    # Written with the promise, so the confirmation already carries them.
    assert _due(db_tx, pid) == {_day(2): "scheduled", _day(6): "scheduled"}
    url = db_tx.execute(text("SELECT pay_url FROM payment_intents WHERE promise_id = :p"), {"p": pid}).scalar()

    # Run 88: the second part moved to the next day.
    moved = [parts[0], {"amount": 2500, "date": _day(7)}]
    out = voice_studio.run_tool("promise_to_pay", {**ctx, "amount": 5000, "date": _day(7), "parts": moved,
                                                  "reason": "partial_payment_agreed"})
    assert out["ok"] is True and out.get("revisionCount") == 1, out
    rev = db_tx.execute(text("SELECT actor_kind, actor_user_id, actor_bot_id FROM promise_revisions "
                             "WHERE promise_id = :p"), {"p": pid}).one()
    assert tuple(rev) == ("bot", None, "voice-studio-4")
    assert _due(db_tx, pid) == {_day(2): "scheduled", _day(6): "off", _day(7): "scheduled"}
    # The new terms are sent again, once, on the same link (ADR 0008).
    confirms = db_tx.execute(text("SELECT status FROM promise_reminders WHERE promise_id = :p AND kind = 'confirm'"),
                             {"p": pid}).scalars().all()
    assert sorted(confirms) == ["off", "queued"]
    assert db_tx.execute(text("SELECT pay_url FROM payment_intents WHERE promise_id = :p AND status IN "
                              "('created','sent','opened')"), {"p": pid}).scalar() == url

    # What each message says: the confirmation has the parts, the first due day names its part.
    confirm = db_tx.execute(text("SELECT id, kind, due_on FROM promise_reminders WHERE promise_id = :p "
                                 "AND kind = 'confirm' AND status = 'queued'"), {"p": pid}).mappings().one()
    body = pf._prepare_reminder(db_tx, {**confirm, "promise_id": pid, "channel": "sms"})["body"]
    assert "Rs 5,000 by" in body and body.count("Rs 2,500 by") == 2 and url in body
    first = db_tx.execute(text("SELECT id, kind, due_on FROM promise_reminders WHERE promise_id = :p "
                               "AND kind = 'due' AND due_on = :d"), {"p": pid, "d": _day(2)}).mappings().one()
    due = pf._prepare_reminder(db_tx, {**first, "promise_id": pid, "channel": "sms"})["body"]
    assert due.startswith("Reminder: Rs 2,500 is due today") and "part 1 of 2" in due


def test_a_failed_sms_receipt_stops_the_confirmation_reading_sent(db_tx, by_sms) -> None:
    import delivery_receipts

    customer_id, account_id = _customer(db_tx)
    promise = db.create_promise({"customerId": customer_id, "accountId": account_id, "amount": 800,
                                 "promisedDate": _day(4)}, idempotency_key=f"rcpt-{uuid.uuid4().hex}")
    reminder = db_tx.execute(text("SELECT id FROM promise_reminders WHERE promise_id = :p AND kind = 'confirm'"),
                             {"p": promise["id"]}).scalar()
    if reminder is None:
        pytest.skip("no SMS confirmation queued")
    sid = f"SM{uuid.uuid4().hex}"
    db_tx.execute(text("UPDATE promise_reminders SET status = 'sent', provider_delivery_id = :s WHERE id = :id"),
                  {"s": sid, "id": reminder})
    delivery_receipts.record(db_tx, tenant_id=db.current_tenant(), customer_id=customer_id, channel="sms",
                             provider="twilio", provider_ref=sid, related_id=reminder, state="queued")
    assert db_tx.execute(text("SELECT status FROM payment_intents WHERE promise_id = :p"),
                         {"p": promise["id"]}).scalar() == "sent"

    assert delivery_receipts.record_twilio_sms_status(sid=sid, state="failed", reason="30044") is True
    row = db_tx.execute(text("SELECT status, last_error FROM promise_reminders WHERE id = :id"), {"id": reminder}).one()
    assert tuple(row) == ("failed", "twilio:30044")
    # Still the open intent (same link), no longer "sent": the promises board's
    # payLinkSent is read off this status (db_promises.list_promises).
    assert db_tx.execute(text("SELECT status FROM payment_intents WHERE promise_id = :p"),
                         {"p": promise["id"]}).scalar() == "created"
    # A replayed callback changes nothing.
    assert pf.delivery_failed(db_tx, reminder, "twilio:30044") is False


def test_a_broken_promise_is_offered_as_missed_not_open(db_tx) -> None:
    customer_id, account_id = _customer(db_tx)
    promise = db.create_promise({"customerId": customer_id, "accountId": account_id, "amount": 800,
                                 "promisedDate": _day(3)}, idempotency_key=f"miss-{uuid.uuid4().hex}")
    db_tx.execute(text("UPDATE promises SET status = 'broken' WHERE id = :p"), {"p": promise["id"]})
    position = voice_studio._account_position(customer_id, account_id)
    assert "open_promise" not in position
    assert position["missed_promise"]["status"] == "broken"


def test_the_engine_mode_names_the_transport() -> None:
    assert voice_studio.transport_for("twilio") == "twilio"
    assert voice_studio.transport_for("ari") == "asterisk"
    assert voice_studio.transport_for("smallwebrtc") == voice_studio.transport_for("webrtc") == "smallwebrtc"
    assert voice_studio.transport_for("plivo") == "websocket"
    assert voice_studio.transport_for("textchat") is None and voice_studio.transport_for(None) is None


def test_a_live_call_is_not_analysed_until_it_is_filed(db_tx, monkeypatch) -> None:
    from call_intel import jobs

    queued: list[tuple[str, bool]] = []
    monkeypatch.setattr(jobs, "enqueue", lambda ix, rerun=False: queued.append((ix, rerun)))
    monkeypatch.setattr(voice_studio, "engine_call", lambda *a, **k: {})
    monkeypatch.setattr(voice_studio, "_engine_runs", lambda *a, **k: [])
    monkeypatch.setattr(voice_studio, "_version_number", lambda *a, **k: None)
    customer_id, account_id = _customer(db_tx)
    run_id = 900000 + uuid.uuid4().int % 99999
    ix = voice_studio.ensure_interaction(run_id, _call(db_tx, customer_id, account_id))

    voice_studio.reconcile_runs()  # 30 s into run 88
    assert ix not in {q[0] for q in queued}
    db_tx.execute(text("UPDATE interactions SET status = 'completed', ended_at = now() WHERE id = :ix"), {"ix": ix})
    voice_studio.reconcile_runs()
    assert (ix, True) in queued


def test_a_job_for_a_live_call_is_not_claimed(db_tx, monkeypatch) -> None:
    from call_intel import jobs

    customer_id, account_id = _customer(db_tx)
    ix = voice_studio.ensure_interaction(900000 + uuid.uuid4().int % 99999, _call(db_tx, customer_id, account_id))
    db_tx.execute(text("INSERT INTO call_intelligence_jobs (id, tenant_id, interaction_id, available_at) "
                       "VALUES (:id, :t, :ix, now() - interval '1 day')"),
                  {"id": f"CIJ-{uuid.uuid4().hex[:12]}", "t": db.current_tenant(), "ix": ix})
    assert ix not in {j["interaction_id"] for j in jobs.claim(500)}
    db_tx.execute(text("UPDATE interactions SET status = 'completed' WHERE id = :ix"), {"ix": ix})
    assert ix in {j["interaction_id"] for j in jobs.claim(500)}


def test_a_failure_the_carrier_reports_early_or_late_is_applied_to_that_send_only(db_tx, by_sms) -> None:
    """Codex review of run 88: a receipt that beat the drain's "sent" was lost,
    and an old confirmation's failure reset the intent a newer one had sent."""
    import delivery_receipts

    customer_id, account_id = _customer(db_tx)
    promise = db.create_promise({"customerId": customer_id, "accountId": account_id, "amount": 800,
                                 "promisedDate": _day(4)}, idempotency_key=f"early-{uuid.uuid4().hex}")
    first = db_tx.execute(text("SELECT id, promise_id, kind FROM promise_reminders WHERE promise_id = :p "
                               "AND kind = 'confirm'"), {"p": promise["id"]}).mappings().first()
    if first is None:
        pytest.skip("no SMS confirmation queued")
    intent = lambda: db_tx.execute(text("SELECT status FROM payment_intents WHERE promise_id = :p"),  # noqa: E731
                                   {"p": promise["id"]}).scalar()

    # Early: the carrier's failure lands while the drain still holds the send.
    sid = f"SM{uuid.uuid4().hex}"
    delivery_receipts.record(db_tx, tenant_id=db.current_tenant(), customer_id=customer_id, channel="sms",
                             provider="twilio", provider_ref=sid, related_id=first["id"], state="failed",
                             reason="30044")
    pf._record_reminder(db_tx, dict(first), ok=True, err=None, provider_delivery_id=sid)
    row = db_tx.execute(text("SELECT status, last_error FROM promise_reminders WHERE id = :id"),
                        {"id": first["id"]}).one()
    assert tuple(row) == ("failed", "twilio:30044") and intent() == "created"

    # Superseded: the terms changed and a newer confirmation went out; the
    # older one's failure is about the older message only.
    db_tx.execute(text("UPDATE promise_reminders SET status = 'sent', created_at = now() - interval '1 hour' "
                       "WHERE id = :id"), {"id": first["id"]})
    db_tx.execute(text("UPDATE payment_intents SET status = 'sent' WHERE promise_id = :p"), {"p": promise["id"]})
    db_tx.execute(text("INSERT INTO promise_reminders (id, promise_id, channel, kind, scheduled_at, status) "
                       "VALUES (:id, :p, 'sms', 'confirm', now(), 'sent')"),
                  {"id": f"PRM-{uuid.uuid4().hex[:10]}", "p": promise["id"]})
    assert pf.delivery_failed(db_tx, first["id"], "twilio:30044") is True
    assert intent() == "sent"


def test_two_parts_on_one_day_are_refused() -> None:
    """Codex review of run 88: the day's reminder named only the first of them."""
    parts, refused = voice_studio._parts({"amount": 5000, "date": _day(6), "parts": [
        {"amount": 2500, "date": _day(6)}, {"amount": 2500, "date": _day(6)}]})
    assert parts is None and refused["error"] == "invalid_parts"


def test_a_reply_in_a_language_the_caller_never_spoke_is_recorded() -> None:
    """Run 88 retried verification in Kannada; the record said only en-IN."""
    turns = [
        {"type": "rtf-user-transcription", "payload": {"text": "1111।", "language": "en-IN"}},
        {"type": "rtf-bot-text", "payload": {"text": "ಕ್ಷಮಿಸಿ, ಅದನ್ನು ಪರಿಶೀಲಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ."}},
        {"type": "rtf-user-transcription", "payload": {"text": "I don't understand.", "language": "en-IN"}},
        {"type": "rtf-bot-text", "payload": {"text": "Sorry, could you tell me the last four digits?"}},
    ]
    got = voice_studio.call_languages({"languages_spoken": ["en-IN"]}, turns)
    assert got["offLanguage"] == [{"turn": 1, "script": "KANNADA"}]
    hindi = [{"type": "rtf-user-transcription", "payload": {"text": "हाँ जी", "language": "hi-IN"}},
             {"type": "rtf-bot-text", "payload": {"text": "धन्यवाद"}}]
    assert "offLanguage" not in voice_studio.call_languages({"languages_spoken": ["hi-IN"]}, hindi)
