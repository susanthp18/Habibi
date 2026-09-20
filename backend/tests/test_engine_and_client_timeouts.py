"""WS7: every outbound dependency has a timeout and, where it is called from
many places, a breaker."""

from __future__ import annotations

import asyncio

import pytest


def test_the_engine_declares_every_timeout(db_tx) -> None:
    """A pool that waits forever, a session that holds its locks forever and
    a statement that queues behind a migration forever are three outages
    that look like a hang."""
    rows = {
        r[0]: r[1]
        for r in db_tx.execute(
            __import__("sqlalchemy").text(
                "SELECT name, setting FROM pg_settings WHERE name IN "
                "('statement_timeout','lock_timeout','idle_in_transaction_session_timeout')"
            )
        )
    }
    assert int(rows["statement_timeout"]) > 0
    assert int(rows["lock_timeout"]) > 0
    assert int(rows["idle_in_transaction_session_timeout"]) > 0
    import db_core

    assert db_core.engine.pool.timeout() == db_core.DB_POOL_TIMEOUT_S


def test_the_breaker_opens_on_async_failures_too() -> None:
    import circuit_breaker

    b = circuit_breaker.get_breaker("test_async_probe", failure_threshold=2, reset_timeout_s=60)

    async def boom():
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            asyncio.run(b.acall(boom))
    with pytest.raises(circuit_breaker.CircuitOpenError):
        asyncio.run(b.acall(boom))


def test_the_voice_llm_client_sits_behind_the_breaker() -> None:
    from voice import llm_pool

    client = llm_pool._build_client()
    assert client.chat.completions.create.__name__ == "guarded"


def test_voice_llm_timeouts_are_the_voice_profile() -> None:
    from voice import llm_pool

    timeout, retries = llm_pool._client_timeouts()
    assert retries == 1
    assert timeout.connect == 3.0
    assert timeout.read == 15.0
    assert timeout.write == 5.0
    assert timeout.pool == 2.0
