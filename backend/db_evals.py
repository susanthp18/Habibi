"""Eval reports and suites: what a run left behind, and the newest twin gate.

Carved out of ``db_inbox.py`` (WP-036 peel); call sites stay ``import db``.
The engine is reached through ``db`` at call time so the test savepoint proxy applies.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from db_core import (
    _db,
    _id,
    _jsonb,
    _one,
    _rows,
    _tenant,
)

logger = logging.getLogger(__name__)


def _engine():
    """The engine, resolved at call time.

    ``tests/conftest.py`` replaces ``db.engine`` with a savepoint proxy by
    setattr on the module object. Binding the name here at import time would
    take the real engine and silently escape that proxy.
    """
    return _db().engine


def _latest_twin_gate_report() -> dict[str, Any] | None:
    """Newest twin run, shaped for compiler G11. None if the table is missing."""
    try:
        from agent_core.twin import latest_gate_report

        return latest_gate_report()
    except Exception:
        return None


def get_latest_eval_report(
    *,
    bot_id: str,
    kind: str,
    prompt_version_id: str | None = None,
    content_key: str | None = None,
) -> dict[str, Any] | None:
    """Newest report for this bot whose suite matches ``kind`` (regression/redteam).

    When ``prompt_version_id`` is set, only a report filed against that exact
    draft counts — a green suite on last week's published card must not open
    the gate for this week's unpublished one. ``content_key`` asks the better
    question -- a report run against *this content*, whichever row carried it
    -- and wins when given: a version restored from a passed one is passed;
    a version edited after its run is not.
    """
    # Tenant-scoped like its sibling `list_eval_reports`. Bot ids are unique
    # across tenants in practice, so this is latent rather than live — but it is
    # the read three publish gates consult, and "latent" is not a property to
    # leave on the gate that decides whether a card may ship.
    clauses = ["r.tenant_id = :tenant", "r.bot_id = :bot", "s.kind = :kind"]
    params: dict[str, Any] = {"tenant": _tenant(), "bot": bot_id, "kind": kind}
    if content_key:
        clauses.append("r.content_key = :ck")
        params["ck"] = content_key
    elif prompt_version_id:
        clauses.append("r.prompt_version_id = :pv")
        params["pv"] = prompt_version_id
    with _engine().connect() as conn:
        r = _one(
            conn.execute(
                text(
                    f"""
                    SELECT r.id, r.status, r.summary, r.suite_id, r.bot_id,
                           r.prompt_version_id, r.content_key, r.created_at
                    FROM eval_reports r
                    JOIN eval_suites s ON s.id = r.suite_id
                    WHERE {" AND ".join(clauses)}
                    ORDER BY r.created_at DESC
                    LIMIT 1
                    """
                ),
                params,
            )
        )
        return dict(r) if r else None


def save_eval_report(
    *,
    suite_id: str,
    bot_id: str | None,
    status: str,
    summary: dict[str, Any],
    trials: list[dict[str, Any]] | None = None,
    prompt_version_id: str | None = None,
    origin: str = "manual",
    content_key: str | None = None,
) -> dict[str, Any]:
    rid = _id("EVR")
    origin = origin if origin in {"manual", "scheduled", "canary", "upgrade"} else "manual"
    with _engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eval_reports (
                  id, tenant_id, suite_id, bot_id, prompt_version_id, status, summary, origin,
                  content_key
                ) VALUES (
                  :id, :tenant, :suite, :bot, :pv, :status, CAST(:summary AS jsonb), :origin,
                  :ck
                )
                """
            ),
            {
                "id": rid,
                "tenant": _tenant(),
                "suite": suite_id,
                "bot": bot_id,
                "pv": prompt_version_id,
                "status": status,
                "summary": _jsonb(summary),
                "origin": origin,
                "ck": content_key,
            },
        )
        for trial in trials or []:
            tid = _id("EVT")
            conn.execute(
                text(
                    """
                    INSERT INTO eval_trials (
                      id, report_id, task_id, redteam_case_id, k, passed,
                      transcript, tool_calls, crm_outcomes, grader_verdicts
                    ) VALUES (
                      :id, :report, :task, :redteam, 1, :passed,
                      CAST(:transcript AS jsonb), CAST(:tools AS jsonb),
                      CAST(:crm AS jsonb), CAST(:verdicts AS jsonb)
                    )
                    """
                ),
                {
                    "id": tid,
                    "report": rid,
                    "task": trial.get("taskId")
                    if str(trial.get("taskId") or "").startswith("task-")
                    else None,
                    "redteam": trial.get("taskId")
                    if str(trial.get("taskId") or "").startswith("rt-")
                    else None,
                    "passed": bool(trial.get("passed")),
                    # The fixture the grader saw, in the columns that were
                    # always written as empty literals -- so a red report can
                    # be opened, not only counted.
                    "transcript": _jsonb(
                        (trial.get("fixture") or {}).get("agent_turns")
                        or (trial.get("fixture") or {}).get("transcript")
                        or []
                    ),
                    "tools": _jsonb((trial.get("fixture") or {}).get("tool_calls") or []),
                    "crm": _jsonb(
                        {k: v for k, v in (trial.get("fixture") or {}).items() if k not in {"agent_turns", "transcript", "tool_calls"}}
                    ),
                    "verdicts": _jsonb(
                        {**(trial.get("verdict") or {}), **({"error": trial["error"]} if trial.get("error") else {})}
                    ),
                },
            )
    return {"id": rid, "status": status, "summary": summary, "botId": bot_id, "suiteId": suite_id, "origin": origin}


#: `botId` value that asks for the reports filed against no card at all.
TENANT_WIDE_REPORTS = "__none__"


def get_eval_report(report_id: str) -> dict[str, Any] | None:
    """One report row, scoped to the tenant like every sibling read."""
    with _engine().connect() as conn:
        row = _one(
            conn.execute(
                text("SELECT * FROM eval_reports WHERE id = :id AND tenant_id = :t"),
                {"id": report_id, "t": _tenant()},
            )
        )
    return dict(row) if row is not None else None


def list_eval_reports(
    *, kind: str | None = None, bot_id: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    clauses = ["r.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": _tenant(), "n": max(1, min(int(limit), 200))}
    if kind:
        clauses.append("s.kind = :kind")
        params["kind"] = kind
    if bot_id == TENANT_WIDE_REPORTS:
        # The scheduler files tenant-wide runs with no card. Filtering a
        # shared page of fifty client-side lost them the moment fifty newer
        # card-scoped reports existed.
        clauses.append("r.bot_id IS NULL")
    elif bot_id:
        clauses.append("r.bot_id = :bot_id")
        params["bot_id"] = bot_id
    where = " AND ".join(clauses)
    with _engine().connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT r.id, r.suite_id, r.bot_id, r.status, r.summary, r.created_at, r.origin,
                           s.kind, s.name AS suite_name
                    FROM eval_reports r
                    JOIN eval_suites s ON s.id = r.suite_id
                    WHERE {where}
                    ORDER BY r.created_at DESC
                    LIMIT :n
                    """
                ),
                params,
            )
        )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "suiteId": r["suite_id"],
                "suiteName": r.get("suite_name"),
                "kind": r.get("kind"),
                "botId": r.get("bot_id"),
                "status": r["status"],
                "summary": r.get("summary") or {},
                "origin": r.get("origin") or "manual",
                "createdAt": str(r["created_at"]) if r.get("created_at") else None,
            }
        )
    return out


def list_eval_suites(*, kind: str | None = None) -> list[dict[str, Any]]:
    clauses = ["tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": _tenant()}
    if kind:
        clauses.append("kind = :kind")
        params["kind"] = kind
    where = " AND ".join(clauses)
    with _engine().connect() as conn:
        rows = _rows(
            conn.execute(
                text(
                    f"""
                    SELECT id, kind, name, description, created_at
                    FROM eval_suites
                    WHERE {where}
                    ORDER BY kind, id
                    """
                ),
                params,
            )
        )
        return [dict(r) for r in rows]
