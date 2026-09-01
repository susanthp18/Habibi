"""Progressive disclosure — descriptions always, body on activation.

The system prefix is stable (skill slugs in sorted order) so the voice
prefix cache survives a 30-turn call. The active body rides a developer
block and is dropped on switch. References never grant tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from agent_core.skills.intersect import tools_after_references
from agent_core.skills.pack import SkillPack

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Never import this at runtime. ``agent_core.cards`` and
    # ``agent_core.skills`` are mutually dependent, and this module is the one
    # voice/bot.py touches first; a module-level import here closes the cycle
    # and every call dies assembling its prompt. ``from __future__ import
    # annotations`` keeps the reference below a string.
    from agent_core.cards.schema import AgentCard

logger = logging.getLogger(__name__)

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
        # Fail closed. The on-disk packs below are the *unsigned* platform
        # defaults, so falling through to them on a DB fault silently reinstates
        # tool grants this tenant removed in their signed pack — and
        # ``intersect.effective_tools`` gates writes on pack contents, so the
        # bot would regain e.g. create_promise_to_pay for the duration of the
        # blip. No packs means the gate denies, which is the safe direction.
        logger.error("skill packs unavailable — failing closed · slugs=%s", slugs, exc_info=True)
        return []
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


@dataclass(frozen=True)
class SkillPrompt:
    """The Skill text that belongs in one turn's prompt. No tool facts."""

    #: Skill descriptions for the stable system prefix. Empty when the mouth
    #: has no usable card or no attached packs.
    prefix: str
    #: The active Skill's body, as a developer message, or None.
    body_message: dict[str, str] | None


@dataclass(frozen=True)
class ToolState:
    """What one mouth turn may execute, and what it is offered. No prompt text."""

    allowed: frozenset[str] | None
    offered: tuple[str, ...] | None

    @property
    def has_grant(self) -> bool:
        """Whether a tool grant could be derived for this mouth at all.

        The single place the ``None`` sentinel is interpreted. ``None`` means
        the mouth has no usable agent card, so no grant exists — and today
        every caller reads that as *no filtering*, falling back to a default
        tool list. That is the fail-open ADR-0002 decides to retire; the
        decision is accepted but not yet implemented, and doing so is the whole
        of the deny-all ticket, which is deliberately the last change in this
        sequence and lands alone.

        Four callers each used to spell this ``allowed is not None`` and each
        had to know what None meant. Asking here is what lets that ticket
        change one branch instead of four call sites.

        Not named ``is_gated``: CONTEXT.md reserves *Gate* for a publish-time
        check, and this is a per-turn question about a *Tool Grant*.
        """
        return self.allowed is not None


@dataclass(frozen=True)
class MouthTurn:
    """A mouth's card, its attached skill packs, and which skill is active.

    The shared root of the two questions that used to be answered together:
    ``prompt()`` for the text, ``tools()`` for the grant. Pack resolution is
    the expensive half and happens once per ``MouthTurn``, so asking both
    questions of one costs no more than asking either. A caller that resolves
    twice still pays twice — the sandbox does, once for the prefix and again
    for the body after intent is known, which its own migration ticket closes.

    ``card is None`` covers both "no card was authored" and "the card would not
    parse". Neither can be filtered against, so both yield an empty prompt and
    no grant. They are also indistinguishable in ``packs``: pack resolution
    parses the same card, so an unparseable one resolves to no packs by the
    same failure — verified against the pre-split implementation rather than
    assumed, because the reverse looked plausible and is not true.
    """

    card: "AgentCard | None"
    packs: tuple[SkillPack, ...]
    active_slug: str | None

    def prompt(self) -> SkillPrompt:
        """The Skill prefix and active body for this turn."""
        if self.card is None or not self.packs:
            return SkillPrompt(prefix="", body_message=None)
        body = None
        if self.active_slug:
            pack = next((p for p in self.packs if p.slug == self.active_slug), None)
            if pack:
                body = body_developer_message(pack)
        return SkillPrompt(prefix=description_block(list(self.packs)), body_message=body)

    def tools(self, *, catalog_names: set[str] | None = None) -> ToolState:
        """What this turn may execute, and what to put in front of the model."""
        if self.card is None:
            return ToolState(allowed=None, offered=None)

        from agent_core.skills.intersect import effective_tools, offered_tools
        from agent_core.tools.catalog import CATALOG

        names = catalog_names or set(CATALOG.specs)
        attached = list(self.packs) if self.packs else None
        return ToolState(
            allowed=frozenset(
                effective_tools(self.card, catalog_names=names, attached_skills=attached)
            ),
            offered=tuple(
                offered_tools(
                    self.card,
                    catalog_names=names,
                    attached_skills=attached,
                    active_slug=self.active_slug,
                )
            ),
        )


def resolve_mouth(
    card_raw: Any,
    *,
    intent: str | None = None,
    active_slug: str | None = None,
) -> MouthTurn:
    """Resolve a mouth's card, packs and active skill once, for both questions."""
    from agent_core.cards.schema import is_authored, parse_card

    if not is_authored(card_raw):
        return MouthTurn(card=None, packs=(), active_slug=None)
    packs = packs_from_card(card_raw)
    try:
        card = parse_card(card_raw)
    except Exception:
        # Packs resolved, card did not parse. Reported as ungated, same as an
        # absent card: there is nothing to filter against either way.
        return MouthTurn(card=None, packs=tuple(packs), active_slug=None)
    resolved = active_slug
    if not resolved:
        hit = resolve_intent_skill(intent, packs)
        resolved = hit.slug if hit else None
    return MouthTurn(card=card, packs=tuple(packs), active_slug=resolved)


def mouth_turn_state(
    card_raw: Any,
    *,
    intent: str | None = None,
    active_slug: str | None = None,
    catalog_names: set[str] | None = None,
) -> dict[str, Any]:
    """Both halves in one untyped dict — the shape callers used before the split.

    Kept only for the tests that pin fail-closed pack resolution through it. No
    runtime calls this; they ask ``resolve_mouth`` for the half they need.
    Retired with the other legacy tool formulas.
    """
    mouth = resolve_mouth(card_raw, intent=intent, active_slug=active_slug)
    prompt = mouth.prompt()
    tools = mouth.tools(catalog_names=catalog_names)
    return {
        "card": mouth.card,
        "packs": list(mouth.packs),
        "allowed": set(tools.allowed) if tools.allowed is not None else None,
        "offered": list(tools.offered) if tools.offered is not None else None,
        "prefix": prompt.prefix,
        "active_slug": mouth.active_slug,
        "body_message": prompt.body_message,
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
