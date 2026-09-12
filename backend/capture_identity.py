"""Identity outcomes on a live interaction: account-tail lookup, rebinding the customer, failed checks.

Carved from capture.py.
"""

from __future__ import annotations

import logging
from typing import Any
from sqlalchemy import text
from sqlalchemy.engine import Connection
from capture_events import _sid, emit_commercial_event

logger = logging.getLogger(__name__)


def find_customer_by_account_tail(conn: Connection, tail: str) -> dict[str, Any] | None:
    """Resolve customer by last-4 account digits — fail closed on ambiguity."""
    digits = "".join(ch for ch in (tail or "") if ch.isdigit())
    if len(digits) < 4:
        return None
    tail4 = digits[-4:]
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.name, c.phone_primary, a.id AS account_id
            FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE RIGHT(regexp_replace(a.id, '[^0-9]', '', 'g'), 4) = :tail
               OR RIGHT(a.id, 4) = :tail
            ORDER BY a.updated_at DESC NULLS LAST, a.id
            """
        ),
        {"tail": tail4},
    ).mappings().all()
    if not rows:
        return None
    # Distinct customers — multiple accounts for the same customer is fine.
    # Unbounded on purpose: a LIMIT here could truncate away the very row that
    # proves the tail is ambiguous, turning a fail-closed into a false match.
    customer_ids = {r["id"] for r in rows}
    if len(customer_ids) > 1:
        return None
    return dict(rows[0])


def rebind_interaction_customer(
    conn: Connection,
    *,
    interaction_id: str,
    customer_id: str,
    method: str = "phone_match",
    account_id: str | None = None,
    actor_bot_id: str | None = None,
    verification_status: str = "verified",
) -> dict[str, Any]:
    """Rebind interaction (+ linked conversation) to a verified customer."""
    if method not in {"phone_match", "dob", "otp", "account_tail", "manual"}:
        method = "manual"
    if verification_status not in {"verified", "pending", "failed"}:
        verification_status = "verified"

    cust = conn.execute(
        text("SELECT id, name FROM customers WHERE id = :id"),
        {"id": customer_id},
    ).mappings().first()
    if cust is None:
        raise KeyError("customer_not_found")

    ix = conn.execute(
        text("SELECT id, customer_id FROM interactions WHERE id = :id"),
        {"id": interaction_id},
    ).mappings().first()
    if ix is None:
        raise KeyError("interaction_not_found")

    if not account_id:
        acct = conn.execute(
            text(
                """
                SELECT id FROM accounts
                WHERE customer_id = :cid
                ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
        account_id = acct["id"] if acct else None

    # This used to read:
    #
    #   # Tail-only matches are never treated as full verification (pending).
    #   if method == "account_tail" and verification_status == "verified":
    #       verification_status = "pending"
    #
    # and it is why no WhatsApp conversation has ever passed a gate. The gate
    # required `status='verified'`; the only ceremony a customer can naturally
    # perform in a chat thread writes `account_tail`; so the ceremony wrote a row
    # that could never open the gate, and nothing anywhere said so.
    #
    # The instinct behind it was right and the mechanism was wrong. A tail on its
    # own IS weak. But `_tool_identify_customer` does not accept a tail on its
    # own: it requires the matched customer's phone to equal the thread's phone
    # (bot_tools.py), so by the time this is reached the caller has proved the
    # endpoint AND supplied a secret. Recording two factors as "pending" is not
    # caution, it is a wrong answer.
    #
    # Strength is now carried by `method`, which this row already stores, and
    # read as an assurance level by `agent_core.tools.gates`. `phone_match`
    # earns `endpoint`; `account_tail` / `dob` / `otp` earn `challenge`. Voice's
    # writer never had this downgrade, so the two channels also stop disagreeing
    # about what one method means.

    conn.execute(
        text(
            """
            UPDATE interactions
            SET customer_id = :cid,
                account_id = COALESCE(:aid, account_id),
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": interaction_id, "cid": customer_id, "aid": account_id},
    )
    conn.execute(
        text(
            """
            UPDATE conversations
            SET customer_id = :cid, updated_at = now()
            WHERE interaction_id = :iid
            """
        ),
        {"cid": customer_id, "iid": interaction_id},
    )

    vid = _sid("VER")
    conn.execute(
        text(
            """
            INSERT INTO identity_verifications (
              id, interaction_id, customer_id, method, status,
              attempt_count, verified_at, created_at, updated_at
            ) VALUES (
              :id, :iid, :cid, :method, :status,
              1, CASE WHEN :status = 'verified' THEN now() ELSE NULL END, now(), now()
            )
            """
        ),
        {
            "id": vid,
            "iid": interaction_id,
            "cid": customer_id,
            "method": method,
            "status": verification_status,
        },
    )
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="identity_verified" if verification_status == "verified" else "identity_partial",
        label=f"Identity {verification_status} | {method}",
        note=cust.get("name"),
        payload={
            "customerId": customer_id,
            "accountId": account_id,
            "method": method,
            "status": verification_status,
            "previousCustomerId": ix.get("customer_id"),
            "verificationId": vid,
        },
        actor_bot_id=actor_bot_id,
    )
    # Never return PII when verification is incomplete.
    if verification_status != "verified":
        return {
            "interactionId": interaction_id,
            "customerId": customer_id,
            "accountId": account_id,
            "method": method,
            "status": verification_status,
            "verificationId": vid,
        }
    return {
        "interactionId": interaction_id,
        "customerId": customer_id,
        "customerName": cust.get("name"),
        "accountId": account_id,
        "method": method,
        "status": verification_status,
        "verificationId": vid,
    }


def record_identity_failed(
    conn: Connection,
    *,
    interaction_id: str | None,
    reason: str,
    method: str = "phone_match",
    actor_bot_id: str | None = None,
) -> None:
    if not interaction_id:
        return
    emit_commercial_event(
        conn,
        entity_type="interaction",
        entity_id=interaction_id,
        kind="identity_failed",
        label=f"Identity failed | {method}",
        note=reason[:240],
        payload={"method": method, "reason": reason},
        actor_bot_id=actor_bot_id,
        tone="negative",
    )
