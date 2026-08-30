"""Key pooling: rotation, retirement, and the boundary between them.

The pool existed and was exercised by hand, which is how three providers ended
up holding pools they could never rotate. These tests pin the two behaviours
that are easy to get subtly wrong and impossible to notice in a demo:

* a key fault rotates and the call still succeeds;
* a *request* fault does not rotate, so one bad payload cannot burn the pool.
"""

from __future__ import annotations

import pytest

from agent_core.providers import pool as pool_mod


@pytest.fixture(autouse=True)
def _clean_pools():
    pool_mod.reset_pools()
    yield
    pool_mod.reset_pools()


def _pool(n: int, **kw) -> pool_mod.KeyPool:
    return pool_mod.KeyPool("test", [f"k{i}" for i in range(n)], **kw)


# ------------------------------------------------------------------ stickiness


def test_session_keeps_its_key_across_calls():
    """Rotation is per session, never per request — a mid-turn key swap is an
    audible seam, which is the whole reason stickiness exists."""
    p = _pool(3)
    first = p.acquire("sess-a")
    assert [p.acquire("sess-a") for _ in range(5)] == [first] * 5


def test_retiring_a_key_moves_its_sessions_off_it():
    p = _pool(2)
    held = p.acquire("sess-a")
    p.retire(held, reason="429")
    assert p.acquire("sess-a") != held


def test_release_drops_the_binding():
    p = _pool(2)
    p.acquire("sess-a")
    assert p.stats().sessions_bound == 1
    p.release("sess-a")
    assert p.stats().sessions_bound == 0


# -------------------------------------------------------------------- rotation


def test_call_with_rotation_retries_past_a_spent_key(monkeypatch):
    p = _pool(3)
    monkeypatch.setitem(pool_mod._POOLS, "test", p)
    seen: list[str] = []

    def fn(key: str) -> str:
        seen.append(key)
        if len(seen) < 3:
            raise pool_mod.KeyRejected("429 quota", status=429)
        return "audio"

    assert pool_mod.call_with_rotation("test", fn) == "audio"
    assert len(set(seen)) == 3, "each attempt must use a different key"
    assert p.stats().retired == 2


def test_call_with_rotation_gives_up_after_one_pass(monkeypatch):
    """A fully spent pool costs one attempt per key, not an unbounded retry.

    The binding layer answers NoKeysAvailable by failing over to the next
    provider, so spinning here would just delay that.
    """
    p = _pool(3)
    monkeypatch.setitem(pool_mod._POOLS, "test", p)
    calls = 0

    def fn(_key: str) -> str:
        nonlocal calls
        calls += 1
        raise pool_mod.KeyRejected("429 quota", status=429)

    with pytest.raises(pool_mod.NoKeysAvailable) as exc:
        pool_mod.call_with_rotation("test", fn)
    assert calls == 3
    assert "429 quota" in str(exc.value), "the last reason must survive"


def test_a_request_error_does_not_burn_the_pool(monkeypatch):
    """A 400 is our payload, not the credential. Every key would refuse it
    identically, so rotating would retire a healthy pool to learn nothing."""
    p = _pool(3)
    monkeypatch.setitem(pool_mod._POOLS, "test", p)

    def fn(_key: str) -> str:
        raise ValueError("malformed request")

    with pytest.raises(ValueError):
        pool_mod.call_with_rotation("test", fn)
    assert p.stats().retired == 0
    assert p.stats().available == 3


@pytest.mark.parametrize("status", sorted(pool_mod.KEY_FAULT_STATUSES))
def test_key_fault_statuses_are_recognised(status):
    assert pool_mod.is_key_fault(status)
    assert pool_mod.reason_for_status(status)


@pytest.mark.parametrize("status", [400, 404, 422, 500, 503])
def test_request_statuses_are_not_key_faults(status):
    assert not pool_mod.is_key_fault(status)


# ------------------------------------------------------------------- cooldown


def test_multi_key_pool_retires_permanently():
    """Free-tier quota is monthly; re-probing spends latency to relearn it."""
    assert pool_mod._default_cooldown(5) is None


def test_single_key_pool_gets_a_cooldown():
    """Retiring the only key is not rotation, it is switching the provider off
    for the life of the process. A bounded window recovers by itself."""
    assert pool_mod._default_cooldown(1) == pool_mod.DEFAULT_SINGLE_KEY_COOLDOWN_S


def test_cooldown_env_override(monkeypatch):
    monkeypatch.setenv("TEST_POOL_COOLDOWN_S", "30")
    assert pool_mod._read_cooldown("TEST", 5) == 30.0
    # <= 0 is the explicit way to ask for permanent retirement.
    monkeypatch.setenv("TEST_POOL_COOLDOWN_S", "0")
    assert pool_mod._read_cooldown("TEST", 1) is None
    monkeypatch.setenv("TEST_POOL_COOLDOWN_S", "not-a-number")
    assert pool_mod._read_cooldown("TEST", 1) == pool_mod.DEFAULT_SINGLE_KEY_COOLDOWN_S


def test_cooldown_expiry_returns_the_key(monkeypatch):
    p = _pool(1, cooldown_s=60.0)
    monkeypatch.setitem(pool_mod._POOLS, "test", p)
    key = p.acquire("s")
    p.retire(key, reason="429")
    assert p.stats().available == 0

    clock = [0.0]
    monkeypatch.setattr(pool_mod.time, "monotonic", lambda: clock[0])
    p._keys[0].retired_until = 60.0
    clock[0] = 61.0
    assert p.stats().available == 1


# --------------------------------------------------------------------- config


def test_dedup_keeps_the_pool_honest():
    """Pasting the same key twice must not double the apparent quota."""
    p = pool_mod.KeyPool("test", pool_mod._parse_keys("a, b ,a,, b "))
    assert len(p) == 2


def test_empty_pool_raises_rather_than_returning_nothing():
    with pytest.raises(pool_mod.NoKeysAvailable):
        pool_mod.KeyPool("test", []).acquire()


def test_release_session_clears_every_pool(monkeypatch):
    a, b = _pool(2), _pool(2)
    monkeypatch.setitem(pool_mod._POOLS, "a", a)
    monkeypatch.setitem(pool_mod._POOLS, "b", b)
    a.acquire("sess-x")
    b.acquire("sess-x")
    pool_mod.release_session("sess-x")
    assert a.stats().sessions_bound == 0
    assert b.stats().sessions_bound == 0
