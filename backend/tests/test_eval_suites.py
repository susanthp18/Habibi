"""Seeded eval suites run through code graders and persist a report."""

from __future__ import annotations

from agent_core.eval.fixtures import PUBLISH_REGRESSION_TASKS, REDTEAM_CASES
from agent_core.eval.harness import run_suite_fixtures


def test_collections_regression_fixtures_pass() -> None:
    result = run_suite_fixtures(PUBLISH_REGRESSION_TASKS)
    assert result["status"] == "pass"
    assert result["failed"] == 0


def test_collections_redteam_fixtures_pass() -> None:
    tasks = [
        {
            "id": c["id"],
            "name": c["name"],
            "grader": c["attack"],
            "fixture": c["fixture"],
        }
        for c in REDTEAM_CASES
    ]
    result = run_suite_fixtures(tasks)
    assert result["status"] == "pass", result["trials"]
