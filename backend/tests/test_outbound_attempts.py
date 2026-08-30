"""The attempt ledger and the Closer — O0 and O1 of the outbound engine.

What these tests defend, in order of how much it would cost to get wrong:

* **An unanswered dial leaves a row.** The whole reason the table exists. Every
  outbound metric in the product — answer rate, right-party-contact rate,
  best-time-to-call, cost per connect — is a query over this table and was
  uncomputable before it, because ``interactions`` is only created when media
  connects.
* **The carrier's callbacks are unordered and repeated.** Twilio retries and
  does not guarantee ordering, so the state machine has to be monotonic. A late
  ``ringing`` overwriting a ``completed`` would silently corrupt talk time and
  double-count reach.
* **A refused attempt is still a row.** Otherwise the denial rate — the single
  most useful number in a compliance review — stays a log-grep.
* **The model may add an outcome, never remove one.** A refusal the agent
  recorded is a fact; an LLM that softens it is editing the record.
* **A summary with an invented number is thrown away.** The same fence
  ``rerank.py`` puts on rationales.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import call_closer
import outbound


TEST_PHONE = "919655282324"


def _a_customer(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id, a.id AS account_id
            FROM customers c
            LEFT JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer")
    return dict(row)


def _reserve(conn, **kw) -> dict:
    cust = _a_customer(conn)
    params = {
        "customer_id": cust["id"],
        "to_phone": TEST_PHONE,
        "objective": "dpd_reminder",
        "account_id": cust["account_id"],
    }
    params.update(kw)
    attempt = outbound.reserve(conn, **params)
    assert attempt is not None
    return attempt


def _state(conn, attempt_id: str) -> str:
    return conn.execute(
        text("SELECT state FROM call_attempts WHERE id = :id"), {"id": attempt_id}
    ).scalar()


# ---------------------------------------------------------------------------
# Reserve / suppress
# ---------------------------------------------------------------------------


def test_a_dial_that_is_never_placed_still_leaves_evidence(db_tx) -> None:
    """The row precedes the carrier call, not the other way round.

    A crash between the contact gate and Twilio used to spend a borrower's
    daily contact budget with nothing recording what spent it.
    """
    attempt = _reserve(db_tx)
    row = outbound.get(db_tx, attempt["id"])
    assert row is not None
    assert row["state"] == outbound.STATE_RESERVED
    assert row["placed_at"] is None
    assert row["provider_call_id"] is None


def test_the_gate_saying_no_is_a_row_not_a_log_line(db_tx) -> None:
    attempt = _reserve(db_tx)
    outbound.suppress(db_tx, attempt["id"], "outside_calling_hours")
    row = outbound.get(db_tx, attempt["id"])
    assert row["state"] == outbound.STATE_SUPPRESSED
    assert row["suppressed_reason"] == "outside_calling_hours"
    assert row["ended_at"] is not None


def test_the_borrowers_number_is_not_stored_again(db_tx) -> None:
    """A second copy of borrower PII with its own retention argument."""
    attempt = _reserve(db_tx)
    row = outbound.get(db_tx, attempt["id"])
    assert TEST_PHONE not in str(row["to_phone_hash"])
    assert row["to_phone_last4"] == "2324"
    assert row["to_phone_hash"] == outbound.phone_hash(TEST_PHONE)
    # Same number, same key — grouping attempts by destination has to work.
    assert outbound.phone_hash("+91 96552 82324") == outbound.phone_hash(TEST_PHONE)


def test_a_suppressed_attempt_does_not_consume_a_retry(db_tx) -> None:
    """``attempt_no`` feeds the cadence's ``max_attempts``.

    Counting an attempt the gate refused would let a busy Tuesday silently
    exhaust a borrower's retry budget without anyone's phone ever ringing.
    """
    first = _reserve(db_tx, decision_id=None)
    outbound.suppress(db_tx, first["id"], "daily_cap")
    second = _reserve(db_tx, decision_id=None)
    assert second["attemptNo"] == first["attemptNo"]


# ---------------------------------------------------------------------------
# The carrier state machine
# ---------------------------------------------------------------------------


def _place(conn, attempt: dict, sid: str) -> None:
    conn.execute(
        text(
            """
            UPDATE call_attempts
            SET state = 'dialing', placed_at = now(), provider_call_id = :sid
            WHERE id = :id
            """
        ),
        {"id": attempt["id"], "sid": sid},
    )


def test_a_ring_out_is_recorded_as_a_ring_out(db_tx) -> None:
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-NOANSWER")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-NOANSWER", status="no-answer"
    )
    row = outbound.get(db_tx, attempt["id"])
    assert row["state"] == outbound.STATE_NO_ANSWER
    assert row["ended_at"] is not None
    assert row["answered_at"] is None


def test_status_callbacks_are_order_insensitive(db_tx) -> None:
    """Twilio does not order them. A late ``ringing`` must not reopen a call."""
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-ORDER")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-ORDER", status="completed", duration_sec=91
    )
    outbound.apply_provider_status(db_tx, provider_call_id="CA-TEST-ORDER", status="ringing")
    row = outbound.get(db_tx, attempt["id"])
    assert row["state"] == outbound.STATE_COMPLETED
    assert row["talk_sec"] == 91


def test_a_repeated_terminal_callback_does_not_restamp_the_call(db_tx) -> None:
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-RETRY")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-RETRY", status="completed", duration_sec=45
    )
    first_end = outbound.get(db_tx, attempt["id"])["ended_at"]
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-RETRY", status="completed", duration_sec=9999
    )
    row = outbound.get(db_tx, attempt["id"])
    assert row["ended_at"] == first_end
    assert row["talk_sec"] == 45


def test_a_dead_number_is_told_apart_from_a_carrier_wobble(db_tx) -> None:
    """One retires the phone slot; the other is retried. Same Twilio status."""
    dead = _reserve(db_tx)
    _place(db_tx, dead, "CA-TEST-DEAD")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-DEAD", status="failed", error_code="21211"
    )
    assert _state(db_tx, dead["id"]) == outbound.STATE_INVALID_NUMBER

    wobble = _reserve(db_tx)
    _place(db_tx, wobble, "CA-TEST-WOBBLE")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-WOBBLE", status="failed", error_code="31000"
    )
    assert _state(db_tx, wobble["id"]) == outbound.STATE_FAILED


def test_an_unknown_call_id_is_not_an_error(db_tx) -> None:
    """Inbound calls have no attempt row, and a 4xx here earns a retry storm."""
    assert (
        outbound.apply_provider_status(
            db_tx, provider_call_id="CA-NOT-OURS", status="completed"
        )
        is None
    )


def test_the_carriers_machine_verdicts_collapse_to_one_word(db_tx) -> None:
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-AMD")
    outbound.apply_provider_status(
        db_tx,
        provider_call_id="CA-TEST-AMD",
        status="completed",
        duration_sec=18,
        answered_by="machine_end_beep",
    )
    assert outbound.get(db_tx, attempt["id"])["answered_by"] == "machine"


# ---------------------------------------------------------------------------
# Runtime signals
# ---------------------------------------------------------------------------


def test_media_connecting_joins_the_dial_to_the_conversation(db_tx) -> None:
    """Without this the call and the attempt sit in two tables with no join."""
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-BIND")
    interaction_id = db_tx.execute(
        text("SELECT id FROM interactions ORDER BY created_at DESC LIMIT 1")
    ).scalar()
    if not interaction_id:
        pytest.skip("no seeded interaction")
    assert outbound.bind_interaction(
        db_tx, attempt_id=attempt["id"], interaction_id=interaction_id
    )
    row = outbound.get(db_tx, attempt["id"])
    assert row["state"] == outbound.STATE_LIVE
    assert row["interaction_id"] == interaction_id


def test_a_runtime_signal_cannot_reopen_a_finished_call(db_tx) -> None:
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-LATE")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-LATE", status="completed", duration_sec=30
    )
    outbound.mark(db_tx, attempt["id"], state=outbound.STATE_LIVE)
    assert _state(db_tx, attempt["id"]) == outbound.STATE_COMPLETED


def test_right_party_is_recordable_at_all(db_tx) -> None:
    """RPC rate is the metric every collections floor manages and we had none."""
    attempt = _reserve(db_tx)
    outbound.mark(db_tx, attempt["id"], right_party=False, answered_by="human")
    row = outbound.get(db_tx, attempt["id"])
    assert row["right_party"] is False
    assert row["answered_by"] == "human"


def test_an_attempt_the_carrier_forgot_about_is_reaped(db_tx, monkeypatch) -> None:
    """Otherwise it holds a slot in the fleet gate until the heat death."""
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-STALE")
    db_tx.execute(
        text("UPDATE call_attempts SET reserved_at = :old WHERE id = :id"),
        {"id": attempt["id"], "old": datetime.now(timezone.utc) - timedelta(hours=4)},
    )

    class _Engine:
        def begin(self):
            import db as dbmod

            return dbmod.engine.begin()

    outbound.sweep_stale(_Engine())
    row = outbound.get(db_tx, attempt["id"])
    assert row["state"] == outbound.STATE_FAILED
    assert row["provider_error"] == "no_carrier_callback"


# ---------------------------------------------------------------------------
# Reach maths
# ---------------------------------------------------------------------------


def test_a_refused_week_is_not_an_unreachable_book(db_tx) -> None:
    """Suppressed attempts sit beside the reach figures, never inside them."""
    cust = _a_customer(db_tx)
    db_tx.execute(
        text("DELETE FROM call_attempts WHERE tenant_id = :t"), {"t": cust["tenant_id"]}
    )
    connected = _reserve(db_tx)
    _place(db_tx, connected, "CA-TEST-STATS-1")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-STATS-1", status="in-progress"
    )
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-STATS-1", status="completed", duration_sec=120
    )
    rang_out = _reserve(db_tx)
    _place(db_tx, rang_out, "CA-TEST-STATS-2")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-STATS-2", status="no-answer"
    )
    refused = _reserve(db_tx)
    outbound.suppress(db_tx, refused["id"], "daily_cap")

    stats = outbound.reach_stats(db_tx, tenant_id=cust["tenant_id"], days=1)
    assert stats["attempts"] == 2, "a suppressed attempt is not a dial the borrower ignored"
    assert stats["suppressed"] == 1
    assert stats["answered"] == 1
    assert stats["answerRate"] == 0.5
    assert stats["attemptsPerConnect"] == 2.0


# ---------------------------------------------------------------------------
# The Closer
# ---------------------------------------------------------------------------


def _close(conn, attempt_id: str) -> dict:
    row = dict(
        conn.execute(
            text("SELECT * FROM call_attempts WHERE id = :id"), {"id": attempt_id}
        ).mappings().first()
    )
    return call_closer.close_one(conn, row)


def test_a_ring_out_gets_an_outcome_too(db_tx, monkeypatch) -> None:
    """A call nobody answered is still a fact the ladder needs."""
    monkeypatch.setenv("CLOSER_LLM_ENABLED", "false")
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-CLOSE-NA")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-NA", status="no-answer"
    )
    result = _close(db_tx, attempt["id"])
    assert result["connection"] == "no_answer"
    assert result["business"] is None
    assert result["objectiveMet"] is False
    assert outbound.get(db_tx, attempt["id"])["closed_at"] is not None


def test_connection_and_business_are_separate_questions(db_tx, monkeypatch) -> None:
    """The old single disposition conflated "did it ring" with "did it work"."""
    monkeypatch.setenv("CLOSER_LLM_ENABLED", "false")
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-CLOSE-CONN")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-CONN", status="in-progress"
    )
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-CONN", status="completed", duration_sec=140
    )
    outbound.mark(db_tx, attempt["id"], right_party=True, answered_by="human")
    result = _close(db_tx, attempt["id"])
    assert result["connection"] == "connected"
    assert result["business"] == "no_resolution", "connected but nothing agreed"


def test_a_wrong_party_is_a_wrong_party_even_though_a_human_spoke(
    db_tx, monkeypatch
) -> None:
    monkeypatch.setenv("CLOSER_LLM_ENABLED", "false")
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-CLOSE-WP")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-WP", status="completed", duration_sec=22
    )
    outbound.mark(db_tx, attempt["id"], right_party=False, answered_by="human")
    result = _close(db_tx, attempt["id"])
    assert result["connection"] == "wrong_party"
    assert result["business"] == "wrong_number"
    assert result["actions"] == [] or "obligation" not in " ".join(result["actions"])


def test_the_reason_the_borrower_gave_survives_the_call(db_tx, monkeypatch) -> None:
    """The tool records a code; the Closer has to be able to read it back.

    This is the pair that was broken end to end: the voice path audited tool
    calls with ``args={}``, so the structured reason and the row proving it were
    on opposite sides of a gap.
    """
    monkeypatch.setenv("CLOSER_LLM_ENABLED", "false")
    interaction_id = db_tx.execute(
        text("SELECT id FROM interactions ORDER BY created_at DESC LIMIT 1")
    ).scalar()
    if not interaction_id:
        pytest.skip("no seeded interaction")
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-CLOSE-REASON")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-REASON", status="completed", duration_sec=180
    )
    outbound.bind_interaction(
        db_tx, attempt_id=attempt["id"], interaction_id=interaction_id
    )
    outbound.mark(db_tx, attempt["id"], right_party=True, answered_by="human")
    db_tx.execute(
        text(
            """
            INSERT INTO bot_tool_calls (id, interaction_id, channel, tool_name, args,
                                        result_ok, created_at)
            VALUES (:id, :ix, 'voice', 'capture_nonpayment_reason',
                    CAST(:args AS jsonb), true, now())
            """
        ),
        {
            "id": "BTC-TEST-REASON",
            "ix": interaction_id,
            "args": '{"reason": "salary_timing", "verbatim": "salary comes on the 7th"}',
        },
    )
    result = _close(db_tx, attempt["id"])
    assert result["nonpaymentReason"] == "salary_timing"
    hint = db_tx.execute(
        text("SELECT next_action_hint FROM call_outcomes WHERE attempt_id = :a"),
        {"a": attempt["id"]},
    ).scalar()
    assert hint == "emi_date_change", "a timing problem is not solved by calling again"


def test_hardship_is_derived_from_the_reason_not_only_the_intent(
    db_tx, monkeypatch
) -> None:
    monkeypatch.setenv("CLOSER_LLM_ENABLED", "false")
    interaction_id = db_tx.execute(
        text("SELECT id FROM interactions ORDER BY created_at DESC LIMIT 1")
    ).scalar()
    if not interaction_id:
        pytest.skip("no seeded interaction")
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-CLOSE-HARD")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-HARD", status="completed", duration_sec=200
    )
    outbound.bind_interaction(db_tx, attempt_id=attempt["id"], interaction_id=interaction_id)
    outbound.mark(db_tx, attempt["id"], right_party=True, answered_by="human")
    db_tx.execute(
        text(
            """
            INSERT INTO bot_tool_calls (id, interaction_id, channel, tool_name, args,
                                        result_ok, created_at)
            VALUES (:id, :ix, 'voice', 'capture_nonpayment_reason',
                    CAST(:args AS jsonb), true, now())
            """
        ),
        {
            "id": "BTC-TEST-HARD",
            "ix": interaction_id,
            "args": '{"reason": "income_loss"}',
        },
    )
    result = _close(db_tx, attempt["id"])
    assert result["business"] == "hardship_declared"
    assert result["nonpaymentReason"] == "income_loss"


def test_a_callback_we_offered_becomes_something_somebody_owes(
    db_tx, monkeypatch
) -> None:
    """"I'll call you Tuesday at six" used to be spoken and forgotten."""
    monkeypatch.setenv("CLOSER_LLM_ENABLED", "false")
    interaction_id = db_tx.execute(
        text("SELECT id FROM interactions ORDER BY created_at DESC LIMIT 1")
    ).scalar()
    if not interaction_id:
        pytest.skip("no seeded interaction")
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-CLOSE-CB")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-CB", status="completed", duration_sec=95
    )
    outbound.bind_interaction(db_tx, attempt_id=attempt["id"], interaction_id=interaction_id)
    outbound.mark(db_tx, attempt["id"], right_party=True, answered_by="human")
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    db_tx.execute(
        text(
            """
            INSERT INTO bot_tool_calls (id, interaction_id, channel, tool_name, args,
                                        result_ok, created_at)
            VALUES (:id, :ix, 'voice', 'request_callback', CAST(:args AS jsonb), true, now())
            """
        ),
        {
            "id": "BTC-TEST-CB",
            "ix": interaction_id,
            "args": '{"preferredAt": "%s", "reason": "wants to check with spouse"}' % when,
        },
    )
    result = _close(db_tx, attempt["id"])
    assert result["business"] == "callback_requested"
    assert any(a.startswith("obligation:callback") for a in result["actions"])
    owed = db_tx.execute(
        text(
            "SELECT kind, state FROM agent_obligations WHERE attempt_id = :a"
        ),
        {"a": attempt["id"]},
    ).mappings().first()
    assert owed["kind"] == "callback"
    assert owed["state"] == "open"


def test_one_attempt_gets_one_outcome(db_tx, monkeypatch) -> None:
    """The unique constraint is what makes the join safe without a pointer."""
    monkeypatch.setenv("CLOSER_LLM_ENABLED", "false")
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-CLOSE-ONCE")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-CLOSE-ONCE", status="busy"
    )
    _close(db_tx, attempt["id"])
    _close(db_tx, attempt["id"])
    count = db_tx.execute(
        text("SELECT count(*) FROM call_outcomes WHERE attempt_id = :a"),
        {"a": attempt["id"]},
    ).scalar()
    assert count == 1


def test_the_closer_claims_nothing_until_the_transcript_has_settled(db_tx) -> None:
    """CrmSink drains asynchronously; a call closed too early is summarised
    from a conversation missing its last turns, and looks just as confident."""
    attempt = _reserve(db_tx)
    _place(db_tx, attempt, "CA-TEST-GRACE")
    outbound.apply_provider_status(
        db_tx, provider_call_id="CA-TEST-GRACE", status="completed", duration_sec=30
    )
    claimed = call_closer.claim_one(db_tx)
    assert claimed is None or claimed["id"] != attempt["id"]

    db_tx.execute(
        text("UPDATE call_attempts SET ended_at = :old WHERE id = :id"),
        {"id": attempt["id"], "old": datetime.now(timezone.utc) - timedelta(minutes=10)},
    )
    claimed = call_closer.claim_one(db_tx)
    assert claimed is not None


# ---------------------------------------------------------------------------
# The number fence
# ---------------------------------------------------------------------------


def test_a_summary_that_invents_a_figure_is_thrown_away() -> None:
    """An LLM that fabricates a rupee amount in a collections record has
    manufactured evidence, and it reads exactly as authoritative as the truth."""
    assert call_closer.numbers_are_grounded("Agreed to pay the instalment shortly.", set())
    assert not call_closer.numbers_are_grounded("Agreed to pay 4200 on the 14th.", set())
    assert call_closer.numbers_are_grounded("Promised 4200 rupees.", {"4200"})


def test_a_stored_number_is_normalised_before_the_carrier_sees_it() -> None:
    """``customers.phone_primary`` holds bare digits because that is what the
    WhatsApp Graph API wants. Twilio rejects the same value as error 21211, so
    every dial to a correctly stored Indian mobile would have failed — and,
    before the attempt ledger, failed invisibly."""
    assert outbound.to_e164("919655282324") == "+919655282324"
    assert outbound.to_e164("9655282324") == "+919655282324"
    assert outbound.to_e164("+91 96552 82324") == "+919655282324"
    assert outbound.to_e164("00919655282324") == "+919655282324"
    assert outbound.to_e164("") == ""
    assert outbound.to_e164(None) == ""


def test_a_campaign_cannot_outrun_the_voice_fleet(db_tx, monkeypatch) -> None:
    """The slot is taken before the carrier is called, so abandon rate is
    structurally zero rather than managed down — which is the whole argument
    against a predictive dialler on a collections line."""
    monkeypatch.setenv("OUTBOUND_MAX_IN_FLIGHT", "2")
    cust = _a_customer(db_tx)
    db_tx.execute(
        text("DELETE FROM call_attempts WHERE tenant_id = :t"), {"t": cust["tenant_id"]}
    )
    for _ in range(3):
        _reserve(db_tx)
    assert outbound.in_flight_count(db_tx, cust["tenant_id"]) == 3
    assert outbound.in_flight_count(db_tx, cust["tenant_id"]) > outbound.max_in_flight()


def test_a_suppressed_attempt_stops_holding_a_slot(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("OUTBOUND_MAX_IN_FLIGHT", "2")
    cust = _a_customer(db_tx)
    db_tx.execute(
        text("DELETE FROM call_attempts WHERE tenant_id = :t"), {"t": cust["tenant_id"]}
    )
    a = _reserve(db_tx)
    _reserve(db_tx)
    outbound.suppress(db_tx, a["id"], "daily_cap")
    assert outbound.in_flight_count(db_tx, cust["tenant_id"]) == 1


def test_the_reason_vocabulary_is_closed() -> None:
    """The value of the field is entirely in being able to group by it."""
    from agent_core.tools.catalog import CATALOG, NONPAYMENT_REASONS

    assert set(NONPAYMENT_REASONS) == call_closer.NONPAYMENT_REASONS
    spec = CATALOG.get("capture_nonpayment_reason")
    reason_arg = next(a for a in spec.args if a.name == "reason")
    assert reason_arg.required
    assert set(reason_arg.enum or ()) == call_closer.NONPAYMENT_REASONS


def test_forgot_tells_the_engine_the_call_was_not_worth_making() -> None:
    """The label an uplift model needs in order to stop dialling this segment."""
    assert call_closer._next_action_hint("connected", "no_resolution", "forgot") == (
        "cheapest_digital_next_time"
    )
    assert call_closer._next_action_hint("connected", "opt_out_requested", None) == (
        "stop_contact"
    )
