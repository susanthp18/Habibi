"""Bot turn + WhatsApp outbound worker — SKIP LOCKED queues.

Usage (from backend/):
  .venv/Scripts/python -m bot_worker
  .venv/Scripts/python -m bot_worker --once
  .venv/Scripts/python -m bot_worker --drain

Drains:
  1) whatsapp_outbound_jobs (agent sends — always on)
  2) bot_turn_jobs (bot replies — gated by BOT_RUNTIME_ENABLED)
  3) promise_reminders (PTP due/confirm) + settle_promises (due_today / auto-break)
  4) bounce last-resort voice (payment_events.next_voice_at)
  5) due treatment plans (TREATMENT_MODE=live only)
  6) treatment follow-through: outcome attribution + ladder re-decision
  7) the delinquent-book sweep (TREATMENT_SWEEP=1) — the corpus generator
  8) outbound webhook deliveries (webhook_deliveries.status='pending')
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

import azure_openai
import bot_jobs
import cadence
import call_closer
import campaigns
import db
import outbound
import payment_events
from agent_core.treatment import enact as treatment_enact
from agent_core.treatment import followthrough as treatment_followthrough
from agent_core.treatment import sweep as treatment_sweep
import promise_fulfillment
import webhooks_dispatch
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
SETTLE_EVERY = 20
_iteration = 0


def process_one_any() -> bool:
    """Prefer agent outbound (latency-sensitive UI), with a fair share for bot turns."""
    global _iteration

    _iteration += 1
    bot_enabled = bot_jobs.bot_runtime_enabled()
    bot_first = bot_enabled and _iteration % BOT_PRIORITY_EVERY == 0

    if _iteration % SETTLE_EVERY == 1:
        try:
            promise_fulfillment.settle_promises(db.engine)
        except Exception:
            logger.exception("settle_promises failed")
        # Attempts whose carrier callback never arrived. They hold a slot in the
        # outbound fleet gate and would never reach the Closer, so a dropped
        # tunnel would quietly throttle dialling to zero over a day.
        try:
            outbound.sweep_stale(db.engine)
        except Exception:
            logger.exception("outbound stale sweep failed")
        # Caller-ID health. Cheap (three UPDATEs over one tenant's numbers) and
        # on the same settle cadence, because a number's answer rate does not
        # move between iterations and rotating on a stale reading is the same
        # mistake as not rotating at all.
        try:
            outbound.sweep_pool_health(db.engine)
        except Exception:
            logger.exception("number pool health sweep failed")

    if bot_first and bot_jobs.process_one(db.engine):
        return True
    if whatsapp_outbound.process_one(db.engine):
        return True
    if promise_fulfillment.process_one_reminder(db.engine):
        return True
    if payment_events.process_one_voice(db.engine):
        return True
    # Post-call: turn one finished dial into one structured outcome. Ahead of
    # the treatment loops because it finishes work rather than generating it,
    # and because followthrough's attribution reads what it writes — closing a
    # call after the ladder has already re-decided the case would attribute the
    # next rung to the wrong attempt.
    try:
        if call_closer.process_one(db.engine):
            return True
    except Exception:
        logger.exception("call closer failed")
    # A retry that is due. Ahead of the campaign runner on purpose: finishing a
    # case somebody is already halfway through beats starting a new one, and the
    # borrower waiting on the second attempt has already been rung once.
    try:
        if cadence.process_one(db.engine):
            return True
    except Exception:
        logger.exception("cadence retry failed")
    try:
        if campaigns.process_one(db.engine):
            return True
    except Exception:
        logger.exception("campaign runner failed")
    # Treatment plans whose moment has arrived. Returns False immediately
    # outside TREATMENT_MODE=live, so a shadow deployment pays one env read per
    # iteration and touches nothing.
    if treatment_enact.process_one(db.engine):
        return True
    # Attribution and ladder re-decision. Runs in shadow too — labelling what
    # happened is not an intervention, and the counterfactuals are most of what
    # the shadow fortnight is for.
    if treatment_followthrough.process_one(db.engine):
        return True
    # The book sweep, last of the treatment loops on purpose. It is the only
    # one that generates work rather than finishing it, so a backlog of due
    # plans or unattributed outcomes must drain before more decisions are made
    # — otherwise a large book pushes the queue further behind every iteration.
    # Off unless TREATMENT_SWEEP is set.
    if treatment_sweep.process_one(db.engine):
        return True
    # Outbound webhooks, below everything that talks to a customer. A tenant's
    # integration is allowed to be a few seconds behind; a borrower waiting on a
    # reply is not. It is above the fallback so a webhook backlog still drains
    # on an otherwise idle worker.
    if webhooks_dispatch.process_one(db.engine):
        return True
    try:
        from agent_core.clerk import process_one as clerk_one, sweep_overdue

        if _iteration % SETTLE_EVERY == 1:
            sweep_overdue()
            try:
                from agent_core.canary import sweep_rollbacks

                sweep_rollbacks()
            except Exception:
                logger.exception("canary sweep failed")
        if clerk_one():
            return True
    except Exception:
        logger.exception("clerk drain failed")
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
    # This worker is idle almost all the time and wakes when a customer sends a
    # message, so without warming the pool its FIRST Azure call of every turn
    # pays cold start — measured at 11.2s for an intent classification that
    # takes 1.9s warm, and 13.1s for a KB lookup that takes 4.0s warm. The
    # customer waits behind all of it. Warm at start, then keep it warm while
    # idle (below).
    azure_openai.prewarm(force=True)
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
            # Idle tick. prewarm() is a no-op until PREWARM_IDLE_SECONDS have
            # passed, so this costs one tiny completion every few minutes and
            # keeps the TLS connection and the deployment hot for whenever the
            # next customer actually writes in.
            try:
                azure_openai.prewarm()
            except Exception:
                logger.debug("idle prewarm failed", exc_info=True)
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
