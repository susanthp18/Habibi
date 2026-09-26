"""MCP draft-tool edits through the same validation path as REST."""

from __future__ import annotations

from typing import Any

from api.mcp_server.auth import authenticate_mcp_request
from api.mcp_server.tracing import traced_tool
from api.schemas.tool import UpdateToolRequest
from api.services.tool_management import ToolManagementError, update_tool_for_user


@traced_tool
async def update_tool(tool_uuid: str, request: UpdateToolRequest) -> dict[str, Any]:
    """Edit a Voice Studio tool draft by UUID using its latest base_revision.

    Read the tool and its revisions first, then supply the newest revision
    number as `base_revision`. A changed tool becomes a new draft revision;
    published agents remain pinned to the approved revision they were released
    with. A human must submit and approve this revision in Voice Studio.
    """
    user = await authenticate_mcp_request()
    try:
        updated = await update_tool_for_user(tool_uuid, request, user)
    except ToolManagementError as exc:
        return {"updated": False, "error_code": exc.error_code, "error": exc.message}
    return {"updated": True, "tool_uuid": updated.tool_uuid,
            "name": updated.name, "status": updated.status,
            "definition": updated.definition}
