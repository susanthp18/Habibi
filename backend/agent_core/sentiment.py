"""Lexicon sentiment — shared across sandbox, WhatsApp, and voice."""

from __future__ import annotations

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
    "no",
    "frustrated",
    "annoyed",
    "upset",
    "worst",
    "horrible",
    "useless",
    "scam",
)
# Strong abuse / hostility — force a clearly negative score.
_ABUSE = (
    "stfu",
    "fuck",
    "fucking",
    "shit",
    "idiot",
    "stupid",
    "shut up",
    "asshole",
    "bastard",
    "damn you",
    "kill yourself",
    "harass",
)


def estimate_sentiment(text: str) -> float:
    raw = text or ""
    padded = f" {raw.lower()} "
    s = 0.0
    for w in _POS:
        if f" {w} " in padded or f"{w}," in padded or f"{w}." in padded:
            s += 0.2
    for w in _NEG:
        if f" {w} " in padded or f"{w}," in padded or f"{w}." in padded or f"{w}!" in padded:
            s -= 0.25
    for w in _ABUSE:
        if w in padded:
            s -= 0.7
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
