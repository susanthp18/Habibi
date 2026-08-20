"""Payment provider adapter + ledger settlement for PTP intents.

The LLM never talks to a PSP. Hosted mode is a public HTML page plus a
sandbox complete endpoint. Razorpay is an interface + env keys: when
configured, ``checkout_url`` can return the PSP link instead of ours.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from env_loader import load_env

logger = logging.getLogger(__name__)

IST = "Asia/Kolkata"
OPEN_PROMISE_STATUSES = ("upcoming", "due_today", "partial")


def _env(name: str, default: str = "") -> str:
    load_env()
    return (os.getenv(name) or default).strip()


def provider() -> str:
    raw = _env("PAYMENT_PROVIDER", "hosted").lower()
    return raw if raw in {"hosted", "razorpay"} else "hosted"


def app_env() -> str:
    return _env("APP_ENV", "dev").lower()


def is_production() -> bool:
    return app_env() in {"prod", "production"}


def public_base_url() -> str:
    base = _env("PUBLIC_BASE_URL") or "http://127.0.0.1:8000"
    return base.rstrip("/")


def checkout_url(public_token: str) -> str:
    """Hosted pay page, or a Razorpay checkout URL when keys exist."""
    if provider() == "razorpay" and _env("RAZORPAY_KEY_ID") and _env("RAZORPAY_KEY_SECRET"):
        # Keys present but link creation is not wired — fall back to hosted
        # until the live Razorpay order API is configured. The intent still
        # records provider='razorpay' so webhooks can match.
        logger.info("PAYMENT_PROVIDER=razorpay but checkout creation is stubbed; using hosted URL")
    return f"{public_base_url()}/pay/{public_token}"


def webhook_secret(provider_name: str | None = None) -> str:
    name = (provider_name or provider()).lower()
    if name == "razorpay":
        return _env("RAZORPAY_WEBHOOK_SECRET") or _env("PAYMENT_WEBHOOK_SECRET")
    return _env("PAYMENT_WEBHOOK_SECRET")


def verify_webhook_signature(
    *,
    provider_name: str,
    raw_body: bytes,
    header: str | None,
) -> bool:
    secret = webhook_secret(provider_name)
    if not secret or not header:
        return False
    provided = header.strip()
    if provided.lower().startswith("sha256="):
        provided = provided[7:]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def parse_webhook_payload(provider_name: str, body: dict[str, Any]) -> dict[str, Any]:
    """Map a provider payload to ``{intent_id|public_token, amount, provider_ref}``."""
    name = (provider_name or "").strip().lower()
    if name == "razorpay":
        payload = body.get("payload") or body
        entity = (payload.get("payment") or payload.get("payment_link") or payload).get("entity") or payload
        notes = entity.get("notes") or {}
        amount_paise = entity.get("amount")
        amount = None
        if amount_paise is not None:
            try:
                amount = float(Decimal(str(amount_paise)) / Decimal("100"))
            except Exception:
                amount = None
        return {
            "intent_id": notes.get("intent_id") or entity.get("notes", {}).get("intent_id"),
            "public_token": notes.get("public_token"),
            "amount": amount,
            "provider_ref": entity.get("id") or entity.get("payment_id"),
        }
    return {
        "intent_id": body.get("intent_id") or body.get("intentId"),
        "public_token": body.get("public_token") or body.get("token"),
        "amount": body.get("amount"),
        "provider_ref": body.get("provider_ref") or body.get("providerRef"),
    }


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def record_payment(
    conn: Any,
    *,
    intent_id: str | None = None,
    public_token: str | None = None,
    amount: Any,
    provider_ref: str | None = None,
) -> dict[str, Any]:
    """Post a ledger payment, mark the intent paid, allocate to open PTPs.

    Ledger payments are stored as **negative** amounts (seed convention).
    Allocation is oldest ``promised_at`` first on the same account.
    """
    paid = _money(amount)
    if paid <= 0:
        raise ValueError("invalid_payment_amount")

    if intent_id:
        intent = conn.execute(
            text("SELECT * FROM payment_intents WHERE id = :id FOR UPDATE"),
            {"id": intent_id},
        ).mappings().first()
    elif public_token:
        intent = conn.execute(
            text("SELECT * FROM payment_intents WHERE public_token = :token FOR UPDATE"),
            {"token": public_token},
        ).mappings().first()
    else:
        raise ValueError("intent_not_specified")
    if intent is None:
        raise KeyError("payment_intent_not_found")

    if intent["status"] == "paid":
        return {"ok": True, "intentId": intent["id"], "status": "paid", "idempotent": True}
    if intent["status"] in {"expired", "cancelled"}:
        raise ValueError(f"intent_{intent['status']}")

    expires = intent.get("expires_at")
    if expires is not None:
        exp = expires if getattr(expires, "tzinfo", None) else expires.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            conn.execute(
                text("UPDATE payment_intents SET status = 'expired' WHERE id = :id AND status <> 'paid'"),
                {"id": intent["id"]},
            )
            raise ValueError("intent_expired")

    import db as dbmod

    ledger_id = dbmod._id("LED")
    posted = datetime.now(timezone.utc)
    conn.execute(
        text(
            """
            INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
            VALUES (:id, :account_id, 'payment', :description, :amount, :posted_at)
            """
        ),
        {
            "id": ledger_id,
            "account_id": intent["account_id"],
            "description": f"PTP payment {intent['id']}",
            "amount": float(-paid),
            "posted_at": posted,
        },
    )
    conn.execute(
        text(
            """
            UPDATE accounts
            SET outstanding = GREATEST(0, outstanding - :paid)
            WHERE id = :id
            """
        ),
        {"id": intent["account_id"], "paid": float(paid)},
    )
    conn.execute(
        text(
            """
            UPDATE payment_intents
            SET status = 'paid',
                paid_at = :paid_at,
                ledger_entry_id = :ledger_id,
                provider_ref = COALESCE(:provider_ref, provider_ref)
            WHERE id = :id
            """
        ),
        {
            "id": intent["id"],
            "paid_at": posted,
            "ledger_id": ledger_id,
            "provider_ref": provider_ref,
        },
    )

    allocated = allocate_to_promises(
        conn,
        account_id=intent["account_id"],
        amount=paid,
        preferred_promise_id=intent.get("promise_id"),
    )
    cured: list[str] = []
    try:
        import payment_events as pe

        preferred_emi = None
        peid = intent.get("payment_event_id")
        if peid:
            ev = conn.execute(
                text("SELECT emi_installment_id FROM payment_events WHERE id = :id"),
                {"id": peid},
            ).mappings().first()
            if ev:
                preferred_emi = ev["emi_installment_id"]
        cured = pe.cure_for_account(
            conn,
            account_id=intent["account_id"],
            amount=paid,
            preferred_emi_id=preferred_emi,
            intent_id=intent["id"],
        )
    except Exception:
        logger.exception("bounce cure failed account=%s", intent["account_id"])
    _close_treatment_cases(conn, bounce_ids=cured, promises=allocated)
    return {
        "ok": True,
        "intentId": intent["id"],
        "status": "paid",
        "ledgerEntryId": ledger_id,
        "allocated": allocated,
        "curedEvents": cured,
    }


def _close_treatment_cases(
    conn: Any,
    *,
    bounce_ids: list[str],
    promises: list[dict[str, Any]],
) -> None:
    """Retire scheduled treatments for anything this payment settled.

    The worst thing a collections system can do is ring somebody about a debt
    they have already paid, and a plan scheduled for 18:00 does not know about a
    payment received at 15:00 unless something tells it. Never raises: a
    payment must record even if the cleanup does not.
    """
    try:
        from agent_core.treatment import followthrough

        for event_id in bounce_ids or []:
            followthrough.resolve_case(
                conn, trigger_kind="bounce", trigger_ref=event_id, outcome="paid"
            )
        for row in promises or []:
            if str(row.get("status")) not in {"kept", "partial"}:
                continue
            followthrough.resolve_case(
                conn,
                trigger_kind="broken_ptp",
                trigger_ref=str(row.get("promiseId") or row.get("id") or ""),
                outcome="paid",
            )
    except Exception:
        logger.exception("closing treatment cases after payment failed")


def allocate_to_promises(
    conn: Any,
    *,
    account_id: str,
    amount: Decimal,
    preferred_promise_id: str | None = None,
) -> list[dict[str, Any]]:
    """Apply a positive rupee amount to open promises, oldest first.

    The intent's own promise is preferred when it is still open, then the rest
    of the account's queue. Never moves a ``kept`` promise.
    """
    remaining = _money(amount)
    rows = conn.execute(
        text(
            """
            SELECT id, amount, paid_amount, status, customer_id
            FROM promises
            WHERE account_id = :account_id
              AND status = ANY(:statuses)
            ORDER BY
              CASE WHEN id = :preferred THEN 0 ELSE 1 END,
              promised_at ASC,
              created_at ASC
            FOR UPDATE
            """
        ),
        {
            "account_id": account_id,
            "statuses": list(OPEN_PROMISE_STATUSES),
            "preferred": preferred_promise_id,
        },
    ).mappings().all()

    applied: list[dict[str, Any]] = []
    for row in rows:
        if remaining <= 0:
            break
        promised = _money(row["amount"])
        already = _money(row["paid_amount"])
        need = promised - already
        if need <= 0:
            continue
        take = min(need, remaining)
        new_paid = already + take
        if new_paid >= promised:
            next_status = "kept"
        else:
            next_status = "partial"
        conn.execute(
            text(
                """
                UPDATE promises
                SET paid_amount = :paid_amount, status = :status
                WHERE id = :id
                """
            ),
            {"id": row["id"], "paid_amount": float(new_paid), "status": next_status},
        )
        import db as dbmod

        dbmod.record_activity(
            conn,
            "promise",
            row["id"],
            "promise_payment",
            f"Payment of ₹{take} allocated",
            next_status,
            row["customer_id"],
        )
        applied.append(
            {
                "promiseId": row["id"],
                "applied": float(take),
                "paidAmount": float(new_paid),
                "status": next_status,
            }
        )
        remaining -= take
    return applied


def load_intent_by_token(conn: Any, token: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT pi.*, c.name AS customer_name, t.name AS tenant_name,
                   a.id AS account_id, a.outstanding
            FROM payment_intents pi
            JOIN customers c ON c.id = pi.customer_id
            JOIN tenants t ON t.id = pi.tenant_id
            JOIN accounts a ON a.id = pi.account_id
            WHERE pi.public_token = :token
            """
        ),
        {"token": token},
    ).mappings().first()
    return dict(row) if row else None


def mark_opened(conn: Any, intent_id: str) -> None:
    conn.execute(
        text(
            """
            UPDATE payment_intents
            SET status = 'opened'
            WHERE id = :id AND status IN ('created','sent')
            """
        ),
        {"id": intent_id},
    )


def render_pay_page(intent: dict[str, Any]) -> str:
    from html import escape

    tenant = escape(str(intent.get("tenant_name") or "Collections"))
    amount = escape(f"{float(intent.get('amount') or 0):,.2f}")
    account = str(intent.get("account_id") or "")
    tail = escape(account[-4:] if len(account) >= 4 else account)
    status = escape(str(intent.get("status") or ""))
    expires = intent.get("expires_at")
    expiry = ""
    if expires is not None:
        exp = expires if getattr(expires, "tzinfo", None) else expires.replace(tzinfo=timezone.utc)
        expiry = escape(exp.astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC"))
    paid = status == "paid"
    expired = status == "expired"
    heading = "Payment received" if paid else ("This link has expired" if expired else "Pay your promised amount")
    action = ""
    if not paid and not expired and not is_production() and provider() == "hosted":
        token = escape(str(intent.get("public_token") or ""))
        action = f"""
        <form method="post" action="/pay/{token}/complete">
          <button type="submit">Mark paid (sandbox)</button>
        </form>
        <p class="note">Sandbox only. Production uses a payment gateway webhook.</p>
        """
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Pay {tenant}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0;
           display: flex; min-height: 100vh; align-items: center; justify-content: center; margin: 0; }}
    .card {{ background: #1e293b; border-radius: 16px; padding: 2rem; max-width: 28rem; width: 90%; }}
    h1 {{ font-size: 1.25rem; margin: 0 0 0.5rem; }}
    .amt {{ font-size: 2rem; font-weight: 700; margin: 1rem 0; }}
    .meta {{ color: #94a3b8; font-size: 0.9rem; line-height: 1.5; }}
    button {{ background: #22c55e; color: #052e16; border: 0; border-radius: 8px;
              padding: 0.75rem 1.25rem; font-weight: 600; cursor: pointer; width: 100%; }}
    .note {{ color: #64748b; font-size: 0.8rem; margin-top: 0.75rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{heading}</h1>
    <div class="meta">{tenant} · account ending {tail}</div>
    <div class="amt">₹{amount}</div>
    <div class="meta">UPI / net-banking amount as shown. Status: {status}{" · expires " + expiry if expiry else ""}</div>
    {action}
  </div>
</body>
</html>
"""
