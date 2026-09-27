"""The ml_worker process: ``python -m call_intel.worker``.

Builds queued evidence exports first (a person is waiting), then claims
call-intelligence jobs and runs each call's missing stages in order.
One call at a time per process (the models already use the CPUs given to
the container); scale by running more workers, the claim is SKIP LOCKED.
"""

from __future__ import annotations

import logging
import signal
import time

from env_utils import env_float

from call_intel import exports, inputs, jobs, qa, signals, stages

logger = logging.getLogger("call_intel.worker")

_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True


def process(job: dict) -> None:
    done = set(job["stages_done"] or [])
    call = inputs.load(job["interaction_id"])
    if call is None:
        jobs.finish(job["id"])  # the interaction was deleted
        return
    rules = inputs.rules()
    for stage in jobs.STAGES:
        if stage in done:
            continue
        started = time.monotonic()
        if stage == "pii":
            versions = stages.run_pii(call, rules)
        elif stage == "audio":
            versions = stages.run_audio(call)
        elif stage == "signals":
            versions = signals.run_signals(call)
        else:
            versions = qa.run_qa(call)
        jobs.stage_done(job["id"], stage, versions)
        logger.info("call_intel %s: %s in %.1fs", call.interaction_id, stage, time.monotonic() - started)
    jobs.finish(job["id"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    idle = env_float("CALL_INTEL_IDLE_S", 5.0)
    logger.info("call_intel worker started")
    while not _stop:
        try:
            # A person is waiting on an export; calls are background work.
            export = exports.claim()
            if export is not None:
                exports.run(export)
                continue
            claimed = jobs.claim(1)
        except Exception:
            # The database is down or restarting: wait, never exit the worker.
            logger.exception("call_intel: claim failed; retrying")
            time.sleep(idle)
            continue
        if not claimed:
            time.sleep(idle)
            continue
        for job in claimed:
            try:
                process(job)
            except Exception as exc:
                logger.exception("call_intel job %s (%s) failed", job["id"], job["interaction_id"])
                jobs.finish(job["id"], error=f"{type(exc).__name__}: {exc}", attempts=job["attempts"])


if __name__ == "__main__":
    main()
