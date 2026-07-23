"""Bot turn worker — claim bot_turn_jobs with SKIP LOCKED + coalesce.

Usage (from backend/):
  .venv/Scripts/python -m bot_worker
  .venv/Scripts/python -m bot_worker --once
  .venv/Scripts/python -m bot_worker --drain
"""

from __future__ import annotations

import argparse
import logging
import time

import bot_jobs
import db
from env_loader import load_env

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("bot_worker")


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="WhatsApp bot turn worker (SKIP LOCKED)")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--drain", action="store_true", help="Drain queue then exit")
    parser.add_argument("--poll", type=float, default=1.5, help="Idle poll seconds")
    args = parser.parse_args()

    if not bot_jobs.bot_runtime_enabled():
        logger.warning("BOT_RUNTIME_ENABLED is false — worker will idle until enabled")

    if args.once:
        did = bot_jobs.process_one(db.engine)
        logger.info("processed=%s", did)
        return
    if args.drain:
        n = bot_jobs.drain_queue(db.engine)
        logger.info("drained=%s", n)
        return

    logger.info("bot_worker started poll=%.1fs env=%s", args.poll, bot_jobs.bot_environment())
    while True:
        try:
            did = bot_jobs.process_one(db.engine)
        except Exception:
            logger.exception("process_one crashed — backing off")
            time.sleep(args.poll)
            continue
        if not did:
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
