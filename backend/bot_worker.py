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
  9) offer follow-through: silence becomes a label after the grace
"""

from __future__ import annotations

import argparse
import logging
import os

os.environ.setdefault("DB_PROCESS_ROLE", "bot_worker")

from env_loader import load_env

load_env()

import azure_openai
import bot_jobs
import work_loop
import cadence
import call_closer
import campaigns
import db
import observability
import outbound
import outbound_pools
from voice import reaper
import payment_events
from agent_core.treatment import enact as treatment_enact
from agent_core.treatment import followthrough as treatment_followthrough
from agent_core.reco import followthrough as offer_followthrough
from agent_core.treatment import sweep as treatment_sweep
import promise_fulfillment
import webhooks_dispatch
import whatsapp_outbound

from agent_core.worker_roles import ROLES

observability.setup_logging()
logger = logging.getLogger("bot_worker")

import actor_context  # noqa: E402

_ROLE = "all"


# Outbound is latency-sensitive so it wins most iterations, but every Nth
# iteration checks bot turns first. Without this, a sustained outbound backlog
# starves bot_turn_jobs indefinitely — customers get no bot reply at all while
# agent sends drain.
BOT_PRIORITY_EVERY = 4
SETTLE_EVERY = 20
_iteration = 0


def _run_stage(queue: str, drain):
    """Run one drain. A poison row must not abort the rest of the tick."""
    if _ROLE != "all" and queue not in ROLES.get(_ROLE, frozenset()):
        return False
    try:
        return bool(drain())
    except Exception:
        logger.exception("queue=%s failed", queue)
        return False


def process_one_any() -> bool:
    """Prefer agent outbound (latency-sensitive UI), with a fair share for bot turns."""
    global _iteration

    _iteration += 1
    bot_enabled = bot_jobs.bot_runtime_enabled()
    bot_first = bot_enabled and _iteration % BOT_PRIORITY_EVERY == 0

    if _iteration % SETTLE_EVERY == 1:
        _run_stage("promise_settle", lambda: promise_fulfillment.settle_promises(db.engine))
        # Attempts whose carrier callback never arrived. They hold a slot in the
        # outbound fleet gate and would never reach the Closer, so a dropped
        # tunnel would quietly throttle dialling to zero over a day.
        _run_stage("outbound_stale", lambda: outbound.sweep_stale(db.engine))
        # Calls whose voice worker stopped heartbeating: the session, its
        # interaction and its attempt all sat live forever.
        _run_stage("voice_stale", lambda: reaper.reap_stale(db.engine, outbound.stale_after()))
        # Caller-ID health. Cheap (three UPDATEs over one tenant's numbers) and
        # on the same settle cadence, because a number's answer rate does not
        # move between iterations and rotating on a stale reading is the same
        # mistake as not rotating at all.
        _run_stage("number_pool_health", lambda: outbound_pools.sweep_pool_health(db.engine))

    if bot_first and _run_stage("bot_jobs", lambda: bot_jobs.process_one(db.engine)):
        return True
    if _run_stage("whatsapp_outbound", lambda: whatsapp_outbound.process_one(db.engine)):
        return True
    if _run_stage("promise_reminders", lambda: promise_fulfillment.process_one_reminder(db.engine)):
        return True
    if _run_stage("bounce_voice", lambda: payment_events.process_one_voice(db.engine)):
        return True
    # Post-call: turn one finished dial into one structured outcome. Ahead of
    # the treatment loops because it finishes work rather than generating it,
    # and because followthrough's attribution reads what it writes — closing a
    # call after the ladder has already re-decided the case would attribute the
    # next rung to the wrong attempt.
    if _run_stage("call_closer", lambda: call_closer.process_one(db.engine)):
        return True
    # A retry that is due. Ahead of the campaign runner on purpose: finishing a
    # case somebody is already halfway through beats starting a new one, and the
    # borrower waiting on the second attempt has already been rung once.
    if _run_stage("cadence", lambda: cadence.process_one(db.engine)):
        return True
    if _run_stage("campaigns", lambda: campaigns.process_one(db.engine)):
        return True
    # Treatment plans whose moment has arrived. Returns False immediately
    # outside TREATMENT_MODE=live, so a shadow deployment pays one env read per
    # iteration and touches nothing.
    if _run_stage("treatment_enact", lambda: treatment_enact.process_one(db.engine)):
        return True
    # Attribution and ladder re-decision. Runs in shadow too — labelling what
    # happened is not an intervention, and the counterfactuals are most of what
    # the shadow fortnight is for.
    if _run_stage("treatment_followthrough", lambda: treatment_followthrough.process_one(db.engine)):
        return True
    # The book sweep, last of the treatment loops on purpose. It is the only
    # one that generates work rather than finishing it, so a backlog of due
    # plans or unattributed outcomes must drain before more decisions are made
    # — otherwise a large book pushes the queue further behind every iteration.
    # Off unless TREATMENT_SWEEP is set.
    if _run_stage("treatment_sweep", lambda: treatment_sweep.process_one(db.engine)):
        return True
    # Outbound webhooks, below everything that talks to a customer. A tenant's
    # integration is allowed to be a few seconds behind; a borrower waiting on a
    # reply is not. It is above the fallback so a webhook backlog still drains
    # on an otherwise idle worker.
    if _run_stage("webhooks_dispatch", lambda: webhooks_dispatch.process_one(db.engine)):
        return True
    # The offer family's follow-through. Periodic rather than per-iteration: it
    # is a batch sweep over a fourteen-day grace, so running it every pass would
    # be a full scan per second to close nothing. W12 -- silence is a label, and
    # which one it is depends on whether the offer was ever delivered.
    if _iteration % SETTLE_EVERY == 1:
        _run_stage("offer_followthrough", lambda: offer_followthrough.process_one(db.engine))
    try:
        from agent_core.clerk import process_one as clerk_one, sweep_overdue

        if _iteration % SETTLE_EVERY == 1:
            _run_stage("clerk_overdue", sweep_overdue)
            try:
                from agent_core.canary import sweep_rollbacks
            except Exception:
                logger.exception("queue=%s failed", "canary")
            else:
                _run_stage("canary", sweep_rollbacks)
        if _run_stage("clerk", clerk_one):
            return True
    except Exception:
        logger.exception("queue=%s failed", "clerk")
    if bot_enabled and not bot_first:
        return _run_stage("bot_jobs", lambda: bot_jobs.process_one(db.engine))
    return False


#: Empty polls before the loop slows down. Twenty at the default 1.5 s is
#: half a minute of nothing; a quiet queue then costs one query every
#: ``IDLE_SLEEP_SECONDS`` instead of one every poll.
IDLE_TICKS_BEFORE_BACKOFF = 20
IDLE_SLEEP_SECONDS = 5.0


def idle_sleep(idle_ticks: int, poll: float) -> float:
    """How long to sleep after this many consecutive empty polls."""
    if idle_ticks >= IDLE_TICKS_BEFORE_BACKOFF:
        return max(poll, IDLE_SLEEP_SECONDS)
    return poll


def main() -> None:
    # Every audit row this process writes is a machine's, not the default
    # user's. Bound here, not at import: a test that imports the module must
    # not become a machine.
    actor_context.bind_service_actor("system")
    parser = argparse.ArgumentParser(description="WhatsApp bot turn + outbound worker (SKIP LOCKED)")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--drain", action="store_true", help="Drain queues then exit")
    parser.add_argument("--poll", type=float, default=1.5, help="Idle poll seconds")
    parser.add_argument(
        "--role",
        choices=("all", "messaging", "dialer", "treatment", "integration"),
        default=os.getenv("BOT_WORKER_ROLE") or "all",
        help="Role-scoped drain. all is the historical combined worker.",
    )
    parser.add_argument(
        "--drain-limit",
        type=int,
        default=100,
        help="Max jobs to process in --drain mode",
    )
    args = parser.parse_args()
    global _ROLE
    _ROLE = args.role

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
    observability.serve_metrics()

    def warm_while_idle(_ticks: int) -> None:
        # prewarm() is a no-op until PREWARM_IDLE_SECONDS have passed, so this
        # costs one tiny completion every few minutes and keeps the TLS
        # connection and the deployment hot for whenever the next customer
        # actually writes in.
        azure_openai.prewarm()

    work_loop.run(
        process_one_any, poll=args.poll, name="bot_worker", on_idle=warm_while_idle, sleep_for=idle_sleep
    )


if __name__ == "__main__":
    main()
