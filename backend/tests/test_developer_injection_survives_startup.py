"""A developer message injected on connect must reach the model.

VS-8C1B760F1B and VS-E6043500C0, both outbound mission calls::

    05:49:16.621  Client connected
    05:49:16.622  ERROR LLMUserAggregator#0 Trying to process
                  LLMMessagesAppendFrame#0 but StartFrame not received yet
    05:49:16.637  StartFrame#0 reached the end of the pipeline

``on_client_connected`` fires before ``StartFrame`` reaches the user
aggregator, and ``_inject_developer`` pushed the mission briefing *from* that
aggregator. Pipecat's ``push_frame`` on an unstarted processor logs and drops.
The briefing -- open promise, balance, "do NOT mention any product" -- never
appeared in a single LLM request, and the agent read nine insurance products to
a borrower on a mission that forbade offers.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("pipecat.frames.frames")

from pipecat.frames.frames import LLMMessagesAppendFrame  # noqa: E402

from voice.bot_handlers import make_developer_injectors  # noqa: E402


class _Worker:
    def __init__(self) -> None:
        self.frames: list[object] = []

    async def queue_frame(self, frame, direction=None) -> None:
        self.frames.append(frame)


class _UnstartedAggregator:
    async def push_frame(self, *_args, **_kwargs) -> None:
        raise AssertionError("pushed from a processor that may not have received StartFrame")


def _call() -> SimpleNamespace:
    call = SimpleNamespace(
        context=SimpleNamespace(get_messages=lambda: [], set_messages=lambda _m: None),
        user_aggregator=_UnstartedAggregator(),
    )
    make_developer_injectors(call)
    return call


def test_injection_is_queued_on_the_worker_behind_startframe() -> None:
    call = _call()
    call.worker = _Worker()  # built after the injectors, exactly as run_bot does
    briefing = {"role": "developer", "content": "OUTBOUND CALL — you placed this call."}

    asyncio.run(call._inject_developer([briefing]))

    assert len(call.worker.frames) == 1
    frame = call.worker.frames[0]
    assert isinstance(frame, LLMMessagesAppendFrame)
    assert frame.messages == [briefing]
    assert frame.run_llm is False, "a fact for the next turn must not trigger a reply"


def test_injecting_before_the_pipeline_exists_is_an_error_not_a_silent_drop() -> None:
    call = _call()
    with pytest.raises(RuntimeError):
        asyncio.run(call._inject_developer([{"role": "developer", "content": "x"}]))


def test_nothing_to_inject_queues_nothing() -> None:
    call = _call()
    call.worker = _Worker()
    asyncio.run(call._inject_developer([]))
    assert call.worker.frames == []
