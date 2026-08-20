"""Idempotent Susanth customer graph for WhatsApp Inbox round-trip testing.

Safe to re-run. Reuses tenant/bots/products already seeded by seed_postgres.
Phone comes from WHATSAPP_TEST_TO (synthetic fallback for non-prod only).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import psycopg

from seed_postgres import DEFAULT_DSN, TENANT_ID, app_dsn_to_psycopg, read_env, upsert


CUSTOMER_ID = "cust-susanth"
ACCOUNT_ID = "AC-SUSANTH"
INTERACTION_ID = "IX-SUSANTH-WA1"
CONVERSATION_ID = "CV-SUSANTH-WA1"
BOT_ID = "collectionsbot-v2-4"
PRODUCT_ID = "personal-loan"
ACTOR = "priya-nair"


def _is_prod() -> bool:
    """Same production detection as scripts/seed_demo.py."""
    return (os.getenv("APP_ENV") or "dev").strip().lower() in {"prod", "production"}


def _test_phone() -> str:
    """Phone for the WhatsApp round-trip fixture — WHATSAPP_TEST_TO only.

    No fallback literal: this number receives real WhatsApp messages during
    testing, so a hard-coded default either points at a real person's handset
    or seeds an undeliverable synthetic number that looks configured. Missing
    configuration must fail loudly instead.
    """
    raw = (os.getenv("WHATSAPP_TEST_TO") or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        raise RuntimeError(
            "WHATSAPP_TEST_TO is not set — seed_susanth needs an explicit test "
            "recipient number (E.164 digits) for the WhatsApp round-trip fixture."
        )
    return digits


PHONE = ""


def seed_susanth(conn: psycopg.Connection) -> None:
    if _is_prod():
        raise RuntimeError("seed_susanth refused: APP_ENV=production")
    global PHONE
    PHONE = _test_phone()
    now = datetime.now(timezone.utc)
    # Keep free-form WhatsApp window open for local testing.
    t0 = now - timedelta(minutes=12)
    t1 = now - timedelta(minutes=10)
    t2 = now - timedelta(minutes=8)
    t3 = now - timedelta(minutes=5)

    upsert(
        conn,
        "customers",
        {
            "id": CUSTOMER_ID,
            "tenant_id": TENANT_ID,
            "assigned_user_id": ACTOR,
            "name": "Susanth",
            "phone_primary": PHONE,
            "phone_alt": f"+91 {PHONE[2:7]} {PHONE[7:]}",
            "email": "susanth@example.com",
            "address": "12, MG Road, Chennai 600002",
            "timezone": "Asia/Kolkata",
            "language": "en-IN",
            "preferred_window": "10:00-19:00 IST",
            "dnd": False,
            "segment": "retail",
            "risk": "medium",
            "risk_score": 58,
            "last_contact_at": t3,
        },
    )

    upsert(
        conn,
        "accounts",
        {
            "id": ACCOUNT_ID,
            "customer_id": CUSTOMER_ID,
            "product_id": PRODUCT_ID,
            "apr": 14.5,
            "sanctioned_amount": 250000,
            "outstanding": 62400,
            "minimum_due": 4800,
            "dpd": 32,
            "bucket": "31-60",
            "status": "active",
            "opened_on": now - timedelta(days=420),
        },
    )

    for idx, (due_offset, amount, status, paid_on, paid_amount) in enumerate(
        [
            (-60, 4800, "paid", now - timedelta(days=55), 4800),
            (-30, 4800, "paid", now - timedelta(days=28), 4800),
            (0, 4800, "overdue", None, None),
            (30, 4800, "upcoming", None, None),
        ],
        start=1,
    ):
        upsert(
            conn,
            "emi_installments",
            {
                "id": f"EMI-SUSANTH-{idx}",
                "account_id": ACCOUNT_ID,
                "installment_index": idx,
                "due_date": now + timedelta(days=due_offset),
                "amount": amount,
                "paid_on": paid_on,
                "paid_amount": paid_amount,
                "status": status,
                "balance_carried": None,
            },
        )

    for i, (etype, desc, amount, bal, days_ago) in enumerate(
        [
            ("charge", "EMI due #1", 4800, 72000, 90),
            ("payment", "UPI payment", -4800, 67200, 85),
            ("charge", "EMI due #2", 4800, 72000, 60),
            ("payment", "UPI payment", -4800, 67200, 55),
            ("charge", "EMI due", 4800, 72000, 40),
            ("payment", "UPI payment", -4800, 67200, 37),
            ("fee", "Late fee", 350, 67550, 35),
            ("waiver", "Goodwill late-fee waiver", -350, 67200, 32),
            ("charge", "EMI due (current)", 4800, 72000, 10),
            ("payment", "Partial UPI", -4800, 67200, 8),
            ("adjustment", "Interest capitalization", 200, 67400, 5),
            ("payment", "Goodwill adjustment settle", -1000, 62400, 2),
        ],
        start=1,
    ):
        upsert(
            conn,
            "ledger_entries",
            {
                "id": f"LED-SUSANTH-{i}",
                "account_id": ACCOUNT_ID,
                "type": etype,
                "description": desc,
                "amount": amount,
                "balance": bal,
                "invoice_id": None,
                "posted_at": now - timedelta(days=days_ago),
            },
        )

    consent_id = f"consent-{CUSTOMER_ID}"
    upsert(
        conn,
        "consent_records",
        {
            "id": consent_id,
            "customer_id": CUSTOMER_ID,
            "dnd_registry": False,
            "expires_at": None,
            "allowed_days": "Mon-Sat",
            "allowed_hours": "10:00-19:00",
        },
    )
    for channel, status in (
        ("voice", "opted_in"),
        ("whatsapp", "opted_in"),
        ("sms", "opted_in"),
        ("email", "opted_out"),
    ):
        upsert(
            conn,
            "channel_consents",
            {
                "id": f"{consent_id}-{channel}",
                "consent_id": consent_id,
                "channel": channel,
                "status": status,
                "source": "seed_susanth",
                "weekly_frequency_cap": 5,
                "used_this_week": 1,
                "captured_at": now - timedelta(days=14),
            },
        )

    upsert(
        conn,
        "interactions",
        {
            "id": INTERACTION_ID,
            "tenant_id": TENANT_ID,
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "handler_kind": "bot",
            "handler_user_id": None,
            "handler_bot_id": BOT_ID,
            "transferred_from_bot_id": None,
            "channel": "whatsapp",
            "direction": "inbound",
            "status": "active",
            "disposition": None,
            "primary_intent": "payment_arrangement",
            "query_resolved": False,
            "upsell_presented": False,
            "ptp_captured": True,
            "avg_sentiment": 0.15,
            "sentiment_label": "neutral",
            "summary": "WhatsApp bot thread — Susanth asking about EMI options.",
            "hash": None,
            "latency_ms": 420,
            "rag_hits": 0,
            "redaction_applied": False,
            "deployment_id": None,
            "started_at": t0,
            "ended_at": None,
            "duration_sec": None,
            "source_payload": {},
        },
    )

    # Prior voice touch + broken PTP context for richer 360 insights
    ix_voice = "IX-SUSANTH-VOICE1"
    upsert(
        conn,
        "interactions",
        {
            "id": ix_voice,
            "tenant_id": TENANT_ID,
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "handler_kind": "human",
            "handler_user_id": ACTOR,
            "handler_bot_id": None,
            "transferred_from_bot_id": None,
            "channel": "voice",
            "direction": "outbound",
            "status": "completed",
            "disposition": "PTP captured (broken)",
            "primary_intent": "collections",
            "query_resolved": True,
            "upsell_presented": False,
            "ptp_captured": True,
            "avg_sentiment": -0.2,
            "sentiment_label": "negative",
            "summary": "Outbound call — Susanth committed ₹4,800 by month-end then missed. Prefers WhatsApp follow-ups.",
            "hash": None,
            "latency_ms": None,
            "rag_hits": 0,
            "redaction_applied": False,
            "deployment_id": None,
            "started_at": now - timedelta(days=28),
            "ended_at": now - timedelta(days=28, hours=-1),
            "duration_sec": 312,
            "source_payload": {},
        },
    )
    ix_wa2 = "IX-SUSANTH-WA2"
    upsert(
        conn,
        "interactions",
        {
            "id": ix_wa2,
            "tenant_id": TENANT_ID,
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "handler_kind": "bot",
            "handler_user_id": None,
            "handler_bot_id": BOT_ID,
            "transferred_from_bot_id": None,
            "channel": "whatsapp",
            "direction": "inbound",
            "status": "completed",
            "disposition": "Bot contained",
            "primary_intent": "balance_inquiry",
            "query_resolved": True,
            "upsell_presented": False,
            "ptp_captured": False,
            "avg_sentiment": 0.05,
            "sentiment_label": "neutral",
            "summary": "Balance and late-fee FAQ. Customer asked about fee waiver — dispute later filed.",
            "hash": None,
            "latency_ms": 380,
            "rag_hits": 2,
            "redaction_applied": False,
            "deployment_id": None,
            "started_at": now - timedelta(days=12),
            "ended_at": now - timedelta(days=12, hours=-1),
            "duration_sec": 180,
            "source_payload": {},
        },
    )

    upsert(
        conn,
        "interaction_participants",
        {
            "id": f"IP-{INTERACTION_ID}-customer",
            "interaction_id": INTERACTION_ID,
            "participant_kind": "customer",
            "user_id": None,
            "bot_id": None,
            "role": "customer",
            "joined_at": t0,
            "left_at": None,
        },
    )
    upsert(
        conn,
        "interaction_participants",
        {
            "id": f"IP-{INTERACTION_ID}-bot",
            "interaction_id": INTERACTION_ID,
            "participant_kind": "bot",
            "user_id": None,
            "bot_id": BOT_ID,
            "role": "primary",
            "joined_at": t0,
            "left_at": None,
        },
    )

    for idx, (speaker, text, at_sec, sent) in enumerate(
        [
            ("customer", "Hi, this is Susanth. Can I pay my EMI next week?", 0, t0),
            (
                "bot",
                "Hi Susanth — I can help with AC-SUSANTH. Your outstanding is ₹62,400. Would you like a payment link or a promise date?",
                20,
                t1,
            ),
            ("customer", "Promise for next Friday works. Also confirm on WhatsApp.", 45, t2),
            (
                "bot",
                "Noted. I've logged a promise for Friday. An agent can take over if you need anything else.",
                70,
                t3,
            ),
        ]
    ):
        upsert(
            conn,
            "interaction_transcript",
            {
                "id": f"TR-{INTERACTION_ID}-{idx}",
                "interaction_id": INTERACTION_ID,
                "turn_index": idx,
                "speaker": speaker,
                "at_sec": at_sec,
                "text": text,
                "sentiment_delta": 0.05 if speaker == "customer" else 0.0,
            },
        )

    upsert(
        conn,
        "conversations",
        {
            "id": CONVERSATION_ID,
            "interaction_id": INTERACTION_ID,
            "customer_id": CUSTOMER_ID,
            "assigned_user_id": None,
            "status": "bot",
            "channel": "whatsapp",
            "created_at": t0,
            "updated_at": t3,
        },
    )

    for idx, (sender, body, sent) in enumerate(
        [
            ("customer", "Hi, this is Susanth. Can I pay my EMI next week?", t0),
            (
                "bot",
                "Hi Susanth — I can help with AC-SUSANTH. Your outstanding is ₹62,400. Would you like a payment link or a promise date?",
                t1,
            ),
            ("customer", "Promise for next Friday works. Also confirm on WhatsApp.", t2),
            (
                "bot",
                "Noted. I've logged a promise for Friday. An agent can take over if you need anything else.",
                t3,
            ),
        ]
    ):
        upsert(
            conn,
            "messages",
            {
                "id": f"MSG-SUSANTH-{idx}",
                "conversation_id": CONVERSATION_ID,
                "sender": sender,
                "body": body,
                "delivery_status": "delivered",
                "provider_ref": None,
                "sent_at": sent,
            },
        )

    promise_at = (now + timedelta(days=5)).replace(hour=11, minute=0, second=0, microsecond=0)
    upsert(
        conn,
        "promises",
        {
            "id": "PTP-SUSANTH-1",
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "interaction_id": INTERACTION_ID,
            "owner_kind": "bot",
            "owner_user_id": None,
            "owner_bot_id": BOT_ID,
            "plan_id": None,
            "amount": 4800,
            "promised_at": promise_at,
            "status": "upcoming",
            "reminder_status": "scheduled",
            "paid_amount": 0,
            "channel": "whatsapp",
        },
    )
    upsert(
        conn,
        "promises",
        {
            "id": "PTP-SUSANTH-2",
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "interaction_id": "IX-SUSANTH-VOICE1",
            "owner_kind": "human",
            "owner_user_id": ACTOR,
            "owner_bot_id": None,
            "plan_id": None,
            "amount": 4800,
            "promised_at": now - timedelta(days=20),
            "status": "broken",
            "reminder_status": "sent",
            "paid_amount": 0,
            "channel": "voice",
        },
    )
    upsert(
        conn,
        "promises",
        {
            "id": "PTP-SUSANTH-3",
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "interaction_id": None,
            "owner_kind": "bot",
            "owner_user_id": None,
            "owner_bot_id": BOT_ID,
            "plan_id": None,
            "amount": 2400,
            "promised_at": now - timedelta(days=45),
            "status": "kept",
            "reminder_status": "acknowledged",
            "paid_amount": 2400,
            "channel": "whatsapp",
        },
    )
    upsert(
        conn,
        "promise_reminders",
        {
            "id": "REM-SUSANTH-1",
            "promise_id": "PTP-SUSANTH-1",
            "channel": "whatsapp",
            "scheduled_at": promise_at - timedelta(hours=24),
            "sent_at": None,
            "status": "scheduled",
        },
    )

    upsert(
        conn,
        "disputes",
        {
            "id": "D-SUSANTH-1",
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "interaction_id": INTERACTION_ID,
            "assignee_user_id": ACTOR,
            "type": "fee_waiver",
            "disputed_amount": 350,
            "source": "whatsapp",
            "status": "under_review",
            "priority": "normal",
            "resolution_code": None,
            "resolution_notes": None,
            "sla_due_at": now + timedelta(days=2),
            "transcript_snippet": "Can you waive the late fee from last month?",
        },
    )

    upsert(
        conn,
        "customer_notes",
        {
            "id": "NOTE-SUSANTH-1",
            "customer_id": CUSTOMER_ID,
            "author_user_id": ACTOR,
            "interaction_id": INTERACTION_ID,
            "text": f"WhatsApp test customer — primary phone {PHONE} for Meta round-trip.",
            "pinned": True,
        },
    )
    upsert(
        conn,
        "customer_notes",
        {
            "id": "NOTE-SUSANTH-2",
            "customer_id": CUSTOMER_ID,
            "author_user_id": ACTOR,
            "interaction_id": None,
            "text": "Prefers WhatsApp over voice. EMI date flexibility OK within 7 days.",
            "pinned": False,
        },
    )

    upsert(
        conn,
        "document_requests",
        {
            "id": "DOC-SUSANTH-1",
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "template_id": "template-statement",
            "interaction_id": INTERACTION_ID,
            "assignee_user_id": ACTOR,
            "doc_type": "statement",
            "period": "last_6_months",
            "requested_via": "bot_chat",
            "delivery_channel": "whatsapp",
            "delivery_target": PHONE,
            "status": "sent",
            "attempts": 1,
            "priority": "normal",
            "failed_reason": None,
            "size_kb": 180,
        },
    )

    upsert(
        conn,
        "callbacks",
        {
            "id": "CB-SUSANTH-1",
            "customer_id": CUSTOMER_ID,
            "account_id": ACCOUNT_ID,
            "interaction_id": INTERACTION_ID,
            "assignee_user_id": ACTOR,
            "team_id": "retail-collections",
            "reason": "Confirm Friday EMI promise on WhatsApp",
            "scheduled_at": now + timedelta(days=1, hours=2),
            "window_mins": 30,
            "dnd_active": False,
            "status": "scheduled",
            "disposition": None,
            "priority": "normal",
            "transcript_snippet": "Promise for next Friday works.",
            "outcome_notes": None,
            "sla_due_at": now + timedelta(days=1, hours=4),
        },
    )

    for i, (kind, label, note, at, entity_type, entity_id, actor_kind) in enumerate(
        [
            ("conversation_opened", "WhatsApp conversation opened", "Inbound WA bot thread", t0, "conversation", CONVERSATION_ID, "bot"),
            ("promise_captured", "Promise logged", "₹4,800 Friday", t2, "conversation", CONVERSATION_ID, "bot"),
            ("note_added", "Agent note", "WA test handset linked", t3, "conversation", CONVERSATION_ID, "human"),
            ("promise_broken", "PTP broken", "₹4,800 month-end miss", now - timedelta(days=18), "customer", CUSTOMER_ID, "system"),
            ("dispute_opened", "Fee waiver dispute", "Late fee challenge", now - timedelta(days=10), "customer", CUSTOMER_ID, "human"),
            ("document_sent", "Statement delivered", "Last 6 months via WhatsApp", now - timedelta(days=9), "customer", CUSTOMER_ID, "bot"),
        ],
        start=1,
    ):
        upsert(
            conn,
            "activity_events",
            {
                "id": f"ACT-SUSANTH-{i}",
                "tenant_id": TENANT_ID,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "at": at,
                "actor_kind": actor_kind,
                "actor_user_id": None if actor_kind != "human" else ACTOR,
                "actor_bot_id": BOT_ID if actor_kind == "bot" else None,
                "kind": kind,
                "label": label,
                "note": note,
                "tone": None,
                "payload": {},
            },
        )

    print(
        f"[seed_susanth] upserted {CUSTOMER_ID} / {ACCOUNT_ID} / {CONVERSATION_ID} "
        f"(phone={PHONE}, channel=whatsapp, status=bot)"
    )


def main() -> None:
    # Guard the direct-execution path too, before any connection is opened —
    # seed_susanth() also checks, but failing here keeps the hardcoded test
    # customer from ever reaching a production DSN.
    if _is_prod():
        raise SystemExit(
            "Refusing to seed the Susanth test fixture when APP_ENV=production|prod."
        )
    dsn = app_dsn_to_psycopg(os.getenv("DATABASE_URL") or read_env("DATABASE_URL") or DEFAULT_DSN)
    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            seed_susanth(conn)


if __name__ == "__main__":
    main()
