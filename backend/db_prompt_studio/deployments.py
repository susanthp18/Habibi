"""Bot deployments: the active row, its bundle, the list, and rollback.

One module of the ``db_prompt_studio`` package (was one 3,400-line file).
Call sites stay ``db.*``; the package re-exports every name.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from sqlalchemy import text

from agent_core.cards.defaults import COLLECTIONS_BOT_ID

from db_prompt_studio.common import (
    _bundle_hash_select,
    _column_exists,
    _db,
    _frozen_tools_select,
)
from db_prompt_studio.voices import (
    voice_locale_facts,
    voice_provider_facts,
)

logger = logging.getLogger(__name__)

def list_bot_deployments(
    *,
    environment: str | None = None,
    status: str | None = None,
    bot_id: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict[str, Any]]:
    """Runtime deployments — authoritative for what runs.

    Paged: this table gains a row on every publish, so it grows with release
    cadence rather than staying at the handful the demo has.
    """
    _mod = _db()
    engine = _mod.engine
    _rows = _mod._rows
    _as_dict = _mod._as_dict
    clamp_list_limit = _mod.clamp_list_limit
    clamp_offset = _mod.clamp_offset
    clauses = ["1=1"]
    params: dict[str, Any] = {}
    if environment in ("sandbox", "production"):
        clauses.append("d.environment = :environment")
        params["environment"] = environment
    if status in ("active", "rolled_back", "retired"):
        clauses.append("d.status = :status")
        params["status"] = status
    if bot_id:
        clauses.append("d.bot_id = :bot_id")
        params["bot_id"] = bot_id
    where = " AND ".join(clauses)
    with engine.connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT
                      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                      d.tts_voice_id, d.environment, d.status,
                      d.published_at, d.rollback_deployment_id, d.voice_config,
                      d.tuning,
                      COALESCE(u.name, d.published_by_user_id) AS published_by
                    FROM bot_deployments d
                    LEFT JOIN users u ON u.id = d.published_by_user_id
                    WHERE {where}
                    ORDER BY d.published_at DESC NULLS LAST, d.id DESC
                    LIMIT :limit OFFSET :offset
                    """
                ),
                {**params, "limit": clamp_list_limit(limit), "offset": clamp_offset(offset)},
            )
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            published = r.get("published_at")
            out.append(
                {
                    "id": r["id"],
                    "botId": r["bot_id"],
                    "promptVersionId": r["prompt_version_id"],
                    "kbSnapshotId": r.get("kb_snapshot_id"),
                    "ttsVoiceId": r.get("tts_voice_id"),
                    "environment": r["environment"],
                    "status": r["status"],
                    "publishedBy": r.get("published_by"),
                    "publishedAt": (
                        published
                        if isinstance(published, str)
                        else (published.isoformat() if published else None)
                    ),
                    "rollbackDeploymentId": r.get("rollback_deployment_id"),
                    "voiceConfig": _as_dict(r.get("voice_config")),
                    "tuning": _as_dict(r.get("tuning")),
                }
            )
        return out

# ---------------------------------------------------------------------------
# Persona & Prompt Studio — writes (PS-2)
# Live-config invariant: active prod deployment.prompt_version_id
# must equal the single prompt_versions row with status='published'.
# ---------------------------------------------------------------------------

# The tenant default card: the collections card unless BOT_ID says otherwise.
# The literal lives in agent_core.cards.defaults, not here.
DEFAULT_BOT_ID = os.getenv("BOT_ID") or COLLECTIONS_BOT_ID

def _active_deployment_sql(conn: Any) -> str:
    frozen = _frozen_tools_select(conn)
    bundle = _bundle_hash_select(conn)
    return f"""
    SELECT
      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
      d.tts_voice_id, d.environment, d.status,
      d.published_at, d.rollback_deployment_id, d.voice_config, d.tuning,
      d.traffic_pct, d.shadow, d.eval_report_id, {frozen}, {bundle},
      COALESCE(u.name, d.published_by_user_id) AS published_by
    FROM bot_deployments d
    LEFT JOIN users u ON u.id = d.published_by_user_id
    WHERE d.bot_id = :bot_id
      AND d.environment = :environment
      AND d.status = 'active'
    ORDER BY d.published_at DESC NULLS LAST, d.id DESC
    LIMIT 1
"""

def _fetch_active_deployment_row(
    conn: Any,
    *,
    bot_id: str,
    environment: str,
) -> dict[str, Any] | None:
    """Raw active deployment row inside an open connection/transaction."""
    _mod = _db()
    _one = _mod._one
    return _one(
        conn.execute(
            text(_active_deployment_sql(conn)),
            {"bot_id": bot_id, "environment": environment},
        )
    )

def get_active_deployment(
    bot_id: str | None = None,
    environment: str = "production",
) -> dict[str, Any] | None:
    """Authoritative runtime loader. One active row per (bot, env) expected.

    Multi-bot: filtered by bot_id. One published prompt per bot.
    """
    _mod = _db()
    engine = _mod.engine
    bid = (bot_id or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    env = environment if environment in ("sandbox", "production") else "production"
    with engine.connect() as conn:
        row = _fetch_active_deployment_row(conn, bot_id=bid, environment=env)
        return _map_bot_deployment_row(row) if row else None

def get_deployment(deployment_id: str) -> dict[str, Any] | None:
    """Load a deployment by id, including retired baselines used by canary split."""
    _mod = _db()
    engine = _mod.engine
    with engine.connect() as conn:
        return _fetch_bot_deployment(conn, deployment_id)

def _latest_kb_snapshot_id(conn: Any) -> str | None:
    """Newest snapshot by created_at — bookkeeping only (retrieve stays live)."""
    _mod = _db()
    _one = _mod._one
    row = _one(
        conn.execute(
            text(
                """
                SELECT id FROM kb_snapshots
                ORDER BY created_at DESC NULLS LAST, id DESC
                LIMIT 1
                """
            )
        )
    )
    return row["id"] if row else None

def _map_bot_deployment_row(r: dict[str, Any]) -> dict[str, Any]:
    _mod = _db()
    _as_dict = _mod._as_dict
    from agent_core.tuning import default_tuning, normalize_tuning

    published = r.get("published_at")
    raw_tuning = _as_dict(r.get("tuning"))
    tuning = normalize_tuning(raw_tuning) if raw_tuning else default_tuning()
    return {
        "id": r["id"],
        "botId": r["bot_id"],
        "promptVersionId": r["prompt_version_id"],
        "kbSnapshotId": r.get("kb_snapshot_id"),
        "ttsVoiceId": r.get("tts_voice_id"),
        "environment": r["environment"],
        "status": r["status"],
        "publishedBy": r.get("published_by"),
        "publishedAt": (
            published if isinstance(published, str) else (published.isoformat() if published else None)
        ),
        "rollbackDeploymentId": r.get("rollback_deployment_id"),
        "voiceConfig": _as_dict(r.get("voice_config")),
        "tuning": tuning,
        "trafficPct": int(r.get("traffic_pct") or 100),
        "shadow": bool(r.get("shadow")),
        "evalReportId": r.get("eval_report_id"),
        "frozenTools": (
            list(r["frozen_tools"])
            if isinstance(r.get("frozen_tools"), list)
            else (r.get("frozen_tools") if r.get("frozen_tools") is not None else None)
        ),
        "bundleHash": r.get("bundle_hash"),
    }

def _fetch_bot_deployment(conn: Any, deployment_id: str) -> dict[str, Any] | None:
    _mod = _db()
    _one = _mod._one
    frozen = _frozen_tools_select(conn)
    bundle = _bundle_hash_select(conn)
    r = _one(
        conn.execute(
            text(
                f"""
                SELECT
                  d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                  d.tts_voice_id, d.environment, d.status,
                  d.published_at, d.rollback_deployment_id, d.voice_config, d.tuning,
                  d.traffic_pct, d.shadow, d.eval_report_id, {frozen}, {bundle},
                  COALESCE(u.name, d.published_by_user_id) AS published_by
                FROM bot_deployments d
                LEFT JOIN users u ON u.id = d.published_by_user_id
                WHERE d.id = :id
                """
            ),
            {"id": deployment_id},
        )
    )
    return _map_bot_deployment_row(r) if r else None

def rollback_bot_deployment(deployment_id: str) -> dict[str, Any]:
    """Re-activate a prior prod deployment and re-publish its prompt version.

    Re-publish is mandatory so the live-config invariant never splits.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _tenant = _mod._tenant
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    _jsonb = _mod._jsonb
    _as_dict = _mod._as_dict
    from sqlalchemy.exc import IntegrityError

    with engine.begin() as conn:
        target = _one(
            conn.execute(
                text(
                    """
                    SELECT
                      d.id, d.bot_id, d.prompt_version_id, d.kb_snapshot_id,
                      d.tts_voice_id, d.environment, d.status, d.voice_config, d.tuning
                    FROM bot_deployments d
                    JOIN prompt_versions pv ON pv.id = d.prompt_version_id
                    WHERE d.id = :id AND pv.tenant_id = :t
                    """
                ),
                {"id": deployment_id, "t": _tenant()},
            )
        )
        if not target:
            raise KeyError(f"bot_deployment_not_found: {deployment_id}")
        if target["environment"] != "production":
            raise ValueError("rollback_requires_production_deployment")
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
            {"k": f"{target['bot_id']}:{target['environment']}"},
        )
        if target["status"] == "active":
            raise ValueError("deployment_already_active")

        prompt_version_id = target["prompt_version_id"]
        pv = _one(
            conn.execute(
                text("SELECT id FROM prompt_versions WHERE id = :id"),
                {"id": prompt_version_id},
            )
        )
        if not pv:
            raise KeyError(f"prompt_version_not_found: {prompt_version_id}")

        version_row = _one(
            conn.execute(
                text(
                    """
                    SELECT prompt, guardrails, flow, agent_card, voice, persona
                      FROM prompt_versions WHERE id = :id
                    """
                ),
                {"id": prompt_version_id},
            )
        )
        from agent_core.cards.compile import compile_card, assert_publishable as _assert_card
        from agent_core.tools.catalog import CATALOG as _CATALOG
        import authz as _authz

        uid = _actor_user_id()
        has_publish = bool(uid and _authz.has_permission(uid, _authz.AGENT_PUBLISH))
        card_raw = version_row.get("agent_card") if version_row else {}
        if not isinstance(card_raw, dict):
            card_raw = {}
        attached = None
        try:
            from agent_core.cards.schema import is_authored, parse_card
            from agent_core.skills.persist import packs_for_skill_refs

            if is_authored(card_raw):
                attached = []
                parsed = parse_card(card_raw)
                attached = packs_for_skill_refs(parsed.skills)
        except Exception:
            pass
        # Tenant-scoped: this is G5's allowlist of legal handoff targets.
        known_bots = {
            r["id"]
            for r in _mod._rows(
                conn.execute(
                    text("SELECT id FROM bots WHERE tenant_id = :t"),
                    {"t": _tenant()},
                )
            )
        }
        voice_short, voice_locale, card_locales = voice_locale_facts(
            (version_row or {}).get("voice"), (version_row or {}).get("persona")
        )
        voice_provider, bound_tts = voice_provider_facts(
            voice_short, voice_locale, target["bot_id"]
        )
        report = compile_card(
            bot_id=target["bot_id"],
            card_raw=card_raw,
            flow=(version_row or {}).get("flow"),
            catalog_names=set(_CATALOG.specs),
            known_bot_ids=known_bots,
            attached_skills=attached,
            has_publish=has_publish,
            skip_eval_gates=True,
            prompt=(version_row or {}).get("prompt"),
            prompt_guardrails=(
                (version_row or {}).get("guardrails")
                if isinstance((version_row or {}).get("guardrails"), dict)
                else {}
            ),
            voice_short_name=voice_short,
            voice_locale=voice_locale,
            card_locales=card_locales,
            voice_provider=voice_provider,
            bound_tts_providers=bound_tts,
        )
        _assert_card(report)

        current = _fetch_active_deployment_row(
            conn, bot_id=target["bot_id"], environment="production"
        )

        try:
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'archived', updated_at = now()
                    WHERE status = 'published' AND bot_id = :bot_id
                    """
                ),
                {"bot_id": target["bot_id"]},
            )
            conn.execute(
                text(
                    """
                    UPDATE prompt_versions
                    SET status = 'published', updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": prompt_version_id},
            )
            if current:
                conn.execute(
                    text(
                        """
                        UPDATE bot_deployments
                        SET status = 'rolled_back', updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": current["id"]},
                )

            # Insert a fresh active row pointing at the rolled-back config
            # (keeps history; links rollback_deployment_id to the prior active).
            new_id = _id("DEP")
            # The executable contract of the version being restored, carried
            # forward. Guarded the same way publish guards it, so an unmigrated
            # database keeps working. Omitted, `frozen_tools` came back NULL,
            # `_map_bot_deployment` turned that into `[]`, and `effective_tools`
            # took the frozen branch and unioned nothing — every connector tool
            # silently disappeared from a rolled-back deployment.
            carried: dict[str, Any] = {}
            carry_sql = ""
            carry_val = ""
            for column in ("frozen_tools", "bundle_hash"):
                if not _column_exists(conn, "bot_deployments", column):
                    continue
                prior_value = _one(
                    conn.execute(
                        text(f"SELECT {column} AS v FROM bot_deployments WHERE id = :id"),
                        {"id": deployment_id},
                    )
                )
                carry_sql += f", {column}"
                if column == "frozen_tools":
                    carry_val += ", CAST(:frozen AS jsonb)"
                    carried["frozen"] = _jsonb((prior_value or {}).get("v"))
                else:
                    carry_val += ", :bundle_hash"
                    carried["bundle_hash"] = (prior_value or {}).get("v")
            conn.execute(
                text(
                    f"""
                    INSERT INTO bot_deployments (
                      id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                      environment, status, published_by_user_id, published_at,
                      rollback_deployment_id, voice_config, tuning{carry_sql},
                      created_at, updated_at
                    ) VALUES (
                      :id, :bot_id, :prompt_version_id, :kb_snapshot_id, :tts_voice_id,
                      'production', 'active', :actor, now(),
                      :rollback_id, CAST(:voice_config AS jsonb), CAST(:tuning AS jsonb){carry_val},
                      now(), now()
                    )
                    """
                ),
                {
                    "id": new_id,
                    "bot_id": target["bot_id"],
                    "prompt_version_id": prompt_version_id,
                    "kb_snapshot_id": target.get("kb_snapshot_id"),
                    "tts_voice_id": target.get("tts_voice_id"),
                    "actor": _actor_user_id(),
                    "rollback_id": current["id"] if current else deployment_id,
                    "voice_config": _jsonb(_as_dict(target.get("voice_config"))),
                    "tuning": _jsonb(_as_dict(target.get("tuning"))),
                    # Carried from the deployment being restored, because they
                    # describe *that* version. Omitted, `frozen_tools` came back
                    # NULL, `_map_bot_deployment` turned that into `[]`, and
                    # `effective_tools` took the frozen branch and unioned
                    # nothing — every connector tool silently disappeared from a
                    # rolled-back deployment.
                    **carried,
                },
            )

            # A rollback changes what callers hear exactly as much as a publish
            # does, so it belongs in the same chain.
            from agent_core import change_log

            # The gates the re-shipped version passed at its publish, from the
            # bundle stored on it. A rollback recorded no verdict at all before.
            compiled = _as_dict(
                conn.execute(
                    text("SELECT compiled FROM prompt_versions WHERE id = :id"),
                    {"id": prompt_version_id},
                ).scalar()
            )
            change_log.record_rollback(
                conn,
                tenant_id=_tenant(),
                actor_user_id=_actor_user_id() or "system",
                entry_id=_id("AUD"),
                bot_id=target["bot_id"],
                to_deployment_id=new_id,
                from_deployment_id=current["id"] if current else None,
                version_id=prompt_version_id,
                report=compiled,
            )
            try:
                from agent_core.canary import close_running_experiments

                close_running_experiments(
                    conn,
                    bot_id=target["bot_id"],
                    environment="production",
                    reason="deployment_rollback",
                )
            except Exception:
                logger.exception("could not close running experiments after deployment rollback")
        except IntegrityError as exc:
            raise ValueError("publish_conflict") from exc

        row = _fetch_bot_deployment(conn, new_id)
    assert row is not None
    return row
