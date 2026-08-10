"""Partial unique index: one active bot_deployment per (bot_id, environment).

Revision ID: 20260725_0039
Revises: 20260725_0038
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260725_0039"
down_revision: Union[str, Sequence[str], None] = "20260725_0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No IF NOT EXISTS: this index is owned by this revision. An object that
    # already carries the name was created elsewhere and may have a different
    # (wrong) definition — fail loudly instead of silently keeping it.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_bot_deployments_bot_env_active
          ON bot_deployments (bot_id, environment)
          WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_bot_deployments_bot_env_active")
