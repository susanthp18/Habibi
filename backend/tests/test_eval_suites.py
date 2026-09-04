"""Seeded eval suites run through code graders and persist a report."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_core.eval.fixtures import (
    OUTBOUND_TASKS,
    PUBLISH_OUTBOUND_TASKS,
    PUBLISH_REGRESSION_TASKS,
    REDTEAM_CASES,
)
from agent_core.eval.graders import run_grader
from agent_core.eval.harness import run_suite_fixtures

_SQL_23 = Path(__file__).resolve().parents[1] / "sql" / "23_outbound_evals.sql"

_SQL_TASK_RE = re.compile(
    r"THEN '(evt-ob-[a-z-]+)' ELSE '\1-'.*?"
    r"\$obname\$(.*?)\$obname\$,\s*"
    r"'([a-z_]+)',\s*"
    r"\$obfix\$(.*?)\$obfix\$",
    re.S,
)


def _sql_23_publish_tasks() -> dict[str, dict]:
    text = _SQL_23.read_text(encoding="utf-8")
    found: dict[str, dict] = {}
    for match in _SQL_TASK_RE.finditer(text):
        found[match.group(1)] = {
            "id": match.group(1),
            "name": match.group(2),
            "grader": match.group(3),
            "fixture": json.loads(match.group(4)),
        }
    return found


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


def test_sql_23_exists_so_a_fresh_install_can_satisfy_g_ob9() -> None:
    """WP-034. 0096 claimed to mirror this file; sql/ jumped 22 → 90."""
    assert _SQL_23.is_file(), (
        "sql/23_outbound_evals.sql is the seed a database built from sql/ "
        "needs to run the outbound suite G-OB9 gates on"
    )


def test_sql_23_mirrors_the_python_publish_tasks() -> None:
    """Python is the pin; this file is what CI actually applies.

    A third restatement of the nine fixtures that then drifted is how 0096
    shipped hollow ``{}`` rows. Comparing the parsed INSERTs to
    ``PUBLISH_OUTBOUND_TASKS`` is the check that would have caught that.
    """
    expected = {
        t["id"]: {
            "id": t["id"],
            "name": t["name"],
            "grader": t["grader"],
            "fixture": t["fixture"],
        }
        for t in PUBLISH_OUTBOUND_TASKS
    }
    assert _sql_23_publish_tasks() == expected


def test_sql_23_does_not_seed_the_expect_fail_siblings() -> None:
    """Those rows exist to prove a grader can fail. Seeding one makes G-OB9
    unsatisfiable, which is the outage this file exists to close."""
    sql = _SQL_23.read_text(encoding="utf-8")
    seeded = {t["id"] for t in PUBLISH_OUTBOUND_TASKS}
    for task in OUTBOUND_TASKS:
        if task.get("expect_fail"):
            assert task["id"] not in seeded
            assert f"THEN '{task['id']}'" not in sql, task["id"]


def test_sql_23_fixtures_are_a_passable_outbound_suite() -> None:
    """A database built from sql/ alone can satisfy G-OB9: the rows it
    inserts are the shape a correct agent produces, and they grade green."""
    tasks = list(_sql_23_publish_tasks().values())
    result = run_suite_fixtures(tasks)
    assert result["status"] == "pass", result["trials"]
    assert result["failed"] == 0
