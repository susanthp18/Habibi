"""Seed → database, and the binding CRUD the Agent Studio writes.

The seed in :mod:`agent_core.providers.registry` is code; the rows here are what
the runtime and the UI read. Sync is an upsert rather than a truncate-and-insert
because ``agent_provider_bindings.provider_model_id`` is ``ON DELETE RESTRICT`` —
a redeploy must not be able to orphan a binding that a published agent depends
on.

``measured_latency_*`` is deliberately never written by the sync. Those columns
belong to our own shadow runs; overwriting them from the seed on every restart
would erase the only numbers in the table that came from real audio.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import text

import db
from agent_core.providers.registry import SEED, as_rows

logger = logging.getLogger(__name__)


def _sid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


# ------------------------------------------------------------------- seeding


def sync_seed() -> dict[str, int]:
    """Upsert providers and provider_models from the code seed. Idempotent."""
    providers = 0
    models = 0
    with db.engine.begin() as conn:
        for spec in SEED:
            conn.execute(
                text(
                    """
                    INSERT INTO providers (id, name, category)
                    VALUES (:id, :name, :category)
                    ON CONFLICT (id) DO UPDATE
                      SET name = EXCLUDED.name,
                          category = EXCLUDED.category,
                          updated_at = now()
                    """
                ),
                {"id": spec.slug, "name": spec.name, "category": spec.category},
            )
            providers += 1

        for row in as_rows():
            conn.execute(
                text(
                    """
                    INSERT INTO provider_models (
                      id, provider_id, kind, model_id, display_name, service_class,
                      locales, streaming, code_switch, on_prem, diarization, styles,
                      cost_per_unit, cost_unit, params_schema, notes
                    ) VALUES (
                      :id, :provider_id, :kind, :model_id, :display_name, :service_class,
                      :locales, :streaming, :code_switch, :on_prem, :diarization, :styles,
                      :cost_per_unit, :cost_unit, CAST(:params_schema AS jsonb), :notes
                    )
                    ON CONFLICT (provider_id, kind, model_id) DO UPDATE
                      SET display_name  = EXCLUDED.display_name,
                          service_class = EXCLUDED.service_class,
                          locales       = EXCLUDED.locales,
                          streaming     = EXCLUDED.streaming,
                          code_switch   = EXCLUDED.code_switch,
                          on_prem       = EXCLUDED.on_prem,
                          diarization   = EXCLUDED.diarization,
                          styles        = EXCLUDED.styles,
                          cost_per_unit = EXCLUDED.cost_per_unit,
                          cost_unit     = EXCLUDED.cost_unit,
                          params_schema = EXCLUDED.params_schema,
                          notes         = EXCLUDED.notes,
                          updated_at    = now()
                    -- measured_latency_* intentionally absent: those are ours.
                    """
                ),
                row,
            )
            models += 1

    logger.info("provider seed synced · providers=%d · models=%d", providers, models)
    return {"providers": providers, "models": models}


# --------------------------------------------------------------------- reads


def list_models(kind: str | None = None, *, enabled_only: bool = True) -> list[dict[str, Any]]:
    """The capability matrix, joined to provider names, for the picker UI."""
    clauses = []
    params: dict[str, Any] = {}
    if kind:
        clauses.append("m.kind = :kind")
        params["kind"] = kind
    if enabled_only:
        clauses.append("m.enabled")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT m.*, p.name AS provider_name, p.category AS provider_category
                FROM provider_models m
                JOIN providers p ON p.id = m.provider_id
                {where}
                ORDER BY m.kind, p.name, m.display_name
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]


def list_bindings(*, tenant_id: str, bot_id: str | None = None) -> list[dict[str, Any]]:
    """Bindings for a bot plus the tenant defaults it inherits."""
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT b.*, m.provider_id, m.model_id, m.display_name, m.kind,
                       p.name AS provider_name
                FROM agent_provider_bindings b
                JOIN provider_models m ON m.id = b.provider_model_id
                JOIN providers p ON p.id = m.provider_id
                WHERE b.tenant_id = :tenant_id
                  AND (b.bot_id IS NULL OR b.bot_id = :bot_id)
                ORDER BY b.slot,
                         (CASE WHEN b.bot_id IS NOT NULL THEN 2 ELSE 0 END
                          + CASE WHEN b.locale IS NOT NULL THEN 1 ELSE 0 END) DESC,
                         b.priority ASC
                """
            ),
            {"tenant_id": tenant_id, "bot_id": bot_id},
        ).mappings().all()
    return [dict(r) for r in rows]


# -------------------------------------------------------------------- writes


def upsert_binding(
    *,
    tenant_id: str,
    slot: str,
    provider_model_id: str,
    bot_id: str | None = None,
    locale: str | None = None,
    voice_ref: str | None = None,
    priority: int = 100,
    settings: dict[str, Any] | None = None,
    enabled: bool = True,
) -> str:
    """Create or replace one binding. Returns its id.

    The conflict target matches the COALESCE unique index: identity is
    (tenant, bot, slot, locale, priority), so re-binding the same slot at the
    same priority replaces rather than accumulating duplicate rows the resolver
    would then have to break ties between.
    """
    import json

    binding_id = _sid("APB")
    with db.engine.begin() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO agent_provider_bindings (
                  id, tenant_id, bot_id, slot, locale, provider_model_id,
                  voice_ref, priority, settings, enabled
                ) VALUES (
                  :id, :tenant_id, :bot_id, :slot, :locale, :provider_model_id,
                  :voice_ref, :priority, CAST(:settings AS jsonb), :enabled
                )
                ON CONFLICT (tenant_id, COALESCE(bot_id, ''), slot, COALESCE(locale, ''), priority)
                DO UPDATE SET
                  provider_model_id = EXCLUDED.provider_model_id,
                  voice_ref         = EXCLUDED.voice_ref,
                  settings          = EXCLUDED.settings,
                  enabled           = EXCLUDED.enabled,
                  updated_at        = now()
                RETURNING id
                """
            ),
            {
                "id": binding_id,
                "tenant_id": tenant_id,
                "bot_id": bot_id,
                "slot": slot,
                "locale": locale,
                "provider_model_id": provider_model_id,
                "voice_ref": voice_ref,
                "priority": priority,
                "settings": json.dumps(settings or {}),
                "enabled": enabled,
            },
        ).mappings().first()
    return str(row["id"]) if row else binding_id


def delete_binding(*, tenant_id: str, binding_id: str) -> bool:
    """Remove a binding. Tenant-scoped so an id alone cannot cross tenants."""
    with db.engine.begin() as conn:
        result = conn.execute(
            text(
                "DELETE FROM agent_provider_bindings "
                "WHERE id = :id AND tenant_id = :tenant_id"
            ),
            {"id": binding_id, "tenant_id": tenant_id},
        )
    return bool(result.rowcount)
