"""Borrower simulation twin — fake ledger + queues, never a dialer.

A bounce ladder is replayed against in-memory state. Outcome graders inspect
that fake ledger, not spoken lines. ``TEMPORAL_ENABLED`` is unrelated; the twin
does not place calls.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text

from agent_core.eval.graders import grade_bounce_ladder, grade_no_dial
from work_runtime.keys import idempotency_key

DEFAULT_TWIN_ID = "twin-bounce-ladder-v0"

DEFAULT_STATE: dict[str, Any] = {
    "dpd": 8,
    "bounce": True,
    "openPtp": False,
    "hardship": False,
    "language": "en",
    "dnd": False,
    "ledger": {"outstanding": 12400, "lastEvent": None},
    "queues": {"whatsapp": [], "sms": [], "voice": []},
}


def ensure_default_twin() -> dict[str, Any]:
    import db

    with db.engine.begin() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM simulation_twins WHERE id = :id AND tenant_id = :t"),
                {"id": DEFAULT_TWIN_ID, "t": db._tenant()},
            )
        )
        if row:
            return _twin_public(row)
        conn.execute(
            text(
                """
                INSERT INTO simulation_twins (id, tenant_id, name, state)
                VALUES (:id, :t, :name, CAST(:state AS jsonb))
                """
            ),
            {
                "id": DEFAULT_TWIN_ID,
                "t": db._tenant(),
                "name": "Bounce chase ladder",
                "state": db._jsonb(DEFAULT_STATE),
            },
        )
    got = get_twin(DEFAULT_TWIN_ID)
    assert got is not None
    return got


def get_twin(twin_id: str) -> dict[str, Any] | None:
    import db

    with db.engine.connect() as conn:
        row = db._one(
            conn.execute(
                text("SELECT * FROM simulation_twins WHERE id = :id AND tenant_id = :t"),
                {"id": twin_id, "t": db._tenant()},
            )
        )
    return _twin_public(row) if row else None


def list_twins() -> list[dict[str, Any]]:
    import db

    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT * FROM simulation_twins
                     WHERE tenant_id = :t
                     ORDER BY created_at
                    """
                ),
                {"t": db._tenant()},
            )
        )
    return [_twin_public(r) for r in rows]


def replay_bounce_ladder(
    twin_id: str | None = None, *, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Chase a bounce on the twin. Never dials. Idempotent per twin+scenario."""
    import db

    twin = get_twin(twin_id or DEFAULT_TWIN_ID) or ensure_default_twin()
    sim = dict(twin.get("state") or DEFAULT_STATE)
    if state:
        sim.update(state)
    outcome = _simulate(sim)
    fixture = {
        "queues": outcome["queues"],
        "ledger": outcome["ledger"],
        "dnd": bool(sim.get("dnd")),
        "dialled": False,
    }
    grader = {
        "bounce_ladder": grade_bounce_ladder(fixture),
        "no_dial": grade_no_dial(fixture),
    }
    passed = all(v.get("passed") for v in grader.values())
    run_id = f"twr-{uuid.uuid4().hex[:12]}"
    key = idempotency_key(workflow_type="twin_bounce", trigger_ref=twin["id"])
    with db.engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO twin_runs (
                  id, tenant_id, twin_id, scenario, status, outcome, grader
                ) VALUES (
                  :id, :t, :twin, 'bounce_ladder', :st,
                  CAST(:outcome AS jsonb), CAST(:grader AS jsonb)
                )
                """
            ),
            {
                "id": run_id,
                "t": db._tenant(),
                "twin": twin["id"],
                "st": "completed",
                "outcome": db._jsonb(outcome),
                "grader": db._jsonb({"passed": passed, **grader, "idempotencyKey": key}),
            },
        )
    return {
        "id": run_id,
        "twinId": twin["id"],
        "scenario": "bounce_ladder",
        "status": "completed",
        "outcome": outcome,
        "grader": {"passed": passed, **grader},
    }


def latest_gate_report() -> dict[str, Any] | None:
    """Shape the compiler G11 gate understands: ``{id, status}``."""
    import db

    try:
        with db.engine.connect() as conn:
            row = db._one(
                conn.execute(
                    text(
                        """
                        SELECT id, grader FROM twin_runs
                         WHERE tenant_id = :t
                         ORDER BY created_at DESC
                         LIMIT 1
                        """
                    ),
                    {"t": db._tenant()},
                )
            )
    except Exception:
        return None
    if not row:
        return None
    grader = row.get("grader") or {}
    passed = bool(grader.get("passed")) if isinstance(grader, dict) else False
    return {"id": row["id"], "status": "pass" if passed else "fail"}


def _simulate(state: dict[str, Any]) -> dict[str, Any]:
    queues = {
        "whatsapp": list((state.get("queues") or {}).get("whatsapp") or []),
        "sms": list((state.get("queues") or {}).get("sms") or []),
        "voice": list((state.get("queues") or {}).get("voice") or []),
    }
    ledger = dict(state.get("ledger") or {})
    dnd = bool(state.get("dnd"))
    if state.get("bounce") and not dnd:
        # One WhatsApp chase. Never a second, never a dial.
        if not queues["whatsapp"]:
            queues["whatsapp"].append(
                {"kind": "bounce_chase", "channel": "whatsapp", "hour": 0}
            )
        ledger["lastEvent"] = "bounce_chase_whatsapp"
    elif state.get("bounce") and dnd:
        ledger["lastEvent"] = "suppressed_dnd"
    return {
        "queues": queues,
        "ledger": ledger,
        "dialled": False,
        "doubleSms": len(queues["sms"]) > 1,
    }


def _twin_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "state": row.get("state") or {},
        "createdAt": str(row["created_at"]) if row.get("created_at") else None,
        "updatedAt": str(row["updated_at"]) if row.get("updated_at") else None,
    }
