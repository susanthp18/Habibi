"""API routes for managing tools."""

import time

from fastapi import APIRouter, Depends, HTTPException

from api.db import db_client
from api.db.models import UserModel
from api.enums import ToolCategory, ToolStatus
from api.schemas.tool import (
    CalculatorToolDefinition,
    CreatedByResponse,
    CreateToolRequest,
    EndCallConfig,
    EndCallToolDefinition,
    HttpApiConfig,
    HttpApiToolDefinition,
    McpRefreshResponse,
    McpToolConfig,
    McpToolDefinition,
    PresetToolParameter,
    ToolDefinition,
    ToolParameter,
    ToolResponse,
    ToolTestRequest,
    ToolTestResponse,
    TransferCallConfig,
    TransferCallToolDefinition,
    UpdateToolRequest,
)
from api.sdk_expose import sdk_expose
from api.services.auth.depends import get_user
from api.services.tool_management import (
    ToolManagementError,
    build_tool_response,
    create_tool_for_user,
    refresh_mcp_tool_for_user,
    update_tool_for_user,
)
from api.services.tool_management import (
    populate_discovered_tools as _populate_discovered_tools,
)
from api.services.workflow.tools.custom_tool import (
    execute_http_tool,
    serialize_query_params,
)

router = APIRouter(prefix="/tools")

__all__ = [
    "CalculatorToolDefinition",
    "CreateToolRequest",
    "CreatedByResponse",
    "EndCallConfig",
    "EndCallToolDefinition",
    "HttpApiConfig",
    "HttpApiToolDefinition",
    "McpRefreshResponse",
    "McpToolConfig",
    "McpToolDefinition",
    "PresetToolParameter",
    "ToolDefinition",
    "ToolParameter",
    "ToolResponse",
    "ToolTestRequest",
    "ToolTestResponse",
    "TransferCallConfig",
    "TransferCallToolDefinition",
    "UpdateToolRequest",
    "_populate_discovered_tools",
]


def validate_category(category: str) -> None:
    """Validate that the category is valid."""
    valid_categories = [c.value for c in ToolCategory]
    if category not in valid_categories:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{category}'. Must be one of: {', '.join(valid_categories)}",
        )


def validate_status(status: str) -> None:
    """Validate that the status is valid. Supports comma-separated values."""
    valid_statuses = [s.value for s in ToolStatus]
    status_list = [s.strip() for s in status.split(",")]
    for s in status_list:
        if s not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status '{s}'. Must be one of: {', '.join(valid_statuses)}",
            )


@router.get(
    "/",
    **sdk_expose(
        method="list_tools",
        description="List tools available to the authenticated organization.",
    ),
)
async def list_tools(
    status: str | None = None,
    category: str | None = None,
    user: UserModel = Depends(get_user),
) -> list[ToolResponse]:
    """
    List all tools for the user's organization.

    Args:
        status: Optional filter by status (active, archived, draft)
        category: Optional filter by category (http_api, native, integration)

    Returns:
        List of tools
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    if status:
        validate_status(status)
    if category:
        validate_category(category)

    tools = await db_client.get_tools_for_organization(
        user.selected_organization_id,
        status=status,
        category=category,
    )

    return [build_tool_response(tool) for tool in tools]


@router.post(
    "/",
    **sdk_expose(
        method="create_tool",
        description="Create a reusable tool for the authenticated organization.",
    ),
)
async def create_tool(
    request: CreateToolRequest,
    user: UserModel = Depends(get_user),
) -> ToolResponse:
    """
    Create a new tool.

    Args:
        request: The tool creation request

    Returns:
        The created tool
    """
    try:
        return await create_tool_for_user(request, user, source="api")
    except ToolManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@router.get("/{tool_uuid}")
async def get_tool(
    tool_uuid: str,
    user: UserModel = Depends(get_user),
) -> ToolResponse:
    """
    Get a specific tool by UUID.

    Args:
        tool_uuid: The UUID of the tool

    Returns:
        The tool
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    tool = await db_client.get_tool_by_uuid(
        tool_uuid, user.selected_organization_id, include_archived=True
    )

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    return build_tool_response(tool, include_created_by=True)


@router.post("/{tool_uuid}/mcp/refresh")
async def refresh_mcp_tools(
    tool_uuid: str,
    user: UserModel = Depends(get_user),
) -> McpRefreshResponse:
    """Re-discover an MCP tool's server catalog and overwrite the cached
    ``definition.config.discovered_tools``. Server down → 200 with error
    (cache not overwritten on transient failure)."""
    try:
        return await refresh_mcp_tool_for_user(tool_uuid, user)
    except ToolManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@router.post("/{tool_uuid}/test")
async def test_tool(
    tool_uuid: str,
    request: ToolTestRequest,
    user: UserModel = Depends(get_user),
) -> ToolTestResponse:
    """Execute an HTTP API tool with sample LLM and preset parameters."""
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    tool = await db_client.get_tool_by_uuid(
        tool_uuid, user.selected_organization_id, include_archived=True
    )

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    if tool.category != ToolCategory.HTTP_API.value:
        raise HTTPException(status_code=400, detail="Only HTTP API tools can be tested")

    from api.services.tool_revisions import validate_external_destination
    try:
        validate_external_destination(str((tool.definition or {}).get("config", {}).get("url") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Tool test destination: {exc}") from exc

    tool_config = (
        tool.definition.get("config", {}) if isinstance(tool.definition, dict) else {}
    )
    configured_method = tool_config.get("method", "?").upper()
    configured_url = tool_config.get("url", "?")

    started_at = time.perf_counter()
    result = await execute_http_tool(
        tool,
        request.llm_params,
        preset_params=request.preset_params,
        organization_id=user.selected_organization_id,
        include_request_headers=True,
        secure_destination=True,
    )
    duration_ms = max(0, round((time.perf_counter() - started_at) * 1000))

    status = result.get("status", "error")
    status_code = result.get("status_code")
    if status_code is not None and status_code >= 400:
        status = "error"

    hint = _hint_for_status_code(status_code, configured_method)

    # Model-supplied values take precedence over context-derived presets,
    # matching live execution. URL variables remain in the body/query.
    resolved_arguments = {**request.preset_params, **request.llm_params}

    request_body = None
    request_params = None
    if configured_method in ("POST", "PUT", "PATCH"):
        request_body = result.get("request_body_preview", resolved_arguments)
    elif resolved_arguments:
        request_params = serialize_query_params(resolved_arguments)

    return ToolTestResponse(
        status=status,
        status_code=status_code,
        data=result.get("data"),
        error=result.get("error"),
        duration_ms=duration_ms,
        hint=hint,
        request_method=configured_method,
        request_url=result.get("rendered_url") or configured_url,
        request_headers=result.get("request_headers", {}),
        request_body=request_body,
        request_params=request_params,
    )


def _hint_for_status_code(
    status_code: int | None, configured_method: str
) -> str | None:
    """Human-readable explanation for a status code a misconfigured tool
    is likely to hit. Returns None for 2xx and any code not covered."""
    if status_code == 400:
        return (
            "HTTP 400 Bad Request — the server rejected the request payload. "
            "Verify the arguments/body match what this endpoint expects."
        )
    if status_code == 401:
        return (
            "HTTP 401 Unauthorized — the request wasn't authenticated. Check "
            "the credential configured on the Authentication tab is present "
            "and valid."
        )
    if status_code == 403:
        return (
            "HTTP 403 Forbidden — authenticated, but the configured "
            "credential doesn't have permission for this endpoint/action."
        )
    if status_code == 404:
        return (
            f"HTTP 404 Not Found — verify the endpoint URL is correct and "
            f"that {configured_method} is a valid method for it."
        )
    if status_code == 405:
        return (
            f"HTTP 405 Method Not Allowed — the endpoint rejected the "
            f"configured method ({configured_method}). Verify the API expects "
            f"{configured_method} for this URL."
        )
    if status_code == 408:
        return (
            "HTTP 408 Request Timeout — the endpoint didn't respond in time. "
            "Check the endpoint is reachable, or increase Timeout (ms) if it's "
            "just slow."
        )
    if status_code == 409:
        return (
            "HTTP 409 Conflict — the endpoint rejected the request due to a "
            "conflicting resource state (e.g. duplicate create). Not "
            "necessarily a configuration problem."
        )
    if status_code == 415:
        return (
            "HTTP 415 Unsupported Media Type — check the Content-Type header "
            "matches the format this endpoint expects for the body."
        )
    if status_code == 422:
        return (
            "HTTP 422 Unprocessable Entity — the request was well-formed but "
            "the payload's structure or field types don't match what this "
            "endpoint expects. Compare your arguments against the API's "
            "documented schema."
        )
    if status_code == 429:
        return (
            "HTTP 429 Too Many Requests — the endpoint is rate-limiting. Wait "
            "and retry; not a configuration problem."
        )
    if status_code is not None and 500 <= status_code < 600:
        return (
            f"HTTP {status_code} — the endpoint itself errored. This is "
            "likely an issue on the API's side, not your tool configuration."
        )
    return None


@router.put("/{tool_uuid}")
async def update_tool(
    tool_uuid: str,
    request: UpdateToolRequest,
    user: UserModel = Depends(get_user),
) -> ToolResponse:
    """
    Update a tool.

    Args:
        tool_uuid: The UUID of the tool to update
        request: The update request

    Returns:
        The updated tool
    """
    try:
        return await update_tool_for_user(tool_uuid, request, user)
    except ToolManagementError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/{tool_uuid}/revisions")
async def list_tool_revisions(tool_uuid: str, user: UserModel = Depends(get_user)) -> list[dict]:
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    rows = await db_client.get_tool_revisions(tool_uuid, user.selected_organization_id)
    usage = await db_client.get_tool_revision_usage(tool_uuid, user.selected_organization_id)
    return [{"revision": r.revision, "digest": r.digest, "state": r.state,
             "snapshot": r.snapshot, "policy": r.policy, "authoredBy": r.authored_by,
             "reviewedBy": r.reviewed_by, "createdAt": r.created_at.isoformat(),
             "publishedUsage": usage.get(r.revision, 0)}
            for r in rows]


@router.post("/{tool_uuid}/revisions/{revision}/submit")
async def submit_tool_revision(tool_uuid: str, revision: int, request: dict,
                               user: UserModel = Depends(get_user)) -> dict:
    from api.services.tool_revisions import LiveToolPolicy, validate_live_snapshot

    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    rows = await db_client.get_tool_revisions(tool_uuid, user.selected_organization_id)
    row = next((r for r in rows if r.revision == revision), None)
    if row is None or row != rows[0]:
        raise HTTPException(status_code=404, detail="Latest tool revision not found")
    try:
        policy = LiveToolPolicy.model_validate(request)
        validate_live_snapshot(row.snapshot, policy)
        reviewed = await db_client.review_tool_revision(
            tool_uuid, revision, user.selected_organization_id,
            actor_id=user.id, state="submitted", policy=policy.model_dump(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"toolUuid": tool_uuid, "revision": revision, "state": reviewed.state,
            "digest": reviewed.digest}


@router.post("/{tool_uuid}/revisions/{revision}/review")
async def review_tool_revision(tool_uuid: str, revision: int, request: dict,
                               user: UserModel = Depends(get_user)) -> dict:
    """Internal-only; the PayInt review endpoint owns human authorization."""
    from api.constants import AUTH_PROVIDER

    if AUTH_PROVIDER != "internal":
        raise HTTPException(status_code=404, detail="Not found")
    if not user.selected_organization_id:
        raise HTTPException(status_code=400, detail="No organization selected")
    state = request.get("decision")
    if state not in {"approved", "rejected", "revoked"}:
        raise HTTPException(status_code=400, detail="Invalid review decision")
    if state == "approved":
        from api.services.tool_revisions import (
            LiveToolPolicy, snapshot_digest, validate_live_snapshot,
        )
        from api.services.workflow.mcp_tool_session import discover_mcp_tools
        from api.services.workflow.tools.mcp_tool import validate_mcp_definition
        from api.services.tool_management import fetch_credential, validate_tool_references

        rows = await db_client.get_tool_revisions(tool_uuid, user.selected_organization_id)
        row = next((entry for entry in rows if entry.revision == revision), None)
        if row is None or row != rows[0] or row.state != "submitted":
            raise HTTPException(status_code=409, detail="Review the latest submitted revision")
        try:
            if snapshot_digest(row.snapshot) != row.digest:
                raise ValueError("Tool revision digest mismatch")
            policy = LiveToolPolicy.model_validate(row.policy)
            validate_live_snapshot(row.snapshot, policy)
            definition = row.snapshot.get("definition") or {}
            await validate_tool_references(definition, organization_id=user.selected_organization_id)
            if row.snapshot.get("category") == ToolCategory.MCP.value:
                config = validate_mcp_definition(definition)
                credential = await fetch_credential(config.get("credential_uuid"), user.selected_organization_id)
                current = await discover_mcp_tools(
                    url=config["url"], credential=credential,
                    timeout_secs=config["timeout_secs"],
                    sse_read_timeout_secs=config["sse_read_timeout_secs"],
                    secure_destination=True,
                )
                discovered = {item["name"]: item["schema_digest"] for item in current}
                if not current or any(discovered.get(name) != digest
                                      for name, digest in policy.allowed_mcp_functions.items()):
                    raise ValueError("MCP function schema changed since submission")
        except (ValueError, ToolManagementError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        row = await db_client.review_tool_revision(
            tool_uuid, revision, user.selected_organization_id,
            actor_id=user.id, state=state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Tool revision not found")
    return {"toolUuid": tool_uuid, "revision": revision, "state": row.state,
            "digest": row.digest}


@router.delete("/{tool_uuid}")
async def delete_tool(
    tool_uuid: str,
    user: UserModel = Depends(get_user),
) -> dict:
    """
    Archive (soft delete) a tool.

    Args:
        tool_uuid: The UUID of the tool to delete

    Returns:
        Success message
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    deleted = await db_client.archive_tool(tool_uuid, user.selected_organization_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Tool not found")

    return {"status": "archived", "tool_uuid": tool_uuid}


@router.post("/{tool_uuid}/unarchive")
async def unarchive_tool(
    tool_uuid: str,
    user: UserModel = Depends(get_user),
) -> ToolResponse:
    """
    Unarchive a tool (restore from archived state).

    Args:
        tool_uuid: The UUID of the tool to unarchive

    Returns:
        The unarchived tool
    """
    if not user.selected_organization_id:
        raise HTTPException(
            status_code=400, detail="No organization selected for the user"
        )

    tool = await db_client.unarchive_tool(tool_uuid, user.selected_organization_id)

    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")

    return build_tool_response(tool)
