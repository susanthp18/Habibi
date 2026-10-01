"""My Workspace — work_items queue accessors.

Peeled from ``db.py`` (WP-036 peel 4). Call sites stay ``db.*`` via a
bottom-of-file re-export. Reach the engine through :func:`_db`, never
``from db_core import engine``: the ``db_tx`` fixture wraps ``db.engine``,
and a name bound from ``db_core`` bypasses that proxy.

``_as_utc`` moved to ``db_core`` first (roadmap peel 4 prerequisite): the
CRM kernel's ``_dispute_sla`` also calls it.
"""

from __future__ import annotations

from datetime import timedelta
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


def _ist_clock(value: Any) -> str | None:
    """``2:30 PM`` in IST -- the one formatter for every callback time on the page.

    The queue printed the UTC clock and appended "IST", so a 14:30 IST callback
    read 9:00 AM in the queue and 2:30 PM on the next-callback card.
    """
    when = _as_utc(value)
    return when.astimezone(_IST).strftime("%I:%M %p").lstrip("0") if when else None


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
            when_label = _ist_clock(r["scheduled_at"]) or "TBD"
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
                    SELECT f.id, f.note, f.promise_id, f.lead_id, p.account_id
                    FROM followups f
                    LEFT JOIN promises p ON p.id = f.promise_id
                    WHERE f.id = ANY(:ids)
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
                "accountId": r["account_id"],
                "relatedId": r["promise_id"],
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


#: The queue scopes. ``me`` is my work: rows assigned to me, plus unassigned
#: rows on customers whose book I hold -- the AI files promises and callbacks
#: with no assignee, and they belong to the borrower's agent. ``pool`` is the
#: unassigned pool ``visibility`` keeps open to every agent. Neither falls back
#: to the other: a screen headed "yours" shows only yours, and finishing your
#: last item does not turn the next refresh into somebody else's book.
#: ``all`` is the whole visible queue; any other value names an assignee.
def _scope_sql(scope: str | None, item_assignee: str) -> tuple[str, dict[str, Any]]:
    if scope in (None, "", "all"):
        return "", {}
    if scope == "pool":
        return f"AND {item_assignee} IS NULL AND c.assigned_user_id IS NULL", {}
    uid = _actor_user_id() if scope == "me" else scope
    if not uid:
        return "AND false", {}
    if scope == "me":
        return (
            f"AND ({item_assignee} = :scope_uid"
            f" OR ({item_assignee} IS NULL AND c.assigned_user_id = :scope_uid))",
            {"scope_uid": uid},
        )
    return f"AND {item_assignee} = :scope_uid", {"scope_uid": uid}


#: Deadline filters, on the due time the Due column shows.
_DUE_SQL = {
    "overdue": "AND w.sla_due_at < now()",
    "due_soon": "AND w.sla_due_at >= now() AND w.sla_due_at < now() + interval '2 hours'",
    "later": "AND (w.sla_due_at IS NULL OR w.sla_due_at >= now() + interval '2 hours')",
}

_ITEMS_SQL = """
    SELECT w.entity_type, w.entity_id, w.customer_id, w.assignee_user_id, w.status,
           w.sla_due_at, w.created_at, c.name AS customer_name
    FROM work_items w
    JOIN customers c ON c.id = w.customer_id
     AND c.tenant_id = :tenant_id
     /*VISIBILITY*/
    WHERE true {where}
"""


def _iso(value: Any) -> str | None:
    when = _as_utc(value)
    return when.isoformat() if when else None


def _shape_items(conn: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Work-item rows as the queue renders them; the summary's attention list too."""
    enrichment = _work_item_enrichment(conn, rows)
    enacted = _enacted_by_map(conn, [r["entity_id"] for r in rows])
    out: list[dict[str, Any]] = []
    for r in rows:
        extra = enrichment.get(f"{r['entity_type']}:{r['entity_id']}") or {}
        sla, sla_label = _work_item_sla(
            r["sla_due_at"], entity_type=r["entity_type"], status=r["status"]
        )
        out.append(
            {
                "id": r["entity_id"],
                "customer": r["customer_name"] or "Unknown",
                # The record's own account. Guessing the customer's first one
                # named the wrong loan for a borrower with two.
                "accountId": extra.get("accountId") or "",
                "type": extra.get("type") or r["entity_type"].replace("_", " ").title(),
                "detail": extra.get("detail") or (r["status"] or ""),
                "amount": extra.get("amount"),
                "createdAt": _iso(r["created_at"]),
                "dueAt": _iso(r["sla_due_at"]),
                "sla": sla,
                "slaLabel": sla_label,
                "entityType": r["entity_type"],
                "status": r["status"],
                "assigneeUserId": r["assignee_user_id"],
                "customerId": r["customer_id"],
                "relatedId": extra.get("relatedId"),
                "enactedBy": enacted.get(r["entity_id"]),
            }
        )
    return out


def list_work_items(
    *,
    assignee: str | None = "me",
    limit: int | None = None,
    offset: int | None = None,
    entity_type: str | None = None,
    due: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    """One page of the queue in a scope (see :func:`_scope_sql`), most urgent first.

    Filters run here, not on a returned page: a tab or a search over the first
    page silently described only that page.
    """
    scope, params = _scope_sql(assignee, "w.assignee_user_id")
    where = [scope, _DUE_SQL.get(due or "", "")]
    if entity_type:
        where.append("AND w.entity_type = :entity_type")
        params["entity_type"] = entity_type
    needle = (q or "").strip()
    if needle:
        where.append(
            "AND (c.name ILIKE :q OR w.entity_id ILIKE :q OR EXISTS ("
            "SELECT 1 FROM accounts qa WHERE qa.customer_id = w.customer_id AND qa.id ILIKE :q))"
        )
        params["q"] = f"%{needle}%"
    with _db().engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    _ITEMS_SQL.format(where=" ".join(where))
                    + """
                    ORDER BY
                      CASE WHEN w.sla_due_at IS NULL THEN 1 WHEN w.sla_due_at < now() THEN 0 ELSE 2 END,
                      w.sla_due_at ASC NULLS LAST, w.created_at ASC, w.entity_id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {
                    **params,
                    "tenant_id": _tenant(),
                    **_vis_params(),
                    "limit": clamp_list_limit(limit),
                    "offset": clamp_offset(offset),
                },
            )
        )
        return _shape_items(conn, rows)


# ---------------------------------------------------------------------------
# Workspace summary: the operator's own numbers, next-up cards, attention list
# ---------------------------------------------------------------------------

#: How many attention rows the summary carries; ``queueCounts`` holds the total.
ATTENTION_ROWS = 8

_ENTITY_TYPES = ("dispute", "callback", "document_request", "promise", "followup", "lead", "bounce")


def _queue_counts(conn: Any, scope: str | None) -> dict[str, Any]:
    clause, params = _scope_sql(scope, "w.assignee_user_id")
    rows = _rows(
        conn.execute(
            _sql(
                f"""
                SELECT w.entity_type, count(*) AS n,
                       count(*) FILTER (WHERE w.sla_due_at < now()) AS overdue,
                       count(*) FILTER (WHERE w.sla_due_at >= now()
                                          AND w.sla_due_at < now() + interval '2 hours') AS due_soon
                FROM work_items w
                JOIN customers c ON c.id = w.customer_id
                 AND c.tenant_id = :tenant_id
                 /*VISIBILITY*/
                WHERE true {clause}
                GROUP BY w.entity_type
                """
            ),
            {**params, "tenant_id": _tenant(), **_vis_params()},
        )
    )
    by_type = {t: 0 for t in _ENTITY_TYPES}
    for r in rows:
        by_type[r["entity_type"]] = int(r["n"])
    return {
        "total": sum(by_type.values()),
        "overdue": sum(int(r["overdue"]) for r in rows),
        "dueSoon": sum(int(r["due_soon"]) for r in rows),
        "byType": by_type,
    }


def _personal_stats(conn: Any) -> dict[str, Any]:
    """The actor's own last seven days, ending now.

    A handled call is a completed voice interaction a person handled -- not a
    WhatsApp thread, a failed dial or a bot call. A promise counts for whoever
    handled the call it was captured on; its current owner can change, and
    reassigning a promise must not move who captured it.
    """
    d = _db()
    end = utc_now()
    params = {"tenant": _tenant(), "uid": _actor_user_id(), "end": end}
    calls_sql = """
        SELECT count(*) AS calls,
               coalesce(avg(duration_sec), 0) AS aht_sec,
               count(*) FILTER (WHERE query_resolved IS TRUE) AS resolutions
        FROM interactions i
        WHERE i.tenant_id = :tenant
          AND i.channel = 'voice' AND i.handler_kind = 'human' AND i.status = 'completed'
          AND i.started_at > CAST(:end AS timestamptz) - interval '{start} days'
          AND i.started_at <= CAST(:end AS timestamptz) - interval '{stop} days'
          {mine}
    """
    mine = "AND i.handler_user_id = :uid"
    cur = d._one(conn.execute(text(calls_sql.format(start=7, stop=0, mine=mine)), params)) or {}
    prev = d._one(conn.execute(text(calls_sql.format(start=14, stop=7, mine=mine)), params)) or {}
    team = d._one(conn.execute(text(calls_sql.format(start=7, stop=0, mine="")), params)) or {}
    ptp = d._one(
        conn.execute(
            text(
                """
                SELECT count(*) AS n, coalesce(sum(p.amount), 0) AS amt
                FROM promises p
                JOIN interactions i ON i.id = p.interaction_id
                WHERE i.tenant_id = :tenant AND i.handler_user_id = :uid
                  AND p.created_at > CAST(:end AS timestamptz) - interval '7 days'
                  AND p.created_at <= CAST(:end AS timestamptz)
                """
            ),
            params,
        )
    ) or {}
    return {
        "windowStart": (end - timedelta(days=7)).isoformat(),
        "windowEnd": end.isoformat(),
        "callsHandled": int(cur.get("calls") or 0),
        "callsHandledPrior": int(prev.get("calls") or 0),
        "resolutions": int(cur.get("resolutions") or 0),
        "ahtSec": int(round(float(cur.get("aht_sec") or 0))),
        "teamAhtSec": int(round(float(team.get("aht_sec") or 0))),
        "promisesCount": int(ptp.get("n") or 0),
        "promisesAmount": float(ptp.get("amt") or 0),
    }


#: A callback still waiting for its slot. Missed and in-progress ones are
#: attention rows, not the next appointment.
_UPCOMING_CALLBACK = "cb.status IN ('scheduled','reminded','rescheduled') AND cb.scheduled_at >= now()"


def _next_callback(conn: Any, scope: str | None) -> dict[str, Any] | None:
    clause, params = _scope_sql(scope, "cb.assignee_user_id")
    cb = _db()._one(
        conn.execute(
            _sql(
                f"""
                SELECT cb.id, cb.reason, cb.scheduled_at, cb.status, cb.account_id,
                       cb.customer_id, c.name AS customer_name
                FROM callbacks cb
                JOIN customers c ON c.id = cb.customer_id
                 AND c.tenant_id = :tenant_id
                 /*VISIBILITY*/
                WHERE {_UPCOMING_CALLBACK} {clause}
                ORDER BY cb.scheduled_at ASC
                LIMIT 1
                """
            ),
            {**params, "tenant_id": _tenant(), **_vis_params()},
        )
    )
    if not cb:
        return None
    return {
        "id": cb["id"],
        "customer": cb["customer_name"] or "Unknown",
        "customerId": cb["customer_id"],
        "accountId": cb["account_id"] or "",
        "reason": cb.get("reason") or "Scheduled callback",
        "status": cb["status"],
        "scheduledAt": _iso(cb["scheduled_at"]),
        "time": _ist_clock(cb["scheduled_at"]) or "",
        "timezone": "IST",
    }


def _next_lead(conn: Any, scope: str | None) -> dict[str, Any] | None:
    """The open lead to work next: highest priority, then highest value."""
    d = _db()
    clause, params = _scope_sql(scope, "l.owner_user_id")
    row = d._one(
        conn.execute(
            _sql(
                f"""
                SELECT
                  l.id, l.customer_id, l.account_id, l.stage, l.priority,
                  c.name AS customer_name,
                  COALESCE(p.name, l.product_id, 'Offer') AS product_name,
                  COALESCE(l.estimated_value, l.offer_amount) AS amount,
                  c.preferred_window,
                  l.transcript_snippet,
                  (SELECT min(f.due_at) FROM followups f
                    WHERE f.lead_id = l.id AND f.status IN ('open','in_progress','snoozed'))
                    AS next_followup_at
                FROM leads l
                JOIN customers c ON c.id = l.customer_id
                 AND c.tenant_id = :tenant_id
                 /*VISIBILITY*/
                LEFT JOIN products p ON p.id = l.product_id
                WHERE l.stage = ANY(:stages) {clause}
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
            {**params, "tenant_id": _tenant(), **_vis_params(), "stages": list(d.OPEN_LEAD_STAGES)},
        )
    )
    if not row:
        return None
    amount = row.get("amount")
    return {
        "id": row["id"],
        "customer": row["customer_name"] or "Unknown",
        "customerId": row["customer_id"],
        "accountId": row["account_id"] or "",
        "productName": row["product_name"] or "Offer",
        "amount": float(amount) if amount is not None else None,
        "stage": row["stage"],
        "priority": row.get("priority") or "normal",
        "window": row.get("preferred_window"),
        "nextFollowupAt": _iso(row.get("next_followup_at")),
        "reason": ((row.get("transcript_snippet") or "").strip() or f"Open {row['stage']} lead")[:180],
    }


def _attention(conn: Any, scope: str | None) -> list[dict[str, Any]]:
    """Overdue and due-within-two-hours work, most urgent first."""
    clause, params = _scope_sql(scope, "w.assignee_user_id")
    rows = _rows(
        conn.execute(
            _sql(
                _ITEMS_SQL.format(where=f"{clause} AND w.sla_due_at < now() + interval '2 hours'")
                + " ORDER BY w.sla_due_at ASC, w.entity_id LIMIT :limit"
            ),
            {**params, "tenant_id": _tenant(), **_vis_params(), "limit": ATTENTION_ROWS},
        )
    )
    return _shape_items(conn, rows)


def _callbacks_blocked(conn: Any, scope: str | None) -> int:
    """Upcoming callbacks booked for a time the contact Gate would refuse.

    The Gate's own verdict (consent, DND, statutory and preferred hours,
    allowed days), not a second reading of the preferred window.
    ``blocks_scheduling`` reserves and writes nothing.
    """
    import contact_policy

    clause, params = _scope_sql(scope, "cb.assignee_user_id")
    rows = _rows(
        conn.execute(
            _sql(
                f"""
                SELECT cb.customer_id, cb.scheduled_at
                FROM callbacks cb
                JOIN customers c ON c.id = cb.customer_id
                 AND c.tenant_id = :tenant_id
                 /*VISIBILITY*/
                WHERE {_UPCOMING_CALLBACK} {clause}
                ORDER BY cb.scheduled_at
                LIMIT 200
                """
            ),
            {**params, "tenant_id": _tenant(), **_vis_params()},
        )
    )
    # ponytail: one Gate evaluation per upcoming callback, capped at 200 rows;
    # batch the evaluation if an operator's diary ever outgrows that.
    return sum(
        1
        for r in rows
        if contact_policy.blocks_scheduling(
            conn, customer_id=r["customer_id"], channel="voice", at=_as_utc(r["scheduled_at"])
        )
    )


def workspace_summary(*, assignee: str | None = "me") -> dict[str, Any]:
    """Everything on My Workspace beside the queue table, for one scope."""
    with _db().engine.connect() as conn:
        counts = _queue_counts(conn, assignee)
        totals = {
            scope: counts["total"] if assignee == scope else _queue_counts(conn, scope)["total"]
            for scope in ("me", "pool")
        }
        return {
            "stats": _personal_stats(conn),
            "nextCallback": _next_callback(conn, assignee),
            "nextLead": _next_lead(conn, assignee),
            "attention": _attention(conn, assignee),
            "queueCounts": counts,
            "scopeTotals": totals,
            "callbacksBlockedCount": _callbacks_blocked(conn, assignee),
        }
