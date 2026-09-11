"""First-party skill attachments per agent card."""

from __future__ import annotations

from agent_core.cards.schema import CardSkillRef
from agent_core.skills.pack import SkillPack, iter_first_party_packs, pack_for_slug

FIRST_PARTY_SKILL_SLUGS: tuple[str, ...] = (
    "verify-and-disclose",
    "ptp-negotiate",
    "hardship-intake",
    "dispute-capture",
    "doc-fulfil",
    "broken-ptp-chase",
    "upsell-pitch",
    "insurance-lapse",
    "qa-examiner",
    "floor-coach",
    "supervisor-brief",
)

COLLECTIONS_SKILLS: tuple[str, ...] = (
    "verify-and-disclose",
    "ptp-negotiate",
    "hardship-intake",
    "dispute-capture",
    "doc-fulfil",
    "broken-ptp-chase",
    "upsell-pitch",
    "floor-coach",
)

INTAKE_SKILLS: tuple[str, ...] = ("verify-and-disclose",)
INSURANCE_SKILLS: tuple[str, ...] = ("verify-and-disclose", "insurance-lapse", "doc-fulfil")
SUPERVISOR_SKILLS: tuple[str, ...] = ("supervisor-brief", "qa-examiner")

CARD_SKILLS: dict[str, tuple[str, ...]] = {
    "kaia-v2-4": COLLECTIONS_SKILLS,
    "intake-v1": INTAKE_SKILLS,
    "insurance-v1": INSURANCE_SKILLS,
    "supervisor-brief": SUPERVISOR_SKILLS,
}


def skill_refs(*slugs: str) -> list[CardSkillRef]:
    """Exact pins on the version the platform ships.

    `version="1"` for every slug pinned the original seed row forever: the
    boot sync stored ptp-negotiate 1.5.0 beside it, honoured the pin, and the
    cards kept running the pack from the first deploy -- no new talk track,
    no `intents`, ever. A first-party card follows the platform pack."""
    out: list[CardSkillRef] = []
    for slug in slugs:
        try:
            version = pack_for_slug(slug).version
        except KeyError:
            version = "1"
        version = "1" if version in {"1", "1.0.0"} else version
        out.append(CardSkillRef(skill_id=slug, version=version, pin="exact"))
    return out


def packs_for_slugs(slugs: tuple[str, ...] | list[str]) -> list[SkillPack]:
    return [pack_for_slug(slug) for slug in slugs]


def all_first_party_packs() -> list[SkillPack]:
    packs = iter_first_party_packs()
    by_slug = {p.slug: p for p in packs}
    missing = [s for s in FIRST_PARTY_SKILL_SLUGS if s not in by_slug]
    if missing:
        raise FileNotFoundError(f"missing_first_party_skills:{missing}")
    return [by_slug[s] for s in FIRST_PARTY_SKILL_SLUGS]
