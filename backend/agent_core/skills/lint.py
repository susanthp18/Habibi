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
