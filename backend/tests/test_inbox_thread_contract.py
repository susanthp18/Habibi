"""The Conversation Inbox, end to end on synthetic threads.

Each test pins a defect three reviews of the page found in the code:

* the rail asked the gate about WhatsApp *outreach* on every thread while the
  send asked about the thread's own channel *in session*;
* "unread" was 0 on every thread you held, and the SLA ignored replies;
* a failed bot reply was deleted from the transcript;
* the thread showed the customer's first account and their first EMI ever;
* takeover needed supervisor rights an agent never has, raced silently, and
  left the interaction with the bot;
* an email, web-chat or voice reply was stored as ``sent`` and went nowhere,
  and SMS let an agent post into a colleague's thread;
* an ambiguous sender was filed against whichever borrower sorted first, and
  replies went to the primary number whoever wrote.

Every row is created here; nothing depends on the seed.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import event, text

import actor_context
import authz
import bot_conversation
import contact_policy
import db
import db_core
import db_inbox
import db_inbox_rag
import db_whatsapp
from agent_core.clock import utc_now

AGENT = "sara-khan"
COLLEAGUE = "arjun-mehta"


@pytest.fixture
def as_actor():
    tokens = []

    def _use(user_id: str):
        tokens.append(actor_context.set_actor_user_id(user_id))

    yield _use
    for token in reversed(tokens):
        actor_context.reset_actor_user_id(token)


@pytest.fixture
def agent_rights(monkeypatch):
    """An agent: interaction writes, no supervisor rights."""
    monkeypatch.setattr(authz, "has_permission", lambda _u, p: p != authz.SUPERVISOR_WRITE)


def _uid(prefix: str) -> str:
    return f"{prefix}-IB-{uuid.uuid4().hex[:8].upper()}"


def _phone() -> str:
    return "+91 7" + "".join(str(uuid.uuid4().int)[:9])


def _customer(conn, *, phone: str | None = None, alt: str | None = None) -> dict:
    cid = _uid("CUST")
    conn.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, risk, phone_primary, phone_alt) "
            "VALUES (:id, :t, 'Inbox Fixture', 'low', :p, :a)"
        ),
        {"id": cid, "t": db.current_tenant(), "p": phone or _phone(), "a": alt},
    )
    accounts = []
    for _ in range(2):
        aid = _uid("ACC")
        conn.execute(
            text(
                "INSERT INTO accounts (id, customer_id, product_id, outstanding, dpd) "
                "VALUES (:id, :c, (SELECT id FROM products ORDER BY id LIMIT 1), 5000, 12)"
            ),
            {"id": aid, "c": cid},
        )
        accounts.append(aid)
    return {"id": cid, "accounts": accounts}


def _thread(conn, customer: dict, *, channel: str = "whatsapp", status: str = "bot",
            assignee: str | None = None, account: int = 1) -> str:
    """A thread on the customer's *second* account: the first is a decoy."""
    ix, cv = _uid("IX"), _uid("CV")
    handler = (
        "'human', :u, NULL" if assignee else "'bot', NULL, (SELECT id FROM bots ORDER BY id LIMIT 1)"
    )
    conn.execute(
        text(
            "INSERT INTO interactions (id, tenant_id, customer_id, account_id, handler_kind, "
            f"handler_user_id, handler_bot_id, channel, status) VALUES (:id, :t, :c, :a, {handler}, :ch, 'active')"
        ),
        {"id": ix, "t": db.current_tenant(), "c": customer["id"], "a": customer["accounts"][account],
         "ch": channel, "u": assignee},
    )
    conn.execute(
        text(
            "INSERT INTO conversations (id, interaction_id, customer_id, assigned_user_id, status, channel) "
            "VALUES (:id, :ix, :c, :u, :s, :ch)"
        ),
        {"id": cv, "ix": ix, "c": customer["id"], "u": assignee, "s": status, "ch": channel},
    )
    return cv


def _message(conn, cv: str, sender: str, *, ago: timedelta, status: str = "delivered",
             real: bool = True, body: str | None = None) -> str:
    mid = _uid("MSG")
    conn.execute(
        text(
            "INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at) "
            "VALUES (:id, :cv, :s, :b, :st, :ref, :at)"
        ),
        {"id": mid, "cv": cv, "s": sender, "b": body or f"{sender} says {mid}", "st": status,
         "ref": f"wamid.{mid}" if real and sender == "customer" else None, "at": utc_now() - ago},
    )
    return mid


def _summary(cv: str) -> dict:
    (row,) = [r for r in db.list_conversations(q=cv) if r["id"] == cv]
    return row


# --- the list is light and its numbers mean what they say -----------------


def test_the_list_carries_no_transcript_and_reads_in_bounded_statements(db_tx, as_actor) -> None:
    customer = _customer(db_tx)
    for _ in range(3):
        cv = _thread(db_tx, customer)
        _message(db_tx, cv, "customer", ago=timedelta(minutes=5))
    as_actor(AGENT)
    seen: list[str] = []
    listener = lambda *a: seen.append(a[2])  # noqa: E731
    event.listen(db_core.engine, "before_cursor_execute", listener)
    try:
        rows = db.list_conversations(customer_id=customer["id"])
    finally:
        event.remove(db_core.engine, "before_cursor_execute", listener)
    assert len(rows) == 3
    assert all("messages" not in r and "context" not in r for r in rows)
    assert len(seen) <= 4, seen  # base rows and typing, whatever the thread count


def test_awaiting_reply_counts_unanswered_customer_messages_for_the_holder_too(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="assigned", assignee=AGENT)
    _message(db_tx, cv, "agent", ago=timedelta(hours=30), status="read")
    _message(db_tx, cv, "customer", ago=timedelta(hours=26))
    _message(db_tx, cv, "customer", ago=timedelta(hours=25))
    as_actor(AGENT)
    row = _summary(cv)
    # It used to be 0 on every thread you held: the inbox's triage signal off.
    assert row["isMine"] and row["awaitingReply"] == 2
    assert row["sla"] == "breach"


def test_a_failed_reply_answered_nobody(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(hours=5))
    _message(db_tx, cv, "bot", ago=timedelta(hours=4), status="failed")
    as_actor(AGENT)
    row = _summary(cv)
    # Bot-held threads always read "ok"; a bot that stopped answering never surfaced.
    assert row["awaitingReply"] == 1 and row["sla"] == "warn"


def test_an_answered_thread_is_not_breached(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="assigned", assignee=AGENT)
    _message(db_tx, cv, "customer", ago=timedelta(hours=30))
    _message(db_tx, cv, "agent", ago=timedelta(hours=1), status="delivered")
    as_actor(AGENT)
    row = _summary(cv)
    assert row["awaitingReply"] == 0 and row["sla"] == "ok"


def test_search_reaches_an_earlier_message_and_a_customer(db_tx, as_actor) -> None:
    customer = _customer(db_tx)
    cv = _thread(db_tx, customer)
    needle = f"needle-{uuid.uuid4().hex[:6]}"
    _message(db_tx, cv, "customer", ago=timedelta(hours=3), body=f"my {needle} question")
    _message(db_tx, cv, "customer", ago=timedelta(hours=1), body="anything else")
    as_actor(AGENT)
    assert [r["id"] for r in db.list_conversations(q=needle)] == [cv]
    assert [r["id"] for r in db.list_conversations(q="100%_literal")] == []
    assert [r["id"] for r in db.list_conversations(customer_id=customer["id"])] == [cv]


# --- the transcript is the record ------------------------------------------


def test_a_failed_bot_reply_stays_in_the_transcript_with_a_reason(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(minutes=30))
    failed = _message(db_tx, cv, "bot", ago=timedelta(minutes=29), status="failed")
    db_tx.execute(
        text(
            "INSERT INTO whatsapp_outbound_jobs (id, message_id, conversation_id, customer_id, to_phone, "
            "body, purpose, source, status, error) VALUES (:id, :m, :cv, "
            "(SELECT customer_id FROM conversations WHERE id = :cv), 'x', 'x', 'in_session', 'bot', 'failed', "
            "'code=131047 Re-engagement message +91 7000000000')"
        ),
        {"id": _uid("WAO"), "m": failed, "cv": cv},
    )
    withdrawn = _message(db_tx, cv, "bot", ago=timedelta(minutes=28), status="cancelled")
    as_actor(AGENT)
    messages = db.get_conversation(cv)["messages"]
    by_id = {m["id"]: m for m in messages}
    assert by_id[failed]["delivery"] == "failed"
    assert by_id[failed]["deliveryNote"] == "Outside WhatsApp's 24-hour window"
    assert "7000000000" not in str(messages), "the provider's text must not reach the screen"
    assert withdrawn not in by_id
    assert all(m.get("at") for m in messages), "every item carries its date"


# --- the rail: this thread's loan, and the reply the send would make --------


def test_the_context_is_the_threads_own_loan_and_its_next_unpaid_emi(db_tx, as_actor) -> None:
    customer = _customer(db_tx)
    cv = _thread(db_tx, customer)
    _message(db_tx, cv, "customer", ago=timedelta(hours=1))
    account = customer["accounts"][1]
    for idx, (months_ago, status, paid) in enumerate([(13, "paid", 1000), (1, "partial", 400), (-1, "upcoming", 0)]):
        db_tx.execute(
            text(
                "INSERT INTO emi_installments (id, account_id, installment_index, due_date, amount, "
                "paid_amount, status) VALUES (:id, :a, :i, now() - make_interval(months => :m), 1000, :p, :s)"
            ),
            {"id": _uid("EMI"), "a": account, "i": idx, "m": months_ago, "p": paid, "s": status},
        )
    as_actor(AGENT)
    thread = db.get_conversation(cv)
    assert thread["accountId"] == account, "the first account is a different loan"
    ctx = thread["context"]
    assert ctx["nextEmiAmount"] == 600.0, "what is left of the partial, not last year's paid one"
    assert ctx["nextEmiOverdue"] is True


def test_the_rail_answers_the_reply_the_send_would_make(db_tx, as_actor, monkeypatch) -> None:
    asked: list[tuple[str, str]] = []

    def _evaluate(conn, **kw):
        asked.append((kw["channel"], kw["purpose"]))
        return contact_policy.Decision(True)

    monkeypatch.setattr(contact_policy, "evaluate", _evaluate)
    customer = _customer(db_tx)
    wa = _thread(db_tx, customer)
    _message(db_tx, wa, "customer", ago=timedelta(hours=2))
    sms = _thread(db_tx, customer, channel="sms")
    seeded = _thread(db_tx, customer)
    _message(db_tx, seeded, "customer", ago=timedelta(hours=1), real=False)
    email = _thread(db_tx, customer, channel="email")
    as_actor(AGENT)

    ctx = db.get_conversation(wa)["context"]
    assert ctx["canReply"] and asked[-1] == ("whatsapp", "in_session")
    assert ctx["replyWindowEndsAt"]
    db.get_conversation(sms)
    assert asked[-1] == ("sms", "outreach"), "an SMS thread was judged as WhatsApp"
    # Only a message Meta delivered opens the service window.
    assert db.get_conversation(seeded)["context"]["replyBlockedReason"] == "whatsapp_window_closed"
    assert db.get_conversation(email)["context"]["replyBlockedReason"] == "channel_not_supported"


def test_an_unreadable_gate_is_a_refusal_with_its_reason(db_tx, as_actor, monkeypatch) -> None:
    def _boom(*_a, **_k):
        raise RuntimeError("policy store unreachable")

    monkeypatch.setattr(contact_policy, "evaluate", _boom)
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(minutes=5))
    as_actor(AGENT)
    ctx = db.get_conversation(cv)["context"]
    assert ctx["canReply"] is False and ctx["replyBlockedReason"] == "policy_unavailable"


# --- ownership -------------------------------------------------------------


def _handler(conn, cv: str) -> dict:
    return dict(
        conn.execute(
            text(
                "SELECT i.handler_kind, i.handler_user_id FROM interactions i "
                "JOIN conversations cv ON cv.interaction_id = i.id WHERE cv.id = :cv"
            ),
            {"cv": cv},
        ).mappings().one()
    )


def test_an_agent_claims_an_unheld_thread_and_the_interaction_follows(
    db_tx, as_actor, agent_rights
) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="needs_human")
    as_actor(AGENT)
    thread = db.takeover_conversation(cv, {"expectedAssigneeId": None})
    assert thread["isMine"] and thread["status"] == "assigned"
    assert _handler(db_tx, cv) == {"handler_kind": "human", "handler_user_id": AGENT}
    assert any(m.get("text") == "You took over" for m in thread["messages"])

    back = db.return_conversation_to_bot(cv)
    assert back["status"] == "bot"
    assert _handler(db_tx, cv)["handler_kind"] == "bot"


def test_taking_a_colleagues_thread_needs_supervisor_rights(db_tx, as_actor, agent_rights) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="assigned", assignee=COLLEAGUE)
    as_actor(AGENT)
    with pytest.raises(PermissionError, match="reassign_requires_supervisor"):
        db.takeover_conversation(cv, {"expectedAssigneeId": COLLEAGUE})


def test_a_takeover_that_lost_a_race_is_refused_not_applied(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="needs_human")
    # A colleague claimed it after this operator's screen last refreshed.
    db_tx.execute(
        text("UPDATE conversations SET status = 'assigned', assigned_user_id = :u WHERE id = :cv"),
        {"u": COLLEAGUE, "cv": cv},
    )
    as_actor(AGENT)
    with pytest.raises(ValueError, match="conversation_owner_changed"):
        db.takeover_conversation(cv, {"expectedAssigneeId": None})


def test_only_whatsapp_goes_back_to_a_bot(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx), channel="sms", status="assigned", assignee=AGENT)
    as_actor(AGENT)
    with pytest.raises(ValueError, match="bot_does_not_answer_channel"):
        db.return_conversation_to_bot(cv)


# --- sending ---------------------------------------------------------------


@pytest.fixture
def gate_open(monkeypatch):
    admitted: list[dict] = []

    def _admit(conn, **kw):
        admitted.append(kw)
        return contact_policy.Decision(True)

    monkeypatch.setattr(contact_policy, "admit", _admit)
    return admitted


def test_every_channel_requires_holding_the_thread(db_tx, as_actor, gate_open) -> None:
    cv = _thread(db_tx, _customer(db_tx), channel="sms", status="assigned", assignee=COLLEAGUE)
    as_actor(AGENT)
    with pytest.raises(ValueError, match="take_over_required"):
        db.send_conversation_message(cv, {"text": "hello"})


@pytest.mark.parametrize("channel", ["email", "chat", "voice"])
def test_a_channel_with_no_transport_refuses_instead_of_recording_sent(
    db_tx, as_actor, gate_open, channel
) -> None:
    cv = _thread(db_tx, _customer(db_tx), channel=channel, status="assigned", assignee=AGENT)
    as_actor(AGENT)
    with pytest.raises(ValueError, match="channel_not_supported"):
        db.send_conversation_message(cv, {"text": "hello"})
    assert db_tx.execute(
        text("SELECT count(*) FROM messages WHERE conversation_id = :cv"), {"cv": cv}
    ).scalar() == 0


def test_a_reply_goes_to_the_number_the_customer_wrote_from_once(db_tx, as_actor, gate_open) -> None:
    primary, alternate = _phone(), _phone()
    customer = _customer(db_tx, phone=primary, alt=alternate)
    cv = _thread(db_tx, customer, status="assigned", assignee=AGENT)
    _message(db_tx, cv, "customer", ago=timedelta(minutes=10))
    db_tx.execute(
        text(
            "UPDATE interactions SET source_payload = jsonb_build_object('endpoint_slot', 'alt') "
            "WHERE id = (SELECT interaction_id FROM conversations WHERE id = :cv)"
        ),
        {"cv": cv},
    )
    as_actor(AGENT)
    key = uuid.uuid4().hex
    db.send_conversation_message(cv, {"text": "on its way"}, key)
    db.send_conversation_message(cv, {"text": "on its way"}, key)  # the response was lost; resent

    jobs = db_tx.execute(
        text("SELECT to_phone, purpose FROM whatsapp_outbound_jobs WHERE conversation_id = :cv"), {"cv": cv}
    ).mappings().all()
    assert len(jobs) == 1, "a resend after a lost response queued a second message"
    assert jobs[0]["to_phone"].endswith(alternate[-10:].replace(" ", ""))
    assert jobs[0]["purpose"] == "in_session"
    assert gate_open[-1]["endpoint"] == alternate


# --- WhatsApp ingest -------------------------------------------------------


def _webhook(from_phone: str, msg: dict) -> dict:
    digits = "".join(ch for ch in from_phone if ch.isdigit())
    return {
        "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": digits, "profile": {"name": "Fixture"}}],
            "messages": [{"id": f"wamid.{uuid.uuid4().hex}", "from": digits,
                          "timestamp": str(int(utc_now().timestamp())), **msg}],
        }}]}]
    }


@pytest.fixture
def no_bot(monkeypatch):
    import bot_jobs

    monkeypatch.setattr(bot_jobs, "enqueue_bot_turn", lambda *_a, **_k: None)


def test_a_number_two_borrowers_share_is_not_filed_against_either(db_tx, no_bot) -> None:
    shared = _phone()
    first, second = _customer(db_tx, phone=shared), _customer(db_tx, phone=shared)
    out = db_whatsapp.process_whatsapp_webhook(_webhook(shared, {"type": "text", "text": {"body": "hi"}}))
    (result,) = out["results"]
    assert result["customerId"] not in {first["id"], second["id"]}
    assert db_tx.execute(
        text("SELECT count(*) FROM identity_verifications WHERE customer_id IN (:a, :b)"),
        {"a": first["id"], "b": second["id"]},
    ).scalar() == 0


def test_media_keeps_the_customers_caption_and_the_writing_number(db_tx, no_bot) -> None:
    primary, alternate = _phone(), _phone()
    customer = _customer(db_tx, phone=primary, alt=alternate)
    out = db_whatsapp.process_whatsapp_webhook(_webhook(alternate, {
        "type": "document",
        "document": {"id": "media-1", "filename": "receipt.pdf", "caption": "paid today"},
    }))
    (result,) = out["results"]
    assert result["customerId"] == customer["id"]
    body = db_tx.execute(
        text("SELECT body FROM messages WHERE id = :m"), {"m": result["messageId"]}
    ).scalar()
    assert body == "[Document: receipt.pdf] paid today"
    conv = bot_conversation.load_conversation(db.engine, result["conversationId"])
    assert bot_conversation.reply_phone(conv) == alternate


def test_a_failed_item_makes_meta_redeliver(db_tx, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import main
    import whatsapp

    monkeypatch.setattr(whatsapp, "verify_signature", lambda *_a: True)
    monkeypatch.setattr(db_whatsapp, "_ingest_inbound_whatsapp_message",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))
    response = TestClient(main.app).post(
        "/webhooks/whatsapp", json=_webhook(_phone(), {"type": "text", "text": {"body": "hi"}})
    )
    assert response.status_code == 503


# --- the bot -----------------------------------------------------------------


def test_the_bot_does_not_send_when_admission_cannot_be_established(monkeypatch) -> None:
    import bot_jobs

    monkeypatch.setattr(bot_jobs, "bot_runtime_enabled", lambda: True)
    monkeypatch.setattr(bot_conversation, "whatsapp_opted_in", lambda *_a: True)
    monkeypatch.setattr(contact_policy, "admit", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("down")))
    conv = {"id": "CV-X", "customer_id": "C-X", "status": "bot", "assigned_user_id": None,
            "channel": "whatsapp", "dnd": False, "last_customer_at": utc_now()}
    assert bot_conversation.policy_gate(db.engine, conv) == "policy_unavailable"


# --- suggestions -------------------------------------------------------------


def test_retrieval_asks_about_the_latest_message_not_an_older_question(db_tx) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(hours=3), body="how do I pay?")
    _message(db_tx, cv, "agent", ago=timedelta(hours=2), body="Here is the link")
    _message(db_tx, cv, "customer", ago=timedelta(minutes=1), body="please send my statement")
    query = db_inbox_rag._conversation_rag_query(db_tx, cv)
    assert query.splitlines()[0] == "Customer: please send my statement"
    assert "Here is the link" not in query


def test_a_failed_search_says_its_passages_are_stale(db_tx, monkeypatch) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(minutes=1), body="question")
    monkeypatch.setattr(db_inbox_rag, "_studio_retrieval",
                        lambda *_a: (_ for _ in ()).throw(RuntimeError("kb down")))
    out = db.refresh_conversation_suggestions(cv)
    assert out["stale"] is True


def test_a_draft_for_an_earlier_turn_is_not_offered(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(hours=2))
    db_tx.execute(
        text(
            "INSERT INTO ai_response_suggestions (id, conversation_id, suggestion_text, source, accepted, created_at) "
            "VALUES (:id, :cv, 'an answer to the first question', 'kb_draft', false, now() - interval '1 hour')"
        ),
        {"id": _uid("SUG"), "cv": cv},
    )
    as_actor(AGENT)
    assert db.get_conversation(cv)["ragDraftAnswer"] == "an answer to the first question"
    _message(db_tx, cv, "customer", ago=timedelta(minutes=1))
    assert db.get_conversation(cv)["ragDraftAnswer"] is None


def test_a_document_filed_from_a_thread_reads_that_threads_identity(db_tx, as_actor) -> None:
    customer = _customer(db_tx)
    cv = _thread(db_tx, customer)
    as_actor(AGENT)
    ix = db_inbox.conversation_interaction_id(cv, customer["id"])
    assert ix and ix.startswith("IX-")
    assert db_inbox.conversation_interaction_id(cv, _customer(db_tx)["id"]) is None
