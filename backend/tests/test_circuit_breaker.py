"""Circuit breaker open / cooldown / half-open probe."""

from __future__ import annotations

import time

import pytest


def test_breaker_opens_after_n_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    import circuit_breaker

    with circuit_breaker._breakers_lock:
        circuit_breaker._breakers.pop("ut_open", None)

    b = circuit_breaker.CircuitBreaker(
        "ut_open", failure_threshold=3, reset_timeout_s=60
    )

    def _fail():
        raise RuntimeError("boom")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            b.call(_fail)

    with pytest.raises(circuit_breaker.CircuitOpenError, match="circuit_open:ut_open"):
        b.call(lambda: "ok")

    snap = b.snapshot()
    assert snap["state"] == "open"
    assert snap["failures"] >= 3


def test_breaker_closes_after_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    import circuit_breaker

    with circuit_breaker._breakers_lock:
        circuit_breaker._breakers.pop("ut_cooldown", None)

    b = circuit_breaker.CircuitBreaker(
        "ut_cooldown", failure_threshold=2, reset_timeout_s=0.05
    )

    def _fail():
        raise RuntimeError("boom")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            b.call(_fail)

    with pytest.raises(circuit_breaker.CircuitOpenError):
        b.call(lambda: "ok")

    time.sleep(0.08)
    assert b.call(lambda: "recovered") == "recovered"
    assert b.snapshot()["state"] == "closed"


def test_circuit_open_handler_returns_503() -> None:
    import asyncio

    import circuit_breaker
    import main as app_main

    resp = asyncio.run(
        app_main._circuit_open_handler(
            None,  # type: ignore[arg-type]
            circuit_breaker.CircuitOpenError("circuit_open:azure_openai"),
        )
    )
    assert resp.status_code == 503
    assert b"circuit_open" in resp.body
