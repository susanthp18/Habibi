"""Simple process-local rate limits for KB retrieve / suggestion refresh."""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from env_loader import load_env

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


class RateLimitExceeded(RuntimeError):
    pass


def _limit(name: str, default: int) -> int:
    load_env()
    raw = (os.getenv(name) or str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def check_rate(bucket: str, *, max_per_minute: int | None = None) -> None:
    """Raise RateLimitExceeded if bucket exceeded within the last 60s."""
    limit = max_per_minute
    if limit is None:
        if bucket == "retrieve":
            limit = _limit("KB_RETRIEVE_MAX_PER_MIN", 60)
        elif bucket == "inbox_suggestions":
            limit = _limit("KB_INBOX_SUGGEST_MAX_PER_MIN", 30)
        else:
            limit = 60

    now = time.monotonic()
    cutoff = now - 60.0
    with _lock:
        q = _hits[bucket]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            raise RateLimitExceeded(f"rate_limited:{bucket}:{limit}/min")
        q.append(now)
