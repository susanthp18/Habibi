"""Billing & usage analytics accessors.

Peeled from ``db.py`` (WP-036 peel 1). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from agent_core.clock import utc_now
from db_core import _one, _rows, _tenant


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


# ---------------------------------------------------------------------------
# Billing & Usage Analytics — metered Azure only (no estimate catalog lines)
# ---------------------------------------------------------------------------

_BILLING_PERIODS = {"mtd", "7d", "30d", "quarter"}
_BILLING_ENVS = {"production", "sandbox"}
_METERED_SERVICE_IDS = ("llm_chat", "llm_embed", "stt_az", "tts_az")


def _fnum(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def _billing_as_of() -> date:
    """Billing day boundary is always UTC — not the API host's local calendar."""
    return utc_now().date()


def _billing_window(period: str, as_of: date) -> tuple[date, date]:
    if period == "mtd":
        return date(as_of.year, as_of.month, 1), as_of
    if period == "7d":
        return as_of - timedelta(days=6), as_of
    if period == "30d":
        return as_of - timedelta(days=29), as_of
    if period == "quarter":
        return as_of - timedelta(days=89), as_of
    raise ValueError(f"invalid_period: {period}")


def _billing_prev_window(start: date, end: date) -> tuple[date, date]:
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=length - 1)
    return prev_start, prev_end


def _month_label(ym: str) -> str:
    try:
        y, m = ym.split("-")
        dt = date(int(y), int(m), 1)
        return dt.strftime("%b %Y")
    except Exception:
        return ym


def _parse_channels(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
        if raw.strip():
            return [raw.strip()]
    return []


def _daily_series(
    conn,
    *,
    start: date,
    end: date,
    env: str,
    tenant_id: str | None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"start": start, "end": end, "env": env}
    tenant_sql = ""
    if tenant_id and tenant_id != "all":
        tenant_sql = "AND tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    rows = _rows(
        conn.execute(
            text(
                f"""
                SELECT to_char(usage_date, 'YYYY-MM-DD') AS d,
                       service_id,
                       coalesce(sum(cost_inr), 0) AS cost
                FROM billing_usage_daily
                WHERE environment = :env
                  AND usage_date >= :start
                  AND usage_date <= :end
                  AND service_id = ANY(:services)
                  {tenant_sql}
                GROUP BY usage_date, service_id
                ORDER BY usage_date, service_id
                """
            ),
            {**params, "services": list(_METERED_SERVICE_IDS)},
        )
    )
    by_date: dict[str, dict[str, float]] = {}
    for r in rows:
        d = r["d"]
        by_date.setdefault(d, {})[r["service_id"]] = _fnum(r["cost"])

    out: list[dict[str, Any]] = []
    cur = start
    while cur <= end:
        key = cur.isoformat()
        out.append({"date": key, "values": by_date.get(key, {})})
        cur += timedelta(days=1)
    return out


def _sum_daily(daily: list[dict[str, Any]], service_id: str | None = None) -> float:
    total = 0.0
    for d in daily:
        values = d.get("values") or {}
        if service_id:
            total += _fnum(values.get(service_id, 0))
        else:
            total += sum(_fnum(v) for v in values.values())
    return total


def _forecast_eom(daily: list[dict[str, Any]], as_of: date) -> float:
    """Project month-end spend from current burn when the window is MTD-shaped."""
    if not daily:
        return 0.0
    spend = _sum_daily(daily)
    month_start = date(as_of.year, as_of.month, 1).isoformat()
    if daily[0]["date"] != month_start:
        return round(spend)
    if as_of.month == 12:
        days_in_month = 31
    else:
        days_in_month = (date(as_of.year, as_of.month + 1, 1) - timedelta(days=1)).day
    per_day = spend / max(1, as_of.day)
    return round(per_day * days_in_month)


@dataclass
class BillingBuild:
    """One billing overview: the window, the metered rows, the spend and its
    forecast, the budgets, alerts, invoices and per-tenant lines, read on one
    connection by the phases below in order. The bodies are what
    ``billing_overview`` was; ``tests/snapshots/reader_shapes.json`` pins the
    key tree.
    """

    _rows: Any
    _tenant: Any
    env: str
    period: str
    tenant_id: str
    conn: Any
    alerts: list[dict[str, Any]] = field(default_factory=list)
    as_of: date = field(init=False)  # set by _billing_window_and_usage
    attributed_calls: int = 0
    attributed_cpc: float = 0.0
    budget_cap: float = 0.0
    budget_rows: list[dict[str, Any]] = field(default_factory=list)
    budgets: list[dict[str, Any]] = field(default_factory=list)
    cost_per_call: float = 0.0
    cost_per_call_prev: float = 0.0
    daily: list[dict[str, Any]] = field(default_factory=list)
    end: date = field(init=False)  # set by _billing_window_and_usage
    forecast: Any = None
    invoices: list[dict[str, Any]] = field(default_factory=list)
    ix_cur: Any = None
    ix_prev: Any = None
    model_spend: Any = None
    month_key: str = ""
    prev_end: date = field(init=False)  # set by _billing_window_and_usage
    prev_start: date = field(init=False)  # set by _billing_window_and_usage
    previous: list[dict[str, Any]] = field(default_factory=list)
    resolved: int = 0
    service_tenant: dict[str, dict[str, float]] = field(default_factory=dict)
    services: list[dict[str, Any]] = field(default_factory=list)
    spend: float = 0.0
    spend_by_env: dict[str, float] = field(default_factory=dict)
    spend_prev: float = 0.0
    start: date = field(init=False)  # set by _billing_window_and_usage
    tenant_breakdown: list[dict[str, Any]] = field(default_factory=list)
    tenants: list[dict[str, Any]] = field(default_factory=list)


def _billing_window_and_usage(st: BillingBuild) -> None:
    """The window and its predecessor, the tenant check, the metered services, the
    resolved-interaction counts, the tenants and both daily series."""
    _rows = st._rows
    _tenant = st._tenant
    env = st.env
    period = st.period
    tenant_id = st.tenant_id
    conn = st.conn

    as_of = _billing_as_of()
    start, end = _billing_window(period, as_of)
    prev_start, prev_end = _billing_prev_window(start, end)
    month_key = as_of.strftime("%Y-%m")

    if tenant_id != "all":
        exists = conn.execute(
            text("SELECT 1 FROM tenants WHERE id = :id"),
            {"id": tenant_id},
        ).scalar()
        if not exists:
            raise ValueError(f"unknown_tenant: {tenant_id}")

    services = [
        {
            "id": r["id"],
            "name": r["name"],
            "provider": r.get("provider") or "Unknown",
            "category": r.get("category") or "Infra",
            "unit": r["unit"],
            "unitCostInr": _fnum(r["unit_cost_inr"]),
            "color": r.get("color") or "#64748b",
        }
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, name, provider, category, unit, unit_cost_inr, color
                    FROM billing_services
                    WHERE id IN ('llm_chat', 'llm_embed', 'stt_az', 'tts_az')
                    ORDER BY
                      CASE id
                        WHEN 'llm_chat' THEN 1
                        WHEN 'llm_embed' THEN 2
                        WHEN 'stt_az' THEN 3
                        WHEN 'tts_az' THEN 4
                        ELSE 5
                      END
                    """
                )
            )
        )
    ]

    # Live interaction metrics (not seed billing_resolved_calls)
    ix_params: dict[str, Any] = {"start": start, "end": end}
    ix_tenant_sql = ""
    if tenant_id != "all":
        ix_tenant_sql = "AND tenant_id = :tenant_id"
        ix_params["tenant_id"] = tenant_id
    ix_cur = conn.execute(
        text(
            f"""
            SELECT
              count(*)::int AS calls,
              count(*) FILTER (WHERE coalesce(query_resolved, false))::int AS resolved,
              coalesce(
                avg(duration_sec) FILTER (WHERE duration_sec IS NOT NULL AND duration_sec > 0),
                0
              )::float AS aht
            FROM interactions
            WHERE started_at >= CAST(:start AS date)::timestamp AT TIME ZONE 'UTC'
              AND started_at < (CAST(:end AS date) + 1)::timestamp AT TIME ZONE 'UTC'
              {ix_tenant_sql}
            """
        ),
        ix_params,
    ).mappings().first()
    ix_prev_params: dict[str, Any] = {"start": prev_start, "end": prev_end}
    if tenant_id != "all":
        ix_prev_params["tenant_id"] = tenant_id
    ix_prev = conn.execute(
        text(
            f"""
            SELECT
              count(*) FILTER (WHERE coalesce(query_resolved, false))::int AS resolved
            FROM interactions
            WHERE started_at >= CAST(:start AS date)::timestamp AT TIME ZONE 'UTC'
              AND started_at < (CAST(:end AS date) + 1)::timestamp AT TIME ZONE 'UTC'
              {ix_tenant_sql}
            """
        ),
        ix_prev_params,
    ).mappings().first()

    tenant_ix = {
        r["tenant_id"]: r
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT tenant_id,
                           count(*)::int AS calls,
                           count(*) FILTER (
                             WHERE coalesce(query_resolved, false)
                           )::int AS resolved,
                           coalesce(
                             avg(duration_sec) FILTER (
                               WHERE duration_sec IS NOT NULL AND duration_sec > 0
                             ),
                             0
                           )::float AS aht
                    FROM interactions
                    WHERE started_at >= CAST(:start AS date)::timestamp AT TIME ZONE 'UTC'
                      AND started_at < (CAST(:end AS date) + 1)::timestamp AT TIME ZONE 'UTC'
                      AND (:tenant_id = 'all' OR tenant_id = :tenant_id)
                    GROUP BY tenant_id
                    """
                ),
                {"start": start, "end": end, "tenant_id": tenant_id},
            )
        )
    }

    # Tenants that have metered spend or live interactions in-window
    tenant_rows = _rows(
        conn.execute(
            text(
                """
                SELECT t.id, t.name,
                       coalesce(t.budget_inr, 0) AS budget
                FROM tenants t
                WHERE (
                  t.id IN (
                    SELECT DISTINCT tenant_id FROM billing_usage_daily
                    WHERE service_id = ANY(:services)
                    UNION
                    SELECT DISTINCT tenant_id FROM interactions
                    WHERE started_at >= CAST(:start AS date)::timestamp AT TIME ZONE 'UTC'
                      AND started_at < (CAST(:end AS date) + 1)::timestamp AT TIME ZONE 'UTC'
                  )
                  OR t.id = :primary
                )
                AND (:tenant_id = 'all' OR t.id = :tenant_id)
                ORDER BY t.name
                """
            ),
            {
                "start": start,
                "end": end,
                "primary": _tenant(),
                "tenant_id": tenant_id,
                "services": list(_METERED_SERVICE_IDS),
            },
        )
    )
    tenants = []
    for r in tenant_rows:
        ix = tenant_ix.get(r["id"], {})
        resolved_n = int(ix.get("resolved") or 0)
        aht = int(round(_fnum(ix.get("aht") or 0)))
        tenants.append(
            {
                "id": r["id"],
                "name": r["name"],
                "resolvedCalls": resolved_n,
                "ahtSec": aht,
                "budgetInr": _fnum(r["budget"]),
                "spendShare": 0.0,
            }
        )

    daily = _daily_series(conn, start=start, end=end, env=env, tenant_id=tenant_id)
    previous = _daily_series(
        conn, start=prev_start, end=prev_end, env=env, tenant_id=tenant_id
    )
    spend = _sum_daily(daily)
    spend_prev = _sum_daily(previous)

    st.as_of = as_of
    st.daily = daily
    st.end = end
    st.ix_cur = ix_cur
    st.ix_prev = ix_prev
    st.month_key = month_key
    st.prev_end = prev_end
    st.prev_start = prev_start
    st.previous = previous
    st.services = services
    st.spend = spend
    st.spend_prev = spend_prev
    st.start = start
    st.tenants = tenants


def _billing_spend(st: BillingBuild) -> None:
    """Cost per resolved call (raw and attributed), model spend, the end-of-month
    forecast, spend by environment, and the budget rows."""
    _rows = st._rows
    env = st.env
    tenant_id = st.tenant_id
    conn = st.conn
    as_of = st.as_of
    daily = st.daily
    end = st.end
    ix_cur = st.ix_cur
    ix_prev = st.ix_prev
    month_key = st.month_key
    spend = st.spend
    spend_prev = st.spend_prev
    start = st.start

    resolved = int((ix_cur or {}).get("resolved") or 0)
    resolved_prev = int((ix_prev or {}).get("resolved") or 0)
    cost_per_call = (spend / resolved) if resolved > 0 else 0.0
    cost_per_call_prev = (spend_prev / resolved_prev) if resolved_prev > 0 else 0.0

    # The measured counterpart to cost_per_call above. Kept alongside rather
    # than replacing it: calls that predate metering have no events, so this
    # is 0 for historical windows and the allocated figure is still the only
    # number available there.
    attributed_cpc, attributed_calls = _attributed_cost_per_call(
        conn, start=start, end=end, env=env, tenant_id=tenant_id
    )
    model_spend = _model_spend(
        conn, start=start, end=end, env=env, tenant_id=tenant_id
    )
    forecast = _forecast_eom(daily, as_of)

    mtd_start = date(as_of.year, as_of.month, 1)

    # MTD spend by env (metered only)
    spend_by_env: dict[str, float] = {}
    for e in ("production", "sandbox"):
        params: dict[str, Any] = {
            "env": e,
            "start": mtd_start,
            "end": as_of,
        }
        tenant_sql = ""
        if tenant_id != "all":
            tenant_sql = "AND tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        spend_by_env[e] = _fnum(
            conn.execute(
                text(
                    f"""
                    SELECT coalesce(sum(cost_inr), 0)
                    FROM billing_usage_daily
                    WHERE environment = :env
                      AND usage_date >= :start
                      AND usage_date <= :end
                      AND service_id = ANY(:services)
                      {tenant_sql}
                    """
                ),
                {**params, "services": list(_METERED_SERVICE_IDS)},
            ).scalar()
        )

    budget_rows = _rows(
        conn.execute(
            text(
                """
                SELECT id, environment, month, amount_inr
                FROM budgets
                WHERE tenant_id IS NULL
                  AND month = :month
                ORDER BY environment
                """
            ),
            {"month": month_key},
        )
    )
    # Fallback: latest month if current month missing
    if not budget_rows:
        budget_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT id, environment, month, amount_inr
                    FROM budgets
                    WHERE tenant_id IS NULL
                    ORDER BY month DESC, environment
                    LIMIT 2
                    """
                )
            )
        )

    st.attributed_calls = attributed_calls
    st.attributed_cpc = attributed_cpc
    st.budget_rows = budget_rows
    st.cost_per_call = cost_per_call
    st.cost_per_call_prev = cost_per_call_prev
    st.forecast = forecast
    st.model_spend = model_spend
    st.resolved = resolved
    st.spend_by_env = spend_by_env


def _billing_lines(st: BillingBuild) -> None:
    """Budgets, alerts, invoices, and the per-tenant and per-service breakdowns."""
    _rows = st._rows
    env = st.env
    conn = st.conn
    budget_rows = st.budget_rows
    end = st.end
    prev_end = st.prev_end
    prev_start = st.prev_start
    start = st.start
    tenants = st.tenants

    budgets: list[dict[str, Any]] = []
    budget_cap = 0.0
    for b in budget_rows:
        rules = [
            {
                "id": rr["id"],
                "threshold": _fnum(rr["threshold_pct"]),
                "channels": _parse_channels(rr.get("channels"))
                or ([rr["action_channel"]] if rr.get("action_channel") else []),
                "action": rr.get("action") or "Notify",
                "severity": rr.get("severity") or "warn",
            }
            for rr in _rows(
                conn.execute(
                    text(
                        """
                        SELECT id, threshold_pct, action_channel, severity, action, channels
                        FROM budget_rules
                        WHERE budget_id = :bid
                        ORDER BY threshold_pct
                        """
                    ),
                    {"bid": b["id"]},
                )
            )
        ]
        cap = _fnum(b["amount_inr"])
        env_key = b["environment"]
        if env_key == env:
            budget_cap = cap
        budgets.append(
            {
                "id": b["id"],
                "env": env_key,
                "month": b["month"],
                "monthlyCapInr": cap,
                "rules": rules,
            }
        )

    alerts = []
    for a in _rows(
        conn.execute(
            text(
                """
                SELECT e.id, e.triggered_at, e.message, e.budget_rule_id,
                       b.environment
                FROM budget_alert_events e
                JOIN budget_rules r ON r.id = e.budget_rule_id
                JOIN budgets b ON b.id = r.budget_id
                ORDER BY e.triggered_at DESC
                LIMIT 10
                """
            )
        )
    ):
        when = a["triggered_at"]
        if isinstance(when, datetime):
            when_s = when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")
        else:
            when_s = str(when)
        alerts.append(
            {
                "id": a["id"],
                "when": when_s,
                "ruleId": a["budget_rule_id"],
                "env": a["environment"],
                "message": a.get("message") or "",
            }
        )

    invoices = []
    for inv in _rows(
        conn.execute(
            text(
                """
                SELECT id, invoice_month, status, total_inr, issued_at
                FROM invoices
                WHERE environment = 'production'
                ORDER BY invoice_month DESC
                LIMIT 8
                """
            )
        )
    ):
        issued = inv.get("issued_at")
        invoices.append(
            {
                "id": inv["id"],
                "month": _month_label(inv["invoice_month"])
                + (" (in progress)" if inv["status"] == "draft" else ""),
                "status": inv["status"],
                "amountInr": _fnum(inv["total_inr"]),
                "issuedAt": issued.isoformat() if isinstance(issued, date) else str(issued or ""),
            }
        )

    # Per-tenant breakdown for selected env + period (ignore tenant filter)
    tenant_spend_cur = {
        r["tenant_id"]: _fnum(r["cost"])
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT tenant_id, coalesce(sum(cost_inr), 0) AS cost
                    FROM billing_usage_daily
                    WHERE environment = :env
                      AND usage_date >= :start
                      AND usage_date <= :end
                      AND service_id = ANY(:services)
                    GROUP BY tenant_id
                    """
                ),
                {
                    "env": env,
                    "start": start,
                    "end": end,
                    "services": list(_METERED_SERVICE_IDS),
                },
            )
        )
    }
    tenant_spend_prev = {
        r["tenant_id"]: _fnum(r["cost"])
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT tenant_id, coalesce(sum(cost_inr), 0) AS cost
                    FROM billing_usage_daily
                    WHERE environment = :env
                      AND usage_date >= :start
                      AND usage_date <= :end
                      AND service_id = ANY(:services)
                    GROUP BY tenant_id
                    """
                ),
                {
                    "env": env,
                    "start": prev_start,
                    "end": prev_end,
                    "services": list(_METERED_SERVICE_IDS),
                },
            )
        )
    }
    tenant_breakdown = []
    for t in tenants:
        sp = tenant_spend_cur.get(t["id"], 0.0)
        sp_prev = tenant_spend_prev.get(t["id"], 0.0)
        calls = max(0, int(t["resolvedCalls"]))
        budget = t["budgetInr"]
        tenant_breakdown.append(
            {
                "id": t["id"],
                "name": t["name"],
                "resolvedCalls": calls,
                "ahtSec": t["ahtSec"],
                "budgetInr": budget,
                "spend": sp,
                "spendPrev": sp_prev,
                "costPerCall": (sp / calls) if calls > 0 else 0.0,
                "budgetPct": round((sp / budget) * 100, 1) if budget > 0 else 0.0,
            }
        )

    # service → tenant spend for drawer (current period + env)
    service_tenant: dict[str, dict[str, float]] = {}
    for r in _rows(
        conn.execute(
            text(
                """
                SELECT service_id, tenant_id, coalesce(sum(cost_inr), 0) AS cost
                FROM billing_usage_daily
                WHERE environment = :env
                  AND usage_date >= :start
                  AND usage_date <= :end
                  AND service_id = ANY(:services)
                GROUP BY service_id, tenant_id
                """
            ),
            {
                "env": env,
                "start": start,
                "end": end,
                "services": list(_METERED_SERVICE_IDS),
            },
        )
    ):
        service_tenant.setdefault(r["service_id"], {})[r["tenant_id"]] = _fnum(r["cost"])

    st.alerts = alerts
    st.budget_cap = budget_cap
    st.budgets = budgets
    st.invoices = invoices
    st.service_tenant = service_tenant
    st.tenant_breakdown = tenant_breakdown


def _billing_response(st: BillingBuild) -> dict[str, Any]:
    """The response the billing screen renders."""
    env = st.env
    period = st.period
    tenant_id = st.tenant_id
    alerts = st.alerts
    as_of = st.as_of
    attributed_calls = st.attributed_calls
    attributed_cpc = st.attributed_cpc
    budget_cap = st.budget_cap
    budgets = st.budgets
    cost_per_call = st.cost_per_call
    cost_per_call_prev = st.cost_per_call_prev
    daily = st.daily
    forecast = st.forecast
    invoices = st.invoices
    model_spend = st.model_spend
    previous = st.previous
    resolved = st.resolved
    service_tenant = st.service_tenant
    services = st.services
    spend = st.spend
    spend_by_env = st.spend_by_env
    spend_prev = st.spend_prev
    tenant_breakdown = st.tenant_breakdown
    tenants = st.tenants

    return {
        "asOf": as_of.isoformat(),
        "period": period,
        "env": env,
        "tenantId": tenant_id,
        "services": services,
        "tenants": tenants,
        "daily": daily,
        "previousDaily": previous,
        "spend": spend,
        "spendPrev": spend_prev,
        "forecast": forecast,
        "costPerCall": cost_per_call,
        "costPerCallPrev": cost_per_call_prev,
        "resolvedCalls": resolved,
        "budgetCap": budget_cap,
        "spendByEnv": spend_by_env,
        "budgets": budgets,
        "alerts": alerts,
        "invoices": invoices,
        "tenantBreakdown": tenant_breakdown,
        "serviceTenantSpend": service_tenant,
        "attributedCostPerCall": attributed_cpc,
        "attributedCalls": attributed_calls,
        "modelSpend": model_spend,
    }


def billing_overview(
    period: str = "mtd",
    tenant_id: str = "all",
    env: str = "production",
) -> dict[str, Any]:
    engine = _db().engine
    if period not in _BILLING_PERIODS:
        raise ValueError(f"invalid_period: {period}")
    if env not in _BILLING_ENVS:
        raise ValueError(f"invalid_env: {env}")

    with engine.connect() as conn:
        st = BillingBuild(
            _rows=_rows,
            _tenant=_tenant,
            env=env,
            period=period,
            tenant_id=tenant_id,
            conn=conn,
        )
        _billing_window_and_usage(st)
        _billing_spend(st)
        _billing_lines(st)
        return _billing_response(st)


def interaction_cost(interaction_id: str) -> dict[str, Any]:
    """What one call actually cost, broken down by service and model.

    Reads ``usage_events`` rather than the daily rollup: the rollup is keyed by
    (service, tenant, env, day) and deliberately carries neither dimension.

    ``attributed`` distinguishes "this call cost nothing" from "this call
    predates metering" — every voice call before the pipeline was instrumented
    has no events at all, and showing those as ₹0.00 would be a lie.
    """
    engine = _db().engine
    with engine.begin() as conn:
        rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT ue.service_id,
                           bs.name  AS service_name,
                           bs.unit  AS unit,
                           bs.category,
                           bs.color,
                           ue.model,
                           SUM(ue.units)    AS units,
                           SUM(ue.cost_inr) AS cost,
                           COUNT(*)         AS events
                      FROM usage_events ue
                      JOIN billing_services bs ON bs.id = ue.service_id
                     WHERE ue.interaction_id = :ix
                     GROUP BY ue.service_id, bs.name, bs.unit, bs.category,
                              bs.color, ue.model
                     ORDER BY SUM(ue.cost_inr) DESC
                    """
                ),
                {"ix": interaction_id},
            )
        )

        meta = _one(
            conn.execute(
                text(
                    """
                    SELECT duration_sec, started_at, channel, status
                      FROM interactions WHERE id = :ix
                    """
                ),
                {"ix": interaction_id},
            )
        )

        tokens = _one(
            conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(tokens), 0) AS tokens
                      FROM interaction_transcript
                     WHERE interaction_id = :ix AND tokens IS NOT NULL
                    """
                ),
                {"ix": interaction_id},
            )
        )

    lines = [
        {
            "serviceId": r["service_id"],
            "serviceName": r["service_name"],
            "unit": r["unit"],
            "category": r["category"],
            "color": r["color"],
            "model": r["model"],
            "units": _fnum(r["units"]),
            "costInr": _fnum(r["cost"]),
            "events": int(r["events"] or 0),
        }
        for r in rows
    ]
    total = sum(line["costInr"] for line in lines)
    return {
        "interactionId": interaction_id,
        "attributed": bool(lines),
        "totalInr": total,
        "lines": lines,
        "durationSec": int((meta or {}).get("duration_sec") or 0),
        "channel": (meta or {}).get("channel"),
        "status": (meta or {}).get("status"),
        "totalTokens": int((tokens or {}).get("tokens") or 0),
    }


def _model_spend(
    conn: Any, *, start: date, end: date, env: str, tenant_id: str
) -> list[dict[str, Any]]:
    """Spend grouped by model.

    The per-model dimension only exists on ``usage_events`` — ``billing_services``
    has a single blended ``llm_chat`` row, so a gpt-5 turn and a gpt-4o-mini turn
    are indistinguishable in the rollup even though they price ~8x apart.
    """
    params: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "env": env,
        "services": list(_METERED_SERVICE_IDS),
    }
    tenant_sql = ""
    if tenant_id and tenant_id != "all":
        tenant_sql = "AND ue.tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    rows = _rows(
        conn.execute(
            text(
                f"""
                SELECT ue.service_id,
                       bs.name AS service_name,
                       bs.unit AS unit,
                       bs.color,
                       COALESCE(ue.model, '(unspecified)') AS model,
                       COALESCE(ue.source_ref, '(unspecified)') AS source_ref,
                       SUM(ue.units)    AS units,
                       SUM(ue.cost_inr) AS cost,
                       COUNT(DISTINCT ue.interaction_id) AS calls
                  FROM usage_events ue
                  JOIN billing_services bs ON bs.id = ue.service_id
                 WHERE ue.occurred_at >= CAST(:start AS date)
                   AND ue.occurred_at < CAST(:end AS date) + INTERVAL '1 day'
                   AND ue.environment = :env
                   AND ue.service_id = ANY(:services)
                   {tenant_sql}
                 GROUP BY ue.service_id, bs.name, bs.unit, bs.color, ue.model, ue.source_ref
                 ORDER BY SUM(ue.cost_inr) DESC
                """
            ),
            params,
        )
    )
    return [
        {
            "serviceId": r["service_id"],
            "serviceName": r["service_name"],
            "unit": r["unit"],
            "color": r["color"],
            "model": r["model"],
            "sourceRef": r.get("source_ref"),
            "units": _fnum(r["units"]),
            "costInr": _fnum(r["cost"]),
            "calls": int(r["calls"] or 0),
        }
        for r in rows
    ]


def _attributed_cost_per_call(
    conn: Any, *, start: date, end: date, env: str, tenant_id: str
) -> tuple[float, int]:
    """Mean cost over calls that actually carry metered usage.

    Distinct from the ``costPerCall`` KPI beside it, which is total spend over
    resolved calls — that one divides *all* spend (including embeddings and
    batch work no call incurred) by a call count, so it is an allocation, not a
    measurement. This one only counts calls with attributed events.
    """
    params: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "env": env,
        "services": list(_METERED_SERVICE_IDS),
    }
    tenant_sql = ""
    if tenant_id and tenant_id != "all":
        tenant_sql = "AND ue.tenant_id = :tenant_id"
        params["tenant_id"] = tenant_id

    row = _one(
        conn.execute(
            text(
                f"""
                SELECT COALESCE(AVG(call_cost), 0) AS avg_cost,
                       COUNT(*)                    AS calls
                  FROM (
                        SELECT ue.interaction_id, SUM(ue.cost_inr) AS call_cost
                          FROM usage_events ue
                         WHERE ue.interaction_id IS NOT NULL
                           AND ue.occurred_at >= CAST(:start AS date)
                           AND ue.occurred_at < CAST(:end AS date) + INTERVAL '1 day'
                           AND ue.environment = :env
                           AND ue.service_id = ANY(:services)
                           {tenant_sql}
                         GROUP BY ue.interaction_id
                       ) per_call
                """
            ),
            params,
        )
    )
    return _fnum((row or {}).get("avg_cost")), int((row or {}).get("calls") or 0)


def upsert_budget_rule(budget_id: str, payload: dict[str, Any], rule_id: str | None = None) -> dict[str, Any]:
    engine = _db().engine
    channels = [str(c).strip() for c in (payload.get("channels") or []) if str(c).strip()]
    if not channels:
        raise ValueError("channels_required")
    threshold = float(payload["threshold"])
    severity = payload.get("severity") or "warn"
    action = (payload.get("action") or "Notify").strip()
    if severity not in {"info", "warn", "critical"}:
        raise ValueError("invalid_severity")

    with engine.begin() as conn:
        budget = conn.execute(
            text("SELECT id FROM budgets WHERE id = :id"),
            {"id": budget_id},
        ).first()
        if not budget:
            raise LookupError("budget_not_found")

        rid = rule_id or f"r_{uuid.uuid4().hex[:10]}"
        if rule_id:
            exists = conn.execute(
                text("SELECT 1 FROM budget_rules WHERE id = :id AND budget_id = :bid"),
                {"id": rule_id, "bid": budget_id},
            ).scalar()
            if not exists:
                raise LookupError("rule_not_found")

        conn.execute(
            text(
                """
                INSERT INTO budget_rules (
                  id, budget_id, threshold_pct, action_channel, severity, action, channels
                ) VALUES (
                  :id, :bid, :thr, :channel, :severity, :action, CAST(:channels AS jsonb)
                )
                ON CONFLICT (id) DO UPDATE SET
                  threshold_pct = EXCLUDED.threshold_pct,
                  action_channel = EXCLUDED.action_channel,
                  severity = EXCLUDED.severity,
                  action = EXCLUDED.action,
                  channels = EXCLUDED.channels,
                  updated_at = now()
                """
            ),
            {
                "id": rid,
                "bid": budget_id,
                "thr": threshold,
                "channel": channels[0],
                "severity": severity,
                "action": action,
                "channels": json.dumps(channels),
            },
        )
        return {
            "id": rid,
            "threshold": threshold,
            "channels": channels,
            "action": action,
            "severity": severity,
        }


def delete_budget_rule(budget_id: str, rule_id: str) -> None:
    engine = _db().engine
    with engine.begin() as conn:
        # Drop alert history first (FK)
        conn.execute(
            text("DELETE FROM budget_alert_events WHERE budget_rule_id = :id"),
            {"id": rule_id},
        )
        result = conn.execute(
            text(
                """
                DELETE FROM budget_rules
                WHERE id = :id AND budget_id = :bid
                """
            ),
            {"id": rule_id, "bid": budget_id},
        )
        if result.rowcount == 0:
            raise LookupError("rule_not_found")


def billing_export_csv(
    period: str = "mtd",
    tenant_id: str = "all",
    env: str = "production",
) -> str:
    data = billing_overview(period, tenant_id, env)
    lines = ["date,service_id,service_name,cost_inr"]
    name_by_id = {s["id"]: s["name"] for s in data["services"]}
    for d in data["daily"]:
        for sid, cost in (d.get("values") or {}).items():
            lines.append(
                f"{d['date']},{sid},{name_by_id.get(sid, sid)},{round(_fnum(cost), 2)}"
            )
    return "\n".join(lines) + "\n"

