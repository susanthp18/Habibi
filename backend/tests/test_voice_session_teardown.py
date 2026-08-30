"""A call that ends must give everything back, even when cleanup misbehaves.

The failure this pins produced no error anywhere. A caller hung up, the session's
end-of-call bookkeeping hung on a background drain, and `worker.cancel()` — the
last step behind it — never ran. The session kept its STT, LLM and TTS
attachments and its concurrency slot for the life of the process.

Nothing logged. Nothing alerted. The only symptom was that *later* calls got
slower: setup went from 0.4s to 16.5s on the same process, which is past the
point where Twilio stops waiting. So the observable bug was "the customer
answers and hears silence", three layers away from the leak that caused it.
"""

from __future__ import annotations

import asyncio

import pytest

from voice import admission


@pytest.fixture(autouse=True)
def _clean_gate():
    admission.reset_for_tests()
    yield
    admission.reset_for_tests()


# --- the concurrency gate ---------------------------------------------------


def test_a_released_slot_is_given_back() -> None:
    token = admission.acquire(label="voice")
    assert admission.in_flight() == 1
    admission.release(token)
    assert admission.in_flight() == 0


def test_the_slot_context_manager_releases_through_an_exception() -> None:
    with pytest.raises(RuntimeError):
        with admission.slot(label="voice"):
            raise RuntimeError("pipeline exploded")
    assert admission.in_flight() == 0


def test_an_abandoned_slot_is_reclaimed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gate only ever counts down, so one leak is permanent without this.

    Capacity ratcheting toward zero has no error attached to it — calls just
    take longer and then stop being answered.
    """
    monkeypatch.setattr(admission, "max_slot_age", lambda: 0.05)
    admission.acquire(label="voice")  # token deliberately dropped: this is the leak
    assert admission.in_flight() == 1

    import time

    time.sleep(0.08)
    assert admission.reap_stale() == 1
    assert admission.in_flight() == 0


def test_a_live_call_is_never_reaped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cutting a real call short would be worse than the leak being guarded."""
    monkeypatch.setattr(admission, "max_slot_age", lambda: 3600.0)
    token = admission.acquire(label="voice")
    assert admission.reap_stale() == 0
    assert admission.in_flight() == 1
    admission.release(token)


def test_reaping_frees_capacity_for_a_real_caller(monkeypatch: pytest.MonkeyPatch) -> None:
    """The point of reaping: nobody is refused because of a phantom occupant."""
    monkeypatch.setattr(admission, "max_concurrent", lambda: 1)
    monkeypatch.setattr(admission, "max_slot_age", lambda: 0.05)
    admission.acquire(label="voice")  # leaked

    import time

    time.sleep(0.08)
    # Would raise AtCapacity if the abandoned slot still counted.
    token = admission.acquire(label="voice")
    assert token
    admission.release(token)


def test_reaping_can_be_disabled() -> None:
    """A zero ceiling is the escape hatch, and it must not reap anything."""
    import os

    os.environ["VOICE_MAX_SLOT_AGE_SECONDS"] = "0"
    try:
        admission.acquire(label="voice")
        assert admission.reap_stale() == 0
        assert admission.in_flight() == 1
    finally:
        os.environ.pop("VOICE_MAX_SLOT_AGE_SECONDS", None)


# --- teardown outlives bookkeeping ------------------------------------------


def test_teardown_runs_even_when_bookkeeping_hangs() -> None:
    """The shape of the fix, in miniature.

    `_finalize_call` now runs its records inside `asyncio.wait_for` and cancels
    the worker in a `finally`. What matters is the ordering guarantee: a
    bookkeeping step that never returns must not be able to keep the worker
    alive.
    """
    cancelled: list[str] = []

    async def _hanging_bookkeeping() -> None:
        await asyncio.Event().wait()  # never returns

    async def _finalize() -> None:
        try:
            await asyncio.wait_for(_hanging_bookkeeping(), timeout=0.05)
        except asyncio.TimeoutError:
            pass
        finally:
            cancelled.append("worker")

    asyncio.run(_finalize())
    assert cancelled == ["worker"], "the worker must be cancelled regardless"


def test_the_finalize_budget_is_finite_and_generous() -> None:
    """Finite is the property under test; the exact number is a judgement call.

    Too small and a slow-but-healthy finalize loses its CRM record. Too large
    and a hung one is indistinguishable from the unbounded version that caused
    the outage.
    """
    import voice.bot as bot

    assert 5.0 <= bot._FINALIZE_BUDGET_SECS <= 60.0


def test_finalize_bounds_its_bookkeeping_and_always_tears_down() -> None:
    """Read the source: the guarantee is structural, not incidental."""
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "async def _bookkeeping()" in src
    assert "asyncio.wait_for(_bookkeeping()" in src
    finally_at = src.index("        finally:\n", src.index("async def _bookkeeping()"))
    cancel_at = src.index("await worker.cancel()")
    assert cancel_at > finally_at, "worker.cancel() must sit in the finally, not before it"


# --- the per-call model cost ------------------------------------------------


def test_the_heavy_models_are_warmed_at_startup() -> None:
    """~1.8s of ONNX loading per call, paid inside Twilio's patience.

    They cannot be shared between sessions — both hold per-stream state, so two
    concurrent calls would analyse each other's audio — but the runtime and the
    page cache underneath them are shared, and building one of each at boot pays
    for that once.
    """
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot._warm_before_serving)
    assert "_warm_silero" in src
    assert "_warm_smart_turn" in src
    assert callable(bot._warm_silero)
    assert callable(bot._warm_smart_turn)


# --- the first call after a restart -----------------------------------------


def _run_bot_imports() -> set[str]:
    """Every module `run_bot` imports on entry, read from its own source."""
    import ast
    import inspect

    import voice.bot as bot

    tree = ast.parse(inspect.getsource(bot))
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_bot"
    )
    mods: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Import):
            mods.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module)
    return mods


def test_the_warm_list_covers_everything_run_bot_imports() -> None:
    """The first call must not pay an import bill nobody warmed.

    `run_bot` keeps its imports function-local on purpose — module scope would
    drag the whole pipeline runtime into anything that touches `voice.bot` — so
    the cost is real and has to be paid somewhere. Paid on the first call it was
    32.7s on this machine, against a carrier that waits a few seconds. That made
    the first call after every restart fail and the second succeed, which reads
    as flakiness rather than as a cold start.

    A new import added to `run_bot` and not to the warm list silently reopens
    that window, so this reads the source rather than trusting the list.
    """
    import sys

    import voice.bot as bot

    warmed = set(bot._RUN_BOT_MODULES)
    needed = {
        m
        for m in _run_bot_imports()
        # Standard library is already imported by the time anything runs.
        if m.split(".")[0] not in sys.stdlib_module_names
    }
    missing = needed - warmed
    assert not missing, (
        f"run_bot imports {sorted(missing)} but startup does not warm them — "
        "the first call after a restart pays for it while the caller waits"
    )


def test_warming_imports_is_best_effort() -> None:
    """A dependency that will not import must not stop the runner starting.

    That call pays for its own import and everyone else is still served, which
    is strictly better than a voice runner that refuses to boot.
    """
    import voice.bot as bot

    warmed = bot._warm_run_bot_imports()
    assert warmed >= len(bot._RUN_BOT_MODULES) - 2


# --- the greeting does not wait on the database -----------------------------


def test_the_crm_bind_runs_beside_the_greeting_not_in_front_of_it() -> None:
    """Six seconds of silence on an answered call, measured.

    Pipecat awaits `on_client_connected` before the FlowManager initialises, so
    every write in the CRM bind — the interaction row, the sink, the
    attempt→interaction join, the sandbox id patch — sat between the borrower
    answering and the bot's first word. On a loaded host that was 5.92s with the
    greeting built and waiting the whole time.

    None of it is needed to speak. The row is bookkeeping; the greeting is the
    product.
    """
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    assert "async def _bind_crm_session()" in src
    assert "asyncio.create_task(_bind_crm_session())" in src
    # The handler must not await the bind — that is the whole point.
    spawn = src.index("crm_bind_task = asyncio.create_task(_bind_crm_session())")
    assert "await _bind_crm_session()" not in src[spawn - 200 : spawn + 200]


def test_session_bound_is_emitted_only_once_the_ids_are_real() -> None:
    """Firing it on the connect path would deep-link the studio to nothing."""
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    body = src[src.index("async def _bind_crm_session()") : src.index("crm_bind_task =")]
    assert "emitter.session_bound(" in body, (
        "session_bound belongs inside the bind, after interaction_id is set"
    )


def test_teardown_waits_for_the_bind_it_might_have_overtaken() -> None:
    """A short call can reach teardown before the bind finishes.

    Without the wait, the completion record is filed against an interaction id
    that does not exist yet and `crm_sink` drops it — the "interaction_id unset"
    line that has been in these logs all along.
    """
    import inspect

    import voice.bot as bot

    src = inspect.getsource(bot.run_bot)
    book = src[src.index("async def _bookkeeping()") :]
    assert "_crm_bind_task" in book
    assert "wait_for" in book, "bounded, like every other step in teardown"
