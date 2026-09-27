"""Read immutable tool revision history before drafting an MCP edit."""

from __future__ import annotations

from api.db import db_client
from api.mcp_server.auth import authenticate_mcp_request
from api.mcp_server.tracing import traced_tool
from api.services.tool_revisions import submit_revision


@traced_tool
async def get_tool_revisions(tool_uuid: str) -> list[dict]:
    """List a tool's draft, submitted, approved and revoked revisions.

    The first entry has the latest revision number for update_tool.base_revision.
    """
    user = await authenticate_mcp_request()
    if not user.selected_organization_id:
        return []
    rows = await db_client.get_tool_revisions(tool_uuid, user.selected_organization_id)
    return [{"revision": r.revision, "digest": r.digest, "state": r.state,
             "snapshot": r.snapshot, "policy": r.policy} for r in rows]


@traced_tool
async def submit_tool_revision(tool_uuid: str, revision: int, policy: dict) -> dict:
    """Submit a tool's latest draft revision for human review, with its live policy.

    Submitting is not approving: a named reviewer approves in Voice Studio,
    and a released agent can only call an approved revision.

    `revision` must be the latest (first entry of `get_tool_revisions`).
    `policy` fields:
    - `risk`: "read" | "write" | "platform" ("platform" only for PayInt's own handlers).
    - `channels`: any of "inbound", "outbound", "whatsapp".
    - `min_identity`: "none" | "endpoint" | "challenge" (write tools need "challenge").
    - `egress_fields`: context paths the tool may receive; must cover every
      `{{...}}` the tool's templates read.
    - `success_path` / `success_value`, `error_code_path`: where the result says ok.
    - `idempotency_parameter`: required for write tools.
    - `allowed_mcp_functions`: MCP tools only, name -> schema digest.
    - `result_schema`: JSON Schema of the result (read and write tools).

    On failure the result has `submitted: false`, an `error_code` and an `error`:
    - `not_latest` — `revision` is not the tool's latest revision.
    - `invalid_policy` — the policy is incomplete or the tool cannot satisfy it.
    """
    user = await authenticate_mcp_request()
    try:
        row = await submit_revision(
            tool_uuid, revision, user.selected_organization_id, user.id, policy,
        )
    except LookupError as e:
        return {"submitted": False, "error_code": "not_latest", "error": str(e)}
    except ValueError as e:
        return {"submitted": False, "error_code": "invalid_policy", "error": str(e)}
    return {"submitted": True, "tool_uuid": tool_uuid, "revision": revision,
            "state": row.state, "digest": row.digest}
