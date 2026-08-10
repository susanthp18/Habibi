"""Repair missing voice_sessions table (CRM bind for Live voice).

Revision ID: 20260726_0045
Revises: 20260726_0044

Alembic may already be at head while ``voice_sessions`` is absent (stamp /
partial apply). Without this table ``persist.start_voice_call`` fails, the
exception is swallowed on connect, and every CRM tool returns
``no_interaction`` / ``identity_not_verified``.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260726_0045"
down_revision: Union[str, Sequence[str], None] = "20260726_0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_sessions (
          id              TEXT PRIMARY KEY,
          interaction_id  TEXT NOT NULL REFERENCES interactions(id) ON DELETE CASCADE,
          deployment_id   TEXT REFERENCES bot_deployments(id),
          transport       TEXT NOT NULL
            CHECK (transport IN ('smallwebrtc','twilio','daily')),
          provider_call_id TEXT,
          worker_host     TEXT,
          status          TEXT NOT NULL
            CHECK (status IN ('starting','live','ending','ended','failed')),
          started_at      timestamptz,
          ended_at        timestamptz,
          last_heartbeat_at timestamptz,
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_voice_sessions_provider_call_id
          ON voice_sessions (provider_call_id)
          WHERE provider_call_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_sessions_interaction_id
          ON voice_sessions (interaction_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_sessions_status
          ON voice_sessions (status)
        """
    )


def downgrade() -> None:
    # Keep table — dropping would break live voice CRM bind again.
    pass
