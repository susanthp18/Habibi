"""Budgets and cost statements, on the worker clock.

Before this, the Billing page's budgets were one July seed row the screen fell
back to, its rules were saved and never read, and its invoices came only from
migrations. Now, per tenant:

* **Every hour** this month's budget exists (carried over from the last one,
  with its rules), and every rule is checked against month-to-date metered
  spend. A threshold crossed for the first time this month files an alert,
  emails the rule's ``email:`` channels, and -- when the rule's action is
  "Pause outbound" -- turns the master outbound switch off.
* **On the 1st** last month's cost statement is built from the metered daily
  rollup: one line per service. A draft is rebuilt; an issued or paid one is
  never touched.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable

import money_inr

from sqlalchemy import text

logger = logging.getLogger(__name__)

ENVS = ("production", "sandbox")
PAUSE_OUTBOUND = "Pause outbound"


def _month(d: date) -> str:
    return d.strftime("%Y-%m")


def _tenants(conn: Any) -> list[str]:
    return [str(t) for t in conn.execute(text("SELECT id FROM tenants ORDER BY id")).scalars()]


def ensure_month_budgets(conn: Any, tenant: str, month: str) -> None:
    """This month's budget per env, copied (with rules) from the latest one before it."""
    for env in ENVS:
        if conn.execute(text("SELECT 1 FROM budgets WHERE tenant_id = :t AND environment = :e AND month = :m"),
                        {"t": tenant, "e": env, "m": month}).first():
            continue
        # The tenant's own last budget, else the org-wide one it has been reading.
        prev = conn.execute(text(
            "SELECT id, amount_inr FROM budgets WHERE environment = :e AND month < :m "
            "AND (tenant_id = :t OR tenant_id IS NULL) ORDER BY (tenant_id IS NULL), month DESC LIMIT 1"
        ), {"t": tenant, "e": env, "m": month}).mappings().first()
        if prev is None:
            continue
        new_id = f"budget-{tenant}-{env}-{month}"
        conn.execute(text(
            "INSERT INTO budgets (id, tenant_id, environment, month, amount_inr) VALUES (:id, :t, :e, :m, :a) "
            "ON CONFLICT DO NOTHING"
        ), {"id": new_id, "t": tenant, "e": env, "m": month, "a": prev["amount_inr"]})
        conn.execute(text(
            "INSERT INTO budget_rules (id, budget_id, threshold_pct, action_channel, severity, action, channels) "
            "SELECT 'br-' || substr(md5(random()::text), 1, 12), :new, threshold_pct, action_channel, severity, "
            "action, channels FROM budget_rules WHERE budget_id = :old"
        ), {"new": new_id, "old": prev["id"]})


def month_spend(conn: Any, tenant: str, env: str, month_start: date, as_of: date) -> Decimal:
    return Decimal(conn.execute(text(
        "SELECT coalesce(sum(cost_inr), 0) FROM billing_usage_daily WHERE tenant_id = :t "
        "AND environment = :e AND usage_date BETWEEN :s AND :u"
    ), {"t": tenant, "e": env, "s": month_start, "u": as_of}).scalar() or 0)


def evaluate(conn: Any, tenant: str, as_of: date) -> list[dict[str, Any]]:
    """Fire every rule whose threshold MTD spend has crossed, once per month."""
    month = _month(as_of)
    fired: list[dict[str, Any]] = []
    rules = conn.execute(text(
        "SELECT r.id, r.threshold_pct, r.action, r.severity, r.channels, b.amount_inr, b.environment "
        "FROM budget_rules r JOIN budgets b ON b.id = r.budget_id "
        "WHERE b.tenant_id = :t AND b.month = :m AND b.amount_inr > 0 ORDER BY r.threshold_pct"
    ), {"t": tenant, "m": month}).mappings().all()
    spend = {env: month_spend(conn, tenant, env, as_of.replace(day=1), as_of) for env in ENVS}
    for r in rules:
        pct = spend[r["environment"]] * 100 / Decimal(r["amount_inr"])
        if pct < Decimal(r["threshold_pct"]):
            continue
        message = (f"{r['environment'].title()} spend is {pct:.0f}% of this month's {money_inr.inr(float(r['amount_inr']))} "
                   f"budget (rule: {Decimal(r['threshold_pct']):.0f}%, {r['action']}).")
        inserted = conn.execute(text(
            "INSERT INTO budget_alert_events (id, budget_rule_id, spend_inr, message, budget_month) "
            "VALUES (:id, :r, :s, :msg, :m) ON CONFLICT (budget_rule_id, budget_month) "
            "WHERE budget_month IS NOT NULL DO NOTHING RETURNING id"
        ), {"id": f"bae-{uuid.uuid4().hex[:12]}", "r": r["id"], "s": spend[r["environment"]],
            "msg": message, "m": month}).scalar()
        if inserted:
            fired.append({"rule": r["id"], "env": r["environment"], "action": r["action"],
                          "channels": list(r["channels"] or []), "message": message})
    return fired


def _act(fired: dict[str, Any]) -> None:
    """Outside the evaluating transaction: email, and the outbound pause."""
    import invite_mail
    import platform_switches

    for channel in fired["channels"]:
        if str(channel).startswith("email:") and "@" in channel:
            err = invite_mail.send_budget_alert_email(to_email=channel.split(":", 1)[1], message=fired["message"])
            if err:
                logger.warning("budget alert email to %s not sent: %s", channel, err)
    if fired["action"] == PAUSE_OUTBOUND and fired["env"] == "production":
        platform_switches.flip(platform_switches.OUTBOUND_ENABLED, False,
                               note=f"Paused by budget rule: {fired['message']}"[:200])


def build_statement(conn: Any, tenant: str, month: str, env: str) -> str | None:
    """Last month's metered spend as a draft statement; returns its id (None when nothing to bill)."""
    inv_id = f"INV-{tenant}-{month}-{env}"
    status = conn.execute(text("SELECT status FROM invoices WHERE tenant_id = :t AND invoice_month = :m "
                               "AND environment = :e"), {"t": tenant, "m": month, "e": env}).scalar()
    if status in ("pending", "paid"):
        return None  # issued: its numbers are what was sent
    lines = conn.execute(text(
        "SELECT d.service_id, sum(d.units) AS units, sum(d.cost_inr) AS cost, s.unit_cost_inr "
        "FROM billing_usage_daily d JOIN billing_services s ON s.id = d.service_id "
        "WHERE d.tenant_id = :t AND d.environment = :e AND to_char(d.usage_date, 'YYYY-MM') = :m "
        "GROUP BY d.service_id, s.unit_cost_inr HAVING sum(d.cost_inr) > 0 OR sum(d.units) > 0"
    ), {"t": tenant, "e": env, "m": month}).mappings().all()
    if not lines and status is None:
        return None
    total = sum((Decimal(line["cost"]) for line in lines), Decimal(0)).quantize(Decimal("0.01"))
    existing = conn.execute(text("SELECT id FROM invoices WHERE tenant_id = :t AND invoice_month = :m "
                                 "AND environment = :e"), {"t": tenant, "m": month, "e": env}).scalar()
    inv_id = existing or inv_id
    if existing:
        conn.execute(text("UPDATE invoices SET total_inr = :tot, updated_at = now() WHERE id = :id"),
                     {"tot": total, "id": inv_id})
        conn.execute(text("DELETE FROM invoice_line_items WHERE invoice_id = :id"), {"id": inv_id})
    else:
        conn.execute(text(
            "INSERT INTO invoices (id, tenant_id, invoice_month, environment, total_inr, status) "
            "VALUES (:id, :t, :m, :e, :tot, 'draft')"
        ), {"id": inv_id, "t": tenant, "m": month, "e": env, "tot": total})
    for line in lines:
        conn.execute(text(
            "INSERT INTO invoice_line_items (id, invoice_id, service_id, units, unit_cost_inr, amount_inr) "
            "VALUES (:id, :inv, :s, :u, :uc, :amt)"
        ), {"id": f"ili-{uuid.uuid4().hex[:12]}", "inv": inv_id, "s": line["service_id"],
            "u": Decimal(line["units"]).quantize(Decimal("0.0001")), "uc": line["unit_cost_inr"],
            "amt": Decimal(line["cost"]).quantize(Decimal("0.01"))})
    return inv_id


def run_hourly(now: datetime) -> dict[str, Any]:
    import db
    import tenant_context

    with db.engine.connect() as conn:
        tenants = _tenants(conn)
    report: dict[str, Any] = {}
    for tenant in tenants:
        with tenant_context.bind(tenant):
            try:
                with db.engine.begin() as conn:
                    ensure_month_budgets(conn, tenant, _month(now.date()))
                    fired = evaluate(conn, tenant, now.date())
                for f in fired:
                    _act(f)
                report[tenant] = len(fired)
            except Exception:
                logger.exception("budget check failed for %s", tenant)
    return report


def run_statements(now: datetime, *, month: str | None = None) -> list[str]:
    """Build (or rebuild the drafts of) a month's statements; default last month."""
    import db
    import tenant_context

    month = month or _month(now.date().replace(day=1) - timedelta(days=1))
    with db.engine.connect() as conn:
        tenants = _tenants(conn)
    built: list[str] = []
    for tenant in tenants:
        with tenant_context.bind(tenant):
            for env in ENVS:
                try:
                    with db.engine.begin() as conn:
                        inv = build_statement(conn, tenant, month, env)
                    if inv:
                        built.append(inv)
                except Exception:
                    logger.exception("statement %s %s %s failed", tenant, month, env)
    return built


def tick(daily: Callable[[str, int, int], bool], now: datetime) -> None:
    """One worker tick. ``daily`` is the worker's once-a-day claim."""
    try:
        if daily(f"billing_budgets_{now.hour}", now.hour, 5):
            run_hourly(now)
        if now.day == 1 and daily("billing_statements", 1, 0):
            run_statements(now)
    except Exception:
        logger.exception("billing jobs tick failed")


if __name__ == "__main__":
    assert _month(date(2026, 9, 28)) == "2026-09"
    assert _month(date(2026, 9, 1) - timedelta(days=1)) == "2026-08"
    print("ok")
