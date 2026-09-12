"""Opening a customer card does not re-run the treatment engine every time."""

from __future__ import annotations

from sqlalchemy import text

import db


def test_the_treatment_preview_is_memoised_per_customer(db_tx, monkeypatch) -> None:
    """Every open of a card ran features, candidates, veto and score for the
    same borrower and the same answer; the preview is kept for a minute."""
    from agent_core import treatment

    customer = db_tx.execute(text("SELECT id FROM customers WHERE id <> 'UNKNOWN-CALLER' LIMIT 1")).scalar()
    calls: list[str] = []
    real = treatment.recommend_treatment

    def _counted(**kw):
        calls.append(kw["customer_id"])
        return real(**kw)

    monkeypatch.setattr(treatment, "recommend_treatment", _counted)
    db._PREVIEW_CACHE.clear()
    first = db._treatment_snapshot(db_tx, customer)
    second = db._treatment_snapshot(db_tx, customer)
    assert calls == [customer]
    assert second == first
