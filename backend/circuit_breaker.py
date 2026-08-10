"""Simple in-process circuit breaker for external dependencies.

Bounds *failure* bursts (Azure / Meta / MinIO hard-down) the way the Azure
semaphore bounds *concurrency*. Open after N failures → fail fast for
``reset_timeout_s``, then half-open probe.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, TypeVar

from env_utils import env_int as _env_int

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when the breaker is open — map to HTTP 503."""


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int | None = None,
        reset_timeout_s: float | None = None,
        failure_exceptions: tuple[type[BaseException], ...] | None = None,
        ignore_exceptions: tuple[type[BaseException], ...] | None = None,
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
        self.failure_exceptions = failure_exceptions
        self.ignore_exceptions = ignore_exceptions or ()
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open = False
        self._probe_admitted = False
        self._probe_admitted_at: float | None = None
        # Monotonic generation stamped on each admitted half-open probe. A probe
        # whose slot aged out can still return afterwards; without the stamp its
        # late verdict overwrote the *current* probe's state — closing the
        # circuit on a stale success, or freeing a slot still in use.
        self._probe_gen = 0

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

    def _before_call(self) -> int | None:
        """Admit the call. Returns the probe generation, or None if not a probe."""
        with self._lock:
            if self._opened_at is None:
                return None
            now = time.monotonic()
            elapsed = now - self._opened_at
            if elapsed < self.reset_timeout_s:
                raise CircuitOpenError(f"circuit_open:{self.name}")
            # Exactly one probe per reset window — but a probe that never
            # returns (hung socket, no client-side timeout) would otherwise hold
            # the slot forever and wedge the breaker open permanently. Age the
            # admission out after one reset window and let a fresh probe run.
            if self._probe_admitted:
                admitted_at = self._probe_admitted_at
                if admitted_at is not None and (now - admitted_at) < self.reset_timeout_s:
                    raise CircuitOpenError(f"circuit_open:{self.name}:probe_busy")
                logger.warning(
                    "circuit probe slot expired name=%s — admitting a new probe", self.name
                )
            self._half_open = True
            self._probe_admitted = True
            self._probe_admitted_at = now
            self._probe_gen += 1
            return self._probe_gen

    def _is_stale_probe(self, probe_id: int | None) -> bool:
        """True when ``probe_id`` belongs to a superseded probe generation."""
        return probe_id is not None and probe_id != self._probe_gen

    def _on_success(self, probe_id: int | None = None) -> None:
        with self._lock:
            if self._is_stale_probe(probe_id):
                logger.warning(
                    "circuit ignoring late probe success name=%s gen=%s current=%s",
                    self.name,
                    probe_id,
                    self._probe_gen,
                )
                return
            self._failures = 0
            self._opened_at = None
            self._half_open = False
            self._probe_admitted = False
            self._probe_admitted_at = None

    def _on_failure(self, probe_id: int | None = None) -> None:
        with self._lock:
            if self._is_stale_probe(probe_id):
                logger.warning(
                    "circuit ignoring late probe failure name=%s gen=%s current=%s",
                    self.name,
                    probe_id,
                    self._probe_gen,
                )
                return
            # Cap at the threshold: an open circuit taking sustained traffic
            # would otherwise count into the millions, which says nothing the
            # snapshot does not already say and just churns the counter.
            self._failures = min(self._failures + 1, self.failure_threshold)
            self._half_open = False
            self._probe_admitted = False
            self._probe_admitted_at = None
            if self._failures >= self.failure_threshold:
                if self._opened_at is None:
                    logger.warning(
                        "circuit OPEN name=%s failures=%s reset_s=%s",
                        self.name,
                        self._failures,
                        self.reset_timeout_s,
                    )
                self._opened_at = time.monotonic()

    def _release_probe(self, probe_id: int | None = None) -> None:
        """Give the half-open probe slot back without counting a failure.

        Without this, a half-open call that raises a non-counting exception
        leaves ``_probe_admitted`` set forever: every later call gets
        ``probe_busy`` and the breaker can never close again.
        """
        with self._lock:
            if self._is_stale_probe(probe_id):
                return
            self._half_open = False
            self._probe_admitted = False
            self._probe_admitted_at = None

    def call(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        probe_id = self._before_call()
        try:
            result = fn(*args, **kwargs)
        # NOTE: the default ignore_exceptions is an empty tuple, which matches
        # nothing — this clause is then a deliberate no-op, not dead code.
        except self.ignore_exceptions:
            self._release_probe(probe_id)
            raise
        except Exception as exc:
            if self.failure_exceptions is not None and not isinstance(exc, self.failure_exceptions):
                self._release_probe(probe_id)
                raise
            self._on_failure(probe_id)
            raise
        except BaseException:
            # KeyboardInterrupt / SystemExit / GeneratorExit: not a dependency
            # failure, but the probe slot must still be released.
            self._release_probe(probe_id)
            raise
        self._on_success(probe_id)
        return result


_breakers: dict[str, CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(
    name: str,
    *,
    failure_threshold: int | None = None,
    reset_timeout_s: float | None = None,
    failure_exceptions: tuple[type[BaseException], ...] | None = None,
    ignore_exceptions: tuple[type[BaseException], ...] | None = None,
) -> CircuitBreaker:
    """Fetch (or create) the named breaker.

    Per-dependency tuning is applied only on first creation — an already
    registered breaker keeps its configuration and live state so a later caller
    cannot silently reset another subsystem's thresholds.
    """
    with _breakers_lock:
        b = _breakers.get(name)
        if b is None:
            b = CircuitBreaker(
                name,
                failure_threshold=failure_threshold,
                reset_timeout_s=reset_timeout_s,
                failure_exceptions=failure_exceptions,
                ignore_exceptions=ignore_exceptions,
            )
            _breakers[name] = b
        return b


def snapshots() -> list[dict[str, Any]]:
    with _breakers_lock:
        return [b.snapshot() for b in _breakers.values()]
