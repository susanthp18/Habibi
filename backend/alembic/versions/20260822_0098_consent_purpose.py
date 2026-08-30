"""Consent is per channel AND per purpose. DPDP purpose limitation.

Revision ID: 20260822_0098
Revises: 20260822_0097
Create Date: 2026-08-22

Mirrors sql/03_consent.sql.

The borrower's phone number was collected to service a loan. Using it to pitch a
top-up is a *different purpose*, and under the DPDP Act a different purpose needs
its own consent basis — not the one already on file for servicing.

``channel_consents`` has been per channel since it was written, which answers
"may we use WhatsApp?" and cannot answer "may we use WhatsApp to sell them
something?". Today those are the same question because the only outbound
messages are collections messages. The moment a cross-sell mission ships they
stop being the same question, and by then the table has a year of rows in it
whose purpose nobody recorded.

Which is why this is cheap now and expensive later, and why it lands before the
mission rather than with it.

**Existing rows become ``servicing``.** That is the truthful backfill: every
consent captured to date was captured in a servicing context, and marking any of
it promotional would be inventing a permission. The consequence is that
promotional contact is refused for every customer in the book until somebody
captures a promotional consent for them — which is the correct default and the
point of the change. It is deliberately not a soft launch: a purpose gate that
falls back to the servicing row when the promotional one is absent grants
exactly the permission the Act says must be granted separately.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0098"
down_revision: Union[str, Sequence[str], None] = "20260822_0097"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_UNIQUE_OLD = "channel_consents_consent_id_channel_key"
_UNIQUE_NEW = "ux_channel_consents_consent_channel_purpose"


def upgrade() -> None:
    op.add_column(
        "channel_consents",
        sa.Column(
            "purpose",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'servicing'"),
        ),
    )
    op.create_check_constraint(
        "ck_channel_consents_purpose",
        "channel_consents",
        "purpose IN ('servicing','promotional')",
    )
    # The old key made one row per (consent, channel) and would now refuse the
    # second purpose for a channel the customer has already answered about.
    op.execute(f'ALTER TABLE channel_consents DROP CONSTRAINT IF EXISTS "{_UNIQUE_OLD}"')
    op.create_unique_constraint(
        _UNIQUE_NEW, "channel_consents", ["consent_id", "channel", "purpose"]
    )
    op.create_index(
        "idx_channel_consents_purpose",
        "channel_consents",
        ["consent_id", "purpose"],
    )


def downgrade() -> None:
    # Promotional rows have to go before the old key can be restored: it cannot
    # hold two rows for one channel, and the servicing row is the one that
    # existed before this revision.
    op.execute("DELETE FROM channel_consents WHERE purpose = 'promotional'")
    op.drop_index("idx_channel_consents_purpose", table_name="channel_consents")
    op.drop_constraint(_UNIQUE_NEW, "channel_consents", type_="unique")
    op.create_unique_constraint(_UNIQUE_OLD, "channel_consents", ["consent_id", "channel"])
    op.drop_constraint("ck_channel_consents_purpose", "channel_consents", type_="check")
    op.drop_column("channel_consents", "purpose")
