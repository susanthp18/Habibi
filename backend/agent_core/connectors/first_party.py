"""First-party connectors: pay-link status and LMS balance. Real CRM rows."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

import db
from agent_core.connectors.strip import strip_result

PAYLINK_SLUG = "paylink"
LMS_SLUG = "lms"

FIRST_PARTY_TOOLS = {
    "ext.paylink.get_status": PAYLINK_SLUG,
    "ext.lms.get_balance": LMS_SLUG,
}


def paylink_status(customer_id: str) -> dict[str, Any]:
    """Latest pay-link status for a customer *in the caller's tenant*.

    The read is tenant-scoped like every other CRM read behind a connector
    (``lms_balance`` gets it from ``db.get_customer``). RLS is opt-in and the
    app connects as BYPASSRLS, so a bare ``customer_id`` predicate made a
    cross-tenant id return that tenant's payment status.
    """
    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT pi.status, pi.amount, pi.paid_at, pi.provider_ref, pi.id
                      FROM payment_intents pi
                      JOIN customers c ON c.id = pi.customer_id
                     WHERE pi.customer_id = :cid
                       AND c.tenant_id = :t
                       AND pi.tenant_id = :t
                     ORDER BY pi.created_at DESC NULLS LAST
                     LIMIT 1
                    """
                ),
                {"cid": customer_id, "t": db._tenant()},
            )
        )
    if not row:
        return strip_result({"ok": True, "status": "none"})
    status = str(row.get("status") or "")
    paid = status.lower() in {"paid", "success", "captured"}
    return strip_result(
        {
            "ok": True,
            "status": "paid" if paid else status or "pending",
            "amount": row.get("amount"),
            "paidAt": str(row["paid_at"]) if row.get("paid_at") else None,
            "providerRef": row.get("provider_ref"),
            "say": "We see the UPI success." if paid else None,
        }
    )


def lms_balance(customer_id: str) -> dict[str, Any]:
    customer = db.get_customer(customer_id)
    if not customer:
        return strip_result({"ok": False, "error": "customer_not_found"})
    return strip_result(
        {
            "ok": True,
            "outstanding": customer.get("outstanding"),
            "accountId": customer.get("accountId"),
            "currency": "INR",
        }
    )


def dispatch_first_party(name: str, customer_id: str) -> dict[str, Any]:
    if name == "ext.paylink.get_status":
        return paylink_status(customer_id)
    if name == "ext.lms.get_balance":
        return lms_balance(customer_id)
    return strip_result({"ok": False, "error": "unknown_first_party_tool"})
