"""My Workspace — work_items queue accessors.

Peeled from ``db.py`` (WP-036 peel 4). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.

``_as_utc`` moved to ``db_core`` first (roadmap peel 4 prerequisite): the
CRM kernel's ``_dispute_sla`` also calls it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from db_core import (
    _IST,
    _actor_user_id,
    _as_utc,
    _rows,
    _sql,
    _tenant,
    _vis_params,
    clamp_list_limit,
    clamp_offset,
)

import money_inr
from db_documents import _doc_channel, _doc_type_screen
from agent_core.clock import utc_now


def _db():
    """The ``db`` module object, resolved at call time.

    Carved modules must use ``_db().engine``, never ``from db_core import
    engine``. See ``db_core._db``.
    """
    import db as d

    return d


# ---------------------------------------------------------------------------
# My Workspace — work_items view (AssignedQueue)
# ---------------------------------------------------------------------------

_DISPUTE_TYPE_LABELS = {
    "paid_already": "Paid already",
    "wrong_amount": "Wrong amount",
    "not_my_account": "Not my account",
    "fee_waiver": "Fee waiver request",
    "duplicate_charge": "Duplicate charge",
    "fraud": "Fraud / unauthorised",
}

_DOC_TYPE_QUEUE_LABELS = {
    "account_statement": "Account statement",
    "no_dues_certificate": "NOC letter",
    "interest_certificate": "Interest certificate",
    "foreclosure_letter": "Foreclosure letter",
    "loan_schedule": "Loan schedule",
    "payment_receipt": "Payment receipt",
    "kyc_letter": "KYC letter",
}


def _fmt_hm(total_seconds: float) -> str:
    secs = max(0, int(abs(total_seconds)))
    hours, rem = divmod(secs, 3600)
    mins = rem // 60
    if hours and mins:
        return f"{hours}h {mins:02d}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _work_item_age_hours(created_at: Any) -> int:
    created = _as_utc(created_at)
    if created is None:
        return 0
    return max(0, int((utc_now() - created).total_seconds() // 3600))


def _work_item_sla(
    sla_due_at: Any,
    *,
    entity_type: str,
    status: str | None,
) -> tuple[str, str]:
    """Compute (sla, slaLabel) server-side — seed strings like '1h 12m left' are not stored."""
    due = _as_utc(sla_due_at)
    now = utc_now()
    if entity_type == "bounce" and status == "in_progress":
        return "ok", "Awaiting pay"
    if due is None:
        if entity_type == "promise" and status == "broken":
            return "breach", "Follow up now"
        if entity_type == "promise":
            return "warn", "Follow up today"
        if entity_type == "bounce":
            return "warn", "First touch pending"
        return "ok", "Open"

    delta = (due - now).total_seconds()
    if delta < 0:
        label = f"Overdue {_fmt_hm(delta)}"
        if entity_type == "promise" and status == "broken":
            return "breach", "Follow up now"
        if entity_type == "bounce":
            return "breach", label
        return "breach", label

    # Callbacks are "due at" appointments — "In …" reads better than "… left".
    if entity_type == "callback":
        level = "warn" if delta < 2 * 3600 else "ok"
        return level, f"In {_fmt_hm(delta)}"

    if entity_type == "promise":
        if status == "broken":
            return "breach", "Follow up now"
        if status == "partial":
            return "warn", "Follow up today"
        if status == "due_today":
            return "warn", "Due today"

    level = "warn" if delta < 2 * 3600 else "ok"
    return level, f"{_fmt_hm(delta)} left"


def _inr(amount: float | None) -> str:
    """Indian digit grouping — ₹12,34,567. See money_inr.inr for the reasoning.

    Kept as a module-local name because db.py writes it several dozen times and
    six other modules used to carry their own divergent copy. There is now one
    implementation and three import sites.
    """
    return money_inr.inr(amount)


def _snippet(text: str | None, limit: int = 72) -> str:
    if not text:
        return ""
    cleaned = " ".join(str(text).replace('"', "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _work_item_enrichment(conn: Any, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-entity_type grouped enrichment — 6 queries, no N+1."""
    _mod = _db()
    by_type: dict[str, list[str]] = {}
    for r in rows:
        by_type.setdefault(r["entity_type"], []).append(r["entity_id"])

    out: dict[str, dict[str, Any]] = {}

    dispute_ids = by_type.get("dispute") or []
    if dispute_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, type, disputed_amount, transcript_snippet, account_id
                    FROM disputes
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": dispute_ids},
            )
        ):
            dtype = r["type"] or "dispute"
            label = _DISPUTE_TYPE_LABELS.get(dtype, dtype.replace("_", " ").title())
            amount = float(r["disputed_amount"]) if r["disputed_amount"] is not None else None
            snippet = _snippet(r["transcript_snippet"])
            detail = snippet or (f"Disputed {_inr(amount)}" if amount is not None else "Open dispute")
            out[f"dispute:{r['id']}"] = {
                "type": label,
                "detail": detail,
                "amount": amount,
                "accountId": r["account_id"],
            }

    callback_ids = by_type.get("callback") or []
    if callback_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, reason, scheduled_at, account_id
                    FROM callbacks
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": callback_ids},
            )
        ):
            when = _as_utc(r["scheduled_at"])
            when_label = when.strftime("%I:%M %p").lstrip("0") if when else "TBD"
            reason = (r["reason"] or "general").strip()
            detail = (
                "General query"
                if reason == "general"
                else reason.replace("_", " ").capitalize()
            )
            out[f"callback:{r['id']}"] = {
                "type": f"Callback · {when_label} IST",
                "detail": detail,
                "amount": None,
                "accountId": r.get("account_id"),
            }

    doc_ids = by_type.get("document_request") or []
    if doc_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, doc_type, period, delivery_channel, account_id
                    FROM document_requests
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": doc_ids},
            )
        ):
            screen = _doc_type_screen(r["doc_type"])
            label = _DOC_TYPE_QUEUE_LABELS.get(screen) or (r["doc_type"] or "Document")
            channel = _doc_channel(r["delivery_channel"]).title()
            period = (r["period"] or "").strip()
            detail = " · ".join(p for p in (period, channel) if p) or "Document request"
            out[f"document_request:{r['id']}"] = {
                "type": label,
                "detail": detail,
                "amount": None,
                "accountId": r["account_id"],
            }

    promise_ids = by_type.get("promise") or []
    if promise_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, status, amount, paid_amount, promised_at, account_id
                    FROM promises
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": promise_ids},
            )
        ):
            status = r["status"] or "broken"
            amount = float(r["amount"]) if r["amount"] is not None else None
            paid = float(r["paid_amount"] or 0)
            when = _as_utc(r["promised_at"])
            date_label = when.strftime("%d %b") if when else ""
            if status == "partial" and amount is not None:
                type_label = "Partial PTP"
                detail = f"Paid {_inr(paid)} of {_inr(amount)} promised"
                remaining = max(0.0, amount - paid)
            elif status == "due_today":
                type_label = "PTP due today"
                detail = f"Promised {_inr(amount)}" + (f" on {date_label}" if date_label else "")
                remaining = amount
            else:
                type_label = "Broken PTP"
                detail = f"Promised {_inr(amount)}" + (f" on {date_label}" if date_label else "")
                remaining = amount
            out[f"promise:{r['id']}"] = {
                "type": type_label,
                "detail": detail.strip(),
                "amount": remaining,
                "accountId": r["account_id"],
            }

    followup_ids = by_type.get("followup") or []
    if followup_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, note, due_at, promise_id, lead_id, priority
                    FROM followups
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": followup_ids},
            )
        ):
            if r["promise_id"]:
                type_label = "Promise follow-up"
            elif r["lead_id"]:
                type_label = "Lead follow-up"
            else:
                type_label = "Follow-up"
            note = _snippet(r["note"]) or "Chase follow-up"
            out[f"followup:{r['id']}"] = {
                "type": type_label,
                "detail": note,
                "amount": None,
                "accountId": None,
            }

    lead_ids = by_type.get("lead") or []
    if lead_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT l.id, l.stage, l.offer_amount, l.estimated_value, l.account_id,
                           l.transcript_snippet, p.name AS product_name
                    FROM leads l
                    LEFT JOIN products p ON p.id = l.product_id
                    WHERE l.id = ANY(:ids)
                    """
                ),
                {"ids": lead_ids},
            )
        ):
            stage = (r["stage"] or "interested").replace("_", " ").title()
            product = r["product_name"] or _snippet(r["transcript_snippet"]) or "Offer"
            amount = r["offer_amount"] if r["offer_amount"] is not None else r["estimated_value"]
            amount_f = float(amount) if amount is not None else None
            out[f"lead:{r['id']}"] = {
                "type": f"Lead · {stage}",
                "detail": str(product),
                "amount": amount_f,
                "accountId": r.get("account_id"),
            }

    bounce_ids = by_type.get("bounce") or []
    if bounce_ids:
        for r in _rows(
            conn.execute(
                text(
                    """
                    SELECT id, reason, amount, account_id, first_touch_channel, status
                    FROM payment_events
                    WHERE id = ANY(:ids)
                    """
                ),
                {"ids": bounce_ids},
            )
        ):
            why = (r["reason"] or "unknown").replace("_", " ")
            amount = float(r["amount"]) if r["amount"] is not None else None
            channel = r["first_touch_channel"]
            if channel:
                detail = f"{why} · sent via {channel}"
            else:
                detail = why
            out[f"bounce:{r['id']}"] = {
                "type": "EMI bounce",
                "detail": detail,
                "amount": amount,
                "accountId": r.get("account_id"),
            }

    return out


def _enacted_by_map(conn: Any, entity_ids: list[str]) -> dict[str, str]:
    """Latest treatment actor, plus clerk-sourced document requests."""
    ids = [e for e in entity_ids if e]
    if not ids:
        return {}
    out: dict[str, str] = {}
    for r in _rows(
        conn.execute(
            text(
                """
                SELECT DISTINCT ON (trigger_ref) trigger_ref, enacted_by
                  FROM treatment_decisions
                 WHERE trigger_ref = ANY(:ids)
                   AND enacted_by IS NOT NULL
                 ORDER BY trigger_ref, created_at DESC
                """
            ),
            {"ids": ids},
        )
    ):
        actor = r.get("enacted_by")
        if actor:
            out[r["trigger_ref"]] = str(actor)
    for r in _rows(
        conn.execute(
            text(
                """
                SELECT id FROM document_requests
                 WHERE id = ANY(:ids) AND source = 'clerk'
                """
            ),
            {"ids": ids},
        )
    ):
        out.setdefault(r["id"], "clerk_agent")
    return out


def _assignee_scope(assignee: str | None) -> str | None:
    """Resolve ``assignee=me`` to the actor, or to the tenant book.

    Entra demo logins are real users with an empty personal queue. Scoping the
    workspace (and the stats that sit next to it) to that empty queue hid the
    seeded book from every org presenter who was not already an assigned agent.
    An actor who *does* have assigned rows still sees only those rows.
    """
    if assignee in (None, "", "all"):
        return None
    if assignee != "me":
        return assignee
    uid = _actor_user_id()
    if not uid:
        return None
    engine = _db().engine
    with engine.connect() as conn:
        hit = conn.execute(
            text("SELECT 1 FROM work_items WHERE assignee_user_id = :uid LIMIT 1"),
            {"uid": uid},
        ).first()
    return uid if hit else None


def list_work_items(
    *, assignee: str | None = "me", limit: int | None = None, offset: int | None = None
) -> list[dict[str, Any]]:
    """Assigned queue from the work_items view — screen QueueRow + entityType.

    assignee='me' (default) scopes to the acting user from /me (ACTOR_USER_ID).
    Pass assignee=None / 'all' for the unfiltered tenant queue. An actor with
    no personal rows is treated as 'all' so demo logins see the seeded book.
    """
    engine = _db().engine
    assignee_id = _assignee_scope(assignee)

    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT
                      w.entity_type,
                      w.entity_id,
                      w.customer_id,
                      w.assignee_user_id,
                      w.status,
                      w.priority,
                      w.sla_due_at,
                      w.created_at,
                      w.source,
                      c.name AS customer_name,
                      a.id AS account_id
                    FROM work_items w
                    JOIN customers c ON c.id = w.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN LATERAL (
                      SELECT id
                      FROM accounts
                      WHERE customer_id = w.customer_id
                      ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
                      LIMIT 1
                    ) a ON true
                    WHERE (
                      CAST(:assignee_id AS text) IS NULL
                      OR w.assignee_user_id = CAST(:assignee_id AS text)
                    )
                    ORDER BY
                      CASE
                        WHEN w.sla_due_at IS NULL THEN 1
                        WHEN w.sla_due_at < now() THEN 0
                        ELSE 2
                      END,
                      w.sla_due_at ASC NULLS LAST,
                      w.created_at ASC,
                      w.entity_id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    "assignee_id": assignee_id,
                    "tenant_id": _tenant(), **_vis_params(),
                    "limit": page,
                    "offset": skip,
                },
            )
        )
        enrichment = _work_item_enrichment(conn, rows)
        enacted = _enacted_by_map(conn, [r["entity_id"] for r in rows])
        out: list[dict[str, Any]] = []
        for r in rows:
            key = f"{r['entity_type']}:{r['entity_id']}"
            extra = enrichment.get(key) or {}
            account_id = extra.get("accountId") or r["account_id"] or ""
            sla, sla_label = _work_item_sla(
                r["sla_due_at"],
                entity_type=r["entity_type"],
                status=r["status"],
            )
            amount = extra.get("amount")
            out.append(
                {
                    "id": r["entity_id"],
                    "customer": r["customer_name"] or "Unknown",
                    "accountId": account_id,
                    "type": extra.get("type") or r["entity_type"].replace("_", " ").title(),
                    "detail": extra.get("detail") or (r["status"] or ""),
                    "amount": amount,
                    "ageHours": _work_item_age_hours(r["created_at"]),
                    "sla": sla,
                    "slaLabel": sla_label,
                    "entityType": r["entity_type"],
                    "status": r["status"],
                    "assigneeUserId": r["assignee_user_id"],
                    "customerId": r["customer_id"],
                    "enactedBy": enacted.get(r["entity_id"]),
                }
            )
        return out


# ---------------------------------------------------------------------------
# Workspace stats + right rail (rolling window anchored to max interaction)
# ---------------------------------------------------------------------------


def _next_lead(conn: Any, assignee_id: str | None) -> dict[str, Any] | None:
    """Highest-value open lead on this agent's queue, for the workspace rail."""
    d = _db()
    params: dict[str, Any] = {
        "tenant": d.current_tenant(),
        "stages": list(d.OPEN_LEAD_STAGES),
    }
    owner_clause = ""
    if assignee_id:
        owner_clause = "AND l.owner_user_id = :uid"
        params["uid"] = assignee_id
    row = d._one(
        conn.execute(
            text(
                f"""
                SELECT
                  l.id,
                  c.name AS customer_name,
                  a.id AS account_id,
                  COALESCE(p.name, l.product_id, 'Offer') AS product_name,
                  COALESCE(l.estimated_value, l.offer_amount) AS amount,
                  l.stage,
                  c.preferred_window,
                  l.transcript_snippet
                FROM leads l
                JOIN customers c ON c.id = l.customer_id
                LEFT JOIN products p ON p.id = l.product_id
                LEFT JOIN LATERAL (
                  SELECT id FROM accounts
                  WHERE customer_id = l.customer_id
                  ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
                  LIMIT 1
                ) a ON true
                WHERE c.tenant_id = :tenant
                  AND l.stage = ANY(:stages)
                  {owner_clause}
                ORDER BY
                  CASE l.priority
                    WHEN 'urgent' THEN 0 WHEN 'high' THEN 1
                    WHEN 'normal' THEN 2 ELSE 3
                  END,
                  COALESCE(l.estimated_value, l.offer_amount, 0) DESC,
                  l.captured_at ASC NULLS LAST
                LIMIT 1
                """
            ),
            params,
        )
    )
    if not row:
        return None
    product = row["product_name"] or "Offer"
    window = row.get("preferred_window")
    amount = row.get("amount")
    reason = (row.get("transcript_snippet") or "").strip() or f"Open {row['stage']} lead"
    if window:
        reason = f"{reason} · {window}"
    return {
        "id": row["id"],
        "customer": row["customer_name"] or "Unknown",
        "accountId": row["account_id"] or "",
        "productName": product,
        "amount": float(amount) if amount is not None else None,
        "stage": row["stage"],
        "window": window,
        "reason": reason[:180],
    }


def workspace_summary(*, assignee: str | None = "me") -> dict[str, Any]:
    """Honest rolling-window stats + next callback + SLA countdowns for My Workspace."""
    d = _db()
    assignee_id = _assignee_scope(assignee)

    with d.engine.connect() as conn:
        anchor = conn.execute(
            text("SELECT max(started_at) FROM interactions WHERE tenant_id = :t"),
            {"t": d.current_tenant()},
        ).scalar()
        if anchor is None:
            anchor = utc_now()

        # Current 7d vs prior 7d, scoped to handler when assignee set
        params: dict[str, Any] = {"tenant": d.current_tenant(), "anchor": anchor}
        handler_clause = ""
        if assignee_id:
            handler_clause = "AND i.handler_user_id = :uid"
            params["uid"] = assignee_id

        cur = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*) AS calls,
                      coalesce(avg(duration_sec), 0) AS aht_sec,
                      count(*) FILTER (WHERE query_resolved IS TRUE) AS resolutions
                    FROM interactions i
                    WHERE i.tenant_id = :tenant
                      AND i.started_at > CAST(:anchor AS timestamptz) - interval '7 days'
                      AND i.started_at <= CAST(:anchor AS timestamptz)
                      {handler_clause}
                    """
                ),
                params,
            )
        )
        prev = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT
                      count(*) AS calls,
                      coalesce(avg(duration_sec), 0) AS aht_sec,
                      count(*) FILTER (WHERE query_resolved IS TRUE) AS resolutions
                    FROM interactions i
                    WHERE i.tenant_id = :tenant
                      AND i.started_at > CAST(:anchor AS timestamptz) - interval '14 days'
                      AND i.started_at <= CAST(:anchor AS timestamptz) - interval '7 days'
                      {handler_clause}
                    """
                ),
                params,
            )
        )
        # Team AHT for delta (all handlers, same window)
        team = d._one(
            conn.execute(
                text(
                    """
                    SELECT coalesce(avg(duration_sec), 0) AS aht_sec
                    FROM interactions i
                    WHERE i.tenant_id = :tenant
                      AND i.started_at > CAST(:anchor AS timestamptz) - interval '7 days'
                      AND i.started_at <= CAST(:anchor AS timestamptz)
                    """
                ),
                {"tenant": d.current_tenant(), "anchor": anchor},
            )
        )

        ptp_params: dict[str, Any] = {"tenant": d.current_tenant(), "anchor": anchor}
        ptp_clause = ""
        if assignee_id:
            ptp_clause = "AND p.owner_user_id = :uid"
            ptp_params["uid"] = assignee_id
        ptp = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT count(*) AS n, coalesce(sum(p.amount), 0) AS amt
                    FROM promises p
                    JOIN customers c ON c.id = p.customer_id
                    WHERE c.tenant_id = :tenant
                      AND p.created_at > CAST(:anchor AS timestamptz) - interval '7 days'
                      AND p.created_at <= CAST(:anchor AS timestamptz)
                      {ptp_clause}
                    """
                ),
                ptp_params,
            )
        )

        calls = int((cur or {}).get("calls") or 0)
        prev_calls = int((prev or {}).get("calls") or 0)
        aht_sec = float((cur or {}).get("aht_sec") or 0)
        team_aht = float((team or {}).get("aht_sec") or 0)
        resolutions = int((cur or {}).get("resolutions") or 0)
        rate = f"{round(100 * resolutions / calls)}%" if calls else "0%"
        delta_calls = calls - prev_calls
        aht_vs_team = int(round(aht_sec - team_aht))

        def fmt_aht(sec: float) -> str:
            s = max(0, int(round(sec)))
            return f"{s // 60}m {s % 60:02d}s"

        stats = {
            "callsHandled": calls,
            "callsHandledDelta": f"{delta_calls:+d} vs prior 7d",
            "aht": fmt_aht(aht_sec),
            "ahtDelta": f"{aht_vs_team:+d}s vs team",
            "resolutions": resolutions,
            "resolutionRate": rate,
            "promisesCount": int((ptp or {}).get("n") or 0),
            "promisesAmount": float((ptp or {}).get("amt") or 0),
            "windowLabel": "Rolling 7 days",
        }

        # Next callback
        cb_params: dict[str, Any] = {}
        cb_clause = ""
        if assignee_id:
            cb_clause = "AND cb.assignee_user_id = :uid"
            cb_params["uid"] = assignee_id
        cb = d._one(
            conn.execute(
                text(
                    f"""
                    SELECT cb.id, cb.reason, cb.scheduled_at,
                           c.name AS customer_name, a.id AS account_id
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                    LEFT JOIN LATERAL (
                      SELECT id FROM accounts
                      WHERE customer_id = cb.customer_id
                      ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
                      LIMIT 1
                    ) a ON true
                    WHERE lower(coalesce(cb.status,'')) NOT IN ('completed','cancelled','done','closed')
                      AND cb.scheduled_at IS NOT NULL
                      AND cb.scheduled_at >= now() - interval '1 hour'
                      AND c.tenant_id = :tenant
                      {cb_clause}
                    ORDER BY cb.scheduled_at ASC
                    LIMIT 1
                    """
                ),
                {**cb_params, "tenant": d.current_tenant()},
            )
        )
        next_cb = None
        if cb and cb.get("scheduled_at"):
            sched = cb["scheduled_at"]
            if isinstance(sched, str):
                try:
                    sched = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                except ValueError:
                    sched = None
            if sched is not None:
                now = utc_now()
                if getattr(sched, "tzinfo", None) is None:
                    sched = sched.replace(tzinfo=timezone.utc)
                mins = int((sched - now).total_seconds() // 60)
                # Fixed offset, matching db._IST: India observes no DST, so this
                # needs no tzdata. The ZoneInfo lookup silently fell back to a
                # raw ISO timestamp on any image without the tz database.
                time_label = sched.astimezone(_IST).strftime("%I:%M %p").lstrip("0")
                next_cb = {
                    "id": cb["id"],
                    "customer": cb["customer_name"] or "Unknown",
                    "accountId": cb["account_id"] or "",
                    "reason": cb.get("reason") or "Scheduled callback",
                    "time": time_label,
                    "timezone": "IST",
                    "inMinutes": mins,
                }

        # SLA countdowns from work_items already assigned
        wi_params: dict[str, Any] = {}
        wi_clause = ""
        if assignee_id:
            wi_clause = "AND w.assignee_user_id = :uid"
            wi_params["uid"] = assignee_id
        wi_rows = d._rows(
            conn.execute(
                text(
                    f"""
                    SELECT w.entity_type, w.entity_id, w.sla_due_at, w.status,
                           c.name AS customer_name
                    FROM work_items w
                    JOIN customers c ON c.id = w.customer_id
                    WHERE w.sla_due_at IS NOT NULL
                      AND c.tenant_id = :tenant
                      {wi_clause}
                    ORDER BY w.sla_due_at ASC
                    LIMIT 8
                    """
                ),
                {**wi_params, "tenant": d.current_tenant()},
            )
        )
        enacted = d._enacted_by_map(conn, [w["entity_id"] for w in wi_rows])
        sla_countdowns: list[dict[str, Any]] = []
        for w in wi_rows:
            sla, label = d._work_item_sla(
                w["sla_due_at"], entity_type=w["entity_type"], status=w["status"]
            )
            kind = {
                "dispute": "Dispute",
                "promise": "Broken PTP",
                "document_request": "Doc",
                "callback": "Callback",
                "followup": "Follow-up",
                "bounce": "Bounce",
            }.get(w["entity_type"], w["entity_type"])
            sla_countdowns.append(
                {
                    "id": w["entity_id"],
                    "label": f"{kind} · {w['customer_name']}",
                    "remaining": label,
                    "level": sla,
                    "enactedBy": enacted.get(w["entity_id"]),
                }
            )

        # Outside preferred window nudge
        outside = 0
        open_cbs = d._rows(
            conn.execute(
                text(
                    f"""
                    SELECT cb.scheduled_at, c.preferred_window
                    FROM callbacks cb
                    JOIN customers c ON c.id = cb.customer_id
                    WHERE lower(coalesce(cb.status,'')) NOT IN ('completed','cancelled','done','closed')
                      AND cb.scheduled_at IS NOT NULL
                      AND c.tenant_id = :tenant
                      {cb_clause}
                    """
                ),
                {**cb_params, "tenant": d.current_tenant()},
            )
        )
        for row in open_cbs:
            sched = row["scheduled_at"]
            sched_s = sched.isoformat() if hasattr(sched, "isoformat") else str(sched)
            try:
                if d._outside_preferred_window(sched_s, row.get("preferred_window")):
                    outside += 1
            except Exception:
                continue

        return {
            "stats": stats,
            "nextCallback": next_cb,
            "nextLead": _next_lead(conn, assignee_id),
            "slaCountdowns": sla_countdowns,
            "outsideWindowCount": outside,
        }
