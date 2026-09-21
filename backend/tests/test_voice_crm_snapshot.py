"""One CRM read per turn instead of one per tool (Phase 2.9).

``db.get_customer`` is not a row read: it fans out to consent, ledger, every
EMI installment, 25 interaction contracts, promises, disputes, documents and
notes, then validates a CustomerResponse -- holding one of the voice
container's five pooled connections for the whole fan-out. Three tools called
it separately on a normal "explain my dues" turn.
"""

from __future__ import annotations

import asyncio

import pytest

from voice import tool_state
from voice.tool_state import (
    ToolState,
    customer_snapshot,
    invalidate_customer_snapshot,
)


@pytest.fixture
def counted(monkeypatch):
    """Count reads without touching a database.

    Patches the one function, NOT ``sys.modules["db"]``. Swapping the whole
    module out leaks: anything that binds ``db`` while the stub is installed
    keeps the stub after monkeypatch restores the entry, and the rest of the
    session then fails on missing attributes -- which reads as a product defect
    somewhere else entirely.
    """
    import db

    calls: list[str] = []

    def fake_get_customer(cid: str):
        calls.append(cid)
        return {"customerId": cid, "outstanding": 1000 + len(calls)}

    monkeypatch.setattr(db, "get_customer", fake_get_customer)
    return calls


def test_the_turns_tools_share_one_read(counted):
    async def scenario():
        state = ToolState()
        return [await customer_snapshot(state, "C1") for _ in range(3)]

    rows = asyncio.run(scenario())
    assert counted == ["C1"], f"the fan-out ran {len(counted)} times"
    assert rows[0] == rows[1] == rows[2]


def test_the_turn_sees_one_balance_not_three(counted):
    """Three staggered reads could report three different balances inside one
    turn. One snapshot cannot -- this is more coherent, not less."""
    async def scenario():
        state = ToolState()
        a = await customer_snapshot(state, "C1")
        b = await customer_snapshot(state, "C1")
        return a["outstanding"], b["outstanding"]

    a, b = asyncio.run(scenario())
    assert a == b


def test_concurrent_tools_do_not_each_start_a_read(counted):
    """Single-flight: the model can emit several tool calls at once."""
    async def scenario():
        state = ToolState()
        return await asyncio.gather(*(customer_snapshot(state, "C1") for _ in range(4)))

    asyncio.run(scenario())
    assert counted == ["C1"], f"{len(counted)} concurrent reads started"


def test_a_write_drops_the_snapshot(counted):
    """A stale balance is the one thing this must never produce."""
    async def scenario():
        state = ToolState()
        await customer_snapshot(state, "C1")
        invalidate_customer_snapshot(state)
        await customer_snapshot(state, "C1")

    asyncio.run(scenario())
    assert counted == ["C1", "C1"], "the write did not force a re-read"


def test_the_snapshot_expires(counted, monkeypatch):
    monkeypatch.setattr(tool_state, "_SNAPSHOT_TTL_S", 0.0)

    async def scenario():
        state = ToolState()
        await customer_snapshot(state, "C1")
        await customer_snapshot(state, "C1")

    asyncio.run(scenario())
    assert counted == ["C1", "C1"], "an expired snapshot was served"


def test_a_different_customer_is_never_served_the_wrong_row(counted):
    async def scenario():
        state = ToolState()
        a = await customer_snapshot(state, "C1")
        b = await customer_snapshot(state, "C2")
        return a, b

    a, b = asyncio.run(scenario())
    assert a["customerId"] == "C1" and b["customerId"] == "C2"
    assert counted == ["C1", "C2"]


def test_the_snapshot_is_never_shared_between_calls(counted):
    """State is per-call; two calls must not see one another's customer."""
    async def scenario():
        one, two = ToolState(), ToolState()
        await customer_snapshot(one, "C1")
        await customer_snapshot(two, "C1")

    asyncio.run(scenario())
    assert counted == ["C1", "C1"], "a second call reused the first call's row"
