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

import money_inr


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
    _as_utc = _db()._as_utc
    created = _as_utc(created_at)
    if created is None:
        return 0
    return max(0, int((datetime.now(timezone.utc) - created).total_seconds() // 3600))


def _work_item_sla(
    sla_due_at: Any,
    *,
    entity_type: str,
    status: str | None,
) -> tuple[str, str]:
    """Compute (sla, slaLabel) server-side — seed strings like '1h 12m left' are not stored."""
    _as_utc = _db()._as_utc
    due = _as_utc(sla_due_at)
    now = datetime.now(timezone.utc)
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
    _rows = _mod._rows
    _as_utc = _mod._as_utc
    _doc_type_screen = _mod._doc_type_screen
    _doc_channel = _mod._doc_channel
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
    _mod = _db()
    _rows = _mod._rows
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


def list_work_items(
    *, assignee: str | None = "me", limit: int | None = None, offset: int | None = None
) -> list[dict[str, Any]]:
    """Assigned queue from the work_items view — screen QueueRow + entityType.

    assignee='me' (default) scopes to the acting user from /me (ACTOR_USER_ID).
    Pass assignee=None / 'all' for the unfiltered tenant queue.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _sql = _mod._sql
    _tenant = _mod._tenant
    _vis_params = _mod._vis_params
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    _actor_user_id = _mod._actor_user_id
    assignee_id: str | None
    if assignee in (None, "", "all"):
        assignee_id = None
    elif assignee == "me":
        assignee_id = _actor_user_id()
    else:
        assignee_id = assignee

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

