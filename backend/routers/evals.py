"""QA: rubric, scorecards, coaching, calibration, and the QA disagreement feed.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db

from fastapi import APIRouter
from fastapi import HTTPException, Query
from schemas import (
    QaCoverageResponse,
    QaDisagreementsResponse,
    QaInteractionPackResponse,
    CalibrationSessionPatchRequest,
    CalibrationSessionResponse,
    CoachingActionCreateRequest,
    CoachingActionPatchRequest,
    CoachingActionResponse,
    RubricResponse,
    ScorecardCreateRequest,
    ScorecardListResponse,
    ScorecardPatchRequest,
)

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/rubric", response_model=RubricResponse)
def get_rubric(rubric_id: str | None = Query(default=None, alias="rubricId")):
    """Active Collections Interaction Rubric (screen defaultRubric shape)."""
    try:
        return db.get_rubric(rubric_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/scorecards", response_model=list[ScorecardListResponse])
def list_scorecards(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_scorecards(limit=limit, offset=offset)

@router.get("/qa/coverage", response_model=QaCoverageResponse)
def qa_coverage(days: int = Query(default=7, ge=1, le=90)):
    return db.qa_coverage_stats(days=days)

@router.get("/qa/interactions/{interaction_id}/pack", response_model=QaInteractionPackResponse)
def qa_interaction_pack(interaction_id: str):
    from agent_core.live_qa.pack import build_pack

    pack = build_pack(interaction_id)
    if pack is None:
        raise HTTPException(status_code=404, detail="interaction_not_found")
    return pack

@router.post("/scorecards", response_model=ScorecardListResponse)
def create_scorecard(payload: ScorecardCreateRequest):
    return _handle_write(db.create_scorecard, payload.model_dump(exclude_unset=True))

@router.patch("/scorecards/{scorecard_id}", response_model=ScorecardListResponse)
def patch_scorecard(scorecard_id: str, payload: ScorecardPatchRequest):
    # exclude_unset (not exclude_none) so present keys are intentional.
    return _handle_write(db.patch_scorecard, scorecard_id, payload.model_dump(exclude_unset=True))

@router.get("/coaching-actions", response_model=list[CoachingActionResponse])
def list_coaching_actions(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_coaching_actions(limit=limit, offset=offset)

@router.post("/coaching-actions", response_model=CoachingActionResponse)
def create_coaching_action(payload: CoachingActionCreateRequest):
    return _handle_write(db.create_coaching_action, payload.model_dump(exclude_unset=True))

@router.patch("/coaching-actions/{action_id}", response_model=CoachingActionResponse)
def patch_coaching_action(action_id: str, payload: CoachingActionPatchRequest):
    return _handle_write(
        db.patch_coaching_action, action_id, payload.model_dump(exclude_unset=True)
    )

@router.get("/calibration-sessions", response_model=list[CalibrationSessionResponse])
def list_calibration_sessions(
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_calibration_sessions(limit=limit, offset=offset)

@router.patch(
    "/calibration-sessions/{session_id}",
    response_model=CalibrationSessionResponse,
)
def patch_calibration_session(session_id: str, payload: CalibrationSessionPatchRequest):
    return _handle_write(
        db.patch_calibration_session, session_id, payload.model_dump(exclude_unset=True)
    )


@router.get("/eval/disagreements", response_model=QaDisagreementsResponse)
def list_qa_disagreements(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core.eval.disagreement import disagreements

    return disagreements(limit=limit)
