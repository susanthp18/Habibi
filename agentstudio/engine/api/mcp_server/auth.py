from fastapi import HTTPException
from fastmcp.server.dependencies import get_http_headers
from opentelemetry import trace

from api.db.models import UserModel
from api.constants import AUTH_PROVIDER
from api.services.auth.depends import _handle_api_key_auth, _handle_internal_auth


async def authenticate_mcp_request() -> UserModel:
    """Resolve the authenticated Dograh user for an MCP tool invocation.

    Accepts either `X-API-Key: <key>` or `Authorization: Bearer <key>`,
    reusing the API-key flow from `api.services.auth.depends`.

    Tags the currently-active OTel span with the resolved organization
    and user identifiers. `_OrgRoutingExporter` reads `dograh.org_id`
    at export time to dispatch the span to the right Langfuse project;
    the `langfuse.user.id` / `langfuse.session.id` attributes make the
    span filterable in the Langfuse UI.
    """
    # FastMCP strips Authorization by default unless explicitly included.
    # Preserve it here so Bearer API keys work for MCP tool invocations.
    headers = get_http_headers(include={
        "authorization", "x-internal-secret", "x-user-id", "x-user-email", "x-org-id",
    })
    if AUTH_PROVIDER == "internal":
        user = await _handle_internal_auth(headers)
    else:
        user = await _api_key_user(headers)

    span = trace.get_current_span()
    if span.is_recording():
        org_id = user.selected_organization_id
        span.set_attribute("mcp.org_id", str(org_id))
        span.set_attribute("mcp.user_id", str(user.id))
        span.set_attribute("langfuse.user.id", str(user.id))

    return user


async def _api_key_user(headers: dict[str, str]) -> UserModel:
    api_key = headers.get("x-api-key")
    if not api_key:
        auth = headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            api_key = auth.split(" ", 1)[1].strip()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail="Missing API key — send X-API-Key or Authorization: Bearer <key>",
        )
    return await _handle_api_key_auth(api_key)
