"""Clone templates for tenant-authored cards. Not first-party mouths.

Collections / Lapse / Hardship / Clerk are clone *recipes*. Cloning creates a
new ``bots`` row. Lapse Specialist is never added to FIRST_PARTY_BOT_IDS.
"""

from __future__ import annotations

from typing import Any

from agent_core.cards.defaults import (
    COLLECTIONS_BOT_ID,
    INSURANCE_BOT_ID,
    SUPERVISOR_BOT_ID,
    card_dump,
)
from agent_core.cards.schema import LOCKED_POLICY_ENGINES

_LOCKED = list(LOCKED_POLICY_ENGINES)

_LAPSE_TOOLS = [
    "verify_identity",
    "get_customer_context",
    "request_documents",
    "capture_lead",
    "escalate_to_human",
    "handoff_to_agent",
    "evaluate_authority",
    "recommend_next_offer",
]


def templates() -> list[dict[str, Any]]:
    return [
        {
            "id": "collections",
            "label": "Collections",
            "sourceBotId": COLLECTIONS_BOT_ID,
            "purpose": "Recover overdue balances.",
        },
        {
            "id": "lapse",
            "label": "Lapse Specialist",
            "sourceBotId": INSURANCE_BOT_ID,
            "purpose": "Premium lapse + EMI bounce. Reco may pitch a rider only when allowed.",
        },
        {
            "id": "hardship",
            "label": "Hardship",
            "sourceBotId": COLLECTIONS_BOT_ID,
            "purpose": "Hold treatment, capture hardship, never unbind DND.",
        },
        {
            "id": "clerk",
            "label": "Clerk",
            "sourceBotId": SUPERVISOR_BOT_ID,
            "purpose": "Internal chase agent. Speaks templates, not dialogue.",
        },
    ]


def _resolve_skill_tools(slugs: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """(resolvable slugs, slug → allowed_tools) for the packs that actually exist.

    Both halves are needed by ``_reconcile``: a slug the catalog cannot resolve
    fails G9 as ``unresolved``, and a resolvable pack whose tools are missing
    from ``tools.include`` fails G9 as ``tools_not_on_card``.
    """
    resolved: list[str] = []
    tools: dict[str, list[str]] = {}
    for slug in slugs:
        pack = None
        try:
            from agent_core.skills.persist import packs_for_slugs

            pack = next(iter(packs_for_slugs([slug])), None)
        except Exception:
            pack = None
        if pack is None:
            try:
                from agent_core.skills.pack import pack_for_slug

                pack = pack_for_slug(slug)
            except KeyError:
                pack = None
        if pack is None:
            continue
        resolved.append(slug)
        tools[slug] = list(pack.allowed_tools)
    return resolved, tools


def _reconcile(raw: dict[str, Any]) -> dict[str, Any]:
    """Drop unresolvable skill pins and grant the tools the kept skills need.

    A template that pins a skill the catalog does not have, or that grants fewer
    tools than its own skills declare, produces a clone that cannot publish:
    G9 is fail-closed on both. Deriving the include list from the attached packs
    keeps template edits and skill edits from drifting apart, instead of
    restating each skill's tools by hand in ``_LAPSE_TOOLS``.
    """
    from agent_core.tools.catalog import CATALOG

    catalog = set(CATALOG.specs)
    refs = [s for s in (raw.get("skills") or []) if isinstance(s, dict) and s.get("skill_id")]
    resolved, per_skill = _resolve_skill_tools([str(s["skill_id"]) for s in refs])
    raw["skills"] = [s for s in refs if str(s["skill_id"]) in resolved]

    tools = dict(raw.get("tools") or {})
    include = list(tools.get("include") or [])
    seen = set(include)
    for slug in resolved:
        for name in per_skill.get(slug, []):
            # Only catalog tools: a pack may name a platform tool (load_skill)
            # that G9 scopes separately and that must not enter `include`.
            if name in catalog and name not in seen:
                seen.add(name)
                include.append(name)
    tools["include"] = include
    raw["tools"] = tools
    return raw


def template_card(template_id: str) -> dict[str, Any]:
    """Card JSON to stamp onto a clone. Identity.bot_id is rewritten by clone."""
    tid = (template_id or "").strip().lower()
    if tid == "lapse":
        raw = card_dump(INSURANCE_BOT_ID)
        ident = dict(raw.get("identity") or {})
        ident["display_name"] = "Lapse Specialist"
        ident["slug"] = "lapse-specialist"
        ident["purpose"] = "Premium lapse specialist. Handoff allowlist is Collections + human."
        raw["identity"] = ident
        tools = dict(raw.get("tools") or {})
        tools["include"] = list(_LAPSE_TOOLS)
        tools["locked"] = list(_LOCKED)
        raw["tools"] = tools
        raw["handoffs"] = [
            {"to_bot_id": COLLECTIONS_BOT_ID, "when": "emi bounce / collections intent", "payload_schema": {}},
        ]
        skills = list(raw.get("skills") or [])
        # Pinned only when the tenant actually has it — cloning the
        # broken-ptp-chase pack under this slug is the documented way to create
        # it, and until then the pin made every Lapse clone unpublishable.
        if not any(s.get("skill_id") == "premium-lapse-chase" for s in skills if isinstance(s, dict)):
            skills.append({"skill_id": "premium-lapse-chase", "version": "1", "pin": "exact"})
        raw["skills"] = skills
        return _reconcile(raw)
    if tid == "hardship":
        raw = card_dump(COLLECTIONS_BOT_ID)
        ident = dict(raw.get("identity") or {})
        ident["display_name"] = "Hardship"
        ident["slug"] = "hardship"
        ident["purpose"] = "Hardship intake. Treatment wait on DND/hardship routing."
        raw["identity"] = ident
        return _reconcile(raw)
    if tid == "clerk":
        raw = card_dump(SUPERVISOR_BOT_ID)
        ident = dict(raw.get("identity") or {})
        ident["display_name"] = "Clerk"
        ident["slug"] = "clerk"
        ident["purpose"] = "Internal chase. Templates only."
        ident["channels"] = ["internal"]
        raw["identity"] = ident
        return _reconcile(raw)
    raw = card_dump(COLLECTIONS_BOT_ID)
    ident = dict(raw.get("identity") or {})
    ident["display_name"] = "Collections"
    ident["slug"] = "collections"
    raw["identity"] = ident
    return _reconcile(raw)
