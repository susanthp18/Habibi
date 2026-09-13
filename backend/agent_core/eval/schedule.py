"""Continuous regression + red-team + twin. Never on the audio path."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.eval.run import run_named_suite

#: Every suite kind the scheduler runs -- the eval_suites.kind CHECK, one
#: list (a drift test holds the pair; the card's EvalRequire is this minus
#: `capability`).
SUITE_KINDS: tuple[str, ...] = ("regression", "redteam", "twin", "capability", "outbound")


def run_continuous(*, kinds: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Run every first-party suite of the requested kinds. Red-team is never skipped."""
    import db

    # `outbound` too: the suite G-OB9 gates on was never run by the
    # scheduler, so its report was always the one filed by hand or never.
    wanted = set(kinds or SUITE_KINDS)
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
