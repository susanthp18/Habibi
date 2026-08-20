"""Effective / offered tool sets.

Skill-gated writes require an attached signed skill that lists them.
Reads, locked engines, and platform tools stay on the card's include set.

When ``card.skills`` is empty the mouth is legacy: no gated filter, so
unmigrated cards keep PTP.
"""

from __future__ import annotations

from typing import Iterable

from agent_core.cards.schema import LOCKED_MOUTH_TOOLS, AgentCard
from agent_core.skills.pack import SkillPack, approx_tokens

# Writes (and late-call offer tools) that only exist while a signed skill
# listing them is attached. Reads and locked engines stay on the idle turn.
SKILL_GATED_TOOLS: frozenset[str] = frozenset(
    {
        "create_promise_to_pay",
        "flag_dispute",
        "capture_lead",
        "request_documents",
        "apply_goodwill",
        "check_product_eligibility",
        "decline_offer",
    }
)

# Always offered when the card has skills; do not count against max_voice_tools.
PLATFORM_SKILL_TOOLS: frozenset[str] = frozenset({"load_skill", "run_skill_script"})


def _locked_mouth(card: AgentCard, catalog_names: set[str]) -> set[str]:
    return {n for n in card.tools.locked if n in LOCKED_MOUTH_TOOLS and n in catalog_names}


def union_skill_tools(skills: Iterable[SkillPack]) -> set[str]:
    names: set[str] = set()
    for skill in skills:
        names.update(skill.allowed_tools)
    return names


def _apply_channel(names: set[str], channel_tools: set[str] | None, extras: set[str]) -> set[str]:
    if channel_tools is None:
        return names
    return (names & channel_tools) | extras


def _order(card: AgentCard, names: set[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for name in [*card.tools.locked, *sorted(PLATFORM_SKILL_TOOLS), *card.tools.include]:
        if name in names and name not in seen:
            seen.add(name)
            ordered.append(name)
    for name in sorted(names):
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def effective_tools(
    card: AgentCard,
    *,
    catalog_names: set[str],
    channel_tools: set[str] | None = None,
    attached_skills: list[SkillPack] | None = None,
) -> list[str]:
    """Card include ∩ catalog, plus locked mouth tools.

    When the card lists skills, skill-gated names survive only if they appear
    on an attached pack. Detaching ``ptp-negotiate`` drops ``create_promise_to_pay``
    even if it remains on ``tools.include``.
    """
    locked_mouth = _locked_mouth(card, catalog_names)
    platform = PLATFORM_SKILL_TOOLS & catalog_names
    names = (set(card.tools.include) | locked_mouth | platform) & catalog_names
    apply_skills = bool(card.skills) or attached_skills is not None
    if apply_skills and (card.skills or attached_skills is not None):
        # Empty attached list + non-empty card.skills = fail closed on gated writes.
        packs = attached_skills if attached_skills is not None else []
        if card.skills and attached_skills is None:
            packs = []
        gated_ok = union_skill_tools(packs) & SKILL_GATED_TOOLS
        names = (names - SKILL_GATED_TOOLS) | (names & gated_ok) | locked_mouth | platform
        names &= catalog_names
    names = _apply_channel(names, channel_tools, locked_mouth | platform)
    if card.connectors:
        try:
            from agent_core.platform_flags import mcp_client_enabled
            from agent_core.connectors.persist import bound_tool_names

            if mcp_client_enabled():
                names |= set(bound_tool_names([c.model_dump() for c in card.connectors]))
        except Exception:
            pass
    return _order(card, names)


def idle_offered_tools(
    card: AgentCard,
    *,
    catalog_names: set[str],
    attached_skills: list[SkillPack] | None = None,
    channel_tools: set[str] | None = None,
) -> list[str]:
    """Tools in the OpenAI/Flows list when no skill body is active."""
    full = effective_tools(
        card,
        catalog_names=catalog_names,
        channel_tools=channel_tools,
        attached_skills=attached_skills,
    )
    if not (card.skills or attached_skills):
        return [n for n in full if not n.startswith("ext.")]
    allowed = (set(full) - SKILL_GATED_TOOLS) | (PLATFORM_SKILL_TOOLS & catalog_names) | _locked_mouth(
        card, catalog_names
    )
    return [n for n in full if n in allowed and not n.startswith("ext.")]


def offered_tools(
    card: AgentCard,
    *,
    catalog_names: set[str],
    attached_skills: list[SkillPack] | None = None,
    active_slug: str | None = None,
    channel_tools: set[str] | None = None,
) -> list[str]:
    idle = idle_offered_tools(
        card,
        catalog_names=catalog_names,
        attached_skills=attached_skills,
        channel_tools=channel_tools,
    )
    if not active_slug or not attached_skills:
        return idle
    active = next((s for s in attached_skills if s.slug == active_slug), None)
    if active is None:
        return idle
    allowed = set(
        effective_tools(
            card,
            catalog_names=catalog_names,
            channel_tools=channel_tools,
            attached_skills=attached_skills,
        )
    )
    extra = [n for n in active.allowed_tools if n in allowed and n not in idle]
    return idle + extra


def description_prefix_tokens(skills: Iterable[SkillPack]) -> int:
    return sum(approx_tokens(s.description) for s in skills)


def tools_after_references(allowed_tools: Iterable[str], references: dict[str, str] | None) -> set[str]:
    """References are prompt text. They cannot grant tools. Fail closed."""
    _ = references
    return set(allowed_tools)
