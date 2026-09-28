"""Shared agent helpers: guardrails, prompt rules, sentiment.

Re-exports are resolved lazily (PEP 562), the same way the sibling packages defer theirs.
Importing *any* submodule runs this ``__init__`` first, so an eager import here
would make every submodule pay for all of them, and an import cycle through
the database layer would decide whether the application starts at all.

Deferring costs nothing at runtime — the first attribute access resolves the
module and caches it in ``globals()`` — and changes no public name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed at runtime
    # PEP 484's explicit re-export form. Resolved at runtime by __getattr__
    # below; a type checker needs them written down to follow the names.
    from agent_core.guardrails import evaluate_guardrails as evaluate_guardrails
    from agent_core.guardrails import (
        mentions_recording_disclosure as mentions_recording_disclosure,
    )
    from agent_core.guardrails import should_halt as should_halt
    from agent_core.prompt import build_system_prompt as build_system_prompt
    from agent_core.prompt import default_context as default_context
    from agent_core.prompt import guardrail_rules as guardrail_rules
    from agent_core.sentiment import estimate_sentiment as estimate_sentiment
    from agent_core.sentiment import sentiment_label as sentiment_label

_EXPORTS: dict[str, str] = {
    "build_system_prompt": "agent_core.prompt",
    "default_context": "agent_core.prompt",
    "estimate_sentiment": "agent_core.sentiment",
    "evaluate_guardrails": "agent_core.guardrails",
    "guardrail_rules": "agent_core.prompt",
    "mentions_recording_disclosure": "agent_core.guardrails",
    "sentiment_label": "agent_core.sentiment",
    "should_halt": "agent_core.guardrails",
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
