"""Lexicon sentiment — shared across sandbox, WhatsApp, and voice."""

from __future__ import annotations

import re
from functools import lru_cache

# Abuse detection lives in agent_core.lexicon — one narrowed, word-boundary
# matched source shared with voice/safety.py, guardrails.py and bot_runtime.py.
# The copy that used to live here matched by bare substring, so "skill" scored
# as "kill", and "fucking"/"harassment" each tripped two lexicon entries and
# were penalised twice for one word.
#
# ABUSE_LEXICON is re-exported rather than moved: agent_core.sentiment is its
# documented import path and tests assert on it there.
from agent_core.lexicon import ABUSE_LEXICON, abuse_hits

__all__ = ["ABUSE_LEXICON", "estimate_sentiment", "sentiment_label"]

_POS = (
    "thanks",
    "thank you",
    "great",
    "wonderful",
    "yes",
    "please",
    "good",
    "happy",
    "ok",
    "okay",
    "sure",
    "appreciate",
    "helpful",
)
_NEG = (
    "angry",
    "ridiculous",
    "terrible",
    "hate",
    "never",
    "won't",
    "cannot",
    "can't",
    "difficult",
    "wrong",
    "court",
    "legal",
    "lawyer",
    "manager",
    # "no" is deliberately absent: it is the single most common word in a
    # cooperative collections call ("no problem", "no issue", "no, that's fine")
    # and scoring it negative dragged neutral calls toward the sentiment-drop
    # escalation threshold.
    "frustrated",
    "annoyed",
    "upset",
    "worst",
    "horrible",
    "useless",
    "scam",
)

@lru_cache(maxsize=512)
def _word_re(word: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(word)}\b")


def estimate_sentiment(text: str) -> float:
    raw = text or ""
    padded = f" {raw.lower()} "
    s = 0.0
    # Word-boundary match, not a suffix-punctuation enumeration: the old
    # `f"{w}," in padded` test scored "eyes," as the word "yes" and "shook," as
    # "ok", which moved a customer's sentiment on words they never said.
    for w in _POS:
        if _word_re(w).search(padded):
            s += 0.2
    for w in _NEG:
        if _word_re(w).search(padded):
            s -= 0.25
    # Word-boundary matched via the shared lexicon, and counted once per
    # distinct term: the old substring loop scored "fucking" twice (it contains
    # "fuck") and matched "kill" inside "skill".
    s -= 0.7 * abuse_hits(raw)
    if "!" in raw:
        s -= 0.15
    # ALL CAPS shouting on short messages.
    letters = [ch for ch in raw if ch.isalpha()]
    if len(letters) >= 6 and sum(1 for ch in letters if ch.isupper()) / len(letters) > 0.7:
        s -= 0.25
    return max(-1.0, min(1.0, round(s, 2)))


def sentiment_label(score: float) -> str:
    if score > 0.15:
        return "positive"
    if score < -0.15:
        return "negative"
    return "neutral"
