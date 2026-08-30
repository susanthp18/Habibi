"""Shared agent brain — sandbox, WhatsApp bot, and voice all import from here.

bot_deployments is the authoritative runtime config source (see deployment.py).
"""

from agent_core.deployment import load_active_bundle, resolve_prompt_bundle
from agent_core.guardrails import (
    evaluate_guardrails,
    mentions_recording_disclosure,
    should_halt,
)
from agent_core.intent import classify_intent, resolve_intent
from agent_core.prompt import build_system_prompt, default_context, guardrail_rules
from agent_core.sentiment import estimate_sentiment, sentiment_label
from agent_core.turn import (
    CHAT_TEMPERATURE,
    DEFAULT_TOP_K,
    assemble_turn_messages,
    context_blocks_from_results,
)
from agent_core.tuning import (
    DEFAULT_PRESET_ID,
    PRESETS,
    default_tuning,
    get_preset,
    list_presets,
    merge_tuning_delta,
    normalize_tuning,
)
from agent_core.voice_ssml import build_voice_ssml, voice_params_from_config

__all__ = [
    "CHAT_TEMPERATURE",
    "DEFAULT_PRESET_ID",
    "DEFAULT_TOP_K",
    "PRESETS",
    "assemble_turn_messages",
    "build_system_prompt",
    "guardrail_rules",
    "build_voice_ssml",
    "classify_intent",
    "context_blocks_from_results",
    "default_context",
    "default_tuning",
    "estimate_sentiment",
    "evaluate_guardrails",
    "mentions_recording_disclosure",
    "get_preset",
    "list_presets",
    "load_active_bundle",
    "merge_tuning_delta",
    "normalize_tuning",
    "resolve_intent",
    "resolve_prompt_bundle",
    "sentiment_label",
    "should_halt",
    "voice_params_from_config",
]
