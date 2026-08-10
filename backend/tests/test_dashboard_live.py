"""The executive dashboard reports what the database says.

Before this, ``get_dashboard`` accepted ``range``/``segment``/``team`` and used
none of them, read ``analytics_daily`` (one seeded row, no runtime writer, and
``db.py`` already tells callers not to read it), and hardcoded the rest:
``sentimentDistribution {58,27,15}``, ``recoveryRate 68.4%``, ``ptp 61.8%``, a
``*12000`` money multiplier, ``whatsapp: 13``, ``recovered = outstanding*0.42``
over six rows, and ``upsell = 12 + rank*1.3``.

Every filter combination therefore returned identical numbers, on the most-
viewed screen in the product. These tests pin that the filters filter and that
the literals are gone.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

import db


# ---------------------------------------------------------------------------
# The filters actually filter — the headline defect
# ---------------------------------------------------------------------------


def _calls(payload: dict) -> str:
    return next(k["value"] for k in payload["kpis"] if k["key"] == "calls")


def test_range_changes_the_numbers() -> None:
    """`today` and `qtd` returned byte-identical payloads."""
    today = db.get_dashboard(range="today")
    quarter = db.get_dashboard(range="qtd")

    assert _calls(today) != _calls(quarter)
    assert len(today["callVolumeStacked"]) < len(quarter["callVolumeStacked"])


def test_team_filter_partitions_interactions() -> None:
    every = db.get_dashboard(range="qtd", team="all")
    bot = db.get_dashboard(range="qtd", team="bot")
    human = db.get_dashboard(range="qtd", team="human")

    def _n(p: dict) -> int:
        return int(_calls(p).replace(",", ""))

    assert _n(bot) + _n(human) == _n(every)
    # Containment is definitionally 100% for the bot slice and 0% for human.
    containment = {p["key"]: p["value"] for p in bot["kpis"]}["containment"]
    assert containment == "100.0%"


def test_segment_narrows_the_book() -> None:
    every = db.get_dashboard(range="qtd", segment="all")
    card = db.get_dashboard(range="qtd", segment="card")

    def _n(p: dict) -> int:
        return int(_calls(p).replace(",", ""))

    assert _n(card) < _n(every)


def test_unknown_range_falls_back_rather_than_raising() -> None:
    """A dashboard should degrade to its default range, not 400.

    bot_analytics deliberately raises on an unknown range; this endpoint has a
    different contract because it is the app's landing screen.
    """
    payload = db.get_dashboard(range="not-a-range")
    assert payload["kpis"]


# ---------------------------------------------------------------------------
# The fabricated values are gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "literal",
    ["68.4%", "61.8%", "14.6%", "12000", "0.42"],
)
def test_hardcoded_kpi_literals_are_gone(literal: str) -> None:
    import json

    payload = json.dumps(db.get_dashboard(range="qtd"))
    assert literal not in payload


def test_sentiment_distribution_is_computed_not_literal() -> None:
    payload = db.get_dashboard(range="qtd")
    dist = payload["sentimentDistribution"]

    assert dist != {"positive": 58, "neutral": 27, "negative": 15}
    assert all(isinstance(v, int) for v in dist.values())
    # Sums to 100 or is entirely empty — never a partial total.
    assert sum(dist.values()) in (0, 100)


def test_whatsapp_volume_is_not_the_literal_13() -> None:
    payload = db.get_dashboard(range="qtd")
    counts = {p["whatsapp"] for p in payload["callVolumeStacked"]}

    assert counts != {13}


def test_money_is_rendered_in_rupees() -> None:
    """These are INR balances; the tile rendered them as $X.XXM."""
    payload = db.get_dashboard(range="qtd")
    recovered = next(k for k in payload["kpis"] if k["key"] == "recovered")

    assert "$" not in recovered["value"]
    assert "₹" in recovered["value"]


def test_recovery_rate_states_its_own_formula() -> None:
    """A rate whose definition lives only in a query is a rate nobody checks."""
    payload = db.get_dashboard(range="qtd")
    rate = next(k for k in payload["kpis"] if k["key"] == "recoveryRate")

    assert "outstanding" in (rate.get("sub") or "")


# ---------------------------------------------------------------------------
# Honest nulls
# ---------------------------------------------------------------------------


def _empty_the_window(conn) -> None:
    """Push every dated row out of any recent window.

    Shifted rather than deleted: `interactions` is referenced by
    `bot_turn_jobs`, and the point here is an empty *window*, not an empty
    database — which is also the realistic production case on a quiet day.
    """
    conn.execute(text("UPDATE interactions SET started_at = now() - interval '5 years'"))
    conn.execute(text("UPDATE ledger_entries SET posted_at = now() - interval '5 years'"))
    conn.execute(text("UPDATE promises SET created_at = now() - interval '5 years'"))
    conn.execute(text("UPDATE leads SET created_at = now() - interval '5 years'"))


def test_no_prior_period_yields_null_delta_not_zero(db_tx) -> None:
    """"Flat" and "nothing to compare against" are different claims."""
    _empty_the_window(db_tx)

    payload = db.get_dashboard(range="7d")
    calls = next(k for k in payload["kpis"] if k["key"] == "calls")

    assert calls["delta"] is None


def test_empty_window_does_not_divide_by_zero(db_tx) -> None:
    _empty_the_window(db_tx)

    payload = db.get_dashboard(range="7d")

    assert payload["recoveryTrend"] == []
    assert payload["callVolumeStacked"] == []
    assert payload["sentimentDistribution"] == {"positive": 0, "neutral": 0, "negative": 0}
    # Uncomputable rates render as a dash rather than 0.0%.
    assert next(k for k in payload["kpis"] if k["key"] == "ptp")["value"] == "—"


def test_response_shape_survives_an_empty_window(db_tx) -> None:
    """DashboardResponse requires all eight keys; fallbacks must be shape-valid."""
    _empty_the_window(db_tx)

    payload = db.get_dashboard(range="today")

    for key in (
        "heroKpis",
        "kpis",
        "recoveryTrend",
        "callVolumeStacked",
        "sentimentDistribution",
        "botVsHuman",
        "leaderboard",
        "atRiskAccounts",
    ):
        assert key in payload


# ---------------------------------------------------------------------------
# Series come from the real tables
# ---------------------------------------------------------------------------


def test_recovery_trend_sums_actual_payments(db_tx) -> None:
    """Payments are stored negative; the trend must report them as recovery."""
    db_tx.execute(text("DELETE FROM ledger_entries"))
    account = db_tx.execute(text("SELECT id FROM accounts LIMIT 1")).scalar()
    db_tx.execute(
        text(
            "INSERT INTO ledger_entries (id, account_id, type, amount, posted_at) "
            "VALUES ('LE-TEST-1', :a, 'payment', -5000, now() - interval '2 days')"
        ),
        {"a": account},
    )

    payload = db.get_dashboard(range="7d")

    assert len(payload["recoveryTrend"]) == 1
    assert payload["recoveryTrend"][0]["value"] == 5000.0


def test_charges_are_not_counted_as_recovery(db_tx) -> None:
    db_tx.execute(text("DELETE FROM ledger_entries"))
    account = db_tx.execute(text("SELECT id FROM accounts LIMIT 1")).scalar()
    db_tx.execute(
        text(
            "INSERT INTO ledger_entries (id, account_id, type, amount, posted_at) "
            "VALUES ('LE-TEST-2', :a, 'charge', 9000, now() - interval '2 days')"
        ),
        {"a": account},
    )

    assert db.get_dashboard(range="7d")["recoveryTrend"] == []


def test_sparklines_are_real_series_not_synthetic_noise() -> None:
    """_spark(seed) generated deterministic noise from an unrelated number."""
    payload = db.get_dashboard(range="qtd")
    calls = next(k for k in payload["kpis"] if k["key"] == "calls")
    volume = payload["callVolumeStacked"]

    if volume:
        assert calls["spark"]
        assert len(calls["spark"]) <= 14


def test_analytics_daily_is_no_longer_read() -> None:
    """db.py:4592 tells callers not to read the stub tables; this one did."""
    import inspect

    source = inspect.getsource(db.get_dashboard)
    assert "analytics_daily" not in source
