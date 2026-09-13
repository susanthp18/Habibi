"""Domain CRM handlers — shared voice/WhatsApp write path."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from agent_core import clock
import pytest


def _customer(db_tx) -> tuple[str, str | None]:
    from sqlalchemy import text

    row = db_tx.execute(
        text(
            """
            SELECT c.id, a.id AS account_id
            FROM customers c
            LEFT JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
              AND NOT EXISTS (SELECT 1 FROM promises p WHERE p.account_id = a.id
                              AND p.status IN ('upcoming','due_today'))
            ORDER BY c.id
            LIMIT 1
            """
        )
    ).mappings().first()
    if not row:
        pytest.skip("no customers seeded")
    return row["id"], row["account_id"]


def test_create_promise_idempotent_via_domain(db_tx) -> None:
    from agent_core.tools import create_promise_to_pay

    customer_id, account_id = _customer(db_tx)
    promised = (clock.today_local() + timedelta(days=9)).isoformat()
    key = f"domain-ptp-{uuid.uuid4().hex}"
    first = create_promise_to_pay(
        customer_id=customer_id,
        amount=77.0,
        promised_date=promised,
        account_id=account_id,
        channel="whatsapp",
        idempotency_key=key,
    )
    second = create_promise_to_pay(
        customer_id=customer_id,
        amount=77.0,
        # Alias shape — shared handler must normalize.
        promised_date=f"{promised}T00:00:00Z",
        account_id=account_id,
        channel="whatsapp",
        idempotency_key=key,
    )
    assert first.ok and second.ok
    assert first.data["promiseId"] == second.data["promiseId"]
    assert first.data["promisedDate"] == promised
    assert "http://" not in (first.spoken_summary or "").lower()
    assert "https://" not in (first.spoken_summary or "").lower()


def test_flag_dispute_invalid_type_structured(db_tx) -> None:
    from agent_core.tools import flag_dispute
    from agent_core.tools.catalog import DISPUTE_TYPES

    customer_id, _ = _customer(db_tx)
    result = flag_dispute(
        customer_id=customer_id,
        dispute_type="not-a-real-type",
    )
    assert result.ok is False
    assert result.error == "invalid_dispute_type"
    assert result.data.get("allowed") == list(DISPUTE_TYPES)


def test_request_callback_rejects_bad_scheduled_at(db_tx) -> None:
    from agent_core.tools import request_callback
    from sqlalchemy import text

    customer_id, _ = _customer(db_tx)
    before = db_tx.execute(text("SELECT count(*) FROM callbacks")).scalar() or 0
    result = request_callback(
        customer_id=customer_id,
        scheduled_at="next Tuesday maybe",
    )
    assert result.ok is False
    assert result.error == "invalid_scheduled_at"
    after = db_tx.execute(text("SELECT count(*) FROM callbacks")).scalar() or 0
    assert after == before


def test_request_callback_accepts_iso_and_clamps_window(db_tx) -> None:
    from agent_core.tools import request_callback

    customer_id, account_id = _customer(db_tx)
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    result = request_callback(
        customer_id=customer_id,
        account_id=account_id,
        scheduled_at=when,
        reason="not_in_enum_so_general",
        window_mins=999,
    )
    assert result.ok
    assert result.data["reason"] == "general"
    assert result.data["windowMins"] == 120
    assert result.data.get("callbackId")


def test_whatsapp_flag_dispute_returns_allowed_no_traceback(
    db_tx, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WA adapter must surface domain `allowed` list — not raise ValueError."""
    import logging

    import bot_tools
    import agent_core.tools.gates as gates
    from agent_core.tools.catalog import DISPUTE_TYPES

    customer_id, _ = _customer(db_tx)
    ctx = bot_tools.ToolContext(
        job_id="job-test-dispute",
        conversation_id="cv-test",
        interaction_id=None,
        customer_id=customer_id,
        bot_id=None,
        customer_text="",
        intent="dispute",
    )
    ctx.allowed_tools = frozenset({"flag_dispute"})
    # Identity is a level now, not a flag: `flag_dispute` is a regulated act and
    # asks for `challenge`. This test is about the domain rejection underneath,
    # so grant the strongest level and let the handler do the refusing.
    monkeypatch.setattr(
        gates, "interaction_assurance", lambda **_kwargs: gates.LEVEL_CHALLENGE
    )
    with caplog.at_level(logging.WARNING):
        ok, payload, _latency = bot_tools.execute_tool(
            ctx, "flag_dispute", '{"type":"bogus"}'
        )
    # Soft domain reject: tuple success follows payload.ok, without traceback.
    assert ok is False
    assert payload.get("ok") is False
    assert payload.get("error") == "invalid_dispute_type"
    assert payload.get("allowed") == list(DISPUTE_TYPES)
    assert not any(r.exc_info for r in caplog.records)
    assert any("rejected" in (r.message or "") for r in caplog.records)


def test_capture_lead_blocked_writes_no_row(db_tx, monkeypatch: pytest.MonkeyPatch) -> None:
    """eligibility_blocked must not call create_lead."""
    from agent_core.tools import capture_lead
    import capture as capture_mod

    customer_id, _ = _customer(db_tx)

    def _block_flags(*_a, **_k):
        return [{"label": "kyc", "passed": False, "reason": "blocked", "status": "fail"}]

    monkeypatch.setattr(capture_mod, "evaluate_product_eligibility", _block_flags)
    monkeypatch.setattr(capture_mod, "eligibility_blocks_capture", lambda _flags: "kyc_stale")

    called = {"n": 0}

    def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("create_lead must not run when blocked")

    import db

    monkeypatch.setattr(db, "create_lead", _boom)

    # Need a real product id for the SELECT; fall back to skip.
    from sqlalchemy import text

    product = db_tx.execute(text("SELECT id FROM products ORDER BY id LIMIT 1")).scalar()
    if not product:
        pytest.skip("no products seeded")

    result = capture_lead(
        customer_id=customer_id,
        product_id=str(product),
        source="bot_chat",
    )
    assert result.ok is False
    assert result.error == "eligibility_blocked"
    assert called["n"] == 0


def test_a_promise_datetime_is_the_tenant_day_not_the_utc_day(monkeypatch) -> None:
    """`2026-09-12T23:30:00Z` is already the 13th in India. The parser used to
    split the string at `T` and record the 12th -- a promise a day earlier
    than the borrower meant, and a pay link that expired a day early."""
    from agent_core.tools.domain import _parse_promise_date

    monkeypatch.setenv("APP_TIMEZONE", "Asia/Kolkata")
    assert _parse_promise_date("2026-09-12T23:30:00Z") == "2026-09-13"
    assert _parse_promise_date("2026-09-12T23:30:00+05:30") == "2026-09-12"
    # A naive datetime is tenant-local, the same reading as a callback time.
    assert _parse_promise_date("2026-09-12T23:30:00") == "2026-09-12"
    assert _parse_promise_date("2026-09-12") == "2026-09-12"
    assert _parse_promise_date("not-a-date") is None
