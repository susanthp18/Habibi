"""Platform: health, readiness, metrics, me, switches, dashboard.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db
import observability
import storage

from fastapi import APIRouter

from api_support import Utf8JSONResponse, ROUTER_DEPENDENCIES
from fastapi import HTTPException, Response
from schemas import (
    AccessRequestApproveRequest,
    AccessRequestCreateRequest,
    AccessRequestWriteResponse,
    AccessRequestsResponse,
    BotAnalyticsResponse,
    DashboardResponse,
    HealthResponse,
    InviteCreateRequest,
    MeResponse,
    OperatorInviteWriteResponse,
    OperatorInvitesResponse,
    PlatformSwitchFlipResponse,
    PlatformSwitchPatchRequest,
    PlatformSwitchesResponse,
    PresencePatchRequest,
    PresenceResponse,
    ReadinessResponse,
    DirectoryUsersResponse,
    UserRolesPutRequest,
    UserStatusPatchRequest,
)

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
def health():
    """Process liveness — no dependency checks."""
    return {"status": "ok"}

@router.get("/ready", response_model=ReadinessResponse, response_model_exclude_unset=True)
def ready():
    """Readiness: DB ping + pool headroom (+ optional MinIO ping).

    Exhausted pool or hard DB failure → 503 so LBs shed load.
    MinIO unconfigured is OK (KB upload routes fail separately).
    """
    result = db.readiness()
    minio = storage.ping()
    # No breaker dump: a readiness probe is polled by a load balancer every
    # few seconds and answers ok / not ok. The breakers are on /metrics as
    # circuit_breaker_state, where an alert reads them.
    result = {**result, "minio": minio}
    # Only fail readiness on MinIO when it is configured but unreachable.
    if minio.get("configured") and not minio.get("ok"):
        result = {
            **result,
            "ok": False,
            "detail": result.get("detail") or f"minio:{minio.get('detail')}",
        }
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result)
    return result

# Prometheus text exposition by design, not JSON. Listed in
# tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.get("/metrics", include_in_schema=False, response_class=Response)
def metrics():
    """Prometheus exposition.

    Authenticated and permission-gated like every other route, rather than
    exempted the way ``/health`` is: this publishes pool occupancy, breaker
    state and call volume, which is reconnaissance for an attacker and
    commercially sensitive besides. A scraper gets its own ``API_KEY_MAP``
    entry pointing at a service user holding ``perm-observability-read``.
    """
    body, content_type = observability.render()
    return Response(content=body, media_type=content_type)

@router.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(range: str = "30d", segment: str = "all", team: str = "all"):
    return db.get_dashboard(range, segment, team)


# CSV download by design. Listed in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.get("/dashboard.csv", response_class=Response)
def export_dashboard_csv(range: str = "30d", segment: str = "all", team: str = "all"):
    csv_body = db.get_dashboard_csv(range, segment, team)
    filename = f"dashboard-{range}-{segment}-{team}.csv"
    return Response(
        content=csv_body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.get("/bot-analytics", response_model=BotAnalyticsResponse)
def get_bot_analytics(range: str = "30d", channel: str = "all"):
    """Live aggregates from interactions — not the stub analytics_* tables."""
    try:
        return db.bot_analytics(range, channel)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.get("/me", response_model=MeResponse)
def get_me():
    try:
        return db.get_current_user()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/me/presence", response_model=PresenceResponse)
def get_me_presence():
    """Agent availability for My Workspace — reads agent_presence for ACTOR_USER_ID."""
    return db.get_agent_presence()

@router.patch("/me/presence", response_model=PresenceResponse)
def patch_me_presence(payload: PresencePatchRequest):
    try:
        return db.patch_agent_presence(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.get("/users", response_model=DirectoryUsersResponse)
def list_users():
    import db_users

    return db_users.list_directory_users()

@router.put("/users/{user_id}/roles", response_model=DirectoryUsersResponse)
def put_user_roles(user_id: str, payload: UserRolesPutRequest):
    import db_users
    from api_support import _handle_write

    return _handle_write(db_users.replace_user_roles, user_id, list(payload.roleIds))

@router.patch("/users/{user_id}", response_model=DirectoryUsersResponse)
def patch_user(user_id: str, payload: UserStatusPatchRequest):
    import db_users
    from api_support import _handle_write

    return _handle_write(db_users.patch_user_status, user_id, payload.status)

@router.get("/invites", response_model=OperatorInvitesResponse)
def list_invites():
    import db_invites

    return db_invites.list_invites()

@router.post("/invites", response_model=OperatorInviteWriteResponse)
def create_invite(payload: InviteCreateRequest):
    import db_invites
    from api_support import _handle_write

    return _handle_write(db_invites.create_invite, payload.email, payload.roleId)

@router.post("/invites/{invite_id}/resend", response_model=OperatorInviteWriteResponse)
def resend_invite(invite_id: str):
    import db_invites
    from api_support import _handle_write

    return _handle_write(db_invites.resend_invite, invite_id)

@router.post("/invites/{invite_id}/revoke", response_model=OperatorInviteWriteResponse)
def revoke_invite(invite_id: str):
    import db_invites
    from api_support import _handle_write

    return _handle_write(db_invites.revoke_invite, invite_id)


@router.get("/access-requests", response_model=AccessRequestsResponse)
def list_access_requests():
    import db_access_requests

    return db_access_requests.list_access_requests()


@router.post("/access-requests", response_model=AccessRequestWriteResponse)
def create_access_request(payload: AccessRequestCreateRequest):
    import db_access_requests
    from api_support import _handle_write

    return _handle_write(
        db_access_requests.create_access_request,
        payload.pagePath,
        payload.reason,
        payload.permission,
    )


@router.post("/access-requests/{request_id}/approve", response_model=AccessRequestWriteResponse)
def approve_access_request(request_id: str, payload: AccessRequestApproveRequest):
    import db_access_requests
    from api_support import _handle_write

    return _handle_write(db_access_requests.approve_access_request, request_id, payload.roleId)


@router.post("/access-requests/{request_id}/deny", response_model=AccessRequestWriteResponse)
def deny_access_request(request_id: str):
    import db_access_requests
    from api_support import _handle_write

    return _handle_write(db_access_requests.deny_access_request, request_id)

@router.get("/platform/switches", response_model=PlatformSwitchesResponse)
def list_platform_switches():
    """Operator-flippable runtime switches and their current state.

    Every known switch is returned whether or not a row exists for it, because
    "no row" is a real state — off — and a screen that showed nothing until
    somebody flipped something would be lying about the default.
    """
    import platform_switches

    return {"switches": platform_switches.read_all()}

@router.patch("/platform/switches/{key}", response_model=PlatformSwitchFlipResponse)
def patch_platform_switch(key: str, payload: PlatformSwitchPatchRequest):
    import platform_switches

    enabled = payload.enabled
    note = payload.note.strip()[:200] if payload.note else None
    try:
        result = platform_switches.flip(key, enabled, note=note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_switch") from None
    logger.warning(
        "platform switch %s set to %s by %s", key, enabled, db._actor_user_id()
    )
    return result

