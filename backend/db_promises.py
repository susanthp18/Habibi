"""Promises to pay and payment plans: the writers, the board readers, the by-id row.

Peeled from ``db.py``. Reaches ``db`` only for ``engine`` (through ``_db()``,
so the suite's savepoint proxy is honoured) and for the sibling readers that
still live there.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text

from agent_core import clock
from agent_core.clock import utc_now
from db_core import (
    _actor,
    assert_transition,
    DEFAULT_DETAIL_LIMIT,
    _account_tail,
    _activity,
    _actor_user_id,
    _assert_tenant_owns,
    _ensure_customer,
    _first_account_id,
    _id,
    _idempotent_response,
    _one,
    _rows,
    _sql,
    _store_idempotent_response,
    _tenant,
    _vis_params,
    clamp_list_limit,
    clamp_offset,
)


logger = logging.getLogger(__name__)


def _db():
    """The ``db`` module object, resolved at call time."""
    import db as d

    return d


class OwnerBotNotFound(KeyError):
    """The requested ownerBotId does not exist in this environment.

    Subclasses KeyError so existing ``except KeyError -> 404`` handlers keep
    working, while callers that want to retry without a bot owner can catch
    exactly this condition instead of every KeyError (including a genuine
    missing-payload-key bug).
    """


def _promise_contracts(conn: Any, customer_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT p.id, p.amount, p.promised_at, p.created_at, p.channel, p.status,
                       p.reminder_status, p.revision_count, p.cancel_reason,
                       COALESCE(u.name, b.name) AS handler
                FROM promises p
                LEFT JOIN users u ON u.id = p.owner_user_id
                LEFT JOIN bots b ON b.id = p.owner_bot_id
                WHERE p.customer_id = :customer_id
                ORDER BY p.promised_at DESC
                LIMIT :limit
                """
            ),
            {"customer_id": customer_id, "limit": DEFAULT_DETAIL_LIMIT},
        )
    )
    return [
        {
            "id": r["id"],
            "amount": r["amount"],
            "promisedDate": r["promised_at"],
            "createdAt": r["created_at"],
            "channel": r["channel"],
            "handler": r["handler"] or "Unassigned",
            "status": r["status"],
            "reminderStatus": r["reminder_status"],
            "revisionCount": int(r["revision_count"] or 0),
            "cancelReason": r["cancel_reason"],
        }
        for r in rows
    ]


def _promise_events(conn: Any, promise_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """activity_events grouped by promise id, for the promises-screen timeline."""
    if not promise_ids:
        return {}
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT entity_id, at, label, tone
                FROM activity_events
                WHERE entity_type = 'promise' AND entity_id = ANY(:ids)
                ORDER BY at
                """
            ),
            {"ids": promise_ids},
        )
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault(r["entity_id"], []).append({"at": r["at"], "label": r["label"], "tone": r["tone"]})
    return grouped


def list_promises(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Promise-to-Pay screen feed (richer than the Customer 360 contract)."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with _db().engine.connect() as conn:
        rows = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT p.id, p.customer_id, c.name AS customer_name, p.account_id,
                           p.amount, p.promised_at, p.created_at, p.channel, p.status,
                           p.reminder_status, p.paid_amount, p.plan_id, p.owner_kind,
                           p.revision_count, p.cancel_reason,
                           COALESCE(u.name, b.name) AS owner,
                           pi.status AS payment_intent_status,
                           pi.confirm_channel,
                           pi.suppression_reason,
                           pi.phone_last4,
                           pi.id AS payment_intent_id
                    FROM promises p
                    JOIN customers c ON c.id = p.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    LEFT JOIN users u ON u.id = p.owner_user_id
                    LEFT JOIN bots b ON b.id = p.owner_bot_id
                    LEFT JOIN LATERAL (
                        SELECT status, confirm_channel, suppression_reason, phone_last4, id
                        FROM payment_intents
                        WHERE promise_id = p.id
                        ORDER BY created_at DESC
                        LIMIT 1
                    ) pi ON true
                    ORDER BY p.promised_at DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
            )
        )
        events = _promise_events(conn, [r["id"] for r in rows])
        result = []
        for r in rows:
            evts = events.get(r["id"]) or [{"at": r["created_at"], "label": "Promise captured", "tone": "info"}]
            result.append(
                {
                    "id": r["id"],
                    "customerId": r["customer_id"],
                    "customerName": r["customer_name"],
                    "accountTail": _account_tail(r["account_id"]) or "",
                    "amount": r["amount"],
                    "promisedDate": r["promised_at"],
                    "createdAt": r["created_at"],
                    "channel": r["channel"] or "voice",
                    "source": "bot" if r["owner_kind"] == "bot" else "agent",
                    "owner": r["owner"] or "Unassigned",
                    "reminderStatus": r["reminder_status"],
                    "status": r["status"],
                    "revisionCount": int(r["revision_count"] or 0),
                    "cancelReason": r["cancel_reason"],
                    "paidAmount": r["paid_amount"] if r["paid_amount"] else None,
                    "notes": None,
                    "planId": r["plan_id"],
                    "events": evts,
                    "confirmChannel": r.get("confirm_channel"),
                    "confirmStatus": (
                        "suppressed"
                        if r.get("suppression_reason") and r.get("payment_intent_status") not in {"sent", "opened", "paid"}
                        else r.get("payment_intent_status")
                    ),
                    "paymentIntentStatus": r.get("payment_intent_status"),
                    "paymentIntentId": r.get("payment_intent_id"),
                    "payLinkSent": r.get("payment_intent_status") in {"sent", "opened", "paid"},
                    "phoneLast4": r.get("phone_last4"),
                }
            )
        return result


def _plan_cadence(due_dates: list[str]) -> str:
    """Infer cadence from the gap between the first two installments."""
    if len(due_dates) < 2:
        return "monthly"
    parsed = sorted(datetime.fromisoformat(d) for d in due_dates)
    gap = (parsed[1] - parsed[0]).days
    if gap <= 8:
        return "weekly"
    if gap <= 17:
        return "biweekly"
    return "monthly"


def list_payment_plans(*, limit: int | None = None, offset: int | None = None) -> list[dict[str, Any]]:
    """Payment-plans table for the Promises screen; owner/cadence/start derived."""
    page, skip = clamp_list_limit(limit), clamp_offset(offset)
    with _db().engine.connect() as conn:
        plans = _rows(
            conn.execute(
                _sql(
                    """
                    SELECT pp.id, pp.customer_id, c.name AS customer_name, pp.account_id,
                           pp.total_amount, pp.created_at
                    FROM payment_plans pp
                    JOIN customers c ON c.id = pp.customer_id
                     AND c.tenant_id = :tenant_id
                     /*VISIBILITY*/
                    ORDER BY pp.created_at DESC, pp.id
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {"limit": page, "offset": skip, "tenant_id": _tenant(), **_vis_params()},
            )
        )
        if not plans:
            return []
        plan_ids = [p["id"] for p in plans]
        inst_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT plan_id, installment_index, due_date, amount, paid_status, paid_at
                    FROM promise_installments
                    WHERE plan_id = ANY(:ids)
                    ORDER BY plan_id, installment_index
                    """
                ),
                {"ids": plan_ids},
            )
        )
        owner_rows = _rows(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT ON (p.plan_id) p.plan_id, COALESCE(u.name, b.name) AS owner
                    FROM promises p
                    LEFT JOIN users u ON u.id = p.owner_user_id
                    LEFT JOIN bots b ON b.id = p.owner_bot_id
                    WHERE p.plan_id = ANY(:ids)
                    ORDER BY p.plan_id, p.created_at
                    """
                ),
                {"ids": plan_ids},
            )
        )
        owners = {r["plan_id"]: r["owner"] for r in owner_rows}
        by_plan: dict[str, list[dict[str, Any]]] = {}
        for r in inst_rows:
            by_plan.setdefault(r["plan_id"], []).append(r)

        now = utc_now()
        result = []
        for p in plans:
            installments = by_plan.get(p["id"], [])
            mapped = [
                {
                    "index": i["installment_index"],
                    "dueDate": i["due_date"],
                    "amount": i["amount"],
                    "paid": i["paid_status"] == "kept",
                    "paidOn": i["paid_at"],
                }
                for i in installments
            ]
            due_dates = [i["due_date"] for i in installments]
            all_paid = bool(mapped) and all(m["paid"] for m in mapped)
            overdue = any(
                (not m["paid"]) and datetime.fromisoformat(m["dueDate"]) < now for m in mapped
            )
            status = "completed" if all_paid else ("slipped" if overdue else "on_track")
            result.append(
                {
                    "id": p["id"],
                    "customerId": p["customer_id"],
                    "customerName": p["customer_name"],
                    "accountTail": _account_tail(p["account_id"]) or "",
                    "total": p["total_amount"],
                    "cadence": _plan_cadence(due_dates),
                    "startDate": min(due_dates) if due_dates else p["created_at"],
                    "installments": mapped,
                    "owner": owners.get(p["id"]) or "Unassigned",
                    "status": status,
                    "createdAt": p["created_at"],
                }
            )
        return result


def _promise_by_id(conn: Any, promise_id: str) -> dict[str, Any]:
    row = _one(conn.execute(text("SELECT customer_id FROM promises WHERE id = :id"), {"id": promise_id}))
    if row is None:
        raise KeyError("promise_not_found")
    for item in _promise_contracts(conn, row["customer_id"]):
        if item["id"] == promise_id:
            return {**item, "revisions": _promise_revisions(conn, promise_id)}
    raise KeyError("promise_not_found")


def create_promise(payload: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
    endpoint = "POST /promises"
    with _db().engine.begin() as conn:
        return _create_promise(conn, payload, idempotency_key, endpoint)


def _create_promise(
    conn: Any,
    payload: dict[str, Any],
    idempotency_key: str | None,
    endpoint: str,
) -> dict[str, Any]:
    """Connection-scoped body of :func:`create_promise`.

    Callers that already hold a transaction (payment plans, interaction wrap-up)
    must spawn the promise inside it. Re-entering ``_db().engine.begin()`` there took
    a second pooled connection and committed independently, so a failure in the
    caller's remaining work left an orphan promise the caller believed it had
    rolled back — and a retry then created a second one.
    """
    cached = _idempotent_response(conn, idempotency_key, endpoint)
    if cached:
        try:
            import promise_fulfillment

            pid = cached.get("id")
            if pid:
                fulfillment = promise_fulfillment.fulfill(conn, pid)
                cached = dict(cached)
                cached["_fulfillment"] = fulfillment.as_dict()
                cached["_spoken"] = fulfillment.spoken_summary
        except Exception:
            logger.exception("ptp fulfill on idempotent replay failed promise=%s", cached.get("id"))
        return cached
    customer_id = payload["customerId"]
    _ensure_customer(conn, customer_id)
    account_id = payload.get("accountId") or _first_account_id(conn, customer_id)
    if account_id:
        open_id = _open_promise_id(conn, account_id)
        if open_id:
            # One commitment per account. The open one travels with the
            # refusal so every client can offer "revise it" instead.
            raise ValueError(f"promise_already_open:{open_id}")
    amount, capped = _capped_amount(conn, account_id, payload["amount"])
    promise_id = _id("PTP")

    # Honour the chosen owner (human or bot); fall back to the acting user.
    owner_bot_id = payload.get("ownerBotId")
    owner_user_id = payload.get("ownerUserId")
    if owner_bot_id and owner_user_id:
        raise ValueError("provide either ownerUserId or ownerBotId, not both")
    if owner_bot_id:
        if not conn.execute(text("SELECT 1 FROM bots WHERE id = :id"), {"id": owner_bot_id}).fetchone():
            raise OwnerBotNotFound(f"bot_not_found: {owner_bot_id}")
        owner_kind = "bot"
    else:
        owner_user_id = owner_user_id or _actor_user_id()
        if not conn.execute(text("SELECT 1 FROM users WHERE id = :id"), {"id": owner_user_id}).fetchone():
            raise KeyError(f"user_not_found: {owner_user_id}")
        owner_kind = "human"

    conn.execute(
        text(
            """
            INSERT INTO promises
              (id, customer_id, account_id, interaction_id, owner_kind, owner_user_id,
               owner_bot_id, amount, promised_at, status, reminder_status, paid_amount, channel)
            VALUES
              (:id, :customer_id, :account_id, :interaction_id, :owner_kind, :owner_user_id,
               :owner_bot_id, :amount, :promised_at, 'upcoming', :reminder_status, 0, :channel)
            """
        ),
        {
            "id": promise_id,
            "customer_id": customer_id,
            "account_id": account_id,
            "interaction_id": payload.get("interactionId"),
            "owner_kind": owner_kind,
            "owner_user_id": owner_user_id if owner_kind == "human" else None,
            "owner_bot_id": owner_bot_id if owner_kind == "bot" else None,
            "amount": amount,
            "promised_at": clock.local_midnight(payload["promisedDate"]),
            "reminder_status": payload.get("reminderStatus") or "queued",
            "channel": payload.get("channel") or "voice",
        },
    )
    _activity(conn, "promise", promise_id, "promise_created", "Promise-to-pay captured", f"Amount {payload['amount']}", customer_id)
    fulfillment = None
    fulfillment_error: str | None = None
    try:
        import promise_fulfillment

        # A savepoint: a fulfiller that raised mid-statement used to abort the
        # caller's transaction, so the promise row -- inserted above, on the
        # same connection -- was lost with it while this function reported the
        # promise as created. The promise is the regulated record; the
        # reminder schedule is derived from it and may be retried.
        with conn.begin_nested():
            fulfillment = promise_fulfillment.fulfill(conn, promise_id)
    except Exception as exc:
        logger.exception("ptp fulfill failed promise=%s", promise_id)
        fulfillment_error = f"{type(exc).__name__}: {exc}"
    response = _promise_by_id(conn, promise_id)
    if capped:
        # The pay link can only ever collect the outstanding balance; a promise
        # for more than that was a figure `kept` could never reach.
        response["_capped"] = True
    if fulfillment is not None:
        response["_fulfillment"] = fulfillment.as_dict()
        response["_spoken"] = fulfillment.spoken_summary
    elif fulfillment_error:
        response["_fulfillment"] = {"error": fulfillment_error}
    _store_idempotent_response(conn, idempotency_key, endpoint, response)
    return response


#: kept is final; broken can still be kept (a late payment); partial can go
#: either way; cancelled and kept move nowhere. A new date is a revision.
_PROMISE_TRANSITIONS: dict[str, frozenset[str]] = {
    "upcoming": frozenset({"kept", "partial", "broken"}),
    "due_today": frozenset({"kept", "partial", "broken"}),
    "partial": frozenset({"kept", "broken"}),
    "broken": frozenset({"kept"}),
}

#: The `promise_revisions.reason` CHECK; the wire carries the same list.
REVISION_REASONS: tuple[str, ...] = (
    "customer_requested_delay",
    "salary_delayed",
    "medical",
    "dispute_raised",
    "partial_payment_agreed",
    "agent_correction",
    "other",
)

OPEN_STATUSES: tuple[str, ...] = ("upcoming", "due_today")


def _open_promise_id(conn: Any, account_id: str) -> str | None:
    """The account's one open commitment, if any (uq_promises_one_open)."""
    return conn.execute(
        text("SELECT id FROM promises WHERE account_id = :a AND status IN ('upcoming','due_today')"),
        {"a": account_id},
    ).scalar()


def _capped_amount(conn: Any, account_id: str | None, amount: Any) -> tuple[Any, bool]:
    """A promise cannot exceed what is owed: the pay link caps at outstanding
    (promise_fulfillment), and `kept` compared against the uncapped figure."""
    if not account_id:
        return amount, False
    outstanding = conn.execute(
        text("SELECT outstanding FROM accounts WHERE id = :a"), {"a": account_id}
    ).scalar()
    if outstanding is None or float(outstanding) <= 0 or float(amount) <= float(outstanding):
        return amount, False
    return float(outstanding), True


def _refulfil(conn: Any, promise_id: str, what: str) -> dict[str, Any] | None:
    """Re-derive the reminder and the pay link from the live promise, under a
    savepoint: the operator's edit is the record, the message a consequence."""
    import promise_fulfillment

    try:
        with conn.begin_nested():
            return promise_fulfillment.fulfill(conn, promise_id).as_dict()
    except Exception:
        logger.exception("promise %s re-fulfil failed promise=%s", what, promise_id)
        return None


def patch_promise(promise_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Settle a promise: kept, partial or broken, with what was paid.

    A new date or amount is not a patch -- it is a renegotiation with a
    reason, see :func:`revise_promise`; withdrawing it is :func:`cancel_promise`.
    """
    with _db().engine.begin() as conn:
        _assert_tenant_owns(conn, "promises", promise_id)
        row = _one(
            conn.execute(
                text("SELECT status, customer_id, amount, paid_amount FROM promises WHERE id = :id FOR UPDATE"),
                {"id": promise_id},
            )
        )
        if row is None:
            raise KeyError("promise_not_found")
        next_status = payload.get("status")
        assert_transition("promise", row["status"], next_status, _PROMISE_TRANSITIONS)
        if next_status == "kept":
            current_paid = float(row["paid_amount"] or 0)
            if current_paid < float(row["amount"] or 0):
                raise ValueError("kept_requires_payment")
        updates: list[str] = []
        params: dict[str, Any] = {"id": promise_id}
        if next_status and next_status != row["status"]:
            updates.append("status = :status")
            params["status"] = next_status
        if payload.get("paidAmount") is not None:
            updates.append("paid_amount = :paid_amount")
            params["paid_amount"] = payload["paidAmount"]
        if updates:
            conn.execute(text(f"UPDATE promises SET {', '.join(updates)} WHERE id = :id"), params)
        if next_status == "broken":
            conn.execute(
                text(
                    """
                    INSERT INTO followups (id, promise_id, customer_id, assignee_user_id, status, priority, due_at, note)
                    VALUES (:id, :promise_id, :customer_id, :assignee_user_id, 'open', 'high', now() + interval '1 day', 'Broken promise follow-up')
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {"id": f"FU-{promise_id}", "promise_id": promise_id, "customer_id": row["customer_id"], "assignee_user_id": _actor_user_id()},
            )
        _activity(conn, "promise", promise_id, "promise_updated", "Promise updated", next_status, row["customer_id"])
        return _promise_by_id(conn, promise_id)


def revise_promise(
    promise_id: str, payload: dict[str, Any], idempotency_key: str | None = None
) -> dict[str, Any]:
    """Renegotiate an open promise: a new date and/or amount, with the reason.

    The promise keeps its id, its reminders and its pay link -- all re-derived
    -- and the change is one row of history. Refused past the policy cap
    (`policy_rules.PTP_MAX_REVISIONS`): a date that keeps moving is a broken
    promise wearing a new one, and the desk has to decide something else.
    """
    import policy_rules

    endpoint = f"POST /promises/{promise_id}/revise"
    reason = str(payload.get("reason") or "")
    if reason not in REVISION_REASONS:
        raise ValueError(f"invalid_revision_reason:{reason}")
    with _db().engine.begin() as conn:
        cached = _idempotent_response(conn, idempotency_key, endpoint)
        if cached:
            return cached
        _assert_tenant_owns(conn, "promises", promise_id)
        row = _one(
            conn.execute(
                text(
                    "SELECT status, customer_id, account_id, amount, promised_at, revision_count "
                    "FROM promises WHERE id = :id FOR UPDATE"
                ),
                {"id": promise_id},
            )
        )
        if row is None:
            raise KeyError("promise_not_found")
        if row["status"] not in OPEN_STATUSES:
            raise ValueError(f"promise_not_open:{row['status']}")
        if int(row["revision_count"] or 0) >= policy_rules.PTP_MAX_REVISIONS:
            raise ValueError("promise_revision_cap")
        new_amount = row["amount"]
        capped = False
        if payload.get("amount") is not None:
            new_amount, capped = _capped_amount(conn, row["account_id"], payload["amount"])
        # _one stringifies timestamps; back to an instant for the compare.
        prior_at = datetime.fromisoformat(str(row["promised_at"]))
        new_at = clock.local_midnight(payload["promisedDate"]) if payload.get("promisedDate") else prior_at
        if float(new_amount) == float(row["amount"]) and new_at == prior_at:
            raise ValueError("nothing_to_revise")
        seq = int(row["revision_count"] or 0) + 1
        actor_kind, actor_user_id, actor_bot_id = _actor()
        conn.execute(
            text(
                """
                INSERT INTO promise_revisions
                  (id, promise_id, seq, prior_amount, prior_promised_at, amount, promised_at,
                   reason, note, actor_kind, actor_user_id, actor_bot_id, interaction_id)
                VALUES
                  (:id, :promise_id, :seq, :prior_amount, :prior_at, :amount, :at,
                   :reason, :note, :actor_kind, :actor_user_id, :actor_bot_id, :interaction_id)
                """
            ),
            {
                "id": _id("PRV"),
                "promise_id": promise_id,
                "seq": seq,
                "prior_amount": row["amount"],
                "prior_at": prior_at,
                "amount": new_amount,
                "at": new_at,
                "reason": reason,
                "note": (payload.get("note") or "").strip() or None,
                "actor_kind": actor_kind,
                "actor_user_id": actor_user_id,
                "actor_bot_id": actor_bot_id,
                "interaction_id": payload.get("interactionId"),
            },
        )
        # A moved date is upcoming again whatever the calendar said yesterday;
        # the settler re-derives due_today from promised_at.
        conn.execute(
            text(
                """
                UPDATE promises
                SET amount = :amount, promised_at = :at, revision_count = :seq, status = 'upcoming'
                WHERE id = :id
                """
            ),
            {"id": promise_id, "amount": new_amount, "at": new_at, "seq": seq},
        )
        label = f"Promise moved to {new_at.astimezone(clock.tenant_tz()).date().isoformat()} for {float(new_amount):.2f} ({reason})"
        _activity(conn, "promise", promise_id, "promise_revised", label, payload.get("note"), row["customer_id"])
        fulfillment = _refulfil(conn, promise_id, "revise")
        response = _promise_by_id(conn, promise_id)
        if capped:
            response["_capped"] = True
        if fulfillment is not None:
            response["_fulfillment"] = fulfillment
        _store_idempotent_response(conn, idempotency_key, endpoint, response)
        return response


def cancel_promise(promise_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Withdraw an open commitment with its reason; the account is free for a
    new one. Pending reminders stop and the open pay link is cancelled."""
    reason = str(payload.get("reason") or "")
    if reason not in REVISION_REASONS:
        raise ValueError(f"invalid_revision_reason:{reason}")
    with _db().engine.begin() as conn:
        _assert_tenant_owns(conn, "promises", promise_id)
        row = _one(
            conn.execute(
                text("SELECT status, customer_id FROM promises WHERE id = :id FOR UPDATE"), {"id": promise_id}
            )
        )
        if row is None:
            raise KeyError("promise_not_found")
        if row["status"] not in OPEN_STATUSES:
            raise ValueError(f"promise_not_open:{row['status']}")
        _actor_kind, actor_user_id, actor_bot_id = _actor()
        conn.execute(
            text(
                """
                UPDATE promises
                SET status = 'cancelled', cancel_reason = :reason, cancelled_at = now(),
                    cancelled_by = :by, reminder_status = 'off'
                WHERE id = :id
                """
            ),
            {"id": promise_id, "reason": reason, "by": actor_user_id or actor_bot_id},
        )
        conn.execute(
            text(
                "UPDATE promise_reminders SET status = 'off' "
                "WHERE promise_id = :id AND status IN ('queued','scheduled')"
            ),
            {"id": promise_id},
        )
        conn.execute(
            text(
                "UPDATE payment_intents SET status = 'cancelled' "
                "WHERE promise_id = :id AND status IN ('created','sent','opened')"
            ),
            {"id": promise_id},
        )
        _activity(
            conn, "promise", promise_id, "promise_cancelled", f"Promise cancelled ({reason})",
            payload.get("note"), row["customer_id"],
        )
        return _promise_by_id(conn, promise_id)


def _promise_revisions(conn: Any, promise_id: str) -> list[dict[str, Any]]:
    rows = _rows(
        conn.execute(
            text(
                """
                SELECT r.seq, r.prior_amount, r.prior_promised_at, r.amount, r.promised_at,
                       r.reason, r.note, r.actor_kind, r.created_at,
                       COALESCE(u.name, b.name) AS actor
                FROM promise_revisions r
                LEFT JOIN users u ON u.id = r.actor_user_id
                LEFT JOIN bots b ON b.id = r.actor_bot_id
                WHERE r.promise_id = :id
                ORDER BY r.seq
                """
            ),
            {"id": promise_id},
        )
    )
    return [
        {
            "seq": r["seq"],
            "priorAmount": r["prior_amount"],
            "priorPromisedDate": r["prior_promised_at"],
            "amount": r["amount"],
            "promisedDate": r["promised_at"],
            "reason": r["reason"],
            "note": r["note"],
            "actorKind": r["actor_kind"],
            "actor": r["actor"],
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def resend_promise_confirm(promise_id: str) -> dict[str, Any]:
    """Re-enqueue the written PTP confirm on the existing open intent."""
    import promise_fulfillment

    with _db().engine.begin() as conn:
        _assert_tenant_owns(conn, "promises", promise_id)
        result = promise_fulfillment.fulfill(conn, promise_id, resend=True)
        row = _promise_by_id(conn, promise_id)
        row["_fulfillment"] = result.as_dict()
        row["_spoken"] = result.spoken_summary
        return row


def create_payment_plan(payload: dict[str, Any]) -> dict[str, Any]:
    with _db().engine.begin() as conn:
        customer_id = payload["customerId"]
        _ensure_customer(conn, customer_id)
        account_id = payload.get("accountId") or _first_account_id(conn, customer_id)
        plan_id = _id("PLAN")
        conn.execute(
            text("INSERT INTO payment_plans (id, customer_id, account_id, total_amount) VALUES (:id, :customer_id, :account_id, :total_amount)"),
            {"id": plan_id, "customer_id": customer_id, "account_id": account_id, "total_amount": payload["totalAmount"]},
        )
        for idx, item in enumerate(payload.get("installments") or [], start=1):
            conn.execute(
                text(
                    """
                    INSERT INTO promise_installments (id, plan_id, installment_index, due_date, amount, paid_status)
                    VALUES (:id, :plan_id, :installment_index, :due_date, :amount, 'upcoming')
                    """
                ),
                {"id": f"{plan_id}-{idx}", "plan_id": plan_id, "installment_index": idx, "due_date": item["dueDate"], "amount": item["amount"]},
            )
        first = (payload.get("installments") or [{}])[0]
        # Same transaction as the plan and its installments: the first
        # instalment's promise is part of the plan, not an independently
        # committed row that survives a rollback of everything around it.
        promise = _create_promise(
            conn,
            {
                "customerId": customer_id,
                "accountId": account_id,
                "amount": first.get("amount", payload["totalAmount"]),
                "promisedDate": first.get("dueDate"),
                "channel": "voice",
            },
            None,
            "POST /promises",
        )
        conn.execute(text("UPDATE promises SET plan_id = :plan_id WHERE id = :id"), {"plan_id": plan_id, "id": promise["id"]})
        _activity(conn, "payment_plan", plan_id, "payment_plan_created", "Payment plan created", None, customer_id)
        return {"id": plan_id, "promise": _promise_by_id(conn, promise["id"])}
