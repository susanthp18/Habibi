"""The Hub's case against the end of the call, across real transactions.

``db_tx`` runs everything on one connection, where a wrap-up and the call's
completion can never interleave. These tests COMMIT (``db_real``) and clean up
after themselves."""

from __future__ import annotations

import threading
import time
import uuid

import pytest
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


@pytest.mark.parametrize(
    ("meanwhile", "refusal"),
    [
        ("UPDATE interaction_handoffs SET completed_at = now() WHERE id = :ho", (ValueError, "handoff_closed")),
        ("UPDATE interaction_handoffs SET to_user_id = :other WHERE id = :ho", (PermissionError, "handoff_not_assigned")),
    ],
    ids=["wrapped-up", "taken-over"],
)
def test_a_disclosure_waits_for_a_wrap_up_or_takeover_in_flight(db_real, meanwhile, refusal) -> None:
    """The holder was checked on an unlocked read: a wrap-up or a takeover
    committed after that check, and the disclosure was written anyway. It
    must wait on the case's lock and then see who holds it."""
    import actor_context

    ix, ho = _case(db_real)
    db_real.track("interaction_disclosures", interaction_id=ix)
    other_user = f"HUB-OTHER-{uuid.uuid4().hex[:8].upper()}"
    with db_real.begin() as conn:
        conn.execute(text("INSERT INTO users (id, tenant_id, name) VALUES (:id, :t, :id)"), {"id": other_user, "t": db.current_tenant()})
    db_real.track("users", id=other_user)
    with db_real.connect() as conn:
        holder = conn.execute(text("SELECT to_user_id FROM interaction_handoffs WHERE id = :ho"), {"ho": ho}).scalar()
    errors: list[BaseException] = []

    def disclose() -> None:
        token = actor_context.set_actor_user_id(holder)
        try:
            db.record_handoff_disclosure(ix, {"itemId": "rule-recording", "ruleId": "rule-recording"})
        except BaseException as exc:  # noqa: BLE001 -- judged in the main thread
            errors.append(exc)
        finally:
            actor_context.reset_actor_user_id(token)

    with db_real.begin() as other:
        other.execute(text("SELECT 1 FROM interactions WHERE id = :ix FOR UPDATE"), {"ix": ix})
        worker = threading.Thread(target=disclose)
        worker.start()
        time.sleep(1.0)  # the disclosure is now waiting on the case's lock
        assert worker.is_alive(), "the disclosure did not wait for the case's lock"
        other.execute(text(meanwhile), {"ho": ho, "other": other_user})
    worker.join(timeout=30)
    assert not worker.is_alive()
    kind, code = refusal
    assert len(errors) == 1 and isinstance(errors[0], kind) and code in str(errors[0]), errors
    with db_real.connect() as conn:
        written = conn.execute(text("SELECT count(*) FROM interaction_disclosures WHERE interaction_id = :ix"), {"ix": ix}).scalar()
    assert written == 0
