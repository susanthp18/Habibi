"""Read immutable tool revision history before drafting an MCP edit."""

from __future__ import annotations

from api.db import db_client
from api.mcp_server.auth import authenticate_mcp_request
from api.mcp_server.tracing import traced_tool


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
