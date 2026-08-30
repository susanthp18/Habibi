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

import authz


BASE = Path(__file__).parent
SEED_DIR = BASE / "seed"
DEFAULT_DSN = "postgresql://collections:collections@localhost:5432/collections"
TENANT_ID = "hdfc.retail"


def _is_prod() -> bool:
    """Same production detection as scripts/seed_demo.py.

    Falls back to .env: DATABASE_URL is resolved the same way below, so a
    deployment that only sets APP_ENV in .env would otherwise be seen as `dev`
    while pointing at the production database.
    """
    return (os.getenv("APP_ENV") or read_env("APP_ENV") or "dev").strip().lower() in {
        "prod",
        "production",
    }


def main() -> None:
    # seed_demo.py guards this, but seed_postgres is also invoked directly
    # (`python seed_postgres.py`, compose exec, ad-hoc shells). Refuse before
    # loading exports or opening a connection — this writes synthetic customers,
    # calls and consent records over whatever is in the target database.
    if _is_prod():
        raise SystemExit(
            "Refusing to seed demo data when APP_ENV=production|prod. "
            "Unset APP_ENV or set APP_ENV=dev for local demos."
        )

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
            seed_skills(conn)
            seed_mcp_phase3(conn)
            seed_phase4(conn)
            seed_phase5(conn)
            seed_phase6(conn)
            seed_eval_catalog(conn)
            seed_interactions(conn, ctx)
            seed_collections_and_sales(conn, ctx)
            # After collections/sales: it re-dates rows those functions wrote.
            seed_recent_activity(conn, ctx)
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


# Postgres TEXT[] columns, by table. psycopg adapts a bare Python list to an
# array and a Json-wrapped one to jsonb, and the two are not interchangeable —
# `jsonable` wrapping everything is right for the jsonb columns that dominate
# this schema and wrong for these. Keep this in step with `TEXT[]` in sql/.
ARRAY_COLUMNS: dict[str, frozenset[str]] = {
    "products": frozenset({"channels"}),
    "product_campaigns": frozenset({"segment_in", "risk_not_in"}),
    "skill_versions": frozenset({"allowed_tools"}),
    "mcp_keys": frozenset({"scopes"}),
    "mcp_connectors": frozenset({"allow_prefixes", "data_class"}),
    "a2a_partners": frozenset({"allowed_skills"}),
}


# ---------------------------------------------------------------------------
# Offer catalog
#
# This depth used to live in Habibi/src/data/upsell-seed.ts, where nothing
# reconciled it against the products table that check_product_eligibility
# actually reads — the UI could offer a product id the server had never heard
# of. It belongs here, and /products serves it to the UI.
#
# ticket_min / ticket_max are load-bearing, not decoration: the recommender
# derives its indicative amount from them, and a NULL band was what produced
# leads worth NULL that rendered as ₹NaN pipeline totals.
# ---------------------------------------------------------------------------

PRODUCT_CATALOG: dict[str, dict[str, Any]] = {
    "topup-loan": {
        "category": "Loan", "family": "unsecured_loan",
        "ticket_min": 50_000, "ticket_max": 1_500_000,
        "roi": "10.75% p.a.", "roi_numeric": 10.75,
        "tenor_months_min": 12, "tenor_months_max": 60, "margin_score": 0.75,
        "description": "Additional loan on an existing personal loan account for eligible customers.",
    },
    "debt-consolidation": {
        "category": "Loan", "family": "unsecured_loan",
        "ticket_min": 100_000, "ticket_max": 2_500_000,
        "roi": "11.5% p.a.", "roi_numeric": 11.5,
        "tenor_months_min": 24, "tenor_months_max": 84, "margin_score": 0.70,
        "description": "Combine multiple outstanding balances into a single lower-EMI loan.",
    },
    "cc-limit-upgrade": {
        "category": "Card", "family": "revolving_credit",
        "ticket_min": 25_000, "ticket_max": 500_000,
        "roi": "36% APR (revolving)", "roi_numeric": 36.0, "margin_score": 0.85,
        "description": "Higher spend limit on an existing credit card; gated by utilisation and bureau score.",
    },
    "personal-loan": {
        "category": "Loan", "family": "unsecured_loan",
        "ticket_min": 50_000, "ticket_max": 2_000_000,
        "roi": "12.5% p.a.", "roi_numeric": 12.5,
        "tenor_months_min": 12, "tenor_months_max": 72, "margin_score": 0.70,
        "description": "Unsecured personal loan pre-approved for salaried customers.",
    },
    "gold-loan": {
        "category": "Loan", "family": "secured_loan",
        "ticket_min": 25_000, "ticket_max": 1_000_000,
        "roi": "9.5% p.a.", "roi_numeric": 9.5,
        "tenor_months_min": 6, "tenor_months_max": 36, "margin_score": 0.55,
        "description": "Secured loan against gold ornaments at branch valuation.",
    },
    "bundled-insurance": {
        "category": "Insurance", "family": "protection",
        "ticket_min": 5_000, "ticket_max": 50_000,
        "roi": "N/A (premium)", "margin_score": 0.90,
        "tenor_months_min": 12, "tenor_months_max": 12,
        "description": "Loan-linked accident + hospitalisation cover bundled with an existing product.",
    },
    "credit-card": {
        "category": "Card", "family": "revolving_credit",
        "ticket_min": 25_000, "ticket_max": 1_000_000,
        "roi": "36% APR (revolving)", "roi_numeric": 36.0, "margin_score": 0.80,
        "description": "Primary credit card facility.",
    },
    "auto-loan": {
        "category": "Loan", "family": "secured_loan",
        "ticket_min": 100_000, "ticket_max": 3_000_000,
        "roi": "10.25% p.a.", "roi_numeric": 10.25,
        "tenor_months_min": 12, "tenor_months_max": 84, "margin_score": 0.60,
        "description": "Secured loan against a vehicle.",
    },
}

# Per-product eligibility. Tighter than the blanket dpdMax=90 default where the
# risk warrants it — an unsecured top-up to someone 90 days down is not a
# cross-sell, it is an impairment.
#
# Conditions use the closed predicate set in capture.SUPPORTED_CONDITION_KEYS.
# Anything absent is not evaluated; anything unknown reports unknown and does
# not block. Keys outside that set raise a warning and an explicit
# `rule_unsupported` flag rather than being silently skipped.
PRODUCT_RULES: dict[str, dict[str, Any]] = {
    # A top-up is new unsecured exposure on an existing loan: needs a track
    # record, room on the relationship, and a customer who is not already at
    # the limit of what we have lent them.
    "topup-loan": {
        "kyc": "current",
        "dpdMax": 30,
        "minRelationshipMonths": 6,
        "maxUtilization": 0.85,
        "minTicket": 50_000,
        "riskNotIn": ["critical"],
    },
    "debt-consolidation": {
        "kyc": "current",
        "dpdMax": 60,
        "minRelationshipMonths": 3,
        "minTicket": 100_000,
    },
    # A limit upgrade to someone already using their limit is how a
    # delinquency becomes a bigger delinquency.
    "cc-limit-upgrade": {
        "kyc": "current",
        "dpdMax": 15,
        "maxUtilization": 0.70,
        "riskNotIn": ["critical", "high"],
    },
    "personal-loan": {
        "kyc": "current",
        "dpdMax": 30,
        "minRelationshipMonths": 6,
        "riskNotIn": ["critical"],
    },
    # Secured against gold, so tenure and utilisation matter far less.
    "gold-loan": {"kyc": "current", "dpdMax": 90},
    # Low-ticket protection: the only real gate is that we may contact them,
    # and fulfilment needs a written record, hence the e-mail consent rule.
    "bundled-insurance": {
        "kyc": "current",
        "dpdMax": 90,
        "requiresConsentChannel": "email",
    },
}

# Complementarity / conflict graph. `excludes` is treated symmetrically by the
# candidate generator; `complements` feeds the affinity signal.
PRODUCT_RELATIONS: list[dict[str, Any]] = [
    {"id": "pr-pl-topup", "product_id": "personal-loan", "related_product_id": "topup-loan",
     "relation": "complements", "affinity": 0.90},
    {"id": "pr-pl-ins", "product_id": "personal-loan", "related_product_id": "bundled-insurance",
     "relation": "complements", "affinity": 0.80},
    {"id": "pr-auto-ins", "product_id": "auto-loan", "related_product_id": "bundled-insurance",
     "relation": "complements", "affinity": 0.85},
    {"id": "pr-cc-limit", "product_id": "credit-card", "related_product_id": "cc-limit-upgrade",
     "relation": "upgrades", "affinity": 0.95},
    {"id": "pr-cc-consol", "product_id": "credit-card", "related_product_id": "debt-consolidation",
     "relation": "complements", "affinity": 0.75},
    # A top-up only exists on top of an existing loan.
    {"id": "pr-topup-req", "product_id": "topup-loan", "related_product_id": "personal-loan",
     "relation": "requires", "affinity": 1.00},
    # A limit upgrade needs a card to upgrade.
    {"id": "pr-ccup-req", "product_id": "cc-limit-upgrade", "related_product_id": "credit-card",
     "relation": "requires", "affinity": 1.00},
    # Consolidating and topping up at once is double leverage.
    {"id": "pr-consol-x-topup", "product_id": "debt-consolidation",
     "related_product_id": "topup-loan", "relation": "excludes", "affinity": 0.00},
]

PRODUCT_CAMPAIGNS: list[dict[str, Any]] = [
    {"id": "camp-topup-q3", "product_id": "topup-loan", "name": "Top-up push Q3",
     "priority": 0.80, "risk_not_in": ["critical"], "enabled": True},
    {"id": "camp-ins-always", "product_id": "bundled-insurance", "name": "Protection attach",
     "priority": 0.60, "enabled": True},
    {"id": "camp-ccup", "product_id": "cc-limit-upgrade", "name": "Limit upgrade",
     "priority": 0.55, "risk_not_in": ["critical", "high"], "enabled": True},
]


#: Configuration tables rooted in a tenant by migration 20260812_0060. The
#: column is injected here rather than at each call site: `upsert` derives its
#: column list from the row dict, so a seed row that forgets `tenant_id` fails
#: with a NOT NULL violation at run time, and there are a dozen call sites to
#: forget it in. Injecting centrally makes the failure impossible instead of
#: merely unlikely.
TENANT_SCOPED_SEED_TABLES = frozenset(
    {
        "compliance_rules",
        "qa_rubrics",
        "products",
        "document_templates",
        "persona_presets",
        "sandbox_scenarios",
        "kb_snapshots",
        "tts_voices",
        "voice_sandbox_sessions",
        "eval_suites",
        "skills",
        "vault_refs",
        "mcp_connectors",
        "mcp_keys",
        "mcp_tasks",
        "simulation_twins",
        "a2a_partners",
        "deployment_experiments",
        "twin_corpus",
        "gateway_canaries",
        "skill_critiques",
        # Rooted by 20260812_0062 — seed rows that omit tenant_id otherwise
        # fail NOT NULL and roll back the whole demo graph.
        "kb_documents",
        "prompt_versions",
        "export_jobs",
        "retrieval_logs",
    }
)


def upsert(conn: psycopg.Connection, table: str, row: dict[str, Any], pk: str = "id") -> None:
    if table in TENANT_SCOPED_SEED_TABLES and "tenant_id" not in row:
        row = {**row, "tenant_id": TENANT_ID}
    keys = list(row)
    cols = ", ".join(keys)
    vals = ", ".join(f"%({k})s" for k in keys)
    updates = ", ".join(f"{k}=EXCLUDED.{k}" for k in keys if k != pk)
    conflict = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    arrays = ARRAY_COLUMNS.get(table, frozenset())
    params = {k: (v if k in arrays else jsonable(v)) for k, v in row.items()}
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
        "kaia-v2-4": "Collections",
        "intake-v1": "Intake",
        "insurance-v1": "Insurance",
        "supervisor-brief": "Supervisor brief",
        "webchatbot": "WebChatBot",
    }
    teams: dict[str, str] = {
        "card-collections": "Card Collections",
        "retail-collections": "Retail Collections",
        "supervisors": "Supervisors",
        # Sales queues leads are routed to by product category. They were only
        # created as a side effect of a lead in the seed happening to name them,
        # so routing a bot-captured insurance lead hit a missing team row.
        "retail-sales": "Retail Sales",
        "cards-sales": "Cards Sales",
        "insurance": "Insurance",
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
            name = handler.get("name") or handler.get("agent") or handler.get("human")
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
    # The grievance officer is seeded, not optional. RBI para 100AA requires the
    # officer's name, email and telephone number in every recovery
    # communication, and `compliance_copy.written_footer()` returns None without
    # them — which means a fresh install with this row empty would refuse to
    # send dunning SMS and refuse to leave voicemail, correctly and silently.
    # Seeding it here makes the compliant path the default one.
    upsert(
        conn,
        "tenants",
        {
            "id": TENANT_ID,
            "name": "HDFC Retail",
            "budget_inr": 2500000,
            "spend_share": 0.62,
            "contact_number": "18002026161",
            # A plain dict — `upsert` runs values through `jsonable()`, which
            # wraps dicts in psycopg's Json adapter. A json.dumps string here
            # would arrive as text and Postgres has no implicit text->jsonb cast.
            "grievance_officer": {
                "name": "R Menon",
                "email": "grievance@hdfcretail.example",
                "phone": "18002026161",
                "address": "HDFC Retail, Nodal Office, Mumbai 400013",
            },
        },
    )

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

    # Permissions and grants come from authz rather than a second list kept
    # here. The hand-written version had 5 of the 28 permissions and granted 6
    # rows across 4 roles, which was harmless while nothing read the table and
    # became a lockout the moment something did: authz treats a role's explicit
    # grants as authoritative — so that revoking works — and those six tokens
    # therefore *replaced* the built-in defaults rather than seeding them. With
    # enforcement on, a Supervisor could do exactly two things.
    for permission_id, module, action, description in authz.PERMISSION_CATALOG:
        upsert(conn, "permissions", {"id": permission_id, "module": module, "action": action, "description": description})

    roles = [("role-agent", "Agent"), ("role-supervisor", "Supervisor"), ("role-admin", "Admin"), ("role-qa", "QA Reviewer")]
    for role_id, name in roles:
        upsert(conn, "roles", {"id": role_id, "tenant_id": TENANT_ID, "name": name})

    for role_id, permission_id in [
        (role_id, permission_id)
        for role_id, name in roles
        for permission_id in sorted(authz.ROLE_DEFAULTS.get(authz._normalize_role(name), ()))
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

    # Demo admin for TTS catalog Refresh (and other admin-gated ops).
    insert_ignore(
        conn,
        "INSERT INTO user_roles (user_id, role_id) VALUES (%(user_id)s, %(role_id)s) ON CONFLICT DO NOTHING",
        {"user_id": "priya-nair", "role_id": "role-admin"},
    )

    for product in ctx["products"].values():
        upsert(conn, "products", {**product, **PRODUCT_CATALOG.get(product["id"], {})})
        upsert(
            conn,
            "product_eligibility_rules",
            {
                "id": f"rule-{product['id']}",
                "product_id": product["id"],
                "name": f"{product['name']} default eligibility",
                "conditions": PRODUCT_RULES.get(
                    product["id"], {"kyc": "current", "dpdMax": 90}
                ),
                "enabled": True,
            },
        )

    seeded = set(ctx["products"])
    for relation in PRODUCT_RELATIONS:
        if relation["product_id"] in seeded and relation["related_product_id"] in seeded:
            upsert(conn, "product_relations", relation)

    for campaign in PRODUCT_CAMPAIGNS:
        if campaign["product_id"] in seeded:
            upsert(conn, "product_campaigns", {**campaign, "tenant_id": TENANT_ID})


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

    # CRM-token-free, and it has to stay that way. A system prompt only
    # interpolates SYSTEM_SAFE_VARIABLES ({agent_name}, {bank_name},
    # {language}, {time_of_day}); render_system_prompt leaves every other token
    # alone and strip_unrendered_crm_tokens then deletes the whole LINE it sits
    # on. A preset that says "Greet {customer_name} warmly" therefore does not
    # greet anyone -- it silently deletes its own instruction, and the author
    # who clicked the preset has no way to see that happened.
    #
    # These four are the exact strings in sql/09_bot_config.sql and in migration
    # 20260819_0084. That migration repairs databases that already hold the old
    # rows, but a migration only runs when it is replayed -- a stamped database
    # never executes its UPDATE -- while this seeder upserts on every run, so it
    # is the copy that actually decides what is in the table. It still held the
    # pre-0084 text, which is how a database at head served presets that delete
    # half their own lines the moment an author applies one.
    _emp_prompt = (
        "You are {agent_name}, an inbound collections voice agent for {bank_name}.\n"
        "Greet the caller warmly and acknowledge their situation before discussing dues.\n"
        "Their account number, outstanding balance and due date arrive in the CRM context card — quote those figures verbatim and never invent one.\n"
        "Speak in {language}. Be patient, empathetic and non-judgemental.\n"
        "Never threaten legal action. Offer Promise-to-Pay options when the caller signals hardship."
    )
    _firm_prompt = (
        "You are {agent_name}, a collections agent for {bank_name}.\n"
        "Address the caller directly and state the purpose of the call within the first two sentences.\n"
        "State the overdue amount and due date from the CRM context card, exactly as given. Never estimate or round them.\n"
        "Speak in {language}. Be concise and outcome-focused; ask for a specific payment date.\n"
        "Never threaten legal action and never imply consequences the bank has not authorised."
    )
    _comp_prompt = (
        "You are {agent_name}, a compliance-first collections agent for {bank_name}.\n"
        "Verify the caller's identity before sharing any account information.\n"
        "Account details are in the CRM context card and may only be discussed after verification succeeds.\n"
        "Speak in {language}. Keep to the script; if a request falls outside policy, say so plainly and escalate.\n"
        "Never quote an interest rate, waiver or settlement figure that a tool has not returned."
    )
    _upsell_prompt = (
        "You are {agent_name}, a collections and relationship voice agent for {bank_name}.\n"
        "Resolve the caller's query about their overdue balance first — the figures are in the CRM context card.\n"
        "Only once the collections matter is settled and sentiment is not negative, mention at most one offer returned by recommend_next_offer.\n"
        "Speak in {language}. Never name a product the tool did not give you."
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
        "voiceId": "en-IN-AartiNeural",
        "azureVoiceName": "en-IN-AartiNeural",
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
        ("priya", "Priya", "Female", "Indian English", "en-IN-AartiNeural"),
        ("anjali", "Anjali", "Female", "Hindi-English", "en-IN-AashiNeural"),
        ("neha", "Neha", "Female", "Neutral English", "en-IN-AartiNeural"),
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

    # One published version per first-party bot. Collections keeps the history
    # row ids (v1_0 … v1_4); the other three cards seed a single published row.
    from agent_core.cards.defaults import card_dump as _card_dump

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
        row = {
            **row,
            "bot_id": "kaia-v2-4",
            "agent_card": _card_dump("kaia-v2-4"),
        }
        upsert(conn, "prompt_versions", row)

    for bot_id, version_id, prompt in (
        ("intake-v1", "pv-intake-1", "You are the intake agent. Identify the caller, disclose recording, and hand off to the right specialist."),
        ("insurance-v1", "pv-insurance-1", "You are the insurance specialist. Eligibility and leads only — never quote a product the reco engine did not return."),
        ("supervisor-brief", "pv-supervisor-1", "You write a compact supervisor brief. You do not speak to the customer."),
    ):
        upsert(
            conn,
            "prompt_versions",
            {
                "id": version_id,
                "author_user_id": "anita-rao",
                "status": "published",
                "label": "v1.0",
                "summary": "first-party card",
                "prompt": prompt,
                "persona": _persona(_emp_traits),
                "voice": {**_voice},
                "guardrails": {**_guardrails},
                "bot_id": bot_id,
                "agent_card": _card_dump(bot_id),
                "created_at": "2026-08-15T10:00:00Z",
                "updated_at": "2026-08-15T10:00:00Z",
            },
        )
        upsert(
            conn,
            "bot_deployments",
            {
                "id": f"DEP-{bot_id}-PROD",
                "bot_id": bot_id,
                "prompt_version_id": version_id,
                "kb_snapshot_id": None,
                "tts_voice_id": "en-IN-AartiNeural",
                "environment": "production",
                "status": "active",
                "published_by_user_id": "priya-nair",
                "published_at": "2026-08-15T10:00:00Z",
                "rollback_deployment_id": None,
                "voice_config": {**_voice, "azureVoiceName": "en-IN-AartiNeural", "voiceId": "en-IN-AartiNeural"},
                "tuning": {"tts": {"voice": "en-IN-AartiNeural"}},
                "traffic_pct": 100,
                "shadow": False,
            },
        )

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
            "tts_voice_id": "en-IN-AartiNeural",
            "environment": "production",
            "status": "active",
            "published_by_user_id": "priya-nair",
            "published_at": "2026-07-21T08:30:00Z",
            "rollback_deployment_id": None,
            "voice_config": {**_voice, "azureVoiceName": "en-IN-AartiNeural", "voiceId": "en-IN-AartiNeural"},
            "tuning": {"tts": {"voice": "en-IN-AartiNeural"}},
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


def seed_skills(conn: psycopg.Connection) -> None:
    """First-party packs, signed with the platform key, attached to published cards."""
    from agent_core.skills.defaults import CARD_SKILLS, all_first_party_packs
    from agent_core.skills.sign import sign_hash

    published = {
        "kaia-v2-4": "v1_4",
        "intake-v1": "pv-intake-1",
        "insurance-v1": "pv-insurance-1",
        "supervisor-brief": "pv-supervisor-1",
    }
    version_ids: dict[str, str] = {}
    for pack in all_first_party_packs():
        sid = f"skill-{pack.slug}"
        vid = f"{sid}-v1"
        version_ids[pack.slug] = vid
        signature = sign_hash(pack.content_hash)
        upsert(
            conn,
            "skills",
            {
                "id": sid,
                "slug": pack.slug,
                "signature_status": "signed",
                "origin": "first_party",
                "latest_version_id": None,
            },
        )
        upsert(
            conn,
            "skill_versions",
            {
                "id": vid,
                "skill_id": sid,
                "version": "1",
                "status": "signed",
                "frontmatter": pack.frontmatter,
                "body": pack.body,
                "allowed_tools": pack.allowed_tools,
                "content_hash": pack.content_hash,
                "signature": signature,
                "signed_by": None,
                "pack": {"references": pack.references, "examples": pack.examples},
            },
        )
        conn.execute(
            "UPDATE skills SET latest_version_id = %(vid)s WHERE id = %(id)s",
            {"vid": vid, "id": sid},
        )
    for bot_id, slugs in CARD_SKILLS.items():
        pv = published.get(bot_id)
        if not pv:
            continue
        for slug in slugs:
            vid = version_ids.get(slug)
            if not vid:
                continue
            insert_ignore(
                conn,
                "INSERT INTO skill_attachments (prompt_version_id, skill_version_id) "
                "VALUES (%(pv)s, %(sv)s) ON CONFLICT DO NOTHING",
                {"pv": pv, "sv": vid},
            )


def seed_mcp_phase3(conn: psycopg.Connection) -> None:
    """First-party pay-link + LMS connectors. No tokens, no vault:// strings."""
    for slug, title, prefixes, data_class in (
        ("paylink", "Pay-link status", ["ext.paylink."], ["money", "pii"]),
        ("lms", "LMS balance", ["ext.lms."], ["money", "pii"]),
    ):
        upsert(
            conn,
            "mcp_connectors",
            {
                "id": f"conn-{slug}",
                "slug": slug,
                "display_name": title,
                "kind": "first_party",
                "allow_prefixes": prefixes,
                "data_class": data_class,
                "status": "approved",
                "allowed_env": "both",
                "health": "healthy",
                "tools_cache": [],
            },
        )


def seed_phase4(conn: psycopg.Connection) -> None:
    """Clerk SMS rubric + bounce twin. No Temporal cluster, no dialer."""
    upsert(
        conn,
        "qa_rubrics",
        {
            "id": "rubric-clerk-sms",
            "name": "Clerk SMS / WhatsApp",
            "version": "v1.0",
            "enabled": True,
            "channel": "clerk",
        },
    )
    upsert(
        conn,
        "qa_rubric_sections",
        {"id": "clerk-contact", "rubric_id": "rubric-clerk-sms", "name": "Contact policy", "weight": 60},
    )
    upsert(
        conn,
        "qa_rubric_sections",
        {"id": "clerk-copy", "rubric_id": "rubric-clerk-sms", "name": "Message accuracy", "weight": 40},
    )
    for cid, section, label, desc, weight, critical in (
        ("clk-dnd", "clerk-contact", "DND / frequency honoured", "No send outside policy.", 50, True),
        ("clk-once", "clerk-contact", "No duplicate chase", "Idempotent: one SMS/WA per trigger.", 50, True),
        ("clk-ask", "clerk-copy", "Ask matches the plan", "Amount/link/next step match the treatment log.", 60, False),
        ("clk-brand", "clerk-copy", "Regulated entity identifiable", "Brand, account tail, grievance route present.", 40, False),
    ):
        upsert(
            conn,
            "qa_rubric_criteria",
            {
                "id": cid,
                "section_id": section,
                "label": label,
                "description": desc,
                "weight": weight,
                "critical_fail": critical,
            },
        )
    from agent_core.twin import DEFAULT_STATE, DEFAULT_TWIN_ID

    upsert(
        conn,
        "simulation_twins",
        {
            "id": DEFAULT_TWIN_ID,
            "name": "Bounce chase ladder",
            "state": DEFAULT_STATE,
        },
    )


def seed_phase5(conn: psycopg.Connection) -> None:
    """Lapse eval suite + a sample A2A partner cert. No OPA import."""
    from agent_core.eval.fixtures import seed_lapse_catalog

    seed_lapse_catalog(conn, TENANT_ID, upsert)
    upsert(
        conn,
        "a2a_partners",
        {
            "id": "a2a-p-bank-fraud",
            "name": "Bank fraud desk",
            "card_url": "https://partner.example/agent-card.json",
            "cert_fingerprint": "seed-cert-fingerprint",
            "cert_dn": "CN=bank-fraud.example",
            "allowed_skills": ["premium-lapse-chase"],
            "status": "active",
        },
    )


def seed_eval_catalog(conn: psycopg.Connection) -> None:
    from agent_core.eval.fixtures import seed_eval_catalog as _seed
    from agent_core.eval.fixtures import seed_phase6_catalog

    _seed(conn, TENANT_ID, upsert)
    seed_phase6_catalog(conn, TENANT_ID, upsert)


def seed_phase6(conn: psycopg.Connection) -> None:
    """Capability + twin suites. No DSPy, no auto-applied tuner."""
    from agent_core.eval.fixtures import seed_phase6_catalog

    seed_phase6_catalog(conn, TENANT_ID, upsert)


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
        ("r-third", "PROH-LANG-05", "Unauthorized third-party disclosure", "critical"),
    ]
    for rule_id, code, label, severity in screen_rules:
        upsert(conn, "compliance_rules", {"id": rule_id, "code": code, "label": label, "severity": severity, "enabled": True})

    for call in ctx["calls"]:
        call_id = call["id"]
        customer_id = call["customerId"]
        handler = call.get("handledBy") or {}
        if handler.get("kind") == "human":
            handler_kind = "human"
            handler_user_id = slug(handler.get("name") or handler.get("agent") or handler.get("human") or "Priya Nair")
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
            "body": "I can't approve a fee reversal on this channel. I'll log a specialist review against the live authority ceiling — they'll confirm what, if anything, can be reversed.",
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

    seed_authored_interactions(conn, ctx)


def seed_authored_interactions(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    """The timeline customers.json actually authors.

    Every other child of a detailed customer record is seeded -- ledger_entries,
    emi_installments, customer_notes, promises, disputes -- but `interactions`
    never was, so Customer 360 rendered a history assembled entirely from
    calls.json. For the two customers that calls.json happens to name that meant
    a synthetic timeline contradicting the authored ledger beside it; for the
    four it does not name it meant no timeline at all.

    The authored rows carry their outcome directly (`sentiment` as a label,
    `intents` as booleans) rather than the derived-from-a-score shape the call
    rows use, so those are read as authored rather than re-inferred from
    disposition text.
    """
    for customer_id, source in ctx["detailed_customers"].items():
        account_id = ctx["account_by_customer"].get(customer_id)
        for row in source.get("interactions") or []:
            # `ai1`/`i1`/`ni1` are unique within a customer, not across the seed.
            # Namespaced the same way customer_notes are.
            interaction_id = f"{customer_id}-{row['id']}"
            handler = row.get("handler") or {}
            if handler.get("kind") == "human":
                handler_kind = "human"
                handler_user_id = slug(handler.get("name") or "")
                if handler_user_id not in ctx["users"]:
                    handler_user_id = "priya-nair"
                handler_bot_id = None
            else:
                handler_kind = "bot"
                handler_user_id = None
                handler_bot_id = slug(handler.get("name") or "CollectionsBot v2.4")
                if handler_bot_id not in ctx["bots"]:
                    # "CollectionsBot" and "CollectionsBot v2.4" are one agent;
                    # the authored rows use the short name. Resolve to the
                    # versioned bot rather than minting a second one that would
                    # then show up on the Agent Studio fleet index.
                    handler_bot_id = next(
                        (b for b in ctx["bots"] if b.startswith(handler_bot_id)),
                        "collectionsbot-v2-4",
                    )
            intents = row.get("intents") or {}
            duration_sec = parse_duration(row.get("duration"))
            upsert(
                conn,
                "interactions",
                {
                    "id": interaction_id,
                    "tenant_id": TENANT_ID,
                    "customer_id": customer_id,
                    "account_id": account_id,
                    "handler_kind": handler_kind,
                    "handler_user_id": handler_user_id,
                    "handler_bot_id": handler_bot_id,
                    "transferred_from_bot_id": "kaia-v2-4" if handler_kind == "human" else None,
                    "channel": channel(row.get("channel")),
                    "direction": "outbound",
                    "status": "completed",
                    "disposition": row.get("disposition"),
                    "primary_intent": seed_primary_intent(row, interaction_id),
                    "query_resolved": bool(intents.get("queryResolved", False)),
                    "upsell_presented": bool(intents.get("upsellPresented", False)),
                    "ptp_captured": bool(intents.get("ptpCaptured", False)),
                    # The authored rows state a sentiment label and no score.
                    # Passing the label through rather than inventing a number
                    # for it keeps "negative" meaning what the author wrote.
                    "avg_sentiment": None,
                    "sentiment_label": sentiment_label(label=row.get("sentiment")),
                    "summary": row.get("summary"),
                    "hash": stable_hash(interaction_id),
                    "latency_ms": None,
                    "rag_hits": 0,
                    "redaction_applied": False,
                    "deployment_id": "DEP-2026-07-PROD",
                    "started_at": row.get("startedAt"),
                    "ended_at": None,
                    "duration_sec": duration_sec,
                    "source_payload": row,
                },
            )
            upsert(conn, "interaction_participants", {"id": f"{interaction_id}-customer", "interaction_id": interaction_id, "participant_kind": "customer", "user_id": None, "bot_id": None, "role": "customer", "joined_at": row.get("startedAt"), "left_at": None})
            upsert(conn, "interaction_participants", {"id": f"{interaction_id}-handler", "interaction_id": interaction_id, "participant_kind": handler_kind, "user_id": handler_user_id, "bot_id": handler_bot_id, "role": "primary", "joined_at": row.get("startedAt"), "left_at": None})


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


def seed_recent_activity(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    """Relative-dated payments so the dashboard has a recent series to draw.

    The executive dashboard used to read ``analytics_daily`` — one hand-seeded
    row — and multiply it by literals. Now that every figure is a real query
    over ``ledger_entries`` / ``promises`` / ``leads``, a corpus whose newest
    payment is months old renders an honest but empty chart, which reads as a
    regression rather than as the truth it is.

    Dates are computed from ``now()`` rather than written as literals. That is
    the whole point: the fixed-date seed is *why* the demo data expired, and a
    hardcoded top-up would expire again on exactly the same schedule.

    Ids are deterministic, so re-seeding updates rather than duplicates.
    """
    # Payments across the last 45 days. The modulus spreads them unevenly so the
    # trend line has a shape instead of a flat bar per day.
    conn.execute(
        """
        INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at, created_at)
        SELECT
          'SEED-RECENT-' || a.id || '-' || d.n,
          a.id,
          'payment',
          'EMI collection',
          -1 * ROUND(COALESCE(a.minimum_due, 2500) * (0.6 + mod(d.n * 7, 5) * 0.15), 2),
          now() - CAST(d.n || ' days' AS interval),
          now()
        FROM (
          SELECT id, minimum_due,
                 row_number() OVER (ORDER BY id) AS rn
          FROM accounts
          WHERE status = 'active'
        ) a
        CROSS JOIN generate_series(1, 44) AS d(n)
        WHERE mod(d.n + a.rn::int, 6) = 0
        ON CONFLICT (id) DO UPDATE SET
          amount = EXCLUDED.amount,
          posted_at = EXCLUDED.posted_at
        """
    )

    # A handful of settled promises inside the window so Promise-Kept Rate has
    # a denominator. Only touches rows this function created.
    conn.execute(
        """
        UPDATE promises
           SET created_at = now() - CAST((mod(abs(hashtext(id)), 25) + 1) || ' days' AS interval),
               promised_at = now() - CAST((mod(abs(hashtext(id)), 25) + 1) || ' days' AS interval)
         WHERE status IN ('kept', 'broken', 'partial')
        """
    )

    # Same for leads, so Upsell Conversion has something to divide by.
    conn.execute(
        """
        UPDATE leads
           SET created_at = now() - CAST((mod(abs(hashtext(id)), 25) + 1) || ' days' AS interval)
         WHERE stage IN ('won', 'lost', 'qualified', 'interested', 'contacted')
        """
    )


def seed_compliance_qa_redaction(conn: psycopg.Connection, ctx: dict[str, Any]) -> None:
    # Full screen rubric — IDs must match Habibi/src/data/qa-seed.ts defaultRubric.
    upsert(conn, "qa_rubrics", {"id": "rubric-v1", "name": "Collections Interaction Rubric", "version": "v1.0", "enabled": True, "channel": "voice"})
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
            # stable_number, not hash(): PYTHONHASHSEED randomisation makes hash()
            # differ per process, so re-running the seeder rewrites every QA score.
            ai = stable_number(f"{scorecard_id}-{crit}-ai", 3, 5)
            final = 0 if status == "unscored" else (ai if status == "ai_draft" else max(0, min(5, ai + stable_number(f"{scorecard_id}-{crit}-f", 0, 2) - 1)))
            upsert(
                conn,
                "qa_scorecard_entries",
                {
                    "id": f"{scorecard_id}-{crit}",
                    "scorecard_id": scorecard_id,
                    "criterion_id": crit,
                    "ai_suggested_score": ai,
                    "final_score": final,
                    "note": "Coach reviewed — see comments." if status == "final" and stable_number(f"{scorecard_id}-{crit}-n", 0, 3) == 0 else None,
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
    upsert(
        conn,
        "coaching_actions",
        {
            "id": "coach-1",
            "tenant_id": TENANT_ID,
            "subject_user_id": None,
            "subject_bot_id": "kaia-v2-4",
            "scorecard_id": f"qa-{first_call['id']}",
            "interaction_id": first_call["id"],
            "action": "Review disclosure phrasing",
            "status": "assigned",
            "due_at": "2026-07-25T10:00:00Z",
        },
    )
    upsert(
        conn,
        "calibration_sessions",
        {
            "id": "calibration-1",
            "interaction_id": first_call["id"],
            "rubric_id": "rubric-v1",
            "status": "active",
        },
    )
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
