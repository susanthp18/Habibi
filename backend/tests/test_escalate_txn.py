"""Escalate single-txn + AMD helpers."""

from __future__ import annotations

import pytest
from sqlalchemy import text


def _seed_interaction(conn, customer_id: str, account_id: str) -> str:
    import db

    ix = f"IX-ESC-{customer_id.replace('-', '')[-8:]}"
    conn.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, account_id, channel, direction, status,
              handler_kind, handler_bot_id, started_at, created_at, updated_at
            ) VALUES (
              :id, 'hdfc.retail', :cid, :aid, 'voice', 'inbound', 'active',
              'bot', :bot_id, now(), now(), now()
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": ix, "cid": customer_id, "aid": account_id, "bot_id": db.DEFAULT_BOT_ID},
    )
    return ix


def test_escalate_voice_interaction_one_txn(db_tx) -> None:
    import db

    cust = db_tx.execute(
        text("SELECT id FROM customers ORDER BY id LIMIT 1")
    ).scalar()
    acct = db_tx.execute(
        text("SELECT id FROM accounts WHERE customer_id = :c ORDER BY id LIMIT 1"),
        {"c": cust},
    ).scalar()
    if not cust or not acct:
        pytest.skip("no customers")
    ix = _seed_interaction(db_tx, str(cust), str(acct))

    result = db.escalate_voice_interaction(
        interaction_id=ix,
        reason="customer_requested",
        bot_id=db.DEFAULT_BOT_ID,
        customer_id=str(cust),
        note_text="[escalation] wants supervisor",
        route_context={
            "channel": "voice",
            "intent": "customer_requested",
            "sentiment": "frustrated",
            "dpd": 45,
            "product": "PL",
            "verification_status": "verified",
            "overdue_amount": 1000,
            "turn_count": 3,
            "guardrail_flag": "none",
            "consent_dnd": False,
        },
    )
    assert result.get("conversationId")
    assert result.get("handoffId")
    # Handoff + conversation + alert all exist inside the rolled-back fixture txn.
    n_ho = db_tx.execute(
        text("SELECT count(*) FROM interaction_handoffs WHERE interaction_id = :ix"),
        {"ix": ix},
    ).scalar()
    n_cv = db_tx.execute(
        text("SELECT count(*) FROM conversations WHERE interaction_id = :ix"),
        {"ix": ix},
    ).scalar()
    n_al = db_tx.execute(
        text("SELECT count(*) FROM live_alerts WHERE interaction_id = :ix AND kind = 'escalation'"),
        {"ix": ix},
    ).scalar()
    assert int(n_ho or 0) >= 1
    assert int(n_cv or 0) >= 1
    assert int(n_al or 0) >= 1


def test_amd_only_on_outbound_twilio() -> None:
    from voice.amd import should_enable_amd

    assert should_enable_amd({"twilio_params": {"call_type": "outbound"}}, is_twilio=True)
    assert not should_enable_amd({"twilio_params": {"call_type": "inbound"}}, is_twilio=True)
    assert not should_enable_amd({"twilio_params": {"call_type": "outbound"}}, is_twilio=False)
