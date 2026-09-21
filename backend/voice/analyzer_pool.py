"""Warm spare VAD and Smart Turn analyzers, so a call does not build its own.

The problem
-----------
``bot.py`` records the measurement this module exists for::

    silero-vad   1374 ms -> 327 ms
    smart-turn    386 ms -> 215 ms

The left column is a cold build; the right is a rebuild once the boot warmer
has paid for the onnxruntime library, its thread pools, and the model files in
the page cache. The boot warmer removes the *cold* delta and leaves the warm
rebuild -- ~540 ms of it -- inside every call's setup window, synchronously on
the event loop, while the caller holds an open and silent line.

What this is not
----------------
Not a shared analyzer. ``bot.py`` is explicit and right: both carry per-stream
state, so two concurrent calls handed the same object would analyse each
other's audio. Nothing here is ever given to two calls.

What it is
----------
A spare. One already-built analyzer per distinct tuning, handed to exactly one
call and immediately replaced in the background. The call gets an object with
the same class and the same parameters it would have constructed itself -- only
the moment of construction moved, from inside the caller's silence to before
they dialled.

Keyed on the parameters, not on the bot: two deployments with identical VAD
tuning can share a queue of spares because the objects are indistinguishable,
and a deployment whose tuning differs by one field gets its own. A key that has
no spare builds inline, exactly as today, and seeds the pool for next time.

Bounded on purpose. A spare nobody takes is one idle ONNX session's worth of
memory, and a fleet with many distinct tunings would otherwise accumulate one
per tuning; ``_MAX_KEYS`` caps that and the least recently used key is dropped.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: At most one spare per key, and at most this many keys. Each entry is a live
#: ONNX session held by nobody, so this is a memory budget, not a throughput
#: one -- a fleet with many distinct tunings should not accumulate a session per
#: tuning in a process that is also carrying audio.
_MAX_KEYS = 6

#: Refills run here, never on the default executor. Every ``asyncio.to_thread``
#: in this process shares that one, and a 300 ms model build must not queue in
#: front of a live tool's CRM read.
_BUILDERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="voice-analyzer-warm")

_lock = threading.Lock()
_spares: "OrderedDict[tuple, Any]" = OrderedDict()
_pending: set[tuple] = set()


def enabled() -> bool:
    """Off restores today's behaviour exactly: build inline, per call."""
    from voice import config as voice_config

    return voice_config.voice_analyzer_pool()


def take(key: tuple, build: Callable[[], Any]) -> Any:
    """The warm spare for ``key``, or a freshly built one; refill in background.

    ``build`` must be a zero-argument callable that constructs the analyzer for
    exactly this key -- the key is the cache's identity claim, so a builder that
    reads anything not in the key will hand a later call the wrong parameters.
    """
    if not enabled():
        return build()

    spare = None
    with _lock:
        if key in _spares:
            spare = _spares.pop(key)

    _refill(key, build)

    if spare is not None:
        return spare
    # Miss: pay it here, exactly as before the pool existed. The refill above
    # means the next call with this tuning does not.
    return build()


def seed(key: tuple, build: Callable[[], Any]) -> None:
    """Populate a key at boot, where the build costs the operator and not a caller."""
    if enabled():
        _refill(key, build)


def _refill(key: tuple, build: Callable[[], Any]) -> None:
    with _lock:
        if key in _spares or key in _pending:
            return
        _pending.add(key)

    def _work() -> None:
        try:
            obj = build()
        except Exception:
            logger.warning("analyzer spare build failed for %s", key, exc_info=True)
            obj = None
        with _lock:
            _pending.discard(key)
            if obj is None:
                return
            _spares[key] = obj
            _spares.move_to_end(key)
            while len(_spares) > _MAX_KEYS:
                dropped, _ = _spares.popitem(last=False)
                logger.debug("analyzer spare evicted key=%s", dropped)

    try:
        _BUILDERS.submit(_work)
    except RuntimeError:
        # Interpreter shutdown. Nothing to warm for.
        with _lock:
            _pending.discard(key)


def vad_key(params: Any) -> tuple:
    """Every VAD field that changes the object's behaviour."""
    return (
        "vad",
        round(float(params.confidence), 4),
        round(float(params.start_secs), 4),
        round(float(params.stop_secs), 4),
        round(float(params.min_volume), 4),
    )


def turn_key(params: Any) -> tuple:
    """Every Smart Turn field that changes the object's behaviour."""
    return (
        "turn",
        round(float(params.stop_secs), 4),
        round(float(params.pre_speech_ms), 4),
        round(float(params.max_duration_secs), 4),
    )


def stats() -> dict[str, Any]:
    with _lock:
        return {"spares": len(_spares), "pending": len(_pending)}


def reset() -> None:
    """Drop every spare. For tests."""
    with _lock:
        _spares.clear()
        _pending.clear()
