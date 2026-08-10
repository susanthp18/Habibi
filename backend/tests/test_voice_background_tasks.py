"""Per-session fire-and-forget task registry (voice/tools.py).

The registry used to be one process-global set drained by a no-argument
``drain_background_tasks()``. Under ``VOICE_EMBEDDED_HOST=true`` a single
process owns every concurrent call, so caller A hanging up cancelled caller
B's in-flight RTVI emits and B's Inspector silently stopped receiving
``flow.node`` breadcrumbs mid-call. These tests pin the session scoping.

Sync tests driving ``asyncio.run`` per the repo convention (no pytest-asyncio).
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from voice import tools as voice_tools


@pytest.fixture(autouse=True)
def _clean_registry():
    """Never let one test's buckets leak into the next."""
    with voice_tools._session_tasks_lock:
        voice_tools._session_tasks.clear()
    yield
    with voice_tools._session_tasks_lock:
        for bucket in voice_tools._session_tasks.values():
            for task in bucket:
                task.cancel()
        voice_tools._session_tasks.clear()


async def _sleep_forever() -> None:
    await asyncio.sleep(3600)


def test_draining_one_session_does_not_cancel_another() -> None:
    async def scenario() -> tuple[bool, bool]:
        a = voice_tools.spawn_session_task("VS-AAAAAAAAAA", _sleep_forever())
        b = voice_tools.spawn_session_task("VS-BBBBBBBBBB", _sleep_forever())
        await asyncio.sleep(0)  # let both tasks start
        await voice_tools.drain_background_tasks("VS-AAAAAAAAAA", timeout=0.01)
        # Sample inside the loop: asyncio.run() cancels every surviving task on
        # its way out, so reading .done() after it returns would report B as
        # cancelled no matter what the drain did.
        sampled = (a.done(), b.done())
        b.cancel()
        return sampled

    a_done, b_done = asyncio.run(scenario())

    assert a_done, "A's task should have been settled by A's own teardown"
    assert not b_done, "B's task must survive A's teardown"


def test_drain_settles_completed_work_without_cancelling() -> None:
    async def scenario() -> bool:
        ran = asyncio.Event()

        async def _quick() -> None:
            ran.set()

        voice_tools.spawn_session_task("VS-CCCCCCCCCC", _quick())
        await voice_tools.drain_background_tasks("VS-CCCCCCCCCC", timeout=1.0)
        return ran.is_set()

    assert asyncio.run(scenario()), "fast work must be awaited, not cancelled"


def test_release_drops_the_bucket() -> None:
    async def scenario() -> None:
        voice_tools.spawn_session_task("VS-DDDDDDDDDD", _sleep_forever())
        await voice_tools.drain_background_tasks("VS-DDDDDDDDDD", timeout=0.01)
        voice_tools.release_session_tasks("VS-DDDDDDDDDD")

    asyncio.run(scenario())

    with voice_tools._session_tasks_lock:
        assert "VS-DDDDDDDDDD" not in voice_tools._session_tasks


def test_drain_of_an_unknown_session_is_a_noop() -> None:
    """Teardown wraps this in try/except, but it must not need to."""
    asyncio.run(voice_tools.drain_background_tasks("VS-NEVERSEEN", timeout=0.01))


def test_completed_tasks_are_discarded_from_their_bucket() -> None:
    """Otherwise a long call accumulates one dead Task per node transition."""

    async def scenario() -> None:
        async def _quick() -> None:
            return None

        task = voice_tools.spawn_session_task("VS-EEEEEEEEEE", _quick())
        await task
        await asyncio.sleep(0)  # let the done-callback run

    asyncio.run(scenario())

    with voice_tools._session_tasks_lock:
        assert voice_tools._session_tasks.get("VS-EEEEEEEEEE") == set()


def test_drain_requires_an_explicit_session_id() -> None:
    """The bug was precisely that "no argument" meant "cancel everything"."""
    sig = inspect.signature(voice_tools.drain_background_tasks)
    assert sig.parameters["session_id"].default is inspect.Parameter.empty
