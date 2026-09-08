"""W1 — truthful, idempotent enactment (unit + schema-gated db_real)."""

from __future__ import annotations

from pathlib import Path

from agent_core.treatment import attempts, cancel

BACKEND = Path(__file__).resolve().parents[1]


def test_idempotency_key_is_stable() -> None:
    a = attempts.idempotency_key("t1", "TD-1", "whatsapp")
    b = attempts.idempotency_key("t1", "TD-1", "whatsapp")
    assert a == b
    assert a != attempts.idempotency_key("t1", "TD-2", "whatsapp")


def test_cancel_reasons_are_the_eleven() -> None:
    assert len(cancel.REASONS) == 11
    assert cancel.PLAN_EXPIRED in cancel.PAGE_ON
    assert cancel.PAID_SINCE_DECISION not in cancel.PAGE_ON
    assert cancel.from_note("contact:cooling_off") == cancel.CONTACT_GATE_REFUSED
    assert cancel.from_note("no_executor:field_visit") == cancel.NO_EXECUTOR


def test_claim_uses_no_key_update() -> None:
    src = (BACKEND / "agent_core" / "treatment" / "decisions.py").read_text(
        encoding="utf-8"
    )
    assert "FOR NO KEY UPDATE SKIP LOCKED" in src
    assert "FOR UPDATE SKIP LOCKED" not in src.split("def insights")[0]


def test_process_one_splits_io_from_claim() -> None:
    src = (BACKEND / "agent_core" / "treatment" / "enact.py").read_text(encoding="utf-8")
    assert "attempts.write_intent" in src
    assert "QUEUED_ACTIONS" in src
    assert "kill_switch.enact_allowed" in src


def test_whatsapp_drain_reuses_decision_session_key() -> None:
    src = (BACKEND / "whatsapp_outbound.py").read_text(encoding="utf-8")
    assert 'session_key=job.get("decision_id")' in src


def test_campaign_ambiguous_dials_park() -> None:
    src = (BACKEND / "campaigns.py").read_text(encoding="utf-8")
    assert "parked" in src


def test_duplicate_send_invariant_over_ten_thousand_keys() -> None:
    seen: set[str] = set()
    sends = 0
    for i in range(10_000):
        key = attempts.idempotency_key("tenant", f"TD-{i}", "sms")
        if key in seen:
            continue
        seen.add(key)
        sends += 1
    assert sends == 10_000
    assert len(seen) == 10_000
