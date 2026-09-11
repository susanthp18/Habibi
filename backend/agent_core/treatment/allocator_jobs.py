"""W13's three nightly jobs: the solve, its reference, and the refusal.

§10.5 derives the daily rhythm backwards from the 08:00 objective and puts the
allocator at 06:10-06:50 with a forty-minute job budget, because "the 39 seconds
is the solve, not the job" — materialising and scoring eighteen million account
× action rows out of Postgres dominates. Until W13 the solve was "a hand-run
script with no scheduler, no lock, no alert and a one-day price validity window"
`[solve-capacity-not-scheduled]`, which means every dual price in the system was
either absent or stale by construction. Measured on ``collections`` on
2026-09-11: one solve, ever, for ``plan_date = 2026-08-22``, twenty-one days
stale.

These are the job bodies. The scheduling, the advisory lock and the run ledger
are :mod:`wk_batch`'s, which already had all three.

**Three jobs rather than one**, because §10.4 gates the write switch on two
measurements that are not the solve:

``w13.capacity_solve``
    Price the book against tomorrow's capacity, and persist only if the answer
    can be believed.
``w13.allocator_gold``
    Solve a sub-book both ways and assert they agree. §10.4 wants this green
    ten consecutive nights, which is a count of rows in the job ledger rather
    than a promise.
``w13.allocator_regret``
    §10.4: "before the write switch is flipped we publish the regret of
    greedy-EV-plus-λ against a dual-adjusted learner on the gold-standard
    sub-book … That is a measurement with a date, not an assumption." There is
    no dual-adjusted learner to compare against, and this job is what says so
    with the numbers rather than leaving the gate unmeasured.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from agent_core.treatment import allocate, config

logger = logging.getLogger(__name__)

#: How far back to look for the decision that states an account's demand.
#:
#: The engine already computed every account's ranked candidate list against the
#: features as they were at decision time; re-scoring now would value tomorrow's
#: plan with today's DPD, which is both slower and wrong.
DEFAULT_SINCE_HOURS = 36


def demands(
    conn: Any,
    *,
    since_hours: int = DEFAULT_SINCE_HOURS,
    modes: Sequence[str] = ("shadow", "live"),
    tenant_id: str | None = None,
) -> tuple[list[allocate.Demand], dict[str, int]]:
    """One entry per account, from the most recent decision the engine made.

    Returns the book and a census of what was dropped getting to it, because a
    solve over four hundred accounts and a solve over four thousand produce
    different prices and only one of them is about the book.

    Three rules, and two of them are W13 repairs:

    **The latest decision only.** Two decisions for one account are two answers
    to the same question at different times, and counting both would double that
    account's demand for every resource it wanted.

    **Suppressed accounts are not demand**
    `[solve-capacity-counts-suppressed-accounts-as-demand]`. A borrower the veto
    stack forbade contacting cannot consume an agent minute at any price, and
    counting them bids up the price of a resource nobody can spend on them.
    §10.3: "the solve excludes accounts the engine decided not to contact".

    **The expected values are put back the way they were found**
    `[allocate-dual-price-double-counted-in-next-days-demand]`. ``scoring.score``
    writes ``ev = gross − cost − fatigue`` where ``cost`` already carries today's
    λ·usage, so reading the logged value as demand charges tomorrow for today's
    scarcity on top of its own. ``capacityPrice`` is logged beside the value
    since W13 precisely so it can be added back; a row written before W13 does
    not carry it, and on those the surcharge was zero anyway because dual
    pricing has never been on.
    """
    rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (COALESCE(account_id, customer_id))
                   COALESCE(account_id, customer_id) AS key,
                   candidates,
                   suppression_reason
            FROM treatment_decisions
            WHERE mode = ANY(:modes)
              AND created_at >= now() - make_interval(hours => :hours)
              AND (CAST(:tenant AS text) IS NULL OR tenant_id = :tenant)
            ORDER BY COALESCE(account_id, customer_id), created_at DESC
            """
        ),
        {"modes": list(modes), "hours": since_hours, "tenant": tenant_id},
    ).mappings().all()

    census = {
        "accounts": len(rows),
        "suppressed": 0,
        "noCandidates": 0,
        "preDualAdjusted": 0,
        "book": 0,
    }
    out: list[allocate.Demand] = []
    for row in rows:
        if row["suppression_reason"]:
            census["suppressed"] += 1
            continue
        entries = row["candidates"]
        if not isinstance(entries, list):
            census["noCandidates"] += 1
            continue
        values: dict[str, float] = {}
        adjusted = False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            action = entry.get("action")
            if not action or action == "wait":
                continue
            surcharge = float(entry.get("capacityPrice") or 0.0)
            if surcharge:
                adjusted = True
            values[str(action)] = float(entry.get("expectedValue") or 0.0) + surcharge
        if not values:
            census["noCandidates"] += 1
            continue
        if adjusted:
            census["preDualAdjusted"] += 1
        out.append(allocate.Demand(account_id=str(row["key"]), values=values))
    census["book"] = len(out)
    return out, census


def solve_book(
    conn: Any,
    *,
    tenant_id: str,
    plan_date: date | None = None,
    since_hours: int = DEFAULT_SINCE_HOURS,
    modes: Sequence[str] = ("shadow", "live"),
    persist: bool = True,
) -> dict[str, Any]:
    """Price tomorrow's book, and write the answer only if it can be believed."""
    day = plan_date or (datetime.now(timezone.utc) + timedelta(days=1)).date()
    book, census = demands(
        conn, since_hours=since_hours, modes=modes, tenant_id=tenant_id
    )
    capacity = allocate.capacity_plan(conn, tenant_id=tenant_id, plan_date=day)
    allocation = allocate.solve(
        book, capacity, plan_date=day, floor=config.policy().min_expected_value
    )
    out: dict[str, Any] = {
        "census": census,
        "allocation": allocation.to_log(),
        "resources": allocate.resource_report(conn, tenant_id=tenant_id),
    }
    if persist:
        out["persisted"] = allocate.persist(conn, allocation, tenant_id=tenant_id)
        allocate.reset_cache()
    return out


def gold_standard(
    conn: Any,
    *,
    tenant_id: str,
    since_hours: int = DEFAULT_SINCE_HOURS,
    modes: Sequence[str] = ("shadow", "live"),
    sample: int = allocate.GOLD_SAMPLE,
) -> dict[str, Any]:
    """Solve a sub-book both ways and report the disagreement as a number."""
    book, census = demands(
        conn, since_hours=since_hours, modes=modes, tenant_id=tenant_id
    )
    capacity = allocate.capacity_plan(conn, tenant_id=tenant_id)
    report = allocate.gold_standard(
        book, capacity, floor=config.policy().min_expected_value, sample=sample
    )
    report["census"] = census
    if not report.get("evaluable"):
        logger.warning("gold standard not evaluable: %s", report.get("reason"))
    return report


def regret(
    conn: Any,
    *,
    tenant_id: str,
    since_hours: int = DEFAULT_SINCE_HOURS,
    modes: Sequence[str] = ("shadow", "live"),
    sample: int = allocate.GOLD_SAMPLE,
) -> dict[str, Any]:
    """§10.4's objective-mismatch measurement, filed with whatever it can say.

    The question is real and the document is honest about it: "the offline
    learner should arguably be trained against the **dual-adjusted** objective
    rather than raw EV, or the two halves fight each other. Our stated position
    is that τ is fitted against the outcome and the dual price enters the
    arithmetic outside the model — the auditable arrangement, and the one a
    validator can separate — **but before the write switch is flipped we publish
    the regret of greedy-EV-plus-λ against a dual-adjusted learner on the
    gold-standard sub-book.** If they differ materially, the ordering of the
    estimator and allocator waves is wrong and the plan changes."

    Half of that comparison is computable today and half is not. Greedy-EV-plus-λ
    is what this allocator does, and its objective on the sub-book is measured
    here. The dual-adjusted learner does not exist: W10 refused to fit anything
    for want of labels, and `registry.corpus_objections` says so with the counts.
    So this files the half that exists, ``null`` for the half that does not, and
    the reason — which is what "a measurement with a date" means when the
    measurement cannot be completed. A filed guess would not be.
    """
    from agent_core.treatment import registry

    book, census = demands(
        conn, since_hours=since_hours, modes=modes, tenant_id=tenant_id
    )
    capacity = allocate.capacity_plan(conn, tenant_id=tenant_id)
    floor = config.policy().min_expected_value
    greedy = allocate.solve(book[:sample], capacity, floor=floor)

    try:
        objections = registry.corpus_objections(conn, tenant_id=tenant_id)
    except Exception:
        logger.exception("corpus objections unreadable")
        objections = ["corpus_unreadable"]
    champion = None
    try:
        champion = registry.champion(conn, tenant_id=tenant_id, target="timing")
    except Exception:
        logger.exception("registry unreadable")

    refused = champion is None
    return {
        "subBook": census,
        "greedyEvPlusLambda": {
            "objectiveInr": round(greedy.primal_value, 2),
            "grossValueInr": round(greedy.gross_value, 2),
            "prices": {r: round(p, 4) for r, p in greedy.prices.items()},
            "converged": greedy.converged,
            "feasible": greedy.feasible,
        },
        # The other arm of the comparison, and it is null on purpose.
        "dualAdjustedLearner": None,
        "regretInr": None,
        "refusedBecause": "no_promoted_estimator" if refused else None,
        # The numbers behind that refusal, so the reader does not have to take
        # it on trust: these are what §8.10 rung 1 measures the corpus against.
        "corpusObjections": objections,
        "labels": _label_counts(conn, tenant_id=tenant_id),
        "measuredAt": datetime.now(timezone.utc).isoformat(),
    }


def _label_counts(conn: Any, *, tenant_id: str) -> dict[str, Any]:
    """What the panel holds, which is what a learner would have to be fitted on."""
    from agent_core.treatment import schema_ready

    if not schema_ready.has_table(conn, "analysis_panel"):
        return {"evaluable": False, "reason": "no_analysis_panel"}
    row = conn.execute(
        text(
            """
            SELECT count(*)::int AS cases,
                   count(DISTINCT customer_id)::int AS customers,
                   count(*) FILTER (WHERE mature)::int AS mature,
                   count(*) FILTER (WHERE reach_outcome IS NOT NULL)::int AS reach,
                   count(*) FILTER (WHERE cure_outcome IS NOT NULL)::int AS cure
            FROM analysis_panel
            WHERE tenant_id = :tenant
            """
        ),
        {"tenant": tenant_id},
    ).mappings().first()
    return {"evaluable": True, **{k: int(v or 0) for k, v in dict(row or {}).items()}}


def run(
    job_type: str, conn: Any, *, tenant_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Dispatch one W13 job. Called by :mod:`wk_batch` under its advisory lock."""
    from wk_batch import ALLOCATOR_GOLD, ALLOCATOR_REGRET, CAPACITY_SOLVE

    since = int(payload.get("since_hours") or DEFAULT_SINCE_HOURS)
    modes = ["shadow", "live"]
    if str(payload.get("include_simulated") or "") == "1":
        modes.append("simulated")

    if job_type == CAPACITY_SOLVE:
        plan_date = payload.get("plan_date")
        return solve_book(
            conn,
            tenant_id=tenant_id,
            plan_date=date.fromisoformat(str(plan_date)) if plan_date else None,
            since_hours=since,
            modes=modes,
            persist=str(payload.get("dry_run") or "") != "1",
        )
    if job_type == ALLOCATOR_GOLD:
        return gold_standard(conn, tenant_id=tenant_id, since_hours=since, modes=modes)
    if job_type == ALLOCATOR_REGRET:
        return regret(conn, tenant_id=tenant_id, since_hours=since, modes=modes)
    raise ValueError(f"unknown_w13_job:{job_type}")
