"""provider_registry — speech/LLM providers become a binding, not a constant.

Revision ID: 20260821_0092
Revises: 20260821_0091
Create Date: 2026-08-21

Mirrors sql/10_admin.sql and sql/09_bot_config.sql.

``providers`` / ``provider_fields`` / ``provider_configs`` already existed and
already carried credentials, health and latency per tenant per environment. What
they could not answer is the only question the runtime actually asks:

    "For this agent, on this call, in this locale — which service do I build?"

That answer lived in Python. ``voice/bot.py`` constructed ``AzureSTTService``
directly, and ``voice/tuning_apply.py`` mapped four locales to a ``Language``
enum with ``.get(key, Language.EN_IN)`` as the default. A locale nobody had
mapped did not fail; it transcribed Arabic with an English-India recogniser and
returned confident nonsense. Every layer downstream then scored that nonsense.

Two tables close that gap.

**provider_models is a capability matrix, not a catalog.**
A provider is not uniformly good. Azure has ~20 Arabic *voices* and weak Arabic
*recognition*; Deepgram is fast everywhere and does not do Arabic code-switching
at all. Recording capability per (provider, kind, model) is what lets binding be
a per-locale decision instead of a per-product one.

``measured_latency_p50_ms`` / ``p95`` are deliberately named *measured*. They are
written by our own shadow runs against our own audio, never copied from a vendor
benchmark. A provider that has not been measured has NULL here, and NULL is
readable as "we do not know yet" — which is the honest state and the one a
vendor's published number would have silently overwritten.

**agent_provider_bindings is resolved most-specific-first.**

    (bot, locale) → (bot, any) → (tenant, locale) → (tenant, any)

``priority`` orders the failover chain *within* one specificity, so a Cartesia
free-tier key exhausting its quota falls to Azure rather than dropping the call.
This is the same shape as the circuit breaker already in ``circuit_breaker.py``,
and it is why binding is a table rather than a column: a column can hold the
choice, but it cannot hold the fallback.

**No silent default.** Resolution returning nothing is an error the caller must
handle — the ``EN_IN`` default is exactly the bug this table exists to remove.

``tts_voice_catalog`` gains ``provider_id`` rather than being replaced. Its shape
(locale, short_name, display_name, gender, styles) is already provider-neutral,
so one column makes every existing sync run, endpoint and browser screen work
unchanged against a catalog that now holds more than one vendor's voices.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260821_0092"
down_revision: Union[str, Sequence[str], None] = "20260821_0091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------------- models
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS provider_models (
          id TEXT PRIMARY KEY,
          provider_id TEXT NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
          kind TEXT NOT NULL CHECK (kind IN ('stt','tts','llm')),
          model_id TEXT NOT NULL,
          display_name TEXT NOT NULL,
          -- Fully-qualified Pipecat service class. Stored rather than derived:
          -- the runtime must not guess a class name from a provider slug.
          service_class TEXT NOT NULL,
          -- Empty array = provider auto-detects / serves any locale.
          locales TEXT[] NOT NULL DEFAULT '{}',
          streaming boolean NOT NULL DEFAULT true,
          -- True only for models that handle a language change INSIDE one
          -- sentence. Language-ID routing does not qualify and must not claim it.
          code_switch boolean NOT NULL DEFAULT false,
          on_prem boolean NOT NULL DEFAULT false,
          diarization boolean NOT NULL DEFAULT false,
          styles TEXT[] NOT NULL DEFAULT '{}',
          cost_per_unit numeric(12,6),
          cost_unit TEXT CHECK (cost_unit IN ('usd_per_1m_chars','usd_per_hour','usd_per_1m_tokens')),
          -- OUR measurements against OUR audio. NULL means unmeasured.
          measured_latency_p50_ms INTEGER,
          measured_latency_p95_ms INTEGER,
          measured_at timestamptz,
          notes TEXT NOT NULL DEFAULT '',
          enabled boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_provider_models_provider_kind_model "
        "ON provider_models (provider_id, kind, model_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_provider_models_kind ON provider_models (kind) "
        "WHERE enabled"
    )

    # -------------------------------------------------------------- bindings
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_provider_bindings (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          -- NULL bot_id = the tenant-wide default for this slot.
          bot_id TEXT REFERENCES bots(id) ON DELETE CASCADE,
          slot TEXT NOT NULL CHECK (slot IN ('stt','tts','llm')),
          -- NULL locale = applies to any locale not otherwise bound.
          locale TEXT,
          provider_model_id TEXT NOT NULL
            REFERENCES provider_models(id) ON DELETE RESTRICT,
          -- TTS only: the concrete voice short_name from tts_voice_catalog.
          voice_ref TEXT,
          -- Lower is tried first. This is the failover chain, not a preference.
          priority INTEGER NOT NULL DEFAULT 100,
          settings jsonb NOT NULL DEFAULT '{}'::jsonb,
          enabled boolean NOT NULL DEFAULT true,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    # bot_id and locale are nullable and both participate in identity, so the
    # uniqueness target must COALESCE them — a plain multi-column unique index
    # treats every NULL as distinct and would allow two conflicting defaults.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_provider_bindings_slot
          ON agent_provider_bindings (
            tenant_id, COALESCE(bot_id, ''), slot, COALESCE(locale, ''), priority
          )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_provider_bindings_lookup "
        "ON agent_provider_bindings (tenant_id, slot, enabled)"
    )

    # ------------------------------------------------------- provider identities
    # The rows the FK below points at. These live here rather than in the
    # application seed because the backfill three statements down references
    # 'azure' — a migration that depends on app code having run first is a
    # migration that fails on a clean database.
    #
    # Only identity is written. Capability, credentials and pricing stay with
    # agent_core.providers.persist.sync_seed(), which upserts over these.
    op.execute(
        """
        INSERT INTO providers (id, name, category) VALUES
          ('azure',        'Microsoft Azure', 'speech'),
          ('deepgram',     'Deepgram',        'speech'),
          ('cartesia',     'Cartesia',        'speech'),
          ('elevenlabs',   'ElevenLabs',      'speech'),
          ('groq',         'Groq',            'speech'),
          ('gladia',       'Gladia',          'speech'),
          ('speechmatics', 'Speechmatics',    'speech')
        ON CONFLICT (id) DO NOTHING
        """
    )

    # ------------------------------------------------- catalog goes multi-vendor
    op.execute(
        "ALTER TABLE tts_voice_catalog "
        "ADD COLUMN IF NOT EXISTS provider_id TEXT REFERENCES providers(id)"
    )
    # Every row present before this migration came from the Azure sync.
    op.execute(
        "UPDATE tts_voice_catalog SET provider_id = 'azure' WHERE provider_id IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tts_voice_catalog_provider "
        "ON tts_voice_catalog (provider_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_tts_voice_catalog_provider")
    op.execute("ALTER TABLE tts_voice_catalog DROP COLUMN IF EXISTS provider_id")
    op.execute("DROP TABLE IF EXISTS agent_provider_bindings")
    op.execute("DROP TABLE IF EXISTS provider_models")
