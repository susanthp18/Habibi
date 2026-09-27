"""The customer card shows the engine's recorded decision; it never re-runs it."""

from __future__ import annotations

from sqlalchemy import text

import db


def test_opening_a_card_reads_the_log_and_never_runs_the_engine(db_tx, monkeypatch) -> None:
    """The card used to run a fresh randomised preview on every open, so it
    could disagree with the cases panel, the copilot and itself. It now reads
    the one current decision every surface reads, and runs nothing."""
    from agent_core import treatment
    from agent_core.treatment import Trigger

    customer = db_tx.execute(text("SELECT id FROM customers WHERE id <> 'UNKNOWN-CALLER' LIMIT 1")).scalar()
    recorded = treatment.recommend_treatment(
        customer_id=customer, trigger=Trigger(kind="manual", ref="manual:card-test"),
        conn=db_tx, force_mode="shadow",
    )
    assert recorded.decision_id

    calls: list[str] = []
    monkeypatch.setattr(treatment, "recommend_treatment", lambda **kw: calls.append(kw["customer_id"]))
    first = db._treatment_snapshot(db_tx, customer)
    second = db._treatment_snapshot(db_tx, customer)
    assert calls == []
    assert first and first["decisionId"] == recorded.decision_id
    assert second == first
