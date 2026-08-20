"""Voice runtime env helpers — map our .env names onto Pipecat constructors.

Do NOT rename AZURE_OPENAI_* / AZURE_SPEECH_* globals; pass values explicitly.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Allow `python -m voice.spike` and `python voice/spike.py` from backend/.
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from env_loader import load_env  # noqa: E402


def _require(name: str) -> str:
    load_env()
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _optional(name: str) -> str | None:
    load_env()
    value = (os.getenv(name) or "").strip()
    return value or None


def azure_openai_api_key() -> str:
    return _require("AZURE_OPENAI_API_KEY")


def azure_openai_endpoint() -> str:
    return _require("AZURE_OPENAI_ENDPOINT").rstrip("/")


def azure_openai_api_version() -> str:
    load_env()
    return (os.getenv("AZURE_OPENAI_API_VERSION") or "2025-04-01-preview").strip()


def azure_openai_chat_deployment() -> str:
    return _require("AZURE_OPENAI_CHAT_DEPLOYMENT")


def azure_openai_voice_api_key() -> str:
    """Voice resource key (BT-RMC etc.); falls back to main AZURE_OPENAI_API_KEY."""
    return _optional("AZURE_OPENAI_VOICE_API_KEY") or azure_openai_api_key()


def azure_openai_voice_endpoint() -> str:
    """Voice resource endpoint; falls back to main AZURE_OPENAI_ENDPOINT."""
    raw = _optional("AZURE_OPENAI_VOICE_ENDPOINT")
    return (raw or azure_openai_endpoint()).rstrip("/")


def azure_openai_voice_api_version() -> str:
    return _optional("AZURE_OPENAI_VOICE_API_VERSION") or azure_openai_api_version()


def azure_openai_voice_deployment() -> str:
    """Fast voice-loop deployment; falls back to CHAT until provisioned."""
    return _optional("AZURE_OPENAI_VOICE_DEPLOYMENT") or azure_openai_chat_deployment()


def azure_speech_key() -> str:
    return _require("AZURE_SPEECH_KEY")


def azure_speech_region() -> str:
    return _require("AZURE_SPEECH_REGION")


def azure_speech_default_voice() -> str:
    load_env()
    return (os.getenv("AZURE_SPEECH_TTS_VOICE_DEFAULT") or "en-IN-AartiNeural").strip()


def voice_handoff_mode() -> str:
    """callback_queue (Inbox) | warm (Twilio conference dial-out).

    An unrecognised explicit value is a configuration error, not a reason to
    silently queue callbacks: an operator who typed ``VOICE_HANDOFF_MODE=warn``
    expecting warm transfers would never find out.
    """
    load_env()
    raw = os.getenv("VOICE_HANDOFF_MODE")
    if raw is None or not raw.strip():
        return "callback_queue"
    mode = raw.strip().lower()
    if mode in {"warm", "warm_transfer", "conference"}:
        return "warm"
    if mode == "callback_queue":
        return mode
    raise RuntimeError(
        f"Invalid VOICE_HANDOFF_MODE={mode!r} (expected callback_queue or warm)"
    )


def _flag(name: str) -> bool:
    load_env()
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _flag_default_on(name: str) -> bool:
    """Like :func:`_flag` but unset means on — for kill switches, not opt-ins."""
    load_env()
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return True
    return raw in {"1", "true", "yes", "on"}


def voice_turn_audio(*, sandbox: bool = False) -> bool:
    """Emit per-turn PCM for Inspector playback.

    Unset defaults on for sandbox sessions and off for production calls.
    """
    load_env()
    raw = (os.getenv("VOICE_TURN_AUDIO") or "").strip().lower()
    if not raw:
        return bool(sandbox)
    return raw in {"1", "true", "yes", "on"}


def voice_filter_incomplete_turns() -> bool:
    return _flag("VOICE_FILTER_INCOMPLETE_TURNS")


def voice_multi_agent_enabled() -> bool:
    return _flag("VOICE_MULTI_AGENT_ENABLED")


def voice_latency_observer() -> bool:
    """Attach Pipecat's UserBotLatencyObserver (needs enable_metrics=True).

    On by default: it is passive, and without it a slow turn cannot be
    attributed to STT, the LLM, TTS, or a tool call without grepping logs.
    """
    return _flag_default_on("VOICE_LATENCY_OBSERVER")


def voice_context_refresh() -> bool:
    """Re-read the CRM card after a write that changes what the card shows.

    On by default — this is a bug fix, not a feature: without it the bot's own
    context still claims the account has no open promises immediately after it
    booked one. Kept as a kill switch because it adds a DB read per write tool.
    """
    return _flag_default_on("VOICE_CONTEXT_REFRESH")


def _number(name: str, default: float, *, minimum: float, maximum: float) -> float:
    """Bounded numeric env read.

    Clamped rather than rejected: these are latency/spend tuning knobs on the
    audio path, and a fat-fingered ``KB_SPEC_MAX_PER_TURN=200`` should cost a
    log line, not a failed call.
    """
    load_env()
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


# --------------------------------------------------------------------------
# Speculative KB retrieval (voice/kb_enrich.py)
# --------------------------------------------------------------------------


def kb_spec_enabled() -> bool:
    """Start KB retrieval on a partial transcript instead of the final one."""
    return _flag_default_on("KB_SPEC_ENABLED")


def kb_spec_max_per_turn() -> int:
    """Hard cap on embeds per user turn — the backstop behind the debounce."""
    return int(_number("KB_SPEC_MAX_PER_TURN", 2, minimum=0, maximum=5))


def kb_spec_max_inflight() -> int:
    return int(_number("KB_SPEC_MAX_INFLIGHT", 1, minimum=1, maximum=3))


def kb_spec_min_words() -> int:
    """Below this the partial is too stubby to be a useful query."""
    return int(_number("KB_SPEC_MIN_WORDS", 5, minimum=2, maximum=20))


def kb_spec_stable_ms() -> float:
    """An interim must go unchanged this long before it is worth an embed.

    This — not the per-turn budget — is what actually bounds spend: Azure emits
    many interims per second and only the last stable one fires.
    """
    return _number("KB_SPEC_STABLE_MS", 250, minimum=50, maximum=2000)


def kb_spec_match_min() -> float:
    """Token containment of the speculated query within the final one."""
    return _number("KB_SPEC_MATCH_MIN", 0.8, minimum=0.5, maximum=1.0)


def kb_enrich_wait_ms() -> float:
    """How long the final transcript waits on an in-flight speculation."""
    return _number("KB_ENRICH_WAIT_MS", 120, minimum=0, maximum=1000)


def kb_enrich_fallback() -> str:
    """``inline`` | ``spec_only`` — what to do when speculation missed.

    Defaults to ``inline``, which is byte-for-byte today's behaviour. Speculation
    cannot fire on a DTMF turn, a one-interim utterance, an idle-ladder turn, or
    an exhausted budget; ``spec_only`` silently drops grounding on all of those,
    and a four-scenario eval suite is far too coarse to notice. Flip it once
    kb_spec_hits/kb_spec_attempts justifies it.
    """
    load_env()
    raw = (os.getenv("KB_ENRICH_FALLBACK") or "").strip().lower()
    return "spec_only" if raw == "spec_only" else "inline"


def voice_flow_graph() -> str:
    """``legacy`` | ``hub`` | ``db`` | ``auto`` (default).

    ``auto`` (unset) runs the Prompt Studio graph when the published version
    actually has nodes, otherwise the hardcoded collections script. ``legacy``
    is the kill-switch that ignores an authored graph. ``db`` always prefers
    the authored graph (and still falls back if it is empty or fails to
    compile). ``hub`` is the merged collections_hub experiment.

    An unrecognised value falls back to ``auto`` rather than raising: an
    operator typo must not take voice down.
    """
    load_env()
    raw = (os.getenv("VOICE_FLOW_GRAPH") or "").strip().lower()
    return raw if raw in {"hub", "db", "legacy", "auto"} else "auto"


def voice_uses_authored_flow(graph_data: Any, *, override: str | None = None) -> bool:
    """Whether this call should compile ``prompt_versions.flow`` instead of Python.

    ``legacy`` / ``hub`` never do. ``db`` / ``auto`` do when the stored JSON
    has nodes. Sandbox per-call override is ``session.extra["flowGraph"]``.
    """
    mode = (override or voice_flow_graph()).strip().lower()
    if mode in {"legacy", "hub"}:
        return False
    from flow_graph import is_authored

    return is_authored(graph_data)


def voice_tool_change_messages() -> bool:
    """Announce advertised-tool-set changes to the model on node transitions.

    Cheap enough to leave on. Note its value is proportional to how often the
    tool set changes, so it is a strong win under VOICE_FLOW_GRAPH=legacy and a
    marginal one under `hub`, which deliberately transitions less.
    """
    return _flag_default_on("VOICE_TOOL_CHANGE_MESSAGES")


def voice_memory() -> bool:
    """Read/write cross-call ``customer_memory``.

    Off by default for the first ship: the summariser prompt writes rows against
    real customers and wants a supervised look at its output before it is
    trusted. The SQL-derived commitments half carries no such risk, but the two
    ship behind one switch so "memory on" means one thing.
    """
    return _flag("VOICE_MEMORY")


def voice_memory_max_age_days() -> int:
    """Suppress memory older than this at read time — stale context is worse
    than none, because the model trusts it exactly as much as fresh context."""
    return int(_number("VOICE_MEMORY_MAX_AGE_DAYS", 90, minimum=1, maximum=3650))


def voice_startup_timing() -> bool:
    """Attach StartupTimingObserver — diagnostic, off by default.

    This is what says whether the ~1.2s handshake tax in voice/SPIKE_NOTES.md
    is transport setup or service construction.
    """
    return _flag("VOICE_STARTUP_TIMING")


def voice_ivr_enabled() -> bool:
    """Navigate a partner/workplace IVR on outbound dials before speaking.

    Off by default: on a direct-to-handset campaign the classifier is pure
    added latency on the first turn.
    """
    return _flag("VOICE_IVR_ENABLED")


def voice_dtmf_input_enabled() -> bool:
    """Fold inbound keypad digits into the transcript (telephony only)."""
    return _flag("VOICE_DTMF_INPUT_ENABLED")


def redis_url() -> str | None:
    return _optional("REDIS_URL")


def voice_public_base_url() -> str | None:
    """Public HTTPS origin for the Pipecat runner (Media Streams /ws).

    Must point at the voice process (:7860), not the CRM API (:8000).
    """
    return _optional("VOICE_PUBLIC_BASE_URL")
