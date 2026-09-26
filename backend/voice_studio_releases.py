"""Voice Studio releases: publish with a changelog note, roll back, list history.

The engine keeps every version of an agent (workflow definitions). PayInt adds
the release gate (voice_studio_routing.validate_publish), who released what and
why (voice_studio_releases), and rollback: an earlier version is copied into the
draft server-side and published as the next version, so history only grows.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import text

import voice_studio
import voice_studio_routing


def _versions(workflow_id: int) -> list[dict[str, Any]]:
    return voice_studio.engine_call("GET", f"/workflow/{workflow_id}/versions") or []


def _live(versions: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((v for v in versions if v.get("status") == "published"), None)


def _note(note: Any) -> str:
    note = str(note or "").strip()
    if len(note) < 3:
        raise ValueError("Describe what changed (at least a few words)")
    return note[:2000]


def _gate(workflow_id: int) -> dict[str, Any]:
    try:
        return voice_studio_routing.validate_publish(workflow_id)
    except ValueError as exc:
        return {"ok": False, "errors": [str(exc)], "channels": []}


def _record(workflow_id: int, action: str, version: int | None, from_version: int | None,
            note: str, actor: str | None) -> dict[str, Any]:
    import db

    tenant = db.current_tenant()
    stable_id = uuid.uuid5(uuid.NAMESPACE_URL, f"voice-studio-release:{tenant}:{workflow_id}:{action}:{version}")
    row = {"id": f"vsr-{stable_id.hex}", "t": tenant, "w": workflow_id,
           "v": version, "f": from_version, "a": action, "n": note, "u": actor}
    with db.engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO voice_studio_releases
              (id, tenant_id, engine_workflow_id, version_number, from_version, action, note, actor_user_id)
            VALUES (:id, :t, :w, :v, :f, :a, :n, :u)
            ON CONFLICT (id) DO NOTHING
        """), row)
    return {"id": row["id"], "workflowId": workflow_id, "action": action,
            "version": version, "fromVersion": from_version, "note": note}


def _pending(workflow_id: int | None = None) -> list[dict[str, Any]]:
    import db

    where = "tenant_id = :tenant AND status = 'pending'"
    if workflow_id is not None:
        where += " AND engine_workflow_id = :workflow"
    with db.engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT id, engine_workflow_id, engine_definition_id, action,
                   from_version, intended_version, note, actor_user_id
            FROM voice_studio_release_attempts WHERE {where}
            ORDER BY created_at
        """), {"tenant": db.current_tenant(), "workflow": workflow_id}).mappings().all()
    return [dict(row) for row in rows]


def _begin(workflow_id: int, definition_id: int, action: str,
           before: dict[str, Any] | None, draft: dict[str, Any],
           note: str, actor: str | None) -> str:
    import db

    attempt_id = f"vsa-{uuid.uuid4().hex}"
    with db.engine.begin() as conn:
        inserted = conn.execute(text("""
            INSERT INTO voice_studio_release_attempts
              (id, tenant_id, engine_workflow_id, engine_definition_id, action,
               from_version, intended_version, note, actor_user_id)
            VALUES (:id, :tenant, :workflow, :definition, :action, :before,
                    :intended, :note, :actor)
            ON CONFLICT (tenant_id, engine_workflow_id, engine_definition_id, action)
              WHERE status = 'pending' DO NOTHING
            RETURNING id
        """), {"id": attempt_id, "tenant": db.current_tenant(), "workflow": workflow_id,
               "definition": definition_id, "action": action,
               "before": before.get("version_number") if before else None,
               "intended": draft.get("version_number"), "note": note, "actor": actor}).scalar_one_or_none()
    if inserted is None:
        raise RuntimeError("This agent definition already has a release attempt; reconcile it first")
    return attempt_id


def _fail(attempt_id: str) -> None:
    import db

    with db.engine.begin() as conn:
        conn.execute(text("""
            UPDATE voice_studio_release_attempts
            SET status = 'failed', completed_at = now()
            WHERE id = :id AND tenant_id = :tenant AND status = 'pending'
        """), {"id": attempt_id, "tenant": db.current_tenant()})


def _complete(attempt: dict[str, Any], version: int | None) -> dict[str, Any]:
    import db

    result = _record(attempt["engine_workflow_id"], attempt["action"], version,
                     attempt["from_version"], attempt["note"], attempt["actor_user_id"])
    with db.engine.begin() as conn:
        conn.execute(text("""
            UPDATE voice_studio_release_attempts
            SET status = 'completed', result_version = :version, completed_at = now()
            WHERE id = :id AND tenant_id = :tenant AND status = 'pending'
        """), {"id": attempt["id"], "tenant": db.current_tenant(), "version": version})
    return result


def reconcile_pending(workflow_id: int | None = None) -> list[dict[str, Any]]:
    """Match pending intents to the exact engine definition promoted by release."""
    outcomes = []
    versions_by_workflow: dict[int, dict[int, dict[str, Any]]] = {}
    for attempt in _pending(workflow_id):
        workflow = attempt["engine_workflow_id"]
        if workflow not in versions_by_workflow:
            versions_by_workflow[workflow] = {v["id"]: v for v in _versions(workflow)}
        definition = versions_by_workflow[workflow].get(attempt["engine_definition_id"])
        if definition and definition.get("status") in {"published", "archived"}:
            _complete(attempt, definition.get("version_number"))
            outcomes.append({"id": attempt["id"], "status": "completed"})
        else:
            outcomes.append({"id": attempt["id"], "status": "pending"})
    return outcomes


def _require_no_pending(workflow_id: int) -> None:
    reconcile_pending(workflow_id)
    if _pending(workflow_id):
        raise RuntimeError("A previous release is pending; inspect and reconcile its engine definition")


def _finish_attempt(attempt_id: str, workflow_id: int, definition_id: int,
                    action: str, before: dict[str, Any] | None,
                    note: str, actor: str | None, version: int | None) -> dict[str, Any]:
    if not isinstance(version, int):
        raise RuntimeError("Engine release returned no version; reconcile the pending attempt")
    return _complete({"id": attempt_id, "engine_workflow_id": workflow_id,
                      "engine_definition_id": definition_id, "action": action,
                      "from_version": before.get("version_number") if before else None,
                      "note": note, "actor_user_id": actor}, version)


def _publish_engine(workflow_id: int, attempt_id: str) -> dict[str, Any]:
    try:
        return voice_studio.engine_call("POST", f"/workflow/{workflow_id}/publish") or {}
    except httpx.HTTPStatusError as exc:
        if 400 <= exc.response.status_code < 500:
            _fail(attempt_id)  # Engine rejected before its publish transaction committed.
        raise


def preflight(workflow_id: int) -> dict[str, Any]:
    """What the publish dialog shows: the gate, the live version and the last checks run."""
    import voice_studio_checks

    gate = _gate(workflow_id)
    versions = _versions(workflow_id)
    draft = next((v for v in versions if v.get("status") == "draft"), None)
    live = _live(versions)
    last = next(iter(voice_studio_checks.runs(workflow_id) or []), None)
    return {**gate,
            "draftVersion": draft.get("version_number") if draft else None,
            "liveVersion": live.get("version_number") if live else None,
            "liveVersionId": live.get("id") if live else None,
            "lastCheck": None if last is None else {
                "status": last.get("status"), "passed": last.get("passed"),
                "failed": last.get("failed"), "createdAt": last.get("createdAt")}}


def publish(workflow_id: int, note: Any, actor: str | None) -> dict[str, Any]:
    note = _note(note)
    _require_no_pending(workflow_id)
    gate = _gate(workflow_id)
    if not gate["ok"]:
        raise PermissionError("; ".join(gate["errors"]))
    versions = _versions(workflow_id)
    before = _live(versions)
    draft = next((v for v in versions if v.get("status") == "draft"), None)
    if draft is None:
        raise ValueError("No draft to publish")
    attempt = _begin(workflow_id, draft["id"], "publish", before, draft, note, actor)
    published = _publish_engine(workflow_id, attempt)
    if published.get("id") != draft["id"] or published.get("status") != "published":
        raise RuntimeError("Engine release response did not match the reviewed draft; reconcile the pending attempt")
    return _finish_attempt(attempt, workflow_id, draft["id"], "publish", before,
                           note, actor, published.get("version_number"))


def rollback(workflow_id: int, version_id: int, note: Any, actor: str | None) -> dict[str, Any]:
    note = _note(note)
    _require_no_pending(workflow_id)
    versions = _versions(workflow_id)
    target = next((v for v in versions if v.get("id") == version_id), None)
    if target is None or target.get("status") not in {"published", "archived"}:
        raise ValueError("Choose an earlier released version")
    live = _live(versions)
    if live and live.get("id") == version_id:
        raise ValueError("That version is already live")
    # Replaces the current draft with the target version, then releases it.
    voice_studio.engine_call("POST", f"/workflow/{workflow_id}/versions/{version_id}/restore")
    gate = _gate(workflow_id)
    if not gate["ok"]:
        raise PermissionError("Version %s no longer passes the release checks: %s"
                              % (target.get("version_number"), "; ".join(gate["errors"])))
    draft = next((v for v in _versions(workflow_id) if v.get("status") == "draft"), None)
    if draft is None:
        raise ValueError("Restored definition has no draft")
    note = f"Rolled back to version {target.get('version_number')}: {note}"
    attempt = _begin(workflow_id, draft["id"], "rollback", live, draft, note, actor)
    published = _publish_engine(workflow_id, attempt)
    if published.get("id") != draft["id"] or published.get("status") != "published":
        raise RuntimeError("Engine release response did not match the restored draft; reconcile the pending attempt")
    return _finish_attempt(attempt, workflow_id, draft["id"], "rollback", live,
                           note, actor, published.get("version_number"))


def history(workflow_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    import db

    where = "r.tenant_id = :t" + (" AND r.engine_workflow_id = :w" if workflow_id is not None else "")
    with db.engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT r.id, r.engine_workflow_id, r.version_number, r.from_version, r.action, r.note,
                   r.created_at, COALESCE(u.name, u.email, r.actor_user_id) AS actor
            FROM voice_studio_releases r LEFT JOIN users u ON u.id = r.actor_user_id
            WHERE {where} ORDER BY r.created_at DESC LIMIT :n
        """), {"t": db.current_tenant(), "w": workflow_id, "n": max(1, min(int(limit), 200))}).mappings()
        return [{"id": r["id"], "workflowId": r["engine_workflow_id"], "version": r["version_number"],
                 "fromVersion": r["from_version"], "action": r["action"], "note": r["note"],
                 "actor": r["actor"], "createdAt": r["created_at"].isoformat()} for r in rows]
