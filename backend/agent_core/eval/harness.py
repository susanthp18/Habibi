"""Run a suite's tasks against fixtures. No LLM on this path."""

from __future__ import annotations

from typing import Any

from agent_core.eval.graders import run_grader


def run_suite_fixtures(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """tasks: {id, name, grader, fixture}."""
    trials: list[dict[str, Any]] = []
    failed = 0
    for task in tasks:
        verdict = run_grader(str(task.get("grader") or ""), task.get("fixture") or {})
        passed = bool(verdict.get("passed"))
        if not passed:
            failed += 1
        trials.append(
            {
                "taskId": task.get("id"),
                "name": task.get("name"),
                "passed": passed,
                "verdict": verdict,
            }
        )
    status = "pass" if failed == 0 else "fail"
    return {"status": status, "failed": failed, "total": len(trials), "trials": trials}
