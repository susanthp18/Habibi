"""Gateway model canary: analysis → text → voice. Red-team is never skipped.

The candidate Azure deployment is an in-process override. Promote to voice
only after regression + red-team + twin + injection-closed + voice SLO.
Nothing here writes ``os.environ``; copy-to-env is a payload for a human.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from agent_core.canary import VOICE_SLO_MS
from agent_core.eval.fixtures import (
    REDTEAM_COLLECTIONS_ID,
    REDTEAM_CASES,
    REGRESSION_COLLECTIONS_ID,
    TWIN_COLLECTIONS_ID,
)
from agent_core.eval.harness import run_suite_fixtures
from agent_core.eval.run import run_named_suite

STAGES = ("analysis", "text", "voice")
_NEXT = {"analysis": "text", "text": "voice"}


def list_canaries(*, limit: int = 20) -> list[dict[str, Any]]:
    import db

    with db.engine.connect() as conn:
        if not _table(conn):
            return []
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT * FROM gateway_canaries
                     WHERE tenant_id = :t
                     ORDER BY created_at DESC
                     LIMIT :n
                    """
                ),
                {"t": db._tenant(), "n": max(1, min(int(limit), 100))},
            )
        )
    return [_public(r) for r in rows]


def current() -> dict[str, Any] | None:
    import db

    with db.engine.connect() as conn:
        if not _table(conn):
            return None
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT * FROM gateway_canaries
                     WHERE tenant_id = :t AND status IN ('running','pass','promoted')
                     ORDER BY CASE WHEN status IN ('running','pass') THEN 0 ELSE 1 END,
                              created_at DESC
                     LIMIT 1
                    """
                ),
                {"t": db._tenant()},
            )
        )
    return _public(row) if row else None


def model_for(profile: str) -> str | None:
    """Override for this gateway profile, or None → env."""
    row = current()
    if not row:
        return None
    status = row["status"]
    stage = row["stage"]
    candidate = row["candidateModel"]
    if status not in {"running", "pass", "promoted"}:
        return None
    if status == "promoted" and stage == "voice":
        return candidate if profile in {"analysis", "text", "voice"} else None
    allowed = {
        "analysis": {"analysis"},
        "text": {"analysis", "text"},
        "voice": {"analysis", "text", "voice"},
    }.get(stage, set())
    return candidate if profile in allowed else None


def propose(candidate_model: str, *, skip_redteam: bool = False) -> dict[str, Any]:
    if skip_redteam:
        raise ValueError("redteam_required")
    model = (candidate_model or "").strip()
    if not model:
        raise ValueError("candidate_model_required")
    import db

    with db.engine.begin() as conn:
        if not _table(conn):
            raise KeyError("gateway_canaries_missing")
        open_row = db._one(
            conn.execute(
                text(
                    """
                    SELECT id FROM gateway_canaries
                     WHERE tenant_id = :t AND status IN ('running','pass')
                     LIMIT 1
                    """
                ),
                {"t": db._tenant()},
            )
        )
        if open_row:
            raise ValueError("canary_already_open")
        cid = db._id("GWC")
        conn.execute(
            text(
                """
                INSERT INTO gateway_canaries (
                  id, tenant_id, candidate_model, stage, status, skip_redteam
                ) VALUES (
                  :id, :t, :model, 'analysis', 'running', false
                )
                """
            ),
            {"id": cid, "t": db._tenant(), "model": model},
        )
    return _finish_stage(cid, "analysis")


def promote(canary_id: str, *, skip_redteam: bool = False) -> dict[str, Any]:
    if skip_redteam:
        raise ValueError("redteam_required")
    import db

    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM gateway_canaries WHERE id = :id AND tenant_id = :t"),
                {"id": canary_id, "t": db._tenant()},
            )
        )
    if row is None:
        raise KeyError("gateway_canary_not_found")
    if row["status"] == "promoted":
        raise ValueError("already_promoted")
    if row["status"] != "pass":
        raise ValueError("stage_not_green")
    nxt = _NEXT.get(str(row["stage"]))
    if not nxt:
        raise ValueError("no_next_stage")
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE gateway_canaries
                   SET stage = :st, status = 'running', updated_at = now()
                 WHERE id = :id
                """
            ),
            {"st": nxt, "id": canary_id},
        )
    return _finish_stage(canary_id, nxt)


def _finish_stage(canary_id: str, stage: str) -> dict[str, Any]:
    import db

    suite_map = {
        "regression": REGRESSION_COLLECTIONS_ID,
        "redteam": REDTEAM_COLLECTIONS_ID,
        "twin": TWIN_COLLECTIONS_ID,
    }
    reports: dict[str, dict[str, Any]] = {}
    for kind, suite_id in suite_map.items():
        try:
            reports[kind] = run_named_suite(suite_id, origin="canary")
        except KeyError:
            if kind == "redteam":
                raise ValueError("redteam_required") from None
            reports[kind] = {"status": "fail", "reportId": None, "kind": kind}

    injection = _injection_closed()
    slo_ms = _voice_slo_ms() if stage == "voice" else None
    red_ok = reports.get("redteam", {}).get("status") == "pass"
    reg_ok = reports.get("regression", {}).get("status") == "pass"
    twin_ok = reports.get("twin", {}).get("status") == "pass"
    slo_ok = True if stage != "voice" else (slo_ms is None or slo_ms <= VOICE_SLO_MS)
    ok = red_ok and reg_ok and twin_ok and injection and slo_ok
    status = "promoted" if ok and stage == "voice" else ("pass" if ok else "fail")
    copy_to_env = []
    if status == "promoted":
        row = _load(canary_id)
        model = row["candidate_model"] if row else ""
        copy_to_env = [
            {"name": "LLM_GATEWAY_VOICE_MODEL", "value": model},
            {"name": "LLM_GATEWAY_TEXT_MODEL", "value": model},
            {"name": "LLM_GATEWAY_ANALYSIS_MODEL", "value": model},
        ]
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE gateway_canaries SET
                  status = :st,
                  regression_report_id = :reg,
                  redteam_report_id = :rt,
                  twin_report_id = :twin,
                  voice_slo_ms = :slo,
                  injection_closed = :inj,
                  copy_to_env = CAST(:copy AS jsonb),
                  updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "st": status,
                "reg": reports.get("regression", {}).get("reportId"),
                "rt": reports.get("redteam", {}).get("reportId"),
                "twin": reports.get("twin", {}).get("reportId"),
                "slo": slo_ms,
                "inj": injection,
                "copy": db._jsonb(copy_to_env),
                "id": canary_id,
            },
        )
    got = _load(canary_id)
    assert got is not None
    public = _public(got)
    public["gates"] = {
        "regression": reg_ok,
        "redteam": red_ok,
        "twin": twin_ok,
        "injectionClosed": injection,
        "voiceSloOk": slo_ok,
        "voiceSloMs": slo_ms,
        "budgetMs": VOICE_SLO_MS,
    }
    public["appliedEnv"] = False
    return public


def _injection_closed() -> bool:
    tasks = [
        {"id": c["id"], "name": c["name"], "grader": c["attack"], "fixture": c["fixture"]}
        for c in REDTEAM_CASES
    ]
    result = run_suite_fixtures(tasks)
    return result["status"] == "pass"


def _voice_slo_ms() -> int | None:
    import db

    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text(
                    """
                    SELECT percentile_cont(0.99) WITHIN GROUP (ORDER BY latency_ms) AS p99
                      FROM interactions
                     WHERE handler_kind = 'bot'
                       AND latency_ms IS NOT NULL
                       AND started_at >= now() - interval '1 day'
                    """
                )
            )
        )
    if not row or row.get("p99") is None:
        return None
    return int(float(row["p99"]))


def _load(canary_id: str) -> dict[str, Any] | None:
    import db

    with db.engine.connect() as conn:
        return db._one(
            conn.execute(
                text("SELECT * FROM gateway_canaries WHERE id = :id AND tenant_id = :t"),
                {"id": canary_id, "t": db._tenant()},
            )
        )


def _table(conn: Any) -> bool:
    row = conn.execute(text("SELECT to_regclass('public.gateway_canaries') AS t")).mappings().first()
    return bool(row and row["t"])


def _public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "candidateModel": row["candidate_model"],
        "stage": row["stage"],
        "status": row["status"],
        "regressionReportId": row.get("regression_report_id"),
        "redteamReportId": row.get("redteam_report_id"),
        "twinReportId": row.get("twin_report_id"),
        "voiceSloMs": row.get("voice_slo_ms"),
        "injectionClosed": bool(row.get("injection_closed")),
        "copyToEnv": row.get("copy_to_env") or [],
        "appliedEnv": False,
        "createdAt": str(row["created_at"]) if row.get("created_at") else None,
        "updatedAt": str(row["updated_at"]) if row.get("updated_at") else None,
    }
