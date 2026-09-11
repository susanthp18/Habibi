"""Evals: suites, reports, critiques, scorecards, QA calibration.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import db

from fastapi import APIRouter
from fastapi import HTTPException, Query
from schemas import (
    EvalReportRowResponse,
    EvalReportSummaryResponse,
    EvalScheduleRunResponse,
    EvalSuiteResponse,
    EvalSuiteRunResponse,
    EvalTaskGraduateResponse,
    QaCoverageResponse,
    QaDisagreementsResponse,
    QaInteractionPackResponse,
    SkillCritiqueResponse,
    TwinCorpusGrowResponse,
    TwinCorpusRowResponse,
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
def list_scorecards():
    return db.list_scorecards()

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

@router.post("/eval/suites/{suite_id}/run", response_model=EvalSuiteRunResponse)
def run_eval_suite(
    suite_id: str,
    botId: str | None = Query(default=None),
    promptVersionId: str | None = Query(default=None),
):
    """Run a suite. ``botId`` files the report against the card that launched it.

    ``promptVersionId`` scopes the report to the draft being published so G7/G8
    cannot accept last week's green run for this week's card.
    """
    from agent_core.eval.run import run_named_suite

    try:
        return run_named_suite(
            suite_id,
            origin="manual",
            bot_id=botId or None,
            prompt_version_id=promptVersionId or None,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/eval/suites", response_model=list[EvalSuiteResponse])
def list_eval_suites(kind: str | None = Query(default=None)):
    return db.list_eval_suites(kind=kind)

@router.get("/eval/reports", response_model=list[EvalReportSummaryResponse])
def list_eval_reports(
    kind: str | None = Query(default=None),
    botId: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Eval history. botId scopes it to one card — the Studio's Evals tab needs
    this card's runs, not the whole tenant's. `botId=__none__` is the runs the
    scheduler filed against no card."""
    return db.list_eval_reports(kind=kind, bot_id=botId, limit=limit)

@router.get(
    "/eval/reports/{report_id}",
    response_model=EvalReportRowResponse,
    response_model_exclude_unset=True,
)
def get_eval_report(report_id: str):
    row = db.get_eval_report(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="eval_report_not_found")
    return row

@router.post("/eval/schedule/run", response_model=EvalScheduleRunResponse)
def run_eval_schedule():
    from agent_core.eval.schedule import run_continuous

    try:
        return run_continuous()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post("/eval/tasks/{task_id}/graduate", response_model=EvalTaskGraduateResponse)
def graduate_eval_task(task_id: str):
    from agent_core.eval.graduate import graduate_task

    try:
        return graduate_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/eval/critiques", response_model=list[SkillCritiqueResponse])
def list_skill_critiques(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core.eval.critique import list_critiques

    return list_critiques(limit=limit)

@router.post("/eval/reports/{report_id}/critique", response_model=list[SkillCritiqueResponse])
def critique_eval_report(report_id: str):
    from agent_core.eval.critique import critique_from_report

    try:
        return critique_from_report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.get("/eval/disagreements", response_model=QaDisagreementsResponse)
def list_qa_disagreements(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core.eval.disagreement import disagreements

    return disagreements(limit=limit)

@router.get("/eval/twin-corpus", response_model=list[TwinCorpusRowResponse])
def list_twin_corpus(limit: int = Query(default=50, ge=1, le=200)):
    from agent_core.eval.corpus import list_corpus

    return list_corpus(limit=limit)

@router.post("/eval/twin-corpus/grow", response_model=TwinCorpusGrowResponse)
def grow_twin_corpus(limit: int = Query(default=20, ge=1, le=100)):
    from agent_core.eval.corpus import grow_from_kept_promises

    try:
        return grow_from_kept_promises(limit=limit)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

