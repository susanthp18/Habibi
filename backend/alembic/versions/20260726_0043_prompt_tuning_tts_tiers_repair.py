"""Repair prompt_versions.tuning + TTS price tiers required by catalog sync.

Revision ID: 20260726_0043
Revises: 20260726_0042

Alembic may already be at head while ``prompt_versions.tuning`` is missing
(stamped ahead / partial apply). Catalog sync also inserts ``hd`` / ``hd_flash``
tiers that FK to ``tts_price_tiers`` — without those rows every sync fails.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260726_0043"
down_revision: Union[str, Sequence[str], None] = "20260726_0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE prompt_versions
          ADD COLUMN IF NOT EXISTS tuning jsonb NOT NULL DEFAULT '{}'::jsonb
        """
    )
    op.execute(
        """
        INSERT INTO tts_price_tiers (tier, label, approx_usd_per_1m_chars, is_premium, notes)
        VALUES
          ('hd', 'Neural HD', 30.0, true, 'HD / Multilingual neural voices'),
          ('hd_flash', 'Neural HD Flash', 22.0, true, 'HD Flash neural voices')
        ON CONFLICT (tier) DO NOTHING
        """
    )


def downgrade() -> None:
    # Keep tuning column — dropping would break Prompt Studio. Only remove tiers
    # we added if unused.
    op.execute(
        """
        DELETE FROM tts_price_tiers
        WHERE tier IN ('hd', 'hd_flash')
          AND NOT EXISTS (
            SELECT 1 FROM tts_voice_catalog c WHERE c.price_tier = tts_price_tiers.tier
          )
        """
    )
