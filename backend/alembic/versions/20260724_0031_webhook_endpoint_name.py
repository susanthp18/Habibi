"""webhook_endpoints.display name for UI.

Revision ID: 20260724_0031
Revises: 20260724_0030
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260724_0031"
down_revision: Union[str, Sequence[str], None] = "20260724_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE webhook_endpoints ADD COLUMN IF NOT EXISTS name TEXT"
    )
    op.execute(
        """
        UPDATE webhook_endpoints
        SET name = COALESCE(NULLIF(name, ''), target_system, id)
        WHERE name IS NULL OR name = ''
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE webhook_endpoints DROP COLUMN IF EXISTS name")
