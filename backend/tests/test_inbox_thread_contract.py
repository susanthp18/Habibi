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

And what a review of the fixes found still wrong:

* a thread with a promise failed to load;
* a queued reply counted as an answer, and a receipt never reached the list;
* a redelivered webhook moved the reply number, and an edited phone inherited
  the window another number opened;
* a Handoff Hub claim left the Inbox thread unheld;
* an empty search returned last time's passages as fresh, and a stored draft
  outlived the message it answered;
* a promise or dispute could name another borrower's loan;
* the list's views stopped at its first 500 rows.

And a third pass:

* a slower search for an older message overwrote the newer one's passages;
* the Hub and the Inbox locked a thread in opposite orders;
* a phone edited mid-ingest gave the old message the new number, and a tie
  on the clock picked the number by arrival, not by the thread's order;
* SMS receipts and the bot's own sends never moved the list's watermark;
* any agent could hand a colleague's escalation to the bot;
* a message out of retries said "retrying";
* the list ended at 500 with no next page, and no number found anyone.

Every row is created here -- staff, product and bot included; nothing depends
on the seed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

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

AGENT = "IB-FIXTURE-AGENT"
COLLEAGUE = "IB-FIXTURE-COLLEAGUE"
PRODUCT = "IB-FIXTURE-PRODUCT"
BOT = "IB-FIXTURE-BOT"


@pytest.fixture(autouse=True)
def world(db_tx):
    """The staff, product and bot every thread here needs."""
    tenant = db.current_tenant()
    for uid in (AGENT, COLLEAGUE):
        db_tx.execute(
            text("INSERT INTO users (id, tenant_id, name) VALUES (:id, :t, :id)"),
            {"id": uid, "t": tenant},
        )
    db_tx.execute(
        text("INSERT INTO products (id, tenant_id, name, type) VALUES (:id, :t, 'Fixture loan', 'loan')"),
        {"id": PRODUCT, "t": tenant},
    )
    db_tx.execute(
        text("INSERT INTO bots (id, tenant_id, name, version) VALUES (:id, :t, 'Fixture bot', '1')"),
        {"id": BOT, "t": tenant},
    )


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
                "VALUES (:id, :c, :p, 5000, 12)"
            ),
            {"id": aid, "c": cid, "p": PRODUCT},
        )
        accounts.append(aid)
    return {"id": cid, "accounts": accounts}


def _thread(conn, customer: dict, *, channel: str = "whatsapp", status: str = "bot",
            assignee: str | None = None, account: int = 1) -> str:
    """A thread on the customer's *second* account: the first is a decoy."""
    ix, cv = _uid("IX"), _uid("CV")
    handler = (
        "'human', :u, NULL" if assignee else "'bot', NULL, :bot"
    )
    conn.execute(
        text(
            "INSERT INTO interactions (id, tenant_id, customer_id, account_id, handler_kind, "
            f"handler_user_id, handler_bot_id, channel, status) VALUES (:id, :t, :c, :a, {handler}, :ch, 'active')"
        ),
        {"id": ix, "t": db.current_tenant(), "c": customer["id"], "a": customer["accounts"][account],
         "ch": channel, "u": assignee, "bot": BOT},
    )
    conn.execute(
        text(
            "INSERT INTO conversations (id, interaction_id, customer_id, assigned_user_id, status, channel) "
            "VALUES (:id, :ix, :c, :u, :s, :ch)"
        ),
        {"id": cv, "ix": ix, "c": customer["id"], "u": assignee, "s": status, "ch": channel},
    )
    return cv


def _wrote_from(conn, cv: str, slot: str) -> None:
    """What ingest records when the customer writes: which number it was."""
    column = "phone_alt_hmac" if slot == "alt" else "phone_primary_hmac"
    conn.execute(
        text(
            "UPDATE interactions i SET source_payload = COALESCE(i.source_payload, '{}'::jsonb) "
            f"|| jsonb_build_object('endpoint_hmac', encode(c.{column}, 'hex')) "
            "FROM conversations cv JOIN customers c ON c.id = cv.customer_id "
            "WHERE cv.id = :cv AND i.id = cv.interaction_id"
        ),
        {"cv": cv},
    )


def _message(conn, cv: str, sender: str, *, ago: timedelta, status: str = "delivered",
             real: bool = True, body: str | None = None) -> str:
    mid = _uid("MSG")
    if real and sender == "customer":
        _wrote_from(conn, cv, "primary")
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


def test_a_queued_reply_has_not_answered_anyone(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="assigned", assignee=AGENT)
    _message(db_tx, cv, "customer", ago=timedelta(hours=5))
    _message(db_tx, cv, "agent", ago=timedelta(hours=4), status="sending")
    as_actor(AGENT)
    # With the outbound worker stopped, it never will.
    row = _summary(cv)
    assert row["awaitingReply"] == 1 and row["sla"] == "warn"


def test_a_delivery_receipt_moves_the_threads_watermark(db_tx) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="assigned", assignee=AGENT)
    reply = _message(db_tx, cv, "agent", ago=timedelta(hours=4), status="sent")
    db_tx.execute(
        text("UPDATE messages SET provider_ref = :ref WHERE id = :m"), {"ref": f"wamid.{reply}", "m": reply}
    )
    # Inside one transaction now() is frozen, so the trigger's new updated_at
    # equals the old one; the update shows as a new version of the row. The
    # list's delta poll reads updated_at: an untouched row kept its old
    # awaiting count and SLA until a full refresh.
    version = "SELECT ctid::text FROM conversations WHERE id = :cv"
    before = db_tx.execute(text(version), {"cv": cv}).scalar()
    db_whatsapp._apply_whatsapp_status(db_tx, wa_message_id=f"wamid.{reply}", status="delivered")
    assert db_tx.execute(text(version), {"cv": cv}).scalar() != before


def test_views_run_on_the_server_and_count_the_whole_inbox(db_tx, as_actor) -> None:
    customer = _customer(db_tx)
    mine = [_thread(db_tx, customer, status="assigned", assignee=AGENT) for _ in range(2)]
    theirs = _thread(db_tx, customer, status="assigned", assignee=COLLEAGUE)
    waiting = _thread(db_tx, customer, status="needs_human")
    as_actor(AGENT)
    assert sorted(r["id"] for r in db.list_conversations(view="mine")) == sorted(mine)
    others = {r["id"] for r in db.list_conversations(view="others", customer_id=customer["id"])}
    assert others == {theirs}
    needs = {r["id"] for r in db.list_conversations(view="needs_human", customer_id=customer["id"])}
    assert needs == {waiting}
    counts = db.conversation_counts()
    assert counts["mine"] == 2
    assert counts["all"] >= 4 and counts["others"] >= 1 and counts["needs_human"] >= 1
    with pytest.raises(ValueError, match="invalid_view"):
        db.list_conversations(view="unread")


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


def test_the_list_pages_on_past_its_first_page_in_its_own_order(db_tx, as_actor, monkeypatch) -> None:
    customer = _customer(db_tx)
    # No messages: all three sort on the same instant, so the page boundary
    # falls inside a tie and only the id orders them.
    threads = [_thread(db_tx, customer) for _ in range(3)]
    monkeypatch.setattr(db_inbox, "INBOX_LIST_LIMIT", 2)
    as_actor(AGENT)
    first = db.list_conversations(customer_id=customer["id"])
    last = first[-1]
    rest = db.list_conversations(customer_id=customer["id"], before_at=last["lastAt"], before_id=last["id"])
    assert [r["id"] for r in first + rest] == sorted(threads)
    with pytest.raises(ValueError, match="invalid_before"):
        db.list_conversations(before_at="yesterday", before_id=last["id"])


def test_search_finds_a_customer_by_number_and_a_call_by_what_was_said(db_tx, as_actor) -> None:
    phone = _phone()
    customer = _customer(db_tx, phone=phone)
    cv = _thread(db_tx, customer)
    call = _thread(db_tx, customer, channel="voice")
    ix = db_tx.execute(text("SELECT interaction_id FROM conversations WHERE id = :cv"), {"cv": call}).scalar()
    needle = f"spoken-{uuid.uuid4().hex[:6]}"
    db_tx.execute(
        text("INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, text, at_sec) "
             "VALUES (:id, :ix, 1, 'customer', :t, 3)"),
        {"id": _uid("TR"), "ix": ix, "t": f"I said {needle} on the call"},
    )
    as_actor(AGENT)
    digits = "".join(ch for ch in phone if ch.isdigit())
    assert {r["id"] for r in db.list_conversations(q=digits)} == {cv, call}
    assert {r["id"] for r in db.list_conversations(q=phone)} == {cv, call}
    assert [r["id"] for r in db.list_conversations(q=needle)] == [call]


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


def test_a_thread_with_a_promise_loads(db_tx, as_actor) -> None:
    customer = _customer(db_tx)
    cv = _thread(db_tx, customer)
    _message(db_tx, cv, "customer", ago=timedelta(hours=1))
    # 18:30 UTC is midnight in India: the promise falls due on the 2nd.
    db_tx.execute(
        text(
            "INSERT INTO promises (id, customer_id, account_id, owner_kind, owner_user_id, amount, "
            "promised_at, status, reminder_status) VALUES (:id, :c, :a, 'human', :u, 2500, "
            "'2026-11-01 18:30:00+00', 'upcoming', 'off')"
        ),
        {"id": _uid("PTP"), "c": customer["id"], "a": customer["accounts"][1], "u": AGENT},
    )
    as_actor(AGENT)
    promise = db.get_conversation(cv)["context"]["lastPromise"]
    assert promise == {"amount": 2500.0, "date": "2026-11-02", "status": "Pending"}


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


def test_a_handoff_hub_claim_gives_the_claimant_the_thread(db_tx, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx), status="needs_human")
    ix = db_tx.execute(text("SELECT interaction_id FROM conversations WHERE id = :cv"), {"cv": cv}).scalar()
    db_tx.execute(
        text(
            "INSERT INTO interaction_handoffs (id, interaction_id, from_kind, to_kind, reason, requested_at) "
            "VALUES (:id, :ix, 'bot', 'human', 'customer_requested', now())"
        ),
        {"id": _uid("HO"), "ix": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    thread = db.get_conversation(cv)
    # The Hub moved only the interaction: the Inbox showed it unheld and
    # refused the claimant's reply.
    assert thread["isMine"] and thread["status"] == "assigned"
    assert _handler(db_tx, cv) == {"handler_kind": "human", "handler_user_id": AGENT}


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


def test_a_colleagues_escalation_is_theirs(db_tx, as_actor) -> None:
    """An escalation keeps its assignee. Any agent could hand it to the bot,
    taking it from the colleague on it; it was missing from "held by others"."""
    customer = _customer(db_tx)
    cv = _thread(db_tx, customer, status="needs_human", assignee=COLLEAGUE)
    as_actor(AGENT)
    with pytest.raises(ValueError, match="return_to_bot_not_allowed"):
        db.return_conversation_to_bot(cv)
    assert {r["id"] for r in db.list_conversations(view="others", customer_id=customer["id"])} == {cv}


def test_the_hub_and_the_inbox_lock_a_thread_in_the_same_order(db_tx, as_actor) -> None:
    """Conversation first, on both. The Hub took its handoff row first while
    the Inbox took the conversation first: a claim and a takeover of the same
    thread at once each held what the other waited for. One transaction
    cannot race itself, so this pins the order each path locks in."""
    cv = _thread(db_tx, _customer(db_tx), status="needs_human")
    ix = db_tx.execute(text("SELECT interaction_id FROM conversations WHERE id = :cv"), {"cv": cv}).scalar()
    db_tx.execute(
        text(
            "INSERT INTO interaction_handoffs (id, interaction_id, from_kind, to_kind, reason, requested_at) "
            "VALUES (:id, :ix, 'bot', 'human', 'customer_requested', now())"
        ),
        {"id": _uid("HO"), "ix": ix},
    )
    as_actor(AGENT)

    def first_lock(call) -> str:
        seen: list[str] = []
        listener = lambda *a: seen.append(a[2])  # noqa: E731
        event.listen(db_core.engine, "before_cursor_execute", listener)
        try:
            call()
        finally:
            event.remove(db_core.engine, "before_cursor_execute", listener)
        return next(" ".join(s.split()) for s in seen if "FOR UPDATE" in s)

    assert "FROM conversations" in first_lock(lambda: db.claim_handoff(ix))
    db_tx.execute(
        text("UPDATE conversations SET assigned_user_id = NULL, status = 'needs_human' WHERE id = :cv"),
        {"cv": cv},
    )
    assert "FROM conversations" in first_lock(
        lambda: db.takeover_conversation(cv, {"expectedAssigneeId": None})
    )


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
    _wrote_from(db_tx, cv, "alt")
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
    ctx = db.get_conversation(cv)["context"]
    assert ctx["replyToSlot"] == "alt"
    assert ctx["replyToLast4"] == "".join(ch for ch in alternate if ch.isdigit())[-4:]


def test_an_edited_phone_does_not_inherit_the_window_another_number_opened(
    db_tx, as_actor, gate_open
) -> None:
    customer = _customer(db_tx, phone=_phone(), alt=_phone())
    cv = _thread(db_tx, customer, status="assigned", assignee=AGENT)
    _message(db_tx, cv, "customer", ago=timedelta(minutes=10))
    _wrote_from(db_tx, cv, "alt")
    db_tx.execute(
        text("UPDATE customers SET phone_alt = :p WHERE id = :c"), {"p": _phone(), "c": customer["id"]}
    )
    as_actor(AGENT)
    ctx = db.get_conversation(cv)["context"]
    assert ctx["canReply"] is False and ctx["replyBlockedReason"] == "whatsapp_endpoint_changed"
    with pytest.raises(ValueError, match="whatsapp_endpoint_changed"):
        db.send_conversation_message(cv, {"text": "hello"})
    conv = bot_conversation.load_conversation(db.engine, cv)
    assert conv["endpoint_slot"] is None


# --- WhatsApp ingest -------------------------------------------------------


def _webhook(from_phone: str, msg: dict, *, ago: timedelta = timedelta(0), wamid: str | None = None,
             at: datetime | None = None) -> dict:
    digits = "".join(ch for ch in from_phone if ch.isdigit())
    return {
        "entry": [{"changes": [{"value": {
            "contacts": [{"wa_id": digits, "profile": {"name": "Fixture"}}],
            "messages": [{"id": wamid or f"wamid.{uuid.uuid4().hex}", "from": digits,
                          "timestamp": str(int((at or utc_now() - ago).timestamp())), **msg}],
        }}]}]
    }


def test_a_redelivered_or_late_message_does_not_move_the_reply_number(db_tx, no_bot) -> None:
    primary, alternate = _phone(), _phone()
    _customer(db_tx, phone=primary, alt=alternate)
    hello = {"type": "text", "text": {"body": "hi"}}
    early = f"wamid.{uuid.uuid4().hex}"
    db_whatsapp.process_whatsapp_webhook(_webhook(alternate, hello, ago=timedelta(minutes=10), wamid=early))
    (latest,) = db_whatsapp.process_whatsapp_webhook(_webhook(primary, hello))["results"]
    cv = latest["conversationId"]

    # Meta redelivers the older one, and a delayed one from the same number lands late.
    (dup,) = db_whatsapp.process_whatsapp_webhook(
        _webhook(alternate, hello, ago=timedelta(minutes=10), wamid=early)
    )["results"]
    assert dup["status"] == "duplicate"
    db_whatsapp.process_whatsapp_webhook(_webhook(alternate, hello, ago=timedelta(minutes=5)))

    conv = bot_conversation.load_conversation(db.engine, cv)
    assert bot_conversation.reply_phone(conv) == primary


def test_a_phone_edited_mid_ingest_does_not_give_the_message_the_new_number(
    db_tx, no_bot, monkeypatch
) -> None:
    primary, alternate = _phone(), _phone()
    customer = _customer(db_tx, phone=primary, alt=alternate)
    matched = db_whatsapp._match_customer_by_phone

    def match_then_edit(conn, phone):
        found = matched(conn, phone)
        # Someone edits the number between the match and the endpoint write.
        conn.execute(text("UPDATE customers SET phone_alt = :p WHERE id = :c"),
                     {"p": _phone(), "c": customer["id"]})
        return found

    monkeypatch.setattr(db_whatsapp, "_match_customer_by_phone", match_then_edit)
    (result,) = db_whatsapp.process_whatsapp_webhook(
        _webhook(alternate, {"type": "text", "text": {"body": "hi"}})
    )["results"]
    conv = bot_conversation.load_conversation(db.engine, result["conversationId"])
    # Read again at the write, the digest was the replacement's: the old
    # message's window went to a number that never wrote.
    assert conv["endpoint_slot"] is None


def test_a_tie_on_the_clock_goes_to_the_threads_own_latest(db_tx, no_bot, monkeypatch) -> None:
    primary, alternate = _phone(), _phone()
    _customer(db_tx, phone=primary, alt=alternate)
    # Message ids that fall as they arrive: the first is the thread's latest.
    run, ids = uuid.uuid4().hex[:6].upper(), iter(range(9, 0, -1))
    make_id = db_whatsapp._id
    monkeypatch.setattr(
        db_whatsapp, "_id", lambda prefix: f"MSG-{run}-{next(ids)}" if prefix == "MSG" else make_id(prefix)
    )
    at = utc_now() - timedelta(minutes=1)
    hello = {"type": "text", "text": {"body": "hi"}}
    (first,) = db_whatsapp.process_whatsapp_webhook(_webhook(primary, hello, at=at))["results"]
    db_whatsapp.process_whatsapp_webhook(_webhook(alternate, hello, at=at))
    cv = first["conversationId"]
    latest = [m for m in db.get_conversation(cv)["messages"] if m.get("sender") == "customer"][-1]
    assert latest["id"] == first["messageId"]
    conv = bot_conversation.load_conversation(db.engine, cv)
    assert bot_conversation.reply_phone(conv) == primary


def test_an_sms_receipt_and_the_bots_own_send_move_the_watermark(db_tx) -> None:
    """The list's delta poll reads updated_at. The WhatsApp receipt moved it;
    the SMS callback and the bot's send did not, and those threads kept their
    old awaiting count and SLA until a full refresh."""
    import delivery_receipts

    customer = _customer(db_tx)
    version = "SELECT ctid::text FROM conversations WHERE id = :cv"
    sms = _thread(db_tx, customer, channel="sms", status="assigned", assignee=AGENT)
    reply = _message(db_tx, sms, "agent", ago=timedelta(minutes=5), status="sending")
    sid = f"SM{uuid.uuid4().hex}"
    db_tx.execute(text("UPDATE messages SET provider_ref = :sid WHERE id = :m"), {"sid": sid, "m": reply})
    before = db_tx.execute(text(version), {"cv": sms}).scalar()
    assert delivery_receipts.record_twilio_sms_status(
        sid=sid, state="delivered", reason=None, customer_id=customer["id"]
    )
    assert db_tx.execute(text(version), {"cv": sms}).scalar() != before

    wa = _thread(db_tx, customer)
    bot = _message(db_tx, wa, "bot", ago=timedelta(minutes=1), status="sending")
    before = db_tx.execute(text(version), {"cv": wa}).scalar()
    bot_conversation.finalize_outbound(
        db.engine, message_id=bot, provider_ref=f"wamid.{bot}", delivery_status="sent",
        customer_id=customer["id"], conversation_id=wa, body="hello",
    )
    assert db_tx.execute(text(version), {"cv": wa}).scalar() != before


def test_a_message_out_of_retries_does_not_say_retrying() -> None:
    error = "code=130429 rate limited"
    assert db_inbox._delivery_note(error, "pending") == "WhatsApp rate limit — retrying"
    assert db_inbox._delivery_note(error, "failed") == "WhatsApp rate limit — not sent"


def test_a_provider_rejection_moves_the_job_off_succeeded(db_tx) -> None:
    """WAO-14F8282BF6AC read `succeeded` while carrying "code=131047 ...
    Message failed to send", and its message read `failed`: anything counting
    job status over-reported delivery."""
    cv = _thread(db_tx, _customer(db_tx))
    reply = _message(db_tx, cv, "bot", ago=timedelta(minutes=1), status="sent")
    db_tx.execute(
        text("UPDATE messages SET provider_ref = :ref WHERE id = :m"), {"ref": f"wamid.{reply}", "m": reply}
    )
    db_tx.execute(
        text(
            "INSERT INTO whatsapp_outbound_jobs (id, message_id, conversation_id, customer_id, to_phone, "
            "body, purpose, source, status) VALUES (:id, :m, :cv, "
            "(SELECT customer_id FROM conversations WHERE id = :cv), 'x', 'x', 'in_session', 'bot', 'succeeded')"
        ),
        {"id": _uid("WAO"), "m": reply, "cv": cv},
    )
    db_whatsapp._apply_whatsapp_status(
        db_tx, wa_message_id=f"wamid.{reply}", status="failed",
        errors=[{"code": 131047, "title": "Message failed to send"}],
    )
    job = db_tx.execute(
        text("SELECT status, error FROM whatsapp_outbound_jobs WHERE message_id = :m"), {"m": reply}
    ).mappings().one()
    assert job["status"] == "failed" and job["error"].startswith("code=131047")


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
            "channel": "whatsapp", "dnd": False, "last_customer_at": utc_now(),
            "endpoint_slot": "primary"}
    assert bot_conversation.policy_gate(db.engine, conv) == "policy_unavailable"
    # The number that opened the window has left the record: no reply goes.
    assert bot_conversation.policy_gate(db.engine, {**conv, "endpoint_slot": None}) == (
        "whatsapp_endpoint_changed"
    )


# --- suggestions -------------------------------------------------------------


def test_retrieval_asks_about_the_latest_message_not_an_older_question(db_tx) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(hours=3), body="how do I pay?")
    _message(db_tx, cv, "agent", ago=timedelta(hours=2), body="Here is the link")
    _message(db_tx, cv, "customer", ago=timedelta(minutes=1), body="please send my statement")
    query, _answers = db_inbox_rag._conversation_rag_query(db_tx, cv)
    assert query.splitlines()[0] == "Customer: please send my statement"
    assert "Here is the link" not in query


def test_a_failed_search_says_its_passages_are_stale(db_tx, monkeypatch) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(minutes=1), body="question")
    monkeypatch.setattr(db_inbox_rag, "_studio_retrieval",
                        lambda *_a: (_ for _ in ()).throw(RuntimeError("kb down")))
    out = db.refresh_conversation_suggestions(cv)
    assert out["stale"] is True


def test_an_empty_search_is_empty_not_last_times_passages(db_tx, monkeypatch) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(hours=2), body="first question")
    db_tx.execute(
        text(
            "INSERT INTO ai_response_suggestions (id, conversation_id, suggestion_text, source, accepted) "
            "VALUES (:id, :cv, 'a passage about the first question', 'kb', false)"
        ),
        {"id": _uid("SUG"), "cv": cv},
    )
    latest = _message(db_tx, cv, "customer", ago=timedelta(minutes=1), body="second question")
    monkeypatch.setattr(db_inbox_rag, "_studio_retrieval",
                        lambda *_a: {"results": [], "draftAnswer": None, "draftFailed": False})
    out = db.refresh_conversation_suggestions(cv)
    assert out["ragSuggestions"] == [] and out["stale"] is False
    assert out["answersMessageId"] == latest
    assert db.get_conversation(cv)["ragSuggestions"] == []


def test_a_draft_names_the_message_it_answers_and_is_not_kept(db_tx, monkeypatch, as_actor) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    latest = _message(db_tx, cv, "customer", ago=timedelta(minutes=1), body="when is my EMI due?")
    hit = {"score": 0.9, "docTitle": "EMI", "heading": "Dates", "snippet": "EMIs fall due on the 5th."}
    monkeypatch.setattr(db_inbox_rag, "_studio_retrieval",
                        lambda *_a: {"results": [hit], "draftAnswer": "It is due on the 5th.",
                                     "draftFailed": False})
    out = db.refresh_conversation_suggestions(cv, include_draft_answer=True)
    assert out["draftAnswer"] == "It is due on the 5th." and out["answersMessageId"] == latest
    as_actor(AGENT)
    # A stored draft outlived the message it answered and was offered for the next.
    assert "ragDraftAnswer" not in db.get_conversation(cv)
    assert db_tx.execute(
        text("SELECT count(*) FROM ai_response_suggestions WHERE conversation_id = :cv AND source = 'kb_draft'"),
        {"cv": cv},
    ).scalar() == 0


def test_a_slower_search_for_an_older_message_does_not_replace_the_newer_ones(db_tx, monkeypatch) -> None:
    cv = _thread(db_tx, _customer(db_tx))
    _message(db_tx, cv, "customer", ago=timedelta(minutes=5), body="first question")
    db_tx.execute(
        text(
            "INSERT INTO ai_response_suggestions (id, conversation_id, suggestion_text, source, accepted) "
            "VALUES (:id, :cv, 'the passage for the newer question', 'kb', false)"
        ),
        {"id": _uid("SUG"), "cv": cv},
    )
    hit = {"score": 0.9, "docTitle": "Old", "heading": "Old", "snippet": "A passage for the first question."}

    def slow_retrieval(*_a):
        # The customer writes again while this one searches.
        _message(db_tx, cv, "customer", ago=timedelta(seconds=1), body="second question")
        return {"results": [hit], "draftAnswer": "an answer to the first", "draftFailed": False}

    monkeypatch.setattr(db_inbox_rag, "_studio_retrieval", slow_retrieval)
    out = db.refresh_conversation_suggestions(cv, include_draft_answer=True)
    assert out["superseded"] is True and out["ragSuggestions"] == [] and out["draftAnswer"] is None
    assert db_inbox._conversation_suggestions(db_tx, cv, None) == ["the passage for the newer question"]


# --- records filed from a thread -------------------------------------------


def test_a_promise_or_dispute_cannot_name_another_borrowers_loan(db_tx, as_actor) -> None:
    customer, stranger = _customer(db_tx), _customer(db_tx)
    as_actor(AGENT)
    with pytest.raises(ValueError, match="account_not_customers"):
        db.create_promise({"customerId": customer["id"], "accountId": stranger["accounts"][0],
                           "amount": 100, "promisedDate": "2026-11-02"})
    with pytest.raises(ValueError, match="account_not_customers"):
        db.create_dispute({"customerId": customer["id"], "accountId": stranger["accounts"][0],
                           "type": "paid_already"})
    # Their own loan is filed as named, not swapped for their first.
    assert db_core._customer_account_id(db_tx, customer["id"], customer["accounts"][1]) == (
        customer["accounts"][1]
    )


def test_a_document_filed_from_a_thread_reads_that_threads_identity(db_tx, as_actor) -> None:
    customer = _customer(db_tx)
    cv = _thread(db_tx, customer)
    as_actor(AGENT)
    ix = db_inbox.conversation_interaction_id(cv, customer["id"])
    assert ix and ix.startswith("IX-")
    assert db_inbox.conversation_interaction_id(cv, _customer(db_tx)["id"]) is None
