"""KB index worker — claim queued kb_index_jobs with SKIP LOCKED.

Also runs a once-per-day Azure TTS voice catalog sync (~02:30 UTC).

Usage (from backend/):
  .venv/Scripts/python -m worker
  .venv/Scripts/python -m worker --once
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from datetime import datetime, timezone

# Longer statement timeout than the API process (must set before importing db).
os.environ.setdefault("DB_PROCESS_ROLE", "worker")

from env_loader import load_env

load_env()

import db
from kb_ingest import drain_queue, process_one

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("kb_worker")

_TTS_SYNC_HOUR_UTC = 2
_TTS_SYNC_MINUTE_UTC = 30
_last_tts_sync_day: str | None = None


def _maybe_sync_tts_catalog() -> None:
    """Time-gated daily catalog refresh (02:30 UTC)."""
    global _last_tts_sync_day
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    if _last_tts_sync_day == day_key:
        return
    if (now.hour, now.minute) < (_TTS_SYNC_HOUR_UTC, _TTS_SYNC_MINUTE_UTC):
        return
    try:
        from tts_catalog_sync import run_sync

        summary = run_sync(db.engine, source="azure")
        _last_tts_sync_day = day_key
        if summary.get("error"):
            logger.warning("daily tts catalog sync error: %s", summary["error"])
        else:
            logger.info(
                "daily tts catalog sync ok fetched=%s upserted=%s",
                summary.get("fetchedCount"),
                summary.get("upserted"),
            )
    except Exception:
        logger.exception("daily tts catalog sync failed")
        _last_tts_sync_day = day_key  # don't hammer on persistent failure


def main() -> None:
    parser = argparse.ArgumentParser(description="KB index worker (SKIP LOCKED)")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--drain", action="store_true", help="Drain queue then exit")
    parser.add_argument("--poll", type=float, default=2.0, help="Idle poll seconds")
    args = parser.parse_args()

    if args.once:
        did = process_one(db.engine)
        logger.info("processed=%s", did)
        return
    if args.drain:
        n = drain_queue(db.engine)
        logger.info("drained=%s", n)
        return

    logger.info("worker started poll=%.1fs", args.poll)
    while True:
        _maybe_sync_tts_catalog()
        did = process_one(db.engine)
        if not did:
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
