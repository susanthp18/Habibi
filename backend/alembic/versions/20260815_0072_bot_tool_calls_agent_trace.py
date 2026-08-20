"""Nullable agent/skill/connector ids on bot_tool_calls for later phases.

Revision ID: 20260815_0072
Revises: 20260814_0071
Create Date: 2026-08-15

Phase 0 of the agent factory: later phases attach Agent Cards, skills and MCP
connectors to a turn. Adding the columns now means those phases do not migrate
the audit table twice. All three are nullable — existing writers omit them.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260815_0072"
down_revision: Union[str, Sequence[str], None] = "20260814_0071"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IF NOT EXISTS: a database built from sql/*.sql already has the columns
    # and is then stamped; a migrated database does not.
    op.execute("ALTER TABLE bot_tool_calls ADD COLUMN IF NOT EXISTS agent_id TEXT")
    op.execute("ALTER TABLE bot_tool_calls ADD COLUMN IF NOT EXISTS skill_id TEXT")
    op.execute("ALTER TABLE bot_tool_calls ADD COLUMN IF NOT EXISTS connector_id TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE bot_tool_calls DROP COLUMN IF EXISTS connector_id")
    op.execute("ALTER TABLE bot_tool_calls DROP COLUMN IF EXISTS skill_id")
    op.execute("ALTER TABLE bot_tool_calls DROP COLUMN IF EXISTS agent_id")
