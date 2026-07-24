"""Seed the Postgres enterprise schema from the frontend export snapshots.

The seed graph is intentionally built in memory so the same customer/account/
interaction ids are reused across customers, calls, promises, disputes,
documents, leads, QA, redaction, analytics, and activity rows.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Json


BASE = Path(__file__).parent
SEED_DIR = BASE / "seed"
DEFAULT_DSN = "postgresql://collections:collections@localhost:5432/collections"
TENANT_ID = "hdfc.retail"


def main() -> None:
    customers_export = load_json("customers.json")
    calls_export = load_json("calls.json")
    leads_export = load_json("leads.json")

    ctx = build_context(customers_export, calls_export, leads_export)
    dsn = app_dsn_to_psycopg(os.getenv("DATABASE_URL") or read_env("DATABASE_URL") or DEFAULT_DSN)

    with psycopg.connect(dsn) as conn:
        with conn.transaction():
            seed_reference_data(conn, ctx)
            seed_customers_accounts(conn, ctx)
            seed_consent(conn, ctx)
            seed_bot_config(conn, ctx)
            seed_interactions(conn, ctx)
            seed_collections_and_sales(conn, ctx)
            seed_compliance_qa_redaction(conn, ctx)
            seed_admin_analytics_crosscutting(conn, ctx)
            from seed_susanth import seed_susanth

            seed_susanth(conn)

    print(
        "[seed] loaded "
        f"{len(ctx['customers'])} customers, "
        f"{len(ctx['calls'])} interactions, "
        f"{len(ctx['leads'])} leads"
    )


def load_json(filename: str) -> Any:
    return json.loads((SEED_DIR / filename).read_text(encoding="utf-8"))


def read_env(key: str) -> str | None:
    env_file = BASE / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        env_key, value = line.split("=", 1)
        if env_key == key:
            return value
    return None


def app_dsn_to_psycopg(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg://", "postgresql://", 1)


def slug(value: str | None, fallback: str = "unknown") -> str:
    text = (value or fallback).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or fallback


def money(value: Any) -> Any:
    if value in (None, "", "N/A"):
        return None
    return value


def parse_duration(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if not value:
        return None
    minutes = re.search(r"(\d+)\s*m", str(value))
    seconds = re.search(r"(\d+)\s*s", str(value))
    return (int(minutes.group(1)) * 60 if minutes else 0) + (int(seconds.group(1)) if seconds else 0)


def channel(value: str | None) -> str:
    return {"call": "voice"}.get(value or "", value or "voice")


def sentiment_label(score: Any = None, label: str | None = None) -> str:
    if label in {"positive", "neutral", "negative"}:
        return label
    try:
        n = float(score)
    except (TypeError, ValueError):
        return "neutral"
    if n > 0.15:
        return "positive"
    if n < -0.15:
        return "negative"
    return "neutral"


def promise_status(value: str | None) -> str:
    return value if value in {"upcoming", "due_today", "kept", "broken", "partial"} else "upcoming"


def dispute_status(value: str | None) -> str:
    return value if value in {"new", "under_review", "awaiting_customer", "resolved", "rejected"} else "new"


def doc_status(value: str | None) -> str:
    return value if value in {"requested", "generating", "sent", "failed"} else "requested"


def lead_stage(value: str | None) -> str:
    return value if value in {"interested", "contacted", "qualified", "won", "lost"} else "interested"


def priority(value: str | None) -> str:
    return value if value in {"low", "normal", "high", "urgent"} else "normal"


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_number(value: str, low: int, high: int) -> int:
    span = high - low + 1
    return low + (int(stable_hash(value)[:8], 16) % span)


def synthetic_account_id(customer_id: str) -> str:
    return f"AC-{stable_number(customer_id, 20000, 98999)}"


# Customer-intent taxonomy for Bot Analytics. Mirrors the migration 0009
# backfill and Habibi/src/data/bot-analytics-seed.ts / db._INTENT_LABELS.
_CUSTOMER_INTENTS = [
    "balance", "emi", "payment-confirm", "statement", "late-fee",
    "callback", "topup", "dnd", "upi", "dispute",
]
_NON_CUSTOMER_INTENTS = {"QA-review", "empathy-coach"}
_HANDOFF_REASONS = [
    "customer_requested", "compliance", "hardship",
    "high_value", "verification_failed", "routing_rule",
]


def seed_primary_intent(call: dict[str, Any], call_id: str) -> str | None:
    """First tag if it's a real customer intent, else a deterministic backfill.
    ~15% stay null so the analytics funnel keeps a real "intent captured" drop."""
    tag = (call.get("tags") or [None])[0]
    if tag and tag not in _NON_CUSTOMER_INTENTS:
        return tag
    if stable_number(call_id, 0, 19) < 3:
        return None
    return _CUSTOMER_INTENTS[stable_number(call_id, 0, len(_CUSTOMER_INTENTS) - 1)]


def seed_handoff_reason(call: dict[str, Any], call_id: str, avg_sentiment: Any) -> str:
    """Diversify escalation reason by signal, else a deterministic spread."""
    if avg_sentiment is not None and float(avg_sentiment) < -0.30:
        return "sentiment_drop"
    if "dispute" in (call.get("disposition") or "").lower():
        return "dispute"
    return _HANDOFF_REASONS[stable_number(call_id, 0, len(_HANDOFF_REASONS) - 1)]


def product_for_account(account_id: str | None) -> str:
    value = account_id or ""
    if "-PL-" in value:
        return "personal-loan"
    if "-AL-" in value:
        return "auto-loan"
    return "credit-card"


def jsonable(value: Any) -> Any:
    return Json(value) if isinstance(value, (dict, list)) else value


def upsert(conn: psycopg.Connection, table: str, row: dict[str, Any], pk: str = "id") -> None:
    keys = list(row)
    cols = ", ".join(keys)
    vals = ", ".join(f"%({k})s" for k in keys)
    updates = ", ".join(f"{k}=EXCLUDED.{k}" for k in keys if k != pk)
    conflict = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    params = {k: jsonable(v) for k, v in row.items()}
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({vals}) ON CONFLICT ({pk}) {conflict}", params)


def insert_ignore(conn: psycopg.Connection, sql: str, params: dict[str, Any]) -> None:
    conn.execute(sql, {k: jsonable(v) for k, v in params.items()})


def build_context(customers_export: list[dict[str, Any]], calls: list[dict[str, Any]], leads: list[dict[str, Any]]) -> dict[str, Any]:
    detailed = {c["id"]: c for c in customers_export}
    customer_names: dict[str, str] = {c["id"]: c["name"] for c in customers_export}
    for row in calls + leads:
        customer_id = row.get("customerId")
        if customer_id:
            customer_names.setdefault(customer_id, row.get("customerName") or customer_id.replace("-", " ").title())

    users: dict[str, str] = {}
    bots: dict[str, str] = {
        "collectionsbot-v2-4": "CollectionsBot v2.4",
        "kaia-v2-4": "Kaia v2.4",
        "webchatbot": "WebChatBot",
    }
    teams: dict[str, str] = {
        "card-collections": "Card Collections",
        "retail-collections": "Retail Collections",
        "supervisors": "Supervisors",
    }
    products: dict[str, dict[str, Any]] = {
        "credit-card": {"id": "credit-card", "name": "Credit Card", "type": "card", "roi": "36% APR (revolving)"},
        "personal-loan": {"id": "personal-loan", "name": "Personal Loan", "type": "loan", "roi": "12.5% p.a."},
        "auto-loan": {"id": "auto-loan", "name": "Auto Loan", "type": "loan", "roi": "10.25% p.a."},
    }

    for customer in customers_export:
        if customer.get("assignedTo") and customer["assignedTo"] != "Unassigned":
            users[slug(customer["assignedTo"])] = customer["assignedTo"]
        account = customer.get("account") or {}
        product_name = account.get("product") or "Credit Card"
        products.setdefault(slug(product_name), {"id": slug(product_name), "name": product_name, "type": product_name.lower(), "roi": None})
        for note in customer.get("notes", []):
            if note.get("author"):
                users[slug(note["author"])] = note["author"]
        for dispute in customer.get("disputes", []):
            if dispute.get("assignee") and dispute["assignee"] != "Unassigned":
                users[slug(dispute["assignee"])] = dispute["assignee"]

    for call in calls:
        handler = call.get("handledBy") or {}
        if handler.get("kind") == "human":
            name = handler.get("name") or handler.get("human")
            if name:
                users[slug(name)] = name
        elif handler.get("kind") == "bot":
            name = handler.get("bot") or handler.get("name") or "CollectionsBot v2.4"
            bots[slug(name)] = name

    for lead in leads:
        if lead.get("owner") and lead["owner"] != "Unassigned":
            users[slug(lead["owner"])] = lead["owner"]
        if lead.get("team"):
            teams[slug(lead["team"])] = lead["team"]
        offer = lead.get("offer") or {}
        product_id = offer.get("productId") or slug(offer.get("label"))
        if product_id:
            products[product_id] = {
                "id": product_id,
                "name": offer.get("label") or product_id,
                "type": "offer",
                "roi": offer.get("indicativeROI"),
            }

    account_by_customer: dict[str, str] = {}
    for customer_id in customer_names:
        if customer_id in detailed:
            account_by_customer[customer_id] = detailed[customer_id].get("accountId") or f"AC-{stable_hash(customer_id)[:5].upper()}"
    for row in leads:
        customer_id = row.get("customerId")
        account_id = row.get("accountId")
        if customer_id and account_id:
            account_by_customer[customer_id] = account_id
    for customer_id in customer_names:
        account_by_customer.setdefault(customer_id, synthetic_account_id(customer_id))

    return {
        "detailed_customers": detailed,
        "customers": customer_names,
        "calls": calls,
        "leads": leads,
        "users": users,
        "bots": bots,
        "teams": teams,
        "products": products,
        "account_by_customer": account_by_customer,
    }


def seed_reference_data(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    upsert(conn, "tenants", {"id": TENANT_ID, "name": "HDFC Retail", "budget_inr": 2500000, "spend_share": 0.62})

    for team_id, name in ctx["teams"].items():
        upsert(conn, "teams", {"id": team_id, "tenant_id": TENANT_ID, "name": name, "supervisor_user_id": None})

    fallback_team = "card-collections"
    for user_id, name in ctx["users"].items():
        team_id = "supervisors" if name in {"Priya Nair", "David Chen"} else fallback_team
        upsert(
            conn,
            "users",
            {
                "id": user_id,
                "tenant_id": TENANT_ID,
                "team_id": team_id,
                "name": name,
                "email": f"{user_id}@hdfc.example",
                "status": "active",
            },
        )

    conn.execute("UPDATE teams SET supervisor_user_id = %s WHERE id = %s", ("priya-nair", "card-collections"))
    conn.execute("UPDATE teams SET supervisor_user_id = %s WHERE id = %s", ("david-chen", "supervisors"))

    for bot_id, name in ctx["bots"].items():
        version = "2.4" if "2.4" in name else "1.0"
        upsert(conn, "bots", {"id": bot_id, "tenant_id": TENANT_ID, "name": name, "version": version})

    permissions = [
        ("perm-interactions-read", "interactions", "read"),
        ("perm-customers-read", "customers", "read"),
        ("perm-workqueue-write", "workqueue", "write"),
        ("perm-admin-write", "admin", "write"),
        ("perm-qa-review", "qa", "review"),
    ]
    for permission_id, module, action in permissions:
        upsert(conn, "permissions", {"id": permission_id, "module": module, "action": action, "description": f"{action} {module}"})

    roles = [("role-agent", "Agent"), ("role-supervisor", "Supervisor"), ("role-admin", "Admin"), ("role-qa", "QA Reviewer")]
    for role_id, name in roles:
        upsert(conn, "roles", {"id": role_id, "tenant_id": TENANT_ID, "name": name})

    for role_id, permission_id in [
        ("role-agent", "perm-interactions-read"),
        ("role-agent", "perm-customers-read"),
        ("role-supervisor", "perm-workqueue-write"),
        ("role-supervisor", "perm-qa-review"),
        ("role-admin", "perm-admin-write"),
        ("role-qa", "perm-qa-review"),
    ]:
        insert_ignore(
            conn,
            "INSERT INTO role_permissions (role_id, permission_id) VALUES (%(role_id)s, %(permission_id)s) ON CONFLICT DO NOTHING",
            {"role_id": role_id, "permission_id": permission_id},
        )

    for user_id in ctx["users"]:
        role_id = "role-supervisor" if user_id in {"priya-nair", "david-chen"} else "role-agent"
        insert_ignore(
            conn,
            "INSERT INTO user_roles (user_id, role_id) VALUES (%(user_id)s, %(role_id)s) ON CONFLICT DO NOTHING",
            {"user_id": user_id, "role_id": role_id},
        )
        upsert(conn, "agent_presence", {"id": f"presence-{user_id}", "user_id": user_id, "status": "available", "since_at": "2026-07-21T09:00:00+05:30", "interaction_id": None})

    for product in ctx["products"].values():
        upsert(conn, "products", product)
        upsert(
            conn,
            "product_eligibility_rules",
            {
                "id": f"rule-{product['id']}",
                "product_id": product["id"],
                "name": f"{product['name']} default eligibility",
                "conditions": {"kyc": "current", "dpdMax": 90},
                "enabled": True,
            },
        )


def seed_customers_accounts(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    detailed = ctx["detailed_customers"]
    for customer_id, name in ctx["customers"].items():
        source = detailed.get(customer_id, {})
        contact = source.get("contact") or {}
        account = source.get("account") or {}
        assigned = source.get("assignedTo")
        account_id = ctx["account_by_customer"][customer_id]
        product_id = slug(account.get("product")) if account.get("product") else product_for_account(account_id)
        synthetic_dpd = stable_number(customer_id, 18, 94)
        synthetic_outstanding = stable_number(customer_id, 3200, 54200)
        synthetic_minimum_due = max(450, round(synthetic_outstanding * 0.12))
        synthetic_risk = "critical" if synthetic_dpd >= 75 else "high" if synthetic_dpd >= 45 else "medium"
        upsert(
            conn,
            "customers",
            {
                "id": customer_id,
                "tenant_id": TENANT_ID,
                "assigned_user_id": slug(assigned) if assigned and assigned != "Unassigned" else None,
                "name": name,
                "phone_primary": contact.get("phonePrimary") or f"+91 9{stable_number(customer_id, 100000000, 999999999)}",
                "phone_alt": contact.get("phoneAlt"),
                "email": contact.get("email") or f"{slug(name)}@mail.co.in",
                "address": contact.get("address") or f"{stable_number(customer_id, 10, 299)}, MG Road, Bengaluru 5600{stable_number(customer_id, 10, 99)}",
                "timezone": contact.get("timezone") or "Asia/Kolkata",
                "language": contact.get("language") or "English",
                "preferred_window": contact.get("preferredWindow") or "10:00-19:00 IST",
                "dnd": bool(contact.get("dnd", False)),
                "segment": "retail",
                "risk": source.get("risk") or synthetic_risk,
                "risk_score": account.get("riskScore") or stable_number(customer_id, 470, 760),
                "last_contact_at": source.get("lastContact") or f"2026-07-{stable_number(customer_id, 14, 21):02d}T{stable_number(customer_id, 4, 17):02d}:45:00Z",
            },
        )
        upsert(
            conn,
            "accounts",
            {
                "id": account_id,
                "customer_id": customer_id,
                "product_id": product_id if product_id in ctx["products"] else "credit-card",
                "apr": account.get("apr") or 36.0,
                "sanctioned_amount": money(account.get("sanctionedAmount")) or stable_number(customer_id, 75000, 650000),
                "outstanding": money(source.get("outstanding")) or synthetic_outstanding,
                "minimum_due": money(source.get("minimumDue")) or synthetic_minimum_due,
                "dpd": account.get("dpd") or synthetic_dpd,
                "bucket": account.get("bucket") or ("61-90" if synthetic_dpd >= 61 else "31-60" if synthetic_dpd >= 31 else "0-30"),
                "status": "active",
                "opened_on": account.get("openedOn") or "2024-07-31T04:45:00Z",
            },
        )
        for entry in source.get("ledger", []):
            upsert(
                conn,
                "ledger_entries",
                {
                    "id": f"{account_id}-{entry['id']}",
                    "account_id": account_id,
                    "type": entry.get("type") if entry.get("type") in {"charge", "payment", "fee", "adjustment", "waiver"} else "adjustment",
                    "description": entry.get("description"),
                    "amount": entry.get("amount") or 0,
                    "balance": entry.get("balance"),
                    "invoice_id": entry.get("invoiceId"),
                    "posted_at": entry.get("date"),
                },
            )
        for emi in source.get("emi", []):
            upsert(
                conn,
                "emi_installments",
                {
                    "id": f"{account_id}-{emi['id']}",
                    "account_id": account_id,
                    "installment_index": emi.get("index") or 0,
                    "due_date": emi.get("dueDate"),
                    "amount": emi.get("amount") or 0,
                    "paid_on": emi.get("paidOn"),
                    "paid_amount": emi.get("paidAmount"),
                    "status": emi.get("status") if emi.get("status") in {"paid", "upcoming", "overdue", "partial"} else "upcoming",
                    "balance_carried": emi.get("balanceCarried"),
                },
            )
        for note in source.get("notes", []):
            upsert(
                conn,
                "customer_notes",
                {
                    "id": f"{customer_id}-{note['id']}",
                    "customer_id": customer_id,
                    "author_user_id": slug(note.get("author")) if note.get("author") else None,
                    "interaction_id": None,
                    "text": note.get("text") or "",
                    "pinned": bool(note.get("pinned", False)),
                    "created_at": note.get("at"),
                },
            )

    known_accounts = set(ctx["account_by_customer"].values())
    for row in ctx["calls"] + ctx["leads"]:
        customer_id = row.get("customerId")
        account_id = row.get("accountId")
        if not customer_id or not account_id or account_id in known_accounts:
            continue
        known_accounts.add(account_id)
        upsert(
            conn,
            "accounts",
            {
                "id": account_id,
                "customer_id": customer_id,
                "product_id": product_for_account(account_id),
                "apr": 36.0,
                "sanctioned_amount": stable_number(account_id, 75000, 650000),
                "outstanding": stable_number(account_id, 3200, 54200),
                "minimum_due": stable_number(account_id, 450, 6200),
                "dpd": stable_number(account_id, 12, 92),
                "bucket": "31-60",
                "status": "active",
                "opened_on": None,
            },
        )


def seed_consent(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    detailed = ctx["detailed_customers"]
    for customer_id in ctx["customers"]:
        source = detailed.get(customer_id, {})
        consent_id = f"consent-{customer_id}"
        contact = source.get("contact") or {}
        upsert(
            conn,
            "consent_records",
            {
                "id": consent_id,
                "customer_id": customer_id,
                "dnd_registry": bool(contact.get("dnd", False)),
                "expires_at": None,
                "allowed_days": "Mon-Sat",
                "allowed_hours": contact.get("preferredWindow") or "10:00-19:00 IST",
            },
        )
        rows = source.get("consent") or [
            {"channel": "voice", "optedIn": True, "source": "seed-default", "capturedAt": "2026-07-01T00:00:00Z"},
            {"channel": "whatsapp", "optedIn": True, "source": "seed-default", "capturedAt": "2026-07-01T00:00:00Z"},
            {"channel": "sms", "optedIn": True, "source": "seed-default", "capturedAt": "2026-07-01T00:00:00Z"},
            {"channel": "email", "optedIn": False, "source": "seed-default", "capturedAt": "2026-07-01T00:00:00Z"},
        ]
        for row in rows:
            ch = channel(row.get("channel"))
            status = "opted_in" if row.get("optedIn") else "opted_out"
            upsert(
                conn,
                "channel_consents",
                {
                    "id": f"{consent_id}-{ch}",
                    "consent_id": consent_id,
                    "channel": ch,
                    "status": status,
                    "source": row.get("source"),
                    "weekly_frequency_cap": 3,
                    "captured_at": row.get("capturedAt"),
                },
            )
            if status == "opted_out":
                upsert(conn, "optout_events", {"id": f"optout-{consent_id}-{ch}", "consent_id": consent_id, "channel": ch, "source": row.get("source") or "seed", "actor_kind": "customer", "actor_user_id": None, "occurred_at": row.get("capturedAt") or "2026-07-01T00:00:00Z"})


def seed_bot_config(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    # --- Prompt Studio (Habibi /prompt-studio shapes). Alembic 0018 mirrors this. ---
    for user_id, name in (("anita-rao", "Anita Rao"), ("vikram-shah", "Vikram Shah")):
        upsert(
            conn,
            "users",
            {
                "id": user_id,
                "tenant_id": TENANT_ID,
                "team_id": "supervisors",
                "name": name,
                "email": f"{user_id}@hdfc.example",
                "status": "active",
            },
        )

    _emp_prompt = (
        "You are {agent_name}, an inbound collections voice agent for {bank_name}.\n"
        "Greet {customer_name} warmly and acknowledge their situation before discussing dues.\n"
        "Reference their account {account_no} and the overdue amount of {overdue_amount} due on {due_date}.\n"
        "Speak in {language}. Be patient, empathetic and non-judgemental.\n"
        "Always disclose that the call is recorded for quality and compliance.\n"
        "Never threaten legal action. Offer Promise-to-Pay options when the customer signals hardship."
    )
    _firm_prompt = (
        "You are {agent_name}, a collections agent for {bank_name}.\n"
        "Address {customer_name} directly and state the purpose of the call within the first two sentences.\n"
        "Clearly state the overdue amount {overdue_amount} on account {account_no}, past due since {due_date}.\n"
        "Speak in {language}. Be professional, direct and outcome-oriented.\n"
        "Disclose call recording. Do not promise waivers. Escalate to a human on any dispute."
    )
    _comp_prompt = (
        "You are {agent_name}, a compliance-first collections agent for {bank_name}.\n"
        "Begin every call with the recording disclosure and verify caller identity before sharing any account information.\n"
        "Reference {customer_name}, account {account_no}, dues {overdue_amount}, due on {due_date} only after verification.\n"
        "Speak in {language}. Never quote interest rates. Never promise fee waivers. Escalate on any dispute or hardship signal."
    )
    _upsell_prompt = (
        "You are {agent_name}, a collections + relationship voice agent for {bank_name}.\n"
        "Resolve {customer_name}'s query about their overdue {overdue_amount} on account {account_no} first.\n"
        "Once the primary query is addressed, and eligibility permits, gently introduce one relevant product offer.\n"
        "Speak in {language}. Do not push if the customer is stressed or has raised a dispute."
    )
    _guardrails = {
        "prohibited": ["guarantee", "police", "arrest", "threaten", "family will pay", "harassment"],
        "escalateAbuse": True,
        "escalateLegal": True,
        "neverQuoteRate": True,
        "neverPromiseWaiver": True,
        "alwaysDiscloseRecording": True,
        "refusePoliticsReligion": True,
        "maxTurns": 20,
        "maxSeconds": 480,
    }
    _voice = {
        "voiceId": "priya",
        "speed": 1.0,
        "pitch": 0,
        "warmth": 62,
        "pauseMs": 320,
        "sampleText": "Hello Rahul, this is a courtesy call from HDFC about your EMI. Do you have a minute?",
    }
    _emp_traits = {"empathy": 82, "firmness": 40, "formality": 55, "verbosity": 60, "upsell": 20}
    _firm_traits = {"empathy": 35, "firmness": 80, "formality": 65, "verbosity": 40, "upsell": 15}
    _comp_traits = {"empathy": 55, "firmness": 55, "formality": 90, "verbosity": 55, "upsell": 5}
    _upsell_traits = {"empathy": 65, "firmness": 45, "formality": 55, "verbosity": 55, "upsell": 75}

    for voice_id, name, gender, accent, azure in (
        ("priya", "Priya", "Female", "Indian English", "en-IN-NeerjaNeural"),
        ("anjali", "Anjali", "Female", "Hindi-English", "en-IN-AashiNeural"),
        ("neha", "Neha", "Female", "Neutral English", "en-IN-NeerjaNeural"),
        ("ravi", "Ravi", "Male", "Indian English", "en-IN-PrabhatNeural"),
        ("arjun", "Arjun", "Male", "Hindi-English", "en-IN-KunalNeural"),
        ("kabir", "Kabir", "Male", "Neutral English", "en-IN-PrabhatNeural"),
    ):
        upsert(
            conn,
            "tts_voices",
            {
                "id": voice_id,
                "provider": "azure-speech",
                "name": name,
                "config": {"gender": gender, "accent": accent, "duration": "0:03", "azureVoiceName": azure},
                "enabled": True,
            },
        )

    for preset_id, name, description, traits, template in (
        ("empathetic", "Empathetic Collector", "Warm, patient, hardship-aware", _emp_traits, _emp_prompt),
        ("firm", "Firm Collector", "Direct, outcome-focused", _firm_traits, _firm_prompt),
        ("compliance", "Compliance-First", "Every disclosure, every time", _comp_traits, _comp_prompt),
        ("upsell", "Upsell-Focused", "Resolve, then convert", _upsell_traits, _upsell_prompt),
    ):
        upsert(
            conn,
            "persona_presets",
            {
                "id": preset_id,
                "name": name,
                "config": {
                    "label": name,
                    "description": description,
                    "traits": traits,
                    "promptTemplate": template,
                },
            },
        )

    def _persona(traits: dict[str, int], fallback: list[str] | None = None) -> dict[str, Any]:
        return {"traits": traits, "language": "English", "fallbackLanguages": fallback or ["Hindi"]}

    # Archived first, then sole published — keeps ux_prompt_versions_one_published happy.
    for row in (
        {
            "id": "v1_0",
            "author_user_id": "anita-rao",
            "status": "archived",
            "label": "v1.0",
            "summary": "first draft",
            "prompt": "You are a collections agent. Collect the overdue amount.",
            "persona": _persona(_emp_traits),
            "voice": {**_voice},
            "guardrails": {**_guardrails, "prohibited": [], "alwaysDiscloseRecording": False, "escalateAbuse": False},
            "created_at": "2026-06-22T10:00:00Z",
            "updated_at": "2026-06-22T10:00:00Z",
        },
        {
            "id": "v1_1",
            "author_user_id": "vikram-shah",
            "status": "archived",
            "label": "v1.1",
            "summary": "initial compliance pass",
            "prompt": _comp_prompt.replace("Never quote interest rates.", ""),
            "persona": _persona(_comp_traits),
            "voice": {**_voice, "warmth": 45},
            "guardrails": {**_guardrails, "neverQuoteRate": False},
            "created_at": "2026-07-02T10:00:00Z",
            "updated_at": "2026-07-02T10:00:00Z",
        },
        {
            "id": "v1_2",
            "author_user_id": "vikram-shah",
            "status": "archived",
            "label": "v1.2",
            "summary": "− legal-threat language, + Hindi fallback",
            "prompt": _firm_prompt,
            "persona": _persona(_firm_traits, ["Hindi", "Marathi"]),
            "voice": {**_voice, "voiceId": "ravi"},
            "guardrails": {**_guardrails, "prohibited": ["police", "arrest", "harassment"]},
            "created_at": "2026-07-10T10:00:00Z",
            "updated_at": "2026-07-10T10:00:00Z",
        },
        {
            "id": "v1_3",
            "author_user_id": "anita-rao",
            "status": "archived",
            "label": "v1.3",
            "summary": "+ upsell-focused fallback path",
            "prompt": _emp_prompt.replace("Offer Promise-to-Pay", "Offer Promise-to-Pay or product upgrade"),
            "persona": _persona({**_emp_traits, "upsell": 40}),
            "voice": {**_voice, "warmth": 55},
            "guardrails": {**_guardrails, "neverPromiseWaiver": False},
            "created_at": "2026-07-16T10:00:00Z",
            "updated_at": "2026-07-16T10:00:00Z",
        },
        {
            "id": "v1_4",
            "author_user_id": "anita-rao",
            "status": "published",
            "label": "v1.4",
            "summary": "+ recording disclosure, empathy 70→75",
            "prompt": _emp_prompt,
            "persona": _persona({**_emp_traits, "empathy": 75}),
            "voice": {**_voice},
            "guardrails": {**_guardrails},
            "created_at": "2026-07-20T10:00:00Z",
            "updated_at": "2026-07-20T10:00:00Z",
        },
    ):
        upsert(conn, "prompt_versions", row)

    upsert(conn, "kb_documents", {"id": "kb-rbi-disclosures", "updated_by_user_id": "priya-nair", "type": "policy", "version": "2026.07", "status": "indexed", "enabled": True, "chunk_size": 800, "chunk_overlap": 120, "title": "RBI Collections Disclosure Guide"})
    upsert(conn, "kb_source_files", {"id": "file-kb-rbi-disclosures", "document_id": "kb-rbi-disclosures", "storage_ref": "minio://kb-sources/hdfc.retail/rbi-disclosures.pdf", "filename": "rbi-disclosures.pdf", "mime_type": "application/pdf", "size_bytes": 284000, "hash": stable_hash("rbi-disclosures")})
    upsert(conn, "kb_chunks", {"id": "chunk-rbi-disclosures-1", "document_id": "kb-rbi-disclosures", "heading": "Recording disclosure", "tokens": 42, "text": "Agents and bots must disclose recording and identity before discussing account details.", "embedding": None, "hits": 12, "chunk_index": 1})
    upsert(conn, "kb_index_jobs", {"id": "kb-job-rbi-disclosures", "document_id": "kb-rbi-disclosures", "status": "succeeded", "chunk_size": 800, "chunk_overlap": 120, "embedding_model": "text-embedding-3-small", "started_at": "2026-07-21T08:00:00Z", "completed_at": "2026-07-21T08:02:00Z", "error": None})
    upsert(conn, "faq_pairs", {"id": "faq-payment-link", "linked_document_id": "kb-rbi-disclosures", "intent": "payment_link", "question": "Can you send a payment link?", "answer": "Yes, I can send a secure payment link to your registered channel.", "enabled": True})
    upsert(conn, "kb_snapshots", {"id": "kb-snapshot-2026-07", "label": "July production KB", "document_ids": ["kb-rbi-disclosures"], "faq_ids": ["faq-payment-link"]})
    # Live-config invariant: active prod deployment → published prompt (v1_4) + Azure voice.
    upsert(
        conn,
        "bot_deployments",
        {
            "id": "DEP-2026-07-PROD",
            "bot_id": "kaia-v2-4",
            "prompt_version_id": "v1_4",
            "kb_snapshot_id": "kb-snapshot-2026-07",
            "tts_voice_id": "priya",
            "environment": "production",
            "status": "active",
            "published_by_user_id": "priya-nair",
            "published_at": "2026-07-21T08:30:00Z",
            "rollback_deployment_id": None,
            "voice_config": {**_voice},
        },
    )
    # Screen-shaped routing library (Habibi Routing Builder). Alembic 0013 mirrors this.
    routing_library = [
        {
            "id": "route-abusive-supervisor",
            "priority": 1,
            "enabled": True,
            "name": "Abusive language → immediate supervisor",
            "description": "Barge supervisor when abusive language or legal threats detected.",
            "category": "Escalation",
            "conditions": [
                {
                    "id": "c-abuse-or",
                    "or": [
                        {"id": "c-abuse-1", "field": "guardrail_flag", "op": "=", "value": "abusive-language"},
                        {"id": "c-abuse-2", "field": "guardrail_flag", "op": "=", "value": "legal-threat"},
                    ],
                }
            ],
            "action_key": "escalate_supervisor",
            "action_params": {},
        },
        {
            "id": "route-high-value-tier2",
            "priority": 2,
            "enabled": True,
            "name": "High-value angry customer → Tier 2",
            "description": "Angry customers with high overdue routed to Tier 2 collections.",
            "category": "Routing",
            "conditions": [
                {"id": "c-hv-sent", "field": "sentiment", "op": "=", "value": "angry"},
                {"id": "c-hv-amt", "field": "overdue_amount", "op": ">", "value": 25000},
            ],
            "action_key": "route_tier2",
            "action_params": {},
        },
        {
            "id": "route-hardship-handoff",
            "priority": 3,
            "enabled": True,
            "name": "Hardship intent → human handoff",
            "description": "Hand off when customer expresses financial hardship.",
            "category": "Handoff",
            "conditions": [{"id": "c-hardship", "field": "intent", "op": "=", "value": "hardship"}],
            "action_key": "handoff_human",
            "action_params": {"team": "Hardship Desk"},
        },
        {
            "id": "route-dispute-queue",
            "priority": 4,
            "enabled": True,
            "name": "Dispute intent → collections queue",
            "description": "Route dispute intents to the specialist collections dispute desk.",
            "category": "Routing",
            "conditions": [{"id": "c-dispute", "field": "intent", "op": "=", "value": "dispute"}],
            "action_key": "route_specialist",
            "action_params": {"team": "Dispute Desk"},
        },
        {
            "id": "route-sentiment-drop",
            "priority": 5,
            "enabled": True,
            "name": "Negative sentiment → supervisor",
            "description": "Escalate when average call sentiment turns strongly negative.",
            "category": "Escalation",
            "conditions": [{"id": "c-sent", "field": "sentiment", "op": "=", "value": "angry"}],
            "action_key": "escalate_supervisor",
            "action_params": {},
        },
        {
            "id": "route-verify-failed",
            "priority": 6,
            "enabled": True,
            "name": "Verification failed → human",
            "description": "Stop upsell and hand off when caller verification fails mid-call.",
            "category": "Throttle",
            "conditions": [
                {"id": "c-vf-status", "field": "verification_status", "op": "=", "value": "failed"},
                {"id": "c-vf-turns", "field": "turn_count", "op": ">=", "value": 4},
            ],
            "action_key": "stop_upsell",
            "action_params": {},
        },
        {
            "id": "route-dnd-sms",
            "priority": 7,
            "enabled": True,
            "name": "DND breach → SMS follow-up only",
            "description": "If DND is on during a voice attempt, close voice and send scheduled SMS.",
            "category": "Compliance",
            "conditions": [
                {"id": "c-dnd", "field": "consent_dnd", "op": "=", "value": True},
                {"id": "c-dnd-ch", "field": "channel", "op": "=", "value": "voice"},
            ],
            "action_key": "send_sms",
            "action_params": {"template": "dnd_followup_v2"},
        },
        {
            "id": "route-high-dpd",
            "priority": 8,
            "enabled": False,
            "name": "High DPD → priority Tier 2 queue",
            "description": "Anyone above 60 DPD goes to Tier 2 regardless of sentiment.",
            "category": "Routing",
            "conditions": [{"id": "c-dpd", "field": "dpd", "op": ">", "value": 60}],
            "action_key": "route_tier2",
            "action_params": {},
        },
    ]
    for rule in routing_library:
        upsert(conn, "routing_rules", {"tenant_id": TENANT_ID, **rule})
    # Sandbox scenarios — Habibi-shaped (sim_persona carries persona + openingBot metadata).
    sandbox_scenarios = [
        {
            "id": "angry-waiver",
            "name": "Angry customer — waiver dispute",
            "sim_persona": {
                "title": "Angry customer — waiver dispute",
                "summary": "Customer is furious about a late fee and demands it be waived immediately.",
                "difficulty": "hard",
                "intents": ["waiver_request", "escalation"],
                "name": "Rahul Sharma",
                "phoneLast4": "4821",
                "product": "Personal Loan",
                "dpd": 12,
                "overdue": 18450,
                "mood": "angry",
                "language": "English",
                "accountNo": "••••4821",
                "dueDate": "the 5th",
                "openingBot": "Hello, this is {agent_name} calling from {bank_name} regarding your loan account. This call is recorded for quality. Am I speaking with {customer_name}?",
            },
            "turns": [
                {"customer": "Yes it's me. Why are you charging me a late fee? This is ridiculous!", "expectedIntent": "waiver_request", "expectedSentiment": -0.7},
                {"customer": "I want it waived. I've been a customer for 5 years.", "expectedIntent": "waiver_request", "expectedSentiment": -0.6},
            ],
        },
        {
            "id": "hardship",
            "name": "Hardship — recent job loss",
            "sim_persona": {
                "title": "Hardship — recent job loss",
                "summary": "Customer lost their job and can't pay this month.",
                "difficulty": "hard",
                "intents": ["hardship", "escalation"],
                "name": "Anil Kumar",
                "phoneLast4": "1177",
                "product": "Home Loan",
                "dpd": 22,
                "overdue": 42800,
                "mood": "distressed",
                "language": "English",
                "accountNo": "••••1177",
                "dueDate": "the 1st",
                "openingBot": "Hello, this is {agent_name} from {bank_name}. This call is recorded. Am I speaking with {customer_name}?",
            },
            "turns": [
                {"customer": "Yes. Look, I lost my job last month. I can't pay right now.", "expectedIntent": "hardship", "expectedSentiment": -0.7},
                {"customer": "How does the deferral work?", "expectedIntent": "hardship", "expectedSentiment": -0.2},
            ],
        },
        {
            "id": "pay-today",
            "name": "Wants to pay today (happy path)",
            "sim_persona": {
                "title": "Wants to pay today (happy path)",
                "summary": "Straightforward: customer wants to clear dues on the call.",
                "difficulty": "easy",
                "intents": ["payment_intent"],
                "name": "Neha Verma",
                "phoneLast4": "5522",
                "product": "Auto Loan",
                "dpd": 3,
                "overdue": 12200,
                "mood": "cooperative",
                "language": "English",
                "accountNo": "••••5522",
                "dueDate": "today",
                "openingBot": "Hi {customer_name}, this is {agent_name} from {bank_name}. This call is recorded. Calling about your auto loan EMI.",
            },
            "turns": [
                {"customer": "Yes, I want to clear it right now.", "expectedIntent": "payment_intent", "expectedSentiment": 0.6},
                {"customer": "Yes, send the UPI link.", "expectedIntent": "payment_intent", "expectedSentiment": 0.7},
            ],
        },
        {
            "id": "legal-threat",
            "name": "Legal threat — auto-escalation trigger",
            "sim_persona": {
                "title": "Legal threat — auto-escalation trigger",
                "summary": "Customer threatens legal action; bot should escalate immediately.",
                "difficulty": "hard",
                "intents": ["escalation"],
                "name": "Vikram Joshi",
                "phoneLast4": "8804",
                "product": "Credit Card",
                "dpd": 45,
                "overdue": 62100,
                "mood": "hostile",
                "language": "English",
                "accountNo": "••••8804",
                "dueDate": "overdue",
                "openingBot": "Hello {customer_name}, {agent_name} from {bank_name}. This call is recorded. Calling regarding your outstanding balance.",
            },
            "turns": [
                {"customer": "If you call me again I'll take you to court!", "expectedIntent": "escalation", "expectedSentiment": -0.9},
            ],
        },
    ]
    for sc in sandbox_scenarios:
        upsert(conn, "sandbox_scenarios", sc)
    upsert(conn, "sandbox_runs", {"id": "SBX-1001", "scenario_id": "hardship", "deployment_id": "DEP-2026-07-PROD", "prompt_version_id": "v1_4", "kb_snapshot_id": "kb-snapshot-2026-07", "started_by_user_id": "priya-nair", "status": "completed", "aggregate_latency_ms": 980, "aggregate_tokens": 640})
    upsert(conn, "sandbox_run_turns", {"id": "SBX-1001-turn-1", "run_id": "SBX-1001", "turn_index": 1, "speaker": "bot", "text": "I understand. Let us find a suitable payment date.", "detected_intent": "hardship", "sentiment_label": "neutral", "retrieved_chunk_ids": ["chunk-rbi-disclosures-1"], "guardrail_flags": [], "latency_ms": 980, "token_count": 64})


def seed_interactions(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    disclosure_rules = {
        "recording": ("rule-recording", "Recording disclosure"),
        "identity": ("rule-identity", "Identity verification"),
        "mini-miranda": ("rule-mini-miranda", "Collections disclosure"),
        "payment": ("rule-payment", "Payment terms disclosure"),
    }
    for rule_id, label in disclosure_rules.values():
        upsert(conn, "compliance_rules", {"id": rule_id, "code": rule_id.upper().replace("-", "_"), "label": label, "severity": "high", "enabled": True})

    # Screen rule IDs (Compliance Risk) — keep legacy disclosure rules above for interaction_disclosures FKs.
    screen_rules = [
        ("r-rec", "RBI-DISC-01", "Missed call recording notice", "high"),
        ("r-mm", "RBI-DISC-02", "Missed Mini-Miranda disclosure", "critical"),
        ("r-dnd-disc", "RBI-DISC-03", "Missed DND / opt-out reminder", "medium"),
        ("r-disp", "RBI-DISC-04", "Missed right-to-dispute notice", "medium"),
        ("r-threat", "PROH-LANG-01", "Threatening language", "critical"),
        ("r-abuse", "PROH-LANG-02", "Abusive / disrespectful tone", "high"),
        ("r-false", "PROH-LANG-03", "False legal claim", "critical"),
        ("r-guarantee", "PROH-LANG-04", "Guarantee-of-outcome claim", "medium"),
        ("r-dnd-win", "CONSENT-01", "Contact outside DND window", "high"),
        ("r-verify", "VERIFY-01", "Skipped identity verification", "high"),
        ("r-distress", "SENT-01", "Customer distress not addressed", "medium"),
    ]
    for rule_id, code, label, severity in screen_rules:
        upsert(conn, "compliance_rules", {"id": rule_id, "code": code, "label": label, "severity": severity, "enabled": True})

    for call in ctx["calls"]:
        call_id = call["id"]
        customer_id = call["customerId"]
        handler = call.get("handledBy") or {}
        if handler.get("kind") == "human":
            handler_kind = "human"
            handler_user_id = slug(handler.get("name") or handler.get("human") or "Priya Nair")
            if handler_user_id not in ctx["users"]:
                handler_user_id = "priya-nair"
            handler_bot_id = None
        else:
            handler_kind = "bot"
            handler_user_id = None
            handler_bot_id = slug(handler.get("bot") or handler.get("name") or "CollectionsBot v2.4")
        duration_sec = parse_duration(call.get("duration"))
        avg_sentiment = call.get("avgSentiment")
        upsert(
            conn,
            "interactions",
            {
                "id": call_id,
                "tenant_id": TENANT_ID,
                "customer_id": customer_id,
                "account_id": call.get("accountId") or ctx["account_by_customer"].get(customer_id),
                "handler_kind": handler_kind,
                "handler_user_id": handler_user_id,
                "handler_bot_id": handler_bot_id,
                "transferred_from_bot_id": "kaia-v2-4" if handler_kind == "human" else None,
                "channel": channel(call.get("channel")),
                "direction": call.get("direction") if call.get("direction") in {"inbound", "outbound"} else "outbound",
                "status": "completed",
                "disposition": call.get("disposition"),
                "primary_intent": seed_primary_intent(call, call_id),
                "query_resolved": "resolved" in (call.get("disposition") or "").lower(),
                "upsell_presented": any("upsell" in str(tag).lower() for tag in call.get("tags", [])),
                "ptp_captured": "ptp" in (call.get("disposition") or "").lower(),
                "avg_sentiment": avg_sentiment,
                "sentiment_label": sentiment_label(avg_sentiment),
                "summary": call.get("summary"),
                "hash": call.get("hash") or stable_hash(call_id),
                "latency_ms": call.get("latencyMs"),
                "rag_hits": call.get("ragHits") or 0,
                "redaction_applied": bool(call.get("redactionApplied", False)),
                "deployment_id": "DEP-2026-07-PROD",
                "started_at": call.get("startedAt"),
                "ended_at": None,
                "duration_sec": duration_sec,
                "source_payload": call,
            },
        )
        upsert(conn, "interaction_participants", {"id": f"{call_id}-customer", "interaction_id": call_id, "participant_kind": "customer", "user_id": None, "bot_id": None, "role": "customer", "joined_at": call.get("startedAt"), "left_at": None})
        upsert(conn, "interaction_participants", {"id": f"{call_id}-handler", "interaction_id": call_id, "participant_kind": handler_kind, "user_id": handler_user_id, "bot_id": handler_bot_id, "role": "primary", "joined_at": call.get("startedAt"), "left_at": None})

        if handler_kind == "human":
            upsert(conn, "interaction_handoffs", {"id": f"handoff-{call_id}", "interaction_id": call_id, "from_kind": "bot", "from_user_id": None, "from_bot_id": "kaia-v2-4", "to_kind": "human", "to_user_id": handler_user_id, "to_bot_id": None, "to_team_id": "card-collections", "reason": seed_handoff_reason(call, call_id, avg_sentiment), "queue": "Card Collections", "requested_at": call.get("startedAt"), "accepted_at": call.get("startedAt"), "completed_at": None})

        for idx, turn in enumerate(call.get("transcript", [])):
            upsert(conn, "interaction_transcript", {"id": f"{call_id}-{turn.get('id') or idx}", "interaction_id": call_id, "turn_index": idx, "speaker": turn.get("speaker") or "bot", "at_sec": turn.get("t") or 0, "text": turn.get("text") or "", "sentiment_delta": None})
        for idx, point in enumerate(call.get("sentimentSeries", [])[:60]):
            score = point.get("v") or 0
            upsert(conn, "interaction_sentiment", {"id": f"{call_id}-sent-{idx}", "interaction_id": call_id, "at_sec": point.get("t") or idx, "score": score, "label": sentiment_label(score)})
        for idx, flag in enumerate(call.get("flags", [])):
            upsert(conn, "interaction_flags", {"id": f"{call_id}-flag-{idx}", "interaction_id": call_id, "flag": str(flag), "severity": "medium"})
        for item in call.get("disclosures", []):
            key = slug(item.get("id") or item.get("label"))
            rule_id = disclosure_rules.get(item.get("id"), (None,))[0]
            upsert(conn, "interaction_disclosures", {"id": f"{call_id}-disc-{key}", "interaction_id": call_id, "rule_id": rule_id, "label": item.get("label") or key, "read_at_sec": item.get("readAtSec"), "read_by_kind": handler_kind, "read_by_user_id": handler_user_id, "read_by_bot_id": handler_bot_id, "read": bool(item.get("read", False))})
        if channel(call.get("channel")) == "voice":
            upsert(conn, "interaction_media", {"id": f"media-{call_id}-audio", "interaction_id": call_id, "kind": "audio", "storage_ref": f"minio://recordings/{TENANT_ID}/{call_id}.wav", "duration_sec": duration_sec, "mime_type": "audio/wav", "size_bytes": (duration_sec or 180) * 32000, "hash": stable_hash(f"audio-{call_id}"), "waveform_ref": f"minio://waveforms/{TENANT_ID}/{call_id}.json"})
        upsert(conn, "identity_verifications", {"id": f"verify-{call_id}", "interaction_id": call_id, "customer_id": customer_id, "method": "phone_match", "status": "verified", "attempt_count": 1, "verified_at": call.get("startedAt"), "failure_reason": None})
        if channel(call.get("channel")) in {"whatsapp", "sms", "email", "chat"}:
            conversation_id = f"CV-{call_id}"
            # Stored statuses are viewer-neutral. "Mine" is derived in the API as
            # assigned_user_id === current actor (GET /me) — never stored as 'mine'.
            if handler_kind == "human":
                conv_status = "assigned"
                conv_assignee = handler_user_id
            elif avg_sentiment is not None and float(avg_sentiment) < -0.25:
                conv_status = "escalated"
                conv_assignee = None
            elif call.get("flags") or (call.get("disposition") or "").lower() in {
                "dispute",
                "callback",
                "escalate",
                "needs_human",
            }:
                conv_status = "needs_human"
                conv_assignee = None
            else:
                conv_status = "bot"
                conv_assignee = None
            upsert(
                conn,
                "conversations",
                {
                    "id": conversation_id,
                    "interaction_id": call_id,
                    "customer_id": customer_id,
                    "assigned_user_id": conv_assignee,
                    "status": conv_status,
                    "channel": channel(call.get("channel")),
                },
            )
            for idx, turn in enumerate(call.get("transcript", [])):
                raw_speaker = turn.get("speaker") or "bot"
                # Legacy transcript seeds used "human"; Inbox vocabulary is "agent".
                if raw_speaker == "human":
                    sender = "agent"
                elif raw_speaker in {"customer", "bot", "agent", "system"}:
                    sender = raw_speaker
                else:
                    sender = "bot"
                upsert(
                    conn,
                    "messages",
                    {
                        "id": f"MSG-{call_id}-{idx}",
                        "conversation_id": conversation_id,
                        "sender": sender,
                        "body": turn.get("text") or "",
                        "delivery_status": "delivered",
                        "provider_ref": None,
                        "sent_at": call.get("startedAt"),
                    },
                )
        if avg_sentiment is not None and float(avg_sentiment) < -0.25:
            upsert(conn, "live_alerts", {"id": f"alert-{call_id}", "interaction_id": call_id, "kind": "sentiment_drop", "severity": "high", "reason": "Negative sentiment detected", "acknowledged_by_user_id": "priya-nair", "acknowledged_at": call.get("startedAt")})
        upsert(conn, "retrieval_logs", {"id": f"retrieval-{call_id}", "interaction_id": call_id, "sandbox_run_id": None, "query": call.get("summary") or call_id, "top_chunks": [{"id": "chunk-rbi-disclosures-1", "score": 0.82}], "latency_ms": call.get("latencyMs"), "selected_answer_source": "kb-rbi-disclosures"})
        upsert(conn, "routing_rule_executions", {"id": f"routing-{call_id}", "rule_id": "route-sentiment-drop", "interaction_id": call_id, "sandbox_run_id": None, "context": {"avgSentiment": avg_sentiment}, "result": "matched" if avg_sentiment is not None and float(avg_sentiment) < -0.25 else "skipped", "action_taken": "handoff" if handler_kind == "human" else None, "evaluated_at": call.get("startedAt")})

    for canned in (
        {
            "id": "canned-greeting",
            "label": "Greeting",
            "body": "Hi, this is Priya from HDFC Collections. How can I help you today?",
            "channel": "whatsapp",
        },
        {
            "id": "canned-verify",
            "label": "Verify identity",
            "body": "For your security, can you confirm your registered date of birth and the last 4 digits of your account?",
            "channel": "whatsapp",
        },
        {
            "id": "canned-payment-link",
            "label": "Payment link",
            "body": "I'm sending you a secure payment link now. It's valid for the next 30 minutes.",
            "channel": "whatsapp",
        },
        {
            "id": "canned-late-fee",
            "label": "Late-fee waiver policy",
            "body": "As a first-time waiver, we can apply a one-time reversal of ₹500 on the late fee. Would you like me to raise the request?",
            "channel": "whatsapp",
        },
        {
            "id": "canned-escalation",
            "label": "Escalation notice",
            "body": "I understand your concern. I'm escalating this to my supervisor and someone will reach out within 24 hours.",
            "channel": "whatsapp",
        },
    ):
        upsert(
            conn,
            "canned_responses",
            {
                **canned,
                "tenant_id": TENANT_ID,
                "team_id": "card-collections",
                "enabled": True,
                "created_by_user_id": "priya-nair",
            },
        )
    first_call = ctx["calls"][0]["id"]
    upsert(conn, "ai_response_suggestions", {"id": "suggestion-payment-link", "conversation_id": None, "interaction_id": first_call, "transcript_turn_id": None, "suggestion_text": "Offer a partial payment and schedule a reminder.", "source": "kb", "accepted": False, "accepted_by_user_id": None, "accepted_at": None})
    upsert(conn, "supervisor_actions", {"id": "sup-action-1", "interaction_id": first_call, "supervisor_user_id": "priya-nair", "action": "listen_in", "target_user_id": None, "target_bot_id": "kaia-v2-4", "note": "Sample supervision event"})


def seed_collections_and_sales(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    detailed = ctx["detailed_customers"]
    upsert(conn, "document_templates", {"id": "template-statement", "name": "Account Statement", "doc_type": "statement", "preview_lines": ["Customer name", "Account summary", "Ledger"]})
    upsert(conn, "document_templates", {"id": "template-noc", "name": "No Objection Certificate", "doc_type": "noc", "preview_lines": ["Customer name", "Closure confirmation"]})

    calls_by_customer: dict[str, list[dict[str, Any]]] = {}
    for call in ctx["calls"]:
        calls_by_customer.setdefault(call["customerId"], []).append(call)

    for customer_id, source in detailed.items():
        account_id = ctx["account_by_customer"][customer_id]
        origin_call = (calls_by_customer.get(customer_id) or ctx["calls"])[0]["id"]
        first_plan_id = None
        for idx, promise in enumerate(source.get("promises", [])):
            plan_id = None
            if idx == 0:
                plan_id = f"PLAN-{promise['id']}"
                first_plan_id = plan_id
                upsert(conn, "payment_plans", {"id": plan_id, "customer_id": customer_id, "account_id": account_id, "status": "active", "total_amount": (promise.get("amount") or 0) * 3})
            handler = promise.get("handler")
            if isinstance(handler, dict) and handler.get("kind") == "bot":
                owner_kind, owner_user_id, owner_bot_id = "bot", None, slug(handler.get("bot") or "CollectionsBot v2.4")
            elif isinstance(handler, dict):
                owner_kind, owner_user_id, owner_bot_id = "human", slug(handler.get("name") or handler.get("human") or source.get("assignedTo")), None
                if owner_user_id not in ctx["users"]:
                    owner_user_id = "priya-nair"
            elif handler and "bot" in str(handler).lower():
                owner_kind, owner_user_id, owner_bot_id = "bot", None, "collectionsbot-v2-4"
            else:
                owner_kind, owner_user_id, owner_bot_id = "human", slug(str(handler or source.get("assignedTo") or "Priya Nair")), None
                if owner_user_id not in ctx["users"]:
                    owner_user_id = "priya-nair"
            upsert(conn, "promises", {"id": promise["id"], "customer_id": customer_id, "account_id": account_id, "interaction_id": origin_call, "owner_kind": owner_kind, "owner_user_id": owner_user_id, "owner_bot_id": owner_bot_id, "plan_id": plan_id, "amount": promise.get("amount") or 0, "promised_at": promise.get("promisedDate") or promise.get("createdAt"), "status": promise_status(promise.get("status")), "reminder_status": promise.get("reminderStatus") if promise.get("reminderStatus") in {"off", "queued", "scheduled", "sent", "acknowledged", "failed"} else "scheduled", "paid_amount": promise.get("paidAmount") or 0, "channel": channel(promise.get("channel"))})
            if first_plan_id and idx == 0:
                for installment_index in range(1, 4):
                    upsert(conn, "promise_installments", {"id": f"{first_plan_id}-{installment_index}", "plan_id": first_plan_id, "installment_index": installment_index, "due_date": promise.get("promisedDate") or "2026-07-22T10:00:00Z", "amount": promise.get("amount") or 0, "paid_status": promise_status(promise.get("status")), "paid_at": None})
            upsert(conn, "promise_reminders", {"id": f"reminder-{promise['id']}", "promise_id": promise["id"], "channel": "whatsapp", "scheduled_at": promise.get("promisedDate"), "sent_at": None, "status": "scheduled", "provider_delivery_id": None})
            if idx == 0:
                upsert(conn, "followups", {"id": f"FU-{promise['id']}", "promise_id": promise["id"], "lead_id": None, "customer_id": customer_id, "assignee_user_id": slug(source.get("assignedTo") or "Priya Nair"), "status": "open", "priority": "high", "due_at": promise.get("promisedDate") or "2026-07-22T10:00:00Z", "note": "Promise follow-up"})
        for dispute in source.get("disputes", []):
            dtype = dispute.get("type") if dispute.get("type") in {"paid_already", "wrong_amount", "not_my_account", "fee_waiver", "duplicate_charge", "fraud"} else "wrong_amount"
            upsert(conn, "disputes", {"id": dispute["id"], "customer_id": customer_id, "account_id": account_id, "interaction_id": origin_call, "assignee_user_id": slug(dispute.get("assignee")) if dispute.get("assignee") and dispute.get("assignee") != "Unassigned" else None, "type": dtype, "disputed_amount": dispute.get("amount"), "source": "bot", "status": dispute_status(dispute.get("status")), "priority": "high", "resolution_code": None, "sla_due_at": "2026-07-24T10:00:00Z", "transcript_snippet": dispute.get("transcriptSnippet")})
            upsert(conn, "dispute_evidence", {"id": f"evidence-{dispute['id']}", "dispute_id": dispute["id"], "storage_ref": f"minio://dispute-evidence/{TENANT_ID}/{dispute['id']}.pdf", "filename": f"{dispute['id']}.pdf", "mime_type": "application/pdf", "size_bytes": 128000, "hash": stable_hash(dispute["id"]), "uploaded_by_user_id": slug(dispute.get("assignee")) if dispute.get("assignee") and dispute.get("assignee") != "Unassigned" else None})
        for doc in source.get("documents", []):
            template_id = "template-statement" if "statement" in (doc.get("type") or "").lower() else "template-noc"
            upsert(conn, "document_requests", {"id": doc["id"], "customer_id": customer_id, "account_id": account_id, "template_id": template_id, "interaction_id": origin_call, "assignee_user_id": slug(source.get("assignedTo") or "Priya Nair"), "doc_type": doc.get("type") or "statement", "delivery_channel": channel(doc.get("deliveryChannel")) if channel(doc.get("deliveryChannel")) in {"whatsapp", "email", "sms"} else "email", "delivery_target": None, "status": doc_status(doc.get("status")), "attempts": 1, "priority": "normal", "sla_due_at": "2026-07-23T10:00:00Z"})
            upsert(conn, "document_files", {"id": f"FILE-{doc['id']}", "request_id": doc["id"], "storage_ref": f"minio://documents/{TENANT_ID}/{doc['id']}.pdf", "filename": f"{doc['id']}.pdf", "mime_type": "application/pdf", "size_bytes": 96000, "hash": stable_hash(doc["id"]), "generated_at": doc.get("requestedAt") or "2026-07-21T10:00:00Z"})
            upsert(conn, "document_delivery_attempts", {"id": f"delivery-{doc['id']}", "request_id": doc["id"], "file_id": f"FILE-{doc['id']}", "channel": "email", "target": None, "provider": "mock-email", "provider_message_id": f"msg-{doc['id']}", "attempt_number": 1, "status": "sent" if doc_status(doc.get("status")) == "sent" else "queued", "error": None, "sent_at": doc.get("requestedAt")})

    for idx, call in enumerate(ctx["calls"][:6], start=1):
        # Stagger across today + next few days so the Callbacks calendar isn't empty.
        day = 22 + ((idx - 1) // 2)  # 22,22,23,23,24,24 July 2026
        hour = 11 + (idx % 4) * 2
        scheduled = f"2026-07-{day:02d}T{hour:02d}:00:00+05:30"
        upsert(conn, "callbacks", {"id": f"CB-{idx:04d}", "customer_id": call["customerId"], "account_id": call.get("accountId") or ctx["account_by_customer"].get(call["customerId"]), "interaction_id": call["id"], "assignee_user_id": "priya-nair", "team_id": "card-collections" if idx % 2 else "retail-collections", "reason": "general", "scheduled_at": scheduled, "window_mins": 30 if idx % 2 else 60, "dnd_active": False, "status": "reminded" if idx == 2 else "scheduled", "disposition": None, "priority": "high" if idx in {2, 4} else "normal", "transcript_snippet": "\"Please call me back, the bot couldn't answer my question.\"", "outcome_notes": None, "sla_due_at": scheduled})
        upsert(conn, "callback_reminders", {"id": f"CBR-{idx:04d}", "callback_id": f"CB-{idx:04d}", "channel": "whatsapp", "scheduled_at": scheduled, "sent_at": None, "status": "scheduled"})

    for lead in ctx["leads"]:
        offer = lead.get("offer") or {}
        product_id = offer.get("productId") or slug(offer.get("label"))
        owner_id = slug(lead.get("owner")) if lead.get("owner") and lead.get("owner") != "Unassigned" else None
        team_id = slug(lead.get("team")) if lead.get("team") else None
        source_call_id = lead.get("sourceCallId")
        if source_call_id not in {call["id"] for call in ctx["calls"]}:
            source_call_id = None
        upsert(conn, "leads", {"id": lead["id"], "customer_id": lead["customerId"], "account_id": lead.get("accountId") or ctx["account_by_customer"].get(lead["customerId"]), "interaction_id": source_call_id, "product_id": product_id if product_id in ctx["products"] else None, "owner_user_id": owner_id, "team_id": team_id, "stage": lead_stage(lead.get("stage")), "source": lead.get("source"), "sentiment_at_capture": sentiment_label(label=lead.get("sentimentAtCapture")), "sentiment_score": lead.get("sentimentScore"), "estimated_value": lead.get("estimatedValue"), "won_amount": lead.get("wonAmount"), "loss_reason": lead.get("lossReason"), "offer_amount": offer.get("indicativeAmount"), "offer_roi": offer.get("indicativeROI"), "priority": priority(lead.get("priority")), "captured_at": lead.get("capturedAt"), "transcript_snippet": lead.get("transcriptSnippet")})
        for idx, flag in enumerate(lead.get("eligibilityFlags", [])):
            upsert(conn, "lead_eligibility", {"id": f"{lead['id']}-elig-{idx}", "lead_id": lead["id"], "rule_id": f"rule-{product_id}" if product_id else None, "label": flag.get("label") or f"Flag {idx}", "passed": bool(flag.get("ok", False)), "reason": flag.get("detail")})
        upsert(conn, "followups", {"id": f"FU-{lead['id']}", "promise_id": None, "lead_id": lead["id"], "customer_id": lead["customerId"], "assignee_user_id": owner_id, "status": "open", "priority": priority(lead.get("priority")), "due_at": "2026-07-23T10:00:00+05:30", "note": "Lead follow-up"})


def seed_compliance_qa_redaction(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    # Full screen rubric — IDs must match Habibi/src/data/qa-seed.ts defaultRubric.
    upsert(conn, "qa_rubrics", {"id": "rubric-v1", "name": "Collections Interaction Rubric", "version": "v1.0", "enabled": True})
    rubric_sections = [
        ("empathy", "Empathy & Tone", 20, [
            ("emp-acknowledge", "Acknowledged customer situation", "Reflected feeling before pushing agenda.", 50, False),
            ("emp-tone", "Calm, respectful tone maintained", "No sarcasm, no raised voice, no interruption.", 50, False),
        ]),
        ("resolution", "Resolution & Accuracy", 30, [
            ("res-identify", "Correctly identified customer need", "Root need captured within 2 turns.", 30, False),
            ("res-answer", "Accurate answer / next-step", "Dues, EMI, dispute path stated correctly.", 40, False),
            ("res-close", "Confirmed resolution before closing", "Summarised action + expectation.", 30, False),
        ]),
        ("compliance", "Compliance", 25, [
            ("cmp-recording", "Recording notice given", "Within first 20 seconds.", 25, True),
            ("cmp-miranda", "Mini-Miranda debt disclosure", "Read verbatim before dues discussion.", 30, True),
            ("cmp-dnd", "DND / opt-out honoured", "No contact outside allowed window; opt-out respected.", 25, True),
            ("cmp-language", "No prohibited language", "No threats, no third-party disclosure.", 20, True),
        ]),
        ("script", "Script Adherence", 15, [
            ("scr-verify", "Identity verification followed", "DOB / OTP as per SOP.", 50, False),
            ("scr-closing", "Approved closing script used", "Includes ticket ID + next step.", 50, False),
        ]),
        ("upsell", "Upsell & Value", 10, [
            ("ups-eligibility", "Checked eligibility before pitch", "Only pitched if flags green.", 50, False),
            ("ups-pitch", "Contextual, non-pushy pitch", "Tied to customer's stated need.", 50, False),
        ]),
    ]
    all_criteria: list[str] = []
    for section_id, label, weight, criteria in rubric_sections:
        upsert(conn, "qa_rubric_sections", {"id": section_id, "rubric_id": "rubric-v1", "name": label, "weight": weight})
        for cid, clabel, desc, cweight, critical in criteria:
            upsert(
                conn,
                "qa_rubric_criteria",
                {
                    "id": cid,
                    "section_id": section_id,
                    "label": clabel,
                    "description": desc,
                    "weight": cweight,
                    "critical_fail": critical,
                },
            )
            all_criteria.append(cid)

    for idx, call in enumerate(ctx["calls"][:24], start=1):
        status = "unscored" if idx <= 6 else "ai_draft" if idx <= 16 else "final"
        handler = call.get("handledBy") or {}
        bot_name = handler.get("bot") or "Kaia v2.4"
        agent_name = handler.get("agent")
        bot_id = slug(bot_name)
        subject_bot = bot_id if handler.get("kind") == "bot" and bot_id in ctx["bots"] else (None if handler.get("kind") == "human" else "kaia-v2-4")
        subject_user = None
        if handler.get("kind") == "human":
            # Prefer a real roster user; fall back to priya-nair.
            subject_user = "priya-nair"
            for uid, uname in [("priya-nair", "Priya Nair"), ("sara-khan", "Sara Khan"), ("arjun-mehta", "Arjun Mehta")]:
                if agent_name and uname.lower() in str(agent_name).lower():
                    subject_user = uid
                    break
        scorecard_id = f"qa-{call['id']}"
        upsert(
            conn,
            "qa_scorecards",
            {
                "id": scorecard_id,
                "interaction_id": call["id"],
                "rubric_id": "rubric-v1",
                "subject_user_id": subject_user,
                "subject_bot_id": subject_bot if subject_user is None else None,
                "reviewer_user_id": "priya-nair" if status != "unscored" else None,
                "status": status,
                "total_score": None,
                "band": None,
                "scored_at": "2026-07-21T12:00:00Z" if status == "final" else None,
            },
        )
        for crit in all_criteria:
            ai = 3 + (abs(hash(f"{scorecard_id}-{crit}-ai")) % 3)
            final = 0 if status == "unscored" else (ai if status == "ai_draft" else max(0, min(5, ai + (abs(hash(f"{scorecard_id}-{crit}-f")) % 3) - 1)))
            upsert(
                conn,
                "qa_scorecard_entries",
                {
                    "id": f"{scorecard_id}-{crit}",
                    "scorecard_id": scorecard_id,
                    "criterion_id": crit,
                    "ai_suggested_score": ai,
                    "final_score": final,
                    "note": "Coach reviewed — see comments." if status == "final" and abs(hash(f"{scorecard_id}-{crit}-n")) % 4 == 0 else None,
                    "accepted": (final == ai) if status == "final" else None,
                },
            )
        if idx <= 3:
            upsert(
                conn,
                "violations",
                {
                    "id": f"V-{idx:05d}",
                    "interaction_id": call["id"],
                    "customer_id": call["customerId"],
                    "rule_id": "r-rec",
                    "actor_kind": "bot",
                    "actor_user_id": None,
                    "actor_bot_id": "kaia-v2-4",
                    "status": "open",
                    "assignee_user_id": "priya-nair",
                    "description": "Disclosure \"Missed call recording notice\" was not read to the customer during the call.",
                    "at_sec": 0,
                },
            )
    first_call = ctx["calls"][0]
    upsert(conn, "coaching_actions", {"id": "coach-1", "subject_user_id": None, "subject_bot_id": "kaia-v2-4", "scorecard_id": f"qa-{first_call['id']}", "interaction_id": first_call["id"], "action": "Review disclosure phrasing", "status": "open", "due_at": "2026-07-25T10:00:00Z"})
    upsert(conn, "calibration_sessions", {"id": "calibration-1", "interaction_id": first_call["id"], "rubric_id": "rubric-v1", "status": "open"})
    upsert(conn, "calibration_reviewer_scores", {"id": "calibration-1-priya", "session_id": "calibration-1", "reviewer_user_id": "priya-nair", "scores": {"cmp-recording": 4}, "notes": "Aligned", "variance_from_target": 2.0})

    for pii_type in ["card", "pan", "phone", "email", "address", "dob", "account", "ifsc", "aadhaar", "custom"]:
        upsert(conn, "redaction_rule_configs", {"id": f"redact-{pii_type}", "tenant_id": TENANT_ID, "pii_type": pii_type, "replacement": f"[{pii_type.upper()}]", "enabled": True})
    for call in [c for c in ctx["calls"] if c.get("redactionApplied")][:8]:
        redaction_id = f"RX-{call['id']}"
        upsert(conn, "redaction_records", {"id": redaction_id, "interaction_id": call["id"], "customer_id": call["customerId"], "reviewed": True, "reviewed_by_user_id": "priya-nair", "reviewed_at": "2026-07-21T12:00:00Z"})
        upsert(conn, "pii_findings", {"id": f"pii-{call['id']}-phone", "redaction_id": redaction_id, "type": "phone", "masked": "+91 98XXXXXX42", "confidence": 0.98, "accepted": True, "transcript_turn_id": None, "start_offset": None, "end_offset": None})
        if channel(call.get("channel")) == "voice":
            upsert(conn, "redaction_audio_segments", {"id": f"mute-{call['id']}-phone", "redaction_id": redaction_id, "media_id": f"media-{call['id']}-audio", "finding_id": f"pii-{call['id']}-phone", "at_sec": 12, "duration_sec": 4, "muted": True})


def seed_admin_analytics_crosscutting(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    upsert(conn, "providers", {"id": "provider-whatsapp", "name": "WhatsApp Business", "category": "messaging"})
    upsert(conn, "providers", {"id": "provider-email", "name": "SMTP Relay", "category": "messaging"})
    upsert(conn, "provider_fields", {"id": "field-whatsapp-token", "provider_id": "provider-whatsapp", "field_key": "token", "label": "API Token", "secret": True, "required": True})
    upsert(conn, "provider_configs", {"id": "config-whatsapp-prod", "provider_id": "provider-whatsapp", "tenant_id": TENANT_ID, "environment": "production", "values": {"phoneNumberId": "vault://whatsapp/phone-number-id"}, "health": "healthy", "latency_ms": 120, "enabled": True, "credential_ref": "vault://whatsapp/token"})
    upsert(conn, "provider_config_versions", {"id": "config-whatsapp-prod-v1", "config_id": "config-whatsapp-prod", "version": 1, "values": {"credentialRef": "vault://whatsapp/token"}, "changed_by_user_id": "priya-nair"})
    upsert(conn, "integration_test_logs", {"id": "test-whatsapp-prod-1", "config_id": "config-whatsapp-prod", "status": "success", "latency_ms": 120, "payload_summary": {"ping": "ok"}, "error": None})
    upsert(conn, "webhook_endpoints", {"id": "wh-crm-events", "tenant_id": TENANT_ID, "target_system": "Core CRM", "url": "https://crm.internal/events", "status": "active", "signing_algorithm": "hmac-sha256", "secret_ref": "vault://webhooks/crm"})
    upsert(conn, "webhook_endpoint_headers", {"id": "wh-crm-tenant-header", "endpoint_id": "wh-crm-events", "header_key": "X-Tenant", "header_value": TENANT_ID})
    upsert(conn, "webhook_retry_policies", {"id": "wh-crm-retry", "endpoint_id": "wh-crm-events", "max_attempts": 5, "backoff_strategy": "exponential", "max_event_age_sec": 86400})
    for event in ["interaction.completed", "promise.created", "dispute.created", "document.sent", "lead.created"]:
        upsert(conn, "event_types", {"id": f"event-{slug(event)}", "name": event, "description": event.replace(".", " ")})
        insert_ignore(conn, "INSERT INTO webhook_subscriptions (endpoint_id, event_type_id) VALUES (%(endpoint_id)s, %(event_type_id)s) ON CONFLICT DO NOTHING", {"endpoint_id": "wh-crm-events", "event_type_id": f"event-{slug(event)}"})
    upsert(conn, "webhook_deliveries", {"id": "dlv-0001", "endpoint_id": "wh-crm-events", "event_type_id": "event-interaction-completed", "payload": {"interactionId": ctx["calls"][0]["id"]}, "response_body": "ok", "http_status": 200, "attempt_number": 1, "latency_ms": 80, "status": "success", "next_retry_at": None})
    upsert(conn, "billing_services", {"id": "llm_gpt4o", "name": "Azure OpenAI GPT-4o", "unit": "1K tokens", "unit_cost_inr": 0.42, "provider": "Azure", "category": "LLM", "color": "#3b82f6"})
    upsert(conn, "billing_services", {"id": "stt_az", "name": "Azure Speech STT", "unit": "minute", "unit_cost_inr": 0.32, "provider": "Azure", "category": "Voice", "color": "#0ea5e9"})
    upsert(conn, "billing_usage_daily", {"id": "usage-2026-07-21-llm", "service_id": "llm_gpt4o", "tenant_id": TENANT_ID, "environment": "production", "usage_date": "2026-07-21", "units": 11428.57, "cost_inr": 4800})
    upsert(conn, "invoices", {"id": "INV-2026-07", "tenant_id": TENANT_ID, "invoice_month": "2026-07", "environment": "production", "total_inr": 4800, "status": "draft", "issued_at": "2026-08-01"})
    upsert(conn, "invoice_line_items", {"id": "INV-2026-07-llm", "invoice_id": "INV-2026-07", "service_id": "llm_gpt4o", "units": 11428.57, "unit_cost_inr": 0.42, "amount_inr": 4800})
    upsert(conn, "budgets", {"id": "budget-prod-2026-07", "tenant_id": None, "environment": "production", "month": "2026-07", "amount_inr": 600000})
    upsert(conn, "budget_rules", {"id": "r1", "budget_id": "budget-prod-2026-07", "threshold_pct": 70, "action_channel": "email:finance-ops", "severity": "info", "action": "Notify finance-ops", "channels": ["email:finance-ops"]})
    upsert(conn, "budget_alert_events", {"id": "budget-alert-1", "budget_rule_id": "r1", "triggered_at": "2026-07-21T12:00:00Z", "spend_inr": 420000, "message": "Prod spend crossed 70% of monthly cap"})

    upsert(conn, "analytics_daily", {"id": "analytics-2026-07-21", "tenant_id": TENANT_ID, "metric_date": "2026-07-21", "resolved_calls": 28, "escalations": 6, "ptp_count": 12, "avg_sentiment": 0.08})
    upsert(conn, "intent_aggregates", {"id": "intent-payment-2026-07-21", "tenant_id": TENANT_ID, "metric_date": "2026-07-21", "intent": "payment", "sessions": 18, "containment_rate": 0.72, "escalation_rate": 0.18, "abandonment_rate": 0.03, "avg_turns": 5.4, "avg_latency_ms": 870, "avg_sentiment": 0.11})
    upsert(conn, "escalation_reasons", {"id": "esc-sentiment-drop", "tenant_id": TENANT_ID, "reason": "sentiment_drop", "count": 6, "trend": -0.04})

    # Unanswered / RAG-miss gaps for Bot Analytics (live read — not the stub aggregate tables).
    unanswered_gaps = [
        ("uq-settlement-letter", "Can I get a settlement letter?", 9, "2026-07-21T11:00:00Z", "statement", "kb", True),
        ("uq-instalments-cibil", "Can I pay in three instalments after due date without CIBIL hit?", 84, "2026-07-21T09:00:00Z", "late-fee", "kb", False),
        ("uq-min-pay-interest", "What's the interest rate if I only pay minimum?", 71, "2026-07-21T10:30:00Z", "emi", "prompt", True),
        ("uq-noc-closure", "How do I get a NOC after full closure?", 63, "2026-07-20T14:00:00Z", "statement", "kb", False),
        ("uq-waiver-job-loss", "Can waiver be given if job loss proof provided?", 58, "2026-07-21T08:15:00Z", "late-fee", "both", False),
        ("uq-foreclosure-charges", "Explain foreclosure charges for personal loan", 52, "2026-07-19T16:40:00Z", "emi", "prompt", True),
        ("uq-emi-debit-date", "How to change EMI debit date?", 47, "2026-07-20T11:20:00Z", "emi", "kb", False),
        ("uq-moratorium-medical", "Is there a moratorium option for medical emergency?", 41, "2026-07-18T12:00:00Z", "late-fee", "kb", False),
        ("uq-late-fee-variance", "Why was late fee ₹599 vs standard ₹450?", 39, "2026-07-21T07:45:00Z", "dispute", "prompt", True),
        ("uq-overdue-to-emi", "Can I convert overdue balance to EMI?", 34, "2026-07-19T09:30:00Z", "topup", "both", False),
    ]
    for qid, question, hits, last_seen, top_intent, fix, has_kb in unanswered_gaps:
        upsert(
            conn,
            "unanswered_questions",
            {
                "id": qid,
                "tenant_id": TENANT_ID,
                "question": question,
                "hit_count": hits,
                "last_seen_at": last_seen,
                "suggested_fix_type": fix,
                "top_intent": top_intent,
            },
        )
        if has_kb:
            link_id = "gap-settlement-letter" if qid == "uq-settlement-letter" else f"gap-{qid}"
            upsert(
                conn,
                "analytics_kb_gap_links",
                {
                    "id": link_id,
                    "unanswered_question_id": qid,
                    "kb_document_id": "kb-rbi-disclosures",
                    "faq_pair_id": "faq-payment-link",
                    "prompt_version_id": "v1_4",
                    "routing_rule_id": None,
                },
            )

    upsert(conn, "export_jobs", {"id": "EX-0001", "actor_user_id": "priya-nair", "format": "zip", "scope": {"from": "2026-07-01", "to": "2026-07-21"}, "watermark": "HDFC Retail", "status": "completed", "storage_ref": f"minio://export-bundles/{TENANT_ID}/EX-0001.zip"})
    first_redaction = conn.execute("SELECT id FROM redaction_records ORDER BY id LIMIT 1").fetchone()
    if first_redaction:
        insert_ignore(conn, "INSERT INTO export_job_records (export_job_id, redaction_id) VALUES (%(export_job_id)s, %(redaction_id)s) ON CONFLICT DO NOTHING", {"export_job_id": "EX-0001", "redaction_id": first_redaction[0]})

    for call in ctx["calls"][:20]:
        upsert(conn, "activity_events", {"id": f"activity-{call['id']}", "tenant_id": TENANT_ID, "entity_type": "interaction", "entity_id": call["id"], "at": call.get("startedAt"), "actor_kind": "bot", "actor_user_id": None, "actor_bot_id": "kaia-v2-4", "kind": "interaction_completed", "label": "Interaction completed", "note": call.get("summary"), "tone": sentiment_label(call.get("avgSentiment")), "payload": {"disposition": call.get("disposition")}})
    upsert(conn, "audit_log", {"id": "audit-seed-1", "tenant_id": TENANT_ID, "actor_user_id": "priya-nair", "action": "seed.database", "entity_type": "tenant", "entity_id": TENANT_ID, "payload": {"source": "backend/seed/*.json"}})


if __name__ == "__main__":
    main()
