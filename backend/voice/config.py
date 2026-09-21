"""Voice runtime env helpers — map our .env names onto Pipecat constructors.

Do NOT rename AZURE_OPENAI_* / AZURE_SPEECH_* globals; pass values explicitly.
"""

from __future__ import annotations

import logging
import os

from env_loader import load_env
from env_utils import env_bool

logger = logging.getLogger(__name__)


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
    # The region has one owner (azure_speech.get_speech_region); this is the
    # voice image's name for it.
    from azure_speech import get_speech_region

    return get_speech_region()


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
    return env_bool(name)


def _flag_default_on(name: str) -> bool:
    """Like :func:`_flag` but unset means on — for kill switches, not opt-ins."""
    load_env()
    return env_bool(name, default=True)


def voice_turn_audio(*, sandbox: bool = False) -> bool:
    """Emit per-turn PCM for Inspector playback.

    Unset defaults on for sandbox sessions and off for production calls.
    """
    load_env()
    return env_bool("VOICE_TURN_AUDIO", default=bool(sandbox))


def voice_filter_incomplete_turns() -> bool:
    return _flag("VOICE_FILTER_INCOMPLETE_TURNS")


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


def kb_spec_shape_gate() -> bool:
    """Require an utterance to look like a KB question before spending an embed.

    Off only as a kill-switch. With it off, the speculator fires on every stable
    interim, which is how one interaction reached 32 retrievals — three quarters
    of them on fragments no passage could answer.
    """
    return _flag_default_on("KB_SPEC_SHAPE_GATE")


def kb_enrich_wait_ms() -> float:
    """How long the final transcript waits on an in-flight speculation.

    Raised from 120ms: a query embed measures 290-410ms warm against Azure (and
    ~1.2s on a cold connection), so a 120ms wait could not win even once — call
    VS-92CDE3F088 recorded 0 speculation hits in 6 attempts. A wait that always
    expires is not a safety valve, it is a guaranteed inline retrieval plus a
    wasted concurrent embed. 400ms covers the warm case; anything slower still
    falls through to the inline path.
    """
    return _number("KB_ENRICH_WAIT_MS", 400, minimum=0, maximum=2000)


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


def voice_tool_change_messages() -> bool:
    """Announce advertised-tool-set changes to the model on node transitions.

    Cheap enough to leave on. Its value is proportional to how often the
    tool set changes between nodes.
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

    This is what says whether the handshake tax on a new call is transport
    setup or service construction.
    """
    return _flag("VOICE_STARTUP_TIMING")


def voice_ivr_enabled() -> bool:
    """Navigate a partner/workplace IVR on outbound dials before speaking.

    Off by default: on a direct-to-handset campaign the classifier is pure
    added latency on the first turn. Unset, commented-false in ``.env.example``,
    and omitted from production compose so it cannot turn on silently.
    """
    load_env()
    return env_bool("VOICE_IVR_ENABLED", default=False)


def voice_stt_segmentation_silence_ms() -> int | None:
    """Azure ``Speech_SegmentationSilenceTimeoutMs``, or None to keep the SDK default.

    Unset/empty leaves Pipecat's ~500ms SDK default. Operators turn this on
    after ``turn.e2e`` / ``turn.endpoint`` exist; do not ship a new default.
    """
    raw = _optional("VOICE_STT_SEGMENTATION_SILENCE_MS")
    if raw is None:
        return None
    try:
        value = int(float(raw))
    except ValueError:
        return None
    return max(100, min(2000, value))


def voice_tts_phrase_cache() -> bool:
    """Replay cached audio for the fixed filler phrases instead of re-synthesising.

    OFF by default, deliberately. The saving is the smallest of its phase --
    the filler plays *while* the tool runs, so its TTS round trip overlaps the
    latency it masks rather than adding to it -- and the risk lands on the
    word-boundary sequencer, which has had a duplication bug before. The cache
    advances the cumulative audio offset itself to keep later word timings
    honest, but that correction wants real `tts_ttfb_ms` / `leading_silence_ms`
    evidence behind it before it is on by default.
    """
    load_env()
    return env_bool("VOICE_TTS_PHRASE_CACHE", default=False)


def voice_analyzer_pool() -> bool:
    """Hand calls a pre-built VAD / Smart Turn analyzer instead of building one.

    On by default. The objects are the same classes with the same params and are
    never shared between calls -- only the moment of construction moves, out of
    the caller's silent line. ``false`` restores per-call construction exactly.
    """
    return _flag_default_on("VOICE_ANALYZER_POOL")


def voice_dtmf_input_enabled() -> bool:
    """Fold inbound keypad digits into the transcript (telephony only)."""
    return _flag("VOICE_DTMF_INPUT_ENABLED")


