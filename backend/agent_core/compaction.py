"""Bound voice/text context. Fail short. Never call an LLM on the mouth path.

Last N turns stay raw. Older turns collapse to a stored analysis-profile
summary (or an extractive stand-in when none exists yet). If the raw window
still blows the char budget, drop the oldest remaining raw turns.
"""

from __future__ import annotations

from typing import Any

RAW_LAST_N = 8
MAX_RAW_CHARS = 6000


def _turn_text(turn: dict[str, Any]) -> str:
    return str(turn.get("text") or turn.get("content") or "").strip()


def extractive_summary(turns: list[dict[str, Any]], *, max_lines: int = 12) -> str:
    """Deterministic stand-in so compaction does not wait on the analysis profile."""
    lines: list[str] = []
    for turn in turns:
        text = _turn_text(turn)
        if not text:
            continue
        role = str(turn.get("role") or turn.get("sender") or "turn")
        lines.append(f"{role}: {text[:240]}")
    if not lines:
        return ""
    clipped = lines[-max_lines:]
    return "Earlier turns:\n" + "\n".join(clipped)


def bound_history(
    history: list[dict[str, Any]] | None,
    *,
    last_n: int = RAW_LAST_N,
    prior_summary: str | None = None,
    max_chars: int = MAX_RAW_CHARS,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return (raw_window, summary_to_inject)."""
    hist = [h for h in (history or []) if isinstance(h, dict)]
    n = max(1, int(last_n))
    older = hist[:-n] if len(hist) > n else []
    recent = hist[-n:] if hist else []
    summary = (prior_summary or "").strip() or extractive_summary(older)
    while recent and sum(len(_turn_text(h)) for h in recent) > max_chars:
        recent = recent[1:]
    return recent, summary or None
