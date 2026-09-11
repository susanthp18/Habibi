"""Outbound: missions, campaigns, cadence, treatment, authority, offers, demo dial.

Split out of main.py by domain (WS7). Routes are verbatim; the router is
included by main.py.
"""

from __future__ import annotations

import logging

import asyncio
import db
import os

from fastapi import APIRouter
from fastapi import HTTPException, Query
from schemas import (
    AuthorityApplyRequest,
    OfferHealthResponse,
    OfferResponseRequest,
    OfferResponseResponse,
    TreatmentHoldCreateRequest,
    TreatmentHoldReleaseRequest,
)
from sqlalchemy import text
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

#: The number the demo dials. A constant, not a request parameter: this button
#: exists so a rehearsed demo is one click, and an endpoint that accepts an
#: arbitrary number is a dialer, not a demo. Ad-hoc dialling already has a home
#: at POST /twilio/voice/outbound, behind the same switch.
DEMO_OUTBOUND_PHONE_DEFAULT = "919655282324"

def _demo_waivable_reasons() -> frozenset[str]:
    """Contact-policy refusals the demo switch may override.

    Every one is a rule about *timing or frequency* — when a borrower may be
    called and how often. None of them is a rule about whether the borrower
    consented to be called at all; those stay in force whatever the switch says,
    which is the line this set exists to draw.
    """
    import contact_policy

    return frozenset(
        {
            contact_policy.REASON_HOURS,    # statutory calling hours
            contact_policy.REASON_WINDOW,   # the borrower's narrower preference
            contact_policy.REASON_COOLING,  # gap between consecutive contacts
            contact_policy.REASON_DAILY,    # touches per day
            contact_policy.REASON_WEEKLY,   # touches per week
        }
    )

_DEMO_WAIVABLE_REASONS = _demo_waivable_reasons()

def _demo_outbound_phone() -> str:
    return (os.getenv("DEMO_OUTBOUND_PHONE") or DEMO_OUTBOUND_PHONE_DEFAULT).strip()

def _demo_outbound_bot_id() -> str:
    """The card that will speak, not always the tenant default."""
    import mission as mission_mod

    return mission_mod.resolve_outbound_bot_id(
        explicit=(os.getenv("DEMO_OUTBOUND_BOT_ID") or "").strip() or None,
        objective=(
            os.getenv("DEMO_OUTBOUND_OBJECTIVE") or DEMO_OUTBOUND_OBJECTIVE_DEFAULT
        ).strip(),
    )

#: The objective the demo runs under. It must be one the *card* declares, not a
#: label invented here: `entry_node`, the success criteria, the duration budget,
#: the voicemail policy and the cadence all come from the card's objective spec,
#: and `OBJECTIVE_BRIEF` — the paragraph telling the agent what this call is for
#: — is keyed by it. An unrecognised objective silently yields an empty brief
#: and no spec, which is a materially worse call that still connects.
DEMO_OUTBOUND_OBJECTIVE_DEFAULT = "dpd_reminder"

def _demo_outbound_objective(card: Any) -> str:
    """The demo objective, validated against the card that will run it."""
    wanted = (
        os.getenv("DEMO_OUTBOUND_OBJECTIVE") or DEMO_OUTBOUND_OBJECTIVE_DEFAULT
    ).strip()
    declared = [
        str(getattr(o, "key", "")) for o in (getattr(getattr(card, "outbound", None), "objectives", None) or [])
    ]
    if wanted in declared:
        return wanted
    if declared:
        logger.warning(
            "demo objective %r is not declared by the card (has %s) — using %s",
            wanted,
            declared,
            declared[0],
        )
        return declared[0]
    return wanted

@router.get("/demo/outbound-call")
def demo_outbound_target():
    """Who the demo button will call, and whether it can right now.

    The screen needs to say this *before* the click. "Dial and find out" is a
    poor design for a control whose side effect is a real phone ringing in
    somebody's hand.
    """
    import platform_switches
    from voice import twilio_ops

    phone = _demo_outbound_phone()
    digits = "".join(ch for ch in phone if ch.isdigit())
    customer: dict[str, Any] | None = None
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT id, name, phone_primary, dnd
                FROM customers
                WHERE tenant_id = :t
                  AND regexp_replace(COALESCE(phone_primary, ''), '\\D', '', 'g') = :d
                LIMIT 1
                """
            ),
            {"t": db._tenant(), "d": digits},
        ).mappings().first()
        if row:
            customer = {
                "id": row["id"],
                "name": row["name"],
                "phone": row["phone_primary"],
                "dnd": bool(row["dnd"]),
            }
    # What the call will actually be authorised to do. `allowed_offers` is empty
    # on every objective this card declares, and `mission.build` turns that into
    # an explicit "do NOT mention any product, offer, top-up or upgrade" line in
    # the brief. Saying so here is the difference between a demo that surprises
    # the person running it and one that does not: whoever clicks this deserves
    # to know upsell is off *before* they promise a customer they will see it.
    import mission as mission_mod

    objective = ""
    offers_allowed = False
    try:
        card = mission_mod.card_for_bot(_demo_outbound_bot_id())
        objective = _demo_outbound_objective(card)
        for spec in getattr(getattr(card, "outbound", None), "objectives", None) or []:
            if str(getattr(spec, "key", "")) == objective:
                offers_allowed = bool(getattr(spec, "allowed_offers", None))
                break
    except Exception:
        logger.exception("demo target: could not resolve the objective")

    # Whether the call would be permitted *right now*, using the dry-run
    # evaluator so asking the question costs the borrower nothing — `admit`
    # increments the daily counter, `evaluate` does not.
    policy_reason: str | None = None
    #: Set when the waiver is what makes the call possible, so the screen can say
    #: "we are overriding this" rather than silently showing all-clear.
    policy_waived: str | None = None
    if customer:
        try:
            import contact_policy

            with db.engine.connect() as conn:
                verdict = contact_policy.evaluate(
                    conn, customer_id=customer["id"], channel="voice", purpose="outreach"
                )
            policy_reason = None if verdict.allowed else (verdict.reason or "contact_policy")
            # Report what the *button* will do, not what the raw engine said.
            # The POST applies the demo waiver, so a screen that showed the
            # unwaived refusal would tell the operator they are blocked and then
            # place the call anyway — the same class of confident-but-wrong
            # state this product keeps getting caught by.
            if (
                policy_reason in _DEMO_WAIVABLE_REASONS
                and platform_switches.demo_ignores_window()
            ):
                policy_waived = policy_reason
                policy_reason = None
        except Exception:
            logger.exception("demo target: contact policy dry-run failed")

    return {
        "phone": phone,
        "customer": customer,
        "objective": objective,
        "offersAllowed": offers_allowed,
        "outboundEnabled": platform_switches.outbound_enabled(),
        "demoIgnoresWindow": platform_switches.demo_ignores_window(),
        "policyReason": policy_reason,
        "policyWaived": policy_waived,
        "twilioConfigured": twilio_ops.configured(),
    }

@router.post("/demo/outbound-call")
async def demo_outbound_call():
    """Place the demo call: one number, the full mission, every real gate.

    Deliberately *not* a shortcut around the pipeline. It builds a mission from
    the live agent card, reserves an attempt, runs `contact_policy` and honours
    the outbound switch — so what the customer watches is the product, not a
    demo harness that resembles it. The compliance refusals are part of the
    demo: a call declined at 21:00 because the statutory window closed is a
    better thing to show than one that goes through.
    """
    import mission as mission_mod
    import outbound
    import platform_switches
    from voice import twilio_ops

    if not platform_switches.outbound_enabled():
        raise HTTPException(status_code=409, detail="outbound_disabled")
    if not twilio_ops.configured():
        raise HTTPException(status_code=503, detail="twilio_not_configured")

    phone = _demo_outbound_phone()
    digits = "".join(ch for ch in phone if ch.isdigit())

    def _prepare() -> tuple[Any, str, str | None, str]:
        """Reserve, gate and (maybe) waive, off the event loop."""
        with db.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT id FROM customers
                    WHERE tenant_id = :t
                      AND regexp_replace(COALESCE(phone_primary, ''), '\\D', '', 'g') = :d
                    LIMIT 1
                    """
                ),
                {"t": db._tenant(), "d": digits},
            ).mappings().first()
            if row is None:
                raise HTTPException(status_code=404, detail="demo_customer_not_found")
            customer_id = str(row["id"])
            account_id = conn.execute(
                text(
                    "SELECT id FROM accounts WHERE customer_id = :c"
                    " ORDER BY CASE WHEN id LIKE 'AC-%' THEN 0 ELSE 1 END, created_at, id LIMIT 1"
                ),
                {"c": customer_id},
            ).scalar()

            bot_id = _demo_outbound_bot_id()
            card = mission_mod.card_for_bot(bot_id)
            objective = _demo_outbound_objective(card)
            built = mission_mod.build(
                conn,
                customer_id=customer_id,
                objective=objective,
                account_id=account_id,
                card=card,
                bot_id=bot_id,
            )
            # The one override, and its limits.
            #
            # Waivable: *when* and *how often*. The calling hours, the borrower's
            # preferred window, the cooling-off gap and the daily and weekly caps
            # all exist to stop a borrower being rung repeatedly. The demo endpoint
            # takes no phone number — it dials one configured handset, the one the
            # operator running the demo is holding — so rehearsing on it is not the
            # harm any of those rules were written to prevent. Hitting `cooling_off`
            # after three rehearsal calls to your own phone is the rule working
            # correctly on the wrong subject.
            #
            # Not waivable, at any switch setting: consent, opt-out, DND, the
            # registry and the DPDP promotional-purpose basis. Those answer "may we
            # contact this person at all", which a demo does not get to re-answer —
            # and they are not what is blocking anyone here, so waiving them would
            # buy nothing and cost the one guarantee worth keeping.
            gated = outbound.gate(
                conn,
                admit={"source": "voice_outbound", "actor_kind": "human"},
                waivable=(
                    _DEMO_WAIVABLE_REASONS
                    if platform_switches.demo_ignores_window()
                    else frozenset()
                ),
                customer_id=customer_id,
                to_phone=phone,
                objective=objective,
                account_id=account_id,
                bot_id=bot_id,
                context={"source": "demo_button", "mission": built},
            )
            attempt = gated.attempt
            reason = gated.reason or "contact_policy"
            if gated.waived:
                logger.warning(
                    "demo call: waiving %s for the demo number by operator switch", reason
                )
                db.record_activity(
                    conn,
                    "customer",
                    customer_id,
                    "demo_window_waived",
                    f"Demo call placed despite {reason}",
                    f"waived:{reason}",
                    customer_id,
                )

        return gated, customer_id, account_id, reason

    gated, customer_id, account_id, reason = await asyncio.to_thread(_prepare)
    attempt = gated.attempt
    if not gated.allowed:
        # 409 with the engine's own reason. `outside_allowed_window` here is the
        # calling window doing its job, not a bug in the button.
        raise HTTPException(status_code=409, detail=reason)

    result = await asyncio.to_thread(
        outbound.place,
        db.engine,
        attempt,
        to_phone=phone,
        custom={"customer_id": customer_id, "demo": "1"},
    )
    if not result.get("placed"):
        reason = result.get("reason") or "dial_failed"
        raise HTTPException(
            status_code=503 if reason in {"fleet_busy", "outbound_disabled"} else 502,
            detail=reason,
        )
    return {
        "placed": True,
        "customerId": customer_id,
        "phone": phone,
        "attemptId": result.get("attemptId"),
        "callSid": result.get("callSid"),
    }

@router.get("/treatment/next")
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

@router.get("/treatment/insights")
def treatment_insights(days: int = Query(default=14, ge=1, le=90)):
    """Coverage, suppression breakdown and action mix over a window.

    The report the roadmap's exit criterion is written against: two weeks of
    shadow logs with a suppression breakdown before any live auto-act.
    """
    return db.treatment_insights(days)

@router.get("/treatment/metrics")
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

@router.get("/treatment/model-health")
def treatment_model_health(
    days: int = Query(default=14, ge=1, le=180),
    includeSimulated: bool = Query(default=False),
):
    """Feature drift, reach calibration, and predicted tau against measured ATE."""
    return db.treatment_model_health(days, include_simulated=includeSimulated)

@router.get("/treatment/models")
def treatment_models(
    target: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """The champion/challenger ledger, and whether it matches what is serving."""
    return db.treatment_models(target, limit)

@router.get("/treatment/holds")
def list_treatment_holds(
    customerId: str | None = Query(default=None),
    activeOnly: bool = Query(default=True),
    limit: int | None = Query(default=None, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    return db.list_treatment_holds(
        customer_id=customerId, active_only=activeOnly, limit=limit, offset=offset
    )

@router.post("/treatment/holds")
def create_treatment_hold(payload: TreatmentHoldCreateRequest):
    """Stop collections outreach for this borrower.

    Not idempotency-keyed: re-placing an active hold returns the existing one.
    A bot that hears "I lost my job" twice in one call and an agent who clicks
    twice must both end with exactly one hold, and a 409 would leave the caller
    deciding what to do about it.
    """
    return _handle_write(db.create_treatment_hold, payload.model_dump(exclude_none=True))

@router.post("/treatment/holds/{hold_id}/release")
def release_treatment_hold(hold_id: str, payload: TreatmentHoldReleaseRequest | None = None):
    return _handle_write(
        db.release_treatment_hold,
        hold_id,
        payload.model_dump(exclude_none=True) if payload else None,
    )

@router.post("/treatment/decisions/{decision_id}/feedback")
def treatment_decision_feedback(decision_id: str, payload: dict[str, Any]):
    import decision_feedback
    from schemas import DecisionFeedbackRequest

    body = DecisionFeedbackRequest.model_validate(payload)
    with db.engine.begin() as conn:
        try:
            return decision_feedback.record_feedback(
                conn,
                tenant_id=db.current_tenant(),
                decision_id=decision_id,
                verdict=body.verdict,
                actor_user_id=db._actor_user_id(),
                reason_code=body.reasonCode,
                note_redacted=body.noteRedacted,
                endpoint=body.endpoint,
                channel=body.channel or "voice",
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get("/treatment/cases")
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

@router.get("/outbound/stats")
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
    import outbound

    with db.engine.connect() as conn:
        return outbound.reach_stats(conn, tenant_id=db.current_tenant(), days=days)

@router.get("/outbound/attempts")
def outbound_attempts(
    customerId: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """The dial log, newest first — including the ones that never connected."""
    clauses = ["a.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": db.current_tenant(), "limit": limit, "offset": offset}
    if customerId:
        clauses.append("a.customer_id = :cid")
        params["cid"] = customerId
    if state:
        clauses.append("a.state = :state")
        params["state"] = state
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT a.id, a.customer_id, c.name AS customer_name, a.objective,
                       a.attempt_no, a.state, a.suppressed_reason, a.to_phone_last4,
                       a.answered_by, a.right_party, a.ring_sec, a.talk_sec,
                       a.provider_call_id, a.provider_status, a.provider_error,
                       a.interaction_id, a.decision_id, a.reserved_at, a.placed_at,
                       a.answered_at, a.ended_at,
                       o.connection, o.business, o.objective_met, o.nonpayment_reason,
                       o.summary, o.summary_source
                FROM call_attempts a
                JOIN customers c ON c.id = a.customer_id
                LEFT JOIN call_outcomes o ON o.attempt_id = a.id
                WHERE {' AND '.join(clauses)}
                ORDER BY a.reserved_at DESC
                LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]

@router.get("/outbound/reasons")
def outbound_reasons(days: int = Query(default=30, ge=1, le=180)):
    """Why the book is not paying, counted.

    The question the product could not answer at all: it could say an account
    was 45 DPD with two bounces and never that the borrower lost their job in
    June. ``forgot`` is the row to watch — it counts the calls that were worth
    less than a reminder.
    """
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT nonpayment_reason AS reason, count(*) AS calls,
                       count(*) FILTER (WHERE objective_met) AS resolved
                FROM call_outcomes
                WHERE tenant_id = :tenant
                  AND nonpayment_reason IS NOT NULL
                  AND created_at >= now() - make_interval(days => :days)
                GROUP BY 1 ORDER BY 2 DESC
                """
            ),
            {"tenant": db.current_tenant(), "days": days},
        ).mappings().all()
    return [dict(r) for r in rows]

@router.get("/outbound/campaigns")
def list_campaign_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """Runs and how far through each one is."""
    clauses = ["r.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": db.current_tenant(), "limit": limit}
    if status:
        clauses.append("r.status = :status")
        params["status"] = status
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT r.*,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'pending')  AS pending,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'done')     AS done,
                  (SELECT count(*) FROM campaign_targets t
                    WHERE t.run_id = r.id AND t.state = 'skipped')  AS skipped
                FROM campaign_runs r
                WHERE {' AND '.join(clauses)}
                ORDER BY r.created_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]

@router.post("/outbound/campaigns")
def create_campaign_run(payload: dict[str, Any]):
    """Create a run in ``draft``. Nothing dials until it is explicitly started.

    Draft-by-default is the point. A campaign is the one object in this system
    whose accidental creation rings real phones, so bringing it into existence
    and setting it going are two deliberate acts rather than one.
    """
    import campaigns

    name = str(payload.get("name") or "").strip()
    objective = str(payload.get("objective") or "").strip()
    if not name or not objective:
        raise HTTPException(status_code=400, detail="name_and_objective_required")
    import flow_graph as fg

    if objective not in fg.OBJECTIVES:
        raise HTTPException(status_code=400, detail="unknown_objective")

    with db.engine.begin() as conn:
        run = campaigns.create(
            conn,
            tenant_id=db.current_tenant(),
            name=name,
            objective=objective,
            bot_id=payload.get("botId"),
            cadence=str(payload.get("cadence") or "default"),
            source=str(payload.get("source") or "list"),
            selector=payload.get("selector") or {},
            window_start_hour=int(payload.get("windowStartHour") or 10),
            window_end_hour=int(payload.get("windowEndHour") or 18),
            max_concurrent=int(payload.get("maxConcurrent") or 5),
            created_by_user_id=db._actor_user_id(),
        )
        ids = [str(c) for c in (payload.get("customerIds") or []) if str(c).strip()]
        if ids:
            campaigns.add_targets(conn, run["id"], ids, tenant_id=db.current_tenant())
        # A selector on the payload is resolved now, against the book as it
        # stands, and the resulting targets are frozen onto the run. Re-resolving
        # at dial time would mean the cohort an operator reviewed and the cohort
        # that got called were different populations — which is precisely the
        # audit answer a campaign exists to be able to give.
        selector = payload.get("selector") or {}
        if selector:
            try:
                campaigns.add_targets_from_selector(
                    conn, run["id"], tenant_id=db.current_tenant(), selector=selector
                )
            except campaigns.SelectorError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    return dict(run)

@router.post("/outbound/campaigns/preview")
def preview_campaign_cohort(payload: dict[str, Any]):
    """Who this selector would call, before a run exists.

    Deliberately reachable without a run id. A campaign is the one object here
    whose accidental creation rings real phones, so seeing the population has to
    be possible *before* committing to one — otherwise the only way to check a
    cohort is to create the thing you were checking.
    """
    import campaigns

    try:
        with db.engine.connect() as conn:
            return campaigns.preview_selector(
                conn,
                tenant_id=db.current_tenant(),
                selector=payload.get("selector") or {},
                sample=int(payload.get("sample") or 10),
            )
    except campaigns.SelectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/outbound/campaigns/{run_id}/targets")
def add_campaign_targets(run_id: str, payload: dict[str, Any]):
    import campaigns

    ids = [str(c) for c in (payload.get("customerIds") or []) if str(c).strip()]
    selector = payload.get("selector") or {}
    if not ids and not selector:
        raise HTTPException(status_code=400, detail="customer_ids_or_selector_required")
    try:
        with db.engine.begin() as conn:
            added = campaigns.add_targets(conn, run_id, ids, tenant_id=db.current_tenant()) if ids else 0
            if selector:
                added += campaigns.add_targets_from_selector(
                    conn, run_id, tenant_id=db.current_tenant(), selector=selector
                )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="campaign_run_not_found") from exc
    except campaigns.SelectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"runId": run_id, "added": added, "requested": len(ids)}

@router.post("/outbound/campaigns/{run_id}/status")
def set_campaign_status(run_id: str, payload: dict[str, Any]):
    """start / pause / finish / cancel.

    Pause takes effect on the next worker iteration and never mid-call: a call
    already in progress is a conversation with a person, and hanging up on them
    to honour a button is worse than letting it finish.
    """
    import campaigns

    status = str(payload.get("status") or "").strip()
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
        with db.engine.begin() as conn:
            run = campaigns.set_status(conn, run_id, status, tenant_id=db.current_tenant())
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return dict(run)

@router.get("/outbound/campaigns/{run_id}")
def get_campaign_run(run_id: str):
    import campaigns

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM campaign_runs WHERE id = :id AND tenant_id = :t"),
            {"id": run_id, "t": db.current_tenant()},
        ).mappings().first()
        if row is None:
            raise HTTPException(status_code=404, detail="run_not_found")
        return {**dict(row), "progress": campaigns.progress(conn, run_id)}

@router.get("/outbound/cadence")
def list_cadence_cases(
    customerId: str | None = Query(default=None),
    state: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """Open retry ladders — what is waiting, and what ran out of attempts."""
    clauses = ["s.tenant_id = :tenant"]
    params: dict[str, Any] = {"tenant": db.current_tenant(), "limit": limit}
    if customerId:
        clauses.append("s.customer_id = :cid")
        params["cid"] = customerId
    if state:
        clauses.append("s.state = :state")
        params["state"] = state
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT s.*, c.name AS customer_name
                FROM call_cadence_state s
                JOIN customers c ON c.id = s.customer_id
                WHERE {' AND '.join(clauses)}
                ORDER BY s.next_attempt_at ASC NULLS LAST, s.updated_at DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    return [dict(r) for r in rows]

@router.get("/outbound/number-pools")
def list_number_pools():
    """Caller-ID pools and the numbers in them, with how each is performing."""
    with db.engine.connect() as conn:
        pools = conn.execute(
            text(
                "SELECT * FROM number_pools WHERE tenant_id = :t ORDER BY name"
            ),
            {"t": db.current_tenant()},
        ).mappings().all()
        numbers = conn.execute(
            text(
                """
                SELECT n.* FROM pool_numbers n
                JOIN number_pools p ON p.id = n.pool_id
                WHERE p.tenant_id = :t
                ORDER BY n.e164
                """
            ),
            {"t": db.current_tenant()},
        ).mappings().all()
    by_pool: dict[str, list[dict[str, Any]]] = {}
    for row in numbers:
        by_pool.setdefault(str(row["pool_id"]), []).append(dict(row))
    return [{**dict(p), "numbers": by_pool.get(str(p["id"]), [])} for p in pools]

@router.get("/outbound/obligations")
def list_agent_obligations(
    state: str = Query(default="open"),
    limit: int = Query(default=50, ge=1, le=db.MAX_LIST_LIMIT),
):
    """What the agent promised and whether we kept it.

    An agent that keeps its promises is the whole trust proposition of an
    automated collections line, and a missed obligation is a QA finding with a
    named owner rather than a thing nobody knew happened.
    """
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT o.*, c.name AS customer_name
                FROM agent_obligations o
                JOIN customers c ON c.id = o.customer_id
                WHERE o.tenant_id = :t AND (:state = 'all' OR o.state = :state)
                ORDER BY o.due_at ASC
                LIMIT :limit
                """
            ),
            {"t": db.current_tenant(), "state": state, "limit": limit},
        ).mappings().all()
    return [dict(r) for r in rows]

@router.get("/outbound/card-vocabulary")
def outbound_card_vocabulary():
    """Every closed vocabulary the Outbound card editor has to offer.

    One endpoint rather than a constant per list in the frontend, and derived
    from the definitions the runtime and the compiler actually use rather than
    restated. That is not tidiness: ``card.outbound`` is validated by Pydantic
    models with ``extra="forbid"`` and gated by G-OB1..8, so an option the
    editor offers that the backend does not know is not a cosmetic mismatch —
    it builds a card that cannot be published, and the author finds out at the
    publish button with a validation error naming a field they picked from a
    dropdown.

    ``dailyCap`` is here for the same reason. G-OB3 fails a cadence planning
    more contacts per day than ``contact_policy`` permits; the editor can say so
    while the number is being typed instead of at compile time.
    """
    from typing import get_args

    import contact_policy
    import flow_graph as fg
    import mission as mission_mod
    import outbound as outbound_mod
    from agent_core.authority import config as authority_config
    from agent_core.cards import compile as compile_mod
    from agent_core.cards import schema as card_schema

    pools: list[dict[str, Any]] = []
    try:
        with db.engine.connect() as conn:
            pools = [
                {"name": str(r["name"]), "kind": str(r["kind"])}
                for r in conn.execute(
                    text(
                        "SELECT name, kind FROM number_pools "
                        "WHERE tenant_id = :t AND enabled IS TRUE ORDER BY name"
                    ),
                    {"t": db.current_tenant()},
                ).mappings()
            ]
    except Exception:
        # A tenant with no pools table yet still gets a usable editor; the pool
        # name is free text on the card and G-OB4 keys off `pool_kind`.
        logger.debug("number pool lookup failed", exc_info=True)

    return {
        "objectives": list(fg.OBJECTIVES),
        "objectiveBriefs": dict(mission_mod.OBJECTIVE_BRIEF),
        "directions": list(get_args(card_schema.Direction)),
        "voicemailModes": list(get_args(card_schema.VoicemailMode)),
        "poolKinds": list(get_args(card_schema.PoolKind)),
        "qaModes": ["always", "sampled", "never"],
        # The Closer's taxonomy — what `success` / `partial` / `stop_on` and a
        # post-call rule's `when` may name. G-OB6 rejects anything else.
        "outcomeCodes": sorted(compile_mod.OUTCOME_CODES),
        # Verbs the Closer implements. A rule may also name any tool on the
        # card, which is why G-OB6 checks the union rather than this alone.
        "postCallActions": sorted(compile_mod.POST_CALL_ACTIONS),
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

@router.get("/outbound/missions")
def list_missions(botId: str | None = Query(default=None)):
    """The missions a card can run, and where each starts.

    Serves the Outbound tab. Two sources, deliberately both: what the *card*
    declares and what the *graph* claims. They disagreeing is the failure G-OB2
    exists to catch, and an author needs to see both halves to fix it.

    ``botId`` is not optional in spirit. This read the default bot and nothing
    else, while the tab that calls it lives inside a per-card editor and says
    "No missions on **this card**" — so opening Outbound on any other card
    reported the default bot's missions, direction and number pool under that
    card's name. It is invisible today only because no card declares an
    outbound block yet, which makes every card show the same empty state; the
    first card to declare one would have shown its missions on all of them.
    """
    import flow_graph as fg
    import mission as mission_mod

    bot_id = (botId or "").strip() or db.DEFAULT_BOT_ID
    card = mission_mod.card_for_bot(bot_id)
    graph_entries: dict[str, str] = {}
    try:
        version = None
        studio = db.get_agent_studio_card(bot_id) or {}
        draft_id = studio.get("draftVersionId")
        if draft_id:
            version = db.get_prompt_version(draft_id) or {}
        if not (version and version.get("flow")):
            deployment = db.get_active_deployment(bot_id=bot_id, environment="production")
            if deployment and deployment.get("promptVersionId"):
                version = db.get_prompt_version(deployment["promptVersionId"]) or {}
        if version:
            graph_entries = fg.parse_graph(version.get("flow") or {}).entry_objectives()
    except Exception:
        logger.debug("mission entry lookup failed", exc_info=True)

    outbound_cfg = getattr(card, "outbound", None) if card is not None else None
    declared = [
        {
            "key": o.key,
            "entryNode": o.entry_node,
            "graphEntryNode": graph_entries.get(o.key),
            "agrees": graph_entries.get(o.key) == o.entry_node,
            "maxDurationSec": o.max_duration_sec,
            "allowedOffers": o.allowed_offers,
            "authorityProfile": o.authority_profile,
            "cadence": o.cadence,
            "success": o.success,
            "brief": mission_mod.OBJECTIVE_BRIEF.get(o.key, ""),
        }
        for o in (outbound_cfg.objectives if outbound_cfg else [])
    ]
    return {
        "botId": bot_id,
        "direction": getattr(outbound_cfg, "direction", "inbound"),
        "poolKind": getattr(outbound_cfg, "pool_kind", "general"),
        "numberPool": getattr(outbound_cfg, "number_pool", None),
        "objectives": declared,
        "graphEntries": graph_entries,
        "available": list(fg.OBJECTIVES),
    }

@router.get("/authority/next")
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

@router.post("/authority/apply")
def authority_apply(payload: AuthorityApplyRequest):
    """Post the goodwill the matrix already approved. Live mode only."""
    return _handle_write(db.apply_authority, payload.model_dump(exclude_none=True))

