"""Voice/text context stays bounded. Compaction never calls an LLM."""

from __future__ import annotations

from agent_core.compaction import RAW_LAST_N, bound_history, extractive_summary
from agent_core.turn import assemble_turn_messages


def test_extractive_summary_is_bounded() -> None:
    older = [{"role": "customer", "text": f"turn {i} " * 40} for i in range(30)]
    summary = extractive_summary(older)
    assert summary.startswith("Earlier turns:")
    assert summary.count("\n") <= 12


def test_bound_history_keeps_last_n() -> None:
    history = [{"role": "customer", "text": f"t{i}"} for i in range(20)]
    recent, summary = bound_history(history, last_n=8)
    assert len(recent) == 8
    assert recent[0]["text"] == "t12"
    assert summary and "t0" in summary


def test_fail_short_drops_oldest_when_over_char_budget() -> None:
    history = [{"role": "user", "content": "x" * 4000} for _ in range(5)]
    recent, _ = bound_history(history, last_n=8, max_chars=5000)
    assert len(recent) < 5
    assert sum(len(h["content"]) for h in recent) <= 5000


def test_twenty_turn_call_stays_inside_raw_window() -> None:
    history: list[dict] = []
    for i in range(20):
        history.append({"role": "customer", "text": f"customer {i} " * 15})
        history.append({"role": "bot", "text": f"agent {i} " * 15})
    assembled = assemble_turn_messages(
        prompt_template="You are a collections agent.",
        persona={},
        guardrails={},
        customer_text="can I pay next week",
        history=history,
    )
    spoken = [m for m in assembled["messages"] if m["role"] in {"user", "assistant"}]
    # last N raw + the current user turn
    assert len(spoken) <= RAW_LAST_N + 1
    summaries = [m for m in assembled["messages"] if "Prior turns" in (m.get("content") or "")]
    assert summaries, "older turns must ride the summary card, not the raw window"
