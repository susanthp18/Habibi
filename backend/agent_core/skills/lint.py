"""Skill pack linter — form fields, not free-text tool names."""

from __future__ import annotations

from typing import Any

from agent_core.skills.pack import SkillPack, approx_tokens

DESCRIPTION_TOKEN_CAP = 120
CATALOG_PREFIX_TOKEN_CAP = 800


def lint_pack(pack: SkillPack, *, catalog_names: set[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not pack.slug:
        issues.append({"code": "missing_name", "msg": "frontmatter.name is required"})
    if not pack.description:
        issues.append({"code": "missing_description", "msg": "description is the prefix the model always sees"})
    tokens = approx_tokens(pack.description)
    if tokens > DESCRIPTION_TOKEN_CAP:
        issues.append(
            {
                "code": "description_too_long",
                "msg": f"description is {tokens} tokens; cap {DESCRIPTION_TOKEN_CAP}",
            }
        )
    unknown = [n for n in pack.allowed_tools if n not in catalog_names]
    if unknown:
        issues.append({"code": "unknown_tools", "msg": "allowed-tools not in catalog", "tools": unknown})
    if any(" " in n or n != n.strip() for n in pack.allowed_tools):
        issues.append({"code": "malformed_tool_name", "msg": "tool names must be catalog slugs"})
    return issues


#: Findings that must refuse the write. A pack naming a tool the catalog does not
#: have — or a name that is not a slug at all — cannot be intersected with a
#: card's tool set, so it fails G9 at compile time anyway; accepting it only buys
#: a draft that can never ship. Every other finding (missing or over-cap
#: description) is worth telling the author about without losing their work.
BLOCKING_LINT_CODES: frozenset[str] = frozenset({"unknown_tools", "malformed_tool_name"})


def catalog_tool_names() -> set[str]:
    """The one tool catalog, as lint's notion of a known tool.

    Imported lazily so ``lint`` stays importable from the pack parser without
    dragging the catalog in.
    """
    from agent_core.tools.catalog import CATALOG

    return set(CATALOG.specs)


def assert_pack_lints(pack: SkillPack, *, catalog_names: set[str] | None = None) -> list[dict[str, Any]]:
    """Lint ``pack`` on the way into the catalog.

    Raises ``ValueError`` on any :data:`BLOCKING_LINT_CODES` finding — which the
    API surfaces the same way as ``skill_slug_taken`` — and returns the
    remaining findings for the caller to carry back as warnings.
    """
    names = catalog_tool_names() if catalog_names is None else catalog_names
    issues = lint_pack(pack, catalog_names=names)
    blocking = [i for i in issues if i.get("code") in BLOCKING_LINT_CODES]
    if blocking:
        detail = "; ".join(
            str(i.get("code")) + (f" ({', '.join(i['tools'])})" if i.get("tools") else "")
            for i in blocking
        )
        raise ValueError(f"skill_lint_failed: {detail}")
    return [i for i in issues if i.get("code") not in BLOCKING_LINT_CODES]
