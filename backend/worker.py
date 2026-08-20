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
import signal
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


_LEAD_REVALIDATE_HOUR_UTC = 1
_LEAD_REVALIDATE_MINUTE_UTC = 15
_last_lead_revalidate_day: str | None = None


def _maybe_revalidate_open_leads() -> None:
    """Re-check open leads against today's consent and account facts (01:15 UTC).

    Eligibility was evaluated once, when the lead was captured, and never again.
    A customer who opted out the next day kept an actionable lead with a green
    badge on it, and the first anyone heard about it was the complaint. This
    does not delete or close anything — it refreshes the flags so the drawer
    tells the truth before a rep dials.
    """
    global _last_lead_revalidate_day
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    if _last_lead_revalidate_day == day_key:
        return
    if (now.hour, now.minute) < (_LEAD_REVALIDATE_HOUR_UTC, _LEAD_REVALIDATE_MINUTE_UTC):
        return
    # Stamp before the work, not after: a sweep that dies halfway must not
    # restart from the top on the next tick and re-walk the whole pipeline.
    _last_lead_revalidate_day = day_key
    try:
        report = db.revalidate_open_leads()
        logger.info(
            "nightly lead eligibility sweep: checked=%s nowBlocked=%s",
            report["checked"],
            report["blockedCount"],
        )
        if report["blocked"]:
            logger.warning(
                "leads no longer eligible (consent/DPD moved): %s",
                ", ".join(report["blocked"][:20]),
            )
    except Exception:
        logger.exception("nightly lead eligibility sweep failed")


# Follow-ups come due at a wall-clock minute somebody chose, so this runs on an
# interval rather than the daily gate the eligibility sweep uses: a callback
# booked for 11:00 that surfaces at 01:15 the following night has already been
# missed by the person it was booked for.
_FOLLOWUP_SWEEP_INTERVAL_S = 600.0
_last_followup_sweep = 0.0


def _maybe_sweep_due_followups() -> None:
    """Raise lead follow-ups whose moment has passed (~10 min).

    Escalates; never contacts. Reaching out on a customer's behalf is a
    contact-policy decision, and a background sweep must not make one quietly.
    """
    global _last_followup_sweep

    now = time.monotonic()
    if now - _last_followup_sweep < _FOLLOWUP_SWEEP_INTERVAL_S:
        return
    _last_followup_sweep = now
    try:
        report = db.sweep_due_followups()
        if report["escalated"]:
            logger.info(
                "overdue follow-up sweep escalated %s: %s",
                report["escalated"],
                ", ".join(report["leads"][:20]),
            )
    except Exception:
        logger.exception("overdue follow-up sweep failed")


# Compliance detection runs off the interaction, after it ends, rather than
# inside the call. That is what lets it cover human agents and chat as well as
# bot voice, and what makes a rule change a backfill instead of a fresh start.
_COMPLIANCE_SWEEP_INTERVAL_S = 300.0
_last_compliance_sweep = 0.0


def _maybe_scan_for_violations() -> None:
    """Judge completed interactions against the rule catalog (~5 min).

    Batched and ledger-backed, so this is resumable: whatever it does not get
    through stays queued rather than being lost. Raising
    ``compliance.RULES_VERSION`` re-queues history automatically.
    """
    global _last_compliance_sweep

    now = time.monotonic()
    if now - _last_compliance_sweep < _COMPLIANCE_SWEEP_INTERVAL_S:
        return
    _last_compliance_sweep = now
    try:
        from agent_core import compliance

        report = compliance.sweep(limit=200)
        if report["scanned"]:
            logger.info(
                "compliance sweep scanned=%s filed=%s rulesVersion=%s",
                report["scanned"],
                report["filed"],
                report["rulesVersion"],
            )
    except Exception:
        logger.exception("compliance sweep failed")


_RATE_LIMIT_PURGE_INTERVAL_S = 300.0
_last_rate_limit_purge = 0.0

# Well past _MAX_CALL_DURATION_SECS (10 min) and the worker idle backstop, so a
# still-running call can never have its config deleted out from under a restart.
_VOICE_SESSION_TTL_S = 24 * 3600

# customer_memory is derived PII with no independent business value: past six
# months a summary is more likely to mislead than help, and voice/memory.py
# already refuses to inject anything older than VOICE_MEMORY_MAX_AGE_DAYS (90)
# anyway. Deleting well after that read-side cutoff keeps the two decoupled.
_CUSTOMER_MEMORY_TTL_S = 180 * 24 * 3600

# A gap asked exactly once and never triaged, three months on, is not a content
# gap — it is a one-off phrasing or a mis-transcription. Anything asked twice or
# linked to a doc/FAQ/prompt survives regardless of age.
_KB_GAP_TTL_DAYS = 90


# QA auto-scoring. Its own gate rather than sharing the purge tick: those are
# single indexed DELETEs, this makes up to ten Azure calls and must not run at
# the same cadence.
_AUTOSCORE_INTERVAL_S = 120.0
_AUTOSCORE_BATCH = 10
_last_autoscore = 0.0


def _maybe_autoscore_interactions() -> None:
    """Score completed bot calls against the QA rubric (~2 min).

    Chosen over a new job table because ``bot_turn_jobs`` has no ``kind`` column
    and ``bot_jobs.process_one`` hard-codes ``bot_runtime.handle_turn``, so a
    second job kind would need a schema change for work that is not
    latency-sensitive. This mirrors the other periodic ``_maybe_*`` sweeps here.

    Batch is capped because this process is the KB indexer: a slow Azure call
    here delays ``kb_ingest.process_one``. Off by default.
    """
    global _last_autoscore

    now = time.monotonic()
    if now - _last_autoscore < _AUTOSCORE_INTERVAL_S:
        return
    _last_autoscore = now
    try:
        import qa_autoscore
        from agent_core.live_qa.scorecard import score_pending as live_score_pending

        live_written = live_score_pending(limit=_AUTOSCORE_BATCH)
        if live_written:
            logger.info("live_qa scorecards wrote %s", live_written)
        if not qa_autoscore.enabled():
            return
        written = qa_autoscore.score_pending(limit=_AUTOSCORE_BATCH)
        if written:
            logger.info("qa autoscore wrote %s scorecards", written)
    except Exception:
        logger.warning("qa autoscore sweep failed", exc_info=True)


def _maybe_purge_rate_limit_counters() -> None:
    """Drop expired kb_rate_limit_counters rows and stale Live sessions (~5 min)."""
    global _last_rate_limit_purge

    now = time.monotonic()
    if now - _last_rate_limit_purge < _RATE_LIMIT_PURGE_INTERVAL_S:
        return
    _last_rate_limit_purge = now
    try:
        import kb_rate_limit

        removed = kb_rate_limit.purge_expired_counters()
        if removed:
            logger.debug("purged %s expired rate-limit counter rows", removed)
    except Exception:
        logger.warning("rate-limit counter purge failed", exc_info=True)

    # Sandbox Live sessions are one row per Live call and nothing deletes them
    # on the happy path — stop() marks a session stopped, it does not remove it.
    try:
        import voice_session_store

        dropped = voice_session_store.purge_stale(_VOICE_SESSION_TTL_S)
        if dropped:
            logger.debug("purged %s stale voice sandbox sessions", dropped)
    except Exception:
        logger.warning("voice sandbox session purge failed", exc_info=True)

    # Cross-call memory retention. Shares this tick's interval gate rather than
    # adding a second timer — it is a single indexed DELETE.
    try:
        from voice import memory as voice_memory

        dropped = voice_memory.purge_stale(_CUSTOMER_MEMORY_TTL_S)
        if dropped:
            logger.debug("purged %s stale customer_memory rows", dropped)
    except Exception:
        logger.warning("customer memory purge failed", exc_info=True)

    # KB-gap retention. Runtime capture turned unanswered_questions from a
    # hand-seeded table of ~10 rows into one that grows with traffic, and a
    # question asked exactly once and never linked to anything is noise on the
    # triage screen. Anything asked twice, or that an operator already acted on,
    # is kept — see db.purge_stale_kb_gaps.
    try:
        dropped = db.purge_stale_kb_gaps(ttl_days=_KB_GAP_TTL_DAYS)
        if dropped:
            logger.debug("purged %s stale kb gap rows", dropped)
    except Exception:
        logger.warning("kb gap purge failed", exc_info=True)


_GARDENER_HOUR_UTC = 3
_GARDENER_MINUTE_UTC = 10
_last_gardener_day: str | None = None


def _maybe_garden_kb_gaps() -> None:
    """Daily unsigned skill drafts from repeated unanswered questions.

    Humans still have to sign. This must never call ``sign_skill``.
    """
    global _last_gardener_day
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    if _last_gardener_day == day_key:
        return
    if (now.hour, now.minute) < (_GARDENER_HOUR_UTC, _GARDENER_MINUTE_UTC):
        return
    try:
        from agent_core.skills.gardener import assert_unsigned, garden_open_gaps
        from agent_core.skills.persist import create_draft_skill, list_skills

        existing = {str(s.get("slug") or "") for s in list_skills()}
        drafts = garden_open_gaps(db.list_kb_gaps(), existing)
        created = 0
        for draft in drafts:
            assert_unsigned(draft)
            create_draft_skill(
                {
                    "slug": draft["slug"],
                    "description": draft["frontmatter"].get("description"),
                    "allowed_tools": draft["allowed_tools"],
                    "body": draft["body"],
                    "frontmatter": draft["frontmatter"],
                    "origin": "gardener",
                }
            )
            created += 1
        _last_gardener_day = day_key
        if created:
            logger.info("kb gardener drafted %s unsigned skill(s)", created)
    except Exception:
        logger.exception("kb gardener failed")
        _last_gardener_day = day_key


_EVAL_HOUR_UTC = 4
_EVAL_MINUTE_UTC = 15
_last_eval_day: str | None = None


def _maybe_run_eval_schedule() -> None:
    """Daily regression + red-team + twin. Never skips red-team. Off the mouth."""
    global _last_eval_day
    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    if _last_eval_day == day_key:
        return
    if (now.hour, now.minute) < (_EVAL_HOUR_UTC, _EVAL_MINUTE_UTC):
        return
    try:
        from agent_core.eval.schedule import run_continuous

        result = run_continuous()
        _last_eval_day = day_key
        logger.info(
            "eval schedule origin=scheduled ran=%s failed=%s",
            result.get("ran"),
            result.get("failed"),
        )
    except Exception:
        logger.exception("eval schedule failed")
        _last_eval_day = day_key


def _maybe_drain_mcp_tasks() -> None:
    """Turn queued MCP statement/bureau tickets into CRM rows. Never on the mouth."""
    try:
        from agent_core.platform_flags import mcp_tasks_enabled

        if not mcp_tasks_enabled():
            return
        from agent_core.mcp_http.tasks import process_one as drain_mcp

        n = 0
        while n < 10 and drain_mcp():
            n += 1
        if n:
            logger.info("mcp task drain processed %s", n)
    except Exception:
        logger.exception("mcp task drain failed")


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
            _maybe_sync_tts_catalog()
            _maybe_revalidate_open_leads()
            _maybe_sweep_due_followups()
            _maybe_scan_for_violations()
            _maybe_purge_rate_limit_counters()
            _maybe_autoscore_interactions()
            _maybe_garden_kb_gaps()
            _maybe_run_eval_schedule()
            _maybe_drain_mcp_tasks()
            did = process_one(db.engine)
        except Exception:
            logger.exception("kb worker iteration crashed — backing off")
            time.sleep(args.poll)
            continue
        if not did:
            time.sleep(args.poll)


if __name__ == "__main__":
    main()
