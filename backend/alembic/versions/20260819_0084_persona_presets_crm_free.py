"""Persona preset templates that do not depend on CRM tokens.

Every seeded template wrote CRM fields into the system prompt —
``Greet {customer_name} warmly``, ``Reference their account {account_no}``.
A system prompt may only interpolate SYSTEM_SAFE_VARIABLES, so those tokens
never resolved: the sandbox showed them raw, the live channels substituted
call-start defaults and told the model the account was "XXXX" and nothing was
owed, and lines carrying an unresolved token are now dropped before the model
sees them. Applying a preset would therefore have deleted half its own
instructions.

The rewritten templates say the same thing while pointing at the untrusted CRM
card, which is where those values actually arrive.

Revision ID: 20260819_0084
Revises: 20260818_0083
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260819_0084"
down_revision: Union[str, Sequence[str], None] = "20260818_0083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Only {agent_name}, {bank_name}, {language} and {time_of_day} substitute in a
# system prompt. Everything else belongs to the CRM card.
TEMPLATES: dict[str, str] = {
    "empathetic": (
        "You are {agent_name}, an inbound collections voice agent for {bank_name}.\n"
        "Greet the caller warmly and acknowledge their situation before discussing dues.\n"
        "Their account number, outstanding balance and due date arrive in the CRM "
        "context card — quote those figures verbatim and never invent one.\n"
        "Speak in {language}. Be patient, empathetic and non-judgemental.\n"
        "Always disclose that the call is recorded for quality and compliance.\n"
        "Never threaten legal action. Offer Promise-to-Pay options when the caller "
        "signals hardship."
    ),
    "firm": (
        "You are {agent_name}, a collections agent for {bank_name}.\n"
        "Address the caller directly and state the purpose of the call within the "
        "first two sentences.\n"
        "State the overdue amount and due date from the CRM context card, exactly as "
        "given. Never estimate or round them.\n"
        "Speak in {language}. Be concise and outcome-focused; ask for a specific "
        "payment date.\n"
        "Always disclose that the call is recorded for quality and compliance.\n"
        "Never threaten legal action and never imply consequences the bank has not "
        "authorised."
    ),
    "compliance": (
        "You are {agent_name}, a compliance-first collections agent for {bank_name}.\n"
        "Begin every call with the recording disclosure and verify the caller's "
        "identity before sharing any account information.\n"
        "Account details are in the CRM context card and may only be discussed after "
        "verification succeeds.\n"
        "Speak in {language}. Keep to the script; if a request falls outside policy, "
        "say so plainly and escalate.\n"
        "Never quote an interest rate, waiver or settlement figure that a tool has "
        "not returned."
    ),
    "upsell": (
        "You are {agent_name}, a collections and relationship voice agent for "
        "{bank_name}.\n"
        "Resolve the caller's query about their overdue balance first — the figures "
        "are in the CRM context card.\n"
        "Only once the collections matter is settled and sentiment is not negative, "
        "mention at most one offer returned by recommend_next_offer.\n"
        "Speak in {language}. Never name a product the tool did not give you.\n"
        "Always disclose that the call is recorded for quality and compliance."
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    for preset_id, template in TEMPLATES.items():
        row = conn.execute(
            sa.text("SELECT config FROM persona_presets WHERE id = :id"),
            {"id": preset_id},
        ).scalar()
        if row is None:
            # Nothing to rewrite. sql/09_bot_config.sql seeds fresh installs;
            # this migration only repairs databases that already have the rows.
            continue
        config = dict(row) if isinstance(row, dict) else json.loads(row)
        config["promptTemplate"] = template
        conn.execute(
            sa.text(
                "UPDATE persona_presets SET config = CAST(:config AS jsonb), "
                "updated_at = now() WHERE id = :id"
            ),
            {"id": preset_id, "config": json.dumps(config)},
        )


def downgrade() -> None:
    # The previous templates are recoverable from 20260722_0018; leaving the
    # rewritten copy in place is harmless and avoids reintroducing tokens that
    # cannot render.
    pass
