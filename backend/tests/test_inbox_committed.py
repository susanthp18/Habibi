"""The Inbox across real transactions: what ``db_tx`` cannot show.

``db_tx`` runs a test as one transaction on one connection. Two "concurrent"
writers there are the same writer, and ``now()`` is frozen at its start -- so
every ``updated_at`` it stamps is the same instant, and a delta poll cannot
tell a thread that changed from one that did not. These tests COMMIT
(``db_real``) and clean up after themselves.
"""

from __future__ import annotations

import threading
import uuid
from contextlib import contextmanager

from sqlalchemy import event, text

import actor_context
import bot_conversation
import db
import db_core

HUB = "IB-REAL-HUB"
INBOX = "IB-REAL-INBOX"


@contextmanager
def _acting_as(user_id: str):
    token = actor_context.set_actor_user_id(user_id)
    try:
        yield
    finally:
        actor_context.reset_actor_user_id(token)


def _thread(db_real, *, channel: str = "whatsapp", status: str = "needs_human") -> tuple[str, str, str]:
    """A customer, a loan and one thread on it, committed. (interaction, conversation, customer)."""
    tag = uuid.uuid4().hex[:8].upper()
    product, bot = f"PROD-REAL-{tag}", f"BOT-REAL-{tag}"
    cust, acc = f"CUST-REAL-{tag}", f"ACC-REAL-{tag}"
    ix, cv = f"IX-REAL-{tag}", f"CV-REAL-{tag}"
    t = db.current_tenant()
    with db_real.begin() as conn:
        for uid in (HUB, INBOX):
            conn.execute(
                text("INSERT INTO users (id, tenant_id, name) VALUES (:id, :t, :id) ON CONFLICT DO NOTHING"),
                {"id": uid, "t": t},
            )
        conn.execute(
            text("INSERT INTO products (id, tenant_id, name, type) VALUES (:id, :t, 'Real loan', 'loan')"),
            {"id": product, "t": t},
        )
        conn.execute(
            text("INSERT INTO bots (id, tenant_id, name, version) VALUES (:id, :t, 'Real bot', '1')"),
            {"id": bot, "t": t},
        )
        conn.execute(
            text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, 'Real Fixture', 'low')"),
            {"id": cust, "t": t},
        )
        conn.execute(
            text("INSERT INTO accounts (id, customer_id, product_id, outstanding, dpd) VALUES (:id, :c, :p, 5000, 12)"),
            {"id": acc, "c": cust, "p": product},
        )
        conn.execute(
            text(
                "INSERT INTO interactions (id, tenant_id, customer_id, account_id, handler_kind, handler_bot_id, "
                "channel, status) VALUES (:id, :t, :c, :a, 'bot', :bot, :ch, 'active')"
            ),
            {"id": ix, "t": t, "c": cust, "a": acc, "bot": bot, "ch": channel},
        )
        conn.execute(
            text(
                "INSERT INTO conversations (id, interaction_id, customer_id, status, channel) "
                "VALUES (:id, :ix, :c, :s, :ch)"
            ),
            {"id": cv, "ix": ix, "c": cust, "s": status, "ch": channel},
        )
    # Torn down in reverse: what refers to a row goes before it.
    for uid in (HUB, INBOX):
        db_real.track("users", id=uid)
    db_real.track("products", id=product)
    db_real.track("bots", id=bot)
    db_real.track("customers", id=cust)
    db_real.track("accounts", id=acc)
    db_real.track("interactions", id=ix)
    db_real.track("conversations", id=cv)
    db_real.track("interaction_handoffs", interaction_id=ix)
    db_real.track("interaction_participants", interaction_id=ix)
    db_real.track("messages", conversation_id=cv)
    db_real.track("activity_events", entity_id=cv)
    db_real.track("activity_events", entity_id=ix)
    return ix, cv, cust


# --- lock order ------------------------------------------------------------


def test_a_hub_claim_and_an_inbox_takeover_at_once_do_not_deadlock(db_real) -> None:
    """The Hub locked its handoff row first and the Inbox the conversation
    first: a claim and a takeover arriving together each held what the other
    waited for. Both now lock conversation, interaction, handoff in order.

    Each side pauses after its first row lock until the other has one too. In
    one order the second blocks on the first's row and never gets there, the
    pause times out, and they run one after the other. In opposite orders both
    get there holding a row each, and Postgres kills one as a deadlock."""
    ix, cv, _ = _thread(db_real)
    with db_real.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO interaction_handoffs (id, interaction_id, from_kind, to_kind, reason, requested_at) "
                "VALUES (:id, :ix, 'bot', 'human', 'customer_requested', now())"
            ),
            {"id": f"HO-REAL-{uuid.uuid4().hex[:8].upper()}", "ix": ix},
        )
    both_locked = threading.Barrier(2)
    seen = threading.local()

    def pause_after_first_lock(_conn, _cursor, statement, *_a) -> None:
        if "FOR UPDATE" in statement and not getattr(seen, "locked", False):
            seen.locked = True
            try:
                both_locked.wait(timeout=3)
            except threading.BrokenBarrierError:
                pass  # the other is queued behind this one's lock: the safe order

    outcomes: dict[str, object] = {}

    def run(name: str, actor: str, call) -> None:
        with _acting_as(actor):
            try:
                call()
                outcomes[name] = "ok"
            except Exception as exc:  # noqa: BLE001 -- judged in the main thread
                outcomes[name] = exc

    event.listen(db_core.engine, "after_cursor_execute", pause_after_first_lock)
    try:
        threads = [
            threading.Thread(target=run, args=("hub", HUB, lambda: db.claim_handoff(ix))),
            threading.Thread(
                target=run,
                args=("inbox", INBOX, lambda: db.takeover_conversation(cv, {"expectedAssigneeId": None})),
            ),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
    finally:
        event.remove(db_core.engine, "after_cursor_execute", pause_after_first_lock)
    assert not any(t.is_alive() for t in threads), "a side never finished"

    # One wins; the other is refused because the thread is held -- never a
    # deadlock, which is a database error, not a refusal.
    assert all(o == "ok" or isinstance(o, ValueError) for o in outcomes.values()), outcomes
    assert "ok" in outcomes.values(), outcomes
    with db_real.connect() as conn:
        holder = conn.execute(text("SELECT assigned_user_id FROM conversations WHERE id = :cv"), {"cv": cv}).scalar()
    assert holder in (HUB, INBOX)


# --- the delta poll --------------------------------------------------------


def _reply(db_real, cv: str, sender: str, *, provider_ref: str | None = None) -> str:
    mid = f"MSG-REAL-{uuid.uuid4().hex[:8].upper()}"
    with db_real.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at) "
                "VALUES (:id, :cv, :s, 'on its way', 'sending', :ref, now())"
            ),
            {"id": mid, "cv": cv, "s": sender, "ref": provider_ref},
        )
    return mid


def _polled_after(cv: str, change) -> bool:
    """Is the thread in the delta poll after ``change``, from the watermark
    the browser held before it?"""
    with _acting_as(INBOX):
        (row,) = [r for r in db.list_conversations(q=cv) if r["id"] == cv]
        watermark = row["updatedAt"]
        assert cv not in {r["id"] for r in db.list_conversations(updated_after=watermark)}
        change()
        return cv in {r["id"] for r in db.list_conversations(updated_after=watermark)}


def test_an_sms_receipt_brings_its_thread_into_the_delta_poll(db_real) -> None:
    """The SMS status callback moved the bubble and not the watermark: the
    thread kept its old awaiting count and SLA until a full refresh."""
    import delivery_receipts

    _, cv, cust = _thread(db_real, channel="sms", status="assigned")
    sid = f"SM{uuid.uuid4().hex}"
    db_real.track("contact_delivery_events", provider_ref=sid)
    _reply(db_real, cv, "agent", provider_ref=sid)
    assert _polled_after(
        cv,
        lambda: delivery_receipts.record_twilio_sms_status(
            sid=sid, state="delivered", reason=None, customer_id=cust
        ),
    )


def test_the_bots_own_send_brings_its_thread_into_the_delta_poll(db_real) -> None:
    _, cv, cust = _thread(db_real, status="bot")
    mid = _reply(db_real, cv, "bot")
    assert _polled_after(
        cv,
        lambda: bot_conversation.finalize_outbound(
            db.engine, message_id=mid, provider_ref=f"wamid.{mid}", delivery_status="sent",
            customer_id=cust, conversation_id=cv, body="hello",
        ),
    )
