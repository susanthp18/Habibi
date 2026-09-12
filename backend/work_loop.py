"""The one poll loop the workers run: a step, a poll interval, a clean stop.

worker.py and bot_worker.py each carried their own copy of the signal
handlers, the crash backoff and the idle sleep. One loop, and a worker is its
step function plus what it does while idle.
"""

from __future__ import annotations

import logging
import signal
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


def run(
    step: Callable[[], bool],
    *,
    poll: float,
    name: str,
    on_idle: Callable[[int], None] | None = None,
    sleep_for: Callable[[int, float], float] | None = None,
) -> None:
    """Call `step` until SIGTERM/SIGINT. `step` returns whether it did work;
    when it did not, `on_idle(idle_ticks)` runs and the loop sleeps `poll`
    seconds, or what `sleep_for(idle_ticks, poll)` says. A step that raises
    is logged and backed off by one poll, never fatal."""
    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    try:
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
    except (ValueError, OSError):
        pass

    idle_ticks = 0
    while not stop:
        try:
            did = step()
        except Exception:
            logger.exception("%s iteration crashed — backing off", name)
            time.sleep(poll)
            continue
        idle_ticks = 0 if did else idle_ticks + 1
        if not did:
            if on_idle is not None:
                try:
                    on_idle(idle_ticks)
                except Exception:
                    logger.debug("%s idle hook failed", name, exc_info=True)
            time.sleep(sleep_for(idle_ticks, poll) if sleep_for else poll)
