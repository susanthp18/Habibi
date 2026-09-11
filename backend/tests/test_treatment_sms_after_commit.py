"""The treatment SMS is sent after the claim commits, and recorded after it is sent.

`_send_sms` used to call the carrier on the executor's open transaction: a
crash between Twilio's 200 and the commit lost the contact event and left the
attempt un-sent, so the next tick sent the borrower the same message again.
Now the handler prepares (copy, outbox row) and hands the send back; process_one
commits, sends with no transaction open, and records on a third one -- the
claim -> commit -> carrier I/O -> record shape every other scheduler has.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import text

from agent_core.treatment import attempts, enact


@pytest.fixture
def account(db_tx):
    row = db_tx.execute(
        text(
            """
            SELECT a.id, a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.phone_primary IS NOT NULL
            ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no account with a phone number")
    return dict(row)


def test_the_handler_prepares_and_defers_the_send(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    import twilio_sms

    monkeypatch.setattr(twilio_sms, "configured", lambda: True)
    monkeypatch.setattr(enact, "_copy", lambda *a, **k: "Your EMI bounced; pay by Friday.")
    monkeypatch.setattr(enact, "_outbox_send", lambda *a, **k: {"submitted": True, "id": "OB-1"})
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(twilio_sms, "send", lambda **kw: sent.append(kw) or {"sid": "SM1"})

    decision = {"id": "TD-SMS-1"}
    ref = enact._send_sms(
        db_tx,
        decision=decision,
        customer={"id": "cust-1", "phone_primary": "+919000000001", "tenant_id": "hdfc.retail"},
    )
    assert ref == "queued:sms:deferred"
    assert sent == [], "the carrier was called with the transaction open"
    assert decision["_deferred_send"]["to_phone"] == "+919000000001"
    assert decision["_deferred_send"]["related_id"] == "TD-SMS-1"


class _Engine:
    """Engine duck-type: ``begin()`` is a savepoint on the test's connection."""

    def __init__(self, conn) -> None:
        self._conn = conn

    @contextmanager
    def begin(self):
        nested = self._conn.begin_nested()
        try:
            yield self._conn
            nested.commit()
        except BaseException:
            nested.rollback()
            raise


def _decision(db_tx, account) -> str:
    from datetime import datetime, timedelta, timezone

    from agent_core.treatment import actions as A, decisions

    return decisions.record(
        conn=db_tx,
        tenant_id="hdfc.retail",
        customer_id=account["customer_id"],
        account_id=account["id"],
        interaction_id=None,
        trigger_kind="dpd_tick",
        trigger_ref=None,
        mode="live",
        variant=None,
        recommender="ev",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_action=A.SMS,
        chosen_channel="sms",
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        expected_value=100.0,
        suppression_reason=None,
        rationale="probe",
        latency_ms=1,
    )


def _attempt(db_tx, decision_id: str) -> str:
    attempt_id = attempts.write_intent(
        db_tx, tenant_id="hdfc.retail", decision_id=decision_id, channel="sms", action="sms"
    )
    assert attempt_id, "write_intent refused; is enactment_attempts present?"
    return attempt_id


def _state(db_tx, attempt_id: str) -> str:
    return db_tx.execute(
        text("SELECT state FROM enactment_attempts WHERE id = :id"), {"id": attempt_id}
    ).scalar_one()


def test_a_sent_message_is_recorded_sent(db_tx, account, monkeypatch: pytest.MonkeyPatch) -> None:
    import twilio_sms

    monkeypatch.setattr(twilio_sms, "send", lambda **kw: {"sid": "SM-OK"})
    decision_id = _decision(db_tx, account)
    attempt_id = _attempt(db_tx, decision_id)
    decision = {
        "id": decision_id,
        "_attempt_id": attempt_id,
        "_reservation_id": None,
        "_deferred_send": {"to_phone": "+919000000001", "body": "x", "customer_id": "c",
                           "tenant_id": "hdfc.retail", "related_id": decision_id},
    }
    enact._send_deferred(_Engine(db_tx), decision)
    assert _state(db_tx, attempt_id) == attempts.STATE_SENT
    enacted = db_tx.execute(
        text("SELECT enacted, enacted_ref FROM treatment_decisions WHERE id = :id"),
        {"id": decision_id},
    ).mappings().one()
    assert enacted["enacted"] is True and enacted["enacted_ref"] == "sms:SM-OK"


def test_a_carrier_failure_after_the_commit_is_recorded_not_retried(
    db_tx, account, monkeypatch: pytest.MonkeyPatch
) -> None:
    import twilio_sms

    def _boom(**kw):
        raise RuntimeError("twilio 503")

    monkeypatch.setattr(twilio_sms, "send", _boom)
    decision_id = _decision(db_tx, account)
    attempt_id = _attempt(db_tx, decision_id)
    decision = {
        "id": decision_id,
        "_attempt_id": attempt_id,
        "_reservation_id": None,
        "_deferred_send": {"to_phone": "+919000000001", "body": "x", "customer_id": "c",
                           "tenant_id": "hdfc.retail", "related_id": decision_id},
    }
    enact._send_deferred(_Engine(db_tx), decision)
    # The attempt row -- the evidence -- survives the failure, marked as one.
    assert _state(db_tx, attempt_id) == attempts.STATE_FAILED
