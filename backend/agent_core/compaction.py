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


#: Speaker strings that mean "not the customer". Matches the set
#: ``agent_core.understanding._format_context`` already normalises against, so a
#: projection built here renders the same way there.
_AGENT_SPEAKERS = frozenset({"bot", "agent", "assistant"})


def _turn_speaker(turn: dict[str, Any]) -> str:
    """``"bot"`` or ``"customer"``, from whichever key this shape uses.

    Four shapes reach this module and they disagree about both keys: the text
    channel carries OpenAI chat rows (``role``: ``user``/``assistant``), the
    sandbox carries ``role``: ``customer``/``bot``, voice carries tuples, and
    the summariser reads ``sender``. Normalising in one place is the point.
    """
    raw = str(turn.get("role") or turn.get("sender") or turn.get("speaker") or "").lower()
    return "bot" if raw in _AGENT_SPEAKERS else "customer"


def to_recent(
    history: list[dict[str, Any]] | None, *, last_n: int = RAW_LAST_N
) -> list[tuple[str, str]]:
    """Project a history window onto the run-up shape the per-turn judgments take.

    ``[(speaker, text), ...]``, oldest first — what
    :func:`agent_core.understanding.analyze_turn` and
    :func:`agent_core.tools.kb_plan.plan_retrieval` both accept as ``recent``,
    and what ``voice/crm_sink.py`` has always built by hand.

    This exists because those two functions were shipped taking a run-up that no
    text-channel caller ever supplied. Each judged one sentence in isolation: a
    customer saying "nope i want to see the benefits." was classified
    ``help_capabilities`` and routed to a product catalog, because nothing told
    either of them that the previous four turns were about travel insurance.

    Both consumers cap and clip the window themselves (``_CONTEXT_TURNS = 6``,
    240 chars a line), so this deliberately does not: it converts shape, it does
    not decide policy. ``last_n`` is a cheap upper bound so a long thread does
    not build a list that is immediately thrown away.
    """
    rows = [h for h in (history or []) if isinstance(h, dict)]
    out: list[tuple[str, str]] = []
    for turn in rows[-max(1, int(last_n)) :]:
        text = _turn_text(turn)
        if text:
            out.append((_turn_speaker(turn), text))
    return out


def run_up(
    history: list[dict[str, Any]] | None,
    customer_text: str,
    *,
    last_n: int = RAW_LAST_N,
) -> list[tuple[str, str]]:
    """The thread behind this turn, with the turn itself removed.

    Most histories already end with the message being classified, because it is
    a row in the same table everything else is read from. Passing it to the
    analyser twice makes the customer look like they are repeating themselves,
    and repetition is one of the signals the analyser reads — so a turn that
    said something once would score as insistence.

    Voice has always got this right by ordering (``crm_sink`` snapshots the
    buffer *before* appending the turn). Text and the sandbox read from storage
    and have no such ordering to rely on, so they need the check instead. One
    owner for it, because "is the last row the turn under test" is exactly the
    sort of question two implementations answer differently.
    """
    rows = [h for h in (history or []) if isinstance(h, dict)]
    tail = (customer_text or "").strip()
    if rows and tail and _turn_speaker(rows[-1]) == "customer" and _turn_text(rows[-1]) == tail:
        rows = rows[:-1]
    return to_recent(rows, last_n=last_n)


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
