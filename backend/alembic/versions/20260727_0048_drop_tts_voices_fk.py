"""Drop bot_deployments → tts_voices FK; store Azure ShortName.

Revision ID: 20260727_0048
Revises: 20260727_0047

``tts_voice_id`` becomes a plain-text Azure Speech ShortName (e.g.
``en-IN-AartiNeural``). Runtime already prefers ``tuning.tts.voice``; this
removes the last FK to the legacy 6-row studio alias table.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260727_0048"
down_revision: Union[str, Sequence[str], None] = "20260727_0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT = "en-IN-AartiNeural"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bot_deployments
          DROP CONSTRAINT IF EXISTS bot_deployments_tts_voice_id_fkey
        """
    )
    # Prefer tuning.tts.voice, then voice_config.azureVoiceName, then alias map.
    op.execute(
        f"""
        UPDATE bot_deployments d
        SET tts_voice_id = COALESCE(
              NULLIF(trim(d.tuning->'tts'->>'voice'), ''),
              NULLIF(trim(d.voice_config->>'azureVoiceName'), ''),
              NULLIF(trim(v.config->>'azureVoiceName'), ''),
              '{_DEFAULT}'
            ),
            updated_at = now()
        FROM tts_voices v
        WHERE v.id = d.tts_voice_id
          AND (
            d.tts_voice_id IS NULL
            OR d.tts_voice_id !~ '^[a-z]{{2,3}}-[A-Z]{{2}}-'
          )
        """
    )
    # Rows whose alias was already deleted / never matched tts_voices.
    op.execute(
        f"""
        UPDATE bot_deployments
        SET tts_voice_id = COALESCE(
              NULLIF(trim(tuning->'tts'->>'voice'), ''),
              NULLIF(trim(voice_config->>'azureVoiceName'), ''),
              '{_DEFAULT}'
            ),
            updated_at = now()
        WHERE tts_voice_id IS NULL
           OR tts_voice_id !~ '^[a-z]{{2,3}}-[A-Z]{{2}}-'
        """
    )


def downgrade() -> None:
    # Best-effort: map known ShortNames back to studio aliases before restoring FK.
    op.execute(
        """
        UPDATE bot_deployments d
        SET tts_voice_id = v.id,
            updated_at = now()
        FROM tts_voices v
        WHERE COALESCE(v.config->>'azureVoiceName', '') = d.tts_voice_id
          AND d.tts_voice_id ~ '^[a-z]{2,3}-[A-Z]{2}-'
        """
    )
    op.execute(
        """
        UPDATE bot_deployments
        SET tts_voice_id = 'priya',
            updated_at = now()
        WHERE tts_voice_id IS NULL
           OR tts_voice_id ~ '^[a-z]{2,3}-[A-Z]{2}-'
        """
    )
    op.execute(
        """
        ALTER TABLE bot_deployments
          ADD CONSTRAINT bot_deployments_tts_voice_id_fkey
          FOREIGN KEY (tts_voice_id) REFERENCES tts_voices(id)
        """
    )
