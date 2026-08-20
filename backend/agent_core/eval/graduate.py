"""Capability graduation — copy a stable hill task into regression. Human-triggered."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.eval.fixtures import REGRESSION_COLLECTIONS_ID


def graduate_task(task_id: str) -> dict[str, Any]:
    """Copy a capability (or twin) task into the regression suite. Does not sign skills."""
    import db

    with db.engine.begin() as conn:
        task = db._one(
            conn.execute(
                text(
                    """
                    SELECT t.id, t.name, t.grader, t.fixture, t.graduated_at, s.kind, s.id AS suite_id
                      FROM eval_tasks t
                      JOIN eval_suites s ON s.id = t.suite_id
                     WHERE t.id = :id AND s.tenant_id = :tenant
                    """
                ),
                {"id": task_id, "tenant": db._tenant()},
            )
        )
        if task is None:
            raise KeyError("eval_task_not_found")
        if task["kind"] not in {"capability", "twin"}:
            raise ValueError("graduate_only_capability_or_twin")
        if task.get("graduated_at"):
            raise ValueError("already_graduated")
        dest_id = f"task-grad-{str(task['id']).replace('task-', '', 1)}"[:80]
        conn.execute(
            text(
                """
                INSERT INTO eval_tasks (id, suite_id, name, grader, fixture, pass_bar)
                VALUES (:id, :suite, :name, :grader, CAST(:fixture AS jsonb), 'all')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": dest_id,
                "suite": REGRESSION_COLLECTIONS_ID,
                "name": task["name"],
                "grader": task["grader"],
                "fixture": db._jsonb(task.get("fixture") or {}),
            },
        )
        conn.execute(
            text("UPDATE eval_tasks SET graduated_at = now() WHERE id = :id"),
            {"id": task_id},
        )
    return {
        "sourceTaskId": task_id,
        "regressionTaskId": dest_id,
        "suiteId": REGRESSION_COLLECTIONS_ID,
        "signedSkill": False,
    }
