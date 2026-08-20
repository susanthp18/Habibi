"""One turn, one timeline.

Tool calls, retrievals and latency sat at three grains that could not be joined:
``bot_tool_calls`` keyed by ``job_id`` (which only the WhatsApp/text path has,
so voice tool calls were never recorded at all), ``retrieval_logs`` keyed by
``interaction_id`` (the whole session), and the latency breakdown on
``interaction_transcript``. "What did the bot do on turn 4" was unanswerable.

Migration 0055 gives the two event tables a ``transcript_turn_id``. These tests
pin the assembly and, more importantly, the two ways it can go quietly wrong:
constructing the turn id instead of reading it back, and leaking raw tool output
through a new endpoint.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import db


@pytest.fixture
def interaction(db_tx) -> str:
    """A bare interaction with two customer turns."""
    ix = f"IX-TRACE-{uuid.uuid4().hex[:8].upper()}"
    customer = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel,
               status, started_at)
            VALUES (:id, :t, :c, 'bot',
                    (SELECT id FROM bots LIMIT 1), 'voice', 'completed', now())
            """
        ),
        {"id": ix, "t": db.TENANT_ID, "c": customer},
    )
    for idx, (speaker, body) in enumerate(
        [("customer", "what does the policy cover"), ("bot", "let me check that")], start=1
    ):
        db_tx.execute(
            text(
                """
                INSERT INTO interaction_transcript
                  (id, interaction_id, turn_index, speaker, at_sec, text, ttfb_ms, tokens)
                VALUES (:id, :ix, :ti, :sp, :ti, :tx, 420, 80)
                """
            ),
            {"id": f"{ix}-T{idx}", "ix": ix, "ti": idx, "sp": speaker, "tx": body},
        )
    return ix


def _turn_id(conn, ix: str, turn_index: int) -> str:
    return conn.execute(
        text(
            "SELECT id FROM interaction_transcript "
            "WHERE interaction_id = :ix AND turn_index = :ti"
        ),
        {"ix": ix, "ti": turn_index},
    ).scalar()


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def test_tool_calls_and_retrievals_nest_under_their_turn(db_tx, interaction) -> None:
    import bot_jobs

    turn_id = _turn_id(db_tx, interaction, 1)
    bot_jobs.record_tool_call(
        db_tx,
        interaction_id=interaction,
        transcript_turn_id=turn_id,
        channel="voice",
        tool_name="search_knowledge_base",
        args={},
        result_ok=True,
        latency_ms=180,
    )
    db_tx.execute(
        text(
            """
            INSERT INTO retrieval_logs
              (id, tenant_id, interaction_id, transcript_turn_id, query,
               top_chunks, latency_ms)
            VALUES ('RL-T1', :tenant, :ix, :turn, 'policy coverage',
                    CAST(:chunks AS jsonb), 45)
            """
        ),
        # Bound, not inlined: the ':' in a JSON literal is a bind marker to
        # SQLAlchemy and turns "score":0.82 into a parameter named '0'.
        {
            "tenant": db.current_tenant(),
            "ix": interaction,
            "turn": turn_id,
            "chunks": '[{"chunkId":"CH-1","score":0.82}]',
        },
    )

    trace = db.get_turn_trace(interaction)

    turn_one = next(t for t in trace if t["turnIndex"] == 1)
    assert [c["tool"] for c in turn_one["toolCalls"]] == ["search_knowledge_base"]
    assert turn_one["retrievals"][0]["hits"] == 1
    assert turn_one["retrievals"][0]["topScore"] == 0.82
    # The turn the tool did NOT belong to stays clean.
    turn_two = next(t for t in trace if t["turnIndex"] == 2)
    assert turn_two["toolCalls"] == []


def test_latency_breakdown_rides_the_turn(db_tx, interaction) -> None:
    trace = db.get_turn_trace(interaction)

    assert trace[0]["latency"]["ttfbMs"] == 420
    assert trace[0]["latency"]["tokens"] == 80


def test_unknown_interaction_raises(db_tx) -> None:
    with pytest.raises(KeyError):
        db.get_turn_trace("IX-DOES-NOT-EXIST")


# ---------------------------------------------------------------------------
# The id must be read back, never constructed
# ---------------------------------------------------------------------------


def test_a_non_canonical_turn_id_still_resolves(db_tx, interaction) -> None:
    """capture's id normalisation is savepoint-guarded and may be skipped.

    When it is, the row keeps `{ix}-T-next-{uuid}` forever. Any code that builds
    `f"{ix}-T{n}"` as an FK dangles exactly on those rows — so this test plants
    one deliberately.
    """
    odd_id = f"{interaction}-T-next-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text("UPDATE interaction_transcript SET id = :new WHERE interaction_id = :ix AND turn_index = 1"),
        {"new": odd_id, "ix": interaction},
    )

    from voice import persist

    persist.record_voice_tool_call(
        interaction_id=interaction,
        turn_index=1,
        tool_name="get_account_position",
        result_ok=True,
        latency_ms=90,
    )

    trace = db.get_turn_trace(interaction)
    turn_one = next(t for t in trace if t["turnIndex"] == 1)

    assert turn_one["turnId"] == odd_id
    assert [c["tool"] for c in turn_one["toolCalls"]] == ["get_account_position"]


# ---------------------------------------------------------------------------
# Races and attribution
# ---------------------------------------------------------------------------


def test_a_tool_call_with_no_transcript_row_is_kept_not_dropped(db_tx, interaction) -> None:
    """The analysis and CRM queues drain independently, so a tool call can be
    recorded before the turn it belongs to exists. Losing an audit record to a
    race is worse than showing it out of place."""
    import bot_jobs

    bot_jobs.record_tool_call(
        db_tx,
        interaction_id=interaction,
        transcript_turn_id=None,
        channel="voice",
        tool_name="create_promise_to_pay",
        args={},
        result_ok=True,
    )

    trace = db.get_turn_trace(interaction)
    orphans = [t for t in trace if t["turnId"] is None]

    assert len(orphans) == 1
    assert [c["tool"] for c in orphans[0]["toolCalls"]] == ["create_promise_to_pay"]


def test_an_unattributable_tool_call_is_rejected(db_tx) -> None:
    """The CHECK replaced two NOT NULLs; this is the invariant that mattered."""
    import bot_jobs

    with pytest.raises(ValueError):
        bot_jobs.record_tool_call(
            db_tx, tool_name="get_customer_context", args={}, result_ok=True
        )


def test_the_database_also_rejects_it(db_tx) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_tx.execute(
            text(
                "INSERT INTO bot_tool_calls (id, tool_name, result_ok) "
                "VALUES ('BTC-BAD', 'x', true)"
            )
        )


# ---------------------------------------------------------------------------
# Redaction — the endpoint widens who can read this table
# ---------------------------------------------------------------------------


def test_tool_output_is_redacted_on_the_way_out(db_tx, interaction) -> None:
    """result_preview holds up to 1500 chars of raw tool output; args hold
    model-supplied customer speech. Only the Inbox read this before."""
    import bot_jobs

    bot_jobs.record_tool_call(
        db_tx,
        interaction_id=interaction,
        transcript_turn_id=_turn_id(db_tx, interaction, 1),
        channel="voice",
        tool_name="flag_dispute",
        args={"summary": "my card 4111111111111111 was charged twice"},
        result_ok=True,
        result_preview="customer mobile 9876543210, balance 42350",
    )

    trace = db.get_turn_trace(interaction)
    call = next(t for t in trace if t["turnIndex"] == 1)["toolCalls"][0]

    assert "4111111111111111" not in str(call["args"])
    assert "9876543210" not in str(call["resultPreview"])
    # Still useful — only the identifiers are gone.
    assert "charged twice" in str(call["args"])


def test_trace_carries_nullable_agent_skill_connector(db_tx, interaction) -> None:
    import bot_jobs

    bot_jobs.record_tool_call(
        db_tx,
        interaction_id=interaction,
        transcript_turn_id=_turn_id(db_tx, interaction, 1),
        channel="voice",
        tool_name="get_customer_context",
        args={},
        result_ok=True,
        agent_id="collections",
        skill_id="ptp-negotiate",
        connector_id=None,
    )
    trace = db.get_turn_trace(interaction)
    call = next(t for t in trace if t["turnIndex"] == 1)["toolCalls"][0]
    assert call["agentId"] == "collections"
    assert call["skillId"] == "ptp-negotiate"
    assert call["connectorId"] is None


def test_transcript_text_is_redacted(db_tx, interaction) -> None:
    db_tx.execute(
        text("UPDATE interaction_transcript SET text = :t WHERE interaction_id = :ix AND turn_index = 1"),
        {"t": "my number is 9876543210", "ix": interaction},
    )

    trace = db.get_turn_trace(interaction)

    assert "9876543210" not in trace[0]["text"]


# ---------------------------------------------------------------------------
# The KB test panel still works and creates no turn linkage
# ---------------------------------------------------------------------------


def test_operator_retrieval_has_no_turn(db_tx) -> None:
    """POST /kb/retrieve passes neither interaction nor turn — it must still
    write its log row rather than failing a NOT NULL.

    It does carry a tenant, though. This row is the reason ``retrieval_logs``
    was given its own ``tenant_id`` in migration 0062: its three parent links
    are all optional, so a row like this one belonged to no tenant and would
    have been invisible to everybody once policies were enforcing.
    """
    db_tx.execute(
        text(
            "INSERT INTO retrieval_logs (id, tenant_id, query, top_chunks) "
            "VALUES ('RL-ORPHAN', :tenant, 'operator test query', CAST('[]' AS jsonb))"
        ),
        {"tenant": db.current_tenant()},
    )

    row = db_tx.execute(
        text("SELECT interaction_id, transcript_turn_id FROM retrieval_logs WHERE id = 'RL-ORPHAN'")
    ).mappings().first()

    assert row["interaction_id"] is None
    assert row["transcript_turn_id"] is None
