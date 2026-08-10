"""Shared store for Sandbox Live voice session config.

Revision ID: 20260727_0046
Revises: 20260726_0045

``POST /voice/sandbox/start`` (API process) wrote the session bundle — prompt
version, KB snapshot, scenario, persona, tuning — to a JSON file under
``backend/.cache``; ``voice.bot`` read it back when the WebRTC offer arrived.
Those are separate containers with separate filesystems in the default compose
deployment, so the bot never found the session and every Live call fell back to
the production bundle with default tuning: the Tuning Studio, the persona and
the KB snapshot had no observable effect.

Postgres is the one store both processes already share, and ``FOR UPDATE`` gives
the read-modify-write atomicity the old ``O_EXCL`` lock-file protocol could only
provide within a single filesystem. See :mod:`voice_session_store`.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260727_0046"
down_revision: Union[str, Sequence[str], None] = "20260726_0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No FK to sandbox_runs: the session must be readable even when the run row
    # could not be created (start_voice_sandbox tolerates that), and it outlives
    # nothing else. Rows are pruned by voice_session_store.purge_stale.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS voice_sandbox_sessions (
          id          TEXT PRIMARY KEY,
          payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_voice_sandbox_sessions_updated_at
          ON voice_sandbox_sessions (updated_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_voice_sandbox_sessions_updated_at")
    op.execute("DROP TABLE IF EXISTS voice_sandbox_sessions")
