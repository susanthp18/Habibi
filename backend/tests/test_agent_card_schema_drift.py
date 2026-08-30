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
from pathlib import Path

import pytest

from agent_core.cards.schema import AgentCard

_TS_CARD = (
    Path(__file__).resolve().parents[2]
    / "Habibi"
    / "src"
    / "api"
    / "agent-card.ts"
)


def _ts_source() -> str:
    if not _TS_CARD.exists():  # pragma: no cover - frontend not checked out
        pytest.skip(f"frontend card type not present at {_TS_CARD}")
    return _TS_CARD.read_text(encoding="utf-8")


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


def test_top_level_members_match() -> None:
    py_members = set(AgentCard.model_fields)
    ts_members = _ts_members()

    missing = py_members - ts_members
    extra = ts_members - py_members
    assert not missing, (
        f"agent-card.ts is missing {sorted(missing)} — the studio cannot edit "
        f"what it cannot name, and nothing in the UI says so"
    )
    assert not extra, (
        f"agent-card.ts invents {sorted(extra)} — schema.py sets extra='forbid', "
        f"so writing one of these makes the card fail validation on publish"
    )


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


def test_rollback_triggers_match() -> None:
    """The vocabulary that caused this file to exist.

    `canary` evaluated six triggers while the card's Literal allowed three, so
    the three outbound-specific ones — an abandoned call, a debt disclosed to a
    third party, an opt-out spike — could not be requested by any published
    version. The frontend must not drift from the widened list either, or the
    checkbox comes back and the publish 422s.
    """
    from agent_core.cards.schema import ROLLBACK_TRIGGERS

    src = _ts_source()
    match = re.search(r"ROLLBACK_TRIGGERS\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert match, "ROLLBACK_TRIGGERS not found in agent-card.ts"
    ts_triggers = set(re.findall(r'"([^"]+)"', match.group(1)))
    assert ts_triggers == set(ROLLBACK_TRIGGERS)


# ---------------------------------------------------------------------------
# Prompt variables — the same boundary, a different vocabulary
# ---------------------------------------------------------------------------

_TS_SEED = (
    Path(__file__).resolve().parents[2] / "Habibi" / "src" / "data" / "prompt-studio-seed.ts"
)


def _ts_const(name: str) -> set[str]:
    if not _TS_SEED.exists():  # pragma: no cover - frontend not checked out
        pytest.skip(f"frontend seed not present at {_TS_SEED}")
    src = _TS_SEED.read_text(encoding="utf-8")
    match = re.search(rf"{name}\s*=\s*\[(.*?)\]\s*as const", src, re.S)
    assert match, f"{name} not found in prompt-studio-seed.ts"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_system_safe_variables_match() -> None:
    """The editor's variable palette is a promise about runtime behaviour.

    A token the palette offers but `render_system_prompt` will not substitute
    does not merely fail to render: `strip_unrendered_crm_tokens` then deletes
    the entire line it sits on, so the author loses a sentence they wrote and
    the live policy silently differs from the one on screen. A token the backend
    *does* substitute but the palette omits shows up under "Unknown variable(s)
    — they won't be substituted", which is the opposite of true.
    """
    import prompt_render

    assert _ts_const("SYSTEM_SAFE_VARIABLES") == set(prompt_render.SYSTEM_SAFE_VARIABLES)


def test_crm_variables_match() -> None:
    """`CRM_VARIABLES` must be exactly what `strip_unrendered_crm_tokens` eats."""
    import prompt_render

    crm_only = set(prompt_render.KNOWN_VARIABLES) - set(prompt_render.SYSTEM_SAFE_VARIABLES)
    assert _ts_const("CRM_VARIABLES") == crm_only
