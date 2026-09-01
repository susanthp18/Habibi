"""Seeded eval suites run through code graders and persist a report."""

from __future__ import annotations

import pytest

from agent_core.eval.fixtures import (
    OUTBOUND_TASKS,
    PUBLISH_OUTBOUND_TASKS,
    PUBLISH_REGRESSION_TASKS,
    REDTEAM_CASES,
)
from agent_core.eval.graders import run_grader
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


def test_outbound_conduct_fixtures_pass() -> None:
    """The suite G-OB9 gates on must be passable by a correct agent.

    It was not: migration 0096 seeded all nine tasks with ``{}``, and
    ``outbound_opens_by_confirming`` reads an empty ``agent_turns`` as silence.
    So the gate refused every outbound publish, permanently.
    """
    result = run_suite_fixtures(PUBLISH_OUTBOUND_TASKS)
    assert result["status"] == "pass", result["trials"]
    assert result["failed"] == 0


@pytest.mark.parametrize("task", OUTBOUND_TASKS, ids=lambda t: t["id"])
def test_every_outbound_fixture_grades_the_way_it_claims(task) -> None:
    """A populated fixture is not the same as a fixture that can fail.

    Eight of these nine graders open with a "not applicable" guard — no machine
    answered, no opt-out requested, not a service pool — so an empty fixture
    returns ``passed: True`` with a reason. Filling them in without also proving
    the grader still says no to a violating shape would rebuild the vacuous pass
    with more JSON in it. Each ``expect_fail`` task is that proof.
    """
    verdict = run_grader(task["grader"], task["fixture"])
    if task.get("expect_fail"):
        assert not verdict["passed"], (
            f"{task['id']} is meant to be the violating shape for "
            f"{task['grader']}, and the grader passed it: {verdict['detail']}"
        )
    else:
        assert verdict["passed"], f"{task['id']}: {verdict['detail']}"


def test_no_seeded_task_is_graded_against_an_empty_fixture() -> None:
    """The ratchet. A task graded against ``{}`` is a task that cannot fail."""
    hollow = [
        t["id"]
        for t in PUBLISH_REGRESSION_TASKS + PUBLISH_OUTBOUND_TASKS
        if not t.get("fixture")
    ]
    assert hollow == [], f"tasks with no fixture cannot fail: {hollow}"
