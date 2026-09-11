"""Persistence for the outbound router (campaigns, cadence, dial log, demo dial).

Peeled from ``routers/outbound.py``: a router validates and returns; it does
not own a transaction or author SQL. Each function here is one route's
transaction and returns exactly the shape the handler used to. Reach the
engine through :func:`_db`, never ``from db_core import engine``: the
``db_tx`` fixture wraps ``db.engine``, and a name bound from ``db_core``
bypasses that proxy.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from typing import Any

logger = logging.getLogger(__name__)


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


_DEMO_CUSTOMER_SQL = """
    SELECT id, name, phone_primary, dnd
    FROM customers
    WHERE tenant_id = :t
      AND regexp_replace(COALESCE(phone_primary, ''), '\\D', '', 'g') = :d
    LIMIT 1
"""


def demo_customer(digits: str, *, tenant_id: str) -> dict[str, Any] | None:
    """The borrower behind the demo number, as the target screen shows them."""
    with _db().engine.connect() as conn:
        row = conn.execute(text(_DEMO_CUSTOMER_SQL), {"t": tenant_id, "d": digits}).mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "phone": row["phone_primary"],
        "dnd": bool(row["dnd"]),
    }


def demo_policy_verdict(customer_id: str):
    """Dry-run the contact policy (``evaluate``, never ``admit``) for the demo target."""
    import contact_policy

    with _db().engine.connect() as conn:
        return contact_policy.evaluate(
            conn, customer_id=customer_id, channel="voice", purpose="outreach"
        )


def reserve_demo_attempt(
    *,
    digits: str,
    phone: str,
    tenant_id: str,
    bot_id: str,
    card: Any,
    objective: str,
    waivable: frozenset[str],
) -> tuple[Any, str, str | None, str]:
    """Build the mission and run the gate for the demo dial, in one transaction.

    Raises ``KeyError("demo_customer_not_found")`` when the number names nobody.
    Returns ``(gated, customer_id, account_id, reason)``.
    """
    import mission as mission_mod
    import outbound

    d = _db()
    with d.engine.begin() as conn:
        row = conn.execute(text(_DEMO_CUSTOMER_SQL), {"t": tenant_id, "d": digits}).mappings().first()
        if row is None:
            raise KeyError("demo_customer_not_found")
        customer_id = str(row["id"])
        account_id = conn.execute(
            text(
                "SELECT id FROM accounts WHERE customer_id = :c"
                " ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id LIMIT 1"
            ),
            {"c": customer_id},
        ).scalar()
        built = mission_mod.build(
            conn,
            customer_id=customer_id,
            objective=objective,
            account_id=account_id,
            card=card,
            bot_id=bot_id,
        )
        # Waivable: *when* and *how often* (hours, window, cooling-off, caps).
        # Not waivable at any switch setting: consent, opt-out, DND, registry,
        # DPDP basis. The router decides the set; the gate enforces it.
        gated = outbound.gate(
            conn,
            admit={"source": "voice_outbound", "actor_kind": "human"},
            waivable=waivable,
            customer_id=customer_id,
            to_phone=phone,
            objective=objective,
            account_id=account_id,
            bot_id=bot_id,
            context={"source": "demo_button", "mission": built},
        )
        reason = gated.reason or "contact_policy"
        if gated.waived:
            logger.warning(
                "demo call: waiving %s for the demo number by operator switch", reason
            )
            d.record_activity(
                conn,
                "customer",
                customer_id,
                "demo_window_waived",
                f"Demo call placed despite {reason}",
                f"waived:{reason}",
                customer_id,
            )
    return gated, customer_id, account_id, reason


def hourly_reach(customer_id: str, *, days: int) -> list[dict[str, Any]]:
    """Per-hour answer rate for one borrower (``outbound.hourly_reach``)."""
    import outbound

    with _db().engine.connect() as conn:
        return outbound.hourly_reach(conn, customer_id=customer_id, days=days)


def record_decision_feedback(
    decision_id: str, body: Any, *, tenant_id: str, actor_user_id: str
) -> dict[str, Any]:
    import decision_feedback

    with _db().engine.begin() as conn:
        return decision_feedback.record_feedback(
            conn,
            tenant_id=tenant_id,
            decision_id=decision_id,
            verdict=body.verdict,
            actor_user_id=actor_user_id,
            reason_code=body.reasonCode,
            note_redacted=body.noteRedacted,
            endpoint=body.endpoint,
            channel=body.channel or "voice",
        )


def reach_stats(days: int, *, tenant_id: str) -> dict[str, Any]:
    import outbound

    with _db().engine.connect() as conn:
        return outbound.reach_stats(conn, tenant_id=tenant_id, days=days)


def list_call_attempts(
    *,
    customer_id: str | None,
    state: str | None,
    limit: int,
    offset: int,
    tenant_id: str,
) -> list[dict[str, Any]]:
    clauses = ["a.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": tenant_id, "limit": limit, "offset": offset}
    if customer_id:
        clauses.append("a.customer_id = :cid")
        params["cid"] = customer_id
    if state:
        clauses.append("a.state = :state")
        params["state"] = state
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT a.id, a.customer_id, c.name AS customer_name, a.objective,
                       a.attempt_no, a.state, a.suppressed_reason, a.to_phone_last4,
                       a.answered_by, a.right_party, a.ring_sec, a.talk_sec,
                       a.provider_call_id, a.provider_status, a.provider_error,
                       a.interaction_id, a.decision_id, a.reserved_at, a.placed_at,
                       a.answered_at, a.ended_at,
                       o.connection, o.business, o.objective_met, o.nonpayment_reason,
                       o.summary, o.summary_source
                FROM call_attempts a
                JOIN customers c ON c.id = a.customer_id
                LEFT JOIN call_outcomes o ON o.attempt_id = a.id
                WHERE {' AND '.join(clauses)}
                ORDER BY a.reserved_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]


def nonpayment_reasons(days: int, *, tenant_id: str) -> list[dict[str, Any]]:
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT nonpayment_reason AS reason, count(*) AS calls,
                       count(*) FILTER (WHERE objective_met) AS resolved
                FROM call_outcomes
                WHERE tenant_id = :tenant
                  AND nonpayment_reason IS NOT NULL
                  AND created_at >= now() - make_interval(days => :days)
                GROUP BY 1 ORDER BY 2 DESC
                """
            ),
            {"tenant": tenant_id, "days": days},
        ).mappings().all()
    return [dict(r) for r in rows]


def list_campaign_runs(
    *, status: str | None, limit: int, tenant_id: str
) -> list[dict[str, Any]]:
    clauses = ["r.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": tenant_id, "limit": limit}
    if status:
        clauses.append("r.status = :status")
        params["status"] = status
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT r.*,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'pending')  AS pending,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'done')     AS done,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'skipped')  AS skipped
                FROM campaign_runs r
                WHERE {' AND '.join(clauses)}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]


def create_campaign_run(
    payload: dict[str, Any],
    *,
    name: str,
    objective: str,
    tenant_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    """Create the draft run and freeze its targets. ``campaigns.SelectorError`` propagates."""
    import campaigns

    with _db().engine.begin() as conn:
        run = campaigns.create(
            conn,
            tenant_id=tenant_id,
            name=name,
            objective=objective,
            bot_id=payload.get("botId"),
            cadence=str(payload.get("cadence") or "default"),
            source=str(payload.get("source") or "list"),
            selector=payload.get("selector") or {},
            window_start_hour=int(payload.get("windowStartHour") or 10),
            window_end_hour=int(payload.get("windowEndHour") or 18),
            max_concurrent=int(payload.get("maxConcurrent") or 5),
            created_by_user_id=actor_user_id,
        )
        ids = [str(c) for c in (payload.get("customerIds") or []) if str(c).strip()]
        if ids:
            campaigns.add_targets(conn, run["id"], ids, tenant_id=tenant_id)
        # A selector is resolved now, against the book as it stands, and the
        # targets are frozen onto the run: the cohort an operator reviewed and
        # the cohort that gets called must be the same population.
        selector = payload.get("selector") or {}
        if selector:
            campaigns.add_targets_from_selector(
                conn, run["id"], tenant_id=tenant_id, selector=selector
            )
    return dict(run)


def preview_campaign_cohort(
    *, selector: dict[str, Any], sample: int, tenant_id: str
) -> dict[str, Any]:
    import campaigns

    with _db().engine.connect() as conn:
        return campaigns.preview_selector(
            conn, tenant_id=tenant_id, selector=selector, sample=sample
        )


def add_campaign_targets(
    run_id: str, *, ids: list[str], selector: dict[str, Any], tenant_id: str
) -> int:
    """Rows added. ``KeyError`` (unknown run) and ``SelectorError`` propagate."""
    import campaigns

    with _db().engine.begin() as conn:
        added = campaigns.add_targets(conn, run_id, ids, tenant_id=tenant_id) if ids else 0
        if selector:
            added += campaigns.add_targets_from_selector(
                conn, run_id, tenant_id=tenant_id, selector=selector
            )
    return added


def set_campaign_status(run_id: str, status: str, *, tenant_id: str) -> dict[str, Any] | None:
    """The updated run, or ``None`` when it does not exist. ``ValueError`` propagates."""
    import campaigns

    with _db().engine.begin() as conn:
        run = campaigns.set_status(conn, run_id, status, tenant_id=tenant_id)
    return dict(run) if run is not None else None


def get_campaign_run(run_id: str, *, tenant_id: str) -> dict[str, Any] | None:
    import campaigns

    with _db().engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM campaign_runs WHERE id = :id AND tenant_id = :t"),
            {"id": run_id, "t": tenant_id},
        ).mappings().first()
        if row is None:
            return None
        return {**dict(row), "progress": campaigns.progress(conn, run_id)}


def list_cadence_cases(
    *, customer_id: str | None, state: str | None, limit: int, tenant_id: str
) -> list[dict[str, Any]]:
    clauses = ["s.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": tenant_id, "limit": limit}
    if customer_id:
        clauses.append("s.customer_id = :cid")
        params["cid"] = customer_id
    if state:
        clauses.append("s.state = :state")
        params["state"] = state
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT s.*, c.name AS customer_name
                FROM call_cadence_state s
                JOIN customers c ON c.id = s.customer_id
                WHERE {' AND '.join(clauses)}
                ORDER BY s.next_attempt_at ASC NULLS LAST, s.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]


def list_number_pools(*, tenant_id: str) -> list[dict[str, Any]]:
    with _db().engine.connect() as conn:
        pools = conn.execute(
            text("SELECT * FROM number_pools WHERE tenant_id = :t ORDER BY name"),
            {"t": tenant_id},
        ).mappings().all()
        numbers = conn.execute(
            text(
                """
                SELECT n.* FROM pool_numbers n
                JOIN number_pools p ON p.id = n.pool_id
                WHERE p.tenant_id = :t
                ORDER BY n.e164
                """
            ),
            {"t": tenant_id},
        ).mappings().all()
    by_pool: dict[str, list[dict[str, Any]]] = {}
    for row in numbers:
        by_pool.setdefault(str(row["pool_id"]), []).append(dict(row))
    return [{**dict(p), "numbers": by_pool.get(str(p["id"]), [])} for p in pools]


def list_agent_obligations(*, state: str, limit: int, tenant_id: str) -> list[dict[str, Any]]:
    with _db().engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT o.*, c.name AS customer_name
                FROM agent_obligations o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.tenant_id = :t AND (:state = 'all' OR o.state = :state)
                ORDER BY o.due_at ASC
                LIMIT :limit
                """
            ),
            {"t": tenant_id, "state": state, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def enabled_number_pools(*, tenant_id: str) -> list[dict[str, str]]:
    """``[{name, kind}]`` for the card editor's pool dropdown."""
    with _db().engine.connect() as conn:
        return [
            {"name": str(r["name"]), "kind": str(r["kind"])}
            for r in conn.execute(
                text(
                    "SELECT name, kind FROM number_pools "
                    "WHERE tenant_id = :t AND enabled IS TRUE ORDER BY name"
                ),
                {"t": tenant_id},
            ).mappings()
        ]
