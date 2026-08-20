"""Voice concurrency admission control.

The property under test is the one that did not exist before: a process that is
already serving its configured number of calls refuses the next one *cleanly*
instead of accepting it and degrading every call in flight.
"""

from __future__ import annotations

import asyncio

import pytest

from voice import admission


@pytest.fixture(autouse=True)
def _clean_admission():
    admission.reset_for_tests()
    yield
    admission.reset_for_tests()


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


def test_acquire_and_release_round_trip(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "3")
    assert admission.in_flight() == 0
    token = admission.acquire(label="t")
    assert admission.in_flight() == 1
    admission.release(token)
    assert admission.in_flight() == 0


def test_refuses_beyond_the_cap(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "2")
    a = admission.acquire()
    b = admission.acquire()
    with pytest.raises(admission.AtCapacity):
        admission.acquire()
    assert admission.in_flight() == 2
    admission.release(a)
    # A freed slot is immediately reusable.
    c = admission.acquire()
    admission.release(b)
    admission.release(c)
    assert admission.in_flight() == 0


def test_capacity_message_names_the_numbers(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    admission.acquire()
    with pytest.raises(admission.AtCapacity) as exc:
        admission.acquire()
    assert "1/1" in str(exc.value)


def test_zero_disables_the_gate(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "0")
    assert admission.enabled() is False
    tokens = [admission.acquire() for _ in range(50)]
    assert admission.in_flight() == 50
    for t in tokens:
        admission.release(t)


def test_limit_is_read_at_call_time(monkeypatch) -> None:
    """A redeploy changes the cap without a code change."""
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    a = admission.acquire()
    with pytest.raises(admission.AtCapacity):
        admission.acquire()
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "2")
    b = admission.acquire()
    admission.release(a)
    admission.release(b)


def test_malformed_limit_falls_back_to_default(monkeypatch) -> None:
    """A bad env value must not take the voice runtime down at import."""
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "not-a-number")
    assert admission.max_concurrent() == admission.DEFAULT_MAX_CONCURRENT_CALLS


# ---------------------------------------------------------------------------
# Release robustness — a leaked slot ratchets the cap down to zero
# ---------------------------------------------------------------------------


def test_double_release_is_harmless(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "2")
    token = admission.acquire()
    admission.release(token)
    admission.release(token)
    assert admission.in_flight() == 0


def test_release_of_none_is_harmless() -> None:
    admission.release(None)
    assert admission.in_flight() == 0


def test_slot_context_manager_releases_on_exception(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    with pytest.raises(ValueError):
        with admission.slot(label="boom"):
            raise ValueError("boom")
    assert admission.in_flight() == 0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_snapshot_reports_occupancy(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "4")
    a = admission.acquire()
    admission.acquire()
    snap = admission.snapshot()
    assert snap["enabled"] is True
    assert snap["maxConcurrentCalls"] == 4
    assert snap["activeCalls"] == 2
    assert snap["availableSlots"] == 2
    assert snap["admittedTotal"] == 2
    assert snap["rejectedTotal"] == 0
    admission.release(a)
    assert admission.snapshot()["activeCalls"] == 1


def test_snapshot_counts_rejections_and_high_water(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    admission.acquire()
    for _ in range(3):
        with pytest.raises(admission.AtCapacity):
            admission.acquire()
    snap = admission.snapshot()
    assert snap["rejectedTotal"] == 3
    assert snap["highWaterMark"] == 1


def test_has_capacity_tracks_the_gate(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    assert admission.has_capacity() is True
    token = admission.acquire()
    assert admission.has_capacity() is False
    admission.release(token)
    assert admission.has_capacity() is True


# ---------------------------------------------------------------------------
# Refusal path — the transport must actually be closed
# ---------------------------------------------------------------------------


class _FakeWebRTC:
    def __init__(self) -> None:
        self.disconnected = False

    async def disconnect(self) -> None:
        self.disconnected = True


class _FakeWebSocket:
    def __init__(self) -> None:
        self.closed_with: int | None = None

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


class _Args:
    def __init__(self, **kw) -> None:
        self.__dict__.update(kw)


def test_refuse_disconnects_a_webrtc_connection() -> None:
    conn = _FakeWebRTC()
    asyncio.run(admission.refuse(_Args(webrtc_connection=conn)))
    assert conn.disconnected is True


def test_refuse_closes_a_websocket_with_try_again_later() -> None:
    ws = _FakeWebSocket()
    asyncio.run(admission.refuse(_Args(websocket=ws)))
    assert ws.closed_with == 1013


def test_refuse_tolerates_an_unknown_transport() -> None:
    """Refusal must never raise — the call is already being dropped."""
    asyncio.run(admission.refuse(_Args()))


def test_refuse_tolerates_a_transport_that_raises() -> None:
    class _Broken:
        async def disconnect(self):
            raise RuntimeError("already gone")

    asyncio.run(admission.refuse(_Args(webrtc_connection=_Broken())))


# ---------------------------------------------------------------------------
# The gate is wired into the entry point both hosting modes share
# ---------------------------------------------------------------------------


def test_bot_refuses_and_does_not_build_a_pipeline(monkeypatch) -> None:
    """At capacity, voice.bot.bot must close the transport and return.

    Asserts on the real entry point rather than re-testing acquire(): the bug
    being locked shut is "the cap exists but nothing calls it".
    """
    from voice import bot as bot_mod

    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")
    admission.acquire()  # fill the only slot

    built = False

    async def _should_not_run(_runner_args):
        nonlocal built
        built = True

    monkeypatch.setattr(bot_mod, "_bot_session", _should_not_run)

    ws = _FakeWebSocket()
    asyncio.run(bot_mod.bot(_Args(websocket=ws)))

    assert built is False, "pipeline was built for a call that had no slot"
    assert ws.closed_with == 1013


def test_bot_releases_the_slot_when_the_session_ends(monkeypatch) -> None:
    from voice import bot as bot_mod

    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")

    async def _session(_runner_args):
        assert admission.in_flight() == 1

    monkeypatch.setattr(bot_mod, "_bot_session", _session)
    asyncio.run(bot_mod.bot(_Args(websocket=_FakeWebSocket())))
    assert admission.in_flight() == 0


def test_bot_releases_the_slot_when_the_session_raises(monkeypatch) -> None:
    """A crashed call must not permanently consume a slot."""
    from voice import bot as bot_mod

    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")

    async def _boom(_runner_args):
        raise RuntimeError("transport exploded")

    monkeypatch.setattr(bot_mod, "_bot_session", _boom)
    with pytest.raises(RuntimeError):
        asyncio.run(bot_mod.bot(_Args(websocket=_FakeWebSocket())))
    assert admission.in_flight() == 0


def test_bot_releases_the_slot_when_cancelled(monkeypatch) -> None:
    """Deploy drain cancels sessions; the cap must not ratchet down."""
    from voice import bot as bot_mod

    monkeypatch.setenv("VOICE_MAX_CONCURRENT_CALLS", "1")

    async def _hang(_runner_args):
        await asyncio.sleep(30)

    monkeypatch.setattr(bot_mod, "_bot_session", _hang)

    async def _scenario():
        task = asyncio.create_task(bot_mod.bot(_Args(websocket=_FakeWebSocket())))
        await asyncio.sleep(0.05)
        assert admission.in_flight() == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(_scenario())
    assert admission.in_flight() == 0
