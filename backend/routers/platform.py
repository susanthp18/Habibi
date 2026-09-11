"""Platform: health, readiness, metrics, me, switches, dashboard.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import circuit_breaker
import db
import observability
import storage

from fastapi import APIRouter

from api_support import Utf8JSONResponse, ROUTER_DEPENDENCIES
from fastapi import HTTPException, Response
from schemas import (
    BotAnalyticsResponse,
    DashboardResponse,
    MeResponse,
    PresencePatchRequest,
    PresenceResponse,
)
from typing import Any

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/health")
def health():
    """Process liveness — no dependency checks."""
    return {"status": "ok"}

@router.get("/ready")
def ready():
    """Readiness: DB ping + pool headroom (+ optional MinIO ping).

    Exhausted pool or hard DB failure → 503 so LBs shed load.
    MinIO unconfigured is OK (KB upload routes fail separately).
    """
    result = db.readiness()
    minio = storage.ping()
    result = {**result, "minio": minio, "circuits": circuit_breaker.snapshots()}
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

@router.get("/metrics", include_in_schema=False)
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

@router.get("/platform/switches")
def list_platform_switches():
    """Operator-flippable runtime switches and their current state.

    Every known switch is returned whether or not a row exists for it, because
    "no row" is a real state — off — and a screen that showed nothing until
    somebody flipped something would be lying about the default.
    """
    import platform_switches

    with db.engine.connect() as conn:
        return {"switches": platform_switches.get_all(conn)}

@router.patch("/platform/switches/{key}")
def patch_platform_switch(key: str, payload: dict[str, Any]):
    import platform_switches

    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=422, detail="enabled_must_be_boolean")
    note = payload.get("note")
    note = str(note).strip()[:200] if note else None
    try:
        with db.engine.begin() as conn:
            result = platform_switches.set_enabled(conn, key, enabled, note=note)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown_switch") from None
    logger.warning(
        "platform switch %s set to %s by %s", key, enabled, db._actor_user_id()
    )
    return result

