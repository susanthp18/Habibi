"""The call-intelligence queue: one job per interaction, claimed with SKIP LOCKED."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

#: A running job whose worker has not finished it in this long is reclaimed.
STALE_MINUTES = 15
#: After this many attempts a job stays failed until someone requeues it.
MAX_ATTEMPTS = 5
#: Stage order. A stage reads what the ones before it wrote.
STAGES = ("pii", "audio", "signals", "qa")


def enqueue(interaction_id: str, *, rerun: bool = False) -> None:
    """Queue the call; ``rerun`` redoes every stage (a model or rule change)."""
    import db

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO call_intelligence_jobs (id, tenant_id, interaction_id)
                VALUES (:id, :t, :ix)
                ON CONFLICT (interaction_id) DO UPDATE SET
                  status = CASE WHEN :rerun THEN 'queued' ELSE call_intelligence_jobs.status END,
                  stages_done = CASE WHEN :rerun THEN '{}' ELSE call_intelligence_jobs.stages_done END,
                  attempts = CASE WHEN :rerun THEN 0 ELSE call_intelligence_jobs.attempts END,
                  available_at = CASE WHEN :rerun THEN now() ELSE call_intelligence_jobs.available_at END,
                  updated_at = now()
                """
            ),
            {"id": db._id("CIJ"), "t": db.current_tenant(), "ix": interaction_id, "rerun": rerun},
        )


def rerun_from(interaction_id: str, stage: str) -> None:
    """Redo ``stage`` and every stage after it (a reviewer changed the masks)."""
    import db

    later = list(STAGES[STAGES.index(stage):])
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE call_intelligence_jobs
                SET stages_done = ARRAY(SELECT s FROM unnest(stages_done) s WHERE s <> ALL(:later)),
                    status = 'queued', attempts = 0, available_at = now(), updated_at = now()
                WHERE interaction_id = :ix
                """
            ),
            {"ix": interaction_id, "later": later},
        )


def claim(limit: int) -> list[dict[str, Any]]:
    import db

    with db.engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                UPDATE call_intelligence_jobs j
                SET status = 'running', locked_at = now(), attempts = j.attempts + 1, updated_at = now()
                WHERE j.id IN (
                  SELECT q.id FROM call_intelligence_jobs q
                  -- A finished call only: its transcript and recording are
                  -- filed at the end, so a live one has nothing to analyse yet.
                  JOIN interactions i ON i.id = q.interaction_id
                   AND i.status IN ('completed', 'abandoned')
                  WHERE (q.status = 'queued' AND q.available_at <= now())
                     OR (q.status = 'running' AND q.locked_at < now() - interval '{STALE_MINUTES} minutes')
                  ORDER BY q.available_at
                  FOR UPDATE OF q SKIP LOCKED
                  LIMIT :n
                )
                RETURNING j.id, j.interaction_id, j.stages_done, j.attempts
                """
            ),
            {"n": limit},
        ).mappings().all()
    return [dict(r) for r in rows]


def stage_done(job_id: str, stage: str, versions: dict[str, str]) -> None:
    import db

    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE call_intelligence_jobs
                SET stages_done = array_append(array_remove(stages_done, :stage), :stage),
                    model_versions = model_versions || CAST(:v AS jsonb), updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": job_id, "stage": stage, "v": json.dumps(versions)},
        )


def finish(job_id: str, *, error: str | None = None, attempts: int = 0) -> None:
    """Done, or back on the queue with backoff, or failed for good."""
    import db

    if error is None:
        sql, params = "status = 'done', last_error = NULL", {}
    elif attempts >= MAX_ATTEMPTS:
        sql, params = "status = 'failed', last_error = :err", {"err": error[:2000]}
    else:
        sql = ("status = 'queued', last_error = :err, "
               "available_at = now() + make_interval(mins => :backoff)")
        params = {"err": error[:2000], "backoff": 2 ** attempts}
    with db.engine.begin() as conn:
        conn.execute(
            text(f"UPDATE call_intelligence_jobs SET {sql}, locked_at = NULL, updated_at = now() WHERE id = :id"),
            {"id": job_id, **params},
        )
