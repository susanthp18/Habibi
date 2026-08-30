"""Recording when an attempt reached somebody.

One function, called from wherever a provider tells us what happened to a
message. It exists as its own module rather than as a helper inside the
WhatsApp path because the second caller is Twilio SMS and the third will be
email, and a receipt log that lives inside one channel's file is a receipt log
that acquires a second implementation the first time a channel is added.

**Never raises.** A receipt is evidence about a message that has already been
sent; losing one costs a training row. Letting the loss propagate would fail a
provider webhook, which makes the provider retry, which at scale is how a
delivery-status endpoint becomes an outage. The reach model would rather have a
gap than the system have a page.

**Append-only, and deduplicated on the provider's own id.** Meta and Twilio both
retry callbacks, so a replay is normal traffic rather than an anomaly. Without
the unique index a retried "read" is a second observation, and a reach model
counting it twice concludes that borrowers who happen to sit behind a flaky
webhook are unusually reachable.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

CHANNELS = frozenset({"whatsapp", "sms", "email", "voice"})
STATES = frozenset({"queued", "sent", "delivered", "read", "failed", "undelivered"})

#: Provider vocabulary → ours. Twilio and Meta describe the same lifecycle in
#: different words, and normalising at the edge means the reach trainer reads
#: one alphabet rather than learning both.
_TWILIO_STATES = {
    "queued": "queued",
    "accepted": "queued",
    "scheduled": "queued",
    "sending": "sent",
    "sent": "sent",
    "delivered": "delivered",
    # Twilio distinguishes "we could not deliver it" from "the carrier rejected
    # it". Both mean the borrower did not receive it, and both are kept apart
    # because only one of them says the number is wrong.
    "undelivered": "undelivered",
    "failed": "failed",
    # Read receipts exist for Twilio's WhatsApp channel, not for plain SMS.
    "read": "read",
}


def normalise_twilio(status: str | None) -> str | None:
    return _TWILIO_STATES.get((status or "").strip().lower())


def record(
    conn: Any,
    *,
    tenant_id: str,
    customer_id: str,
    channel: str,
    provider: str,
    state: str,
    provider_ref: str | None = None,
    message_id: str | None = None,
    related_id: str | None = None,
    reason: str | None = None,
    occurred_at: datetime | None = None,
) -> str | None:
    """Append one delivery transition. Returns its id, or None if it was a replay."""
    if channel not in CHANNELS or state not in STATES:
        logger.warning(
            "delivery receipt ignored: channel=%r state=%r", channel, state
        )
        return None

    event_id = f"CDE-{uuid.uuid4().hex[:12].upper()}"
    try:
        row = conn.execute(
            text(
                """
                INSERT INTO contact_delivery_events (
                  id, tenant_id, customer_id, channel, provider, provider_ref,
                  message_id, related_id, state, reason, occurred_at
                ) VALUES (
                  :id, :tenant_id, :customer_id, :channel, :provider, :provider_ref,
                  -- Resolved inside the INSERT: a message deleted between the
                  -- send and the receipt must null the column rather than lose
                  -- the receipt to a foreign-key error.
                  (SELECT m.id FROM messages m WHERE m.id = :message_id),
                  :related_id, :state, :reason, :occurred_at
                )
                ON CONFLICT DO NOTHING
                RETURNING id
                """
            ),
            {
                "id": event_id,
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "channel": channel,
                "provider": provider,
                "provider_ref": provider_ref,
                "message_id": message_id,
                "related_id": related_id,
                "state": state,
                "reason": (reason or None) and str(reason)[:500],
                "occurred_at": occurred_at or datetime.now(timezone.utc),
            },
        ).scalar()
        return str(row) if row else None
    except Exception:
        logger.exception(
            "delivery receipt failed customer=%s channel=%s state=%s",
            customer_id,
            channel,
            state,
        )
        return None
