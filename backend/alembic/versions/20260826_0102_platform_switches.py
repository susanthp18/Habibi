"""Operator-flippable runtime switches, starting with the outbound kill switch.

Every gate on the dialler today is an environment variable — ``TREATMENT_MODE``,
``CAMPAIGN_RUNTIME_ENABLED``, ``BOUNCE_VOICE_ENABLED``. All three are read with
``os.getenv`` at call time in four separate processes, so turning dialling off
means editing ``.env`` and restarting the API, ``bot_worker``, ``voice.bot`` and
the insurance worker. That is not a control anyone can reach while a campaign is
misbehaving, and it is not one a demo can lean on.

The table is deliberately tiny and deliberately fail-safe: **absence is off**.
A missing row, an empty table and a failed read all resolve to disabled, so a
fresh install does not dial, a half-restored backup does not dial, and a
database the reader cannot reach does not dial.

No row is seeded. Seeding ``enabled = true`` would defeat the point, and seeding
``enabled = false`` would say the same thing the empty table already says.

Revision ID: 20260826_0102
Revises: 20260825_0101
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260826_0102"
down_revision: Union[str, None] = "20260825_0101"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_switches (
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          key TEXT NOT NULL,
          enabled boolean NOT NULL DEFAULT false,
          updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          note TEXT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, key)
        )
        """
    )


def downgrade() -> None:
    # Dropping the table restores the previous behaviour exactly: with no
    # switch to read, the reader falls back to "off", which is where every
    # deployment starts anyway.
    op.execute("DROP TABLE IF EXISTS platform_switches")
