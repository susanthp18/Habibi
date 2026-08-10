"""Store the authored conversation flow alongside the prompt it belongs to.

The call script has always been a node graph, but it lived in ``voice/flows.py``
as Python — changing the conversation meant editing code. This adds the column
the authored version of that graph is stored in.

It goes on ``prompt_versions`` rather than in a table of its own, because the
flow is not independent of the prompt: node instructions *are* prompts, and a
graph that references a persona or guardrail the published prompt no longer has
is incoherent. Sharing the row means the flow inherits the whole existing
lifecycle — draft autosave, the one-published-row partial unique index, publish,
diff, restore-as-draft and deployment rollback — instead of growing a parallel
and inevitably divergent one.

Default '{}' rather than a seeded starter graph: every existing version predates
flow authoring and did not have one. ``flow_graph.parse_graph`` treats an empty
object as "no graph", and the runtime falls back to the hardcoded flow, so old
versions keep behaving exactly as they did.

Revision ID: 20260801_0057
Revises: 20260801_0056
Create Date: 2026-08-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260801_0057"
down_revision: Union[str, Sequence[str], None] = "20260801_0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prompt_versions",
        sa.Column(
            "flow",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("prompt_versions", "flow")
