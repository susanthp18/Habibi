"""FOR UPDATE serialisation in voice_session_store._pg_mutate.

``tests/test_production_hardening.py`` exercises mutate() semantics through the
*file* backend, so the Postgres ``SELECT ... FOR UPDATE`` at
voice_session_store.py:219 — the path that actually runs in the containers — has
had no coverage at all. Without that lock two concurrent Sandbox tuning deltas
both read the pre-merge payload and the second write silently drops the first.

Modelled on tests/test_job_claim.py, including its teardown ordering caveat:
liveness is asserted *before* any cleanup SQL, because a thread still inside its
transaction holds the row lock and the DELETE would block on it — turning a hung
thread into a hung test.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import text

import voice_session_store as store


@pytest.fixture
def pg_session():
    """A real Postgres-backed session row, or skip."""
    if store.backend() != "postgres":
        pytest.skip("voice_session_store is not on the postgres backend here")

    import db

    session_id = f"VS-{uuid.uuid4().hex[:10].upper()}"
    store.write(session_id, {"base": True})
    try:
        yield session_id
    finally:
        with db.engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {store._TABLE} WHERE id = :id"), {"id": session_id}
            )


def _run_concurrently(session_id: str, mutators) -> list[BaseException]:
    """Drive N mutate() calls through a barrier so they genuinely overlap."""
    barrier = threading.Barrier(len(mutators))
    errors: list[BaseException] = []

    def run(fn) -> None:
        try:
            barrier.wait(timeout=5)
            store.mutate(session_id, fn)
        except BaseException as exc:  # noqa: BLE001 — surfaced in the main thread
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(fn,)) for fn in mutators]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    # Liveness BEFORE the fixture's cleanup SQL runs — see module docstring.
    alive = [t for t in threads if t.is_alive()]
    if alive:
        raise AssertionError(f"{len(alive)} mutator thread(s) did not finish")
    return errors


def test_concurrent_mutations_do_not_lose_updates(pg_session: str) -> None:
    """Both deltas must survive. Without FOR UPDATE one silently vanishes."""

    def add_a(payload: dict) -> dict:
        return {**payload, "a": 1}

    def add_b(payload: dict) -> dict:
        return {**payload, "b": 2}

    errors = _run_concurrently(pg_session, [add_a, add_b])
    assert not errors, errors

    final = store.read(pg_session)
    assert final is not None
    assert final.get("a") == 1, "first writer's delta was dropped"
    assert final.get("b") == 2, "second writer's delta was dropped"
    assert final.get("base") is True, "pre-existing payload was clobbered"


def test_second_writer_observes_the_first(pg_session: str) -> None:
    """Read-modify-write must serialise, not both read the pre-image.

    Ten increments of one counter can only end at 10 if every reader saw the
    previous writer's committed value.
    """

    def bump(payload: dict) -> dict:
        return {**payload, "n": int(payload.get("n") or 0) + 1}

    errors = _run_concurrently(pg_session, [bump] * 10)
    assert not errors, errors

    final = store.read(pg_session)
    assert final is not None
    assert final.get("n") == 10, f"lost update: counter reached {final.get('n')}, not 10"


def test_mutating_a_missing_session_returns_none(pg_session: str) -> None:
    """Guard the other branch of the FOR UPDATE read."""
    assert store.mutate(f"VS-{uuid.uuid4().hex[:10].upper()}", lambda p: p) is None


def test_handler_exception_is_not_masked_as_a_store_outage(pg_session: str) -> None:
    """A caller's own ValueError must reach it unchanged.

    Reporting it as SessionStoreUnavailable would send the caller retrying a
    write that can never succeed.
    """

    def boom(_payload: dict) -> dict:
        raise ValueError("caller bug")

    with pytest.raises(ValueError, match="caller bug"):
        store.mutate(pg_session, boom)
