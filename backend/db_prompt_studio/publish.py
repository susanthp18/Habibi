"""Publishing: freeze, compile, deploy, record -- and the fleet rebuild a member
publish triggers on its doors.

One module of the ``db_prompt_studio`` package (was one 3,400-line file).
Call sites stay ``db.*``; the package re-exports every name.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any

from sqlalchemy import text

from db_prompt_studio.common import (
    _column_exists,
    _db,
)
from db_prompt_studio.voices import (
    resolve_prompt_azure_voice,
    voice_locale_facts,
    voice_provider_facts,
)
from db_prompt_studio.deployments import (
    DEFAULT_BOT_ID,
    _fetch_active_deployment_row,
    _latest_kb_snapshot_id,
)
from db_prompt_studio.versions import (
    _DEFAULT_AZURE_TTS_VOICE,
    _fetch_prompt_version,
    _prompt_voice,
    get_prompt_version,
)
from db_prompt_studio.compile import (
    _fleet_members,
    compile_agent_studio_card,
    doors_merging,
)
from agent_core.dicts import sub

logger = logging.getLogger(__name__)

def _change_log_components(
    conn: Any, version_id: str, target: dict[str, Any], summary: str
) -> dict[str, Any]:
    """The version as the change log hashes it.

    Read back rather than taken from ``target``: the publishing transaction
    rewrites ``agent_card`` (the shipped experiment) and ``tuning`` before this
    point, so the in-memory copy is stale and the digest would describe a
    version that was never live.
    """
    _mod = _db()
    _one = _mod._one
    row = _one(
        conn.execute(
            text(
                """
                SELECT id, label, prompt, persona, voice, guardrails, flow, agent_card
                  FROM prompt_versions WHERE id = :id
                """
            ),
            {"id": version_id},
        )
    ) or {}
    return {**dict(row), "label": row.get("label") or target.get("label"), "summary": summary}

def publish_prompt_version(
    version_id: str,
    summary: str = "",
    *,
    kb_snapshot_id: str | None = None,
    tuning: dict[str, Any] | None = None,
    traffic_pct: int | None = None,
    auto_rollback: list[str] | None = None,
) -> dict[str, Any]:
    """Archive current published → promote draft → swap active prod deployment.

    kb_snapshot_id: explicit Sandbox pin wins; else prior active snap, else latest.
    tuning: explicit AgentTuning from Sandbox Promote; else prior deployment tuning.
    """
    _mod = _db()
    engine = _mod.engine

    with engine.begin() as conn:
        frozen = _freeze(conn, version_id, traffic_pct=traffic_pct, auto_rollback=auto_rollback)
        compiled = _compile(conn, frozen)
        deployed = _deploy(
            conn, frozen, compiled, kb_snapshot_id=kb_snapshot_id, tuning=tuning, summary=summary
        )
        _record(conn, frozen, compiled, deployed)
        row = _fetch_prompt_version(conn, version_id)
    bot_id = frozen.bot_id
    assert row is not None

    # Publishing a member is a fleet act. A door serves `compiled.fleet_flow`,
    # derived from its members' published versions, so every door that merged
    # this card gets a *new* deployment carrying the rebuilt bundle -- one
    # deployment id is one bundle_hash, which is what "which version said this
    # on the hop" needs -- and a change-log entry naming the member version
    # that caused it. Outside the transaction above because a rebuild opens
    # its own, and a failure must not roll back a publish that already
    # succeeded: the reason is returned and logged, and fleet_parity reports
    # the stale door.
    rebuilds: list[dict[str, Any]] = []
    for door in doors_merging(bot_id):
        try:
            rebuilds.append(
                rebuild_fleet_deployment(
                    door, member_bot_id=bot_id, member_version_id=str(row["id"])
                )
            )
        except Exception as exc:
            logger.exception("could not rebuild the fleet bundle owned by %s", door)
            rebuilds.append({"doorBotId": door, "rebuilt": False, "reason": f"error:{exc}"})
    return {**row, "fleetRebuilds": rebuilds}

def rebuild_fleet_deployment(
    door_bot_id: str, *, member_bot_id: str, member_version_id: str
) -> dict[str, Any]:
    """Re-derive a door's bundle from its members' published versions and ship
    it as a new deployment.

    Not `recompile_published_bundle`: that fills `compiled` in place on a row
    that never had one (a backfill) and deliberately leaves the deployment's
    identity alone. This is the opposite case -- the artefact a live
    deployment serves has changed, so the deployment changes: the active row
    is retired, a new one is inserted with the same voice, tuning, snapshot
    and frozen tools and the new bundle_hash, and the change log records
    which member version made it happen.

    A door with a running canary experiment is not rebuilt: the experiment
    compares two deployments, and replacing the baseline under it would
    measure nothing. The reason is returned; the parity report shows the
    stale door until the experiment ends.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _jsonb = _mod._jsonb
    _tenant = _mod._tenant
    _id = _mod._id
    from agent_core import change_log

    with engine.connect() as conn:
        live = _one(
            conn.execute(
                text(
                    "SELECT id FROM prompt_versions "
                    " WHERE bot_id = :b AND status = 'published' AND tenant_id = :t LIMIT 1"
                ),
                {"b": door_bot_id, "t": _tenant()},
            )
        )
    if live is None:
        return {"doorBotId": door_bot_id, "rebuilt": False, "reason": "no_published_version"}

    report = compile_agent_studio_card(door_bot_id, prompt_version_id=str(live["id"]))
    bundle = report.get("bundle") or {}
    bundle_hash = str(bundle.get("bundle_hash") or "")
    version_id = str(bundle.get("prompt_version_id") or "")
    if not bundle_hash or not version_id:
        return {"doorBotId": door_bot_id, "rebuilt": False, "reason": "no_compiled_bundle"}

    with engine.begin() as conn:
        prior = _fetch_active_deployment_row(conn, bot_id=door_bot_id, environment="production")
        if prior is None:
            return {"doorBotId": door_bot_id, "rebuilt": False, "reason": "no_active_deployment"}
        if str(prior.get("bundle_hash") or "") == bundle_hash:
            return {
                "doorBotId": door_bot_id,
                "rebuilt": False,
                "reason": "unchanged",
                "deploymentId": prior["id"],
                "bundleHash": bundle_hash,
            }
        running = _one(
            conn.execute(
                text(
                    "SELECT id FROM deployment_experiments "
                    " WHERE bot_id = :b AND status = 'running' AND tenant_id = :t LIMIT 1"
                ),
                {"b": door_bot_id, "t": _tenant()},
            )
        )
        if running is not None:
            return {
                "doorBotId": door_bot_id,
                "rebuilt": False,
                "reason": f"experiment_running:{running['id']}",
                "deploymentId": prior["id"],
            }
        conn.execute(
            text(
                "UPDATE prompt_versions SET compiled = CAST(:c AS jsonb), updated_at = now() "
                " WHERE id = :id AND tenant_id = :t"
            ),
            {"c": _jsonb(bundle), "id": version_id, "t": _tenant()},
        )
        conn.execute(
            text("UPDATE bot_deployments SET status = 'retired', updated_at = now() WHERE id = :id"),
            {"id": prior["id"]},
        )
        dep_id = _id("DEP")
        conn.execute(
            text(
                """
                INSERT INTO bot_deployments (
                  id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                  environment, status, published_by_user_id, published_at,
                  rollback_deployment_id, voice_config, tuning, traffic_pct, shadow,
                  frozen_tools, bundle_hash, created_at, updated_at
                )
                SELECT :id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                       environment, 'active', :actor, now(),
                       id, voice_config, tuning, 100, false,
                       frozen_tools, :bundle_hash, now(), now()
                  FROM bot_deployments WHERE id = :prior
                """
            ),
            {
                "id": dep_id,
                "actor": _mod._actor_user_id(),
                "bundle_hash": bundle_hash,
                "prior": prior["id"],
            },
        )
        change_log.record_fleet_rebuild(
            conn,
            tenant_id=_tenant(),
            actor_user_id=_mod._actor_user_id(),
            entry_id=_id("AUD"),
            bot_id=door_bot_id,
            deployment_id=dep_id,
            previous_deployment_id=str(prior["id"]),
            bundle_hash=bundle_hash,
            member_bot_id=member_bot_id,
            member_version_id=member_version_id,
        )
    logger.info(
        "fleet rebuilt · door=%s · deployment=%s · because %s published %s",
        door_bot_id,
        dep_id,
        member_bot_id,
        member_version_id,
    )
    return {
        "doorBotId": door_bot_id,
        "rebuilt": True,
        "deploymentId": dep_id,
        "previousDeploymentId": str(prior["id"]),
        "bundleHash": bundle_hash,
    }

@dataclasses.dataclass(frozen=True)
class _Frozen:
    """The draft as ``_freeze`` read and locked it: every value the later
    publish phases take from the row and its bot rather than from the caller."""

    version_id: str
    target: dict[str, Any]
    bot_id: str
    known_bots: set[str]
    card_raw: dict[str, Any]
    attached: list[Any] | None
    pct: int
    triggers: list[str]
    cert_ok: bool | None
    uid: str | None
    has_publish: bool
    voice_short: str
    voice_locale: str | None
    card_locales: list[str]
    voice_provider: Any
    bound_tts: Any
    candidate_key: str

@dataclasses.dataclass(frozen=True)
class _Compiled:
    report: Any
    shipped_card: dict[str, Any]
    compiled_dump: dict[str, Any]
    bundle_hash: str

@dataclasses.dataclass(frozen=True)
class _Deployed:
    dep_id: str
    note: str
    previously_published: dict[str, Any] | None

def _freeze(
    conn: Any,
    version_id: str,
    *,
    traffic_pct: int | None,
    auto_rollback: list[str] | None,
) -> _Frozen:
    """Load and lock the draft; refuse a non-draft or an archived bot; read
    the facts the compile needs (known bots, attached skills, experiment,
    actor, mouth columns, content key)."""
    _mod = _db()
    _rows = _mod._rows
    _one = _mod._one
    _tenant = _mod._tenant
    _actor_user_id = _mod._actor_user_id

    target = _one(
        conn.execute(
            text(
                """
                SELECT id, status, voice, persona, label, tuning, flow, bot_id, agent_card,
                       prompt, guardrails
                FROM prompt_versions WHERE id = :id AND tenant_id = :t
                """
            ),
            {"id": version_id, "t": _tenant()},
        )
    )
    if not target:
        raise KeyError(f"prompt_version_not_found: {version_id}")
    if target["status"] != "draft":
        raise ValueError("prompt_version_not_draft")

    bot_id = str(target.get("bot_id") or DEFAULT_BOT_ID).strip() or DEFAULT_BOT_ID
    archived = _one(
        conn.execute(
            text("SELECT archived_at FROM bots WHERE id = :id"),
            {"id": bot_id},
        )
    )
    if archived and archived.get("archived_at") is not None:
        raise ValueError("bot_archived")
    # Serialize publish/rollback for this bot+env (single-active invariant).
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"{bot_id}:production"},
    )

    # Tenant-scoped: this is G5's allowlist of legal handoff targets.
    known_bots = {
        r["id"]
        for r in _rows(
            conn.execute(
                text("SELECT id FROM bots WHERE tenant_id = :t"),
                {"t": _tenant()},
            )
        )
    }
    card_raw = sub(target, "agent_card")
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
    exp = sub(card_raw, "experiment")
    pct = traffic_pct if traffic_pct is not None else int(exp.get("traffic_pct") or 100)
    triggers = auto_rollback if auto_rollback is not None else list(exp.get("auto_rollback") or [])
    a2a_raw = sub(card_raw, "a2a")
    cert_ok = None
    if a2a_raw.get("expose"):
        try:
            from agent_core.a2a import partner_has_cert

            cert_ok = partner_has_cert(bot_id)
        except Exception:
            cert_ok = False
    import authz as _authz

    uid = _actor_user_id()
    has_publish = bool(uid and _authz.has_permission(uid, _authz.AGENT_PUBLISH))
    voice_short, voice_locale, card_locales = voice_locale_facts(
        target.get("voice"), target.get("persona")
    )
    voice_provider, bound_tts = voice_provider_facts(voice_short, voice_locale, bot_id)
    # Same identity the preview and the suite run used -- computed from the
    # mapped row (normalised voice/tuning/flow), not the raw columns, or
    # the three keys would not agree on the same content.
    from agent_core.eval.provenance import content_key_for_version

    candidate_key = content_key_for_version(get_prompt_version(version_id) or {})
    return _Frozen(
        version_id=version_id,
        target=target,
        bot_id=bot_id,
        known_bots=known_bots,
        card_raw=card_raw,
        attached=attached,
        pct=pct,
        triggers=triggers,
        cert_ok=cert_ok,
        uid=uid,
        has_publish=has_publish,
        voice_short=voice_short,
        voice_locale=voice_locale,
        card_locales=card_locales,
        voice_provider=voice_provider,
        bound_tts=bound_tts,
        candidate_key=candidate_key,
    )

def _compile(conn: Any, f: _Frozen) -> _Compiled:
    """compile_card + the fleet gates + assert_publishable; fold the shipped
    experiment back into the card; compile_bundle -> bundle hash."""
    _mod = _db()
    _jsonb = _mod._jsonb
    _latest_twin_gate_report = _mod._latest_twin_gate_report
    get_latest_eval_report = _mod.get_latest_eval_report
    version_id, target, bot_id, card_raw = f.version_id, f.target, f.bot_id, f.card_raw
    known_bots, attached, pct, triggers = f.known_bots, f.attached, f.pct, f.triggers
    candidate_key, cert_ok, has_publish = f.candidate_key, f.cert_ok, f.has_publish
    voice_short, voice_locale, card_locales = f.voice_short, f.voice_locale, f.card_locales
    voice_provider, bound_tts = f.voice_provider, f.bound_tts

    # Compiler: flow + Agent Card gates. Empty card is legacy (G0 skipped).
    from agent_core.cards.compile import compile_card, assert_publishable as _assert_card
    from agent_core.tools.catalog import CATALOG as _CATALOG

    def _report(kind: str) -> dict[str, Any] | None:
        by_content = get_latest_eval_report(bot_id=bot_id, kind=kind, content_key=candidate_key)
        if by_content is not None:
            if by_content.get("prompt_version_id") != version_id:
                by_content = {**by_content, "cached": True}
            return by_content
        return get_latest_eval_report(bot_id=bot_id, kind=kind, prompt_version_id=version_id)

    report = compile_card(
        bot_id=bot_id,
        card_raw=card_raw,
        flow=target.get("flow"),
        catalog_names=set(_CATALOG.specs),
        known_bot_ids=known_bots,
        eval_report=_report("regression"),
        redteam_report=_report("redteam"),
        twin_report=_latest_twin_gate_report(),
        outbound_report=_report("outbound"),
        content_key=candidate_key,
        attached_skills=attached,
        traffic_pct=pct,
        auto_rollback=triggers,
        has_publish=has_publish,
        a2a_cert_ok=cert_ok,
        voice_short_name=voice_short,
        voice_locale=voice_locale,
        card_locales=card_locales,
        voice_provider=voice_provider,
        bound_tts_providers=bound_tts,
        prompt=target.get("prompt"),
        prompt_guardrails=(
            sub(target, "guardrails")
        ),
    )
    # The fleet gates run here, before the assert, rather than alongside
    # `compile_bundle` further down. They are warn-level today so this
    # changes no publish outcome -- which is the point of wiring them now:
    # when G-F2/G-F6/G-F15 are promoted to blocking, the promotion is a
    # status change in one function and not new plumbing on the publish
    # path.
    from agent_core.fleet.compile import fleet_gates as _fleet_gates

    report.gates.extend(
        _fleet_gates(
            primary_bot_id=bot_id,
            card_raw=card_raw if isinstance(card_raw, dict) else {},
            flow=sub(target, "flow"),
            members=_fleet_members(card_raw),
        )
    )
    _assert_card(report)
    # Fold the shipped experiment back into the card. The deployment row
    # recorded the split, but the card kept whatever it was authored with —
    # so the Studio's Ship tab, which reads the card, showed 100% after a
    # 40% canary and would silently re-ship at full traffic on the next
    # publish. Only valid triggers are stored: CardExperiment types them as
    # a Literal, so an unknown one would make the card unparseable.
    shipped_card = card_raw
    try:
        from agent_core.cards.compile import _ROLLBACK_TRIGGERS
        from agent_core.cards.schema import is_authored as _is_authored

        if _is_authored(card_raw):
            shipped_exp = {
                "traffic_pct": int(pct),
                "auto_rollback": [t for t in triggers if t in _ROLLBACK_TRIGGERS],
            }
            if (card_raw.get("experiment") or {}) != shipped_exp:
                shipped_card = {**card_raw, "experiment": shipped_exp}
                conn.execute(
                    text(
                        """
                        UPDATE prompt_versions
                        SET agent_card = CAST(:card AS jsonb), updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": version_id, "card": _jsonb(shipped_card)},
                )
    except Exception:
        logger.exception("could not persist the shipped experiment onto the card")
    # Compile the persisted artifact from the exact card that is about to
    # become live. Ship controls can rewrite ``experiment`` above; hashing
    # the pre-rewrite card would make the deployment point at a contract
    # that production never ran.
    from agent_core.cards.compile import CompileReport
    from agent_core.fleet.compile import compile_bundle

    shipped_report = CompileReport.model_validate(
        {**report.model_dump(mode="json"), "card": shipped_card}
    )
    compiled_bundle = compile_bundle(
        report=shipped_report,
        prompt=str(target.get("prompt") or ""),
        persona=sub(target, "persona"),
        guardrails=sub(target, "guardrails"),
        flow=sub(target, "flow"),
        prompt_version_id=version_id,
        attached_skills=attached,
        source_ids={"bot_id": bot_id, "prompt_version_id": version_id},
        members=_fleet_members(shipped_card),
    )
    compiled_dump = compiled_bundle.model_dump(mode="json")
    bundle_hash = compiled_bundle.bundle_hash
    try:
        from agent_core.skills.persist import sync_attachments_from_card

        sync_attachments_from_card(version_id, card_raw)
    except Exception:
        logger.exception("skill attachment sync failed")
    return _Compiled(
        report=report,
        shipped_card=shipped_card,
        compiled_dump=compiled_dump,
        bundle_hash=bundle_hash,
    )

def _deploy(
    conn: Any,
    f: _Frozen,
    c: _Compiled,
    *,
    kb_snapshot_id: str | None,
    tuning: dict[str, Any] | None,
    summary: str,
) -> _Deployed:
    """Resolve voice, tuning and KB snapshot against the prior production
    deployment; archive the live version, promote the draft, swap the
    ``bot_deployments`` row."""
    _mod = _db()
    _one = _mod._one
    _id = _mod._id
    _actor_user_id = _mod._actor_user_id
    _jsonb = _mod._jsonb
    _as_dict = _mod._as_dict
    from sqlalchemy.exc import IntegrityError
    from agent_core.tuning import apply_voice_config_overlay, default_tuning, normalize_tuning

    version_id, target, bot_id, card_raw = f.version_id, f.target, f.bot_id, f.card_raw
    pct, triggers = f.pct, f.triggers
    shipped_card, compiled_dump, bundle_hash = c.shipped_card, c.compiled_dump, c.bundle_hash

    note = (summary or "").strip()
    voice = _prompt_voice(target.get("voice"))
    # Column stores Azure ShortName (no FK to legacy tts_voices aliases).
    if tuning is not None:
        early = normalize_tuning(tuning)
        tts_voice_id = str((early.get("tts") or {}).get("voice") or "").strip() or None
    else:
        tts_voice_id = None
    if not tts_voice_id:
        tts_voice_id = resolve_prompt_azure_voice(voice) or _DEFAULT_AZURE_TTS_VOICE

    prior = _fetch_active_deployment_row(
        conn, bot_id=bot_id, environment="production"
    )
    resolved_snap = kb_snapshot_id
    if not resolved_snap:
        resolved_snap = prior.get("kb_snapshot_id") if prior else None
    if not resolved_snap:
        resolved_snap = _latest_kb_snapshot_id(conn)
    if resolved_snap and not _one(
        conn.execute(text("SELECT 1 FROM kb_snapshots WHERE id = :id"), {"id": resolved_snap})
    ):
        raise ValueError(f"kb_snapshot_not_found: {resolved_snap}")

    voice_config = _as_dict(prior.get("voice_config")) if prior else {}
    # Keep voice_config.azureVoiceName aligned with the authoritative ShortName.
    voice_config = {
        **voice_config,
        **{
            k: voice.get(k)
            for k in ("speed", "pitch", "warmth", "pauseMs", "sampleText", "style", "params")
            if k in voice
        },
        "azureVoiceName": tts_voice_id,
        "voiceId": tts_voice_id,
    }
    if tuning is not None:
        # Sandbox Promote — Tuning Studio payload is authoritative.
        resolved_tuning = normalize_tuning(tuning)
    else:
        prior_tuning = _as_dict(prior.get("tuning")) if prior else {}
        target_tuning = _as_dict(target.get("tuning"))
        seed = target_tuning or prior_tuning
        resolved_tuning = normalize_tuning(seed) if seed else default_tuning()
        # Prompt Studio publish: fold voice sliders into AgentTuning.tts once
        # so runtime never needs the warmth/speed/pitch overlay.
        resolved_tuning = apply_voice_config_overlay(
            resolved_tuning,
            voice_name=tts_voice_id,
            speed=float(voice.get("speed", 1.0)),
            pitch=int(voice.get("pitch", 0)),
            warmth=int(voice.get("warmth", 60)),
            params=voice.get("params"),
            style=voice.get("style") or None,
        )

    conn.execute(
        text(
            """
            UPDATE prompt_versions
            SET tuning = CAST(:tuning AS jsonb), updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": version_id, "tuning": _jsonb(resolved_tuning)},
    )

    # Captured while it is still the live row — the change log diffs the
    # incoming version against the one it replaces, and the next statement
    # archives it.
    previously_published = _one(
        conn.execute(
            text(
                """
                SELECT id, label, prompt, persona, voice, guardrails, flow, agent_card
                  FROM prompt_versions
                 WHERE bot_id = :bot_id AND status = 'published'
                 LIMIT 1
                """
            ),
            {"bot_id": bot_id},
        )
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
            {"bot_id": bot_id},
        )
        compiled_sql = ""
        compiled_params: dict[str, Any] = {"id": version_id, "summary": note}
        if _column_exists(conn, "prompt_versions", "compiled"):
            compiled_sql = ", compiled = CAST(:compiled AS jsonb)"
            compiled_params["compiled"] = _jsonb(compiled_dump)
        conn.execute(
            text(
                f"""
                UPDATE prompt_versions
                SET status = 'published',
                    summary = CASE WHEN :summary = '' THEN summary ELSE :summary END,
                    updated_at = now()
                    {compiled_sql}
                WHERE id = :id AND status = 'draft'
                """
            ),
            compiled_params,
        )
        # Force unique-index check before we leave the transaction half-done.
        promoted = _one(
            conn.execute(
                text("SELECT id, status FROM prompt_versions WHERE id = :id"),
                {"id": version_id},
            )
        )
        if not promoted or promoted["status"] != "published":
            raise ValueError("publish_failed")

        if prior:
            conn.execute(
                text(
                    """
                    UPDATE bot_deployments
                    SET status = 'retired', updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": prior["id"]},
            )

        dep_id = _id("DEP")
        frozen_names: list[str] = []
        try:
            from agent_core.connectors.persist import bound_tool_names
            from agent_core.cards.schema import is_authored as _authored_card, parse_card as _parse_card

            snap_card = shipped_card if isinstance(shipped_card, dict) else card_raw
            if _authored_card(snap_card):
                frozen_names = sorted(
                    bound_tool_names([c.model_dump() for c in _parse_card(snap_card).connectors])
                )
        except Exception:
            logger.exception("could not snapshot connector tools for deployment")
            frozen_names = []
        frozen_sql = ""
        frozen_val = ""
        params = {
            "id": dep_id,
            "bot_id": bot_id,
            "prompt_version_id": version_id,
            "kb_snapshot_id": resolved_snap,
            "tts_voice_id": tts_voice_id,
            "actor": _actor_user_id(),
            "rollback_id": prior["id"] if prior else None,
            "voice_config": _jsonb(voice_config),
            "tuning": _jsonb(resolved_tuning),
            "traffic_pct": pct,
            "shadow": False,
        }
        if _column_exists(conn, "bot_deployments", "frozen_tools"):
            frozen_sql = ", frozen_tools"
            frozen_val = ", CAST(:frozen AS jsonb)"
            params["frozen"] = _jsonb(frozen_names)
        if _column_exists(conn, "bot_deployments", "bundle_hash"):
            frozen_sql += ", bundle_hash"
            frozen_val += ", :bundle_hash"
            params["bundle_hash"] = bundle_hash
        conn.execute(
            text(
                f"""
                INSERT INTO bot_deployments (
                  id, bot_id, prompt_version_id, kb_snapshot_id, tts_voice_id,
                  environment, status, published_by_user_id, published_at,
                  rollback_deployment_id, voice_config, tuning,
                  traffic_pct, shadow{frozen_sql}, created_at, updated_at
                ) VALUES (
                  :id, :bot_id, :prompt_version_id, :kb_snapshot_id, :tts_voice_id,
                  'production', 'active', :actor, now(),
                  :rollback_id, CAST(:voice_config AS jsonb), CAST(:tuning AS jsonb),
                  :traffic_pct, :shadow{frozen_val}, now(), now()
                )
                """
            ),
            params,
        )
        try:
            from agent_core.canary import record_experiment

            record_experiment(
                conn,
                bot_id=bot_id,
                canary_deployment_id=dep_id,
                baseline_deployment_id=prior["id"] if prior else None,
                traffic_pct=pct,
                auto_rollback=list(triggers or []),
            )
        except Exception:
            logger.exception("canary experiment record failed")
    except IntegrityError as exc:
        raise ValueError("publish_conflict") from exc
    return _Deployed(dep_id=dep_id, note=note, previously_published=previously_published)

def _record(conn: Any, f: _Frozen, c: _Compiled, d: _Deployed) -> None:
    """The change log entry for the publish that just happened."""
    _mod = _db()
    _tenant = _mod._tenant
    _id = _mod._id
    from sqlalchemy.exc import IntegrityError

    version_id, target, bot_id, uid = f.version_id, f.target, f.bot_id, f.uid
    pct, triggers, report = f.pct, f.triggers, c.report
    dep_id, note, previously_published = d.dep_id, d.note, d.previously_published

    try:
        # Change log — inside the transaction on purpose. A record that can
        # be lost when the process dies mid-publish is worse than none,
        # because it looks complete. Not wrapped in try/except for the same
        # reason: if the agent's configuration history cannot be written,
        # the configuration must not change either.
        from agent_core import change_log

        change_log.record_publish(
            conn,
            tenant_id=_tenant(),
            actor_user_id=uid or "system",
            entry_id=_id("AUD"),
            bot_id=bot_id,
            version=_change_log_components(conn, version_id, target, note),
            previous_version=previously_published,
            deployment_id=dep_id,
            traffic_pct=pct,
            auto_rollback=list(triggers or []),
            report=report,
        )
    except IntegrityError as exc:
        raise ValueError("publish_conflict") from exc
