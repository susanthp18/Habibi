"""Azure TTS voice catalog + price tiers + sync runs.

Revision ID: 20260724_0034
Revises: 20260724_0033
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "20260724_0034"
down_revision: Union[str, Sequence[str], None] = "20260724_0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_VOICE = "en-IN-AartiNeural"
_OLD_DEFAULT = "en-IN-NeerjaNeural"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tts_price_tiers (
          tier text PRIMARY KEY,
          label text NOT NULL,
          approx_usd_per_1m_chars numeric,
          is_premium boolean NOT NULL DEFAULT false,
          notes text NOT NULL DEFAULT '',
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO tts_price_tiers (tier, label, approx_usd_per_1m_chars, is_premium, notes)
        VALUES
          ('standard', 'Standard Neural', 15, false, 'Prebuilt Neural (budget)'),
          ('hd_flash', 'Neural HD Flash', 15, true, 'HD Flash / MAI — gated as premium in UI'),
          ('hd', 'Neural HD', 22, true, 'DragonHD / NeuralHD'),
          ('turbo', 'Turbo / AOAI', NULL, true, 'Rare turbo / AOAI voices')
        ON CONFLICT (tier) DO NOTHING
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tts_voice_catalog (
          short_name text PRIMARY KEY,
          display_name text NOT NULL,
          local_name text NOT NULL DEFAULT '',
          gender text NOT NULL DEFAULT 'Neutral',
          locale text NOT NULL,
          locale_name text NOT NULL DEFAULT '',
          voice_type text NOT NULL DEFAULT 'Neural',
          status text NOT NULL DEFAULT 'GA',
          sample_rate_hertz integer,
          words_per_minute integer,
          styles jsonb NOT NULL DEFAULT '[]'::jsonb,
          model_series jsonb NOT NULL DEFAULT '[]'::jsonb,
          personalities jsonb NOT NULL DEFAULT '[]'::jsonb,
          scenarios jsonb NOT NULL DEFAULT '[]'::jsonb,
          price_tier text NOT NULL DEFAULT 'standard'
            REFERENCES tts_price_tiers(tier),
          is_premium boolean NOT NULL DEFAULT false,
          raw jsonb NOT NULL DEFAULT '{}'::jsonb,
          first_seen_at timestamptz NOT NULL DEFAULT now(),
          last_seen_at timestamptz NOT NULL DEFAULT now(),
          removed_at timestamptz,
          enabled_for_picker boolean NOT NULL DEFAULT true
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_locale ON tts_voice_catalog (locale)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_price_tier ON tts_voice_catalog (price_tier)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_gender ON tts_voice_catalog (gender)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_status ON tts_voice_catalog (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_premium ON tts_voice_catalog (is_premium)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_removed ON tts_voice_catalog (removed_at)"
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_search
        ON tts_voice_catalog (lower(display_name), lower(short_name), lower(local_name))
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tts_voice_sync_runs (
          id text PRIMARY KEY,
          started_at timestamptz NOT NULL DEFAULT now(),
          finished_at timestamptz,
          source text NOT NULL CHECK (source IN ('azure', 'json_import', 'admin')),
          fetched_count integer NOT NULL DEFAULT 0,
          upserted integer NOT NULL DEFAULT 0,
          soft_removed integer NOT NULL DEFAULT 0,
          unchanged integer NOT NULL DEFAULT 0,
          error text,
          region text NOT NULL DEFAULT ''
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tts_voice_sync_runs_started
        ON tts_voice_sync_runs (started_at DESC)
        """
    )

    # Flip product default Neerja → Aarti only where still the old default.
    op.execute(
        f"""
        UPDATE bot_deployments
        SET tuning = jsonb_set(
              COALESCE(tuning, '{{}}'::jsonb),
              '{{tts,voice}}',
              to_jsonb('{_DEFAULT_VOICE}'::text),
              true
            ),
            updated_at = now()
        WHERE COALESCE(tuning->'tts'->>'voice', '') IN ('', '{_OLD_DEFAULT}')
        """
    )
    op.execute(
        f"""
        UPDATE prompt_versions
        SET tuning = jsonb_set(
              COALESCE(tuning, '{{}}'::jsonb),
              '{{tts,voice}}',
              to_jsonb('{_DEFAULT_VOICE}'::text),
              true
            ),
            updated_at = now()
        WHERE COALESCE(tuning->'tts'->>'voice', '') IN ('', '{_OLD_DEFAULT}')
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tts_voice_sync_runs")
    op.execute("DROP TABLE IF EXISTS tts_voice_catalog")
    op.execute("DROP TABLE IF EXISTS tts_price_tiers")
