"""When a caller ID last changed state. Makes 'cooling' an exit as well as an entry.

Revision ID: 20260822_0099
Revises: 20260822_0098
Create Date: 2026-08-22

Mirrors sql/22_campaigns.sql.

``pool_numbers`` shipped with ``state IN ('active','cooling','retired')``,
``attempts_7d`` and ``answer_rate_7d``, and section 8.2 of the outbound design
doc justifies the whole table on spam decay — *"a number enough handsets have
flagged simply stops connecting, and there is currently no way to observe that,
let alone rotate"*.

Nothing wrote any of it. ``answer_rate_7d`` was never computed, no number was
ever moved to ``cooling``, and ``attempts_7d`` was incremented on every dial and
never decayed — a lifetime counter with ``_7d`` in its name, which is worse than
an empty column because a dashboard would have rendered it without complaint.

This adds the one column the loop was missing. A number can now be cooled on
evidence and, just as importantly, **come back**: without a timestamp, cooling
is a one-way door and a caller ID that had one bad week is retired by accident
for the life of the deployment. After the cool-off it returns on probation and
the next sweep re-cools it if it is still bad.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260822_0099"
down_revision: Union[str, Sequence[str], None] = "20260822_0098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pool_numbers",
        sa.Column(
            "state_changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.add_column(
        "pool_numbers",
        sa.Column("health_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pool_numbers", "health_checked_at")
    op.drop_column("pool_numbers", "state_changed_at")
