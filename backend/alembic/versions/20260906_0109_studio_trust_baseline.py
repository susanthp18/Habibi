"""Studio trust baseline: frozen connector grants and audit chain heads.

Revision ID: 20260906_0109
Revises: 20260906_0108
Create Date: 2026-09-06

NOT applied to the running database by this work package. Mirror:
sql/09_bot_config.sql, sql/12_crosscutting.sql.

Measured on collections (2026-09-06, alembic 20260905_0106):
  bot_deployments=9, audit_log=8, mcp_connectors=2,
  deployment_experiments=0, eval_reports=171 of which 0 carry
  prompt_version_id (no eval backfill — guessing a draft would lie),
  bots.archived_at set on 2 rows, frozen_tools column absent.
  Frozen-tools backfill therefore touches 9 rows. Chain-head backfill
  touches one row per tenant that already has a bot-entity audit_log
  entry (8 audit rows; typically a single tenant head).
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260906_0109"
down_revision: Union[str, None] = "20260906_0108"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE bot_deployments ADD COLUMN IF NOT EXISTS frozen_tools jsonb")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_chain_heads (
          tenant_id TEXT PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
          entry_hash TEXT NOT NULL,
          seq BIGINT NOT NULL,
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    bind = op.get_bind()
    _backfill_frozen_tools(bind)
    _backfill_chain_heads(bind)


def _backfill_frozen_tools(bind) -> None:
    rows = list(
        bind.execute(
            text(
                """
                SELECT d.id, pv.agent_card
                  FROM bot_deployments d
                  JOIN prompt_versions pv ON pv.id = d.prompt_version_id
                 WHERE d.frozen_tools IS NULL
                """
            )
        ).mappings()
    )
    try:
        from agent_core.cards.schema import is_authored, parse_card
        from agent_core.connectors.persist import bound_tool_names
    except Exception:
        is_authored = parse_card = bound_tool_names = None  # type: ignore[assignment]
    for row in rows:
        names: list[str] = []
        card = row["agent_card"]
        if isinstance(card, str):
            try:
                card = json.loads(card)
            except json.JSONDecodeError:
                card = {}
        if is_authored is not None and isinstance(card, dict):
            try:
                if is_authored(card):
                    names = sorted(
                        bound_tool_names(
                            [c.model_dump() for c in parse_card(card).connectors]
                        )
                    )
            except Exception:
                names = []
        bind.execute(
            text(
                "UPDATE bot_deployments SET frozen_tools = CAST(:n AS jsonb) WHERE id = :id"
            ),
            {"id": row["id"], "n": json.dumps(names)},
        )


def _backfill_chain_heads(bind) -> None:
    bind.execute(
        text(
            """
            INSERT INTO audit_chain_heads (tenant_id, entry_hash, seq, updated_at)
            SELECT tenant_id,
                   COALESCE(payload->>'entryHash', repeat('0', 64)),
                   COALESCE((payload->>'seq')::bigint, 0),
                   now()
              FROM (
                    SELECT DISTINCT ON (tenant_id) tenant_id, payload
                      FROM audit_log
                     WHERE entity_type = 'bot'
                       AND tenant_id IS NOT NULL
                     ORDER BY tenant_id,
                              COALESCE((payload->>'seq')::bigint, 0) DESC,
                              id DESC
                   ) newest
            ON CONFLICT (tenant_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_chain_heads")
    op.execute("ALTER TABLE bot_deployments DROP COLUMN IF EXISTS frozen_tools")
