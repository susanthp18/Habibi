"""Both summarisers must refuse to editorialise (voice/bot.py, voice/memory.py).

Session VS-0D653BF9C3: pipecat's generic context summariser asserted the account
was unresolved while a get_account_position result saying otherwise was still in
the same context window, and the model repeated the summary. Two summarisers now
exist — the in-call one and the cross-call one in customer_memory — and both sit
next to authoritative facts, so both need the same discipline.

The cross-call one is enforced by a post-filter (tested in
tests/test_customer_memory.py). The in-call one cannot be post-filtered, because
pipecat owns that call, so its prompt is all there is — hence these assertions.
"""

from __future__ import annotations

from pipecat.utils.context.llm_context_summarization import (
    DEFAULT_SUMMARIZATION_PROMPT,
    LLMContextSummaryConfig,
)

import voice.bot as bot


def _configured() -> LLMContextSummaryConfig:
    return LLMContextSummaryConfig(
        target_context_tokens=4000,
        min_messages_after_summary=6,
        summarization_prompt=bot._CONTEXT_SUMMARY_PROMPT,
    )


def test_our_prompt_actually_replaces_pipecats_default() -> None:
    """`summary_prompt` (a property) is what the summariser reads.

    Setting the field is not enough on its own to prove anything — this asserts
    the resolved value, so a pipecat rename shows up here rather than silently
    reverting us to the generic prompt.
    """
    resolved = _configured().summary_prompt
    assert resolved == bot._CONTEXT_SUMMARY_PROMPT
    assert resolved != DEFAULT_SUMMARIZATION_PROMPT


def test_unset_prompt_falls_back_to_pipecats_default() -> None:
    """Control: proves the assertion above is testing something real."""
    bare = LLMContextSummaryConfig(target_context_tokens=4000, min_messages_after_summary=6)
    assert bare.summary_prompt == DEFAULT_SUMMARIZATION_PROMPT


def test_in_call_prompt_preserves_commitments_verbatim() -> None:
    p = bot._CONTEXT_SUMMARY_PROMPT.lower()
    assert "verbatim" in p
    for commitment in ("promise", "dispute", "callback", "document"):
        assert commitment in p, f"{commitment} not protected from summarisation"


def test_in_call_prompt_forbids_resolution_verdicts() -> None:
    """The exact failure mode of VS-0D653BF9C3."""
    p = bot._CONTEXT_SUMMARY_PROMPT.lower()
    assert "never state or imply" in p
    for verdict in ("resolved", "approved", "waived", "closed", "settled"):
        assert verdict in p, f"{verdict} not forbidden"


def test_in_call_prompt_defers_to_later_tool_results() -> None:
    """The specific ordering rule that would have prevented the incident."""
    assert "tool result wins" in bot._CONTEXT_SUMMARY_PROMPT.lower()


def test_in_call_prompt_forbids_restating_money() -> None:
    assert "never restate a balance" in bot._CONTEXT_SUMMARY_PROMPT.lower()


def test_both_summarisers_forbid_the_same_verdicts() -> None:
    """The two prompts must not drift apart on what counts as editorialising."""
    from voice import memory

    in_call = bot._CONTEXT_SUMMARY_PROMPT.lower()
    for word in memory._RESOLUTION_DENYLIST:
        if " " in word:
            continue  # multi-word entries are output-filter only
        assert word in in_call, f"in-call prompt does not forbid {word!r}"
