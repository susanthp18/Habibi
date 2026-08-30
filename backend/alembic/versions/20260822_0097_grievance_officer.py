"""The grievance officer, on the tenant. RBI para 100AA.

Revision ID: 20260822_0097
Revises: 20260822_0096
Create Date: 2026-08-22

Mirrors sql/01_identity.sql.

The amendment requires the grievance redressal officer's name, email, telephone
number and address in the loan agreement **and in all recovery communications**.
Nothing in this system held those details, so every recovery communication it
has ever sent omitted them — the voicemail script, the SMS bodies in
``enact._copy`` and the WhatsApp confirms alike.

It belongs on ``tenants`` and not on the agent card, because it is an
institutional fact rather than an authored one: the same officer answers for
every agent the bank runs, and an author choosing a grievance contact per card
is a way for four cards to name four different people.

Nullable, deliberately. A deployment that has not filled it in is not blocked
from running — it is blocked from *leaving a voicemail*, which is where the
duty actually bites, and `voice/amd.py` degrades to not leaving one rather than
leaving a non-compliant one.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0097"
down_revision: Union[str, Sequence[str], None] = "20260822_0096"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "grievance_officer",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # A callback number the borrower can actually ring. Distinct from
    # TWILIO_PHONE_NUMBER: what we dial *from* rotates across a pool, and a
    # voicemail that asks somebody to return a call has to name one number that
    # will still be answered tomorrow.
    op.add_column("tenants", sa.Column("contact_number", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "contact_number")
    op.drop_column("tenants", "grievance_officer")
