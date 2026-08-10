"""Index whatsapp_outbound_jobs(conversation_id, status) for typing lookups.

Revision ID: 20260725_0037
Revises: 20260725_0036
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260725_0037"
down_revision: Union[str, Sequence[str], None] = "20260725_0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_whatsapp_outbound_jobs_conversation_status
          ON whatsapp_outbound_jobs (conversation_id, status)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_whatsapp_outbound_jobs_conversation_status")
