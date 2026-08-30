"""Defects found tracing one WhatsApp thread end to end (`conversation_trace.md`).

Every one of these is the same shape: nothing raises, nothing is logged as an
error, and the system presents state that is confident and wrong. A throttled
retrieval that answers 200 with yesterday's chips, a bot bubble that never
shipped wearing a delivered tick, an audit note holding a customer id, a
transcript where every turn happened at t=0 — none of them look like bugs from
the outside, which is exactly why they survived.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import db


# --- F16: a throttled refresh must say so, not serve stale chips -------------


def test_a_rate_limited_refresh_raises_instead_of_faking_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main.py` maps `RateLimitExceeded` to 429 and the inbox has copy for it.

    Neither ever fired. `kb_retrieve.retrieve` raises the throttle from inside
    the broad `except Exception` that exists to survive retrieval outages, so a
    throttled poll fell through to the stale-chip fallback and returned 200.
    The operator saw suggestions for a conversation that had moved on, with no
    indication they were old.
    """
    import kb_rate_limit
    import kb_retrieve

    monkeypatch.setattr(db, "_conversation_rag_query", lambda _c, _cid: "how do I pay")

    def _throttled(**_kwargs: object) -> dict[str, object]:
        raise kb_rate_limit.RateLimitExceeded("rate_limited:inbox:30/min")

    monkeypatch.setattr(kb_retrieve, "retrieve", _throttled)

    with pytest.raises(kb_rate_limit.RateLimitExceeded):
        db.refresh_conversation_suggestions("CV-SUSANTH-WA1")


def test_a_retrieval_outage_still_falls_back_to_persisted_chips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback is deliberate — only the throttle must escape it."""
    import kb_retrieve

    monkeypatch.setattr(db, "_conversation_rag_query", lambda _c, _cid: "how do I pay")

    def _down(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("azure is down")

    monkeypatch.setattr(kb_retrieve, "retrieve", _down)

    out = db.refresh_conversation_suggestions("CV-SUSANTH-WA1")
    assert isinstance(out["ragSuggestions"], list)


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
    import capture

    started = datetime(2026, 8, 23, 5, 0, 0, tzinfo=timezone.utc)
    at = started + timedelta(minutes=1, seconds=30, milliseconds=600)
    assert capture.elapsed_seconds(started, at) == 90


def test_elapsed_seconds_degrades_to_zero_rather_than_guessing() -> None:
    """A missing start is not an error; it is the pre-existing behaviour."""
    import capture

    at = datetime(2026, 8, 23, 5, 0, 0, tzinfo=timezone.utc)
    assert capture.elapsed_seconds(None, at) == 0
    assert capture.elapsed_seconds(at, None) == 0


def test_elapsed_seconds_never_goes_backwards() -> None:
    """Clock skew and back-dated seed rows must not produce a negative offset."""
    import capture

    started = datetime(2026, 8, 23, 5, 0, 0, tzinfo=timezone.utc)
    assert capture.elapsed_seconds(started, started - timedelta(minutes=5)) == 0


def test_elapsed_seconds_reads_naive_timestamps_as_utc() -> None:
    import capture

    started = datetime(2026, 8, 23, 5, 0, 0)
    at = datetime(2026, 8, 23, 5, 0, 45, tzinfo=timezone.utc)
    assert capture.elapsed_seconds(started, at) == 45


def test_the_whatsapp_bridge_no_longer_hard_codes_at_sec() -> None:
    """Voice computes real elapsed seconds; the WhatsApp bridge passed 0.

    Both turns of every live WhatsApp exchange sat at t=0, so any analysis
    keyed on `at_sec` — pacing, dead air, time-to-first-answer — was degenerate
    for the entire channel while looking perfectly well-formed.
    """
    import inspect

    import bot_runtime

    src = inspect.getsource(bot_runtime._handle_turn)
    assert "at_sec=0," not in src, "a literal 0 offset is the bug"
    assert "elapsed_seconds" in src


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

    yesterday = (date.today() - timedelta(days=1)).isoformat()
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

    assert domain._promise_date_is_past(date.today().isoformat()) is False
    assert domain._promise_date_is_past((date.today() + timedelta(days=3)).isoformat()) is False
    assert domain._promise_date_is_past((date.today() - timedelta(days=1)).isoformat()) is True


# --- F38: an allowlist that cannot resolve its card must deny ---------------


def _handoff_ctx(bot_id: str | None):
    import bot_tools

    return bot_tools.ToolContext(
        job_id="JOB-TRACE-1",
        conversation_id="CV-SUSANTH-WA1",
        customer_id="CUST-1001",
        interaction_id=None,
        bot_id=bot_id,
        customer_text="put me through to someone else",
        intent="other",
    )


def test_an_unresolvable_card_denies_handoff_rather_than_allowing_every_bot() -> None:
    """`allowlist=None` means *unrestricted* to the handoff tool.

    That is what an unknown bot id produced: `card_for` raised, the allowlist
    was set to None, and the check skipped itself — so every registered bot
    became a legal transfer target at exactly the moment the running identity
    was misconfigured. A compliance control that disappears when configuration
    drifts is worse than no control, because the dashboard still shows it on.
    """
    import bot_tools

    ctx = _handoff_ctx("no-such-bot-in-this-deployment")
    out = bot_tools._tool_handoff_to_agent(
        ctx, {"target_bot_id": "some-other-bot", "reason": "specialist"}
    )
    assert out["ok"] is False
    assert out["error"] == "handoff_not_allowlisted"


def test_a_missing_bot_id_also_denies() -> None:
    import bot_tools

    ctx = _handoff_ctx(None)
    out = bot_tools._tool_handoff_to_agent(
        ctx, {"target_bot_id": "some-other-bot", "reason": "specialist"}
    )
    assert out["ok"] is False
    assert out["error"] == "handoff_not_allowlisted"


def test_the_live_card_governs_the_allowlist_not_the_env_bot_id() -> None:
    """The turn ran on the card in the bundle; that card owns its handoffs.

    Re-resolving the allowlist from `BOT_ID` meant the published card's targets
    were ignored whenever the environment variable and the card the turn
    actually used diverged — which is the live state on this deployment.
    """
    import bot_tools
    from agent_core.cards.defaults import card_for

    # A real published card, with this deployment's own handoff targets — the
    # clone-card shape the trace found live.
    card = card_for("kaia-v2-4").model_dump(mode="json")
    card["handoffs"] = [
        {"to_bot_id": "insurance-specialist-v1", "payload_schema": {}, "when": "policy questions"}
    ]

    ctx = _handoff_ctx("kaia-v2-4")
    ctx.agent_card = card
    denied = bot_tools._tool_handoff_to_agent(
        ctx, {"target_bot_id": "insurance-v1", "reason": "specialist"}
    )
    assert denied["error"] == "handoff_not_allowlisted", (
        "insurance-v1 is on the *built-in* card; the live card is what governs"
    )

    allowed = bot_tools._tool_handoff_to_agent(
        ctx, {"target_bot_id": "insurance-specialist-v1", "reason": "specialist"}
    )
    # No interaction on this context, so the transfer stops one step later —
    # past the allowlist, which is the gate under test.
    assert allowed["error"] == "no_interaction"
