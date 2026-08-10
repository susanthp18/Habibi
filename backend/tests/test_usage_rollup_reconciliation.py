"""The daily rollup must reconcile with the events that produced it.

``usage_meter.flush()`` writes each event to ``usage_events`` and adds the batch
total into ``billing_usage_daily``. Those are two records of the same money, and
the billing screens read the second one — so any scale mismatch between them is
an understatement users see and events do not explain.

That is not hypothetical: ``billing_usage_daily.cost_inr`` was ``numeric(14,2)``
against events at ``numeric(14,6)``, so every flush rounded to paise and a batch
worth less than half a paisa rounded to zero and vanished. Real data carried
both symptoms before migration 20260801_0058.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

import usage_meter


@pytest.fixture
def meter(monkeypatch):
    """A meter whose buffer is ours alone and whose flusher never races us."""
    with usage_meter._buffer_lock:
        usage_meter._buffer.clear()
    monkeypatch.setattr(usage_meter, "_ensure_flusher", lambda: None)
    yield usage_meter
    with usage_meter._buffer_lock:
        usage_meter._buffer.clear()


def _totals(conn, service_id: str) -> tuple[Decimal, Decimal]:
    """(rollup, events) cost for a service, same day, same tenant/env."""
    from sqlalchemy import text

    rollup = conn.execute(
        text(
            "SELECT COALESCE(SUM(cost_inr), 0) FROM billing_usage_daily "
            "WHERE service_id = :s AND usage_date = CURRENT_DATE"
        ),
        {"s": service_id},
    ).scalar()
    events = conn.execute(
        text(
            "SELECT COALESCE(SUM(cost_inr), 0) FROM usage_events "
            "WHERE service_id = :s AND occurred_at::date = CURRENT_DATE"
        ),
        {"s": service_id},
    ).scalar()
    return Decimal(rollup), Decimal(events)


def test_rollup_matches_events_after_flush(db_tx, meter) -> None:
    import db

    with db.engine.begin() as conn:
        before_rollup, before_events = _totals(conn, usage_meter.SERVICE_TTS)

    meter.record_tts_usage(chars=812, voice="en-IN-NeerjaNeural")
    meter.record_tts_usage(chars=1450, voice="en-IN-NeerjaNeural")
    assert meter.flush() == 2

    with db.engine.begin() as conn:
        after_rollup, after_events = _totals(conn, usage_meter.SERVICE_TTS)

    assert after_rollup - before_rollup == after_events - before_events


def test_sub_paisa_batch_is_not_rounded_away(db_tx, meter) -> None:
    """The failure that lost a whole day of llm_embed spend to 0.00.

    A single small embedding call costs well under half a paisa; at
    numeric(14,2) the rollup stored nothing at all while the event kept the
    charge, so the two records disagreed and the cheaper one was billed.
    """
    import db

    with db.engine.begin() as conn:
        before_rollup, before_events = _totals(conn, usage_meter.SERVICE_EMBED)

    # ~0.0000172 INR at the default price book — far below a paisa.
    meter.record_embed_usage(prompt_tokens=10, deployment="text-embedding-3-small")
    assert meter.flush() == 1

    with db.engine.begin() as conn:
        after_rollup, after_events = _totals(conn, usage_meter.SERVICE_EMBED)

    charged = after_events - before_events
    assert charged > 0, "the event itself must carry a non-zero charge"
    assert after_rollup - before_rollup == charged


def test_many_small_flushes_do_not_accumulate_drift(db_tx, meter) -> None:
    """Each flush is a separate rounding opportunity, and the error was
    systematically downward rather than noise that cancels."""
    import db

    with db.engine.begin() as conn:
        before_rollup, before_events = _totals(conn, usage_meter.SERVICE_CHAT)

    for _ in range(25):
        meter.record_chat_usage(prompt_tokens=7, completion_tokens=3, model="gpt-5-mini")
        assert meter.flush() == 1

    with db.engine.begin() as conn:
        after_rollup, after_events = _totals(conn, usage_meter.SERVICE_CHAT)

    assert after_rollup - before_rollup == after_events - before_events


def test_rollup_columns_are_at_least_as_precise_as_events(db_tx) -> None:
    """Pins the invariant directly, so a future narrowing fails loudly here
    rather than quietly in the invoice."""
    from sqlalchemy import text

    import db

    with db.engine.begin() as conn:
        scales = dict(
            conn.execute(
                text(
                    """
                    SELECT table_name || '.' || column_name, numeric_scale
                      FROM information_schema.columns
                     WHERE (table_name = 'usage_events'
                            OR table_name = 'billing_usage_daily')
                       AND column_name IN ('cost_inr', 'units')
                    """
                )
            ).all()
        )

    assert scales["billing_usage_daily.cost_inr"] >= scales["usage_events.cost_inr"]
    assert scales["billing_usage_daily.units"] >= scales["usage_events.units"]
