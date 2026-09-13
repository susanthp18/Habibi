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


def test_every_breaker_call_lands_in_one_dependency_histogram() -> None:
    """The breaker is the seam every adapter entry point passes through, so
    latency and outcome are observed there once -- ok, error, ignored and
    rejected -- rather than at ten call sites."""
    import circuit_breaker
    import observability

    with circuit_breaker._breakers_lock:
        circuit_breaker._breakers.pop("ut_metric", None)
    b = circuit_breaker.CircuitBreaker("ut_metric", failure_threshold=1, reset_timeout_s=60)

    assert b.call(lambda: "x") == "x"
    with pytest.raises(RuntimeError):
        b.call(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(circuit_breaker.CircuitOpenError):
        b.call(lambda: "x")

    def _n(outcome: str) -> float:
        # Read the rendered exposition rather than a private counter attribute.
        from prometheus_client import generate_latest

        text = generate_latest(observability.REGISTRY).decode()
        line = next(
            (
                ln
                for ln in text.splitlines()
                if ln.startswith("dependency_call_duration_seconds_count")
                and 'dependency="ut_metric"' in ln
                and f'outcome="{outcome}"' in ln
            ),
            None,
        )
        return float(line.rsplit(" ", 1)[1]) if line else 0.0

    assert _n("ok") >= 1 and _n("error") >= 1 and _n("rejected") >= 1
