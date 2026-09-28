"""The TypeScript Agent Card and the Pydantic one must describe the same card.

`Habibi/src/api/agent-card.ts` is a hand-written mirror of
`agent_core/cards/schema.py`. Hand-written because generating it would add a
build step nobody asked for and a generated file nobody reads — but hand-written
mirrors rot, and this one rots in a way that is expensive to discover.

Every model in schema.py sets ``extra="forbid"``. So a member the frontend
invents is not ignored on the way in; it fails validation, and the first symptom
is a publish rejecting a card the studio was perfectly happy to build. A member
the frontend *omits* is the quieter half: that tab simply cannot edit it, and
nothing says so.

This is the same idea as the repo's `check-spacing-scale.mjs` and
`check-type-scale.mjs` — a cheap check for a class of drift that no type system
spans, because the two type systems are on opposite sides of a JSON boundary.
"""

from __future__ import annotations

import re

from tests.conftest import frontend_file


def _ts_source() -> str:
    return frontend_file("src", "api", "agent-card.ts").read_text(encoding="utf-8")


def _ts_members() -> set[str]:
    """Members of the exported `AGENT_CARD_MEMBERS` list.

    Read from that constant rather than parsed out of the `type AgentCard`
    block: the constant is what the frontend itself uses to reason about the
    card, so checking it means checking the thing that is actually relied on.
    """
    src = _ts_source()
    match = re.search(r"AGENT_CARD_MEMBERS\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert match, "AGENT_CARD_MEMBERS not found in agent-card.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_the_declared_type_covers_every_member() -> None:
    """`AGENT_CARD_MEMBERS` and the `type AgentCard` block must agree too.

    Otherwise the list above could stay honest while the type it claims to
    describe quietly loses a field, and the panels would be back to guessing.
    """
    src = _ts_source()
    match = re.search(r"export type AgentCard = \{(.*?)\n\};", src, re.S)
    assert match, "type AgentCard block not found in agent-card.ts"
    declared = set(re.findall(r"^\s*(\w+)\??:", match.group(1), re.M))
    assert declared == _ts_members(), (
        f"type AgentCard and AGENT_CARD_MEMBERS disagree: "
        f"only in type={sorted(declared - _ts_members())}, "
        f"only in list={sorted(_ts_members() - declared)}"
    )


# ---------------------------------------------------------------------------
# Prompt variables — the same boundary, a different vocabulary
# ---------------------------------------------------------------------------

def _ts_const(name: str) -> set[str]:
    src = frontend_file("src", "lib", "prompt-studio.ts").read_text(encoding="utf-8")
    match = re.search(rf"{name}\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert match, f"{name} not found in lib/prompt-studio.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def _ts_type_members(name: str) -> set[str] | None:
    match = re.search(rf"export type {name} = \{{(.*?)\n\}};", _ts_source(), re.S)
    if not match:
        return None
    return set(re.findall(r"^\s*(\w+)\??:", match.group(1), re.M))


