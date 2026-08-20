"""Where live QA meets the rest of the product."""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db
from agent_core.live_qa.enact import barge_audio, provider_call_id, whisper_correction
from agent_core.live_qa.scorecard import LIVE_NOTE_PREFIX, is_live_locked
from voice import persist


TENANT = "hdfc.retail"


@pytest.fixture
def interaction(db_tx):
    row = db_tx.execute(
        text(
            """
            SELECT i.id, i.customer_id, i.account_id, i.handler_bot_id
            FROM interactions i
            WHERE i.tenant_id = :t AND i.handler_kind = 'bot'
            ORDER BY i.started_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"t": TENANT},
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no bot interaction")
    return dict(row)


def test_new_flags_map_to_rules() -> None:
    assert persist.rule_for_flag("hours-breach") == "r-dnd-win"
    assert persist.rule_for_flag("identity-before-verify") == "r-verify"
    assert persist.rule_for_flag("missing-mini-miranda") == "r-mm"
    assert persist.rule_for_flag("third-party-leak") == "r-third"
    assert persist.rule_for_flag("opt-out-ignored") == "r-dnd-disc"
    assert persist.rule_for_flag("rate-quoted") == "r-false"


def test_barge_without_call_sid_is_crm_only(interaction) -> None:
    assert provider_call_id(interaction["id"]) is None
    result = barge_audio(interaction["id"], reason="test")
    assert result["audio"] is False
    assert result["reason"] == "no_call_sid"


def test_whisper_correction_is_a_developer_message() -> None:
    c = whisper_correction("Do not quote a waiver")
    assert c is not None
    msg = c.to_message()
    assert msg["role"] == "developer"
    assert "waiver" in msg["content"]
    assert c.kind == "whisper"


def test_live_note_is_locked() -> None:
    assert is_live_locked("[live] Recording notice missing")
    assert not is_live_locked("model guessed this")
    assert LIVE_NOTE_PREFIX == "[live]"


def test_evaluate_and_flag_writes_hours_and_identity(db_tx, interaction, monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")
    flags = persist.evaluate_and_flag_bot_turn(
        interaction_id=interaction["id"],
        customer_text="hello",
        bot_text="Your outstanding is ₹12,400.",
        intent="payment_inquiry",
        guardrails={"alwaysDiscloseRecording": False},
        turn_index=3,
        elapsed_seconds=40,
        customer_bot_exchanges=2,
        identity_verified=False,
        third_party=False,
        channel="voice",
        customer_id=interaction["customer_id"],
        account_id=interaction["account_id"],
        now_hour=11,
    )
    assert "identity-before-verify" in flags
    stored = [
        r[0]
        for r in db_tx.execute(
            text("SELECT flag FROM interaction_flags WHERE interaction_id = :id"),
            {"id": interaction["id"]},
        ).fetchall()
    ]
    assert "identity-before-verify" in stored
    rule = db_tx.execute(
        text(
            """
            SELECT rule_id FROM violations
            WHERE interaction_id = :id AND rule_id = 'r-verify'
            """
        ),
        {"id": interaction["id"]},
    ).scalar()
    assert rule == "r-verify"


def test_whatsapp_after_hours_does_not_file_hours(db_tx, interaction, monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")
    flags = persist.evaluate_and_flag_bot_turn(
        interaction_id=interaction["id"],
        customer_text="hi",
        bot_text="Thanks, noted.",
        intent="out_of_scope",
        guardrails={},
        turn_index=1,
        elapsed_seconds=5,
        customer_bot_exchanges=1,
        identity_verified=True,
        channel="whatsapp",
        customer_id=interaction["customer_id"],
        now_hour=21,
    )
    assert "hours-breach" not in flags


def test_coverage_endpoint_shape(db_tx) -> None:
    stats = db.qa_coverage_stats(days=7)
    assert "coverage" in stats
    assert stats["windowDays"] == 7
    assert stats["completed"] >= 0
    assert stats["scored"] >= 0


def test_voice_after_hours_files_dnd_window(db_tx, interaction, monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")
    flags = persist.evaluate_and_flag_bot_turn(
        interaction_id=interaction["id"],
        customer_text="hello",
        bot_text="Just checking in.",
        intent="out_of_scope",
        guardrails={},
        turn_index=2,
        elapsed_seconds=20,
        customer_bot_exchanges=1,
        identity_verified=True,
        channel="voice",
        customer_id=interaction["customer_id"],
        now_hour=19,
    )
    assert "hours-breach" in flags
    assert "live-qa-auto-barge" not in flags
    stored = [
        r[0]
        for r in db_tx.execute(
            text("SELECT flag FROM interaction_flags WHERE interaction_id = :id"),
            {"id": interaction["id"]},
        ).fetchall()
    ]
    assert "hours-breach" in stored
    assert "live-qa-auto-barge" not in stored
    rule = db_tx.execute(
        text(
            """
            SELECT rule_id FROM violations
            WHERE interaction_id = :id AND rule_id = 'r-dnd-win'
            """
        ),
        {"id": interaction["id"]},
    ).scalar()
    assert rule == "r-dnd-win"


def test_third_party_dues_files_r_third(db_tx, interaction, monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")
    flags = persist.evaluate_and_flag_bot_turn(
        interaction_id=interaction["id"],
        customer_text="this is not my account",
        bot_text="The EMI is ₹8,200 this month.",
        intent="payment_inquiry",
        guardrails={},
        turn_index=2,
        elapsed_seconds=25,
        customer_bot_exchanges=1,
        identity_verified=True,
        third_party=True,
        channel="voice",
        customer_id=interaction["customer_id"],
        now_hour=11,
    )
    assert "third-party-leak" in flags
    rule = db_tx.execute(
        text(
            """
            SELECT rule_id FROM violations
            WHERE interaction_id = :id AND rule_id = 'r-third'
            """
        ),
        {"id": interaction["id"]},
    ).scalar()
    assert rule == "r-third"


def test_authority_cap_is_a_barge_recommend(db_tx, interaction, monkeypatch) -> None:
    monkeypatch.setattr("agent_core.live_qa.decisions.record", lambda **_k: "LQ-TEST")
    flags = persist.evaluate_and_flag_bot_turn(
        interaction_id=interaction["id"],
        customer_text="can you waive the late fee",
        bot_text="I can waive ₹2000 for you.",
        intent="waiver_request",
        guardrails={"neverPromiseWaiver": False},
        turn_index=3,
        elapsed_seconds=40,
        customer_bot_exchanges=2,
        identity_verified=True,
        channel="voice",
        customer_id=interaction["customer_id"],
        max_waiver_inr=400.0,
        now_hour=11,
    )
    assert "authority-cap-exceeded" in flags
    assert "live-qa-auto-barge" not in flags


def test_barge_audio_reuses_warm_transfer(monkeypatch) -> None:
    called = {}

    monkeypatch.setattr(
        "agent_core.live_qa.enact.provider_call_id",
        lambda *_a, **_k: "CA123",
    )

    def _warm(sid, reason=""):
        called["sid"] = sid
        called["reason"] = reason
        return {"conference": "CF1", "callSid": sid}

    monkeypatch.setattr("voice.twilio_ops.warm_transfer_to_supervisor", _warm)
    result = barge_audio("IX-1", reason="hours-breach")
    assert result["audio"] is True
    assert called["sid"] == "CA123"
    assert called["reason"] == "hours-breach"


def test_pack_is_tenant_scoped(db_tx) -> None:
    from agent_core.live_qa.pack import build_pack

    db_tx.execute(text("INSERT INTO tenants (id, name) VALUES ('rival.bank', 'Rival Bank')"))
    db_tx.execute(
        text("INSERT INTO users (id, tenant_id, name) VALUES ('rv-qa-user', 'rival.bank', 'Rival Agent')")
    )
    db_tx.execute(
        text(
            """
            INSERT INTO customers (id, tenant_id, name, risk)
            VALUES ('rv-qa-cust', 'rival.bank', 'Rival', 'low')
            """
        )
    )
    db_tx.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, handler_kind, handler_user_id, channel, status)
            VALUES ('rv-qa-ix', 'rival.bank', 'rv-qa-cust', 'human', 'rv-qa-user', 'voice', 'completed')
            """
        )
    )
    assert build_pack("rv-qa-ix") is None
    own = db_tx.execute(
        text("SELECT id FROM interactions WHERE tenant_id = :t LIMIT 1"),
        {"t": TENANT},
    ).scalar()
    pack = build_pack(own)
    assert pack is not None
    assert pack["interactionId"] == own
