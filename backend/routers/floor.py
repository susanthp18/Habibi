"""Floor: supervisor actions, work items, staff, teams, workspace.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db
import json
import db_floor

from fastapi import APIRouter

from api_support import Utf8JSONResponse, ROUTER_DEPENDENCIES
from fastapi import HTTPException, Query
from fastapi.responses import StreamingResponse
from schemas import (
    FloorAlertAckResponse,
    FloorApprovalSignalRequest,
    FloorCopilotResponse,
    FloorSnapshotResponse,
    StaffResponse,
    SupervisorActionRequest,
    SupervisorActionResponse,
    TeamResponse,
    WorkItemResponse,
    WorkRuntimeJobResponse,
    WorkspaceSummaryResponse,
)
from typing import Any

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/work-runtime/jobs/{job_id}", response_model=WorkRuntimeJobResponse)
def get_work_runtime_job(job_id: str):
    from work_runtime import query

    row = query(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="work_job_not_found")
    return row

@router.get("/work-items", response_model=list[WorkItemResponse])
def list_work_items(
    assignee: str | None = Query("me"),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Assigned queue from the work_items view. Default assignee=me is viewer-relative."""
    return db.list_work_items(assignee=assignee, limit=limit, offset=offset)

@router.get("/workspace/summary", response_model=WorkspaceSummaryResponse)
def get_workspace_summary(assignee: str | None = Query("me")):
    """Rolling-window StatsStrip + RightRail (next callback / SLA / outside-window)."""
    return db.workspace_summary(assignee=assignee)

@router.get("/staff", response_model=list[StaffResponse])
def list_staff():
    return db.list_staff()

@router.get("/teams", response_model=list[TeamResponse])
def list_teams():
    return db.list_teams()

@router.get("/floor", response_model=FloorSnapshotResponse)
def get_floor():
    return db_floor.get_floor_snapshot()

@router.get("/floor/copilot/{interaction_id}", response_model=FloorCopilotResponse)
def get_floor_copilot(interaction_id: str):
    from agent_core.copilot import build

    pack = build(interaction_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="interaction_not_found")
    return pack

# text/event-stream by design: the pack, then whisper tokens, as SSE. Listed
# in tests/test_route_structure.py::_UNTYPED_BY_DESIGN.
@router.get("/floor/copilot/{interaction_id}/stream", response_class=StreamingResponse)
def stream_floor_copilot(interaction_id: str):

    from agent_core.copilot import iter_events

    events = iter_events(interaction_id)
    first = next(events, None)
    if first is None or first.get("type") == "error":
        raise HTTPException(status_code=404, detail="interaction_not_found")

    def _sse() -> Any:
        yield f"event: {first['type']}\ndata: {json.dumps(first, default=str)}\n\n"
        for event in events:
            name = str(event.get("type") or "message")
            yield f"event: {name}\ndata: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        _sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

@router.get("/floor/approvals", response_model=list[WorkRuntimeJobResponse])
def list_floor_approvals():
    from work_runtime import list_jobs

    return list_jobs(status="input_required")

@router.post("/floor/approvals/{job_id}/signal", response_model=WorkRuntimeJobResponse)
def signal_floor_approval(job_id: str, payload: FloorApprovalSignalRequest):
    from work_runtime import signal

    name = str(payload.name or payload.signal or "").strip()
    if name not in {"approve", "reject"}:
        raise HTTPException(status_code=422, detail="signal_must_be_approve_or_reject")
    try:
        return signal(job_id, name, payload.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/supervisor-actions", response_model=SupervisorActionResponse)
def post_supervisor_action(payload: SupervisorActionRequest):
    try:
        return db_floor.create_supervisor_action(payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/floor/alerts/{alert_id}/ack", response_model=FloorAlertAckResponse)
def ack_floor_alert(alert_id: str):
    try:
        return db_floor.ack_floor_alert(alert_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

