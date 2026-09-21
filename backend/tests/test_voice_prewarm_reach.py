"""Prewarming reach (Phase 2): the warmers that existed but never ran.

Two gaps, same shape -- a warm-up with exactly one call site that the running
topology did not go through, so the cost it existed to prevent was paid by a
caller instead. These assert what happens when the code runs, not where it
sits: a pure move should not break them.
"""

from __future__ import annotations

import asyncio

import pytest

from voice import bot, host, llm_pool


# ------------------------------------------------- the embedded host warms


def test_the_embedded_host_starts_the_warmers(monkeypatch):
    """_warm_before_serving had one call site, bot.py's __main__, and
    host._dispatch goes straight to bot(runner_args) -- so under
    VOICE_EMBEDDED_HOST the first caller paid the 32.7s import set inside
    their own silent line."""
    warmed = asyncio.Event()
    bridged: list[str] = []

    class _Runner:
        async def run(self, auto_end=False):
            await asyncio.sleep(3600)

    async def fake_warm():
        warmed.set()

    import voice.log_bridge as log_bridge

    monkeypatch.setattr(log_bridge, "install", lambda: bridged.append("installed"))
    monkeypatch.setattr(bot, "warm_before_serving_async", fake_warm)
    monkeypatch.setattr(host, "_runner", None, raising=False)
    monkeypatch.setattr(host, "_runner_task", None, raising=False)
    monkeypatch.setattr(host, "_warm_task", None, raising=False)

    class _WorkerRunner:
        def __init__(self, **_kw):
            pass

        async def run(self, auto_end=False):
            await asyncio.sleep(3600)

    import sys
    import types

    mod = types.ModuleType("pipecat.workers.runner")
    mod.WorkerRunner = _WorkerRunner
    monkeypatch.setitem(sys.modules, "pipecat.workers.runner", mod)

    async def scenario():
        await host.get_runner()
        await asyncio.wait_for(warmed.wait(), timeout=5)
        started_once = host._warm_task
        await host.get_runner()
        return started_once is host._warm_task

    try:
        same = asyncio.run(scenario())
    finally:
        for name in ("_runner", "_runner_task", "_warm_task"):
            setattr(host, name, None)

    assert bridged == ["installed"], "stdlib->loguru bridge is still __main__-only"
    assert same, "a second call started a second warm"


# ------------------------------------------- the async warmer is loop-safe


def test_the_async_warmer_runs_inside_a_live_loop(monkeypatch):
    """_warm_shared_llm_client uses asyncio.run, which raises inside a running
    loop -- and in a worker thread would open TLS on a loop closed immediately
    after, warming nothing the call actually uses."""
    calls: list[object] = []

    def fake_sync_warm(*, skip_shared_llm_client=False):
        calls.append(("sync", skip_shared_llm_client))

    async def fake_prewarm():
        calls.append(("client", True))
        return 12.0

    monkeypatch.setattr(bot, "_warm_before_serving", fake_sync_warm)
    monkeypatch.setattr(llm_pool, "prewarm_shared_client", fake_prewarm)

    asyncio.run(bot.warm_before_serving_async())

    assert ("sync", True) in calls, "the synchronous warmers did not run"
    assert ("client", True) in calls, "the shared client was never warmed on the live loop"


def test_skipping_the_client_warm_leaves_every_other_warmer_alone(monkeypatch):
    ran: list[str] = []
    for name in ("_warm_llm_service", "_warm_silero", "_warm_smart_turn"):
        monkeypatch.setattr(bot, name, lambda n=name: ran.append(n))
    monkeypatch.setattr(
        bot, "_warm_shared_llm_client", lambda: ran.append("_warm_shared_llm_client")
    )
    monkeypatch.setattr(bot, "_warm_run_bot_imports", lambda: 0)

    # Hermetic on purpose. _warm_before_serving also reaches Azure, pgvector and
    # -- the one that matters -- provider_persist.record_runtime, which WRITES
    # the provider registry. Left real, this test rewrote bindings that later
    # tests in the same session then failed to resolve ("pinned: no binding"),
    # which is a test poisoning shared state, not a product defect.
    import azure_openai
    import kb_retrieve
    from agent_core.providers import persist as provider_persist
    from agent_core.tools import kb_rerank

    monkeypatch.setattr(azure_openai, "prewarm", lambda **_kw: 0.0)
    monkeypatch.setattr(kb_retrieve, "prewarm", lambda: 0.0)
    monkeypatch.setattr(kb_rerank, "prewarm", lambda: False)
    monkeypatch.setattr(provider_persist, "record_runtime", lambda _report: None)

    bot._warm_before_serving(skip_shared_llm_client=True)

    assert "_warm_llm_service" in ran
    assert "_warm_silero" in ran
    assert "_warm_smart_turn" in ran
    assert "_warm_shared_llm_client" not in ran, (
        "the embedded host would open TLS on a throwaway loop"
    )


# ------------------------------------------------------------- keep-warm loop


def test_keep_warm_is_started_once_per_process():
    async def scenario():
        llm_pool._keep_warm_task = None
        try:
            await llm_pool.ensure_keep_warm()
            first = llm_pool._keep_warm_task
            await llm_pool.ensure_keep_warm()
            return first, llm_pool._keep_warm_task
        finally:
            if llm_pool._keep_warm_task is not None:
                llm_pool._keep_warm_task.cancel()
                llm_pool._keep_warm_task = None

    first, second = asyncio.run(scenario())
    assert first is second, "a second call started a second warm loop"


def test_keep_warm_sleeps_before_it_pings(monkeypatch):
    """The call that starts the loop must never pay for it. Warming on the call
    path just moves a real Azure completion into the greeting least able to
    afford it."""
    order: list[str] = []

    async def fake_sleep(_secs):
        order.append("sleep")
        raise asyncio.CancelledError

    async def fake_prewarm(*, force=False):
        order.append("ping")
        return 1.0

    monkeypatch.setattr(llm_pool.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm_pool, "prewarm_shared_client", fake_prewarm)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(llm_pool._keep_warm_loop())

    assert order == ["sleep"], f"pinged before sleeping: {order}"


def test_keep_warm_skips_the_tick_while_a_call_is_live(monkeypatch):
    """A keep-alive completion during a call competes with that call's own turn
    on the same shared client and the same breaker."""
    ticks = {"n": 0}
    pinged: list[str] = []

    async def fake_sleep(_secs):
        ticks["n"] += 1
        if ticks["n"] > 2:
            raise asyncio.CancelledError

    async def fake_prewarm(*, force=False):
        pinged.append("ping")
        return 1.0

    monkeypatch.setattr(llm_pool.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(llm_pool, "prewarm_shared_client", fake_prewarm)
    monkeypatch.setattr(llm_pool, "_calls_in_flight", lambda: 1)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(llm_pool._keep_warm_loop())

    assert pinged == [], "warmed while a call was in flight"


def test_unknown_call_count_is_treated_as_busy(monkeypatch):
    """Skipping a warm costs a slow turn; pinging mid-call costs the turn the
    caller is currently in."""
    import voice.admission as adm

    def boom():
        raise RuntimeError("admission unavailable")

    monkeypatch.setattr(adm, "snapshot", boom)
    assert llm_pool._calls_in_flight() == 1
