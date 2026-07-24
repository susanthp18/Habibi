"""Simple in-process circuit breaker for external dependencies.

Bounds *failure* bursts (Azure / Meta / MinIO hard-down) the way the Azure
semaphore bounds *concurrency*. Open after N failures → fail fast for
``reset_timeout_s``, then half-open probe.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when the breaker is open — map to HTTP 503."""


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int | None = None,
        reset_timeout_s: float | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = max(
            1,
            failure_threshold
            if failure_threshold is not None
            else _env_int("CIRCUIT_FAILURE_THRESHOLD", 5),
        )
        self.reset_timeout_s = float(
            reset_timeout_s
            if reset_timeout_s is not None
            else max(5, _env_int("CIRCUIT_RESET_TIMEOUT_S", 60))
        )
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            state = "closed"
            if self._opened_at is not None:
                state = "half_open" if self._half_open else "open"
            return {
                "name": self.name,
                "state": state,
                "failures": self._failures,
                "threshold": self.failure_threshold,
                "resetTimeoutS": self.reset_timeout_s,
            }

    def _before_call(self) -> None:
        with self._lock:
            if self._opened_at is None:
                return
            elapsed = time.monotonic() - self._opened_at
            if elapsed < self.reset_timeout_s and not self._half_open:
                raise CircuitOpenError(f"circuit_open:{self.name}")
            # Probe: allow one call through.
            self._half_open = True

    def _on_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None
            self._half_open = False

    def _on_failure(self) -> None:
        with self._lock:
            self._failures += 1
            self._half_open = False
            if self._failures >= self.failure_threshold:
                if self._opened_at is None:
                    logger.warning(
                        "circuit OPEN name=%s failures=%s reset_s=%s",
                        self.name,
                        self._failures,
                        self.reset_timeout_s,
                    )
                self._opened_at = time.monotonic()

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        self._before_call()
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self._on_failure()
            raise
        self._on_success()
        return result


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(name: str) -> CircuitBreaker:
    with _breakers_lock:
        b = _breakers.get(name)
        if b is None:
            b = CircuitBreaker(name)
            _breakers[name] = b
        return b


def snapshots() -> list[dict[str, Any]]:
    with _breakers_lock:
        return [b.snapshot() for b in _breakers.values()]
