"""Load a named suite from Postgres and persist a report. No LLM on this path."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.eval.harness import run_suite_fixtures

_ORIGINS = frozenset({"manual", "scheduled", "canary", "upgrade"})


def bot_id_for_suite(suite_id: str) -> str | None:
    if suite_id.endswith("-collections") or "collections" in suite_id:
        return "kaia-v2-4"
    return None


def load_suite_fixtures(suite_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    import db

    with db.engine.connect() as conn:
        suite = db._one(
            conn.execute(
                text("SELECT id, kind, name FROM eval_suites WHERE id = :id AND tenant_id = :t"),
                {"id": suite_id, "t": db._tenant()},
            )
        )
        if suite is None:
            raise KeyError("eval_suite_not_found")
        tasks = db._rows(
            conn.execute(
                text(
                    "SELECT id, name, grader, fixture FROM eval_tasks WHERE suite_id = :id ORDER BY id"
                ),
                {"id": suite_id},
            )
        )
        cases = db._rows(
            conn.execute(
                text(
                    "SELECT id, name, attack, fixture FROM eval_redteam_cases WHERE suite_id = :id ORDER BY id"
                ),
                {"id": suite_id},
            )
        )
    fixtures = [
        {"id": t["id"], "name": t["name"], "grader": t["grader"], "fixture": t.get("fixture") or {}}
        for t in tasks
    ]
    for case in cases:
        fixtures.append(
            {
                "id": case["id"],
                "name": case["name"],
                "grader": case.get("attack") or "no_prose_handoff",
                "fixture": case.get("fixture") or {},
            }
        )
    return dict(suite), fixtures


def run_named_suite(
    suite_id: str,
    *,
    origin: str = "manual",
    bot_id: str | None = None,
) -> dict[str, Any]:
    import db

    origin = origin if origin in _ORIGINS else "manual"
    suite, fixtures = load_suite_fixtures(suite_id)
    result = run_suite_fixtures(fixtures)
    saved = db.save_eval_report(
        suite_id=suite_id,
        bot_id=bot_id if bot_id is not None else bot_id_for_suite(suite_id),
        status=result["status"],
        summary={"failed": result["failed"], "total": result["total"], "origin": origin},
        trials=result["trials"],
        origin=origin,
    )
    return {
        "suiteId": suite_id,
        "kind": suite["kind"],
        "name": suite.get("name"),
        "reportId": saved["id"],
        **result,
    }
