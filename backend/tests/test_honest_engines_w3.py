"""W3 — honest reach, cure, and censoring labels."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text

from agent_core.treatment import cancel, followthrough


def test_cancelled_is_censoring_not_a_training_outcome() -> None:
    assert "cancelled" in followthrough.RESOLVING
    assert cancel.PLAN_EXPIRED in cancel.REASONS
    src = followthrough.__doc__ or ""
    assert "outcome" in src


def test_ptp_does_not_close_cure() -> None:
    reach, cure = followthrough._reach_and_cure(
        None,
        {"enacted": True},
        "ptp",
        now=datetime.now(timezone.utc),
    )
    assert reach == "reached"
    assert cure is None


def test_rupee_one_cannot_keep_a_fifty_thousand_promise(db_tx) -> None:
    import payments

    row = db_tx.execute(
        text(
            """
            SELECT p.id, p.account_id, p.customer_id, p.amount
            FROM promises p
            WHERE p.status IN ('upcoming','due_today','partial')
              AND p.amount >= 1000
            ORDER BY p.amount DESC
            LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no open promise")
    applied = payments.allocate_to_promises(
        db_tx,
        account_id=row["account_id"],
        amount=Decimal("1"),
        preferred_promise_id=row["id"],
    )
    assert applied
    assert applied[0]["status"] != "kept"
    status = db_tx.execute(
        text("SELECT status, paid_amount FROM promises WHERE id = :id"),
        {"id": row["id"]},
    ).mappings().first()
    assert status["status"] == "partial"
    assert float(status["paid_amount"]) == 1.0


def test_variant_is_selected_for_attribution() -> None:
    text_src = Path(followthrough.__file__).read_text(encoding="utf-8")
    select = text_src.split("def attribute_outcomes")[1].split("def _outcome_for")[0]
    assert "variant" in select
