"""Twin corpus grows from production *outcomes* (PTP kept), never raw audio."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import text

from agent_core.eval.fixtures import TWIN_COLLECTIONS_ID

_AUDIO_KEYS = frozenset({"audio", "recordingUrl", "raw_audio", "recording_url", "wav"})


def _scrub(outcome: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in outcome.items() if k not in _AUDIO_KEYS}


def list_corpus(*, limit: int = 50) -> list[dict[str, Any]]:
    import db

    with db.engine.connect() as conn:
        if not _table(conn):
            return []
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT id, source, source_ref, outcome, task_id, created_at
                      FROM twin_corpus
                     WHERE tenant_id = :t
                     ORDER BY created_at DESC
                     LIMIT :n
                    """
                ),
                {"t": db._tenant(), "n": max(1, min(int(limit), 200))},
            )
        )
    return [_public(r) for r in rows]


def grow_from_kept_promises(*, limit: int = 20) -> dict[str, Any]:
    """Insert capability/twin tasks from kept PTPs. Human still owns graduation."""
    import db

    created = 0
    skipped = 0
    with db.engine.begin() as conn:
        if not _table(conn):
            raise KeyError("twin_corpus_missing")
        _ensure_twin_suite(conn)
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT p.id, p.amount, p.promised_at, p.status
                      FROM promises p
                      JOIN customers c ON c.id = p.customer_id
                     WHERE c.tenant_id = :t AND p.status = 'kept'
                     ORDER BY p.updated_at DESC NULLS LAST, p.id
                     LIMIT :n
                    """
                ),
                {"t": db._tenant(), "n": max(1, min(int(limit), 100))},
            )
        )
        for row in rows:
            promised = row.get("promised_at")
            outcome = _scrub(
                {
                    "promiseId": row["id"],
                    "amount": float(row["amount"]) if row.get("amount") is not None else None,
                    "promise_date": str(promised)[:10] if promised else None,
                    "status": "kept",
                }
            )
            task_id = _task_id(str(row["id"]))
            conn.execute(
                text(
                    """
                    INSERT INTO eval_tasks (id, suite_id, name, grader, fixture, pass_bar)
                    VALUES (
                      :id, :suite, :name, 'ptp_row', CAST(:fixture AS jsonb), 'all'
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": task_id,
                    "suite": TWIN_COLLECTIONS_ID,
                    "name": f"PTP kept {str(row['id'])[-8:]}",
                    "fixture": db._jsonb(
                        {
                            "amount": outcome.get("amount"),
                            "promise_date": outcome.get("promise_date"),
                            "promise": {
                                "id": outcome.get("promiseId"),
                                "amount": outcome.get("amount"),
                                "promise_date": outcome.get("promise_date"),
                                "status": "kept",
                            },
                        }
                    ),
                },
            )
            inserted = conn.execute(
                text(
                    """
                    INSERT INTO twin_corpus (
                      id, tenant_id, source, source_ref, outcome, task_id
                    ) VALUES (
                      :id, :t, 'ptp_kept', :ref, CAST(:outcome AS jsonb), :task
                    )
                    ON CONFLICT (tenant_id, source, source_ref) DO NOTHING
                    """
                ),
                {
                    "id": f"tcx-{hashlib.sha256(str(row['id']).encode()).hexdigest()[:12]}",
                    "t": db._tenant(),
                    "ref": str(row["id"]),
                    "outcome": db._jsonb(outcome),
                    "task": task_id,
                },
            )
            if inserted.rowcount == 0:
                skipped += 1
                continue
            created += 1
    return {"created": created, "skipped": skipped, "source": "ptp_kept"}


def _ensure_twin_suite(conn: Any) -> None:
    import db

    exists = db._one(
        conn.execute(
            text("SELECT 1 FROM eval_suites WHERE id = :id AND tenant_id = :t"),
            {"id": TWIN_COLLECTIONS_ID, "t": db._tenant()},
        )
    )
    if exists:
        return
    conn.execute(
        text(
            """
            INSERT INTO eval_suites (id, tenant_id, kind, name, description)
            VALUES (:id, :t, 'twin', 'Collections twin outcomes', 'Grown from kept PTPs')
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": TWIN_COLLECTIONS_ID, "t": db._tenant()},
    )


def _task_id(source_ref: str) -> str:
    digest = hashlib.sha256(source_ref.encode()).hexdigest()[:10]
    return f"task-twin-kept-{digest}"


def _table(conn: Any) -> bool:
    row = conn.execute(text("SELECT to_regclass('public.twin_corpus') AS t")).mappings().first()
    return bool(row and row["t"])


def _public(row: dict[str, Any]) -> dict[str, Any]:
    outcome = _scrub(dict(row.get("outcome") or {}))
    return {
        "id": row["id"],
        "source": row["source"],
        "sourceRef": row["source_ref"],
        "outcome": outcome,
        "taskId": row.get("task_id"),
        "createdAt": str(row["created_at"]) if row.get("created_at") else None,
    }
