"""Outbound: missions, campaigns, cadence, treatment, authority, offers, demo dial.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

from datetime import datetime
import db
import db_outbound

from fastapi import APIRouter
from fastapi import Header, HTTPException, Query
from schemas.outbound import (
    OfferLogRowResponse,
    OfferTraceResponse,
    OpportunitiesResponse,
    SignalFeedbackRequest,
    SignalFeedbackResponse,
    SignalHealthResponse,
    DecisionExplanationResponse,
    StrategyDecisionRequest,
    StrategyProposalRequest,
    StrategyProposalResponse,
    StrategySettingResponse,
    DecisionLogRowResponse,
    DecisionTraceResponse,
    LearnedRateResponse,
    TreatmentCurrentResponse,
    TreatmentDecideRequest,
    TreatmentHealthResponse,
)
from schemas import (
    AgentObligationResponse,
    AuthorityApplyRequest,
    AuthorityApplyResponse,
    AuthorityNextResponse,
    CadenceCaseResponse,
    CallAttemptResponse,
    CampaignCohortPreviewRequest,
    CampaignCohortPreviewResponse,
    CampaignRunCreateRequest,
    CampaignRunResponse,
    CampaignStatusRequest,
    CampaignTargetsAddedResponse,
    CampaignTargetsRequest,
    DecisionFeedbackRequest,
    DecisionFeedbackResponse,
    NonpaymentReasonResponse,
    NumberPoolResponse,
    OfferHealthResponse,
    OfferResponseRequest,
    OfferResponseResponse,
    OutboundCardVocabularyResponse,
    ReachStatsResponse,
    TreatmentCaseResponse,
    TreatmentEnactRequest,
    TreatmentEnactResponse,
    TreatmentHoldCreateRequest,
    TreatmentHoldReleaseRequest,
    TreatmentHoldResponse,
    TreatmentInsightsResponse,
    TreatmentMetricsResponse,
    TreatmentModelHealthResponse,
    TreatmentModelsResponse,
    TreatmentNextResponse,
    TreatmentOpsRowResponse,
)
from typing import Any

from api_support import _handle_write, Utf8JSONResponse, ROUTER_DEPENDENCIES

router = APIRouter(default_response_class=Utf8JSONResponse, dependencies=ROUTER_DEPENDENCIES)
logger = logging.getLogger(__name__)


@router.get("/offers/health", response_model=OfferHealthResponse)
def get_offer_health(
    window: str = Query("30d", description="24h | 7d | 30d | 90d"),
    includeSimulated: bool = Query(
        False,
        description="Include synthetic rows from scripts/simulate_offer_decisions.py",
    ),
):
    """Offer-engine observability — coverage, funnel, latency, guardrails.

    Synthetic decisions are excluded unless asked for, so nobody makes a call
    on a number that came out of the simulator.
    """
    from agent_core.reco import observability

    return observability.offer_health(window, include_simulated=includeSimulated)

@router.post("/offers/{decisionId}/response", response_model=OfferResponseResponse)
def post_offer_response(decisionId: str, payload: OfferResponseRequest):
    """Record what the borrower said about a delivered offer.

    The route whose absence is the structural reason the offer log has recorded
    **zero** responses in its entire history. `decisionId` is produced, typed and
    serialised on every recommendation and every consumer discarded it at the
    call boundary; nothing posted an outcome back, so the one engine that
    produces a human-visible recommendation produced no label from it.

    Returns 404 for an id that names no decision, so a caller cannot silently
    label nothing. `recorded: false` means the decision already carried a
    response and the first one stands.
    """
    from agent_core.reco import decisions as reco_decisions

    if not db.offer_decision_exists(decisionId):
        raise HTTPException(status_code=404, detail="unknown offer decision")
    written = reco_decisions.record_response(decisionId, payload.response)
    return OfferResponseResponse(
        decisionId=decisionId, response=payload.response, recorded=written
    )

@router.get("/treatment/next", response_model=TreatmentNextResponse, response_model_exclude_unset=True)
def treatment_next(
    customerId: str = Query(...),
    accountId: str | None = Query(default=None),
    trigger: str = Query(default="manual"),
):
    """What should happen to this account next, and when.

    Safe to call from a screen: this is a preview. It writes no decision row
    and creates no enactable schedule.
    """
    return _handle_write(
        db.next_treatment, customer_id=customerId, account_id=accountId, trigger=trigger
    )

@router.get("/treatment/insights", response_model=TreatmentInsightsResponse)
def treatment_insights(days: int = Query(default=14, ge=1, le=90)):
    """Coverage, suppression breakdown and action mix over a window.

    The report the roadmap's exit criterion is written against: two weeks of
    shadow logs with a suppression breakdown before any live auto-act.
    """
    return db.treatment_insights(days)

@router.get("/treatment/metrics", response_model=TreatmentMetricsResponse, response_model_exclude_unset=True)
def treatment_metrics(
    days: int = Query(default=28, ge=1, le=180),
    includeSimulated: bool = Query(default=False),
):
    """Section 17 in full: is the engine working, and what is it costing?

    ``/treatment/insights`` says whether it is safe to switch on. This says
    whether switching it on paid, measured against the randomised control arm.
    Where an arm is too thin to support a causal figure the field says so
    rather than degrading to a collections rate -- which is the number a
    response model wins on, and therefore the number this endpoint exists not
    to report.
    """
    return db.treatment_metrics(days, include_simulated=includeSimulated)

@router.get(
    "/treatment/model-health", response_model=TreatmentModelHealthResponse, response_model_exclude_unset=True
)
def treatment_model_health(
    days: int = Query(default=14, ge=1, le=180),
    includeSimulated: bool = Query(default=False),
):
    """Feature drift, reach calibration, and predicted tau against measured ATE."""
    return db.treatment_model_health(days, include_simulated=includeSimulated)

@router.get("/treatment/models", response_model=TreatmentModelsResponse, response_model_exclude_unset=True)
def treatment_models(
    target: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """The champion/challenger ledger, and whether it matches what is serving."""
    return db.treatment_models(target, limit)

@router.get("/treatment/holds", response_model=list[TreatmentHoldResponse], response_model_exclude_unset=True)
def list_treatment_holds(
    customerId: str | None = Query(default=None),
    activeOnly: bool = Query(default=True),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_treatment_holds(
        customer_id=customerId, active_only=activeOnly, limit=limit, offset=offset
    )

@router.post("/treatment/holds", response_model=TreatmentHoldResponse, response_model_exclude_unset=True)
def create_treatment_hold(payload: TreatmentHoldCreateRequest):
    """Stop collections outreach for this borrower.

    Not idempotency-keyed: re-placing an active hold returns the existing one.
    A bot that hears "I lost my job" twice in one call and an agent who clicks
    twice must both end with exactly one hold, and a 409 would leave the caller
    deciding what to do about it.
    """
    return _handle_write(db.create_treatment_hold, payload.model_dump(exclude_none=True))

@router.post(
    "/treatment/holds/{hold_id}/release", response_model=TreatmentHoldResponse, response_model_exclude_unset=True
)
def release_treatment_hold(hold_id: str, payload: TreatmentHoldReleaseRequest | None = None):
    return _handle_write(
        db.release_treatment_hold,
        hold_id,
        payload.model_dump(exclude_none=True) if payload else None,
    )

@router.post("/treatment/decisions/{decision_id}/feedback", response_model=DecisionFeedbackResponse)
def treatment_decision_feedback(decision_id: str, body: DecisionFeedbackRequest):
    try:
        return db_outbound.record_decision_feedback(
            decision_id,
            body,
            tenant_id=db.current_tenant(),
            actor_user_id=db._actor_user_id(),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.post(
    "/treatment/decisions/{decision_id}/enact",
    response_model=TreatmentEnactResponse,
    response_model_exclude_unset=True,
)
def treatment_decision_enact(
    decision_id: str,
    body: TreatmentEnactRequest | None = None,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Carry out one live decision. Same executor as the clerk; enacted_by=human."""
    return _handle_write(
        db.enact_treatment_decision,
        decision_id,
        body.model_dump(exclude_none=True) if body else {},
        idempotency_key,
    )

@router.get("/treatment/cases", response_model=list[TreatmentCaseResponse])
def list_treatment_cases(
    customerId: str | None = Query(default=None),
    openOnly: bool = Query(default=True),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """One row per case, with the ladder it has already walked.

    ``GET /treatment/next`` answers "what does the engine say?". A floor lead's
    actual question is "what has been tried on this account, and what is left",
    which is a different query.
    """
    return db.list_treatment_cases(
        customer_id=customerId, open_only=openOnly, limit=limit, offset=offset
    )

@router.get("/treatment/ops/{kind}", response_model=list[TreatmentOpsRowResponse])
def list_treatment_ops(
    kind: str,
    customerId: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Mandate / field / legal operator queues. Distinct from Holds."""
    if kind not in {"mandates", "field", "legal"}:
        raise HTTPException(status_code=404, detail="unknown_ops_kind")
    return db.list_treatment_ops(
        kind=kind, customer_id=customerId, limit=limit, offset=offset
    )

@router.get("/treatment/decisions", response_model=list[DecisionLogRowResponse])
def list_treatment_decisions(
    customerId: str | None = Query(default=None),
    action: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    held: bool | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    format: str = Query(default="json", pattern="^(json|csv)$"),
):
    """The decision log, newest first; ``format=csv`` for an auditor's export."""
    import decision_trace
    from fastapi.responses import PlainTextResponse

    rows = decision_trace.list_decisions(
        customer_id=customerId, action=action, outcome=outcome, held=held,
        since=since, until=until, limit=limit, offset=offset,
    )
    if format == "csv":
        return PlainTextResponse(
            decision_trace.to_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="decisions.csv"'},
        )
    return rows

@router.get("/treatment/decisions/{decision_id}", response_model=DecisionTraceResponse)
def treatment_decision_trace(decision_id: str):
    """One decision end to end: why now, every option and why it lost or was
    blocked, how the choice was made, and what happened afterwards."""
    import decision_trace

    try:
        return decision_trace.trace(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="decision_not_found") from exc

@router.post("/treatment/decisions/{decision_id}/explain", response_model=DecisionExplanationResponse)
def treatment_decision_explain(decision_id: str):
    """A plain-language explanation of one decision, written only from its
    trace; the rule-written rationale when the model is unavailable or strays."""
    import decision_ai

    try:
        return decision_ai.explain(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="decision_not_found") from exc

@router.get("/treatment/health", response_model=TreatmentHealthResponse)
def treatment_health(days: int = Query(default=1, ge=1, le=30)):
    """Is every stage of the engine running, are the bank feeds fresh, and
    what is stopping contact right now."""
    import decision_trace

    return decision_trace.health(days)

@router.get("/treatment/learned", response_model=list[LearnedRateResponse])
def treatment_learned():
    """Each starting assumption beside what the engine has learned from outcomes."""
    import decision_trace

    return decision_trace.learned_rates()

@router.get("/treatment/current", response_model=TreatmentCurrentResponse)
def treatment_current(customerId: str = Query(...), accountId: str | None = Query(default=None)):
    """The account's next best action: its latest real decision, as a trace.
    The same answer the customer card, the cases panel and the copilot use."""
    import decision_trace

    return {"decision": decision_trace.current(customerId, accountId)}

@router.post("/treatment/decide", response_model=DecisionTraceResponse)
def treatment_decide_now(body: TreatmentDecideRequest):
    """Ask the engine now and keep the answer (recorded in shadow: logged and
    traceable, never carried out)."""
    import decision_trace

    return _handle_write(
        decision_trace.decide_now, customer_id=body.customerId, account_id=body.accountId
    )

@router.get("/treatment/strategy", response_model=list[StrategySettingResponse])
def treatment_strategy():
    """Every setting the engine runs on, in plain words, with where it came from."""
    import strategy

    return strategy.settings()

@router.get("/treatment/strategy/proposals", response_model=list[StrategyProposalResponse])
def treatment_strategy_proposals(status: str | None = Query(default=None)):
    import strategy

    return strategy.proposals(status)

@router.post("/treatment/strategy/proposals", response_model=StrategyProposalResponse)
def treatment_strategy_propose(body: StrategyProposalRequest):
    """Propose a change. It applies only when someone else approves it."""
    import strategy

    return _handle_write(
        strategy.propose, body.changes, reason=body.reason, author=db._actor_user_id() or "unknown"
    )

@router.post("/treatment/strategy/proposals/{proposal_id}/approve", response_model=StrategyProposalResponse)
def treatment_strategy_approve(proposal_id: str, body: StrategyDecisionRequest | None = None):
    import strategy

    return _handle_write(
        strategy.decide, proposal_id, approve=True,
        decider=db._actor_user_id() or "unknown", note=body.note if body else None,
    )

@router.post("/treatment/strategy/proposals/{proposal_id}/reject", response_model=StrategyProposalResponse)
def treatment_strategy_reject(proposal_id: str, body: StrategyDecisionRequest | None = None):
    import strategy

    return _handle_write(
        strategy.decide, proposal_id, approve=False,
        decider=db._actor_user_id() or "unknown", note=body.note if body else None,
    )

@router.get("/offers/decisions", response_model=list[OfferLogRowResponse])
def list_offer_decisions(
    customerId: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Offer decisions, newest first, each one traceable."""
    import offer_trace

    return offer_trace.log(customer_id=customerId, limit=limit, offset=offset)

@router.get("/offers/decisions/{decision_id}", response_model=OfferTraceResponse)
def offer_decision_trace(decision_id: str):
    """One offer: the signals it cited, every product and why it lost or was
    blocked, the suitability finding, and whether it was sent and answered."""
    import offer_trace

    try:
        return offer_trace.trace(decision_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="decision_not_found") from exc

@router.get("/offers/opportunities", response_model=OpportunitiesResponse)
def offer_opportunities(customerId: str = Query(...)):
    """What this customer said that a product could serve, and the latest offer."""
    import offer_trace

    return offer_trace.opportunities(customerId)

@router.get("/offers/signals/health", response_model=SignalHealthResponse)
def offer_signal_health(days: int = Query(default=30, ge=1, le=180)):
    import offer_trace

    return offer_trace.signal_health(days)

@router.post("/offers/signals/{signal_id}/feedback", response_model=SignalFeedbackResponse)
def offer_signal_feedback(signal_id: str, body: SignalFeedbackRequest):
    """Mark a detected signal right or wrong; this measures the extractor."""
    import offer_trace

    return _handle_write(
        offer_trace.signal_feedback, signal_id, body.verdict, by=db._actor_user_id() or "unknown"
    )

@router.get("/outbound/stats", response_model=ReachStatsResponse)
def outbound_stats(days: int = Query(default=14, ge=1, le=90)):
    """Answer rate, right-party rate, attempts per connect, denial rate.

    Every one of these was uncomputable until an unanswered dial started
    leaving a row: ``interactions`` is created when media connects, so the
    denominator of "how often do we reach the people we call" was never
    recorded anywhere.

    Suppressed attempts are reported beside the reach figures rather than
    inside them. A call the contact gate refused is not a call the borrower
    ignored, and folding the two together would make a compliant week look like
    an unreachable book.
    """
    return db_outbound.reach_stats(days, tenant_id=db.current_tenant())

@router.get("/outbound/attempts", response_model=list[CallAttemptResponse])
def outbound_attempts(
    customerId: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """The dial log, newest first — including the ones that never connected."""
    return db_outbound.list_call_attempts(
        customer_id=customerId,
        state=state,
        limit=limit,
        offset=offset,
        tenant_id=db.current_tenant(),
    )

@router.get("/outbound/reasons", response_model=list[NonpaymentReasonResponse])
def outbound_reasons(days: int = Query(default=30, ge=1, le=180)):
    """Why the book is not paying, counted.

    The question the product could not answer at all: it could say an account
    was 45 DPD with two bounces and never that the borrower lost their job in
    June. ``forgot`` is the row to watch — it counts the calls that were worth
    less than a reminder.
    """
    return db_outbound.nonpayment_reasons(days, tenant_id=db.current_tenant())

@router.get(
    "/outbound/campaigns", response_model=list[CampaignRunResponse], response_model_exclude_unset=True
)
def list_campaign_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """Runs and how far through each one is."""
    return db_outbound.list_campaign_runs(
        status=status, limit=limit, tenant_id=db.current_tenant()
    )

@router.post("/outbound/campaigns", response_model=CampaignRunResponse, response_model_exclude_unset=True)
def create_campaign_run(body: CampaignRunCreateRequest):
    """Create a run in ``draft``. Nothing dials until it is explicitly started.

    Draft-by-default is the point. A campaign is the one object in this system
    whose accidental creation rings real phones, so bringing it into existence
    and setting it going are two deliberate acts rather than one.
    """
    import campaigns

    payload = body.model_dump(exclude_none=True)
    name = str(payload.get("name") or "").strip()
    objective = str(payload.get("objective") or "").strip()
    if not name or not objective:
        raise HTTPException(status_code=400, detail="name_and_objective_required")
    import outbound_policy

    if objective not in outbound_policy.OBJECTIVES:
        raise HTTPException(status_code=400, detail="unknown_objective")

    try:
        return db_outbound.create_campaign_run(
            payload,
            name=name,
            objective=objective,
            tenant_id=db.current_tenant(),
            actor_user_id=db._actor_user_id(),
        )
    except campaigns.SelectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/outbound/campaigns/preview", response_model=CampaignCohortPreviewResponse)
def preview_campaign_cohort(payload: CampaignCohortPreviewRequest):
    """Who this selector would call, before a run exists.

    Deliberately reachable without a run id. A campaign is the one object here
    whose accidental creation rings real phones, so seeing the population has to
    be possible *before* committing to one — otherwise the only way to check a
    cohort is to create the thing you were checking.
    """
    import campaigns

    try:
        return db_outbound.preview_campaign_cohort(
            selector=payload.selector.model_dump(exclude_none=True) if payload.selector else {},
            sample=int(payload.sample or 10),
            tenant_id=db.current_tenant(),
        )
    except campaigns.SelectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/outbound/campaigns/{run_id}/targets", response_model=CampaignTargetsAddedResponse)
def add_campaign_targets(run_id: str, payload: CampaignTargetsRequest):
    import campaigns

    ids = [str(c) for c in (payload.customerIds or []) if str(c).strip()]
    selector = payload.selector.model_dump(exclude_none=True) if payload.selector else {}
    if not ids and not selector:
        raise HTTPException(status_code=400, detail="customer_ids_or_selector_required")
    try:
        added = db_outbound.add_campaign_targets(
            run_id, ids=ids, selector=selector, tenant_id=db.current_tenant()
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign_run_not_found") from exc
    except campaigns.SelectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"runId": run_id, "added": added, "requested": len(ids)}

@router.post(
    "/outbound/campaigns/{run_id}/status", response_model=CampaignRunResponse, response_model_exclude_unset=True
)
def set_campaign_status(run_id: str, payload: CampaignStatusRequest):
    """start / pause / finish / cancel.

    Pause takes effect on the next worker iteration and never mid-call: a call
    already in progress is a conversation with a person, and hanging up on them
    to honour a button is worse than letting it finish.
    """
    import campaigns

    status = str(payload.status or "").strip()
    allowed = {
        campaigns.STATUS_RUNNING,
        campaigns.STATUS_PAUSED,
        campaigns.STATUS_FINISHED,
        campaigns.STATUS_CANCELLED,
    }
    if status not in allowed:
        raise HTTPException(status_code=400, detail="bad_status")
    if status == campaigns.STATUS_RUNNING and not campaigns.enabled():
        raise HTTPException(status_code=409, detail="campaign_runtime_disabled")
    if status == campaigns.STATUS_RUNNING:
        import platform_switches

        if not platform_switches.outbound_enabled():
            raise HTTPException(status_code=409, detail="outbound_disabled")
    try:
        run = db_outbound.set_campaign_status(run_id, status, tenant_id=db.current_tenant())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return run

@router.get(
    "/outbound/campaigns/{run_id}", response_model=CampaignRunResponse, response_model_exclude_unset=True
)
def get_campaign_run(run_id: str):
    run = db_outbound.get_campaign_run(run_id, tenant_id=db.current_tenant())
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return run

@router.get("/outbound/cadence", response_model=list[CadenceCaseResponse])
def list_cadence_cases(
    customerId: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """Open retry ladders — what is waiting, and what ran out of attempts."""
    return db_outbound.list_cadence_cases(
        customer_id=customerId, state=state, limit=limit, tenant_id=db.current_tenant()
    )

@router.get("/outbound/number-pools", response_model=list[NumberPoolResponse])
def list_number_pools():
    """Caller-ID pools and the numbers in them, with how each is performing."""
    return db_outbound.list_number_pools(tenant_id=db.current_tenant())

@router.get("/outbound/obligations", response_model=list[AgentObligationResponse])
def list_agent_obligations(
    state: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """What the agent promised and whether we kept it.

    An agent that keeps its promises is the whole trust proposition of an
    automated collections line, and a missed obligation is a QA finding with a
    named owner rather than a thing nobody knew happened.
    """
    return db_outbound.list_agent_obligations(
        state=state, limit=limit, tenant_id=db.current_tenant()
    )

@router.get("/outbound/card-vocabulary", response_model=OutboundCardVocabularyResponse)
def outbound_card_vocabulary():
    """Every closed vocabulary the outbound policy may use.

    Derived from the definitions the dialler and the Closer actually use rather
    than restated, so an editor never offers an option the policy validator
    rejects. ``dailyCap`` is here for the same reason: a cadence planning more
    contacts per day than ``contact_policy`` permits is vetoed on every dial.
    """
    from typing import get_args

    import call_closer
    import contact_policy
    import mission as mission_mod
    import outbound as outbound_mod
    import outbound_policy
    import post_call_actions
    from agent_core.authority import config as authority_config

    pools: list[dict[str, Any]] = []
    try:
        pools = db_outbound.enabled_number_pools(tenant_id=db.current_tenant())
    except Exception:
        # A tenant with no pools table yet still gets a usable editor.
        logger.debug("number pool lookup failed", exc_info=True)

    return {
        "objectives": list(outbound_policy.OBJECTIVES),
        "objectiveBriefs": dict(mission_mod.OBJECTIVE_BRIEF),
        "directions": list(get_args(outbound_policy.Direction)),
        "voicemailModes": list(get_args(outbound_policy.VoicemailMode)),
        "poolKinds": list(get_args(outbound_policy.PoolKind)),
        "qaModes": ["always", "sampled", "never"],
        # The Closer's taxonomy: what `success` / `partial` / `stop_on` and a
        # post-call rule's `when` may name.
        "outcomeCodes": sorted(call_closer.BUSINESS_OUTCOMES),
        # Verbs the Closer carries out.
        "postCallActions": sorted(post_call_actions.REGISTRY),
        # `retry_on` is matched against the attempt's connection outcome *and*
        # its state, so the offerable set is the states worth another dial.
        "retryStates": sorted(outbound_mod.RETRYABLE),
        "authorityProfiles": [
            {"name": name, "ceilingInr": authority_config.profile_ceilings().get(name)}
            for name in authority_config.profile_names()
        ],
        "numberPools": pools,
        "dailyCap": contact_policy.tenant_daily_cap(),
    }

@router.get("/authority/next", response_model=AuthorityNextResponse)
def authority_next(
    customerId: str = Query(...),
    accountId: str | None = Query(default=None),
    feeType: str = Query(default="late_fee"),
    askedAmount: float | None = Query(default=None),
    interactionId: str | None = Query(default=None),
):
    """What may close on this call, in rupees.

    Safe to call from a screen: outside ``AUTHORITY_MODE=live`` the engine
    decides, logs and posts nothing. The decision row is written either way.
    """
    return _handle_write(
        db.next_authority,
        customer_id=customerId,
        account_id=accountId,
        fee_type=feeType,
        asked_amount=askedAmount,
        interaction_id=interactionId,
    )

@router.post("/authority/apply", response_model=AuthorityApplyResponse)
def authority_apply(payload: AuthorityApplyRequest):
    """Post the goodwill the matrix already approved. Live mode only."""
    return _handle_write(db.apply_authority, payload.model_dump(exclude_none=True))
