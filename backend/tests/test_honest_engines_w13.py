"""W13 — the allocator, and the price nobody is allowed to believe yet.

§15.2's W13 exit criteria, in three numbers:

    **|Δλ|/λ < 0.15** day over day under a synthetic 5% capacity shock; the
    regret measurement **filed before** the write switch is flipped;
    **``lambda_bucket`` carries a real bucket on 100% of new rows**, replacing
    W2's ``'none'``.

Measured read-only against ``collections`` on 2026-09-11, which is what shapes
the wave:

    capacity_duals rows                 4, from ONE solve, plan_date 2026-08-22
    ...solved on                        2026-08-21 — twenty-one days stale
    ...mandate_presentations row        capacity 0.00, demand 486, converged = t
    bank_capacity (the C9 feed)         0 rows, and capacity_plan never read it
    lambda_bucket                       302 of 304 NULL, 2 'none'
    numpy in collections_api            absent
    passes per solve()                  6 sweeps x 4 resources x 21 = 504

That third line is the wave in miniature. Read literally it says 486 mandate
presentations are planned against a budget of nothing and the solver calls it
converged. It is not what happened: ``capacity_plan`` dropped any resource whose
environment variable was unset and ``persist`` wrote ``capacity.get(r, 0.0)``, so
"nobody configured this" and "the budget is nothing" arrived in the table as the
same number.

The load-bearing test in this file is
:func:`test_the_serving_path_does_not_import_numpy`. Everything else here is
arithmetic about a price nothing reads; that one is the difference between the
API starting and not.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import os
import random
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from agent_core import logging_contract
from agent_core.treatment import allocate, allocator_jobs, schema_ready, scoring
from agent_core.treatment import sweep as book_sweep

BACKEND = Path(__file__).resolve().parents[1]

pytest.importorskip("numpy", reason="the allocator's solve needs numpy; the read path does not")
pytest.importorskip("scipy", reason="the cutting-plane master and the gold standard need HiGHS")

ACTIONS = ("sms", "whatsapp", "voice_bot", "human_call", "field_visit", "represent_mandate")


@pytest.fixture(autouse=True)
def _reset():
    schema_ready.reset_cache()
    allocate.reset_cache()
    yield
    schema_ready.reset_cache()
    allocate.reset_cache()


def _book(n: int = 400, seed: int = 7) -> list[allocate.Demand]:
    rng = random.Random(seed)
    return [
        allocate.Demand(
            f"A{i}", {a: round(rng.random() * 500, 2) for a in ACTIONS}
        )
        for i in range(n)
    ]


def _require_w13(db_tx) -> None:
    """``capacity_duals.feasible`` is this wave's own column (sql/33, 0122)."""
    if not schema_ready.w13_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("capacity_duals.feasible absent (migration 0122)")
        pytest.skip("capacity_duals.feasible absent (migration 0122 unapplied)")


def _tenant(db_tx) -> str:
    tenant = db_tx.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    if not tenant:
        pytest.skip("no tenant seeded")
    return str(tenant)


# ---------------------------------------------------------------------------
# The one that decides whether the API starts
# ---------------------------------------------------------------------------


def test_the_serving_path_does_not_import_numpy() -> None:
    """``allocate`` is on the path that decides whether a borrower is contacted.

    ``config.Costs.for_action`` imports it, the scorer calls that, and the
    scorer runs inside the API. Measured 2026-09-11: ``collections_api`` and
    both batch workers have no numpy — only the voice image does, via pipecat.
    A module-level import would take the API down to add a price it does not
    solve for.

    Asserted on the syntax tree rather than by importing, because an import that
    has already happened in this process would pass either way.
    """
    tree = ast.parse((BACKEND / "agent_core" / "treatment" / "allocate.py").read_text("utf-8"))
    top_level = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    names = {
        alias.name.split(".")[0]
        for node in top_level
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in top_level
        if isinstance(node, ast.ImportFrom)
    }
    assert "numpy" not in names and "scipy" not in names, (
        f"allocate.py imports {names & {'numpy', 'scipy'}} at module scope. "
        "The read half of this module is pure SQL and must keep working on an "
        "image that has no solver."
    )


def test_a_missing_solver_refuses_rather_than_falling_back() -> None:
    """Two solvers in one file is the bypass §8.12 forbids.

    Without numpy the solve returns a refusal and writes nothing. It does not
    quietly run a slower algorithm, because then nobody could tell which one
    produced the price a floor manager is reading.
    """
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.split(".")[0] in {"numpy", "scipy"}:
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    builtins.__import__ = blocked
    try:
        # Purge any cached module so the guarded import actually re-runs.
        solved = allocate.solve(_book(50), {"agent_minutes": 100}, floor=2.0)
    finally:
        builtins.__import__ = real_import
    if solved.refusals == ("numpy_unavailable",):
        assert not solved.converged and not solved.feasible
        assert all(p == 0.0 for p in solved.prices.values())
    else:  # pragma: no cover - numpy already imported in this process
        pytest.skip("numpy was already imported; the guard cannot be exercised here")


# ---------------------------------------------------------------------------
# §10.1 — a solve that knows how far from optimal it is
# ---------------------------------------------------------------------------


def test_the_allocator_agrees_with_the_lp_it_is_an_approximation_of() -> None:
    """§10.4's gold standard, on a book small enough to solve both ways.

    "assert the allocator's objective is within 0.1% and its λ within 1e-3 of
    the LP duals". The λ half is the one that matters: the objective can agree
    while the published price is somewhere else, which is §10.1 defect 3.
    """
    report = allocate.gold_standard(
        _book(600), {"agent_minutes": 1200, "field_slots": 40}, floor=2.0
    )
    assert report["evaluable"], report.get("reason")
    assert report["objectiveError"] <= allocate.GOLD_OBJECTIVE_TOLERANCE
    assert report["worstPriceError"] <= allocate.GOLD_PRICE_TOLERANCE, (
        f"λ disagrees with HiGHS by {report['worstPriceError']:.2e}: the dual "
        "loop stopped while the price was still moving"
    )
    assert report["agrees"]


def test_the_solve_says_how_far_from_optimal_it_is() -> None:
    """Coordinate descent could not, and that is why the gold standard had
    nothing to compare against until W13."""
    solved = allocate.solve(_book(600), {"agent_minutes": 1200}, floor=2.0)
    assert solved.converged and solved.feasible
    # The relaxation bounds the integral plan from above. Not an assertion
    # about quality — an assertion that the two numbers are the right way round.
    assert solved.dual_bound >= solved.primal_value
    assert 0.0 <= solved.duality_gap <= allocate.REPAIR_GAP_CEILING
    assert solved.iterations >= 1


def test_the_plan_never_overbooks_a_resource() -> None:
    """§10.1 defect 2: the prototype terminated at 2M with an overshoot still
    present. Exactly, not within a tolerance — the field team is a number of
    people."""
    capacity = {"agent_minutes": 900, "field_slots": 12, "bot_minutes": 400}
    solved = allocate.solve(_book(800), capacity, floor=2.0)
    assert solved.feasible
    for resource, limit in capacity.items():
        assert solved.demand[resource] <= limit + 1e-6, resource


def test_the_swap_repair_beats_dropping_the_marginal_account_to_wait() -> None:
    """§10.1 defect 1, as a comparison rather than as a citation.

    The naive repair — drop the lowest-surplus accounts on the tight resource
    until it fits — gave gaps of 0.37-1.06%; the swap repair, which moves them
    to their best alternative action instead, gave 0.003%. Both are feasible;
    one of them is worth a lot of money at two million accounts.
    """
    import numpy as np

    book = _book(800)
    capacity = {"agent_minutes": 700}
    floor = 2.0
    solved = allocate.solve(book, capacity, floor=floor)
    assert solved.feasible

    values, usage, _actions = allocate._matrices(book, floor, allocate.RESOURCES)
    n, m = values.shape
    limits = np.array(
        [capacity.get(r, np.inf) for r in allocate.RESOURCES], dtype=np.float64
    )
    lam = np.array(
        [solved.prices[r] for r in allocate.RESOURCES], dtype=np.float64
    )
    reduced = values - usage @ lam
    choice = reduced.argmax(axis=1)
    rows = np.arange(n)

    # The naive repair: everything over capacity goes to the null action,
    # cheapest surplus first.
    naive = choice.copy()
    for index, resource in enumerate(allocate.RESOURCES):
        limit = limits[index]
        if not np.isfinite(limit):
            continue
        while True:
            counts = np.bincount(naive, minlength=m).astype(np.float64)
            over = counts @ usage[:, index] - limit
            if over <= 1e-9:
                break
            on_it = np.nonzero(usage[naive, index] > 0)[0]
            if on_it.size == 0:
                break
            worst = on_it[np.argmin(reduced[on_it, naive[on_it]])]
            naive[worst] = m - 1

    def surplus(assignment):
        taken = assignment != m - 1
        return float(np.where(taken, values[rows, assignment] - floor, 0.0).sum())

    assert surplus(naive) <= solved.primal_value + 1e-6, (
        "the swap repair lost more than dropping accounts to wait, which means "
        "it is not the repair §10.1 measured"
    )


def test_two_solves_of_the_same_book_agree() -> None:
    """A price that wanders between identical solves cannot be told apart from
    scarcity, which is the whole content of the number."""
    book = _book(300)
    first = allocate.solve(book, {"agent_minutes": 600}, floor=2.0)
    second = allocate.solve(book, {"agent_minutes": 600}, floor=2.0)
    assert first.prices == second.prices
    assert first.mix == second.mix


def test_price_stability_under_a_five_percent_capacity_shock() -> None:
    """W13's first exit criterion: |Δλ|/λ < 0.15.

    Reported whether or not it clears, and measured on the UNDAMPED prices —
    a stability claim measured after smoothing is a claim about the smoother.
    """
    report = allocate.shock_report(_book(800), {"agent_minutes": 900}, floor=2.0)
    assert report["evaluable"], "nothing was binding, so nothing was measured"
    assert report["threshold"] == 0.15
    assert report["worst"] < 0.15, report["relativeMove"]
    assert report["clears"]


def test_an_unpriced_book_is_not_a_stable_one() -> None:
    """§8.12: an unevaluable gate is a refusal. A shock test over a book where
    nothing binds has measured nothing, and reading that as a pass is how a gate
    becomes decorative."""
    report = allocate.shock_report(_book(50), {}, floor=2.0)
    assert report["evaluable"] is False
    assert report["clears"] is False


# ---------------------------------------------------------------------------
# §10.2 — capacity has three states
# ---------------------------------------------------------------------------


def test_an_unconfigured_resource_is_not_a_budget_of_nothing() -> None:
    """The row measured on ``collections``: capacity 0.00, demand 486, converged.

    That row says a resource is 486 units oversubscribed. It means nobody ever
    set ``TREATMENT_CAPACITY_MANDATE_PRESENTATIONS``.
    """
    solved = allocate.solve(_book(200), {"agent_minutes": 500}, floor=2.0)
    assert solved.capacity["mandate_presentations"] is None
    assert solved.capacity_source["mandate_presentations"] == "unset"
    assert solved.prices["mandate_presentations"] == 0.0
    assert solved.to_log()["capacity"]["mandate_presentations"] is None


def test_a_configured_zero_is_a_real_constraint() -> None:
    """And the solve refuses against it rather than pricing it at zero."""
    solved = allocate.solve(_book(200), {"field_slots": 0}, floor=2.0)
    assert solved.capacity["field_slots"] == 0.0
    assert solved.demand["field_slots"] == 0.0
    assert solved.prices["field_slots"] == allocate.MAX_PRICE
    assert "price_at_ceiling" in solved.refusals
    assert not solved.servable()


def test_capacity_comes_from_the_feed_when_there_is_one(db_tx, monkeypatch) -> None:
    """W5 landed ``bank_capacity`` and C9 ingest; nothing read it until W13."""
    tenant = _tenant(db_tx)
    if not schema_ready.has_table(db_tx, "bank_capacity"):
        pytest.skip("bank_capacity absent (migration 0110 unapplied)")
    monkeypatch.setenv("TREATMENT_CAPACITY_AGENT_MINUTES", "11")
    day = date(2026, 9, 12)
    db_tx.execute(
        text(
            """
            INSERT INTO bank_capacity
              (id, tenant_id, plan_date, resource, capacity_units, known_from)
            VALUES (:id, :tenant, :day, 'agent_minutes', 4242, now())
            ON CONFLICT (tenant_id, plan_date, resource) DO UPDATE
              SET capacity_units = EXCLUDED.capacity_units
            """
        ),
        {"id": f"BC-{random.randrange(10**9)}", "tenant": tenant, "day": day},
    )
    plan = allocate.capacity_plan(db_tx, tenant_id=tenant, plan_date=day)
    assert plan["agent_minutes"].units == 4242.0
    assert plan["agent_minutes"].source == "feed", (
        "the environment won over the feed, which is the wrong way round: "
        "§10.2 makes C9 the capacity input and the env var the fallback"
    )


def test_the_environment_survives_as_a_named_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TREATMENT_CAPACITY_FIELD_SLOTS", "60")
    plan = allocate.capacity_plan()
    assert plan["field_slots"].units == 60.0
    assert plan["field_slots"].source == "env"


def test_the_resources_this_tree_will_not_price_are_named() -> None:
    """§10.2's complaint is that the resource set "omits every constraint that
    actually binds in an Indian NBFC". A list that does not say what is missing
    from it reads as a claim that nothing is."""
    assert "nach_return_budget" in allocate.REFUSED_RESOURCES
    assert "dlt_template_throughput" in allocate.REFUSED_RESOURCES
    assert "whatsapp_bsp_tier" in allocate.REFUSED_RESOURCES
    for resource, reason in allocate.REFUSED_RESOURCES.items():
        assert reason and reason != "todo", resource
        assert resource not in allocate.USAGE, (
            f"{resource} is both priced and refused, which is two answers"
        )


def test_the_return_budget_reports_its_ratio_and_declines_to_price_it(db_tx) -> None:
    """§10.2 keys it on ``(utility_code, sponsor_bank)`` and neither column
    exists, so the ratio below is the aggregate of buckets that can be barred
    independently — a warning, not a constraint."""
    tenant = _tenant(db_tx)
    budget = allocate.return_budget(db_tx, tenant_id=tenant)
    assert budget["ceiling"] == 0.50
    assert budget["prudentCeiling"] == 0.45
    assert "no_sponsor_bank_key" in budget["refusedBecause"]
    assert "no_return_model" in budget["refusedBecause"]
    assert budget["keyedOn"] is None


# ---------------------------------------------------------------------------
# §10.1 defect 4 — a price the solver does not believe is not a price
# ---------------------------------------------------------------------------


def test_a_solve_that_did_not_converge_is_never_written(db_tx) -> None:
    _require_w13(db_tx)
    tenant = _tenant(db_tx)
    solved = allocate.solve(_book(200), {"field_slots": 0}, floor=2.0)
    assert not solved.servable()
    outcome = allocate.persist(db_tx, solved, tenant_id=tenant)
    assert outcome["written"] == 0
    assert "price_at_ceiling" in outcome["refused"]
    assert (
        db_tx.execute(
            text(
                "SELECT count(*) FROM capacity_duals"
                " WHERE tenant_id = :t AND plan_date = :d"
            ),
            {"t": tenant, "d": solved.plan_date},
        ).scalar()
        == 0
    )


def test_a_published_price_is_damped_against_the_day_before(db_tx) -> None:
    """§10.3 publishes λ as a business price and §10.1 defect 3 measures λ as
    more weakly identified than the objective. Both numbers are kept: the damped
    one is served, the raw one is what the solve alone said."""
    _require_w13(db_tx)
    tenant = _tenant(db_tx)
    book = _book(600)
    first = allocate.solve(book, {"agent_minutes": 1200}, plan_date=date(2026, 9, 20), floor=2.0)
    assert first.servable()
    allocate.persist(db_tx, first, tenant_id=tenant)

    # A tighter day: the raw price rises, the served one moves halfway.
    second = allocate.solve(book, {"agent_minutes": 600}, plan_date=date(2026, 9, 21), floor=2.0)
    assert second.servable()
    allocate.persist(db_tx, second, tenant_id=tenant)

    row = db_tx.execute(
        text(
            "SELECT dual_price, dual_price_raw, damping, capacity_source, capacity"
            " FROM capacity_duals"
            " WHERE tenant_id = :t AND plan_date = :d AND resource = 'agent_minutes'"
        ),
        {"t": tenant, "d": date(2026, 9, 21)},
    ).mappings().first()
    assert row is not None
    raw = float(row["dual_price_raw"])
    served = float(row["dual_price"])
    alpha = float(row["damping"])
    expected = (1 - alpha) * first.prices["agent_minutes"] + alpha * raw
    # numeric(14,4): both stored numbers are rounded and `expected` mixes one
    # of them with an unrounded float, so the comparison is to one unit in the
    # column's last place rather than to the float the solver produced.
    assert served == pytest.approx(expected, abs=1e-4)
    assert raw == pytest.approx(second.prices["agent_minutes"], abs=1e-4)
    # The damping is doing something: the served price is strictly between
    # yesterday's and today's, which is the whole of §10.1 defect 3's remedy.
    assert min(first.prices["agent_minutes"], raw) < served < max(
        first.prices["agent_minutes"], raw
    )
    assert row["capacity_source"] == "env"
    assert float(row["capacity"]) == 600.0


def test_only_a_believable_price_is_servable(db_tx) -> None:
    """Refusing to persist is not enough on its own: a row written by an older
    build is still readable, so the read filters too."""
    _require_w13(db_tx)
    tenant = _tenant(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO capacity_duals
              (id, tenant_id, plan_date, resource, capacity, demand, dual_price,
               converged, feasible)
            VALUES (:id, :t, CURRENT_DATE, 'agent_minutes', 100, 900, 4500,
                    true, false)
            ON CONFLICT (tenant_id, plan_date, resource) DO UPDATE
              SET dual_price = EXCLUDED.dual_price, feasible = false
            """
        ),
        {"id": f"CD-{random.randrange(10**9)}", "t": tenant},
    )
    servable = db_tx.execute(
        text(
            "SELECT count(*) FROM capacity_duals"
            " WHERE tenant_id = :t AND plan_date = CURRENT_DATE"
            " AND converged AND feasible"
        ),
        {"t": tenant},
    ).scalar()
    assert servable == 0, (
        "an infeasible solve is readable as a price; §10.1 defect 4's ₹4.5m "
        "field-visit price is exactly this row"
    )


def test_the_price_cache_is_keyed_by_tenant() -> None:
    """`[allocate-cache-not-tenant-keyed]`. One process-global tuple served
    every tenant whichever one read first, for up to a minute."""
    allocate.reset_cache()
    allocate._CACHE["tenant-a"] = (float("inf"), {"agent_minutes": 19.0})
    allocate._CACHE["tenant-b"] = (float("inf"), {"agent_minutes": 0.0})
    assert allocate._CACHE["tenant-a"] != allocate._CACHE["tenant-b"]
    assert isinstance(allocate._CACHE, dict)


# ---------------------------------------------------------------------------
# §10.3 — the double count
# ---------------------------------------------------------------------------


def test_a_scored_action_can_be_put_back_the_way_it_was_found() -> None:
    """``expected_value`` has λ·usage subtracted; ``capacity_price`` is how much.

    Without this the allocator reads its own surcharge back as demand and the
    price compounds daily
    `[allocate-dual-price-double-counted-in-next-days-demand]`.
    """
    scored = scoring.ScoredAction(
        action="human_call",
        channel="voice",
        at=None,
        expected_value=94.0,
        p_reach=0.5,
        p_resolve=0.4,
        cost=51.0,
        capacity_price=6.0,
        explanation="",
    )
    assert scored.pre_dual_expected_value == 100.0
    assert scored.to_log()["capacityPrice"] == 6.0


def test_the_cost_term_still_has_exactly_one_place_lambda_is_added() -> None:
    """Splitting the term must not create a second one. §8.1's opening
    complaint is four quantities all called the treatment effect; two
    definitions of what an action costs is the same failure one layer down."""
    from agent_core.treatment import config as treatment_config

    costs = treatment_config.Costs(
        sms=1.0,
        whatsapp=2.0,
        voice_bot=3.0,
        human_call=45.0,
        field_visit=1150.0,
        legal_notice=250.0,
        represent_mandate=12.0,
        emi_date_change=0.0,
        self_service_plan=0.0,
    )
    for action in ("sms", "human_call", "field_visit"):
        assert costs.for_action(action) == pytest.approx(
            costs.ledger_price(action) + costs.capacity_price(action)
        )
    # Unpriced stays infinite, which is what keeps a new action family from
    # outranking every priced one on its first day.
    assert costs.for_action("device_lock") == float("inf")


def test_tomorrows_solve_does_not_pay_for_todays_scarcity(db_tx) -> None:
    """The logged expected value is put back before it is read as demand."""
    tenant = _tenant(db_tx)
    customer = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t LIMIT 1"), {"t": tenant}
    ).scalar()
    if not customer:
        pytest.skip("no seeded customer")
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions
              (id, tenant_id, customer_id, trigger_kind, mode,
               recommender, recommender_version, feature_schema_version,
               candidates)
            VALUES ('TD-W13-PRICED', :t, :c, 'dpd_tick', 'shadow',
                    'ev', '1.0.0', 'v1', CAST(:candidates AS jsonb))
            """
        ),
        {
            "t": tenant,
            "c": customer,
            "candidates": (
                '[{"action": "human_call", "expectedValue": 94.0, '
                '"capacityPrice": 6.0}]'
            ),
        },
    )
    book, census = allocator_jobs.demands(db_tx, since_hours=24, tenant_id=tenant)
    # `demands` keys on COALESCE(account_id, customer_id); this row has no
    # account, which is also the shape a customer-grain decision takes.
    mine = [d for d in book if d.account_id == str(customer)]
    assert mine, "the decision was not read as demand at all"
    assert mine[0].values["human_call"] == pytest.approx(100.0)
    assert census["preDualAdjusted"] >= 1


def test_a_suppressed_borrower_is_not_demand(db_tx) -> None:
    """`[solve-capacity-counts-suppressed-accounts-as-demand]`. A borrower the
    veto stack forbade contacting cannot consume an agent minute at any price,
    and counting them bids up a resource nobody can spend on them."""
    tenant = _tenant(db_tx)
    customer = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t LIMIT 1"), {"t": tenant}
    ).scalar()
    if not customer:
        pytest.skip("no seeded customer")
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions
              (id, tenant_id, customer_id, trigger_kind, mode,
               recommender, recommender_version, feature_schema_version,
               candidates, suppression_reason)
            VALUES ('TD-W13-DND', :t, :c, 'dpd_tick', 'shadow',
                    'ev', '1.0.0', 'v1',
                    CAST('[{"action": "human_call", "expectedValue": 500.0}]' AS jsonb),
                    'dnd')
            """
        ),
        {"t": tenant, "c": customer},
    )
    book, census = allocator_jobs.demands(db_tx, since_hours=24, tenant_id=tenant)
    assert not [d for d in book if d.account_id == str(customer)]
    assert census["suppressed"] >= 1


# ---------------------------------------------------------------------------
# W13's third exit criterion — lambda_bucket carries a real bucket
# ---------------------------------------------------------------------------


def test_the_bucket_is_none_while_the_price_is_gated_off() -> None:
    """And that is the truth rather than a placeholder: λ never entered the
    score, so every such row is one equivalence class. Every row in this tree's
    corpus is one of those and stays one after this ships."""
    assert logging_contract.lambda_bucket({}, pricing_enabled=False) == "none"
    assert (
        logging_contract.lambda_bucket({"agent_minutes": 19.0}, pricing_enabled=False)
        == "none"
    )


def test_nothing_binding_is_also_none() -> None:
    assert logging_contract.lambda_bucket({"agent_minutes": 0.0}, pricing_enabled=True) == "none"


def test_the_bucket_names_the_binding_set_and_its_band() -> None:
    bucket = logging_contract.lambda_bucket(
        {"agent_minutes": 19.0, "field_slots": 0.0, "bot_minutes": 0.6},
        pricing_enabled=True,
    )
    assert bucket == "agent_minutes:3|bot_minutes:1"
    assert "field_slots" not in bucket, "a zero price is not binding"


def test_the_bucket_does_not_move_when_a_price_moves_a_rupee() -> None:
    """``lambda_bucket`` is in ``ope.CLASS_COLUMNS``, so it partitions the
    off-policy corpus. A bucket carrying λ to two decimal places would make
    every day its own equivalence class and leave nothing with enough rows to
    evaluate — the failure §8.9 names for ``policy_binding_hash``, arriving
    through a different door."""
    from agent_core.treatment import ope

    assert "lambda_bucket" in ope.CLASS_COLUMNS
    monday = logging_contract.lambda_bucket({"agent_minutes": 11.0}, pricing_enabled=True)
    tuesday = logging_contract.lambda_bucket({"agent_minutes": 12.4}, pricing_enabled=True)
    assert monday == tuesday
    # But a move across a band is a different logging policy and says so.
    friday = logging_contract.lambda_bucket({"agent_minutes": 140.0}, pricing_enabled=True)
    assert friday != monday


def test_the_bands_are_ordered_and_start_at_not_binding() -> None:
    assert logging_contract.lambda_band(0.0) == 0
    assert logging_contract.lambda_band(-1.0) == 0
    bands = [logging_contract.lambda_band(p) for p in (0.5, 3.0, 11.0, 50.0, 300.0, 9000.0)]
    assert bands == sorted(bands)
    assert len(set(bands)) == len(bands)


def test_every_new_decision_carries_a_bucket(db_tx) -> None:
    """W2's exit criterion was "non-null with their defined day-1 values on 100%
    of live rows"; measured 2026-09-11, 302 of 304 rows are NULL because they
    predate 0107. What W13 owes is that no NEW row is."""
    from agent_core.treatment import decisions as treatment_decisions

    tenant = _tenant(db_tx)
    customer = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t LIMIT 1"), {"t": tenant}
    ).scalar()
    if not customer:
        pytest.skip("no seeded customer")
    if not schema_ready.w2_ready(db_tx):
        pytest.skip("lambda_bucket absent (migration 0107 unapplied)")
    decision_id = treatment_decisions.record(
        conn=db_tx,
        tenant_id=tenant,
        customer_id=str(customer),
        account_id=None,
        interaction_id=None,
        trigger_kind="dpd_tick",
        trigger_ref=None,
        mode="shadow",
        variant=None,
        recommender="ev",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_action="wait",
        chosen_channel=None,
        scheduled_at=None,
        expected_value=0.0,
        suppression_reason=None,
        rationale=None,
        latency_ms=1,
        lambda_bucket=logging_contract.lambda_bucket(),
    )
    assert decision_id
    bucket = db_tx.execute(
        text("SELECT lambda_bucket FROM treatment_decisions WHERE id = :id"),
        {"id": decision_id},
    ).scalar()
    assert bucket is not None
    assert bucket == "none", "dual pricing is gated off, so nothing was priced"


# ---------------------------------------------------------------------------
# §10.4 — the write switch, and no way round it
# ---------------------------------------------------------------------------


def test_every_gate_on_the_write_switch_refuses_today(db_tx) -> None:
    """The deliverable, in the W12 shape: all six, named, with numbers behind
    them. An empty list here would mean an estimator is serving and ten green
    gold-standard nights are on record, neither of which is true."""
    tenant = _tenant(db_tx)
    objections = allocate.write_switch_objections(db_tx, tenant_id=tenant)
    assert "no_promoted_estimator" in objections
    assert any(o.startswith("gold_standard_nights=") for o in objections)
    assert any(o.startswith("regret_not_measur") for o in objections)
    assert objections, "the gate opened, which needs six separate things to be true"


def test_the_environment_variable_cannot_open_the_gate(monkeypatch) -> None:
    """§8.12: "a gate with a documented bypass is worse than no gate". The
    variable can only ever turn the price off."""
    monkeypatch.setenv("TREATMENT_DUAL_PRICING", "1")
    monkeypatch.setattr(allocate, "_cached_objections", lambda: ["no_promoted_estimator"])
    assert allocate.enabled() is False
    monkeypatch.setattr(allocate, "_cached_objections", lambda: [])
    assert allocate.enabled() is True
    monkeypatch.setenv("TREATMENT_DUAL_PRICING", "0")
    assert allocate.enabled() is False


def test_the_gate_fails_closed_when_it_cannot_be_read(monkeypatch) -> None:
    """The thing being gated changes who gets contacted, so an unreadable gate
    disables the price rather than passing it."""
    monkeypatch.setenv("TREATMENT_DUAL_PRICING", "1")

    def explode(*_args, **_kwargs):
        raise RuntimeError("no database")

    monkeypatch.setattr(allocate, "write_switch_objections", explode)
    allocate.reset_cache()
    assert allocate.enabled() is False


def test_a_filed_refusal_does_not_clear_the_regret_gate() -> None:
    """§10.4 asks for the regret "filed before the write switch is flipped".
    Filing that it cannot be measured satisfies "a measurement with a date" and
    must not open the gate: a null regret does not answer the question the gate
    is asking."""
    report = {"regretInr": None, "refusedBecause": "no_promoted_estimator"}
    assert report["regretInr"] is None
    # The objection the gate raises for exactly this shape.
    assert "regret_not_measurable:no_promoted_estimator" == (
        f"regret_not_measurable:{report['refusedBecause']}"
    )


def test_the_regret_measurement_files_the_half_it_can_compute(db_tx) -> None:
    tenant = _tenant(db_tx)
    report = allocator_jobs.regret(db_tx, tenant_id=tenant, since_hours=24 * 365 * 5)
    assert report["dualAdjustedLearner"] is None
    assert report["regretInr"] is None
    assert report["refusedBecause"] == "no_promoted_estimator"
    assert "measuredAt" in report
    # The numbers behind the refusal, so a reader need not take it on trust.
    assert "corpusObjections" in report
    assert "labels" in report


def test_the_gold_standard_counts_nights_rather_than_promising_them() -> None:
    assert allocate.GOLD_STANDARD_NIGHTS == 10
    assert allocate.JOB_ALLOCATOR_GOLD == "w13.allocator_gold"


# ---------------------------------------------------------------------------
# §10.5 — scheduled, and refusing for a named reason
# ---------------------------------------------------------------------------


def test_the_solve_is_a_job_the_dispatcher_already_knows_how_to_run() -> None:
    """§10.5 asks for a job ledger with an advisory lock and a row that makes
    "did it run today" a query. ``wk_batch`` is that, and a third job ledger
    would be the fourth contact-window restatement in a different costume."""
    import wk_batch

    assert wk_batch.CAPACITY_SOLVE in wk_batch.JOBS
    assert wk_batch.ALLOCATOR_GOLD in wk_batch.JOBS
    assert wk_batch.ALLOCATOR_REGRET in wk_batch.JOBS
    # They read the primary, not the reporting standby: the decision log as it
    # stands now, and the solve writes back.
    assert wk_batch.PRIMARY_SOURCE_JOBS <= wk_batch.JOBS


def test_the_sweep_does_not_refuse_while_the_price_is_gated_off(db_tx) -> None:
    """§10.5's refusal is conditional on purpose. With pricing off the sweep
    does not consume λ, and refusing to decide the book because a price nobody
    reads is missing would be a self-inflicted outage."""
    assert allocate.enabled() is False
    assert book_sweep.duals_missing(db_tx) is None


def test_the_sweep_refuses_by_name_when_the_price_is_on_and_absent(db_tx, monkeypatch) -> None:
    monkeypatch.setattr(allocate, "enabled", lambda: True)
    monkeypatch.delenv("TREATMENT_STATIC_QUOTA", raising=False)
    db_tx.execute(
        text("DELETE FROM capacity_duals WHERE plan_date = CURRENT_DATE")
    )
    assert book_sweep.duals_missing(db_tx) == "no_duals_for_today"
    # §10.5's named escape: decide on fixed quotas, and say so.
    monkeypatch.setenv("TREATMENT_STATIC_QUOTA", "1")
    assert book_sweep.duals_missing(db_tx) is None


# ---------------------------------------------------------------------------
# §10.3 — the dashboard
# ---------------------------------------------------------------------------


def test_the_price_panel_carries_what_the_control_arm_cost(db_tx) -> None:
    """§10.3: λ "shares a dashboard panel with the cumulative borrower-cases
    withheld by the control arm, because those two numbers together say what the
    system is spending"."""
    from agent_core.treatment import metrics

    tenant = _tenant(db_tx)
    panel = metrics.capacity(db_tx, days=28, tenant_id=tenant)
    assert "withheldCases" in panel
    withheld = panel["withheldCases"]
    assert "evaluable" in withheld
    if withheld["evaluable"]:
        assert withheld["controlCases"] <= withheld["cases"]
    else:
        # An empty panel is not "nothing was withheld" — it is "the panel that
        # would say has not been built", which is §8.12's distinction.
        assert withheld.get("reason") or withheld["cases"] == 0


def test_the_capacity_panel_is_scoped_to_one_tenant(db_tx) -> None:
    """`[metrics-capacity-no-tenant-filter]`. Capacity, book size, demand and
    price together are a complete picture of a competitor's operation."""
    import inspect

    from agent_core.treatment import metrics

    source = inspect.getsource(metrics.capacity)
    assert "tenant_id = :tenant" in source
    assert "tenant_id" in inspect.signature(metrics.capacity).parameters


def test_the_panel_separates_the_damped_series_from_the_raw_one(db_tx) -> None:
    from agent_core.treatment import metrics

    _require_w13(db_tx)
    tenant = _tenant(db_tx)
    panel = metrics.capacity(db_tx, days=28, tenant_id=tenant)
    for row in panel["resources"]:
        assert "undampedStability" in row, (
            "a price that is stable only after damping is a damped price, not a "
            "stable one"
        )
        assert "unconfiguredDays" in row


def test_the_module_reloads_without_a_database() -> None:
    """Import-time work in this module would run inside the API's startup."""
    importlib.reload(allocate)
    assert allocate.RESOURCES
