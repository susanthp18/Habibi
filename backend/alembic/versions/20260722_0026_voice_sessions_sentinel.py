"""voice_sessions registry + UNKNOWN-CALLER sentinel (Voice Agent V2).

Revision ID: 20260722_0026
Revises: 20260722_0025
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260722_0026"
down_revision: Union[str, Sequence[str], None] = "20260722_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

UNKNOWN_CALLER_ID = "UNKNOWN-CALLER"


def upgrade() -> None:
    # Schema only — UNKNOWN-CALLER sentinel is ensured at runtime
    # (voice.persist.ensure_unknown_caller), not injected by migrations.
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
    op.execute("DROP INDEX IF EXISTS idx_voice_sessions_status")
    op.execute("DROP INDEX IF EXISTS idx_voice_sessions_interaction_id")
    op.execute("DROP INDEX IF EXISTS uq_voice_sessions_provider_call_id")
    op.execute("DROP TABLE IF EXISTS voice_sessions")
    # Leave UNKNOWN-CALLER customer in place — interactions may reference it.
