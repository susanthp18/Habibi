"""sandbox: seed Habibi-shaped scenarios for PS-3

Replaces the thin one-row seed with demo scenarios that carry
sim_persona (persona + openingBot + difficulty/summary/intents) and
scripted customer turns. Turn count is kept modest (≤2) so a live run
stays within the hard cost ceiling.

Revision ID: 20260722_0019
Revises: 20260722_0018
Create Date: 2026-07-22
"""

from __future__ import annotations

import json
from typing import Any, Sequence, Union

from alembic import op
from seed_guard import seed_demo_enabled
import sqlalchemy as sa


revision: str = "20260722_0019"
down_revision: Union[str, Sequence[str], None] = "20260722_0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCENARIOS: list[dict[str, Any]] = [
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
            "openingBot": (
                "Hello, this is {agent_name} calling from {bank_name} regarding your loan account. "
                "This call is recorded for quality. Am I speaking with {customer_name}?"
            ),
        },
        "turns": [
            {
                "customer": "Yes it's me. Why are you charging me a late fee? This is ridiculous!",
                "expectedIntent": "waiver_request",
                "expectedSentiment": -0.7,
            },
            {
                "customer": "I want it waived. I've been a customer for 5 years.",
                "expectedIntent": "waiver_request",
                "expectedSentiment": -0.6,
            },
        ],
    },
    {
        "id": "confused-first",
        "name": "Confused first-time defaulter",
        "sim_persona": {
            "title": "Confused first-time defaulter",
            "summary": "Customer doesn't understand what they owe or why.",
            "difficulty": "easy",
            "intents": ["balance_query"],
            "name": "Priya Iyer",
            "phoneLast4": "9034",
            "product": "Credit Card",
            "dpd": 4,
            "overdue": 6320,
            "mood": "confused",
            "language": "English",
            "accountNo": "••••9034",
            "dueDate": "the 8th",
            "openingBot": (
                "Hi, this is {agent_name} from {bank_name}. This call is recorded. "
                "Am I speaking with {customer_name}?"
            ),
        },
        "turns": [
            {
                "customer": "Yes, but I don't understand why you're calling.",
                "expectedIntent": "balance_query",
                "expectedSentiment": -0.1,
            },
            {
                "customer": "Okay, how can I pay it?",
                "expectedIntent": "payment_intent",
                "expectedSentiment": 0.4,
            },
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
            "openingBot": (
                "Hello, this is {agent_name} from {bank_name}. This call is recorded. "
                "Am I speaking with {customer_name}?"
            ),
        },
        "turns": [
            {
                "customer": "Yes. Look, I lost my job last month. I can't pay right now.",
                "expectedIntent": "hardship",
                "expectedSentiment": -0.7,
            },
            {
                "customer": "How does the deferral work?",
                "expectedIntent": "hardship",
                "expectedSentiment": -0.2,
            },
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
            "openingBot": (
                "Hi {customer_name}, this is {agent_name} from {bank_name}. "
                "This call is recorded. Calling about your auto loan EMI."
            ),
        },
        "turns": [
            {
                "customer": "Yes, I want to clear it right now.",
                "expectedIntent": "payment_intent",
                "expectedSentiment": 0.6,
            },
            {
                "customer": "Yes, send the UPI link.",
                "expectedIntent": "payment_intent",
                "expectedSentiment": 0.7,
            },
        ],
    },
    {
        "id": "dispute-txn",
        "name": "Disputed card transaction",
        "sim_persona": {
            "title": "Disputed card transaction",
            "summary": "Customer claims a transaction was not made by them.",
            "difficulty": "medium",
            "intents": ["dispute"],
            "name": "Sanjay Menon",
            "phoneLast4": "7710",
            "product": "Credit Card",
            "dpd": 0,
            "overdue": 0,
            "mood": "concerned",
            "language": "English",
            "accountNo": "••••7710",
            "dueDate": "—",
            "openingBot": (
                "Hello, this is {agent_name} from {bank_name}. This call is recorded. How can I help?"
            ),
        },
        "turns": [
            {
                "customer": "There's a ₹8,000 charge I did not make.",
                "expectedIntent": "dispute",
                "expectedSentiment": -0.5,
            },
            {
                "customer": "It says GLOBAL-EMART, three days ago.",
                "expectedIntent": "dispute",
                "expectedSentiment": -0.3,
            },
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
            "openingBot": (
                "Hello {customer_name}, {agent_name} from {bank_name}. "
                "This call is recorded. Calling regarding your outstanding balance."
            ),
        },
        "turns": [
            {
                "customer": "If you call me again I'll take you to court!",
                "expectedIntent": "escalation",
                "expectedSentiment": -0.9,
            },
        ],
    },
]


def upgrade() -> None:
    if not seed_demo_enabled():
        return
    bind = op.get_bind()

    # Insert/upsert new scenarios first so FK re-points succeed.
    for s in SCENARIOS:
        bind.execute(
            sa.text(
                """
                INSERT INTO sandbox_scenarios (id, name, sim_persona, turns, created_at, updated_at)
                VALUES (
                  :id, :name, CAST(:sim_persona AS jsonb), CAST(:turns AS jsonb), now(), now()
                )
                ON CONFLICT (id) DO UPDATE SET
                  name = EXCLUDED.name,
                  sim_persona = EXCLUDED.sim_persona,
                  turns = EXCLUDED.turns,
                  updated_at = now()
                """
            ),
            {
                "id": s["id"],
                "name": s["name"],
                "sim_persona": json.dumps(s["sim_persona"]),
                "turns": json.dumps(s["turns"]),
            },
        )

    # Re-point legacy sample run, then drop the thin seed row.
    bind.execute(
        sa.text(
            """
            UPDATE sandbox_runs
            SET scenario_id = 'hardship'
            WHERE scenario_id = 'scenario-hardship'
            """
        )
    )
    bind.execute(sa.text("DELETE FROM sandbox_scenarios WHERE id = 'scenario-hardship'"))


def downgrade() -> None:
    if not seed_demo_enabled():
        return
    bind = op.get_bind()
    ids = [s["id"] for s in SCENARIOS]
    bind.execute(
        sa.text("UPDATE sandbox_runs SET scenario_id = NULL WHERE scenario_id = ANY(:ids)"),
        {"ids": ids},
    )
    bind.execute(
        sa.text("DELETE FROM sandbox_scenarios WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO sandbox_scenarios (id, name, sim_persona, turns, created_at, updated_at)
            VALUES (
              'scenario-hardship',
              'Hardship PTP negotiation',
              CAST(:sim AS jsonb),
              CAST(:turns AS jsonb),
              now(), now()
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "sim": json.dumps({"risk": "high"}),
            "turns": json.dumps([{"speaker": "customer", "text": "I cannot pay today."}]),
        },
    )
