"""W10's one reachable exit criterion: each discount appears exactly once.

§8.1 names one estimand, one primary endpoint and one arithmetic::

    EV = p_reach · tau_delivered · rupees_given_cure − cost − λ·usage − fatigue

and then says what keeps it that way:

    "A CI identity test asserts EV(tau_marginal, no reach term) ==
     EV(p_reach, tau_delivered) on a fixture and fails the build when they
     diverge. That test is the only thing that keeps this fix alive through six
     months of edits."

This is that test. The identity holds if and only if reach enters the
expected value exactly once — write it into the formula a second time, or fold
it into ``p_resolve`` while leaving the explicit multiply in place, and the two
sides part company. The failure it prevents was live in the pre-W0 tree, where
an already-marginal τ was multiplied by ``p(reach)`` and ``1 − p(self_cure)``
a second time before being compared to a ₹2.00 floor
`[tau-double-discounted-by-reach-and-timing]`: the engine went quiet on
borrowers a randomised arm says it helps, and the quiet looked intentional.

Both scorers go through :func:`scoring.expected_value`, so both are covered by
one implementation. That is itself the fix — ``EstimatorScorer`` used to carry
its own copy of the formula, and two copies of an arithmetic stay identical
only until one of them acquires a term.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_core.treatment import actions as A
from agent_core.treatment import models, scoring
from agent_core.treatment.config import Costs, Policy
from agent_core.treatment.features import AccountFeatures, Trigger
from agent_core.treatment.scoring import Candidate, EVScorer

TOLERANCE = 1e-9


def _costs(**over) -> Costs:
    base = dict(
        sms=0.18,
        whatsapp=0.42,
        voice_bot=7.50,
        human_call=45.0,
        field_visit=1150.0,
        legal_notice=2500.0,
        represent_mandate=0.50,
        emi_date_change=15.0,
        self_service_plan=8.0,
    )
    base.update(over)
    return Costs(**base)


def _policy() -> Policy:
    """The shipped defaults, spelled out. ``config.policy()`` would read
    ``engine_config``, and an arithmetic identity must not depend on a row."""
    return Policy(
        min_expected_value=2.0,
        recovery_fraction=0.35,
        urgency_halflife_hours=36.0,
        fatigue_cost=6.0,
        max_rung_advance=1,
        reserve_budget=True,
        reserve_margin=3.0,
        field_digital_exhaustion=4,
        planning_horizon_hours=72,
        max_attempts_per_case=5,
        retry_backoff_hours=12.0,
    )


def _features(**kw) -> AccountFeatures:
    base = dict(
        customer_id="c-identity",
        tenant_id="t1",
        dpd=22,
        # ``exposure`` is derived — the instalment, not the balance — so the
        # fixture sets what it is derived from.
        instalment_amount=18_000.0,
        bucket=A.B_0_30,
        ptp_keep_rate=0.55,
        connect_rate={"voice": 0.41, "whatsapp": 0.62, "sms": 0.3},
    )
    base.update(kw)
    return AccountFeatures(**base)


# ---------------------------------------------------------------------------
# The identity itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "p_reach,tau_delivered",
    [
        (0.30, 0.22),
        (0.95, 0.01),
        (0.01, 0.95),
        # p_reach = 1 is the non-contacting family: a mandate presentation, a
        # legal notice, a schedule change. "Marginal" and "delivered" are the
        # same quantity there, so the identity must hold trivially — and a
        # formula that applied reach twice would still pass at 1.0, which is
        # why the cases above carry the weight.
        (1.00, 0.35),
    ],
)
def test_marginal_and_delivered_tau_price_the_same_action(
    p_reach: float, tau_delivered: float
) -> None:
    """The identity, stated exactly as §8.1 states it."""
    rupees, decay, cost, fatigue = 9_000.0, 0.83, 7.5, 2.25
    tau_marginal = p_reach * tau_delivered

    delivered = scoring.expected_value(
        p_reach=p_reach,
        p_resolve=tau_delivered,
        rupees=rupees,
        decay=decay,
        cost=cost,
        fatigue=fatigue,
    )
    marginal = scoring.expected_value(
        p_reach=1.0,
        p_resolve=tau_marginal,
        rupees=rupees,
        decay=decay,
        cost=cost,
        fatigue=fatigue,
    )
    assert delivered == pytest.approx(marginal, abs=TOLERANCE)


def test_a_second_reach_multiply_breaks_the_identity() -> None:
    """The test's own claim to be worth having.

    An identity nothing can violate is a tautology on the page. This applies
    the discount twice — the exact shape of the defect — and asserts the two
    sides now differ, so a future edit that reintroduces it cannot also pass.
    """
    p_reach, tau = 0.30, 0.22
    rupees, decay = 9_000.0, 1.0

    double_discounted = p_reach * (p_reach * tau) * rupees * decay
    once = scoring.gross_value(
        p_reach=p_reach, p_resolve=tau, rupees=rupees, decay=decay
    )
    assert double_discounted != pytest.approx(once, abs=TOLERANCE)


# ---------------------------------------------------------------------------
# ... and through the two scorers, which is where it has to hold
# ---------------------------------------------------------------------------


def _score_one(action: str, *, features: AccountFeatures) -> scoring.ScoredAction:
    now = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)
    scorer = EVScorer()
    scored = scorer.score(
        features,
        Trigger(kind="dpd_tick", at=now - timedelta(hours=6)),
        [Candidate(action=action, at=now + timedelta(hours=2), timing_rationale="")],
        now=now,
        policy=_policy(),
        costs=_costs(),
    )
    return scored[0]


@pytest.mark.parametrize(
    "action",
    [a for a in A.ALL if a != A.WAIT],
)
def test_every_action_the_ev_scorer_prices_satisfies_the_identity(action: str) -> None:
    """Across the whole action space, not one convenient row.

    The non-contacting family matters most here: ``p_reach`` is 1.0 by
    construction for a mandate presentation or a legal notice, and a formula
    that had drifted would still agree on those — so they are included to prove
    the parametrisation covers them, while the contacting actions are what can
    actually fail.
    """
    scored = _score_one(action, features=_features())
    rebuilt = scoring.expected_value(
        p_reach=1.0,
        p_resolve=scored.p_reach * scored.p_resolve,
        rupees=scored.components["value_at_stake"],
        decay=scored.components["urgency_decay"],
        cost=scored.cost,
        fatigue=-scored.components["fatigue"],
    )
    assert scored.expected_value == pytest.approx(rebuilt, abs=TOLERANCE)


def test_the_estimator_scorer_prices_through_the_same_arithmetic(monkeypatch) -> None:
    """``EstimatorScorer`` substitutes terms, never the formula.

    It used to carry its own copy of ``gross = value * reach * resolve * decay``
    beside ``EVScorer``'s. Both were correct on the day they were written,
    which is the only day two copies of an arithmetic are ever both correct.
    """
    now = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)

    class _Fixed:
        """An artifact stub: whatever it is asked, it answers ``value``."""

        def __init__(self, value: float) -> None:
            self.value = value

        def predict(self, _vec) -> float:
            return self.value

    scorer = models.EstimatorScorer(
        EVScorer(), reach=_Fixed(0.44), timing=_Fixed(0.2), uplift=_Fixed(0.17)
    )
    scored = scorer.score(
        _features(),
        Trigger(kind="dpd_tick", at=now - timedelta(hours=6)),
        [Candidate(action=A.WHATSAPP, at=now + timedelta(hours=2), timing_rationale="")],
        now=now,
        policy=_policy(),
        costs=_costs(),
    )[0]

    assert scored.p_reach == pytest.approx(0.44, abs=TOLERANCE)
    assert scored.p_resolve == pytest.approx(0.17, abs=TOLERANCE)
    # The timing model reports P(already resolved); the decay is its complement.
    assert scored.components["urgency_decay"] == pytest.approx(0.8, abs=TOLERANCE)

    rebuilt = scoring.expected_value(
        p_reach=1.0,
        p_resolve=scored.p_reach * scored.p_resolve,
        rupees=scored.components["value_at_stake"],
        decay=scored.components["urgency_decay"],
        cost=scored.cost,
        fatigue=-scored.components["fatigue"],
    )
    assert scored.expected_value == pytest.approx(rebuilt, abs=TOLERANCE)


# ---------------------------------------------------------------------------
# The estimand, which is what makes the number readable a year later
# ---------------------------------------------------------------------------


def test_the_priors_are_recorded_as_a_response_model() -> None:
    """``RESOLVE_PRIOR`` is P(cure | landed). Saying so is the whole point.

    A response model ranks the borrower who would have paid anyway at the top,
    because they genuinely do have the highest absolute repayment probability.
    That is a legitimate thing to ship on day one and an illegitimate thing to
    compare against a τ without noticing.
    """
    scored = _score_one(A.WHATSAPP, features=_features())
    assert scored.estimand == scoring.ESTIMAND_RESPONSE_PRIOR
    assert scored.to_log()["estimand"] == scoring.ESTIMAND_RESPONSE_PRIOR


def test_an_uplift_artifact_changes_the_estimand_on_the_row() -> None:
    """§8.1's opening complaint, closed at the decision grain.

    Before this, ``expected_value`` meant P(cure | landed) on rows scored
    without an uplift artifact and τ on rows scored with one, under one column
    name, with nothing on the row to tell them apart. A corpus spanning a
    rollout could not be split by which quantity produced each row.
    """
    now = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)

    class _Fixed:
        def predict(self, _vec) -> float:
            return 0.17

    scored = models.EstimatorScorer(EVScorer(), uplift=_Fixed()).score(
        _features(),
        Trigger(kind="dpd_tick", at=now - timedelta(hours=6)),
        [Candidate(action=A.WHATSAPP, at=now, timing_rationale="")],
        now=now,
        policy=_policy(),
        costs=_costs(),
    )[0]
    assert scored.estimand == scoring.ESTIMAND_TAU_MODEL


def test_reach_and_timing_alone_leave_the_estimand_a_response() -> None:
    """Only the uplift artifact changes what ``p_resolve`` *means*.

    A learned reach model is still a reach model and a learned timing model is
    still a timing model; neither turns the resolve prior into a causal
    quantity. Marking those rows ``tau_model`` would be the same conflation
    with a fresher date on it.
    """
    now = datetime(2026, 9, 10, 6, 0, tzinfo=timezone.utc)

    class _Fixed:
        def predict(self, _vec) -> float:
            return 0.4

    scored = models.EstimatorScorer(
        EVScorer(), reach=_Fixed(), timing=_Fixed()
    ).score(
        _features(),
        Trigger(kind="dpd_tick", at=now - timedelta(hours=6)),
        [Candidate(action=A.WHATSAPP, at=now, timing_rationale="")],
        now=now,
        policy=_policy(),
        costs=_costs(),
    )[0]
    assert scored.estimand == scoring.ESTIMAND_RESPONSE_PRIOR


# ---------------------------------------------------------------------------
# rupees_given_cure — §8.1's third term, as a term
# ---------------------------------------------------------------------------


def test_a_mandate_is_priced_at_what_it_is_authorised_to_collect() -> None:
    """The ceiling belongs to the rupee term, and is applied exactly once.

    A mandate authorises an amount; presenting for more is refused by the rail.
    Pricing the full arrears would value a collection that cannot happen.
    """
    capped = _features(mandate_max_amount=6_000.0)
    uncapped = _features()
    policy = _policy()

    assert scoring.capped_exposure(A.REPRESENT_MANDATE, capped) == 6_000.0
    assert scoring.capped_exposure(A.REPRESENT_MANDATE, uncapped) == 18_000.0
    # ... and the ceiling is specific to the mandate. It must not leak into the
    # pricing of a contact action on the same borrower.
    assert scoring.capped_exposure(A.WHATSAPP, capped) == 18_000.0
    assert scoring.rupees_given_cure(
        A.REPRESENT_MANDATE, capped, policy=policy
    ) < scoring.rupees_given_cure(A.REPRESENT_MANDATE, uncapped, policy=policy)


def test_the_capacity_price_can_be_taken_back_out_of_the_expected_value() -> None:
    """The identity W13's allocator depends on, and the one that stops the
    surcharge compounding.

    ``scoring.score`` writes ``ev = gross − cost − fatigue`` where ``cost``
    already carries λ·usage, and ``solve_capacity`` reads that ``ev`` back as
    tomorrow's demand. Without a separately logged ``capacityPrice`` the value
    of an action falls by the surcharge every day the price holds
    ``[allocate-dual-price-double-counted-in-next-days-demand]`` — an
    oscillation with no economic cause, on a number a floor manager reads.

    The identity: pricing an action at λ and then adding the logged
    ``capacityPrice`` back gives the same number as pricing it at λ = 0.
    """
    from agent_core.treatment import allocate as alloc
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
    free = costs.for_action("human_call")
    assert costs.capacity_price("human_call") == 0.0, "dual pricing is gated off"

    # Six minutes of an agent priced at ₹2.50 a minute.
    original_enabled = alloc.enabled
    original_prices = alloc._todays_prices
    alloc.enabled = lambda: True
    alloc._todays_prices = lambda: {"agent_minutes": 2.50}
    try:
        priced = costs.for_action("human_call")
        surcharge = costs.capacity_price("human_call")
    finally:
        alloc.enabled = original_enabled
        alloc._todays_prices = original_prices

    assert surcharge == pytest.approx(15.0)
    assert priced == pytest.approx(free + surcharge)
    # And the identity, stated the way the allocator uses it: a scored action
    # plus its logged capacity price is the action valued at λ = 0.
    scored = scoring.ScoredAction(
        action="human_call",
        channel="voice",
        at=None,
        expected_value=100.0 - surcharge,
        p_reach=0.5,
        p_resolve=0.4,
        cost=priced,
        capacity_price=surcharge,
        explanation="",
    )
    assert scored.pre_dual_expected_value == pytest.approx(100.0)
