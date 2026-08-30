"""Concurrency admission control for live voice calls.

Before this, ``voice/host.py`` created one asyncio task per inbound call and
added it to a set. Call 1 and call 500 were treated identically: no cap, no
queue, no backpressure. With ``VOICE_EMBEDDED_HOST=true`` those tasks share the
event loop and the 5+5 connection pool with every CRM request in the process, so
the failure mode was not "calls degrade" but "the whole API degrades, and the
calls that caused it still get answered badly".

What this is
------------
A counted gate. A call takes a slot before the pipeline is built and returns it
when the session ends, and a call that cannot get a slot is refused *cleanly* —
Twilio hears busy TwiML, a browser gets its connection closed — rather than
being accepted into a process that cannot serve it.

Refusing a call is a worse outcome than serving it and a much better one than
degrading every call in flight. That is the whole trade, and it is why the
default is deliberately conservative.

Scope, stated plainly
---------------------
The counter is **per process**. Each voice worker caps itself; there is no
deployment-wide total. For the single-worker compose stack that is the same
number, and for a multi-worker rollout it is ``workers x cap``. A true fleet
limit needs a shared counter (Redis is already a dependency for
:mod:`voice.mesh_bus`) and is deliberately not attempted here — a distributed
limiter that is subtly wrong is worse than a local one that is exactly right.

Thread safety
-------------
Acquire/release run on the event loop; :func:`snapshot` is read from ``/ready``
and ``/voice/status``, which are sync FastAPI routes and therefore run in the
threadpool. Hence a real lock rather than relying on loop affinity.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from env_utils import env_int

logger = logging.getLogger(__name__)

#: Chosen against the documented connection budget in ``docker-compose.yml``
#: (voice gets 3+2 connections) and the per-call Azure concurrency, not picked
#: for roundness. Raise it only together with the pool and the Azure semaphore.
DEFAULT_MAX_CONCURRENT_CALLS = 25


class AtCapacity(RuntimeError):
    """No slot available. Callers must refuse the call, not queue it here."""


_lock = threading.Lock()
_active: dict[str, tuple[str, float]] = {}
_rejected_total = 0
_admitted_total = 0
_high_water = 0


def max_concurrent() -> int:
    """Read at call time so a redeploy can change it without a code change.

    ``0`` or negative disables admission control entirely — an explicit escape
    hatch for a load test, not a supported production setting.
    """
    return env_int("VOICE_MAX_CONCURRENT_CALLS", DEFAULT_MAX_CONCURRENT_CALLS)


def enabled() -> bool:
    return max_concurrent() > 0


def max_slot_age() -> float:
    """How long a slot may be held before it is treated as abandoned.

    Well above any real call — the duration cap is 10 minutes — because this is
    a leak detector, not a call timer. Cutting a live call short would be a far
    worse bug than the one it guards against.
    """
    return float(env_int("VOICE_MAX_SLOT_AGE_SECONDS", 3600))


def reap_stale() -> int:
    """Reclaim slots whose session never returned them. Returns how many.

    ``bot()`` releases in a ``finally``, so this should never fire — and it did.
    A session whose teardown hung held its slot for the life of the process, and
    because the gate only ever counts down, the effective capacity ratcheted
    toward zero with no error anywhere: calls simply got slower and then stopped
    being answered.

    A counter that can only leak is a counter that will. This is the floor under
    it, and it is deliberately loud: every reclaim is a bug worth chasing, not
    routine housekeeping.
    """
    ceiling = max_slot_age()
    if ceiling <= 0:
        return 0
    now = time.monotonic()
    reaped: list[tuple[str, str, float]] = []
    with _lock:
        for tok, (label, started) in list(_active.items()):
            age = now - started
            if age > ceiling:
                del _active[tok]
                reaped.append((tok, label, age))
    for tok, label, age in reaped:
        logger.error(
            "voice admission reclaimed an abandoned %s slot after %.0fs (token=%s) — "
            "its session never released it; teardown is leaking",
            label, age, tok,
        )
        _count("voice_calls_slot_reaped")
    return len(reaped)


def acquire(*, label: str = "call") -> str:
    """Take a slot, or raise :class:`AtCapacity`.

    Returns an opaque token that must be handed to :func:`release`.
    """
    global _rejected_total, _admitted_total, _high_water

    limit = max_concurrent()
    token = uuid.uuid4().hex
    # Before refusing anyone, make sure the occupancy is real. Refusing a live
    # caller because of a slot nobody is using is the worst outcome available.
    reap_stale()
    with _lock:
        if limit > 0 and len(_active) >= limit:
            _rejected_total += 1
            in_flight = len(_active)
            logger.warning(
                "voice admission refused %s: %d/%d slots in use (rejected_total=%d)",
                label, in_flight, limit, _rejected_total,
            )
            _count("voice_calls_rejected")
            raise AtCapacity(f"voice_at_capacity:{in_flight}/{limit}")
        _active[token] = (label, time.monotonic())
        _admitted_total += 1
        if len(_active) > _high_water:
            _high_water = len(_active)
        in_flight = len(_active)
    _count("voice_calls_admitted")
    logger.info("voice admission granted %s: %d/%d slots in use", label, in_flight, limit)
    return token


def _count(metric: str) -> None:
    """Bump a metrics counter without making metrics a hard dependency.

    The voice worker imports this module before (and sometimes without) the API
    process's observability stack, and a missing metrics backend must never be
    the reason a call is not admitted.
    """
    try:
        import observability

        getattr(observability, metric).inc()
    except Exception:
        logger.debug("metric %s unavailable", metric, exc_info=True)


def release(token: str | None) -> None:
    """Return a slot. Safe to call twice, or with ``None``."""
    if not token:
        return
    with _lock:
        entry = _active.pop(token, None)
        remaining = len(_active)
    if entry is None:
        # Double release is a bug in the caller, not a reason to fail a teardown.
        logger.debug("voice admission release for unknown token %s", token)
        return
    label, started = entry
    logger.info(
        "voice admission released %s after %.1fs: %d slots in use",
        label, time.monotonic() - started, remaining,
    )


@contextmanager
def slot(*, label: str = "call") -> Iterator[str]:
    """Scope a slot to a block. Releases even if the body raises."""
    token = acquire(label=label)
    try:
        yield token
    finally:
        release(token)


def in_flight() -> int:
    with _lock:
        return len(_active)


def has_capacity() -> bool:
    """Non-reserving check — for the Twilio webhook, which answers before the
    media socket connects and so cannot hold a slot across the two requests.

    Inherently racy: capacity can vanish between this check and the socket
    arriving. That race costs one call the clean busy message and gives it the
    hard refusal in :func:`acquire` instead, which is the acceptable direction.
    """
    limit = max_concurrent()
    if limit <= 0:
        return True
    with _lock:
        return len(_active) < limit


def snapshot() -> dict[str, Any]:
    """Occupancy for ``/ready`` and ``/voice/status``. No side effects."""
    limit = max_concurrent()
    with _lock:
        active = len(_active)
        oldest = min((started for _label, started in _active.values()), default=None)
        return {
            "enabled": limit > 0,
            "maxConcurrentCalls": limit,
            "activeCalls": active,
            "availableSlots": max(0, limit - active) if limit > 0 else None,
            "highWaterMark": _high_water,
            "admittedTotal": _admitted_total,
            "rejectedTotal": _rejected_total,
            "longestCallSeconds": round(time.monotonic() - oldest, 1) if oldest else 0.0,
        }


async def refuse(runner_args: Any, *, label: str = "call") -> None:
    """Close a refused call's transport without building a pipeline.

    Best-effort and deliberately tolerant of a transport that does not expose
    the method we expect: the call is already being dropped, so a surprise here
    must not turn a clean refusal into an unhandled exception in the accept
    path.
    """
    connection = getattr(runner_args, "webrtc_connection", None)
    if connection is not None:
        try:
            await connection.disconnect()
        except Exception:
            logger.debug("refused %s: webrtc disconnect failed", label, exc_info=True)
        return

    websocket = getattr(runner_args, "websocket", None)
    if websocket is not None:
        try:
            # 1013 "try again later" is the close code for transient overload;
            # a generic 1000 would read to the client as a normal end of call.
            await websocket.close(code=1013)
        except Exception:
            logger.debug("refused %s: websocket close failed", label, exc_info=True)


def reset_for_tests() -> None:
    """Clear all state. Tests only — never call from application code."""
    global _rejected_total, _admitted_total, _high_water
    with _lock:
        _active.clear()
        _rejected_total = 0
        _admitted_total = 0
        _high_water = 0
