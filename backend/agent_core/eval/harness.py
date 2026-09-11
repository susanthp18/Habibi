"""Run a suite's tasks against fixtures. No LLM on this path."""

from __future__ import annotations

import logging
from typing import Any

from agent_core.eval.graders import run_grader

logger = logging.getLogger(__name__)


def run_suite_fixtures(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """tasks: {id, name, grader, fixture}.

    A grader that raises is one errored trial, not an aborted run: the run
    used to die on the first exception, file no report, and never write the
    ``error`` status the table reserves. Each trial carries its fixture so a
    red report can be opened.
    """
    trials: list[dict[str, Any]] = []
    failed = 0
    errored = 0
    for task in tasks:
        fixture = task.get("fixture") or {}
        grader = str(task.get("grader") or "")
        try:
            verdict = run_grader(grader, fixture)
            error = None
        except Exception as exc:
            logger.exception("eval grader %s raised on task %s", grader, task.get("id"))
            verdict = {"grader": grader, "passed": False, "detail": f"grader raised: {exc}"}
            error = f"{exc.__class__.__name__}: {exc}"
            errored += 1
        passed = bool(verdict.get("passed"))
        if not passed:
            failed += 1
        trials.append(
            {
                "taskId": task.get("id"),
                "name": task.get("name"),
                "passed": passed,
                "verdict": verdict,
                "fixture": fixture,
                "error": error,
            }
        )
    status = "error" if errored else ("pass" if failed == 0 else "fail")
    return {
        "status": status,
        "failed": failed,
        "errored": errored,
        "total": len(trials),
        "trials": trials,
    }
