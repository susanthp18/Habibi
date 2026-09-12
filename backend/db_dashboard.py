"""Executive dashboard accessors.

Peeled from ``db.py`` (WP-036 peel 3). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

import money_inr
from schemas import DashboardResponse


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Executive dashboard
#
# Every number below used to be one of three things: a literal, a literal
# multiplied by a live count, or a read of `analytics_daily` — a table with one
# seeded row and no runtime writer, which db.py:4592 already tells callers not
# to read. The range/segment/team parameters were accepted and never used, so
# every filter combination returned identical numbers.
#
# All of it now comes from interactions / ledger_entries / promises / leads.
# Where a figure genuinely cannot be computed (no prior period to compare
# against, a rep with no leads) the API returns null and the UI renders a dash,
# rather than inventing a plausible-looking number.
# ---------------------------------------------------------------------------

# The UI's own vocabulary (Habibi/src/data/dashboard-seed.ts). Deliberately not
# _BOT_ANALYTICS_RANGE_DAYS, which speaks 7d/30d/90d and raises on anything else
# — a dashboard should degrade to its default range, not 400.
_DASHBOARD_RANGE_DAYS = {"today": 1, "7d": 7, "30d": 30, "qtd": 90}
_DASHBOARD_DEFAULT_DAYS = 30

# UI segment → products.family. The screen speaks product language and the
# catalog stores portfolio families; without this map the segment filter
# silently matched nothing.
_DASHBOARD_SEGMENT_FAMILIES = {
    "card": ("revolving_credit",),
    "personal": ("unsecured_loan",),
    "auto": ("secured_loan",),
}


def _dashboard_window(range_key: str, segment: str, team: str) -> dict[str, Any]:
    """Resolve the three filters the endpoint has always accepted and ignored."""
    days = _DASHBOARD_RANGE_DAYS.get(
        (range_key or "").strip().lower(), _DASHBOARD_DEFAULT_DAYS
    )
    families = _DASHBOARD_SEGMENT_FAMILIES.get((segment or "").strip().lower())
    handler = (team or "").strip().lower()
    return {
        "days": days,
        "families": list(families) if families else None,
        "handler_kind": handler if handler in ("bot", "human") else None,
    }


def _pct_delta(current: float | None, prior: float | None) -> float | None:
    """Percentage change, or None when there is nothing to compare against.

    None rather than 0.0: "flat" and "we have no prior data" are different
    claims, and the KPI chips used to render the second as the first.
    """
    if current is None or prior is None or not prior:
        return None
    return round((float(current) - float(prior)) / abs(float(prior)) * 100.0, 1)


def _spark_from_series(values: list[float], *, points: int = 14) -> list[float]:
    """Downsample a real daily series for a sparkline.

    Replaces _spark(seed), which generated deterministic noise from an unrelated
    number — a chart that looked like data and was not.
    """
    clean = [float(v or 0) for v in values]
    if not clean:
        return []
    if len(clean) <= points:
        return [round(v, 2) for v in clean]
    step = len(clean) / points
    return [round(clean[min(len(clean) - 1, int(i * step))], 2) for i in range(points)]


def _inr_compact(amount: float | None) -> str:
    """Compact Indian money. See money_inr.inr_compact for the canonical ladder.

    Mirrors Habibi/src/data/billing-seed.ts::inrCompact exactly. The two used to
    disagree twice over: this side printed "₹1.5 K" where the client printed
    "₹1.5k", and — the one that mattered — this side floored every sub-rupee
    amount to "₹0", which is precisely what main.py warns must not happen to a
    metering figure.
    """
    return money_inr.inr_compact(amount)


@dataclass
class DashboardBuild:
    """One dashboard build: the window and the SQL fragments the head derives,
    the rows ``_dashboard_reads`` fetches in one connection, and what
    ``_dashboard_shape`` makes of them. The bodies are what ``get_dashboard``
    was; ``tests/snapshots/reader_shapes.json`` pins the key tree.
    """

    _dump: Any
    _duration: Any
    _one: Any
    _rows: Any
    _short_product: Any
    days: int
    engine: Any
    families: list[str] | None
    ix_where: str
    params: dict[str, Any]
    since_cur: str
    since_prior: str
    ttft_hours: float | None
    ttft_n: int
    until_cur: str
    until_prior: str
    at_risk: list[dict[str, Any]] = field(default_factory=list)
    leaderboard_rows: list[dict[str, Any]] = field(default_factory=list)
    leads_cur: dict[str, Any] = field(default_factory=dict)
    leads_prior: dict[str, Any] = field(default_factory=dict)
    outstanding_row: dict[str, Any] = field(default_factory=dict)
    prior_recovery: dict[str, Any] = field(default_factory=dict)
    prior_summary: dict[str, Any] = field(default_factory=dict)
    promises_cur: dict[str, Any] = field(default_factory=dict)
    promises_prior: dict[str, Any] = field(default_factory=dict)
    recovery_rows: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    volume_rows: list[dict[str, Any]] = field(default_factory=list)


def _dashboard_reads(st: DashboardBuild) -> None:
    """Every query the dashboard needs, in one connection: the summary and its prior
    window, volume, recovery, outstanding, promises, leads, at-risk, the
    leaderboard and time-to-first-touch."""
    _one = st._one
    _rows = st._rows
    engine = st.engine
    families = st.families
    ix_where = st.ix_where
    params = st.params
    since_cur = st.since_cur
    since_prior = st.since_prior
    ttft_hours = st.ttft_hours
    ttft_n = st.ttft_n
    until_cur = st.until_cur
    until_prior = st.until_prior

    def _ix_window(since: str, until: str) -> str:
        return ix_where.replace(":since", since).replace(":until", until)

    with engine.connect() as conn:
        summary = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*)::int AS interactions,
                      count(*) FILTER (WHERE i.ptp_captured)::int AS ptp_captured,
                      count(*) FILTER (WHERE i.handler_kind = 'human')::int AS human_handled,
                      avg(i.avg_sentiment) AS avg_sentiment,
                      avg(i.duration_sec) AS avg_duration_sec,
                      count(*) FILTER (WHERE i.sentiment_label = 'positive')::int AS pos,
                      count(*) FILTER (WHERE i.sentiment_label = 'neutral')::int AS neu,
                      count(*) FILTER (WHERE i.sentiment_label = 'negative')::int AS neg
                    FROM interactions i
                    {_ix_window(since_cur, until_cur)}
                    """
                ),
                params,
            )
        ) or {}
        prior_summary = _one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*)::int AS interactions,
                      count(*) FILTER (WHERE i.handler_kind = 'human')::int AS human_handled,
                      avg(i.avg_sentiment) AS avg_sentiment,
                      avg(i.duration_sec) AS avg_duration_sec
                    FROM interactions i
                    {_ix_window(since_prior, until_prior)}
                    """
                ),
                params,
            )
        ) or {}

        # Daily interaction volume, split by channel. bot_analytics treats
        # channel as a filter; here it is a pivot, so this cannot reuse it.
        volume_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT to_char(date_trunc('day', i.started_at), 'YYYY-MM-DD') AS date,
                           count(*) FILTER (WHERE i.channel = 'voice')::int AS voice,
                           count(*) FILTER (WHERE i.channel = 'whatsapp')::int AS whatsapp,
                           count(*) FILTER (WHERE i.channel IN ('chat','sms','email'))::int AS chat
                    FROM interactions i
                    {_ix_window(since_cur, until_cur)}
                    GROUP BY 1 ORDER BY 1
                    """
                ),
                params,
            )
        )

        # Money actually collected. Payments are stored negative (a credit
        # against the balance), so the sign is flipped to report a recovery.
        led_segment = " AND p.family = ANY(:families) " if families else ""
        recovery_sql = f"""
            SELECT to_char(date_trunc('day', l.posted_at), 'YYYY-MM-DD') AS date,
                   SUM(-l.amount)::numeric AS value
            FROM ledger_entries l
            JOIN accounts a ON a.id = l.account_id
            JOIN customers c ON c.id = a.customer_id
            JOIN products p ON p.id = a.product_id
            WHERE c.tenant_id = :tenant_id
              AND l.type = 'payment'
              AND l.posted_at >= {{since}} AND l.posted_at < {{until}}
              {led_segment}
            GROUP BY 1 ORDER BY 1
        """
        recovery_rows = _rows(
            conn.execute(
                text(recovery_sql.format(since=since_cur, until=until_cur)), params
            )
        )
        prior_recovery = _one(
            conn.execute(
                text(
                    f"""
                    SELECT COALESCE(SUM(-l.amount), 0)::numeric AS value
                    FROM ledger_entries l
                    JOIN accounts a ON a.id = l.account_id
                    JOIN customers c ON c.id = a.customer_id
                    JOIN products p ON p.id = a.product_id
                    WHERE c.tenant_id = :tenant_id
                      AND l.type = 'payment'
                      AND l.posted_at >= {since_prior} AND l.posted_at < {until_prior}
                      {led_segment}
                    """
                ),
                params,
            )
        ) or {}

        # Outstanding across the filtered book — the denominator of recovery rate.
        outstanding_row = _one(
            conn.execute(
                text(
                    f"""
                    SELECT COALESCE(SUM(a.outstanding), 0)::numeric AS total
                    FROM accounts a
                    JOIN customers c ON c.id = a.customer_id
                    JOIN products p ON p.id = a.product_id
                    WHERE c.tenant_id = :tenant_id AND a.status = 'active'
                      {led_segment}
                    """
                ),
                params,
            )
        ) or {}

        # Promise-kept rate. Denominator is settled promises only: an 'upcoming'
        # promise has not failed, and counting it as unkept made the rate a
        # function of how recently the bot had been running.
        prom_segment = " AND p.family = ANY(:families) " if families else ""
        promise_sql = f"""
            SELECT
              count(*) FILTER (WHERE pr.status = 'kept')::int AS kept,
              count(*) FILTER (WHERE pr.status IN ('kept','broken','partial'))::int AS settled
            FROM promises pr
            JOIN accounts a ON a.id = pr.account_id
            JOIN customers c ON c.id = a.customer_id
            JOIN products p ON p.id = a.product_id
            WHERE c.tenant_id = :tenant_id
              AND pr.created_at >= {{since}} AND pr.created_at < {{until}}
              {prom_segment}
        """
        promises_cur = _one(
            conn.execute(text(promise_sql.format(since=since_cur, until=until_cur)), params)
        ) or {}
        promises_prior = _one(
            conn.execute(
                text(promise_sql.format(since=since_prior, until=until_prior)), params
            )
        ) or {}

        # Upsell conversion — leads won over leads captured.
        lead_sql = """
            SELECT count(*)::int AS total,
                   count(*) FILTER (WHERE l.stage = 'won')::int AS won
            FROM leads l
            JOIN customers c ON c.id = l.customer_id
            WHERE c.tenant_id = :tenant_id
              AND l.created_at >= {since} AND l.created_at < {until}
        """
        leads_cur = _one(
            conn.execute(text(lead_sql.format(since=since_cur, until=until_cur)), params)
        ) or {}
        leads_prior = _one(
            conn.execute(text(lead_sql.format(since=since_prior, until=until_prior)), params)
        ) or {}

        at_risk = _rows(
            conn.execute(
                text(
                    """
                    SELECT c.id, c.name, a.id AS account, a.outstanding,
                           a.dpd AS days_past_due, c.risk, c.last_contact_at,
                           p.name AS product
                    FROM customers c
                    JOIN LATERAL (
                      SELECT *
                      FROM accounts a
                      WHERE a.customer_id = c.id
                      ORDER BY CASE WHEN a.id LIKE 'AC-%' THEN 0 ELSE 1 END, a.created_at, a.id
                      LIMIT 1
                    ) a ON true
                    JOIN products p ON p.id = a.product_id
                    WHERE c.risk IN ('critical','high','medium')
                    ORDER BY a.dpd DESC, a.outstanding DESC
                    LIMIT 6
                    """
                )
            )
        )
        # Reps ranked over the same window as everything else, with a real
        # upsell number joined from leads rather than `12 + idx * 1.3`.
        leaderboard_rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT u.id,
                           u.name,
                           COALESCE(t.name, 'Collections') AS team,
                           COUNT(i.id)::int AS calls,
                           AVG(i.duration_sec)::int AS aht,
                           AVG(i.avg_sentiment) AS csat,
                           (
                             SELECT count(*)::int FROM leads l
                             WHERE l.owner_user_id = u.id
                               AND l.created_at >= {since_cur} AND l.created_at < {until_cur}
                           ) AS leads_total,
                           (
                             SELECT count(*)::int FROM leads l
                             WHERE l.owner_user_id = u.id AND l.stage = 'won'
                               AND l.created_at >= {since_cur} AND l.created_at < {until_cur}
                           ) AS leads_won
                    FROM users u
                    LEFT JOIN teams t ON t.id = u.team_id
                    LEFT JOIN interactions i
                           ON i.handler_user_id = u.id
                          AND i.started_at >= {since_cur} AND i.started_at < {until_cur}
                    GROUP BY u.id, u.name, t.name
                    ORDER BY calls DESC, u.name
                    LIMIT 6
                    """
                ),
                params,
            )
        )

        ttft_hours = None
        ttft_n = 0
        try:
            ttft = _one(
                conn.execute(
                    text(
                        f"""
                        SELECT
                          percentile_cont(0.5) WITHIN GROUP (
                            ORDER BY EXTRACT(EPOCH FROM (pe.first_touch_at - pe.occurred_at)) / 3600.0
                          ) AS hours,
                          count(*) FILTER (WHERE pe.first_touch_at IS NOT NULL)::int AS touched
                        FROM payment_events pe
                        JOIN customers c ON c.id = pe.customer_id
                        WHERE pe.kind = 'bounce'
                          AND c.tenant_id = :tenant_id
                          AND pe.occurred_at >= {since_cur}
                          AND pe.occurred_at < {until_cur}
                          AND pe.first_touch_at IS NOT NULL
                        """
                    ),
                    params,
                )
            ) or {}
            if ttft.get("hours") is not None:
                ttft_hours = float(ttft["hours"])
            ttft_n = int(ttft.get("touched") or 0)
        except Exception:
            logger.debug("time-to-first-touch kpi skipped", exc_info=True)

    st.ttft_hours = ttft_hours
    st.ttft_n = ttft_n
    st.at_risk = at_risk
    st.leaderboard_rows = leaderboard_rows
    st.leads_cur = leads_cur
    st.leads_prior = leads_prior
    st.outstanding_row = outstanding_row
    st.prior_recovery = prior_recovery
    st.prior_summary = prior_summary
    st.promises_cur = promises_cur
    st.promises_prior = promises_prior
    st.recovery_rows = recovery_rows
    st.summary = summary
    st.volume_rows = volume_rows


def _dashboard_shape(st: DashboardBuild) -> dict[str, Any]:
    """The rates, trends and distributions, and the response the screen renders."""
    _dump = st._dump
    _duration = st._duration
    _short_product = st._short_product
    days = st.days
    ttft_hours = st.ttft_hours
    ttft_n = st.ttft_n
    at_risk = st.at_risk
    leaderboard_rows = st.leaderboard_rows
    leads_cur = st.leads_cur
    leads_prior = st.leads_prior
    outstanding_row = st.outstanding_row
    prior_recovery = st.prior_recovery
    prior_summary = st.prior_summary
    promises_cur = st.promises_cur
    promises_prior = st.promises_prior
    recovery_rows = st.recovery_rows
    summary = st.summary
    volume_rows = st.volume_rows

    interactions = summary.get("interactions") or 0
    human = summary.get("human_handled") or 0
    bot = max(interactions - human, 0)
    aht = round(summary.get("avg_duration_sec") or 0)
    mm, ss = divmod(aht, 60)
    avg_sent = float(summary.get("avg_sentiment") or 0)

    recovery_trend = [
        {"date": r["date"], "value": float(r["value"] or 0)} for r in recovery_rows
    ]
    recovered = sum(p["value"] for p in recovery_trend)
    prior_recovered = float(prior_recovery.get("value") or 0)

    # Recovery rate: collected over (collected + still owed). Stated in the KPI
    # `sub` so the definition is auditable from the screen rather than only from
    # this file — a rate whose formula nobody can see is a rate nobody trusts.
    outstanding_total = float(outstanding_row.get("total") or 0)
    denominator = recovered + outstanding_total
    recovery_rate = (recovered / denominator * 100.0) if denominator > 0 else None

    settled = promises_cur.get("settled") or 0
    ptp_rate = ((promises_cur.get("kept") or 0) / settled * 100.0) if settled else None
    prior_settled = promises_prior.get("settled") or 0
    prior_ptp_rate = (
        ((promises_prior.get("kept") or 0) / prior_settled * 100.0) if prior_settled else None
    )

    leads_total = leads_cur.get("total") or 0
    upsell_rate = ((leads_cur.get("won") or 0) / leads_total * 100.0) if leads_total else None
    prior_leads_total = leads_prior.get("total") or 0
    prior_upsell_rate = (
        ((leads_prior.get("won") or 0) / prior_leads_total * 100.0) if prior_leads_total else None
    )

    prior_interactions = prior_summary.get("interactions") or 0
    prior_human = prior_summary.get("human_handled") or 0
    prior_containment = (
        (max(prior_interactions - prior_human, 0) / prior_interactions * 100.0)
        if prior_interactions
        else None
    )
    containment = (bot / interactions * 100.0) if interactions else None

    volume_series = [
        {
            "date": r["date"],
            "voice": int(r["voice"] or 0),
            "whatsapp": int(r["whatsapp"] or 0),
            "chat": int(r["chat"] or 0),
        }
        for r in volume_rows
    ]
    daily_calls = [v["voice"] + v["whatsapp"] + v["chat"] for v in volume_series]

    # Normalised to ints summing 100, or all zeros for an empty window. The
    # denominator genuinely can be 0 now that the window is real, so this is a
    # live divide-by-zero rather than a theoretical one.
    labelled = (summary.get("pos") or 0) + (summary.get("neu") or 0) + (summary.get("neg") or 0)
    if labelled:
        pos_pct = round((summary.get("pos") or 0) / labelled * 100)
        neu_pct = round((summary.get("neu") or 0) / labelled * 100)
        sentiment_distribution = {
            "positive": pos_pct,
            "neutral": neu_pct,
            # Absorb the rounding drift here so the three always sum to 100.
            "negative": max(0, 100 - pos_pct - neu_pct),
        }
    else:
        sentiment_distribution = {"positive": 0, "neutral": 0, "negative": 0}

    def _pct(value: float | None) -> str:
        return "—" if value is None else f"{value:.1f}%"

    dashboard = {
        "heroKpis": [
            {
                "label": "Avg Handle Time (AHT)",
                "value": f"{mm}m {ss:02d}s" if aht else "—",
                "raw": aht,
                "delta": _pct_delta(aht, prior_summary.get("avg_duration_sec")),
                "deltaGood": "down",
                "sub": f"mean duration over {days}d",
                "spark": _spark_from_series(daily_calls),
            },
            {
                "label": "Upsell Conversion Rate",
                "value": _pct(upsell_rate),
                "raw": round(upsell_rate, 1) if upsell_rate is not None else 0,
                "unit": "%",
                "delta": _pct_delta(upsell_rate, prior_upsell_rate),
                "deltaGood": "up",
                "sub": f"{leads_cur.get('won') or 0} won of {leads_total} leads",
                "spark": [],
            },
        ],
        "kpis": [
            {
                "key": "recovered",
                "label": "Total Dues Recovered",
                "value": _inr_compact(recovered),
                "delta": _pct_delta(recovered, prior_recovered),
                "deltaGood": "up",
                "spark": _spark_from_series([p["value"] for p in recovery_trend]),
                "tone": "success",
            },
            {
                "key": "recoveryRate",
                "label": "Recovery Rate",
                "value": _pct(recovery_rate),
                "delta": None,
                "deltaGood": "up",
                "sub": "collected ÷ (collected + outstanding)",
                "spark": [],
            },
            {
                "key": "containment",
                "label": "Bot Containment",
                "value": _pct(containment),
                "delta": _pct_delta(containment, prior_containment),
                "deltaGood": "up",
                "spark": [],
                "tone": "brand",
            },
            {
                "key": "ptp",
                "label": "Promise-Kept Rate",
                "value": _pct(ptp_rate),
                "delta": _pct_delta(ptp_rate, prior_ptp_rate),
                "deltaGood": "up",
                "sub": f"{promises_cur.get('kept') or 0} kept of {settled} settled",
                "spark": [],
                "tone": "warning",
            },
            {
                "key": "timeToFirstTouch",
                "label": "Time to first touch",
                "value": f"{ttft_hours:.1f}h" if ttft_hours is not None else "—",
                "delta": None,
                "deltaGood": "down",
                "sub": (
                    f"median hours bounce→contact · {ttft_n} touched"
                    if ttft_n
                    else "median hours bounce→first contact"
                ),
                "spark": [],
                "tone": "brand",
            },
            {
                "key": "csat",
                "label": "Avg Sentiment / CSAT",
                "value": f"{avg_sent:.2f}" if labelled else "—",
                # No percentage delta. Sentiment is a signed score in [-1, 1],
                # so 0.02 → 0.07 is "+217%", which is arithmetically true and
                # tells a reader nothing. The prior value is shown instead.
                "delta": None,
                "deltaGood": "up",
                "sub": (
                    f"prior period {float(prior_summary['avg_sentiment']):.2f}"
                    if prior_summary.get("avg_sentiment") is not None
                    else "no prior period"
                ),
                "spark": [],
            },
            {
                "key": "calls",
                "label": "Calls Handled",
                "value": f"{interactions:,}",
                "delta": _pct_delta(interactions, prior_interactions),
                "deltaGood": "up",
                "spark": _spark_from_series([float(v) for v in daily_calls]),
            },
        ],
        "recoveryTrend": recovery_trend,
        "callVolumeStacked": volume_series,
        "sentimentDistribution": sentiment_distribution,
        "botVsHuman": [
            {"name": "Contained by bot", "value": bot, "color": "var(--background-brand-bold)"},
            {"name": "Handled by human", "value": human, "color": "var(--chart-warning-bold)"},
        ],
        "leaderboard": [
            {
                "rank": idx + 1,
                "name": r["name"],
                "team": r["team"],
                "calls": r["calls"],
                "aht": _duration(r["aht"]) if r["aht"] else "—",
                # None, not a number, when the rep captured no leads in the
                # window. The UI renders a dash — "no data" is not "12.0%".
                "upsell": (
                    round((r["leads_won"] or 0) / r["leads_total"] * 100.0, 1)
                    if r["leads_total"]
                    else None
                ),
                "csat": round(float(r["csat"]), 2) if r["csat"] is not None else None,
            }
            for idx, r in enumerate(leaderboard_rows)
        ],
        "atRiskAccounts": [
            {
                "id": r["id"],
                "name": r["name"],
                "account": r["account"],
                "outstanding": r["outstanding"],
                "daysPastDue": r["days_past_due"],
                "risk": r["risk"],
                "lastContact": r["last_contact_at"],
                "product": _short_product(r["product"]),
            }
            for r in at_risk
        ],
    }
    return _dump(DashboardResponse(**dashboard))


def get_dashboard(range: str = "30d", segment: str = "all", team: str = "all") -> dict[str, Any]:
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _rows = _mod._rows
    _tenant = _mod._tenant
    _dump = _mod._dump
    _duration = _mod._duration
    _short_product = _mod._short_product
    window = _dashboard_window(range, segment, team)
    days = window["days"]
    families = window["families"]
    handler_kind = window["handler_kind"]

    # Interactions filtered by segment reach products through their account.
    # EXISTS rather than a join so an interaction with no account_id is excluded
    # from a specific segment but still counted under "all".
    ix_segment = (
        """
        AND EXISTS (
          SELECT 1 FROM accounts a
          JOIN products p ON p.id = a.product_id
          WHERE a.id = i.account_id AND p.family = ANY(:families)
        )
        """
        if families
        else ""
    )
    ix_team = " AND i.handler_kind = :handler_kind " if handler_kind else ""
    ix_where = (
        "WHERE i.tenant_id = :tenant_id "
        "AND i.started_at >= :since AND i.started_at < :until "
        + ix_segment
        + ix_team
    )
    params: dict[str, Any] = {"tenant_id": _tenant(), "days": days}
    if families:
        params["families"] = families
    if handler_kind:
        params["handler_kind"] = handler_kind

    ttft_hours: float | None = None
    ttft_n = 0

    # Bound intervals are interpolated as literal day counts from a fixed dict,
    # never from the caller's string — _dashboard_window maps any unknown range
    # to the default rather than passing it through.
    since_cur = f"now() - CAST('{days} days' AS interval)"
    until_cur = "now()"
    since_prior = f"now() - CAST('{days * 2} days' AS interval)"
    until_prior = since_cur

    st = DashboardBuild(
        _dump=_dump,
        _duration=_duration,
        _one=_one,
        _rows=_rows,
        _short_product=_short_product,
        days=days,
        engine=engine,
        families=families,
        ix_where=ix_where,
        params=params,
        since_cur=since_cur,
        since_prior=since_prior,
        ttft_hours=ttft_hours,
        ttft_n=ttft_n,
        until_cur=until_cur,
        until_prior=until_prior,
    )
    _dashboard_reads(st)
    return _dashboard_shape(st)

