"""AgentTuning — one serialisable config for voice / sandbox / WhatsApp.

Persisted on bot_deployments.tuning (JSONB). Every Pipecat Settings / VAD /
Smart-Turn / barge-in / mute / idle knob the product exposes lives here.
A knob that is not in AgentTuning does not exist in the product.

See voice_agent_plan.md §4.7 and sandbox_plan.md §4.4.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

# ── Presets (Sandbox Tuning Studio dropdown) ───────────────────────────────

PRESET_EMPATHETIC_COLLECTIONS: dict[str, Any] = {
    "llm": {
        "temperature": 0.4,
        "top_p": 0.9,
        "frequency_penalty": 0.3,
        "presence_penalty": 0.0,
        "max_completion_tokens": 220,
        "seed": None,
    },
    "tts": {
        "voice": "en-IN-AartiNeural",
        "style": "empathetic",
        "style_degree": "1.4",
        "rate": "1.05",
        "pitch": "+2%",
        "volume": "default",
        "emphasis": None,
        "text_aggregation_mode": "SENTENCE",
    },
    "stt": {
        "language": "en-IN",
        "fallback_languages": ["hi-IN", "en-IN"],
        "profanity": "raw",
    },
    "vad": {
        "confidence": 0.7,
        "start_secs": 0.15,
        "stop_secs": 0.2,
        "min_volume": 0.6,
    },
    "turn": {
        "stop_secs": 3.0,
        "pre_speech_ms": 0,
        "max_duration_secs": 8.0,
    },
    "interaction": {
        "barge_in": "on",
        "min_words": 3,
        "mute": ["until_first_bot_complete", "during_function_calls"],
        # 6.0 fired inside normal thinking time. On call VS-6B252E0479 the
        # caller's real pauses ran 3-28s — twice the ladder tripped at exactly
        # 6.006s while they were still composing an answer, and the bot talked
        # over the reply it had just asked for. 12s still reads as attentive on
        # a phone call and sits above the pauses that matter.
        "idle_timeout_secs": 12.0,
        "idle_ladder": ["nudge", "direct", "close"],
    },
}

PRESET_BRISK_VERIFICATION: dict[str, Any] = {
    **deepcopy(PRESET_EMPATHETIC_COLLECTIONS),
    "llm": {
        **PRESET_EMPATHETIC_COLLECTIONS["llm"],
        "temperature": 0.25,
        "max_completion_tokens": 160,
        "frequency_penalty": 0.1,
    },
    "tts": {
        **PRESET_EMPATHETIC_COLLECTIONS["tts"],
        "style": "friendly",
        "style_degree": "1.2",
        "rate": "1.12",
    },
    "interaction": {
        **PRESET_EMPATHETIC_COLLECTIONS["interaction"],
        "barge_in": "min_words",
        "min_words": 2,
        "idle_timeout_secs": 10.0,
    },
}

PRESET_FIRM_LEGAL: dict[str, Any] = {
    **deepcopy(PRESET_EMPATHETIC_COLLECTIONS),
    "llm": {
        **PRESET_EMPATHETIC_COLLECTIONS["llm"],
        "temperature": 0.2,
        "max_completion_tokens": 200,
        "frequency_penalty": 0.4,
    },
    "tts": {
        **PRESET_EMPATHETIC_COLLECTIONS["tts"],
        "style": "serious",
        "style_degree": "1.1",
        "rate": "0.98",
        "pitch": "+0%",
    },
    "interaction": {
        **PRESET_EMPATHETIC_COLLECTIONS["interaction"],
        "barge_in": "locked",  # protect mandatory disclosures
        "idle_timeout_secs": 15.0,
    },
}

PRESET_LOW_LATENCY_DEMO: dict[str, Any] = {
    **deepcopy(PRESET_EMPATHETIC_COLLECTIONS),
    "llm": {
        **PRESET_EMPATHETIC_COLLECTIONS["llm"],
        "temperature": 0.3,
        "max_completion_tokens": 140,
        "frequency_penalty": 0.2,
    },
    "tts": {
        **PRESET_EMPATHETIC_COLLECTIONS["tts"],
        "style": "friendly",
        "style_degree": "1.3",
        "rate": "1.1",
        "text_aggregation_mode": "TOKEN",
    },
    "vad": {
        **PRESET_EMPATHETIC_COLLECTIONS["vad"],
        "start_secs": 0.12,
    },
    "interaction": {
        **PRESET_EMPATHETIC_COLLECTIONS["interaction"],
        "idle_timeout_secs": 10.0,
    },
}

PRESETS: dict[str, dict[str, Any]] = {
    "empathetic-collections": PRESET_EMPATHETIC_COLLECTIONS,
    "brisk-verification": PRESET_BRISK_VERIFICATION,
    "firm-legal": PRESET_FIRM_LEGAL,
    "low-latency-demo": PRESET_LOW_LATENCY_DEMO,
}

DEFAULT_PRESET_ID = "empathetic-collections"


def default_tuning() -> dict[str, Any]:
    """Empathetic-collections preset — the product default."""
    return deepcopy(PRESETS[DEFAULT_PRESET_ID])


def get_preset(preset_id: str) -> dict[str, Any]:
    key = (preset_id or "").strip().lower()
    if key not in PRESETS:
        raise KeyError(f"unknown_tuning_preset: {preset_id}")
    return deepcopy(PRESETS[key])


def list_presets() -> list[dict[str, Any]]:
    return [
        {"id": pid, "label": pid.replace("-", " ").title(), "tuning": deepcopy(body)}
        for pid, body in PRESETS.items()
    ]


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any] | None) -> dict[str, Any]:
    """Merge overlay onto base.

    Required section mappings (dict values already present on base) are preserved
    when the overlay replaces them with null/non-dict junk — only nested dict
    overlays are applied into those sections.
    """
    out = deepcopy(base)
    if not isinstance(overlay, dict):
        return out
    for key, value in overlay.items():
        if isinstance(out.get(key), dict):
            if isinstance(value, dict):
                out[key] = _deep_merge(out[key], value)
            # else: keep required base mapping (ignore null/list/scalar wipe)
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    # float() accepts "nan"/"inf". NaN compares false against everything, so the
    # clamp below silently returned `hi` — a persisted "nan" confidence became
    # the maximum rather than the default.
    if not math.isfinite(n):
        return default
    return max(lo, min(hi, n))


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def normalize_tuning(raw: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fill defaults + clamp to doc-legal ranges. Always returns a full AgentTuning."""
    t = _deep_merge(default_tuning(), raw if isinstance(raw, dict) else None)

    llm = t["llm"]
    llm["temperature"] = _clamp_float(llm.get("temperature"), 0.0, 2.0, 0.4)
    llm["top_p"] = _clamp_float(llm.get("top_p"), 0.0, 1.0, 0.9)
    llm["frequency_penalty"] = _clamp_float(llm.get("frequency_penalty"), -2.0, 2.0, 0.3)
    llm["presence_penalty"] = _clamp_float(llm.get("presence_penalty"), -2.0, 2.0, 0.0)
    llm["max_completion_tokens"] = _clamp_int(llm.get("max_completion_tokens"), 32, 1024, 220)
    seed = llm.get("seed")
    llm["seed"] = None if seed is None else _clamp_int(seed, 0, 2_147_483_647, 0)

    tts = t["tts"]
    mode = str(tts.get("text_aggregation_mode") or "SENTENCE").upper()
    tts["text_aggregation_mode"] = "TOKEN" if mode == "TOKEN" else "SENTENCE"
    tts["style_degree"] = (
        f"{_clamp_float(tts.get('style_degree'), 0.01, 2.0, 1.4):.2f}".rstrip("0").rstrip(".") or "1.4"
    )
    tts["voice"] = str(tts.get("voice") or "en-IN-AartiNeural").strip()
    tts["rate"] = str(tts.get("rate") or "1.05")
    tts["pitch"] = str(tts.get("pitch") or "+2%")
    tts["volume"] = str(tts.get("volume") or "default")
    if tts.get("style"):
        tts["style"] = str(tts["style"]).strip().lower()
    if tts.get("emphasis") in ("", "none", "null"):
        tts["emphasis"] = None

    stt = t["stt"]
    stt["language"] = str(stt.get("language") or "en-IN").strip()
    fallbacks = stt.get("fallback_languages") or ["hi-IN", "en-IN"]
    if not isinstance(fallbacks, list):
        fallbacks = ["hi-IN", "en-IN"]
    stt["fallback_languages"] = [str(x).strip() for x in fallbacks if str(x).strip()]
    if stt["language"] not in stt["fallback_languages"]:
        stt["fallback_languages"] = [stt["language"], *stt["fallback_languages"]]
    prof = str(stt.get("profanity") or "raw").strip().lower()
    stt["profanity"] = prof if prof in ("raw", "masked", "removed") else "raw"

    vad = t["vad"]
    vad["confidence"] = _clamp_float(vad.get("confidence"), 0.0, 1.0, 0.7)
    vad["start_secs"] = _clamp_float(vad.get("start_secs"), 0.05, 2.0, 0.15)
    # Smart Turn docs require stop_secs ≈ 0.2 when Smart Turn is on.
    vad["stop_secs"] = _clamp_float(vad.get("stop_secs"), 0.2, 2.0, 0.2)
    vad["min_volume"] = _clamp_float(vad.get("min_volume"), 0.0, 1.0, 0.6)

    turn = t["turn"]
    turn["stop_secs"] = _clamp_float(turn.get("stop_secs"), 0.5, 10.0, 3.0)
    turn["pre_speech_ms"] = _clamp_float(turn.get("pre_speech_ms"), 0.0, 2000.0, 0.0)
    turn["max_duration_secs"] = _clamp_float(turn.get("max_duration_secs"), 2.0, 30.0, 8.0)

    ix = t["interaction"]
    barge = str(ix.get("barge_in") or "on").strip().lower()
    ix["barge_in"] = barge if barge in ("on", "min_words", "locked") else "on"
    ix["min_words"] = _clamp_int(ix.get("min_words"), 1, 12, 3)
    mute = ix.get("mute") or []
    if not isinstance(mute, list):
        mute = ["until_first_bot_complete", "during_function_calls"]
    allowed = {"until_first_bot_complete", "during_function_calls", "always", "first_speech"}
    ix["mute"] = [m for m in mute if isinstance(m, str) and m in allowed]
    if not ix["mute"]:
        # Same fallback shape as idle_ladder below: a persisted list of only
        # unrecognised values must not silently disable user muting entirely,
        # which lets the customer's own audio feed back during function calls.
        ix["mute"] = ["until_first_bot_complete", "during_function_calls"]
    idle = ix.get("idle_timeout_secs")
    try:
        idle_f = float(idle)
    except (TypeError, ValueError):
        idle_f = 6.0
    ix["idle_timeout_secs"] = 0.0 if idle_f <= 0 else _clamp_float(idle_f, 2.0, 30.0, 6.0)
    ladder = ix.get("idle_ladder") or ["nudge", "direct", "close"]
    if not isinstance(ladder, list) or not ladder:
        ladder = ["nudge", "direct", "close"]
    ix["idle_ladder"] = [str(s) for s in ladder if str(s) in ("nudge", "direct", "close")]
    if not ix["idle_ladder"]:
        ix["idle_ladder"] = ["nudge", "direct", "close"]

    return t


def merge_tuning_delta(base: dict[str, Any] | None, delta: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-merge a Studio delta onto a full AgentTuning, then re-normalize."""
    return normalize_tuning(_deep_merge(normalize_tuning(base), delta if isinstance(delta, dict) else None))


def apply_voice_config_overlay(
    tuning: dict[str, Any],
    *,
    voice_name: str | None = None,
    speed: float | None = None,
    pitch: int | None = None,
    warmth: int | None = None,
) -> dict[str, Any]:
    """Optionally overlay Prompt Studio voice fields onto AgentTuning.tts.

    Tuning Studio owns ``style`` / ``rate`` / ``pitch`` via AgentTuning. Callers
    should pass ``speed`` / ``pitch`` / ``warmth`` only when those Studio knobs
    are intentionally authoritative (legacy path). Pass ``None`` (default from
    voice bot) to leave AgentTuning.tts untouched. ``voice_name`` may still be
    applied so the Prompt Studio voice picker selects the neural voice.
    """
    t = normalize_tuning(tuning)
    tts = t["tts"]
    if voice_name:
        tts["voice"] = str(voice_name).strip()
    # These arrive from persisted Studio jsonb, so a legacy/hand-edited row can
    # carry a string or null. Raw float()/int() turned that into a TypeError in
    # the middle of call setup; the clamp helpers fall back the same way every
    # other tuning field does. Pitch is clamped *before* the ×2 conversion so a
    # stray 9999 cannot emit "+19998%" into the SSML.
    if speed is not None:
        # Azure rate is a float string; nudge slightly for phone like bot.py did.
        rate = max(0.85, min(1.25, _clamp_float(speed, 0.5, 2.0, 1.0) * 1.03))
        tts["rate"] = f"{rate:.2f}"
    if pitch is not None:
        p = _clamp_int(pitch, -25, 25, 0)
        tts["pitch"] = "+2%" if p == 0 else f"{p * 2:+d}%"
    if warmth is not None:
        # Mirror voice.natural.azure_tts_style_from_warmth (keep agent_core
        # free of the voice package — sandbox / WhatsApp also import this).
        w = _clamp_int(warmth, 0, 100, 60)
        if w >= 70:
            tts["style"], tts["style_degree"] = "friendly", "1.6"
        elif w <= 35:
            tts["style"], tts["style_degree"] = "empathetic", "1.15"
        else:
            tts["style"], tts["style_degree"] = "empathetic", "1.4"
    return normalize_tuning(t)


# Live-mutable subset (LLM + TTS). Everything else is construction-time.
LIVE_TUNABLE_SECTIONS = frozenset({"llm", "tts"})


def live_delta_only(delta: dict[str, Any] | None) -> dict[str, Any]:
    """Strip next-call-only knobs from a mid-call Studio delta."""
    if not isinstance(delta, dict):
        return {}
    out: dict[str, Any] = {}
    for section in LIVE_TUNABLE_SECTIONS:
        if section in delta and isinstance(delta[section], dict):
            # text_aggregation_mode is construction-time even inside tts.
            section_delta = dict(delta[section])
            if section == "tts":
                section_delta.pop("text_aggregation_mode", None)
            out[section] = section_delta
    return out
