"""Progressive disclosure — descriptions always, body on activation.

The system prefix is stable (skill slugs in sorted order) so the voice
prefix cache survives a 30-turn call. The active body rides a developer
block and is dropped on switch. References never grant tools.
"""

from __future__ import annotations

from typing import Any

from agent_core.skills.intersect import tools_after_references
from agent_core.skills.pack import SkillPack

SKILL_BODY_PREFIX = "ACTIVE SKILL"
INTENT_TO_SKILL: dict[str, str] = {
    "hardship": "hardship-intake",
    "dispute": "dispute-capture",
    "payment_intent": "ptp-negotiate",
    "waiver_request": "ptp-negotiate",
    "upsell_opportunity": "upsell-pitch",
    "product_faq": "insurance-lapse",
    "balance_query": "verify-and-disclose",
}


def description_block(skills: list[SkillPack]) -> str:
    if not skills:
        return ""
    lines = ["## Skills", "Call load_skill with a slug to load that skill's instructions. One body at a time."]
    for skill in sorted(skills, key=lambda s: s.slug):
        lines.append(f"- {skill.slug}: {skill.description}")
    return "\n".join(lines)


def body_developer_message(pack: SkillPack, *, include_references: bool = False) -> dict[str, str]:
    parts = [f"{SKILL_BODY_PREFIX} ({pack.slug})", pack.body.strip()]
    if include_references and pack.references:
        for name in sorted(pack.references):
            parts.append(f"\n### {name}\n{pack.references[name].strip()}")
    return {"role": "developer", "content": "\n\n".join(parts)}


def packs_from_card(card_raw: Any) -> list[SkillPack]:
    """Signed DB packs when present; on-disk first-party packs otherwise.

    Empty first-party cards get the default attachment list so a stale
    published prompt cannot silently run with no skills.
    """
    from agent_core.cards.schema import is_authored, parse_card
    from agent_core.skills.defaults import CARD_SKILLS
    from agent_core.skills.pack import pack_for_slug

    if not is_authored(card_raw):
        return []
    try:
        card = parse_card(card_raw)
    except Exception:
        return []
    slugs = [ref.skill_id for ref in card.skills]
    if not slugs:
        slugs = list(CARD_SKILLS.get(card.identity.bot_id, ()))
    if not slugs:
        return []
    try:
        from agent_core.skills.persist import packs_for_slugs

        db_packs = packs_for_slugs(slugs)
        if db_packs:
            return db_packs
    except Exception:
        pass
    packs: list[SkillPack] = []
    for slug in slugs:
        try:
            packs.append(pack_for_slug(slug))
        except KeyError:
            continue
    return packs


def resolve_intent_skill(intent: str | None, attached: list[SkillPack]) -> SkillPack | None:
    slug = INTENT_TO_SKILL.get((intent or "").strip())
    if not slug:
        return None
    return next((s for s in attached if s.slug == slug), None)


def mouth_turn_state(
    card_raw: Any,
    *,
    intent: str | None = None,
    active_slug: str | None = None,
    catalog_names: set[str] | None = None,
) -> dict[str, Any]:
    """Allowed tools, offered tools, prefix, and active body for one mouth turn."""
    from agent_core.cards.schema import is_authored, parse_card
    from agent_core.skills.intersect import effective_tools, offered_tools
    from agent_core.tools.catalog import CATALOG

    names = catalog_names or set(CATALOG.specs)
    packs = packs_from_card(card_raw)
    if not is_authored(card_raw):
        return {
            "card": None,
            "packs": [],
            "allowed": None,
            "offered": None,
            "prefix": "",
            "active_slug": None,
            "body_message": None,
        }
    try:
        card = parse_card(card_raw)
    except Exception:
        return {
            "card": None,
            "packs": packs,
            "allowed": None,
            "offered": None,
            "prefix": "",
            "active_slug": None,
            "body_message": None,
        }
    use_skills = bool(packs)
    attached = packs if use_skills else None
    allowed = set(effective_tools(card, catalog_names=names, attached_skills=attached))
    resolved = active_slug
    if not resolved:
        hit = resolve_intent_skill(intent, packs)
        resolved = hit.slug if hit else None
    offered = offered_tools(
        card,
        catalog_names=names,
        attached_skills=attached,
        active_slug=resolved,
    )
    body = None
    if resolved:
        pack = next((p for p in packs if p.slug == resolved), None)
        if pack:
            body = body_developer_message(pack)
    return {
        "card": card,
        "packs": packs,
        "allowed": allowed,
        "offered": offered,
        "prefix": description_block(packs) if use_skills else "",
        "active_slug": resolved,
        "body_message": body,
    }


def load_skill(
    slug: str,
    attached: list[SkillPack],
    *,
    include_references: bool = False,
) -> dict[str, Any]:
    pack = next((s for s in attached if s.slug == slug), None)
    if pack is None:
        return {"ok": False, "error": "skill_not_attached", "slug": slug}
    effective = tools_after_references(pack.allowed_tools, pack.references if include_references else {})
    return {
        "ok": True,
        "slug": pack.slug,
        "allowed_tools": sorted(effective),
        "message": body_developer_message(pack, include_references=include_references),
    }
