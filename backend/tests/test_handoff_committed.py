"""The Hub's case against the end of the call, across real transactions.

``db_tx`` runs everything on one connection, where a wrap-up and the call's
completion can never interleave. These tests COMMIT (``db_real``) and clean up
after themselves."""

from __future__ import annotations

import threading
import time
import uuid

from sqlalchemy import text

import db


def _case(db_real) -> tuple[str, str]:
    """A voice call handed to a person, the case claimed by a person, committed."""
    tag = uuid.uuid4().hex[:8].upper()
    product, bot, cust = f"PROD-HUB-{tag}", f"BOT-HUB-{tag}", f"CUST-HUB-{tag}"
    ix, ho, agent = f"IX-HUB-{tag}", f"HO-HUB-{tag}", f"HUB-AGENT-{tag}"
    t = db.current_tenant()
    with db_real.begin() as conn:
        conn.execute(text("INSERT INTO users (id, tenant_id, name) VALUES (:id, :t, :id)"), {"id": agent, "t": t})
        conn.execute(
            text("INSERT INTO products (id, tenant_id, name, type) VALUES (:id, :t, 'Hub loan', 'loan')"),
            {"id": product, "t": t},
        )
        conn.execute(
            text("INSERT INTO bots (id, tenant_id, name, version) VALUES (:id, :t, 'Hub bot', '1')"),
            {"id": bot, "t": t},
        )
        conn.execute(
            text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, 'Hub Fixture', 'low')"),
            {"id": cust, "t": t},
        )
        conn.execute(
            text(
                "INSERT INTO interactions (id, tenant_id, customer_id, handler_kind, handler_user_id, channel, "
                "status, disposition, started_at) VALUES (:id, :t, :c, 'human', :u, 'voice', 'active', 'escalated', now())"
            ),
            {"id": ix, "t": t, "c": cust, "u": agent},
        )
        conn.execute(
            text(
                "INSERT INTO interaction_handoffs (id, interaction_id, from_kind, from_bot_id, to_kind, to_user_id, "
                "reason, requested_at, accepted_at) VALUES (:id, :ix, 'bot', :bot, 'human', :u, 'dispute', now(), now())"
            ),
            {"id": ho, "ix": ix, "bot": bot, "u": agent},
        )
    db_real.track("users", id=agent)
    db_real.track("products", id=product)
    db_real.track("bots", id=bot)
    db_real.track("customers", id=cust)
    db_real.track("interactions", id=ix)
    db_real.track("interaction_handoffs", interaction_id=ix)
    db_real.track("voice_sessions", interaction_id=ix)
    db_real.track("activity_events", entity_id=ix)
    return ix, ho


def test_a_wrap_up_saved_while_the_call_is_filed_is_kept(db_real, monkeypatch) -> None:
    """The completion read the case in one transaction and wrote the
    disposition in another: a wrap-up saved between them was overwritten with
    'escalated'. The wrap-up here holds the interaction (as it does) while the
    completion starts; the completion must wait for it and keep its outcome."""
    from agent_core.live_qa import scorecard
    from voice import persist

    monkeypatch.setattr(scorecard, "score_completed_interaction", lambda _ix: None)
    ix, ho = _case(db_real)

    errors: list[BaseException] = []

    def complete() -> None:
        try:
            persist.complete_voice_call(session_id=f"VS-{ix}", interaction_id=ix, disposition="escalated")
        except BaseException as exc:  # noqa: BLE001 -- judged in the main thread
            errors.append(exc)

    with db_real.begin() as wrap:
        wrap.execute(text("SELECT 1 FROM interactions WHERE id = :ix FOR UPDATE"), {"ix": ix})
        worker = threading.Thread(target=complete)
        worker.start()
        time.sleep(1.0)  # the completion is now waiting on the wrap-up's lock
        assert worker.is_alive(), "the completion did not wait for the wrap-up"
        wrap.execute(
            text("UPDATE interactions SET disposition = 'Info provided' WHERE id = :ix"), {"ix": ix}
        )
        wrap.execute(
            text("UPDATE interaction_handoffs SET completed_at = now(), wrap_up_notes = 'explained' WHERE id = :ho"),
            {"ho": ho},
        )
    worker.join(timeout=30)
    assert not worker.is_alive() and not errors, errors

    with db_real.connect() as conn:
        row = conn.execute(
            text(
                "SELECT i.status, i.disposition, h.completed_at, h.wrap_up_notes FROM interactions i "
                "JOIN interaction_handoffs h ON h.interaction_id = i.id WHERE i.id = :ix"
            ),
            {"ix": ix},
        ).mappings().one()
    assert row["status"] == "completed"
    assert row["disposition"] == "Info provided"
    assert row["completed_at"] is not None and row["wrap_up_notes"] == "explained"
