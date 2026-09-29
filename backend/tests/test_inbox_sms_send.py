"""A person's SMS is sent by Twilio, or it is not recorded as sent.

``send_conversation_message`` and ``send_customer_outreach`` stored an SMS as
``delivery_status='sent'`` with ``provider_ref = NULL`` and never called a
provider. Both now queue it on the agent outbox the way WhatsApp is queued; the
worker sends it through ``twilio_sms.send`` after commit, and only Twilio's
answer moves the row off ``sending``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import contact_policy
import db
import db_inbox
import delivery_receipts
import twilio_sms
import whatsapp_outbound as wo

_REAL_SEND = twilio_sms.send


@pytest.fixture
def sms(db_tx, monkeypatch):
    """An SMS thread opened by outreach, with the gate open and Twilio faked."""
    cid = db_tx.execute(
        text(
            """
            SELECT a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.phone_primary IS NOT NULL
            ORDER BY a.id LIMIT 1
            """
        )
    ).scalar()
    if cid is None:
        pytest.skip("seed has no customer with a phone")
    state = {"customer_id": cid, "verdict": contact_policy.Decision(True), "admits": [], "sent": []}

    def _admit(conn, **kw):
        state["admits"].append(kw["channel"])
        return state["verdict"]

    def _send(**kw):
        sid = f"SM{uuid.uuid4().hex}"
        state["sent"].append({**kw, "sid": sid})
        return {"sid": sid, "status": "queued"}

    monkeypatch.setattr(contact_policy, "admit", _admit)
    monkeypatch.setattr(twilio_sms, "configured", lambda: True)
    monkeypatch.setattr(twilio_sms, "send", _send)
    opened = db_inbox.send_customer_outreach(cid, {"channel": "sms", "text": _body()})
    state["conversation_id"] = opened["conversationId"]
    return state


def _body() -> str:
    return f"sms test {uuid.uuid4().hex}"


def _message(conn, body: str):
    return conn.execute(
        text("SELECT id, delivery_status, provider_ref FROM messages WHERE body = :b"), {"b": body}
    ).mappings().first()


def _job(conn, message_id: str) -> dict:
    return dict(
        conn.execute(
            text("SELECT * FROM whatsapp_outbound_jobs WHERE message_id = :m"), {"m": message_id}
        ).mappings().one()
    )


def _reply(sms, body: str) -> None:
    db_inbox.send_conversation_message(sms["conversation_id"], {"text": body})


def test_an_sms_reply_is_queued_and_twilio_sends_it_after_commit(db_tx, sms) -> None:
    body = _body()
    _reply(sms, body)

    queued = _message(db_tx, body)
    assert queued["delivery_status"] == "sending"
    assert queued["provider_ref"] is None
    job = _job(db_tx, queued["id"])
    assert job["status"] == "queued" and job["source"] == "inbox_reply"
    assert sms["sent"] == [], "Twilio was called inside the request"

    wo.handle_job(db.engine, job)

    (call,) = sms["sent"]
    assert call["body"] == body
    assert call["related_id"] == queued["id"]
    assert call["customer_id"] == sms["customer_id"]
    sent = _message(db_tx, body)
    assert sent["delivery_status"] == "sent"
    assert sent["provider_ref"] == call["sid"]
    assert _job(db_tx, queued["id"])["status"] == "succeeded"
    # API and worker both gated on SMS, never on WhatsApp.
    assert sms["admits"] and set(sms["admits"]) == {"sms"}


def test_no_sms_provider_refuses_and_stores_nothing(db_tx, sms, monkeypatch) -> None:
    monkeypatch.setattr(twilio_sms, "configured", lambda: False)
    body = _body()
    with pytest.raises(ValueError, match="sms_not_configured"):
        _reply(sms, body)
    with pytest.raises(ValueError, match="sms_not_configured"):
        db_inbox.send_customer_outreach(sms["customer_id"], {"channel": "sms", "text": body})
    assert _message(db_tx, body) is None


def test_a_provider_gone_by_send_time_fails_the_message(db_tx, sms, monkeypatch) -> None:
    body = _body()
    _reply(sms, body)
    # The worker's environment has no Twilio: the real sender refuses.
    monkeypatch.setattr(twilio_sms, "configured", lambda: False)
    monkeypatch.setattr(twilio_sms, "send", _REAL_SEND)
    queued = _message(db_tx, body)

    wo.handle_job(db.engine, _job(db_tx, queued["id"]))

    assert _message(db_tx, body)["delivery_status"] == "failed"
    job = _job(db_tx, queued["id"])
    assert job["status"] == "dead" and job["error"] == "sms_not_configured"


def test_contact_policy_still_blocks_an_sms(db_tx, sms) -> None:
    body = _body()
    _reply(sms, body)  # queued while the gate was open
    sms["verdict"] = contact_policy.Decision(False, contact_policy.REASON_OPTED_OUT)

    refused = _body()
    with pytest.raises(ValueError, match=contact_policy.REASON_OPTED_OUT):
        _reply(sms, refused)
    with pytest.raises(ValueError, match=contact_policy.REASON_OPTED_OUT):
        db_inbox.send_customer_outreach(sms["customer_id"], {"channel": "sms", "text": refused})
    assert _message(db_tx, refused) is None

    # The opt-out also stops the one already queued, at send time.
    wo.handle_job(db.engine, _job(db_tx, _message(db_tx, body)["id"]))
    assert sms["sent"] == []
    assert _message(db_tx, body)["delivery_status"] == "failed"


def test_twilio_receipts_move_the_bubble_forward_only(db_tx, sms) -> None:
    body = _body()
    _reply(sms, body)
    queued = _message(db_tx, body)
    wo.handle_job(db.engine, _job(db_tx, queued["id"]))
    sid = _message(db_tx, body)["provider_ref"]
    # The receipt the real twilio_sms.send writes as the SID is born.
    delivery_receipts.record(
        db_tx,
        tenant_id=db_tx.execute(
            text("SELECT tenant_id FROM customers WHERE id = :c"), {"c": sms["customer_id"]}
        ).scalar(),
        customer_id=sms["customer_id"],
        channel="sms",
        provider="twilio",
        provider_ref=sid,
        related_id=queued["id"],
        state="queued",
    )

    for state, bubble in [("delivered", "delivered"), ("sent", "delivered"), ("undelivered", "failed")]:
        assert delivery_receipts.record_twilio_sms_status(sid=sid, state=state, reason=None)
        assert _message(db_tx, body)["delivery_status"] == bubble, state
