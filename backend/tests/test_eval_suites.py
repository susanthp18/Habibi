"""Seeded eval suites run through code graders and persist a report."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


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


def test_sql_23_exists_so_a_fresh_install_can_satisfy_g_ob9() -> None:
    """WP-034. 0096 claimed to mirror this file; sql/ jumped 22 → 90."""
    assert _SQL_23.is_file(), (
        "sql/23_outbound_evals.sql is the seed a database built from sql/ "
        "needs to run the outbound suite G-OB9 gates on"
    )


