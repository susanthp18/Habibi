"""The promotional sender: the only way an offer reaches a customer.

A scored offer is never spoken on a collections call (§9.7). It waits in the
decision log (``action_family='offer'``) until this drain delivers it on a separate, consented
channel. For each promotional decision still unsent it:

1. holds back a small, fixed comparison group (``RECO_PROMO_CONTROL_SHARE``)
   that is decided but never sent, so the lift of sending can be measured;
2. re-checks consent at send time through ``contact_policy.admit`` with
   ``data_purpose='promotional'`` (DND, promotional opt-in, windows, caps);
3. sends an approved WhatsApp marketing template when one is configured
   (``WHATSAPP_PROMO_TEMPLATE_NAME``), marking the offer presented once the
   provider accepts it; otherwise
4. hands it to a relationship manager as a ``qualified`` lead carrying the
   decision id, whose stage later labels the decision.

Runs only while the offer engine is live and the ``reco.enabled`` switch is on.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

SUPPRESS_CONTROL = "promo_control_group"
SEND_WINDOW_DAYS = 14


def _in_control(customer_id: str, share: float) -> bool:
    """Deterministic per customer, so the same person is always in or out."""
    digest = hashlib.blake2b(f"promo-control|{customer_id}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64 < share


def enabled() -> bool:
    from agent_core.reco import config

    if config.mode() != config.MODE_LIVE:
        return False
    try:
        import platform_switches

        return bool(platform_switches.is_enabled("reco.enabled"))
    except Exception:
        logger.exception("reco switch unreadable; not sending")
        return False


def _suppress(conn: Any, decision_id: str, reason: str) -> None:
    from agent_core.reco import decisions

    decisions.suppress(conn, decision_id, reason)


def process_one(engine: Any) -> bool:
    """Deliver one promotional offer. Returns whether there was one to handle."""
    if not enabled():
        return False
    from agent_core import engine_config

    import contact_policy

    share = engine_config.number("RECO_PROMO_CONTROL_SHARE", 0.10)
    with engine.begin() as conn:
        row = conn.execute(
            text(
                f"""
                SELECT d.id, d.tenant_id, d.customer_id, d.product_id AS chosen_product_id,
                       d.suggested_amount, p.name AS product_name, c.name AS customer_name,
                       c.phone_primary
                  FROM treatment_decisions d
                  JOIN products p ON p.id = d.product_id
                  JOIN customers c ON c.id = d.customer_id
                 WHERE d.action_family = 'offer' AND d.mode = 'live' AND d.product_id IS NOT NULL
                   AND d.presented IS FALSE AND d.offer_response IS NULL
                   AND d.suppression_reason IS NULL
                   AND d.features ->> 'context' = 'promotional'
                   AND d.created_at > now() - interval '{SEND_WINDOW_DAYS} days'
                   AND NOT EXISTS (SELECT 1 FROM leads l WHERE l.decision_id = d.id)
                   AND NOT EXISTS (SELECT 1 FROM whatsapp_outbound_jobs j WHERE j.decision_id = d.id)
                 ORDER BY d.created_at
                 LIMIT 1
                 FOR UPDATE OF d SKIP LOCKED
                """
            )
        ).mappings().first()
        if row is None:
            return False
        decision_id, customer_id = row["id"], row["customer_id"]
        if _in_control(customer_id, share):
            _suppress(conn, decision_id, SUPPRESS_CONTROL)
            return True
        template = (os.getenv("WHATSAPP_PROMO_TEMPLATE_NAME") or "").strip()
        by_message = bool(template and row["phone_primary"])
        # The channel the contact will actually use is the one charged: a
        # WhatsApp template, or a relationship manager's call.
        admitted = contact_policy.admit(
            conn,
            customer_id=customer_id,
            channel="whatsapp" if by_message else "voice",
            purpose="outreach",
            data_purpose="promotional",
            source="offer",
            related_id=decision_id,
            actor_kind="system" if by_message else "human",
            product_id=row["chosen_product_id"],
            endpoint=row["phone_primary"],
        )
        if admitted.allowed and by_message:
            import promise_fulfillment as pf

            pf.enqueue_whatsapp_paylink(
                conn,
                customer_id=customer_id,
                intent={"amount": row["suggested_amount"] or 0, "pay_url": ""},
                to_phone=row["phone_primary"],
                body=f"{row['product_name']}: an offer for you. Reply to know more.",
                use_template=True,
                purpose="promotional",
                source="offer",
                template_env_name="WHATSAPP_PROMO_TEMPLATE_NAME",
                template_env_lang="WHATSAPP_PROMO_TEMPLATE_LANG",
                template_params=[str(row["customer_name"] or ""), str(row["product_name"])],
                decision_id=decision_id,
            )
            return True
        if not admitted.allowed:
            _suppress(conn, decision_id, f"send:{admitted.reason}")
            return True
        # No approved marketing template: a person follows up instead, within
        # the same consent. The lead's stage labels the decision later.
        import db

        conn.execute(
            text(
                """
                INSERT INTO leads (id, customer_id, product_id, stage, source, priority,
                                   offer_amount, captured_at, decision_id)
                VALUES (:id, :c, :p, 'qualified', 'offer_engine', 'normal', :amt, now(), :d)
                """
            ),
            {"id": db._id("LEAD"), "c": customer_id, "p": row["chosen_product_id"],
             "amt": row["suggested_amount"], "d": decision_id},
        )
        return True


def label_from_lead(conn: Any, *, decision_id: str | None, stage: str) -> None:
    """A relationship manager's lead stage, as the offer's outcome."""
    from agent_core.reco import decisions

    if not decision_id:
        return
    if stage in {"contacted", "qualified"}:
        decisions.mark_presented(decision_id)
    elif stage in {"interested", "won"}:
        decisions.mark_presented(decision_id)
        decisions.record_response(decision_id, "interested")
    elif stage == "lost":
        decisions.mark_presented(decision_id)
        decisions.record_response(decision_id, "declined")
