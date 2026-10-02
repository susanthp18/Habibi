"""The WhatsApp webhook as the inbox ingests it: the borrower behind a phone,
the conversation a message opens, the message row, the delivery status. Carved
out of db_inbox; ``process_whatsapp_webhook`` is the entry.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from db_core import (
    _activity,
    _id,
    _one,
    _rows,
    _tenant,
)
from pg_errors import is_unique_violation as _is_unique_violation
from agent_core.clock import utc_now

logger = logging.getLogger(__name__)


def _db():
    """The ``db`` module object, resolved at call time: tests route
    ``db.engine`` through a savepoint proxy by setattr on the module."""
    import db as d

    return d


def _engine():
    return _db().engine


def _digits_phone_exact_sql() -> str:
    """The exact match runs on the HMAC of the normalised digits, so the index
    on customers_pii answers it without decrypting the book (sql/01_pii)."""
    return """
      c.phone_primary_hmac = pii_phone_hmac(:phone)
      OR c.phone_alt_hmac = pii_phone_hmac(:phone)
    """


def _digits_phone_tail10_sql() -> str:
    """Legacy local-format fallback, restricted to a bare 10-digit national number.

    A plain last-10 comparison matched across country codes: a stored
    ``+91 98765 43210`` and an inbound ``+1 98765 43210`` share their last ten
    digits and resolved to the same customer. A bare "is a suffix of" test is
    no better — ``19876543210`` really is a suffix of ``919876543210``.

    The only shape this fallback exists for is a legacy row stored as the bare
    10-digit national number, so that is exactly what it allows: the shorter
    side must be 10 digits and must be the tail of the longer one. Anything
    with two different country codes has a shorter side of 11+ and cannot match.
    """
    return " OR ".join(_tail10_predicate(col) for col in ("c.phone_primary", "c.phone_alt"))


def _tail10_predicate(column: str) -> str:
    digits = f"regexp_replace(COALESCE({column}, ''), '[^0-9]', '', 'g')"
    return f"""
      (
        length({digits}) >= 10
        AND least(length({digits}), length(:phone)) = 10
        AND (
          {digits} = right(:phone, 10)
          OR :phone = right({digits}, 10)
        )
      )
    """


#: Which of the customer's numbers, as the record stands now, last wrote on
#: the thread (``i`` its interaction, ``c`` its customer). NULL when that
#: number is no longer on the record: a WhatsApp service window belongs to the
#: number that opened it, and an edited phone must not inherit it.
REPLY_SLOT_SQL = """
  CASE i.source_payload->>'endpoint_hmac'
    WHEN encode(c.phone_primary_hmac, 'hex') THEN 'primary'
    WHEN encode(c.phone_alt_hmac, 'hex') THEN 'alt'
  END
"""


class AmbiguousSender(Exception):
    """More than one customer is on file at this number."""


def _match_customer_by_phone(conn: Any, phone: str) -> dict[str, Any] | None:
    """The one customer at this number, with ``endpoint_slot`` naming which of
    their numbers it is; None for nobody; :class:`AmbiguousSender` for several.

    Several is a refusal, never a pick. The exact branch used to log a warning
    and take the most recently updated row, which filed the conversation -- and
    the endpoint assurance that lets the bot act on it -- against a borrower
    the sender may not be.
    """
    # Digits only: the tail fallback embeds :phone in a LIKE pattern, so a `%`
    # or `_` surviving from a caller that skipped normalisation would turn the
    # suffix match back into a wildcard scan.
    phone = re.sub(r"\D+", "", phone or "")
    if len(phone) < 10:
        return None
    for predicate, slot in (
        (_digits_phone_exact_sql(), "CASE WHEN c.phone_primary_hmac = pii_phone_hmac(:phone) THEN 'primary' ELSE 'alt' END"),
        (_digits_phone_tail10_sql(), f"CASE WHEN {_tail10_predicate('c.phone_primary')} THEN 'primary' ELSE 'alt' END"),
    ):
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT id, name, phone_primary, phone_alt, {slot} AS endpoint_slot
                    FROM customers c
                    WHERE {predicate}
                    ORDER BY c.id
                    LIMIT 2
                    """
                ),
                {"phone": phone},
            )
        )
        if len(rows) > 1:
            logger.warning("phone …%s matches more than one customer — failing closed", phone[-4:])
            raise AmbiguousSender()
        if rows:
            return rows[0]
    return None


def _find_customer_by_phone(conn: Any, phone: str) -> dict[str, Any] | None:
    try:
        return _match_customer_by_phone(conn, phone)
    except AmbiguousSender:
        return None


def find_customer_by_phone(phone: str) -> dict[str, Any] | None:
    """Public wrapper — PSTN / WhatsApp caller identity resolution."""
    digits = re.sub(r"\D+", "", phone or "")
    if not digits:
        return None
    with _engine().connect() as conn:
        return _find_customer_by_phone(conn, digits)


def _ensure_whatsapp_customer(
    conn: Any, phone: str, profile_name: str | None
) -> tuple[dict[str, Any], bool]:
    """The customer behind this number, and whether we *recognised* them.

    The flag matters. Matching an inbound number to a borrower already on the
    books means Meta has verified that the sender controls that number and we
    have matched it to a CRM row — that is a proof of endpoint, and it is what
    lets a WhatsApp thread do anything at all without first asking the customer
    to recite a number we are already messaging them on.

    Inventing a ``cust-wa-`` stub for an unknown number proves nothing, and must
    not be confused with it. A number several borrowers share is filed on that
    unrecognised stub too: a person resolves who wrote, the bot does not guess.
    """
    try:
        existing = _match_customer_by_phone(conn, phone)
    except AmbiguousSender:
        existing = None
    if existing:
        return existing, True
    # Derive the ids from the FULL normalized number. Keying on the last 10 (or
    # 6) digits collided across country codes — +91 98765 43210 and +1 987 654
    # 3210 both produced cust-wa-9876543210 — and the DO UPDATE below then
    # overwrote the first person's phone and name with the second's, merging two
    # customers into one record.
    customer_id = f"cust-wa-{phone}" if phone else _id("cust-wa").lower()
    account_id = f"AC-WA-{phone}" if phone else _id("AC")
    name = (profile_name or f"WhatsApp {phone[-4:]}").strip() or f"WhatsApp {phone[-4:]}"
    conn.execute(
        text(
            """
            -- The base table, not the view: ON CONFLICT is unsupported on a
            -- view with INSTEAD OF triggers, so this writer encrypts itself
            -- through the same functions the view's trigger uses (sql/01_pii).
            INSERT INTO customers_pii
              (id, tenant_id, assigned_user_id, name, phone_primary_enc, phone_primary_hmac,
               risk, preferred_window, dnd, segment)
            VALUES
              (:id, :tenant_id, NULL, :name, pii_encrypt(:phone), pii_phone_hmac(:phone),
               'medium', NULL, false, 'retail')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": customer_id, "tenant_id": _tenant(), "name": name, "phone": phone},
    )
    # Prefer personal-loan if present, else any product.
    product = _one(conn.execute(text("SELECT id FROM products WHERE id = 'personal-loan'")))
    if product is None:
        product = _one(conn.execute(text("SELECT id FROM products ORDER BY id LIMIT 1")))
    if product is None:
        raise ValueError("no_products_seeded")
    conn.execute(
        text(
            """
            INSERT INTO accounts (id, customer_id, product_id, outstanding, dpd, status)
            VALUES (:id, :customer_id, :product_id, 0, 0, 'active')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": account_id, "customer_id": customer_id, "product_id": product["id"]},
    )
    # By id: once a stub exists for a shared number, a phone lookup is
    # ambiguous by construction.
    found = _one(
        conn.execute(
            text(
                "SELECT id, name, phone_primary, phone_alt, 'primary' AS endpoint_slot "
                "FROM customers WHERE id = :id"
            ),
            {"id": customer_id},
        )
    )
    if found is None:
        raise ValueError("customer_create_failed")
    return found, False


def _record_endpoint_assurance(conn: Any, conversation_id: str, customer_id: str) -> None:
    """Record that this thread reached a number the borrower is known at.

    One row per interaction, written the first time we recognise the sender.
    ``phone_match`` reads as the ``endpoint`` assurance level in
    ``agent_core.tools.gates`` — enough for reads, a note or a callback; not
    enough for a promise to pay, which still needs the customer to tell us
    something only they know.

    Before this, ``identity_verifications`` had never received a single row from
    the text channel: every row in the live table came from a voice call. Two
    things followed. Every gated tool was refused on WhatsApp forever, and the
    containment funnel in ``db_bot_analytics`` — whose ``verified`` stage every
    later stage is a subset of — reported 0% for every WhatsApp interaction and
    collapsed everything below it.

    Analytics and gating both read this table, so it is written inside the
    ingest transaction rather than deferred: a turn must never be able to run
    against an assurance row that has not committed.
    """
    ix = _one(
        conn.execute(
            text("SELECT interaction_id FROM conversations WHERE id = :id"),
            {"id": conversation_id},
        )
    )
    interaction_id = (ix or {}).get("interaction_id")
    if not interaction_id:
        return
    conn.execute(
        text(
            """
            INSERT INTO identity_verifications (
              id, interaction_id, customer_id, method, status,
              attempt_count, verified_at, created_at, updated_at
            )
            SELECT :id, :iid, :cid, 'phone_match', 'verified', 1, now(), now(), now()
            WHERE NOT EXISTS (
              SELECT 1 FROM identity_verifications
               WHERE interaction_id = :iid AND customer_id = :cid
                 AND method = 'phone_match' AND status = 'verified'
            )
            """
        ),
        {"id": _id("IDV"), "iid": interaction_id, "cid": customer_id},
    )


def whatsapp_bot_id(conn: Any) -> str:
    """The bot a WhatsApp thread is filed under: the Voice Studio agent bound to
    WhatsApp -- the one that answers it (whatsapp_studio) -- or the unnamed
    Voice Studio agent when none is bound yet, in which case a person answers."""
    import voice_studio

    agent = voice_studio.agent_for(conn, "whatsapp", allow_default=False)
    return voice_studio.ensure_bot(conn, agent["engine_workflow_id"] if agent else None)


def _open_whatsapp_conversation(conn: Any, customer_id: str) -> str:
    """Return an existing WhatsApp conversation for the customer, or create one (status=bot).

    Serialised per customer: two first messages arriving together both read
    "no thread" and both inserted one, and the customer's history split
    across two rows the Inbox showed as two people. The lock is
    transaction-scoped, so the second webhook waits for the first commit and
    then finds the thread. (A unique index would say the same thing, but the
    live data already carries the split threads that race produced, so the
    writer is fixed first and the index waits for a dedupe.)
    """
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"whatsapp-thread:{_tenant()}:{customer_id}"},
    )
    row = _one(
        conn.execute(
            text(
                """
                SELECT id FROM conversations
                WHERE customer_id = :customer_id AND channel = 'whatsapp'
                ORDER BY COALESCE(updated_at, created_at) DESC, id
                LIMIT 1
                """
            ),
            {"customer_id": customer_id},
        )
    )
    if row:
        return row["id"]

    account = _one(
        conn.execute(
            text(
                """
                SELECT id FROM accounts
                WHERE customer_id = :customer_id
                ORDER BY created_at, id
                LIMIT 1
                """
            ),
            {"customer_id": customer_id},
        )
    )
    bot = {"id": whatsapp_bot_id(conn)}

    interaction_id = _id("IX")
    conversation_id = _id("CV")
    now = utc_now()
    conn.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, account_id, handler_kind, handler_bot_id,
               channel, direction, status, sentiment_label, avg_sentiment, started_at, source_payload)
            VALUES
              (:id, :tenant_id, :customer_id, :account_id, 'bot', :bot_id,
               'whatsapp', 'inbound', 'active', 'neutral', 0, :started_at, CAST(:payload AS jsonb))
            """
        ),
        {
            "id": interaction_id,
            "tenant_id": _tenant(),
            "customer_id": customer_id,
            "account_id": account["id"] if account else None,
            "bot_id": bot["id"],
            "started_at": now,
            "payload": "{}",
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO conversations
              (id, interaction_id, customer_id, assigned_user_id, status, channel, created_at, updated_at)
            VALUES
              (:id, :interaction_id, :customer_id, NULL, 'bot', 'whatsapp', :now, :now)
            """
        ),
        {
            "id": conversation_id,
            "interaction_id": interaction_id,
            "customer_id": customer_id,
            "now": now,
        },
    )
    return conversation_id


def touch_interaction_sentiment(
    conn: Any,
    interaction_id: str | None,
    text_value: str,
    *,
    score: float | None = None,
) -> None:
    """Public alias for _touch_interaction_sentiment (see record_activity)."""
    _touch_interaction_sentiment(conn, interaction_id, text_value, score=score)


def _touch_interaction_sentiment(
    conn: Any,
    interaction_id: str | None,
    text_value: str,
    *,
    score: float | None = None,
) -> None:
    """Blend latest customer-turn sentiment into the linked interaction (Inbox header).

    ``score`` lets a caller that has already classified the turn pass its result
    in rather than have the English lexicon re-derive one from the raw text —
    which on a Hindi or code-switched turn returns 0.00 regardless of what was
    said. The webhook ingest path deliberately does not pass it: it runs inside
    the inbound request transaction, where an Azure call risks provider
    redelivery, and bot_worker re-touches the same interaction moments later
    with the enriched score.
    """
    if not interaction_id:
        return
    from agent_core.sentiment import estimate_sentiment, sentiment_label

    score = estimate_sentiment(text_value) if score is None else float(score)
    row = _one(
        conn.execute(
            text("SELECT avg_sentiment FROM interactions WHERE id = :id"),
            {"id": interaction_id},
        )
    )
    if row is None:
        return
    prev = row.get("avg_sentiment")
    try:
        prev_f = float(prev) if prev is not None else None
    except (TypeError, ValueError):
        prev_f = None
    blended = score if prev_f is None else round(0.35 * prev_f + 0.65 * score, 3)
    label = sentiment_label(blended)
    conn.execute(
        text(
            """
            UPDATE interactions
            SET avg_sentiment = :avg,
                sentiment_label = :label
            WHERE id = :id
            """
        ),
        {"id": interaction_id, "avg": blended, "label": label},
    )


def _ingest_inbound_whatsapp_message(
    conn: Any,
    *,
    wa_message_id: str,
    from_phone: str,
    body: str,
    profile_name: str | None,
    sent_at: datetime,
) -> dict[str, Any]:
    customer, recognised = _ensure_whatsapp_customer(conn, from_phone, profile_name)
    conversation_id = _open_whatsapp_conversation(conn, customer["id"])
    if recognised:
        _record_endpoint_assurance(conn, conversation_id, customer["id"])
    msg_id = _id("MSG")
    try:
        with conn.begin_nested():
            conn.execute(
                text(
                    """
                    INSERT INTO messages (id, conversation_id, sender, body, delivery_status, provider_ref, sent_at)
                    VALUES (:id, :conversation_id, 'customer', :body, 'delivered', :provider_ref, :sent_at)
                    """
                ),
                {
                    "id": msg_id,
                    "conversation_id": conversation_id,
                    "body": body or "",
                    "provider_ref": wa_message_id,
                    "sent_at": sent_at,
                },
            )
    except Exception as exc:
        # Unique provider_ref is the idempotency key — treat conflicts as
        # duplicates. Detect via SQLSTATE 23505, not driver message text: the
        # wording is psycopg-version- and locale-dependent, and substring
        # matching on "unique" also swallowed unrelated constraint failures.
        if not _is_unique_violation(exc):
            raise
        existing = _one(
            conn.execute(
                text("SELECT id, conversation_id FROM messages WHERE provider_ref = :ref"),
                {"ref": wa_message_id},
            )
        )
        if existing:
            return {
                "status": "duplicate",
                "messageId": existing["id"],
                "conversationId": existing["conversation_id"],
            }
        raise

    # Which number wrote. Replies -- the agent's and the bot's -- go back to
    # it: the service window Meta opened is that number's. Kept as the keyed
    # digest the customer record already holds, never the number, and only
    # after the dedupe above: a redelivered older message must not move it.
    # Only the newest inbound sets it -- the window runs from the newest, so
    # the number has to be the newest's too.
    conn.execute(
        text(
            """
            UPDATE interactions i
               SET source_payload = COALESCE(i.source_payload, '{}'::jsonb)
                   || jsonb_build_object('endpoint_hmac', encode(
                        CASE WHEN CAST(:slot AS text) = 'alt' THEN c.phone_alt_hmac
                             ELSE c.phone_primary_hmac END, 'hex'))
              FROM conversations cv
              JOIN customers c ON c.id = cv.customer_id
             WHERE cv.id = :cv AND i.id = cv.interaction_id
               AND NOT EXISTS (
                 SELECT 1 FROM messages m
                 WHERE m.conversation_id = cv.id AND m.sender = 'customer'
                   AND m.provider_ref IS NOT NULL AND m.sent_at > :sent_at
               )
            """
        ),
        {"slot": customer.get("endpoint_slot") or "primary", "cv": conversation_id, "sent_at": sent_at},
    )

    # Pref: inbound stays bot until take-over / escalate (do not flip to needs_human).
    conv_row = _one(
        conn.execute(
            text(
                """
                UPDATE conversations
                SET updated_at = now(),
                    status = CASE
                      WHEN assigned_user_id IS NOT NULL THEN status
                      WHEN status IN ('needs_human', 'escalated', 'assigned') THEN status
                      ELSE 'bot'
                    END
                WHERE id = :id
                RETURNING id, interaction_id, status, assigned_user_id
                """
            ),
            {"id": conversation_id},
        )
    )
    _activity(
        conn,
        "conversation",
        conversation_id,
        "whatsapp_inbound",
        "Inbound WhatsApp message",
        (body or "")[:120],
        customer["id"],
    )
    if conv_row and conv_row.get("interaction_id"):
        _touch_interaction_sentiment(conn, conv_row.get("interaction_id"), body or "")

    job_info = None
    if (
        conv_row
        and conv_row.get("status") == "bot"
        and not conv_row.get("assigned_user_id")
    ):
        try:
            import bot_jobs

            # Savepoint: an enqueue failure otherwise aborts the shared webhook
            # transaction, and the fallback _activity write below would then run
            # on a broken connection.
            with conn.begin_nested():
                job_info = bot_jobs.enqueue_bot_turn(
                    conn,
                    conversation_id=conversation_id,
                    customer_id=customer["id"],
                    trigger_message_id=msg_id,
                    trigger_provider_ref=wa_message_id,
                    interaction_id=conv_row.get("interaction_id"),
                    channel="whatsapp",
                )
        except Exception:
            # Never fail Meta webhook because the queue insert failed — log via activity.
            _activity(
                conn,
                "conversation",
                conversation_id,
                "bot_enqueue_failed",
                "Failed to enqueue bot turn",
                wa_message_id,
                customer["id"],
            )

    out: dict[str, Any] = {
        "status": "ok",
        "messageId": msg_id,
        "conversationId": conversation_id,
        "customerId": customer["id"],
    }
    if job_info:
        out["botJobId"] = job_info.get("id")
    return out


# Monotonic delivery lifecycle. Anything not listed (including NULL / "sending")
# ranks 0, so the first real callback always applies.
_DELIVERY_RANK = {"sent": 1, "delivered": 2, "read": 3}


def _apply_whatsapp_status(
    conn: Any,
    *,
    wa_message_id: str,
    status: str,
    errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    mapping = {
        "sent": "sent",
        "delivered": "delivered",
        "read": "read",
        "failed": "failed",
    }
    delivery = mapping.get(status)
    if not delivery:
        return {"status": "ignored", "reason": "unknown_status"}
    row = _one(
        conn.execute(
            text(
                """
                SELECT m.id, m.delivery_status, cv.customer_id, c.tenant_id
                FROM messages m
                JOIN conversations cv ON cv.id = m.conversation_id
                LEFT JOIN customers c ON c.id = cv.customer_id
                WHERE m.provider_ref = :ref
                """
            ),
            {"ref": wa_message_id},
        )
    )
    if row is None:
        return {"status": "missing", "providerRef": wa_message_id}

    # The receipt is appended before the monotonic guard below, and deliberately.
    # That guard exists to stop a late "sent" dragging an already-read message
    # backwards *in the Inbox*, which is a display concern. The reach estimator
    # wants the opposite: every transition, in the order the provider reports
    # it, because "delivered at 09:02, read at 21:40" is the signal that says
    # when this borrower is actually reachable — and discarding the out-of-order
    # ones would systematically drop exactly the slow reads that carry it.
    if row.get("customer_id") and row.get("tenant_id"):
        import delivery_receipts

        delivery_receipts.record(
            conn,
            tenant_id=str(row["tenant_id"]),
            customer_id=str(row["customer_id"]),
            channel="whatsapp",
            provider="meta",
            provider_ref=wa_message_id,
            message_id=str(row["id"]),
            related_id=str(row["id"]),
            state=delivery,
            reason=(errors[0].get("title") if errors and isinstance(errors[0], dict) else None),
        )

    # Meta delivers sent / delivered / read callbacks asynchronously and they
    # arrive out of order often enough to matter: a late "sent" used to drag an
    # already-read message backwards in the Inbox. Only accept a status that
    # advances the lifecycle. "failed" is terminal and always wins.
    current = str(row["delivery_status"] or "")
    if delivery != "failed" and _DELIVERY_RANK.get(delivery, 0) <= _DELIVERY_RANK.get(current, 0):
        return {
            "status": "ignored",
            "reason": "out_of_order",
            "messageId": row["id"],
            "delivery": current,
        }
    conn.execute(
        text("UPDATE messages SET delivery_status = :delivery WHERE id = :id"),
        {"delivery": delivery, "id": row["id"]},
    )
    # The thread changed: whether the customer is still awaiting an answer
    # turns on this status. The list's delta poll reads `updated_at`, so
    # without this the row kept its old count and SLA until a full refresh.
    conn.execute(
        text(
            "UPDATE conversations SET updated_at = now() "
            "WHERE id = (SELECT conversation_id FROM messages WHERE id = :id)"
        ),
        {"id": row["id"]},
    )
    if delivery == "failed" and errors:
        # Persist Meta's reason on the outbound job so operators see 131047
        # (outside 24h window) instead of a silent "failed" tick.
        detail_bits: list[str] = []
        for err in errors[:3]:
            if not isinstance(err, dict):
                continue
            code = err.get("code")
            title = err.get("title") or err.get("message") or ""
            details = ""
            ed = err.get("error_data")
            if isinstance(ed, dict):
                details = str(ed.get("details") or "")
            bit = " ".join(
                p for p in (f"code={code}" if code is not None else "", str(title), details) if p
            ).strip()
            if bit:
                detail_bits.append(bit[:400])
        err_text = (" | ".join(detail_bits) or "whatsapp_delivery_failed")[:2000]
        logger.warning(
            "whatsapp delivery failed message=%s provider_ref=%s err=%s",
            row["id"],
            wa_message_id,
            err_text,
        )
        conn.execute(
            text(
                """
                UPDATE whatsapp_outbound_jobs
                SET error = :error,
                    -- The job said `succeeded` because the POST to Meta was
                    -- accepted, and then Meta rejected the message itself in a
                    -- status callback. This wrote the reason onto the row and
                    -- left the status alone, so WAO-14F8282BF6AC reads
                    -- `succeeded` while carrying "code=131047 Message failed to
                    -- send" and its message row reads `failed`. Anything
                    -- counting job status over-reported delivery.
                    --
                    -- `failed` has been legal in the check constraint since the
                    -- table was created and written by nothing. This is what it
                    -- is for. Only `succeeded` moves: a job already dead or
                    -- still queued is not made worse by a late callback.
                    status = CASE WHEN status = 'succeeded' THEN 'failed' ELSE status END,
                    updated_at = now()
                WHERE message_id = :message_id
                """
            ),
            {"error": err_text, "message_id": row["id"]},
        )
    return {"status": "ok", "messageId": row["id"], "delivery": delivery}


_MEDIA_LABELS = {
    "image": "Image",
    "video": "Video",
    "document": "Document",
    "audio": "Audio",
    "sticker": "Sticker",
}


def _inbound_body(msg: dict[str, Any]) -> str:
    """The text a customer's message carries, as the transcript records it.

    Media used to become ``[image message]``, dropping the caption -- often the
    only words the borrower wrote ("paid today, receipt attached") -- and the
    file's name. Both are the customer's words and stay on the record. The
    media itself is fetched from Meta by id, which this ingest does not do.
    """
    kind = msg.get("type") or "text"
    if kind == "text":
        return ((msg.get("text") or {}).get("body")) or ""
    if kind == "button":
        return ((msg.get("button") or {}).get("text")) or ""
    if kind == "interactive":
        interactive = msg.get("interactive") or {}
        return (
            ((interactive.get("button_reply") or {}).get("title"))
            or ((interactive.get("list_reply") or {}).get("title"))
            or ""
        )
    if kind in _MEDIA_LABELS:
        media = msg.get(kind) or {}
        label = "Voice note" if kind == "audio" and media.get("voice") else _MEDIA_LABELS[kind]
        filename = (media.get("filename") or "").strip()
        tag = f"[{label}: {filename}]" if filename else f"[{label}]"
        caption = (media.get("caption") or "").strip()
        return f"{tag} {caption}" if caption else tag
    if kind == "reaction":
        emoji = ((msg.get("reaction") or {}).get("emoji")) or ""
        return f"[Reacted {emoji}]" if emoji else "[Removed a reaction]"
    if kind == "location":
        return "[Location]"
    if kind == "contacts":
        return "[Contact card]"
    return f"[Unsupported {kind} message]"


def process_whatsapp_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle Meta WhatsApp Cloud API webhook POST body (messages + statuses)."""
    import whatsapp as wa

    results: list[dict[str, Any]] = []
    with _engine().begin() as conn:
        for entry in payload.get("entry") or []:
            for change in entry.get("changes") or []:
                value = change.get("value") or {}
                contacts = {c.get("wa_id"): c for c in (value.get("contacts") or []) if c.get("wa_id")}

                for msg in value.get("messages") or []:
                    wa_id = msg.get("id")
                    from_phone = wa.normalize_phone(msg.get("from"))
                    if not wa_id or not from_phone:
                        results.append({"status": "skipped", "reason": "missing_id_or_from"})
                        continue
                    body = _inbound_body(msg)
                    ts_raw = msg.get("timestamp")
                    try:
                        sent_at = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc) if ts_raw else utc_now()
                    except (TypeError, ValueError, OSError):
                        sent_at = utc_now()
                    contact = contacts.get(from_phone) or contacts.get(msg.get("from")) or {}
                    profile_name = ((contact.get("profile") or {}).get("name")) if isinstance(contact, dict) else None
                    # Savepoint per message: Meta batches several messages into
                    # one POST and does not support partial acknowledgement, so
                    # one bad item aborting the transaction would discard every
                    # sibling message and they would never be redelivered
                    # individually.
                    nested = conn.begin_nested()
                    try:
                        result = _ingest_inbound_whatsapp_message(
                            conn,
                            wa_message_id=wa_id,
                            from_phone=from_phone,
                            body=body,
                            profile_name=profile_name,
                            sent_at=sent_at,
                        )
                        nested.commit()
                    except Exception:
                        nested.rollback()
                        logger.exception(
                            "whatsapp inbound ingest failed wa_message_id=%s", wa_id
                        )
                        result = {"status": "error", "waMessageId": wa_id}
                    results.append(result)

                for st in value.get("statuses") or []:
                    wa_id = st.get("id")
                    status = st.get("status")
                    if not wa_id or not status:
                        continue
                    nested = conn.begin_nested()
                    try:
                        errs = st.get("errors") if isinstance(st.get("errors"), list) else None
                        result = _apply_whatsapp_status(
                            conn,
                            wa_message_id=wa_id,
                            status=status,
                            errors=errs,
                        )
                        nested.commit()
                    except Exception:
                        nested.rollback()
                        logger.exception(
                            "whatsapp status update failed wa_message_id=%s status=%s",
                            wa_id,
                            status,
                        )
                        result = {"status": "error", "waMessageId": wa_id}
                    results.append(result)

    return {"ok": all(r.get("status") != "error" for r in results), "results": results}
