"""Prefix-keyed developer-block replacement (voice/context_edit.py).

Shared by the KB enricher and the CRM-card refresher. Both reach it after an
await, and both would corrupt the context in the same two ways if written
independently — hence one implementation and one set of tests.
"""

from __future__ import annotations

from voice.context_edit import (
    CRM_CARD_PREFIX,
    count_developer_blocks,
    replace_developer_block,
)

PREFIX = "VERIFIED CUSTOMER FACTS"


class _Ctx:
    """Minimal stand-in for LLMContext's get/set_messages pair."""

    def __init__(self, messages: list | None = None) -> None:
        self.messages = list(messages or [])

    def get(self) -> list:
        return self.messages

    def set(self, messages: list) -> None:
        self.messages = messages


def _card(text: str) -> dict[str, str]:
    return {"role": "developer", "content": f"{PREFIX}\n{text}"}


def test_replace_evicts_the_prior_card() -> None:
    ctx = _Ctx([_card("outstanding 1000"), {"role": "user", "content": "hi"}])

    assert replace_developer_block(
        ctx.get, ctx.set, prefix=PREFIX, message=_card("outstanding 500")
    )

    assert count_developer_blocks(ctx.messages, PREFIX) == 1
    block = next(m for m in ctx.messages if m["role"] == "developer")
    assert "outstanding 500" in block["content"], "kept the stale card"


def test_replace_evicts_every_prior_card_not_just_one() -> None:
    """Guard the pathological case a bug could already have created."""
    ctx = _Ctx([_card("a"), _card("b"), _card("c")])
    replace_developer_block(ctx.get, ctx.set, prefix=PREFIX, message=_card("d"))
    assert count_developer_blocks(ctx.messages, PREFIX) == 1


def test_insert_lands_before_the_latest_user_message() -> None:
    """So the model reads the facts as context for the turn it is answering."""
    ctx = _Ctx(
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "what do I owe"},
        ]
    )
    replace_developer_block(ctx.get, ctx.set, prefix=PREFIX, message=_card("x"))

    roles = [m["role"] for m in ctx.messages]
    assert roles == ["user", "assistant", "developer", "user"]


def test_replace_reads_the_context_at_call_time() -> None:
    """The exact bug the KB enricher documents.

    Callers reach this after an await. If the implementation closed over a
    snapshot instead of calling get_messages(), everything appended during the
    await — tool results, other injected cards — would be dropped.
    """
    ctx = _Ctx([_card("old")])
    # Simulate a message arriving during the caller's await.
    ctx.messages.append({"role": "assistant", "content": "tool result"})

    replace_developer_block(ctx.get, ctx.set, prefix=PREFIX, message=_card("new"))

    contents = [m.get("content") for m in ctx.messages]
    assert "tool result" in contents, "dropped a message appended during the await"


def test_non_dict_entries_survive() -> None:
    """Pipecat message objects share the list; probing .role would raise."""

    class _PipecatMessage:
        role = "assistant"

    obj = _PipecatMessage()
    ctx = _Ctx([obj, {"role": "user", "content": "hi"}])

    assert replace_developer_block(ctx.get, ctx.set, prefix=PREFIX, message=_card("x"))
    assert obj in ctx.messages


def test_other_developer_blocks_are_untouched() -> None:
    """The KB block and the CRM card must not evict each other."""
    kb = {"role": "developer", "content": "Relevant knowledge base passages ..."}
    ctx = _Ctx([kb, _card("old")])

    replace_developer_block(ctx.get, ctx.set, prefix=PREFIX, message=_card("new"))

    assert kb in ctx.messages
    assert count_developer_blocks(ctx.messages, PREFIX) == 1


def test_first_injection_with_no_prior_block_works() -> None:
    ctx = _Ctx([{"role": "user", "content": "hi"}])
    assert replace_developer_block(ctx.get, ctx.set, prefix=PREFIX, message=_card("x"))
    assert count_developer_blocks(ctx.messages, PREFIX) == 1


def test_never_raises_on_a_broken_context() -> None:
    """This runs on the audio path; an exception must not kill a live call."""

    def _boom() -> list:
        raise RuntimeError("context gone")

    assert (
        replace_developer_block(_boom, lambda _m: None, prefix=PREFIX, message=_card("x"))
        is False
    )


def test_prefix_constant_matches_the_real_card() -> None:
    """CRM_CARD_PREFIX must actually be the first line of crm_card()."""
    from agent_core.context import CallContext

    ctx = CallContext(
        channel="voice",
        session_id="VS-X",
        interaction_id=None,
        customer_id="C1",
        account_id=None,
        identity_verified=True,
    )
    assert ctx.crm_card().startswith(CRM_CARD_PREFIX)
