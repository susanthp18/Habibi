"""Deterministic wrapper around ``compile_card``.

Does not replace the publish compiler. Builds the persisted artefact from
the same inputs the live grant uses, so a one-member fleet is byte-identical
to today's prompt, tools, flow and attribution.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from agent_core.cards.compile import CompileReport, node_offers
from agent_core.cards.schema import AgentCard, is_authored, parse_card
from agent_core.fleet.schema import (
    ChannelGrant,
    CompiledBundle,
    CompiledHashes,
    FrozenConnector,
    NodeOffer,
    PinnedSkill,
)
from agent_core.skills.pack import SkillPack
from agent_core.tools.grant import TEXT, VOICE, ToolGrant

logger = logging.getLogger(__name__)


def canonical_dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical_dumps(obj).encode("utf-8")).hexdigest()


def bundle_hash_valid(bundle: CompiledBundle) -> bool:
    payload = bundle.model_dump(mode="json")
    claimed = str(payload.pop("bundle_hash", "") or "")
    return bool(claimed) and claimed == digest(payload)


def compile_bundle(
    *,
    report: CompileReport,
    prompt: str = "",
    persona: dict[str, Any] | None = None,
    guardrails: dict[str, Any] | None = None,
    flow: Any = None,
    prompt_version_id: str | None = None,
    attached_skills: list[SkillPack] | None = None,
    source_ids: dict[str, str] | None = None,
) -> CompiledBundle:
    """Fold a ``CompileReport`` plus mouth columns into one hashed artefact."""
    card_dump = report.card if isinstance(report.card, dict) else {}
    persona = persona if isinstance(persona, dict) else {}
    guardrails = guardrails if isinstance(guardrails, dict) else {}
    flow_obj = flow if isinstance(flow, dict) else {}
    packs = tuple(attached_skills or ())
    card: AgentCard | None = None
    if is_authored(card_dump):
        try:
            card = parse_card(card_dump)
        except Exception:
            card = None

    skills = [
        PinnedSkill(
            skill_id=p.slug,
            version=p.version,
            pin="exact",
            content_hash=p.content_hash,
            signed=bool(p.signed),
            mouth=list(p.mouth or []),
        )
        for p in packs
    ]
    connectors: list[FrozenConnector] = []
    if card is not None:
        for conn in card.connectors:
            dumped = conn.model_dump(mode="json")
            registry: dict[str, Any] = {}
            try:
                from agent_core.connectors.persist import get_connector

                registry = get_connector(conn.connector_id) or {}
            except Exception:
                logger.exception(
                    "connector registry unavailable while freezing %s",
                    conn.connector_id,
                )
            prefixes = list(conn.allow_prefixes or registry.get("allowPrefixes") or [])
            frozen_names = sorted(
                name
                for name in report.effective_tools
                if name.startswith("ext.")
                and (not prefixes or any(name.startswith(prefix) for prefix in prefixes))
            )
            registry_contract = {
                key: registry.get(key)
                for key in (
                    "id",
                    "slug",
                    "kind",
                    "url",
                    "allowPrefixes",
                    "dataClass",
                    "toolsCache",
                    "status",
                )
            }
            connectors.append(
                FrozenConnector(
                    connector_id=conn.connector_id,
                    allow_prefixes=prefixes,
                    tool_names=frozen_names,
                    digest=digest(
                        {"binding": dumped, "registry": registry_contract}
                    ),
                    voice_supported=False,
                )
            )

    frozen_connector_tools = sorted(
        {name for connector in connectors for name in connector.tool_names}
    )
    grants: list[ChannelGrant] = []
    for channel in (VOICE, TEXT):
        grant = ToolGrant.for_card(
            card,
            packs,
            channel=channel,
            frozen_connector_tools=frozen_connector_tools,
        )
        grants.append(
            ChannelGrant(
                channel=channel,
                allowed=sorted(grant.allowed),
                offered=list(grant.offer()),
            )
        )

    # The same intersection G16 reports, from the same helper, so the gate that
    # certified the publish and the artefact the runtime reads cannot disagree
    # about what a step can call. Voice, because a flow node is a voice node.
    voice_grant = next(
        (set(g.allowed) for g in grants if g.channel == VOICE), set(report.effective_tools)
    )
    offers = [NodeOffer(**row) for row in node_offers(flow_obj, voice_grant)]

    human_gates = []
    if card is not None:
        human_gates = [g.model_dump(mode="json") for g in card.human_gates]

    hashes = CompiledHashes(
        prompt=digest(prompt or ""),
        persona=digest(persona),
        guardrails=digest(guardrails),
        flow=digest(flow_obj),
        card=digest(card_dump),
    )
    draft = CompiledBundle(
        bot_id=report.bot_id,
        prompt_version_id=prompt_version_id,
        source_ids=dict(source_ids or {}),
        skills=skills,
        connectors=connectors,
        grants=grants,
        node_offers=offers,
        human_gates=human_gates,
        hashes=hashes,
        gates=[g.model_dump(mode="json") for g in report.gates],
        prompt=prompt or "",
        persona=persona,
        guardrails=guardrails,
        flow=flow_obj,
        agent_card=card_dump,
        bundle_hash="",
    )
    hashed = draft.model_dump(mode="json")
    hashed.pop("bundle_hash", None)
    return draft.model_copy(update={"bundle_hash": digest(hashed)})


def parity_report(
    *,
    live_prompt: str,
    live_flow: dict[str, Any] | None,
    live_tools: list[str] | set[str],
    bundle: CompiledBundle,
    live_persona: dict[str, Any] | None = None,
    live_guardrails: dict[str, Any] | None = None,
    channel: str = "voice",
    bot_id: str | None = None,
    prompt_version_id: str | None = None,
) -> dict[str, Any]:
    """Compare a live mouth against the persisted bundle. No traffic change."""
    grant = bundle.grant_for(channel)
    live_set = set(live_tools)
    bundle_set = set(grant.allowed) if grant else set()
    mismatches: list[str] = []
    if (live_prompt or "") != (bundle.prompt or ""):
        mismatches.append("prompt")
    if digest(live_persona or {}) != bundle.hashes.persona:
        mismatches.append("persona")
    if digest(live_guardrails or {}) != bundle.hashes.guardrails:
        mismatches.append("guardrails")
    if digest(live_flow or {}) != bundle.hashes.flow:
        mismatches.append("flow")
    if live_set != bundle_set:
        mismatches.append("tools")
    if bot_id is not None and bot_id != bundle.bot_id:
        mismatches.append("bot_id")
    if (
        prompt_version_id is not None
        and prompt_version_id != bundle.prompt_version_id
    ):
        mismatches.append("prompt_version_id")
    return {
        "ok": not mismatches,
        "mismatches": mismatches,
        "bundle_hash": bundle.bundle_hash,
        "live_only": sorted(live_set - bundle_set),
        "bundle_only": sorted(bundle_set - live_set),
    }
