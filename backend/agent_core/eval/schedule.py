"""Continuous regression + red-team + twin. Never on the audio path."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.eval.run import run_named_suite


def scheduled_suite_ids() -> list[str]:
    import db

    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id FROM eval_suites
                     WHERE tenant_id = :t
                       AND kind IN ('regression','redteam','twin','capability')
                     ORDER BY kind, id
                    """
                ),
                {"t": db._tenant()},
            )
        )
    return [str(r["id"]) for r in rows]


def run_continuous(*, kinds: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Run every first-party suite of the requested kinds. Red-team is never skipped."""
    import db

    wanted = set(kinds or ("regression", "redteam", "twin", "capability"))
    if "redteam" not in wanted:
        raise ValueError("redteam_required")
    reports: list[dict[str, Any]] = []
    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, kind FROM eval_suites
                     WHERE tenant_id = :t
                     ORDER BY kind, id
                    """
                ),
                {"t": db._tenant()},
            )
        )
    for row in rows:
        if str(row["kind"]) not in wanted:
            continue
        reports.append(run_named_suite(str(row["id"]), origin="scheduled"))
    failed = [r for r in reports if r.get("status") != "pass"]
    return {
        "origin": "scheduled",
        "ran": len(reports),
        "failed": len(failed),
        "status": "pass" if not failed else "fail",
        "reports": reports,
    }
