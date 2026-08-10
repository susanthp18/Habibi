"""TTS catalog polish: Aarti aliases + demo admin role.

Revision ID: 20260727_0047
Revises: 20260727_0046

- Flip legacy studio aliases priya/neha from Neerja → Aarti (product default).
- Grant role-admin to priya-nair so catalog Refresh works when API auth is on.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260727_0047"
down_revision: Union[str, Sequence[str], None] = "20260727_0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE tts_voices
        SET config = jsonb_set(
              COALESCE(config, '{}'::jsonb),
              '{azureVoiceName}',
              '"en-IN-AartiNeural"'::jsonb,
              true
            ),
            updated_at = now()
        WHERE id IN ('priya', 'neha')
          AND COALESCE(config->>'azureVoiceName', '') = 'en-IN-NeerjaNeural'
        """
    )
    op.execute(
        """
        INSERT INTO user_roles (user_id, role_id)
        VALUES ('priya-nair', 'role-admin')
        ON CONFLICT DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE tts_voices
        SET config = jsonb_set(
              COALESCE(config, '{}'::jsonb),
              '{azureVoiceName}',
              '"en-IN-NeerjaNeural"'::jsonb,
              true
            ),
            updated_at = now()
        WHERE id IN ('priya', 'neha')
          AND COALESCE(config->>'azureVoiceName', '') = 'en-IN-AartiNeural'
        """
    )
    op.execute(
        """
        DELETE FROM user_roles
        WHERE user_id = 'priya-nair' AND role_id = 'role-admin'
        """
    )
