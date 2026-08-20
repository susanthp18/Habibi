"""Agent Card package.

Re-exports are resolved lazily (PEP 562). Importing them eagerly made this
``__init__`` pull in ``agent_core.cards.compile``, which imports
``agent_core.skills.intersect``, which imports ``agent_core.cards.schema`` —
and importing a submodule runs the package ``__init__`` first. So the cycle
closed on itself whenever ``agent_core.skills`` was the first of the two
packages touched:

    agent_core.skills.intersect
      -> agent_core.cards.schema
        -> agent_core.cards.__init__
          -> agent_core.cards.compile
            -> agent_core.skills.intersect   (still initialising)
            ImportError: cannot import name 'PLATFORM_SKILL_TOOLS'

Import order decided whether the process survived. ``voice/bot.py`` defers
``from agent_core.skills.runtime import mouth_turn_state`` into the function
that builds the system prompt, so in the voice worker that lazy import was the
first to touch the cycle and every call would have died assembling its prompt.

Deferring here breaks the loop without changing the public surface: by the time
anything asks for ``compile_card``, both packages have finished initialising.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed at runtime
    from agent_core.cards.compile import CompileError, CompileReport, compile_card
    from agent_core.cards.defaults import (
        COLLECTIONS_BOT_ID,
        FIRST_PARTY_BOT_IDS,
        FIRST_PARTY_BOTS,
        INSURANCE_BOT_ID,
        INTAKE_BOT_ID,
        SUPERVISOR_BOT_ID,
        card_dump,
        card_for,
    )
    from agent_core.cards.schema import AgentCard, parse_card

_EXPORTS: dict[str, str] = {
    "AgentCard": "agent_core.cards.schema",
    "COLLECTIONS_BOT_ID": "agent_core.cards.defaults",
    "CompileError": "agent_core.cards.compile",
    "CompileReport": "agent_core.cards.compile",
    "FIRST_PARTY_BOT_IDS": "agent_core.cards.defaults",
    "FIRST_PARTY_BOTS": "agent_core.cards.defaults",
    "INSURANCE_BOT_ID": "agent_core.cards.defaults",
    "INTAKE_BOT_ID": "agent_core.cards.defaults",
    "SUPERVISOR_BOT_ID": "agent_core.cards.defaults",
    "card_dump": "agent_core.cards.defaults",
    "card_for": "agent_core.cards.defaults",
    "compile_card": "agent_core.cards.compile",
    "parse_card": "agent_core.cards.schema",
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from importlib import import_module

    value = getattr(import_module(module_path), name)
    globals()[name] = value  # resolve once, then behave like a plain attribute
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *_EXPORTS})
