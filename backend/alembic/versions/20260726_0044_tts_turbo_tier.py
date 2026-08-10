"""Add missing turbo TTS price tier for catalog sync.

Revision ID: 20260726_0044
Revises: 20260726_0043

Catalog sync derives ``turbo`` for some Azure/AOAI voices; without the row
every worker sync hits FK violations.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260726_0044"
down_revision: Union[str, Sequence[str], None] = "20260726_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO tts_price_tiers (tier, label, approx_usd_per_1m_chars, is_premium, notes)
        VALUES
          ('turbo', 'Turbo / AOAI', NULL, true, 'Rare turbo / AOAI voices')
        ON CONFLICT (tier) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM tts_price_tiers
        WHERE tier = 'turbo'
          AND NOT EXISTS (
            SELECT 1 FROM tts_voice_catalog c WHERE c.price_tier = tts_price_tiers.tier
          )
        """
    )
