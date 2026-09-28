"""The periodic worker: reconcile Voice Studio calls, retention, QA scoring,
lead and follow-up sweeps, violations, policy, decision and billing jobs.

Each sweep keeps its own clock; the loop ticks every ``--poll`` seconds.
"""

from __future__ import annotations

import argparse
import logging
import os
import time

# Longer statement timeout than the API process (must set before importing db).
os.environ.setdefault("DB_PROCESS_ROLE", "worker")

from env_loader import load_env

load_env()

import bot_jobs
import db
import observability
import work_loop
from agent_core.clock import utc_now

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("worker")

_TTS_SYNC_HOUR_UTC = 2
_TTS_SYNC_MINUTE_UTC = 30
#: job -> the day this process last claimed it. A fast path only; the row in
#: nightly_runs is the marker, so two replicas cannot both win a day and a
#: restarted worker does not run the night again.
_daily_done: dict[str, str] = {}


def _daily(job: str, hour: int, minute: int) -> bool:
    """True for the one caller that gets to run `job` today, once it is past
    hour:minute UTC. Claimed before the work, so a run that dies halfway does
    not restart from the top on the next tick."""
    now = utc_now()
    day = now.strftime("%Y-%m-%d")
    if _daily_done.get(job) == day or (now.hour, now.minute) < (hour, minute):
        return False
    _daily_done[job] = day
    return bot_jobs.claim_daily(db.engine, job, day)


def _maybe_sync_tts_catalog() -> None:
    """Time-gated daily catalog refresh (02:30 UTC)."""
    if not _daily("tts_sync", _TTS_SYNC_HOUR_UTC, _TTS_SYNC_MINUTE_UTC):
        return
    try:
        from tts_catalog_sync import run_sync

        summary = run_sync(db.engine, source="azure")
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


_LEAD_REVALIDATE_HOUR_UTC = 1
_LEAD_REVALIDATE_MINUTE_UTC = 15


def _maybe_revalidate_open_leads() -> None:
    """Re-check open leads against today's consent and account facts (01:15 UTC).

    Eligibility was evaluated once, when the lead was captured, and never again.
    A customer who opted out the next day kept an actionable lead with a green
    badge on it, and the first anyone heard about it was the complaint. This
    does not delete or close anything — it refreshes the flags so the drawer
    tells the truth before a rep dials.
    """
    if not _daily("lead_revalidate", _LEAD_REVALIDATE_HOUR_UTC, _LEAD_REVALIDATE_MINUTE_UTC):
        return
    try:
        report = db.revalidate_open_leads()
        logger.info(
            "nightly lead eligibility sweep: checked=%s nowBlocked=%s",
            report["checked"],
            report["blockedCount"],
        )
        if report["blocked"]:
            reasons = report.get("reasons") or {}
            # One line per distinct reason rather than a bare id list: an
            # operator needs to know whether this is consent moving under them
            # or the book simply being delinquent, and the id list cannot say.
            by_reason: dict[str, list[str]] = {}
            for lead_id in report["blocked"]:
                by_reason.setdefault(reasons.get(lead_id, "unspecified"), []).append(lead_id)
            for why, ids_ in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
                logger.info(
                    "leads ineligible (%s): %s%s",
                    why,
                    ", ".join(ids_[:10]),
                    "" if len(ids_) <= 10 else f" (+{len(ids_) - 10} more)",
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


# Voice Studio calls are filed by the engine's post-call delivery; this sweep
# files any it missed (engine restart, PayInt down) and repairs audio refs
# filed before the recording fix. Cheap when there is nothing to do: one
# engine listing and one indexed lookup.
_STUDIO_RECONCILE_INTERVAL_S = 600.0
_last_studio_reconcile = 0.0


def _maybe_reconcile_voice_studio() -> None:
    global _last_studio_reconcile

    now = time.monotonic()
    if now - _last_studio_reconcile < _STUDIO_RECONCILE_INTERVAL_S:
        return
    _last_studio_reconcile = now
    try:
        import voice_studio

        if voice_studio.preflight():
            return  # Voice Studio is not configured on this deployment
        report = voice_studio.reconcile_runs()
        if report["filed"] or report["repaired"] or report["failed"]:
            logger.info("voice studio reconcile %s", report)
    except Exception:
        logger.exception("voice studio reconcile failed")


_RETENTION_PURGE_INTERVAL_S = 300.0
_last_retention_purge = 0.0

# Well past _MAX_CALL_DURATION_SECS (10 min) and the worker idle backstop, so a
# still-running call can never have its config deleted out from under a restart.
_VOICE_SESSION_TTL_S = 24 * 3600

# customer_memory is derived PII with no independent business value: past six
# months a summary is more likely to mislead than help, and voice/memory.py
# already refuses to inject anything older than VOICE_MEMORY_MAX_AGE_DAYS (90)
# anyway. Deleting well after that read-side cutoff keeps the two decoupled.
_CUSTOMER_MEMORY_TTL_S = 180 * 24 * 3600

# Unanswered questions the legacy runtime recorded: nothing writes them now. A
# gap asked once and never linked ages out; anything asked twice, or that an
# operator linked to a document, is kept.
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
    and ``bot_jobs.process_one`` runs only the WhatsApp turn, so a
    second job kind would need a schema change for work that is not
    latency-sensitive. This mirrors the other periodic ``_maybe_*`` sweeps here.

    Batch is capped so a slow Azure call cannot hold up the other sweeps here.
    Off by default.
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


def _maybe_purge_retention() -> None:
    """Age out derived customer data nothing writes any more (~5 min)."""
    global _last_retention_purge

    now = time.monotonic()
    if now - _last_retention_purge < _RETENTION_PURGE_INTERVAL_S:
        return
    _last_retention_purge = now
    from sqlalchemy import text as _sql

    try:
        with db.engine.begin() as conn:
            dropped = conn.execute(
                _sql("DELETE FROM customer_memory WHERE updated_at < now() - CAST(:w AS interval)"),
                {"w": f"{_CUSTOMER_MEMORY_TTL_S} seconds"},
            ).rowcount
        if dropped:
            logger.debug("purged %s stale customer_memory rows", dropped)
    except Exception:
        logger.warning("customer memory purge failed", exc_info=True)

    try:
        with db.engine.begin() as conn:
            dropped = conn.execute(
                _sql(
                    "DELETE FROM unanswered_questions uq WHERE uq.tenant_id = :t AND uq.hit_count <= 1 "
                    "AND uq.last_seen_at < now() - CAST(:w AS interval) AND NOT EXISTS "
                    "(SELECT 1 FROM analytics_kb_gap_links g WHERE g.unanswered_question_id = uq.id)"
                ),
                {"t": db.current_tenant(), "w": f"{_KB_GAP_TTL_DAYS} days"},
            ).rowcount
        if dropped:
            logger.debug("purged %s stale kb gap rows", dropped)
    except Exception:
        logger.warning("kb gap purge failed", exc_info=True)


def _maybe_run_eval_schedule() -> None:
    """Daily regression + red-team + twin. Never skips red-team. Off the mouth."""
    if not _daily("eval_schedule", _EVAL_HOUR_UTC, _EVAL_MINUTE_UTC):
        return
    try:
        from agent_core.eval.schedule import run_continuous

        result = run_continuous()
        logger.info(
            "eval schedule origin=scheduled ran=%s failed=%s",
            result.get("ran"),
            result.get("failed"),
        )
    except Exception:
        logger.exception("eval schedule failed")


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


_POLICY_SCAN_HOUR_UTC = 22
_POLICY_CUTOVER_HOUR_UTC = 23


def _maybe_policy_jobs() -> None:
    """Horizon scan from 22:00 UTC, cutover from 23:00. Jobs are daily-idempotent."""
    now = utc_now()
    if now.hour < _POLICY_SCAN_HOUR_UTC:
        return
    try:
        import policy_jobs

        with db.engine.begin() as conn:
            policy_jobs.horizon_scan(conn, now=now, report_only=True)
            if now.hour >= _POLICY_CUTOVER_HOUR_UTC:
                policy_jobs.cutover_cancel(conn, now=now)
    except Exception:
        logger.exception("policy jobs failed")


def _maybe_decision_jobs() -> None:
    """The decision engine's schedule: snapshots, nightly learning, weekly training."""
    import decision_jobs

    decision_jobs.tick(_daily, utc_now())


def _maybe_billing_jobs() -> None:
    """Budgets checked hourly; last month's cost statements on the 1st."""
    import billing_jobs

    billing_jobs.tick(_daily, utc_now())


def main() -> None:
    import actor_context

    actor_context.bind_service_actor("system")
    parser = argparse.ArgumentParser(description="Periodic sweeps: reconcile, retention, QA, policy, billing")
    parser.add_argument("--poll", type=float, default=2.0, help="Seconds between ticks")
    args = parser.parse_args()

    logger.info("worker started poll=%.1fs", args.poll)
    observability.serve_metrics()

    def step() -> bool:
        _maybe_billing_jobs()
        _maybe_sync_tts_catalog()
        _maybe_revalidate_open_leads()
        _maybe_sweep_due_followups()
        _maybe_scan_for_violations()
        _maybe_reconcile_voice_studio()
        _maybe_purge_retention()
        _maybe_autoscore_interactions()
        _maybe_run_eval_schedule()
        _maybe_drain_mcp_tasks()
        _maybe_policy_jobs()
        _maybe_decision_jobs()
        return False  # every sweep keeps its own clock; idle between ticks

    work_loop.run(step, poll=args.poll, name="worker")


if __name__ == "__main__":
    main()
