"""Bot turn + WhatsApp outbound worker — SKIP LOCKED queues.

Usage (from backend/):
  .venv/Scripts/python -m bot_worker
  .venv/Scripts/python -m bot_worker --once
  .venv/Scripts/python -m bot_worker --drain

Drains:
  1) whatsapp_outbound_jobs (agent sends — always on)
  2) bot_turn_jobs (bot replies — gated by BOT_RUNTIME_ENABLED)
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import time

os.environ.setdefault("DB_PROCESS_ROLE", "bot_worker")

from env_loader import load_env

load_env()

import bot_jobs
import db
import whatsapp_outbound

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("bot_worker")


# Outbound is latency-sensitive so it wins most iterations, but every Nth
# iteration checks bot turns first. Without this, a sustained outbound backlog
# starves bot_turn_jobs indefinitely — customers get no bot reply at all while
# agent sends drain.
BOT_PRIORITY_EVERY = 4
_iteration = 0


def process_one_any() -> bool:
    """Prefer agent outbound (latency-sensitive UI), with a fair share for bot turns."""
    global _iteration

    _iteration += 1
    bot_enabled = bot_jobs.bot_runtime_enabled()
    bot_first = bot_enabled and _iteration % BOT_PRIORITY_EVERY == 0

    if bot_first and bot_jobs.process_one(db.engine):
        return True
    if whatsapp_outbound.process_one(db.engine):
        return True
    if bot_enabled and not bot_first:
        return bot_jobs.process_one(db.engine)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="WhatsApp bot turn + outbound worker (SKIP LOCKED)")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--drain", action="store_true", help="Drain queues then exit")
    parser.add_argument("--poll", type=float, default=1.5, help="Idle poll seconds")
    parser.add_argument(
        "--drain-limit",
        type=int,
        default=100,
        help="Max jobs to process in --drain mode",
    )
    args = parser.parse_args()

    if not bot_jobs.bot_runtime_enabled():
        logger.warning(
            "BOT_RUNTIME_ENABLED is false — bot turns idle; agent WhatsApp outbound still processed"
        )

    if args.once:
        did = process_one_any()
        logger.info("processed=%s", did)
        return
    if args.drain:
        n = 0
        for _ in range(max(1, args.drain_limit)):
            if not process_one_any():
                break
            n += 1
        logger.info("drained=%s", n)
        return

    logger.info("bot_worker started poll=%.1fs env=%s", args.poll, bot_jobs.bot_environment())
    stop = False

    def _stop(*_args: object) -> None:
        nonlocal stop
        stop = True

    try:
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
    except (ValueError, OSError):
        pass

    while not stop:
        try:
            did = process_one_any()
        except Exception:
            logger.exception("process_one crashed — backing off")
            time.sleep(args.poll)
            continue
        if not did:
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
