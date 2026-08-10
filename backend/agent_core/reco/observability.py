"""Part 7 of the plan — the numbers that decide whether the engine stays on.

`offer_decisions` has carried every field these need since the engine shipped;
nothing surfaced them, which meant the only way to answer "is the recommender
helping?" was to write ad-hoc SQL and trust whoever wrote it. This module is
the one definition of each metric, so the dashboard, the alert and the weekly
review cannot quietly disagree about what "presentation rate" means.

Two decisions worth stating:

* **Simulated rows are excluded by default.** Synthetic traffic from
  `scripts/simulate_offer_decisions.py` is tagged `mode='simulated'` precisely
  so it can never leak into a number someone makes a decision on.
* **Alerts are computed here, not in the UI.** A threshold that lives in a
  chart config is a threshold nobody reviews. Each metric carries its own
  breach state and the reason, so the same verdict reaches a dashboard, a page
  and a weekly report.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Windows the endpoint accepts, mapped to a Postgres interval. A closed set,
# because the alternative is interpolating user input into an interval literal.
WINDOWS: dict[str, str] = {
    "24h": "24 hours",
    "7d": "7 days",
    "30d": "30 days",
    "90d": "90 days",
}
DEFAULT_WINDOW = "30d"

REAL_MODES = ("live", "shadow")

# Thresholds from the plan's Part 7 table. Env-tunable would be nice; hard-coded
# and reviewed in a diff is better than a number someone changed in a UI at 2am.
LATENCY_P99_BUDGET_MS = 150.0
COVERAGE_DROP_ALERT = 0.20
SUPPRESSION_CONCENTRATION_ALERT = 0.60
FALLBACK_RATE_ALERT = 0.01
CLOSE_PROBE_CONVERSION_FLOOR = 0.01


def _interval(window: str) -> tuple[str, str]:
    key = (window or DEFAULT_WINDOW).strip().lower()
    if key not in WINDOWS:
        logger.warning("unknown observability window %r — using %s", window, DEFAULT_WINDOW)
        key = DEFAULT_WINDOW
    return key, WINDOWS[key]


def _modes(include_simulated: bool) -> list[str]:
    return list(REAL_MODES) + (["simulated"] if include_simulated else [])


def _rows(conn: Any, sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings()]


def _one(conn: Any, sql: str, params: dict[str, Any]) -> dict[str, Any]:
    rows = _rows(conn, sql, params)
    return rows[0] if rows else {}


def _ratio(numerator: Any, denominator: Any) -> float | None:
    """None, not zero, when the denominator is zero.

    A presentation rate of 0% and "we made no offers to present" are different
    facts, and only one of them is a problem.
    """
    n, d = float(numerator or 0), float(denominator or 0)
    return round(n / d, 4) if d else None


def offer_health(
    window: str = DEFAULT_WINDOW,
    *,
    include_simulated: bool = False,
) -> dict[str, Any]:
    """Every Part 7 metric, plus its alert state."""
    import db

    key, interval = _interval(window)
    params = {"modes": _modes(include_simulated)}

    with db.engine.connect() as conn:
        totals = _one(
            conn,
            f"""
            SELECT
              COUNT(*)::int                                                  AS decisions,
              COUNT(*) FILTER (WHERE suppression_reason IS NULL)::int        AS approved,
              COUNT(*) FILTER (WHERE presented)::int                         AS presented,
              COUNT(*) FILTER (WHERE response = 'interested')::int           AS interested,
              COUNT(*) FILTER (WHERE response = 'declined')::int             AS declined,
              COUNT(*) FILTER (WHERE response IS NOT NULL)::int              AS responded,
              COUNT(DISTINCT customer_id)::int                               AS customers,
              COUNT(DISTINCT interaction_id)
                FILTER (WHERE interaction_id IS NOT NULL)::int               AS interactions
            FROM offer_decisions
            WHERE mode = ANY(:modes) AND created_at > now() - interval '{interval}'
            """,
            params,
        )

        # Previous window, same length — coverage is alerted on week-over-week
        # change, and an absolute coverage number means nothing without it.
        previous = _one(
            conn,
            f"""
            SELECT
              COUNT(*)::int                                            AS decisions,
              COUNT(*) FILTER (WHERE suppression_reason IS NULL)::int  AS approved
            FROM offer_decisions
            WHERE mode = ANY(:modes)
              AND created_at <= now() - interval '{interval}'
              AND created_at >  now() - interval '{interval}' - interval '{interval}'
            """,
            params,
        )

        latency = _one(
            conn,
            f"""
            SELECT
              percentile_disc(0.50) WITHIN GROUP (ORDER BY latency_ms) AS p50,
              percentile_disc(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95,
              percentile_disc(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99,
              MAX(latency_ms)                                          AS max,
              COUNT(latency_ms)::int                                   AS n
            FROM offer_decisions
            WHERE mode = ANY(:modes)
              AND created_at > now() - interval '{interval}'
              AND latency_ms IS NOT NULL
            """,
            params,
        )

        suppression = _rows(
            conn,
            f"""
            SELECT suppression_reason AS reason, COUNT(*)::int AS n
            FROM offer_decisions
            WHERE mode = ANY(:modes)
              AND created_at > now() - interval '{interval}'
              AND suppression_reason IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC
            """,
            params,
        )

        # `excluded` is {productId: reason}; the reason carries a stable prefix
        # ("eligibility:…"), so grouping on the prefix answers "what is
        # actually filtering the catalogue" without exploding per product.
        exclusion = _rows(
            conn,
            f"""
            SELECT split_part(value, ':', 1) AS reason, COUNT(*)::int AS n
            FROM offer_decisions d, jsonb_each_text(d.excluded)
            WHERE d.mode = ANY(:modes)
              AND d.created_at > now() - interval '{interval}'
            GROUP BY 1 ORDER BY 2 DESC LIMIT 20
            """,
            params,
        )

        by_product = _rows(
            conn,
            f"""
            SELECT
              d.chosen_product_id                                       AS product_id,
              p.name                                                    AS product_name,
              COUNT(*) FILTER (WHERE d.presented)::int                  AS presented,
              COUNT(*) FILTER (WHERE d.response = 'interested')::int    AS interested,
              COUNT(DISTINCT l.id) FILTER (WHERE l.stage = 'won')::int  AS won,
              COUNT(DISTINCT l.id) FILTER (WHERE l.stage = 'lost')::int AS lost
            FROM offer_decisions d
            LEFT JOIN products p ON p.id = d.chosen_product_id
            LEFT JOIN leads l ON l.id = d.lead_id
            WHERE d.mode = ANY(:modes)
              AND d.created_at > now() - interval '{interval}'
              AND d.chosen_product_id IS NOT NULL
            GROUP BY 1, 2 ORDER BY 3 DESC
            """,
            params,
        )

        by_recommender = _rows(
            conn,
            f"""
            SELECT
              d.recommender, d.recommender_version                       AS version,
              COUNT(*) FILTER (WHERE d.presented)::int                   AS presented,
              COUNT(*) FILTER (WHERE d.response = 'interested')::int     AS interested,
              COUNT(DISTINCT l.id) FILTER (WHERE l.stage = 'won')::int   AS won,
              COUNT(DISTINCT l.id) FILTER (WHERE l.stage = 'lost')::int  AS lost
            FROM offer_decisions d
            LEFT JOIN leads l ON l.id = d.lead_id
            WHERE d.mode = ANY(:modes)
              AND d.created_at > now() - interval '{interval}'
            GROUP BY 1, 2 ORDER BY 3 DESC
            """,
            params,
        )

        # The A/B readout. Grouped on `variant` rather than `recommender`
        # because two arms can share a scorer — a mode holdout runs the same
        # one and stays silent — and grouping on the scorer would merge them.
        by_variant = _rows(
            conn,
            f"""
            SELECT
              d.variant,
              COUNT(*)::int                                              AS decisions,
              COUNT(DISTINCT d.customer_id)::int                         AS customers,
              COUNT(*) FILTER (WHERE d.suppression_reason IS NULL)::int   AS approved,
              COUNT(*) FILTER (WHERE d.presented)::int                    AS presented,
              COUNT(*) FILTER (WHERE d.response = 'interested')::int      AS interested,
              COUNT(DISTINCT l.id) FILTER (WHERE l.stage = 'won')::int    AS won,
              AVG(i.duration_sec)::float                                  AS avg_duration_sec,
              AVG(i.avg_sentiment)::float                                 AS avg_sentiment
            FROM offer_decisions d
            LEFT JOIN leads l ON l.id = d.lead_id
            LEFT JOIN interactions i ON i.id = d.interaction_id
            WHERE d.mode = ANY(:modes)
              AND d.created_at > now() - interval '{interval}'
              AND d.variant IS NOT NULL
            GROUP BY 1 ORDER BY 2 DESC
            """,
            params,
        )

        # `unknown` rate on eligibility flags. A rising unknown rate is the
        # early warning that a source system stopped answering: nothing blocks
        # (by design), so the offers keep flowing and nothing else complains.
        veto = _one(
            conn,
            f"""
            SELECT
              COUNT(*)::int                                     AS flags,
              COUNT(*) FILTER (WHERE passed IS FALSE
                               AND reason ILIKE '%%unknown%%')::int AS unknown,
              COUNT(*) FILTER (WHERE passed IS FALSE
                               AND reason NOT ILIKE '%%unknown%%')::int AS failed
            FROM lead_eligibility le
            JOIN leads l ON l.id = le.lead_id
            WHERE l.captured_at > now() - interval '{interval}'
            """,
            {},
        )

        probe = _one(
            conn,
            f"""
            SELECT
              COUNT(*) FILTER (WHERE kind = 'close_probe_presented')::int AS asked,
              COUNT(*) FILTER (WHERE kind = 'offer_declined')::int        AS declined,
              COUNT(*) FILTER (WHERE kind = 'lead_captured')::int         AS captured
            FROM activity_events
            WHERE at > now() - interval '{interval}'
              AND kind IN ('close_probe_presented', 'offer_declined', 'lead_captured')
            """,
            {},
        )

        # Handle time and escalation on calls that carried an offer versus
        # those that did not. This is the guardrail the probe lives or dies on:
        # a conversion lift bought with 40 seconds of AHT is not a win.
        aht = _rows(
            conn,
            f"""
            SELECT
              (d.interaction_id IS NOT NULL)          AS offered,
              COUNT(*)::int                           AS interactions,
              AVG(i.duration_sec)::float              AS avg_duration_sec,
              AVG(i.avg_sentiment)::float             AS avg_sentiment,
              -- There is no `outcome` column; escalation shows up as a bot
              -- interaction that ended up with a human, or a disposition the
              -- handoff path stamps. Both, OR'd, because voice and chat set
              -- them on different paths.
              AVG(
                (
                  i.transferred_from_bot_id IS NOT NULL
                  OR COALESCE(i.disposition, '') ILIKE '%%escalat%%'
                )::int
              )::float                                AS escalation_rate
            FROM interactions i
            LEFT JOIN (
              SELECT DISTINCT interaction_id
              FROM offer_decisions
              WHERE mode = ANY(:modes) AND presented AND interaction_id IS NOT NULL
            ) d ON d.interaction_id = i.id
            WHERE i.started_at > now() - interval '{interval}'
            GROUP BY 1
            """,
            params,
        )

    return _assemble(
        window=key,
        totals=totals,
        previous=previous,
        latency=latency,
        suppression=suppression,
        exclusion=exclusion,
        by_product=by_product,
        by_recommender=by_recommender,
        by_variant=by_variant,
        veto=veto,
        probe=probe,
        aht=aht,
        include_simulated=include_simulated,
    )


def _assemble(**parts: Any) -> dict[str, Any]:
    totals = parts["totals"]
    previous = parts["previous"]
    latency = parts["latency"]
    suppression = parts["suppression"]
    probe = parts["probe"]
    veto = parts["veto"]

    decisions = int(totals.get("decisions") or 0)
    approved = int(totals.get("approved") or 0)
    presented = int(totals.get("presented") or 0)
    interested = int(totals.get("interested") or 0)

    coverage = _ratio(approved, decisions)
    prior_coverage = _ratio(previous.get("approved"), previous.get("decisions"))
    coverage_change = (
        round(coverage - prior_coverage, 4)
        if coverage is not None and prior_coverage is not None
        else None
    )

    suppression_total = sum(int(r["n"]) for r in suppression) or 0
    top_suppression = suppression[0] if suppression else None
    top_suppression_share = (
        _ratio(top_suppression["n"], suppression_total) if top_suppression else None
    )

    p99 = latency.get("p99")
    probe_asked = int(probe.get("asked") or 0)
    probe_captured = int(probe.get("captured") or 0)

    aht_by_offer = {bool(r["offered"]): r for r in parts["aht"]}
    with_offer = aht_by_offer.get(True, {})
    without_offer = aht_by_offer.get(False, {})
    aht_delta = None
    if with_offer.get("avg_duration_sec") and without_offer.get("avg_duration_sec"):
        aht_delta = round(
            float(with_offer["avg_duration_sec"]) - float(without_offer["avg_duration_sec"]), 1
        )

    alerts: list[dict[str, str]] = []

    def alert(metric: str, message: str) -> None:
        alerts.append({"metric": metric, "message": message})

    if coverage_change is not None and coverage_change <= -COVERAGE_DROP_ALERT:
        alert(
            "coverage",
            f"offer coverage fell {abs(coverage_change):.1%} versus the previous window",
        )
    if top_suppression_share is not None and top_suppression_share > SUPPRESSION_CONCENTRATION_ALERT:
        alert(
            "suppression",
            f"{top_suppression_share:.0%} of suppressions are a single reason "
            f"({top_suppression['reason']})",
        )
    if p99 is not None and float(p99) > LATENCY_P99_BUDGET_MS:
        alert("latency", f"recommender p99 is {float(p99):.0f}ms against a {LATENCY_P99_BUDGET_MS:.0f}ms budget")
    unknown_rate = _ratio(veto.get("unknown"), veto.get("flags"))
    if unknown_rate is not None and unknown_rate > 0.5:
        alert(
            "eligibility",
            f"{unknown_rate:.0%} of eligibility flags are unknown — a source system may be silent",
        )
    probe_conversion = _ratio(probe_captured, probe_asked)
    if probe_asked >= 100 and probe_conversion is not None and probe_conversion < CLOSE_PROBE_CONVERSION_FLOOR:
        alert(
            "closeProbe",
            f"close probe converts at {probe_conversion:.2%} over {probe_asked} asks — reconsider it",
        )

    return {
        "window": parts["window"],
        "includesSimulated": parts["include_simulated"],
        "volume": {
            "decisions": decisions,
            "approved": approved,
            "presented": presented,
            "customers": int(totals.get("customers") or 0),
            "interactions": int(totals.get("interactions") or 0),
        },
        "funnel": {
            "coverage": coverage,
            "coveragePrevious": prior_coverage,
            "coverageChange": coverage_change,
            "presentationRate": _ratio(presented, approved),
            "interestRate": _ratio(interested, presented),
            "declineRate": _ratio(totals.get("declined"), presented),
            "responseRate": _ratio(totals.get("responded"), presented),
        },
        "latency": {
            "p50": latency.get("p50"),
            "p95": latency.get("p95"),
            "p99": p99,
            "max": latency.get("max"),
            "samples": int(latency.get("n") or 0),
            "budgetMs": LATENCY_P99_BUDGET_MS,
            "withinBudget": None if p99 is None else float(p99) <= LATENCY_P99_BUDGET_MS,
        },
        "suppressionByReason": [
            {**r, "share": _ratio(r["n"], suppression_total)} for r in suppression
        ],
        "exclusionByReason": parts["exclusion"],
        "byProduct": [
            {
                **r,
                "interestRate": _ratio(r["interested"], r["presented"]),
                "winRate": _ratio(r["won"], (r["won"] or 0) + (r["lost"] or 0)),
            }
            for r in parts["by_product"]
        ],
        "byRecommender": [
            {
                **r,
                "interestRate": _ratio(r["interested"], r["presented"]),
                "winRate": _ratio(r["won"], (r["won"] or 0) + (r["lost"] or 0)),
            }
            for r in parts["by_recommender"]
        ],
        "byVariant": [
            {
                "variant": r["variant"],
                "decisions": r["decisions"],
                "customers": r["customers"],
                "approved": r["approved"],
                "presented": r["presented"],
                "interested": r["interested"],
                "won": r["won"],
                "coverage": _ratio(r["approved"], r["decisions"]),
                "interestRate": _ratio(r["interested"], r["presented"]),
                "avgDurationSec": _round(r.get("avg_duration_sec")),
                "avgSentiment": _round(r.get("avg_sentiment"), 3),
            }
            for r in parts["by_variant"]
        ],
        "eligibility": {
            "flags": int(veto.get("flags") or 0),
            "unknown": int(veto.get("unknown") or 0),
            "failed": int(veto.get("failed") or 0),
            "unknownRate": unknown_rate,
        },
        "closeProbe": {
            "asked": probe_asked,
            "declined": int(probe.get("declined") or 0),
            "captured": probe_captured,
            "conversion": probe_conversion,
        },
        "guardrails": {
            "avgDurationSecWithOffer": _round(with_offer.get("avg_duration_sec")),
            "avgDurationSecWithoutOffer": _round(without_offer.get("avg_duration_sec")),
            "ahtDeltaSec": aht_delta,
            "avgSentimentWithOffer": _round(with_offer.get("avg_sentiment"), 3),
            "avgSentimentWithoutOffer": _round(without_offer.get("avg_sentiment"), 3),
            "escalationRateWithOffer": _round(with_offer.get("escalation_rate"), 4),
            "escalationRateWithoutOffer": _round(without_offer.get("escalation_rate"), 4),
        },
        "alerts": alerts,
    }


def _round(value: Any, places: int = 1) -> float | None:
    return None if value is None else round(float(value), places)
