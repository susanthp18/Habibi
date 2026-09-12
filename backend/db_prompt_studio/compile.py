"""Compiling a card: the gates, the fleet merge, recompiling a live bundle, and
the effective contract.

One module of the ``db_prompt_studio`` package (was one 3,400-line file).
Call sites stay ``db.*``; the package re-exports every name.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db_prompt_studio.common import (
    _column_exists,
    _db,
)
from db_prompt_studio.voices import (
    voice_locale_facts,
    voice_provider_facts,
)
from db_prompt_studio.versions import (
    get_prompt_version,
    get_published_prompt_version,
)
from db_prompt_studio.cards import (
    _studio_card_versions,
)

logger = logging.getLogger(__name__)

def compile_agent_studio_card(
    bot_id: str,
    *,
    prompt_version_id: str | None = None,
    card_raw: dict[str, Any] | None = None,
    flow: Any = None,
    traffic_pct: int | None = None,
    auto_rollback: list[str] | None = None,
    voice: dict[str, Any] | None = None,
    persona: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _mod = _db()
    list_bot_ids = _mod.list_bot_ids
    _latest_twin_gate_report = _mod._latest_twin_gate_report
    get_latest_eval_report = _mod.get_latest_eval_report
    from agent_core.cards.compile import compile_card
    from agent_core.tools.catalog import CATALOG

    published, draft = _studio_card_versions(bot_id)
    explicit = get_prompt_version(prompt_version_id) if prompt_version_id else None
    if prompt_version_id and explicit is None:
        raise KeyError(f"prompt_version_not_found: {prompt_version_id}")
    if explicit and explicit.get("botId") != bot_id:
        raise ValueError("prompt_version_bot_mismatch")
    card = card_raw if isinstance(card_raw, dict) and card_raw else None
    if card is None:
        # Compile preview must gate what publish will actually ship, and publish
        # ships the draft. Falling straight to published reported a green compile
        # for a draft whose card had not been checked.
        for row in (explicit, draft, published):
            candidate = (row or {}).get("agentCard")
            if isinstance(candidate, dict) and candidate:
                card = candidate
                break
    # No card on any version is what the compiler is told: G0 reports the
    # legacy mouth. It used to be handed the first-party constant instead,
    # which gated a card nobody had stored.
    card = card or {}
    graph = flow if flow is not None else ((explicit or draft or published or {}).get("flow") or {})
    # Same precedence the card itself follows: preview what publish will ship,
    # which is the draft. The caller may pass the editor's unsaved voice and
    # persona instead — without that the preview gates the last autosave, and
    # G15 is exactly the gate an operator would trip between two of them.
    mouth = explicit or draft or published or {}
    voice_short, voice_locale, card_locales = voice_locale_facts(
        voice if voice is not None else mouth.get("voice"),
        persona if persona is not None else mouth.get("persona"),
    )
    voice_provider, bound_tts = voice_provider_facts(voice_short, voice_locale, bot_id)
    attached = None
    try:
        from agent_core.cards.schema import is_authored, parse_card
        from agent_core.skills.persist import packs_for_skill_refs

        raw = card if isinstance(card, dict) else {}
        if is_authored(raw):
            attached = []
            parsed = parse_card(raw)
            attached = packs_for_skill_refs(parsed.skills)
    except Exception:
        pass
    version_id = mouth.get("id")
    # The identity of what is about to ship: a report filed against the same
    # content on any row counts, one filed against different content on this
    # row does not.
    from agent_core.eval.provenance import content_key as _content_key

    candidate_key = _content_key(
        card=card,
        flow=graph,
        prompt=mouth.get("prompt"),
        persona=persona if persona is not None else mouth.get("persona"),
        guardrails=mouth.get("guardrails"),
        voice=voice if voice is not None else mouth.get("voice"),
        tuning=mouth.get("tuning"),
        skill_packs=attached or [],
    )

    def _report(kind: str) -> dict[str, Any] | None:
        by_content = get_latest_eval_report(bot_id=bot_id, kind=kind, content_key=candidate_key)
        if by_content is not None:
            if by_content.get("prompt_version_id") != version_id:
                by_content = {**by_content, "cached": True}
            return by_content
        return get_latest_eval_report(bot_id=bot_id, kind=kind, prompt_version_id=version_id)

    report = compile_card(
        bot_id=bot_id,
        card_raw=card,
        flow=graph,
        catalog_names=set(CATALOG.specs),
        known_bot_ids=list_bot_ids(),
        eval_report=_report("regression"),
        redteam_report=_report("redteam"),
        twin_report=_latest_twin_gate_report(),
        outbound_report=_report("outbound"),
        content_key=candidate_key,
        attached_skills=attached,
        # Without these the preview read the card's stored experiment while
        # publish used the Ship tab's, so G12 reported "full ship" green and the
        # very next call 422'd on "canary split requires auto_rollback".
        traffic_pct=traffic_pct,
        auto_rollback=auto_rollback,
        voice_short_name=voice_short,
        voice_locale=voice_locale,
        card_locales=card_locales,
        voice_provider=voice_provider,
        bound_tts_providers=bound_tts,
        prompt=mouth.get("prompt"),
        prompt_guardrails=mouth.get("guardrails") if isinstance(mouth.get("guardrails"), dict) else {},
    )
    from agent_core.fleet.compile import compile_bundle, fleet_gates

    # Warn-level, and appended rather than folded into `compile_card` because
    # they need the merged graph, which only exists once the members are known.
    report.gates.extend(
        fleet_gates(
            primary_bot_id=bot_id,
            card_raw=card if isinstance(card, dict) else {},
            flow=graph if isinstance(graph, dict) else {},
            members=_fleet_members(card),
        )
    )

    bundle = compile_bundle(
        report=report,
        prompt=str(mouth.get("prompt") or ""),
        persona=mouth.get("persona") if isinstance(mouth.get("persona"), dict) else {},
        guardrails=mouth.get("guardrails") if isinstance(mouth.get("guardrails"), dict) else {},
        flow=graph if isinstance(graph, dict) else {},
        prompt_version_id=version_id,
        attached_skills=attached,
        source_ids={"bot_id": bot_id, "prompt_version_id": str(version_id or "")},
        members=_fleet_members(card),
    )
    return report.model_copy(
        update={"bundle": bundle.model_dump(mode="json"), "doors_merging": doors_merging(bot_id)}
    ).model_dump()

def doors_merging(bot_id: str) -> list[str]:
    """Published cards whose compiled bundle contains ``bot_id``'s subgraph.

    Read from `compiled.entry_by_specialist` -- what was actually merged -- and
    not from the handoff graph. The graph cannot answer this: `insurance-v1` and
    `collections-clone-9ff4b6` both hand off to cards the other also reaches, so
    "the owning door" is not a single value, and a function returning the first
    match would be picking by sort order.

    Publishing a member has to refresh every bundle that merged it, or the
    door keeps serving that member's old flow; this is how the publish path
    finds them.
    """
    bid = (bot_id or "").strip()
    if not bid:
        return []
    _mod = _db()
    with _mod.engine.connect() as conn:
        if not _column_exists(conn, "prompt_versions", "compiled"):
            return []
        rows = _mod._rows(
            conn.execute(
                text(
                    """
                    SELECT bot_id
                      FROM prompt_versions
                     WHERE status = 'published' AND tenant_id = :t
                       AND compiled -> 'entry_by_specialist' ? :b
                    """
                ),
                {"t": _mod._tenant(), "b": bid},
            )
        )
    return sorted(str(r["bot_id"]) for r in rows if str(r["bot_id"]) != bid)

def recompile_published_bundle(bot_id: str) -> dict[str, Any]:
    """Fill in `prompt_versions.compiled` for a card that is already live.

    `compiled` is NULL on every published row, because the column landed after
    they were published and only `publish_prompt_version` writes it. While it is
    NULL, `deployment._dual_compute_parity` returns at its first guard: no parity
    is logged, and `fleet_enabled()` is never even reached. So the compiled
    artefact cannot be trusted before it is switched on, because nothing has
    ever compared it to the live path.

    **This is not a republish, and the difference matters.**
    `publish_prompt_version` archives the live row, inserts a new
    `bot_deployments` row, re-snapshots frozen connector tools, re-applies the
    tuning overlay and rewrites the card through `model_dump`. Running it on an
    unchanged card is therefore a real production swap of the deployment every
    inbound call resolves, and it would rewrite the card in the same motion.
    This writes two columns and changes no row's identity: `compiled` on the
    published version, and `bundle_hash` on the deployment that is already
    active. Reversal is `UPDATE prompt_versions SET compiled = NULL`.

    Compile members before the door: `_fleet_members` reads each member's
    *published* row, so a door compiled first would merge whatever those rows
    held at the time.
    """
    _mod = _db()
    engine = _mod.engine
    _one = _mod._one
    _jsonb = _mod._jsonb
    _tenant = _mod._tenant

    with engine.connect() as conn:
        live = _one(
            conn.execute(
                text(
                    "SELECT id FROM prompt_versions "
                    " WHERE bot_id = :b AND status = 'published' AND tenant_id = :t "
                    " LIMIT 1"
                ),
                {"b": bot_id, "t": _tenant()},
            )
        )
    if live is None:
        raise KeyError(f"no_published_version: {bot_id}")

    # Named explicitly. `compile_agent_studio_card(bot_id)` with no version
    # resolves the *draft* when there is one -- correct for a preview, wrong
    # here: it would stamp the column the runtime reads with an artefact
    # compiled from a card nobody has published.
    report = compile_agent_studio_card(bot_id, prompt_version_id=str(live["id"]))
    bundle = report.get("bundle") or {}
    bundle_hash = str(bundle.get("bundle_hash") or "")
    version_id = str(bundle.get("prompt_version_id") or "")
    if not bundle_hash or not version_id:
        raise ValueError(f"no compiled bundle for {bot_id}")

    with engine.begin() as conn:
        if not _column_exists(conn, "prompt_versions", "compiled"):
            raise RuntimeError("prompt_versions.compiled does not exist")
        row = _one(
            conn.execute(
                text(
                    "SELECT id, status FROM prompt_versions "
                    "WHERE id = :id AND tenant_id = :t"
                ),
                {"id": version_id, "t": _tenant()},
            )
        )
        if row is None:
            raise KeyError(f"prompt_version_not_found: {version_id}")
        if row["status"] != "published":
            # Only the live row. A draft's bundle is what the preview is for,
            # and stamping one here would put an artefact nothing serves into
            # the column the runtime reads.
            raise ValueError(f"prompt_version_not_published: {version_id}")

        conn.execute(
            text(
                "UPDATE prompt_versions SET compiled = CAST(:c AS jsonb), "
                "updated_at = now() WHERE id = :id AND tenant_id = :t"
            ),
            {"c": _jsonb(bundle), "id": version_id, "t": _tenant()},
        )
        deployments = 0
        if _column_exists(conn, "bot_deployments", "bundle_hash"):
            # No tenant predicate here, and it is not an omission:
            # `bot_deployments` has no `tenant_id` column -- it reaches its
            # tenant through `bot_id`, which is how `rls.plan` derives its
            # policy at depth 1. `version_id` was matched against a
            # tenant-scoped `prompt_versions` row three statements above, so
            # the row this updates is already known to be ours.
            deployments = conn.execute(
                text(
                    "UPDATE bot_deployments SET bundle_hash = :h "
                    " WHERE prompt_version_id = :pv AND status = 'active'"
                ),
                {"h": bundle_hash, "pv": version_id},
            ).rowcount

    return {
        "botId": bot_id,
        "promptVersionId": version_id,
        "bundleHash": bundle_hash,
        "deploymentsStamped": int(deployments or 0),
    }

def _fleet_members(card_raw: Any) -> list[dict[str, Any]]:
    """The published card and flow of every agent this one hands off to.

    The fleet is already declared — it is the card's handoff allowlist — so an
    author never types a namespace and there is no second place for the roster
    to drift from. A target with no published version is skipped rather than
    guessed at; it simply contributes no subgraph, and the hop into it stays a
    ledger row.
    """
    from agent_core.cards import routing

    out: list[dict[str, Any]] = []
    for target in sorted(set(routing.handoff_targets(card_raw))):
        try:
            published = get_published_prompt_version(target)
        except Exception:
            logger.debug("fleet member lookup failed for %s", target, exc_info=True)
            continue
        if not published:
            continue
        out.append(
            {
                "bot_id": target,
                "prompt_version_id": str(published.get("id") or ""),
                "card": published.get("agentCard") or {},
                "flow": published.get("flow") if isinstance(published.get("flow"), dict) else {},
            }
        )
    return out

def get_effective_contract(bot_id: str) -> dict[str, Any]:
    """Published artefact if persisted, else a dry-run compile of the draft."""
    published = get_published_prompt_version(bot_id)
    stored = (published or {}).get("compiled") if isinstance(published, dict) else None
    if isinstance(stored, dict) and stored.get("bundle_hash"):
        return {
            "source": "published",
            "botId": bot_id,
            "promptVersionId": published.get("id") if published else None,
            "compiled": stored,
        }
    dumped = compile_agent_studio_card(bot_id)
    compiled = dumped.get("bundle") if isinstance(dumped.get("bundle"), dict) else {}
    if not compiled.get("bundle_hash"):
        raise KeyError("effective_contract_unavailable")
    return {
        "source": "preview",
        "botId": bot_id,
        "promptVersionId": compiled.get("prompt_version_id"),
        "compiled": compiled,
        "gates": dumped.get("gates") or [],
    }
