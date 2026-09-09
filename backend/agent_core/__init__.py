"""Shared agent brain — sandbox, WhatsApp bot, and voice all import from here.

bot_deployments is the authoritative runtime config source (see deployment.py).

Re-exports are resolved lazily (PEP 562), the same way ``agent_core.cards`` and
``agent_core.fleet`` already defer theirs, and for the same reason one rung up.
Importing *any* submodule runs this ``__init__`` first, and eagerly pulling
``deployment`` from here made the whole application a prerequisite for reading a
pydantic model:

    schemas                              (schemas.py:12, for CompiledBundle)
      -> agent_core.fleet.schema
        -> agent_core.__init__
          -> agent_core.deployment
            -> db
              -> schemas                 partially initialised — ImportError

So ``import schemas`` failed on its own, and whether the application started at
all depended on which module an entrypoint happened to touch first. The two
sibling packages had each closed their own leg of this cycle; this is the leg
that was left, and it is the one that reaches the database.

It also made a cheap test expensive: pinning the TypeScript card mirror against
``agent_core.cards.schema`` needs pydantic and nothing else, but importing it
dragged in SQLAlchemy, psycopg and httpx.

Deferring costs nothing at runtime — the first attribute access resolves the
module and caches it in ``globals()`` — and changes no public name.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never executed at runtime
    # PEP 484's explicit re-export form. Resolved at runtime by __getattr__
    # below; a type checker needs them written down to follow the names.
    from agent_core.deployment import load_active_bundle as load_active_bundle
    from agent_core.deployment import resolve_prompt_bundle as resolve_prompt_bundle
    from agent_core.guardrails import evaluate_guardrails as evaluate_guardrails
    from agent_core.guardrails import (
        mentions_recording_disclosure as mentions_recording_disclosure,
    )
    from agent_core.guardrails import should_halt as should_halt
    from agent_core.intent import classify_intent as classify_intent
    from agent_core.intent import resolve_intent as resolve_intent
    from agent_core.prompt import build_system_prompt as build_system_prompt
    from agent_core.prompt import default_context as default_context
    from agent_core.prompt import guardrail_rules as guardrail_rules
    from agent_core.sentiment import estimate_sentiment as estimate_sentiment
    from agent_core.sentiment import sentiment_label as sentiment_label
    from agent_core.turn import CHAT_TEMPERATURE as CHAT_TEMPERATURE
    from agent_core.turn import DEFAULT_TOP_K as DEFAULT_TOP_K
    from agent_core.turn import assemble_turn_messages as assemble_turn_messages
    from agent_core.turn import context_blocks_from_results as context_blocks_from_results
    from agent_core.tuning import DEFAULT_PRESET_ID as DEFAULT_PRESET_ID
    from agent_core.tuning import PRESETS as PRESETS
    from agent_core.tuning import default_tuning as default_tuning
    from agent_core.tuning import get_preset as get_preset
    from agent_core.tuning import list_presets as list_presets
    from agent_core.tuning import merge_tuning_delta as merge_tuning_delta
    from agent_core.tuning import normalize_tuning as normalize_tuning
    from agent_core.voice_ssml import build_voice_ssml as build_voice_ssml
    from agent_core.voice_ssml import voice_params_from_config as voice_params_from_config

_EXPORTS: dict[str, str] = {
    "CHAT_TEMPERATURE": "agent_core.turn",
    "DEFAULT_PRESET_ID": "agent_core.tuning",
    "DEFAULT_TOP_K": "agent_core.turn",
    "PRESETS": "agent_core.tuning",
    "assemble_turn_messages": "agent_core.turn",
    "build_system_prompt": "agent_core.prompt",
    "build_voice_ssml": "agent_core.voice_ssml",
    "classify_intent": "agent_core.intent",
    "context_blocks_from_results": "agent_core.turn",
    "default_context": "agent_core.prompt",
    "default_tuning": "agent_core.tuning",
    "estimate_sentiment": "agent_core.sentiment",
    "evaluate_guardrails": "agent_core.guardrails",
    "get_preset": "agent_core.tuning",
    "guardrail_rules": "agent_core.prompt",
    "list_presets": "agent_core.tuning",
    "load_active_bundle": "agent_core.deployment",
    "mentions_recording_disclosure": "agent_core.guardrails",
    "merge_tuning_delta": "agent_core.tuning",
    "normalize_tuning": "agent_core.tuning",
    "resolve_intent": "agent_core.intent",
    "resolve_prompt_bundle": "agent_core.deployment",
    "sentiment_label": "agent_core.sentiment",
    "should_halt": "agent_core.guardrails",
    "voice_params_from_config": "agent_core.voice_ssml",
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
