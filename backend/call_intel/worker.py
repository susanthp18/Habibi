"""The ml_worker process: ``python -m call_intel.worker``.

Builds queued evidence exports first (a person is waiting), then claims a
batch of call-intelligence jobs and runs it stage by stage: every call's PII
pass, then every call's audio, and so on. Only the stage's own models are
resident while it runs (``models.keep_only``), and each model loads once per
batch. The models already use the CPUs given to the container; scale by
running more workers, the claim is SKIP LOCKED.
"""

from __future__ import annotations

import logging
import signal
import time

from env_utils import env_float, env_int

from call_intel import exports, inputs, jobs, models, qa, signals, stages

logger = logging.getLogger("call_intel.worker")

_stop = False


def _handle_stop(*_):
    global _stop
    _stop = True


def _run_stage(stage: str, call, rules) -> dict:
    if stage == "pii":
        return stages.run_pii(call, rules)
    if stage == "audio":
        return stages.run_audio(call)
    if stage == "signals":
        return signals.run_signals(call)
    return qa.run_qa(call)


def _fail(job: dict, exc: Exception) -> None:
    logger.exception("call_intel job %s (%s) failed", job["id"], job["interaction_id"])
    jobs.finish(job["id"], error=f"{type(exc).__name__}: {exc}", attempts=job["attempts"])


def process_batch(batch: list[dict]) -> None:
    """Every job's missing stages, stage-major. A job that fails leaves the
    batch (retried later by ``jobs.finish``); the others carry on."""
    live: list[tuple[dict, object]] = []
    for job in batch:
        try:
            call = inputs.load(job["interaction_id"])
        except Exception as exc:
            _fail(job, exc)
            continue
        if call is None:
            jobs.finish(job["id"])  # the interaction was deleted
            continue
        live.append((job, call))
    rules = inputs.rules() if live else None
    for stage in jobs.STAGES:
        models.keep_only(*models.STAGE_MODELS[stage])
        for job, call in list(live):
            if stage in (job["stages_done"] or []):
                continue
            started = time.monotonic()
            try:
                versions = _run_stage(stage, call, rules)
            except Exception as exc:
                _fail(job, exc)
                live.remove((job, call))
                continue
            jobs.stage_done(job["id"], stage, versions)
            logger.info("call_intel %s: %s in %.1fs", call.interaction_id, stage, time.monotonic() - started)
    for job, _ in live:
        jobs.finish(job["id"])


def process(job: dict) -> None:
    process_batch([job])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    idle = env_float("CALL_INTEL_IDLE_S", 5.0)
    batch = max(1, env_int("CALL_INTEL_BATCH", 8))
    logger.info("call_intel worker started")
    while not _stop:
        try:
            # A person is waiting on an export; calls are background work.
            export = exports.claim()
            if export is not None:
                exports.run(export)
                continue
            claimed = jobs.claim(batch)
        except Exception:
            # The database is down or restarting: wait, never exit the worker.
            logger.exception("call_intel: claim failed; retrying")
            time.sleep(idle)
            continue
        if not claimed:
            time.sleep(idle)
            continue
        try:
            process_batch(claimed)
        except Exception:
            # Per-job failures are handled inside; this is the database going
            # away mid-batch. The claimed jobs are reclaimed when their lock
            # goes stale.
            logger.exception("call_intel: batch of %d interrupted", len(claimed))


if __name__ == "__main__":
    main()
