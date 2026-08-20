"""Rate limits for KB retrieve / suggestion refresh.

Counters live in Postgres, keyed by (bucket, tenant, minute), so the configured
limit is the limit for the *deployment* rather than per worker process: the
previous process-local deque let an N-replica rollout serve N× the intended
Azure embed spend and gave one noisy tenant the whole budget.

Postgres (already a hard dependency and already the queue broker) is used
rather than Redis so the API image needs no extra client. If the counter write
fails, the limiter degrades to a process-local window instead of failing the
request — a rate limiter must never be the reason a call drops.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque

from env_loader import load_env

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)

# Observability: throttling is invisible otherwise — a tenant hitting the cap
# looks identical to a quiet tenant in the request logs.
_throttle_counts: dict[str, int] = defaultdict(int)
_throttle_lock = threading.Lock()


class RateLimitExceeded(RuntimeError):
    pass


def _limit(name: str, default: int) -> int:
    load_env()
    raw = (os.getenv(name) or str(default)).strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def _bucket_limit(bucket: str) -> int:
    if bucket == "retrieve":
        return _limit("KB_RETRIEVE_MAX_PER_MIN", 60)
    if bucket == "inbox_suggestions":
        return _limit("KB_INBOX_SUGGEST_MAX_PER_MIN", 30)
    return 60


def _tenant_id() -> str:
    import db

    return db.current_tenant()


def throttle_metrics() -> dict[str, int]:
    """Per-key throttle counts since process start (surfaced by /metrics)."""
    with _throttle_lock:
        return dict(_throttle_counts)


def _record_throttle(key: str) -> None:
    with _throttle_lock:
        _throttle_counts[key] += 1
    logger.warning("kb_rate_limited key=%s", key)


def _check_shared(bucket: str, tenant_id: str, limit: int) -> bool | None:
    """Increment the shared counter. True=allowed, False=denied, None=unavailable."""
    try:
        import db
        from sqlalchemy import text

        with db.engine.begin() as conn:
            count = conn.execute(
                text(
                    """
                    INSERT INTO kb_rate_limit_counters (bucket, tenant_id, window_start, hits)
                    VALUES (:bucket, :tenant_id, date_trunc('minute', now()), 1)
                    ON CONFLICT (bucket, tenant_id, window_start) DO UPDATE SET
                      hits = kb_rate_limit_counters.hits + 1
                    RETURNING hits
                    """
                ),
                {"bucket": bucket, "tenant_id": tenant_id},
            ).scalar()
        return int(count or 0) <= limit
    except Exception:
        # Degrading to the per-process window multiplies the effective limit by
        # the worker count. That has to be visible in /metrics and in the log,
        # not a DEBUG line nobody has enabled.
        with _throttle_lock:
            _throttle_counts["shared_counter_unavailable"] += 1
        logger.warning(
            "shared rate-limit counter unavailable; degrading to per-process window",
            exc_info=True,
        )
        return None


def _check_local(key: str, limit: int) -> bool:
    now = time.monotonic()
    cutoff = now - 60.0
    with _lock:
        q = _hits[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


def check_rate(bucket: str, *, max_per_minute: int | None = None) -> None:
    """Raise RateLimitExceeded if bucket exceeded within the current minute."""
    # Floor at 1, matching _bucket_limit. A caller passing 0 (or a negative)
    # made `len(q) >= limit` true on an empty window, so every single request
    # was rejected — a "no limit configured" reading of 0 became a total block.
    limit = (
        max(1, int(max_per_minute)) if max_per_minute is not None else _bucket_limit(bucket)
    )
    tenant_id = _tenant_id()
    key = f"{bucket}:{tenant_id}"

    allowed = _check_shared(bucket, tenant_id, limit)
    if allowed is None:
        allowed = _check_local(key, limit)
    if not allowed:
        _record_throttle(key)
        raise RateLimitExceeded(f"rate_limited:{bucket}:{limit}/min")


def purge_expired_counters(older_than_minutes: int = 10) -> int:
    """Delete counter rows outside the retention window. Called by the worker."""
    try:
        import db
        from sqlalchemy import text

        with db.engine.begin() as conn:
            result = conn.execute(
                text(
                    """
                    DELETE FROM kb_rate_limit_counters
                    WHERE window_start < now() - CAST(:window AS interval)
                    """
                ),
                {"window": f"{max(1, int(older_than_minutes))} minutes"},
            )
        return result.rowcount or 0
    except Exception:
        logger.debug("rate-limit counter purge failed", exc_info=True)
        return 0
