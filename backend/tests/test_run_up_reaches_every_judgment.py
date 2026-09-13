"""Every per-turn judgment sees the thread, not one sentence.

``analyze_turn`` and ``kb_plan.plan_retrieval`` both shipped taking a ``recent``
run-up that no text-channel caller supplied. Each therefore judged one sentence
in isolation, which is how a live WhatsApp thread (CV-SUSANTH-WA1, 2026-09-11)
failed three turns running:

    customer: i am looking for travel insurance
    bot:      You can consider Travel Protect360 ...
    customer: nono... better yourself tell me the benefits
              -> classified help_capabilities, retrieval planned as "catalog",
                 answered with a list of capabilities and a product name

Measured on the corpus that was live at the time, the benefits the customer was
asking for retrieve at 0.649-0.692 — the answer was always there. What was
missing was the four turns of context that say *benefits of what*.

These tests pin the wiring, not the model: that the run-up is built once, that
it reaches each consumer, and that the turn under test is not fed back in as
part of its own context.
"""

from __future__ import annotations

import inspect

import pytest

from agent_core.compaction import run_up, to_recent


# ---------------------------------------------------------------------------
# The projection
# ---------------------------------------------------------------------------


def test_chat_shape_projects_to_the_run_up_shape() -> None:
    """The text channel stores OpenAI chat rows; the analyser wants tuples."""
    history = [
        {"role": "user", "content": "do you have insurance products?"},
        {"role": "assistant", "content": "Yes — the Protect360 range."},
    ]
    assert to_recent(history) == [
        ("customer", "do you have insurance products?"),
        ("bot", "Yes — the Protect360 range."),
    ]


def test_sandbox_shape_projects_the_same_way() -> None:
    """Same function, the other of the four shapes in this codebase."""
    history = [
        {"role": "customer", "text": "what are the exclusions?"},
        {"role": "bot", "text": "Professional sport, self-inflicted injury..."},
    ]
    assert to_recent(history) == [
        ("customer", "what are the exclusions?"),
        ("bot", "Professional sport, self-inflicted injury..."),
    ]


@pytest.mark.parametrize("agent_role", ["assistant", "bot", "agent"])
def test_every_agent_spelling_is_not_the_customer(agent_role: str) -> None:
    """A human agent's message must not be read as something the caller said."""
    assert to_recent([{"role": agent_role, "content": "hi"}]) == [("bot", "hi")]


def test_blank_turns_are_dropped_not_rendered_as_empty_lines() -> None:
    history = [
        {"role": "user", "content": "  "},
        {"role": "user", "content": "hello"},
    ]
    assert to_recent(history) == [("customer", "hello")]


def test_the_window_is_bounded() -> None:
    history = [{"role": "user", "content": f"t{i}"} for i in range(40)]
    assert len(to_recent(history, last_n=6)) == 6
    assert to_recent(history, last_n=6)[0] == ("customer", "t34")


# ---------------------------------------------------------------------------
# The turn under test is not part of its own run-up
# ---------------------------------------------------------------------------


def test_the_turn_under_test_is_removed_from_its_own_run_up() -> None:
    """Text reads history from storage, so the latest turn is already in it.

    Voice avoids this by ordering — crm_sink snapshots the buffer before
    appending. Text has no such ordering and needs the check instead.
    """
    history = [
        {"role": "user", "content": "i am looking for travel insurance"},
        {"role": "assistant", "content": "You can consider Travel Protect360."},
        {"role": "user", "content": "tell me the benefits"},
    ]
    assert run_up(history, "tell me the benefits") == [
        ("customer", "i am looking for travel insurance"),
        ("bot", "You can consider Travel Protect360."),
    ]


def test_an_earlier_identical_message_is_still_run_up() -> None:
    """Only the trailing copy is the turn under test.

    A customer who sends "hi" twice has genuinely said it twice, and the second
    one repeating the first is exactly the signal the analyser reads.
    """
    history = [
        {"role": "user", "content": "hi"},
        {"role": "user", "content": "hi"},
    ]
    assert run_up(history, "hi") == [("customer", "hi")]


def test_a_bot_turn_at_the_end_is_never_stripped() -> None:
    history = [{"role": "assistant", "content": "tell me the benefits"}]
    assert run_up(history, "tell me the benefits") == [("bot", "tell me the benefits")]


# ---------------------------------------------------------------------------
# The wiring: every consumer is actually handed it
# ---------------------------------------------------------------------------
#
# Source inspection, following test_conversation_trace_regressions.py. There is
# no DB fixture that drives _handle_turn end to end, and the property worth
# pinning is structural anyway: the argument is passed at all.


def test_the_text_channel_classifies_with_the_thread() -> None:
    from tests.voice_tools_source import text_turn_source

    src = text_turn_source()
    assert "recent=turn_run_up," in src, (
        "analyze_turn on the text channel must be given the run-up — without it "
        "a follow-up is classified on one sentence"
    )
    assert "tool_ctx.recent = turn_run_up" in src, (
        "the tools resolve follow-ups against the same thread the classifier saw"
    )


def test_the_text_channel_fetches_the_thread_before_it_judges_the_turn() -> None:
    """Ordering is the whole bug: history used to load *after* classification."""
    from tests.voice_tools_source import text_turn_source

    src = text_turn_source()
    assert src.index("full_history = bot_conversation.message_history(") < src.index("understanding = analyze_turn("), (
        "the thread must be in hand before anything classifies the turn"
    )


def test_the_thread_is_fetched_once() -> None:
    """Three queries became one fetch plus the latest-row lookup.

    The product hint used to run its own `SELECT body FROM messages` and the
    prompt history another, so three reads of one table could disagree about
    what had been said.
    """
    from tests.voice_tools_source import text_turn_source

    src = text_turn_source()
    assert src.count("message_history(") == 1
    assert "FROM messages" not in src, (
        "message reads belong in the named helpers, not inline in the turn"
    )


def test_the_kb_tool_is_given_the_run_up() -> None:
    import bot_tools

    src = inspect.getsource(bot_tools._tool_search_knowledge_base)
    assert "recent=ctx.recent" in src


def test_sandbox_assembly_is_given_the_run_up() -> None:
    import agent_core.turn as turn_mod

    src = inspect.getsource(turn_mod.assemble_turn_messages)
    assert "recent=run_up(" in src


def test_the_sandbox_prefetch_is_given_the_run_up() -> None:
    import sandbox_runtime

    src = inspect.getsource(sandbox_runtime._start_enrichment)
    assert "_run_up_for_run(" in src


def test_the_intent_label_no_longer_outranks_the_customer() -> None:
    """A wrong label must degrade, not derail.

    The block used to be headed "highest priority" and to instruct the model to
    recite its capabilities whenever the turn was classified help_capabilities —
    which it duly did at a customer asking, for the second time, to be told the
    benefits of a product.
    """
    import bot_runtime

    block = bot_runtime._dialog_control_block(
        intent="help_capabilities",
        customer_text="nope i want to see the benefits.",
        disclosed_recording=False,
    )
    assert "highest priority" not in block
    assert "a hint, not an instruction" in block
    assert "do not reply with a list of capabilities instead" in block
    # The thread is for resolving what was meant, not for answering old asks.
    assert "REFERS to" in block
