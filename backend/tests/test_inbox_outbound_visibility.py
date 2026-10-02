"""An agent must be able to tell a sent message from a stuck one.

An operator took over a WhatsApp conversation and sent two replies. The API
returned 200 twice, both bubbles appeared in the thread, and the customer
received nothing: ``bot_worker`` was not running, so both jobs sat in
``whatsapp_outbound_jobs`` at ``queued`` for six minutes. Three separate things
had to go wrong at once for that to be invisible, and each is pinned here.

1. ``sending`` collapsed to no delivery state, so a queued bubble rendered
   byte-identically to a delivered one.
2. The thread showed "Bot is typing…" the whole time — the bot was doing
   nothing; the flag was reading the *agent's* own stuck send, with no upper
   age bound. (An unreadable gate on the rail: test_inbox_thread_contract.)
3. Suggestions refresh raised on a conversation with no messages, so a voice
   call escalated into the inbox 400'd on every poll.
"""

from __future__ import annotations

import pytest

import db
import db_inbox_rag


# --- 1. a queued message must not look delivered ----------------------------


@pytest.mark.parametrize("sender", ["bot", "agent"])
def test_queued_outbound_reports_pending(sender: str) -> None:
    assert db._inbox_delivery("sending", sender) == "pending"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("sent", "sent"),
        ("delivered", "delivered"),
        ("read", "read"),
        ("failed", "failed"),
        # Deliberately withdrawn — it was never going to arrive, and there is
        # nothing for the sender to wait on.
        ("cancelled", None),
    ],
)
def test_other_delivery_states_are_unchanged(status: str, expected: str | None) -> None:
    assert db._inbox_delivery(status, "agent") == expected


def test_pending_is_distinguishable_from_delivered() -> None:
    """The whole point: these two must not collapse to the same value."""
    assert db._inbox_delivery("sending", "agent") != db._inbox_delivery("delivered", "agent")


def test_customer_messages_never_carry_a_delivery_state() -> None:
    assert db._inbox_delivery("delivered", "customer") is None


def test_the_response_schema_admits_pending() -> None:
    """A value db.py can emit that schemas.py rejects is a 500, not a bubble."""
    import typing

    from schemas import InboxMessageResponse

    annotation = InboxMessageResponse.model_fields["delivery"].annotation
    allowed = {a for arg in typing.get_args(annotation) for a in typing.get_args(arg) or ()}
    assert "pending" in allowed
    # Everything db._inbox_delivery can return must be representable here.
    emitted = {
        db._inbox_delivery(s, "agent")
        for s in ("sending", "sent", "delivered", "read", "failed", "cancelled", None)
    }
    assert emitted - {None} <= allowed


# --- 2. "Bot is typing…" must mean the bot ----------------------------------


def _typing_case(conn, *, bot_job_age: str | None = None, agent_send: bool = False) -> bool:
    """Whether a thread with the given in-flight work reads as the bot typing."""
    import uuid

    from sqlalchemy import text

    tag = uuid.uuid4().hex[:8].upper()
    cid, cv = f"CUST-TY-{tag}", f"CV-TY-{tag}"
    conn.execute(
        text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, 'Typing Fixture', 'low')"),
        {"id": cid, "t": db.current_tenant()},
    )
    conn.execute(
        text(
            "INSERT INTO interactions (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel, status) "
            "VALUES (:id, :t, :c, 'bot', (SELECT id FROM bots ORDER BY id LIMIT 1), 'whatsapp', 'active')"
        ),
        {"id": f"IX-TY-{tag}", "t": db.current_tenant(), "c": cid},
    )
    conn.execute(
        text(
            "INSERT INTO conversations (id, interaction_id, customer_id, status, channel) "
            "VALUES (:id, :ix, :c, 'bot', 'whatsapp')"
        ),
        {"id": cv, "ix": f"IX-TY-{tag}", "c": cid},
    )
    if bot_job_age is not None:
        conn.execute(
            text(
                "INSERT INTO bot_turn_jobs (id, conversation_id, customer_id, status, updated_at) "
                "VALUES (:id, :cv, :c, 'queued', now() - CAST(:age AS interval))"
            ),
            {"id": f"BTJ-{tag}", "cv": cv, "c": cid, "age": bot_job_age},
        )
    if agent_send:
        conn.execute(
            text(
                "INSERT INTO messages (id, conversation_id, sender, body, delivery_status) "
                "VALUES (:id, :cv, 'agent', 'x', 'sending')"
            ),
            {"id": f"MSG-{tag}", "cv": cv},
        )
        conn.execute(
            text(
                "INSERT INTO whatsapp_outbound_jobs (id, message_id, conversation_id, customer_id, to_phone, "
                "body, purpose, source, status) "
                "VALUES (:id, :m, :cv, :c, 'x', 'x', 'in_session', 'inbox_reply', 'queued')"
            ),
            {"id": f"WAO-{tag}", "m": f"MSG-{tag}", "cv": cv, "c": cid},
        )
    return bool(db._bot_typing_by_conversation(conn, [cv]).get(cv))


def test_the_bot_composing_reads_as_typing(db_tx) -> None:
    assert _typing_case(db_tx, bot_job_age="5 seconds")


def test_an_agents_own_send_is_not_the_bot_typing(db_tx) -> None:
    """An agent's own outbound is not the bot composing a reply."""
    assert not _typing_case(db_tx, agent_send=True)


def test_a_stuck_queue_is_not_typing(db_tx) -> None:
    """Unbounded, the indicator ran for as long as the worker stayed down."""
    assert not _typing_case(db_tx, bot_job_age="5 minutes")


# --- 3. no messages is a normal state, not a bad request --------------------


def test_suggestions_refresh_survives_a_conversation_with_no_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A voice call escalated into the inbox keeps its turns in the transcript.

    It has no ``messages`` rows at all, and every poll of that thread returned
    400 ``conversation_has_no_messages`` — a client error for something the
    client did nothing wrong to cause.
    """

    def _raise(_conn: object, _cid: str) -> str:
        raise ValueError("conversation_has_no_messages")

    monkeypatch.setattr(db_inbox_rag, "_conversation_rag_query", _raise)
    out = db.refresh_conversation_suggestions("CV-VOICE-0001")
    assert out["conversationId"] == "CV-VOICE-0001"
    assert out["ragSuggestions"] == []
    assert out["draftAnswer"] is None


def test_a_real_retrieval_failure_still_surfaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the empty-conversation case is benign; do not swallow the rest."""

    def _raise(_conn: object, _cid: str) -> str:
        raise ValueError("conversation_not_found")

    monkeypatch.setattr(db_inbox_rag, "_conversation_rag_query", _raise)
    with pytest.raises(ValueError, match="conversation_not_found"):
        db.refresh_conversation_suggestions("CV-NOPE")


# --- the diagnostic that would have caught it -------------------------------


def test_enqueue_warns_when_nothing_is_draining_the_queue(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    import whatsapp_outbound

    class _Row:
        _mapping = {"n": 2, "oldest_s": 400.0}

    class _Conn:
        def execute(self, *_a: object, **_k: object) -> "_Conn":
            return self

        def fetchone(self) -> _Row:
            return _Row()

    with caplog.at_level(logging.WARNING, logger="whatsapp_outbound"):
        whatsapp_outbound._warn_if_queue_is_not_draining(_Conn())
    assert "not draining" in caplog.text
    assert "bot_worker" in caplog.text


def test_the_staleness_check_never_breaks_a_send() -> None:
    """A diagnostic that can fail a send is worse than no diagnostic."""
    import whatsapp_outbound

    class _Boom:
        def execute(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("database on fire")

    whatsapp_outbound._warn_if_queue_is_not_draining(_Boom())  # must not raise
