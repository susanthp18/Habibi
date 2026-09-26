"""Human review boundary for immutable Voice Studio tool revisions."""

from __future__ import annotations

import uuid
from typing import Any

import voice_studio
import voice_studio_routing


def _revision(tool_uuid: str, revision: int) -> tuple[dict[str, Any], dict[str, Any]]:
    rows = voice_studio.engine_call("GET", f"/tools/{tool_uuid}/revisions") or []
    current = next((row for row in rows if row.get("revision") == revision), None)
    if current is None:
        raise ValueError("Tool revision was not found in this tenant")
    return rows[-1], current


def _check_approval(first: dict[str, Any], current: dict[str, Any]) -> None:
    snapshot = current.get("snapshot") or {}
    policy = current.get("policy") or {}
    original_name = str((first.get("snapshot") or {}).get("name") or "")
    name = str(snapshot.get("name") or "")
    protected = original_name in voice_studio_routing.APPROVED_ARGUMENTS or name in voice_studio_routing.APPROVED_ARGUMENTS
    if protected:
        if name != original_name or policy.get("risk") != "platform":
            raise ValueError("Protected PayInt tool identity and risk cannot change")
        errors = voice_studio_routing._check_tool(snapshot, voice_studio_routing._hook_credential())
        if errors:
            raise ValueError("; ".join(errors))
    elif policy.get("risk") == "platform":
        raise ValueError("Only validated PayInt handlers may use platform risk")
    elif snapshot.get("category") not in {"http_api", "mcp"}:
        raise ValueError("Customer live tools must be HTTP or MCP")


def review(tool_uuid: str, revision: int, decision: str, actor: str) -> dict[str, Any]:
    """Audit intent durably before the engine decision, then audit its outcome."""
    if decision not in {"approved", "rejected", "revoked"}:
        raise ValueError("Invalid review decision")
    first, current = _revision(tool_uuid, revision)
    if decision == "approved":
        if current.get("state") != "submitted":
            raise ValueError("Only a submitted revision can be approved")
        _check_approval(first, current)
    elif decision == "rejected" and current.get("state") != "submitted":
        raise ValueError("Only a submitted revision can be rejected")
    elif decision == "revoked" and current.get("state") not in {"approved", "legacy"}:
        raise ValueError("Only a callable revision can be revoked")

    import db
    from agent_core import change_log

    path = f"/tools/{tool_uuid}/revisions/{revision}/{decision}/{current['digest']}"
    with db.engine.begin() as conn:
        change_log.record_agentstudio_change(
            conn, tenant_id=db.current_tenant(), actor_user_id=actor,
            entry_id=f"as-{uuid.uuid4().hex}", method="POST", path=path, status=202,
        )
    try:
        result = voice_studio.engine_call(
            "POST", f"/tools/{tool_uuid}/revisions/{revision}/review",
            json={"decision": decision}, actor=actor,
        )
    except Exception:
        with db.engine.begin() as conn:
            change_log.record_agentstudio_change(
                conn, tenant_id=db.current_tenant(), actor_user_id=actor,
                entry_id=f"as-{uuid.uuid4().hex}", method="POST", path=path, status=502,
            )
        raise
    with db.engine.begin() as conn:
        change_log.record_agentstudio_change(
            conn, tenant_id=db.current_tenant(), actor_user_id=actor,
            entry_id=f"as-{uuid.uuid4().hex}", method="POST", path=path, status=200,
        )
    return result
