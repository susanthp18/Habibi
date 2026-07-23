"""KB index worker — claim queued kb_index_jobs with SKIP LOCKED.

Usage (from backend/):
  .venv/Scripts/python -m worker
  .venv/Scripts/python -m worker --once
"""

from __future__ import annotations

import argparse
import logging
import time

import db
from env_loader import load_env
from kb_ingest import drain_queue, process_one

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("kb_worker")


def main() -> None:
    load_env()
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
        did = process_one(db.engine)
        if not did:
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
