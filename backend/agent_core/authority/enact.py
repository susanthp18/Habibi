"""Post an in-policy goodwill waiver. Live mode only for the bot path.

The specialist path (``post_waiver_for_dispute``) is the disputes desk: a human
who chose ``valid_waive_fee`` after review. That path does not need live mode —
escalation *is* the review.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from agent_core.authority import config, decisions
from agent_core.authority.matrix import VERDICT_ESCALATE

logger = logging.getLogger(__name__)


class AuthorityError(ValueError):
    """Structured refusal the tool layer can return without raising to audio."""


def apply_goodwill(
    *,
    decision_id: str,
    amount: float | None = None,
    dispute_id: str | None = None,
    conn: Any | None = None,
    force_mode: str | None = None,
) -> dict[str, Any]:
    """Post the waiver the engine already approved. Live only."""
    mode = (force_mode or config.mode()).strip().lower()
    if mode != config.MODE_LIVE:
        raise AuthorityError("shadow_mode")

    def _run(c: Any) -> dict[str, Any]:
        row = c.execute(
            text(
                """
                SELECT id, customer_id, account_id, fee_type, verdict,
                       approved_amount, cap_amount, enacted, dispute_id
                FROM authority_decisions
                WHERE id = :id
                """
            ),
            {"id": decision_id},
        ).mappings().first()
        if row is None:
            raise AuthorityError("decision_not_found")
        if row["enacted"]:
            raise AuthorityError("already_applied")
        if row["verdict"] == VERDICT_ESCALATE:
            raise AuthorityError("verdict_escalate")
        cap = float(row["approved_amount"] or row["cap_amount"] or 0)
        if cap <= 0:
            raise AuthorityError("no_approved_amount")
        asked = float(amount) if amount is not None else cap
        if asked <= 0:
            raise AuthorityError("invalid_amount")
        if asked > cap + 0.009:
            raise AuthorityError("amount_above_cap")
        posted = min(asked, cap)

        account_id = row["account_id"]
        if not account_id:
            raise AuthorityError("account_missing")

        did = dispute_id or row["dispute_id"]
        return _post(
            c,
            account_id=account_id,
            customer_id=row["customer_id"],
            amount=posted,
            fee_type=row["fee_type"] or "late_fee",
            decision_id=decision_id,
            dispute_id=did,
        )

    if conn is not None:
        return _run(conn)
    import db

    with db.engine.begin() as owned:
        return _run(owned)


def post_waiver_for_dispute(
    conn: Any,
    *,
    dispute_id: str,
    amount: float | None = None,
    description: str | None = None,
) -> dict[str, Any] | None:
    """Specialist resolve path. Idempotent on dispute id."""
    existing = conn.execute(
        text(
            """
            SELECT id FROM ledger_entries
            WHERE description LIKE :pat
            LIMIT 1
            """
        ),
        {"pat": f"%{dispute_id}%"},
    ).first()
    if existing:
        return None

    row = conn.execute(
        text(
            """
            SELECT d.id, d.customer_id, d.account_id, d.disputed_amount, d.type
            FROM disputes d
            WHERE d.id = :id
            """
        ),
        {"id": dispute_id},
    ).mappings().first()
    if row is None:
        return None
    account_id = row["account_id"]
    if not account_id:
        return None
    posted = float(amount if amount is not None else (row["disputed_amount"] or 0))
    if posted <= 0:
        return None
    return _post(
        conn,
        account_id=account_id,
        customer_id=row["customer_id"],
        amount=posted,
        fee_type=row["type"] or "fee_waiver",
        decision_id=None,
        dispute_id=dispute_id,
        description=description or f"Goodwill waiver {dispute_id}",
    )


def _post(
    conn: Any,
    *,
    account_id: str,
    customer_id: str,
    amount: float,
    fee_type: str,
    decision_id: str | None,
    dispute_id: str | None,
    description: str | None = None,
) -> dict[str, Any]:
    import db

    ledger_id = db._id("LED")
    posted_at = datetime.now(timezone.utc)
    desc = description or (
        f"Goodwill {fee_type} waiver {decision_id or dispute_id or ''}".strip()
    )
    conn.execute(
        text(
            """
            INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
            VALUES (:id, :account_id, 'waiver', :description, :amount, :posted_at)
            """
        ),
        {
            "id": ledger_id,
            "account_id": account_id,
            "description": desc,
            "amount": float(-abs(amount)),
            "posted_at": posted_at,
        },
    )
    conn.execute(
        text(
            """
            UPDATE accounts
            SET outstanding = GREATEST(0, outstanding - :paid),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": account_id, "paid": float(abs(amount))},
    )

    resolved_dispute = dispute_id
    if not resolved_dispute:
        resolved_dispute = _open_or_create_fee_dispute(
            conn,
            customer_id=customer_id,
            account_id=account_id,
            amount=amount,
        )
    if resolved_dispute:
        conn.execute(
            text(
                """
                UPDATE disputes
                SET status = 'resolved',
                    resolution_code = 'valid_waive_fee',
                    resolution_notes = COALESCE(resolution_notes, :note)
                WHERE id = :id AND status NOT IN ('resolved', 'rejected')
                """
            ),
            {
                "id": resolved_dispute,
                "note": f"In-policy goodwill {ledger_id}",
            },
        )

    if decision_id:
        decisions.mark_enacted(
            decision_id,
            conn=conn,
            ledger_id=ledger_id,
            dispute_id=resolved_dispute,
        )

    db.record_activity(
        conn,
        "dispute" if resolved_dispute else "customer",
        resolved_dispute or customer_id,
        "dispute_updated",
        f"Goodwill waiver ₹{int(round(amount)):,}",
        desc,
        customer_id,
    )
    return {
        "ledgerId": ledger_id,
        "disputeId": resolved_dispute,
        "amount": float(abs(amount)),
        "accountId": account_id,
        "decisionId": decision_id,
    }


def _open_or_create_fee_dispute(
    conn: Any,
    *,
    customer_id: str,
    account_id: str,
    amount: float,
) -> str | None:
    open_row = conn.execute(
        text(
            """
            SELECT id FROM disputes
            WHERE customer_id = :cid
              AND type = 'fee_waiver'
              AND status NOT IN ('resolved', 'rejected')
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"cid": customer_id},
    ).mappings().first()
    if open_row:
        return open_row["id"]
    import db

    dispute_id = db._id("DSP")
    conn.execute(
        text(
            """
            INSERT INTO disputes (
              id, customer_id, account_id, type, disputed_amount, source,
              status, priority, resolution_code, resolution_notes
            ) VALUES (
              :id, :cid, :aid, 'fee_waiver', :amount, 'bot_voice',
              'resolved', 'normal', 'valid_waive_fee',
              'In-policy goodwill on the call'
            )
            """
        ),
        {
            "id": dispute_id,
            "cid": customer_id,
            "aid": account_id,
            "amount": amount,
        },
    )
    return dispute_id
