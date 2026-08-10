"""whatsapp_outbound_jobs.post_attempted_at — avoid duplicate Meta POST on reclaim

Revision ID: 20260725_0036
Revises: 20260725_0035
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260725_0036"
down_revision: Union[str, Sequence[str], None] = "20260725_0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_outbound_jobs",
        sa.Column("post_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("whatsapp_outbound_jobs", "post_attempted_at")
