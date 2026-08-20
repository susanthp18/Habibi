"""Voice safety helpers — loop / abuse / legal / sentiment / hold / language.

Grounded in flow_improve.md §4 edge cases. Pure detection; callers decide
how to escalate (CrmSink alerts + Flow escalate_to_human).
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from agent_core import lexicon

# Rolling windows / thresholds (collections voice).
LOOP_WINDOW = 3
LOOP_SIMILARITY = 0.92
SENTIMENT_WINDOW = 4
SENTIMENT_COLLAPSE = -0.45

# These patterns moved to agent_core/lexicon.py so the text channel, the
# guardrail evaluator and the sentiment scorer stop carrying divergent copies —
# all four feed compliance escalation, and they disagreed. The two narrowings
# this module contributed (an explicit target for `kill`; police context for
# `fir`, the Hinglish फिर) survived the merge as the canonical form.
_ABUSE_RE = lexicon.ABUSE_RE
_LEGAL_RE = lexicon.LEGAL_RE

_HOLD_RE = re.compile(
    r"\b("
    r"hold\s+on|hang\s+on|one\s+(sec|second|minute|moment)|"
    r"just\s+a\s+(sec|second|minute|moment)|give\s+me\s+a\s+(sec|second|minute)|"
    r"wait\s+a\s+(sec|second|minute)|ek\s+minute|ek\s+sec"
    r")\b",
    re.I,
)

# Indic scripts — caller not on Latin en-IN.
_INDIC_SCRIPT_RE = re.compile(
    r"[\u0900-\u097F"  # Devanagari (Hindi/Marathi)
    r"\u0980-\u09FF"  # Bengali
    r"\u0A80-\u0AFF"  # Gujarati
    r"\u0B80-\u0BFF"  # Tamil
    r"\u0C00-\u0C7F"  # Telugu
    r"\u0C80-\u0CFF"  # Kannada
    r"\u0D00-\u0D7F"  # Malayalam
    r"]+"
)

_HINDI_LATIN_RE = re.compile(
    r"\b(namaste|haan|nahi|nahin|kya|aap|mujhe|mera|bahut|theek|"
    r"accha|samajh|paisa|kitna)\b",
    re.I,
)


def _norm_bot_text(text: str) -> str:
    t = unicodedata.normalize("NFKC", (text or "").lower())
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def texts_near_duplicate(a: str, b: str, *, threshold: float = LOOP_SIMILARITY) -> bool:
    na, nb = _norm_bot_text(a), _norm_bot_text(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if abs(len(na) - len(nb)) > max(20, int(0.4 * max(len(na), len(nb)))):
        return False
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def detect_bot_loop(recent_bot_texts: list[str]) -> bool:
    """True when the last N bot turns are near-identical (edge #11)."""
    if len(recent_bot_texts) < LOOP_WINDOW:
        return False
    window = recent_bot_texts[-LOOP_WINDOW:]
    first = window[0]
    return all(texts_near_duplicate(first, t) for t in window[1:])


def detect_abuse(text: str) -> bool:
    return bool(_ABUSE_RE.search(text or ""))


def detect_legal(text: str) -> bool:
    return bool(_LEGAL_RE.search(text or ""))


def detect_hold_request(text: str) -> bool:
    return bool(_HOLD_RE.search(text or ""))


def rolling_sentiment_collapsed(scores: list[float]) -> bool:
    """True when the last N customer sentiment scores average below threshold."""
    if len(scores) < SENTIMENT_WINDOW:
        return False
    window = scores[-SENTIMENT_WINDOW:]
    return (sum(window) / len(window)) <= SENTIMENT_COLLAPSE


def detect_language_signal(text: str) -> str | None:
    """Return a BCP-47 hint when the caller is clearly not on Latin English.

    - ``hi-IN`` for Devanagari or common Hindi-in-Latin
    - ``other`` for other Indic scripts
    """
    raw = text or ""
    if _INDIC_SCRIPT_RE.search(raw):
        # Devanagari → Hindi; other blocks → other
        if re.search(r"[\u0900-\u097F]", raw):
            return "hi-IN"
        return "other"
    markers = {m.group(0).lower() for m in _HINDI_LATIN_RE.finditer(raw)}
    # Require at least two distinct Hindi-Latin markers to avoid English FPs.
    if len(markers) >= 2 and len(_norm_bot_text(raw).split()) <= 12:
        return "hi-IN"
    return None


def resolve_language_action(
    text: str,
    *,
    current_language: str,
    fallback_languages: list[str] | None,
) -> dict[str, Any] | None:
    """Decide mid-call language handling (flow_improve edge #16).

    Returns None, or ``{action: switch|offer_agent, language?, reason}``.
    """
    signal = detect_language_signal(text)
    if not signal:
        return None
    current = (current_language or "en-IN").strip()
    fallbacks = [str(x).strip() for x in (fallback_languages or []) if str(x).strip()]
    if signal == "hi-IN" and signal != current and signal in fallbacks:
        return {"action": "switch", "language": "hi-IN", "reason": "hindi_detected"}
    if signal != current and signal not in fallbacks:
        return {
            "action": "offer_agent",
            "language": signal,
            "reason": "unsupported_language",
        }
    return None
