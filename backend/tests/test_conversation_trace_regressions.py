"""Defects found tracing one WhatsApp thread end to end (`conversation_trace.md`).

Every one of these is the same shape: nothing raises, nothing is logged as an
error, and the system presents state that is confident and wrong. A throttled
retrieval that answers 200 with yesterday's chips, a bot bubble that never
shipped wearing a delivered tick, an audit note holding a customer id, a
transcript where every turn happened at t=0 — none of them look like bugs from
the outside, which is exactly why they survived.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent_core import clock
import pytest
from sqlalchemy import text

import db
import db_inbox_rag


# --- F16: a throttled refresh must say so, not serve stale chips -------------


# --- F8b: a forged signature is a 403, never a 500 --------------------------


def test_a_non_ascii_signature_header_is_rejected_not_crashed() -> None:
    """`hmac.compare_digest` raises TypeError on a non-ASCII `str`.

    The header is attacker-controlled, so one byte above 0x7f turned a 403 into
    an unhandled 500. Fail-closed either way, but it pollutes 5xx alerting with
    something that is simply a bad signature.
    """
    import whatsapp

    assert whatsapp.verify_signature("s3cret", b"{}", "sha256=café") is False


def test_a_valid_signature_still_verifies() -> None:
    import hashlib
    import hmac as _hmac

    import whatsapp

    body = b'{"entry":[]}'
    good = _hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert whatsapp.verify_signature("s3cret", body, f"sha256={good}") is True
    assert whatsapp.verify_signature("s3cret", body, f"sha256={good[:-1]}0") is False


# --- F15: an audit note is a note, not a customer id ------------------------


def test_an_activity_row_without_a_note_leaves_the_note_empty(db_tx) -> None:
    """`note or customer_id` put `CUST-…` in the notes column of every takeover.

    `activity_events.note` is rendered as a human note on the customer
    timeline, the disputes timeline and the violations feed. Every takeover,
    return-to-bot and inbound event carried an id there instead.
    """
    entity_id = "CV-TRACE-NOTE-TEST"
    db.record_activity(
        db_tx,
        "conversation",
        entity_id,
        "conversation_takeover",
        "Took over from bot",
        None,
        "CUST-1001",
    )
    row = (
        db_tx.execute(
            text("SELECT note, payload FROM activity_events WHERE entity_id = :e"),
            {"e": entity_id},
        )
        .mappings()
        .first()
    )
    assert row is not None
    assert row["note"] is None, "an event with no note must not borrow the customer id"
    assert row["payload"].get("customerId") == "CUST-1001", (
        "the customer id is still worth keeping — it belongs in payload, not note"
    )


def test_a_real_note_is_preserved(db_tx) -> None:
    entity_id = "CV-TRACE-NOTE-TEST-2"
    db.record_activity(
        db_tx,
        "conversation",
        entity_id,
        "message_sent",
        "Agent reply sent",
        "hi there",
        "CUST-1001",
    )
    row = (
        db_tx.execute(
            text("SELECT note, payload FROM activity_events WHERE entity_id = :e"),
            {"e": entity_id},
        )
        .mappings()
        .first()
    )
    assert row["note"] == "hi there"
    assert row["payload"].get("customerId") == "CUST-1001"


# --- F1/F3: a transcript where everything happens at t=0 ---------------------


def test_elapsed_seconds_measures_from_the_interaction_start() -> None:
    import capture_events

    started = datetime(2026, 8, 23, 5, 0, 0, tzinfo=timezone.utc)
    at = started + timedelta(minutes=1, seconds=30, milliseconds=600)
    assert capture_events.elapsed_seconds(started, at) == 90


def test_elapsed_seconds_degrades_to_zero_rather_than_guessing() -> None:
    """A missing start is not an error; it is the pre-existing behaviour."""
    import capture_events

    at = datetime(2026, 8, 23, 5, 0, 0, tzinfo=timezone.utc)
    assert capture_events.elapsed_seconds(None, at) == 0
    assert capture_events.elapsed_seconds(at, None) == 0


def test_elapsed_seconds_never_goes_backwards() -> None:
    """Clock skew and back-dated seed rows must not produce a negative offset."""
    import capture_events

    started = datetime(2026, 8, 23, 5, 0, 0, tzinfo=timezone.utc)
    assert capture_events.elapsed_seconds(started, started - timedelta(minutes=5)) == 0


def test_elapsed_seconds_reads_naive_timestamps_as_utc() -> None:
    import capture_events

    started = datetime(2026, 8, 23, 5, 0, 0)
    at = datetime(2026, 8, 23, 5, 0, 45, tzinfo=timezone.utc)
    assert capture_events.elapsed_seconds(started, at) == 45


# --- F27: an unknown delivery state is unknown, not delivered ---------------


def test_an_unknown_delivery_state_shows_no_tick() -> None:
    """The fallback asserted delivery for rows that had never been sent.

    A seeded bot bubble with a NULL `delivery_status` rendered the same tick as
    a message Meta had confirmed. There is no CHECK on the column, so anything
    unrecognised landed here too.
    """
    assert db._inbox_delivery(None, "bot") is None
    assert db._inbox_delivery("", "bot") is None
    assert db._inbox_delivery("queued_by_some_future_writer", "agent") is None


def test_known_delivery_states_are_untouched() -> None:
    for status in ("sent", "delivered", "read", "failed"):
        assert db._inbox_delivery(status, "bot") == status
    assert db._inbox_delivery("sending", "bot") == "pending"
    assert db._inbox_delivery("cancelled", "bot") is None


# --- F43: a promise for a date that has already passed ----------------------


def test_a_promise_for_yesterday_is_refused() -> None:
    """The pay link's expiry is the promised day + 1 at 23:59 IST.

    A past date therefore mints a link that is already dead — the customer gets
    a URL that the next settle tick breaks, and the CRM records a promise that
    was unkeepable the moment it was written.
    """
    from agent_core.tools import create_promise_to_pay

    yesterday = (clock.today_local() - timedelta(days=1)).isoformat()
    result = create_promise_to_pay(
        customer_id="CUST-1001",
        amount=1000.0,
        promised_date=yesterday,
        channel="whatsapp",
    )
    assert result.ok is False
    assert result.error == "promise_date_in_past"


def test_a_promise_for_today_is_still_allowed() -> None:
    """Today is a real promise — the link lives until tomorrow 23:59 IST."""
    from agent_core.tools import domain

    assert domain._promise_date_is_past(clock.today_local().isoformat()) is False
    assert domain._promise_date_is_past((clock.today_local() + timedelta(days=3)).isoformat()) is False
    assert domain._promise_date_is_past((clock.today_local() - timedelta(days=1)).isoformat()) is True


def test_a_retrieval_outage_shows_the_last_passages_and_says_they_are_stale(
    db_tx, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A knowledge-base outage degrades to the last persisted passages, never an
    error -- and says they are last time's, not answers to this turn."""
    import uuid

    from sqlalchemy import text

    import voice_studio

    tag = uuid.uuid4().hex[:8].upper()
    cid, cv = f"CUST-RAG-{tag}", f"CV-RAG-{tag}"
    db_tx.execute(
        text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, 'RAG Fixture', 'low')"),
        {"id": cid, "t": db.current_tenant()},
    )
    db_tx.execute(
        text(
            "INSERT INTO interactions (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel, status) "
            "VALUES (:id, :t, :c, 'bot', (SELECT id FROM bots ORDER BY id LIMIT 1), 'whatsapp', 'active')"
        ),
        {"id": f"IX-RAG-{tag}", "t": db.current_tenant(), "c": cid},
    )
    db_tx.execute(
        text(
            "INSERT INTO conversations (id, interaction_id, customer_id, status, channel) "
            "VALUES (:id, :ix, :c, 'bot', 'whatsapp')"
        ),
        {"id": cv, "ix": f"IX-RAG-{tag}", "c": cid},
    )
    db_tx.execute(
        text(
            "INSERT INTO ai_response_suggestions (id, conversation_id, suggestion_text, source, accepted) "
            "VALUES (:id, :cv, 'Payments — How to pay', 'kb', false)"
        ),
        {"id": f"SUG-{tag}", "cv": cv},
    )
    monkeypatch.setattr(db_inbox_rag, "_conversation_rag_query", lambda _c, _cid: "how do I pay")

    def _down(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        raise RuntimeError("engine is down")

    monkeypatch.setattr(voice_studio, "kb_search", _down)

    out = db.refresh_conversation_suggestions(cv)
    assert out["ragSuggestions"] == ["Payments — How to pay"]
    assert out["stale"] is True
