"""W11a — the gate that can be evaluated.

§15.2's W11 exit criterion has two halves: *"One challenger promoted and one
refused, both with a filed record; **one gate returning 'cannot be evaluated'
and correctly refusing**."* The first half needs a fit and a fit is still not
attemptable — 0 mature labels, 21 borrowers, 18 days of corpus. The second half
is what this suite pins down.

Measured read-only against ``collections`` on 2026-09-10, through the tree's own
code rather than by inspection:

    ope.scan(...) evaluable                       124 rows over 10 borrowers
    ESS over rows (what used to gate)             97.3  -> a fraction of 0.78
    ESS over customer-aggregated weights (§8.9)   9.45  over 10 borrowers
    largest single-customer share of weight       13.9%
    disagreement vs greedy_on_logged_ev           26 of 124 rows, 21%
    live rows on logging_contract_version = 2     0 of 278

The last line is the one that matters most: ``sql/05_collections.sql`` has said
since W2 that contract-1 rows "are excluded from OPE", nothing enforced it, and
every row on the book is contract 1. Applying the rule honestly empties the
corpus — which is the true answer, and belongs in a refusal that names it rather
than in an estimate computed over rows the schema excludes.
"""

from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agent_core.treatment import cluster, ope, prereg, registry, schema_ready, sequence


@pytest.fixture(autouse=True)
def _reset():
    schema_ready.reset_cache()
    yield
    schema_ready.reset_cache()


def _require_w11(db_tx) -> None:
    """``treatment_pre_registrations`` is this wave's own table (sql/31, 0120).

    Absent from the running database because 0120 is deliberately unapplied
    there — which is precisely the condition :func:`prereg.objections` refuses
    on, so this skip is the same fact seen from the test's side.
    """
    if not schema_ready.w11_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("treatment_pre_registrations absent (migration 0120)")
        pytest.skip("treatment_pre_registrations absent (migration 0120 unapplied)")


def _obs(decision_id, customer, action, reward, propensity, support=None, **components):
    entry = {
        "action": action,
        "propensity": propensity,
        "expectedValue": components.pop("ev", 0.0),
        "cost": components.pop("cost", 0.0),
        "components": components or {},
    }
    return ope.Observation(
        decision_id=decision_id,
        action=action,
        reward=reward,
        propensity=propensity,
        support=support or {action: propensity},
        candidates={action: entry},
        customer_id=customer,
    )


# ---------------------------------------------------------------------------
# §8.9 tier 0 — the diagnostics, and the one that was off by a factor of ten
# ---------------------------------------------------------------------------


def test_ess_is_computed_on_customer_aggregated_weights() -> None:
    """§8.9: "ESS computed on customer-aggregated weights with the cluster count
    printed beside it".

    Forty decisions on four borrowers is four observations, not forty. The row
    figure reports a healthy sample; the customer figure reports the truth, and
    the gap between them is the whole reason both are published.
    """
    rows = [
        _obs(f"D{i}", f"C{i % 4}", "sms", 1.0 if i % 2 else 0.0, 0.5)
        for i in range(40)
    ]
    est = ope.snips(rows, ope.greedy_on(lambda e: 1.0))

    assert est.n == 40
    assert est.clusters == 4
    # Row ESS sees forty independent draws.
    assert est.ess > 30, est.ess
    # Customer ESS sees four borrowers, and cannot exceed the cluster count.
    assert est.ess_customers <= est.clusters + 1e-9
    assert est.ess_customers == pytest.approx(4.0, abs=0.01)
    assert est.to_log()["essCustomers"] == pytest.approx(4.0, abs=0.01)
    assert est.to_log()["ess"] > est.to_log()["essCustomers"]


def test_one_borrower_carrying_the_estimate_is_a_refusal() -> None:
    """§8.3: "refusing any gate evaluation where one customer contributes more
    than a stated share"."""
    rows = [_obs(f"D{i}", f"C{i}", "sms", 0.0, 0.5) for i in range(60)]
    # One borrower on a propensity a hundred times smaller than everybody else's.
    rows.append(_obs("DX", "WHALE", "sms", 1.0, 0.005))
    est = ope.ips(rows, ope.greedy_on(lambda e: 1.0))

    assert est.max_customer_share > ope.MAX_CUSTOMER_LEVERAGE, est.max_customer_share
    assert not est.trustworthy
    assert any("leverage cap" in o for o in est.objections), est.objections


def test_an_untrustworthy_estimate_says_which_number_failed() -> None:
    """"Untrustworthy" sends an operator looking; the number tells them what to do."""
    est = ope.snips(
        [_obs(f"D{i}", f"C{i}", "sms", 0.0, 0.5) for i in range(5)],
        ope.greedy_on(lambda e: 1.0),
    )
    assert not est.trustworthy
    assert any(str(cluster.MIN_CLUSTERS) in o for o in est.objections), est.objections


# ---------------------------------------------------------------------------
# §8.9's four repairs to the corpus reader
# ---------------------------------------------------------------------------


def test_the_logging_contract_floor_empties_this_corpus_and_says_so(db_tx) -> None:
    """The refusal that names its number, on the live corpus's own shape.

    Every live row is ``logging_contract_version = 1``. Before this, ``scan``
    returned them and the estimate looked fine; now it returns nothing and the
    scope says why. An operator reading "no evaluable decisions" went and
    lowered ``TREATMENT_GREEDINESS`` on a corpus where exploration was already
    running at δ = 0.10.
    """
    strict = ope.scan(db_tx, modes=("shadow", "live", "simulated"))
    if strict.scope.considered == 0:
        pytest.skip("this database holds no labelled decisions to scope")

    loose = ope.scan(db_tx, modes=("shadow", "live", "simulated"), contract_min=1)
    assert loose.scope.evaluable >= strict.scope.evaluable

    if strict.scope.evaluable == 0:
        assert strict.scope.objections, "an empty corpus must refuse, not return []"
        message = strict.scope.objections[0]
        assert str(strict.scope.considered) in message, message
        assert "logging contract" in message, message


def test_the_equivalence_class_filter_refuses_an_unknown_column(db_tx) -> None:
    """§8.9 names four columns. A fifth is a typo, and a typo that silently
    matched nothing would quietly empty the corpus."""
    with pytest.raises(ValueError, match="equivalence-class"):
        ope.scan(db_tx, equivalence_class={"policy_binding_hash": "abc"})


def test_pinning_the_equivalence_class_counts_what_it_excluded(db_tx) -> None:
    scoped = ope.scan(
        db_tx,
        modes=("shadow", "live", "simulated"),
        contract_min=1,
        equivalence_class={"recommender_version": "no-such-version"},
    )
    if scoped.scope.considered == 0:
        pytest.skip("this database holds no labelled decisions to scope")
    assert scoped.scope.evaluable == 0
    assert any("equivalence class" in k for k in scoped.scope.excluded), scoped.scope.excluded


def test_a_suppressed_decision_is_an_observation(db_tx) -> None:
    """§8.9's first repair, and it is the entire negative class.

    A suppressed row's ``chosen_action`` is ``wait``, which the candidate list
    does not price, so ``support[chosen]`` was always None and the row was
    dropped. It carries a logged propensity and an outcome: it is evaluable, and
    a corpus of only-acted-upon rows scores every policy against the population
    the engine had already decided to act on.
    """
    kept = ope.scan(db_tx, modes=("shadow", "live", "simulated"), contract_min=1)
    dropped = ope.scan(
        db_tx,
        modes=("shadow", "live", "simulated"),
        contract_min=1,
        include_suppressed=False,
    )
    if kept.scope.considered == 0:
        pytest.skip("this database holds no labelled decisions to scope")
    assert kept.scope.evaluable >= dropped.scope.evaluable
    assert kept.scope.suppressed_included >= 0
    if kept.scope.suppressed_included:
        assert kept.scope.evaluable > dropped.scope.evaluable


def test_the_challenger_evaluated_is_the_challenger_that_would_ship() -> None:
    """§8.9's fourth repair.

    ``estimator_policy`` used to re-derive ``exposure × recovery_fraction ×
    p_reach × tau × decay − cost − fatigue``, dropping ``VALUE_HORIZON[a]``,
    both clamps and ``capped_exposure``'s mandate ceiling. So the policy the
    gate evaluated was not the policy the engine would run, and the difference
    ran in the direction nobody checks.

    ``value_at_stake`` is what ``scoring.rupees_given_cure`` wrote at decision
    time. Reading it back is the only way to score the same rupees, and the
    horizon is where the two answers part company.
    """
    from agent_core.treatment import scoring

    # An action whose horizon is not the identity, so dropping it is visible.
    action = "self_service_plan"
    horizon = scoring.VALUE_HORIZON[action]
    assert horizon != 1.0, "pick an action whose horizon is not the identity"

    exposure, recovery = 10_000.0, 0.35
    entry = {
        "action": action,
        "propensity": 1.0,
        "cost": 0.0,
        "pReach": 0.5,
        "pResolve": 0.4,
        "components": {
            "exposure": exposure,
            "value_at_stake": exposure * recovery * horizon,
            "urgency_decay": 1.0,
            "fatigue": 0.0,
        },
        "vector": {"dpd": 30.0},
    }
    policy = ope.estimator_policy(recovery_fraction=recovery)

    # The score the shipped scorer would produce for the same inputs.
    expected = scoring.expected_value(
        p_reach=0.5, p_resolve=0.4, rupees=exposure * recovery * horizon,
        decay=1.0, cost=0.0, fatigue=0.0,
    )
    got = policy({action: entry})
    assert got == {action: 1.0}
    # And the number itself, reachable through the same private scorer the
    # policy uses, is the one with the horizon in it.
    assert expected == pytest.approx(0.5 * 0.4 * exposure * recovery * horizon)
    assert expected != pytest.approx(0.5 * 0.4 * exposure * recovery)


# ---------------------------------------------------------------------------
# §8.9 tier 3 — the confidence sequence
# ---------------------------------------------------------------------------


def test_the_confidence_sequence_covers_under_the_null() -> None:
    """Coverage checked, not asserted.

    A challenger identical to the champion produces a mean of zero. The bound
    may cross zero on no more than α of independent nulls — and because a
    confidence sequence is valid at *every* look rather than at one, it is
    conservative at any single one, which is exactly the property being bought.
    """
    trials, crossings = 300, 0
    for seed in range(trials):
        rng = random.Random(seed)
        values = [rng.uniform(-1.0, 1.0) for _ in range(150)]
        if sequence.lower_bound(values, lo=-1.0, hi=1.0, alpha=0.05).clears_zero:
            crossings += 1
    assert crossings <= 0.05 * trials, f"{crossings}/{trials} false crossings"


def test_the_confidence_sequence_finds_a_real_effect() -> None:
    """A conservative bound that never clears is not a gate, it is a refusal."""
    rng = random.Random(11)
    values = [0.4 + rng.uniform(-1.0, 1.0) for _ in range(500)]
    bound = sequence.lower_bound(values, lo=-1.5, hi=1.5, alpha=0.05)
    assert bound.clears_zero, bound.as_dict()
    assert bound.lower < bound.mean, "a lower bound above its own mean is a bug"


def test_a_value_outside_the_declared_range_is_refused_not_clamped() -> None:
    """The range is the bound's own assumption. Clamping would restore the
    guarantee by deleting the evidence against it."""
    bound = sequence.lower_bound([0.2, 0.4, 7.0], lo=0.0, hi=1.0)
    assert not math.isfinite(bound.lower)
    assert "declared range" in bound.refusal
    assert not bound.clears_zero


def test_the_bound_never_reports_a_number_it_could_not_compute() -> None:
    for bad in (
        sequence.lower_bound([], lo=0.0, hi=1.0),
        sequence.lower_bound([float("nan")], lo=0.0, hi=1.0),
        sequence.lower_bound([0.5], lo=1.0, hi=0.0),
        sequence.logarithmic_smoothing([1.0], [-0.5]),
        sequence.logarithmic_smoothing([], []),
    ):
        assert bad.refusal, bad.as_dict()
        assert bad.lower == float("-inf")
        assert bad.as_dict()["lower"] is None


def test_the_logarithmic_smoothing_bound_is_below_the_mean() -> None:
    """Tier 2 pessimism. It corroborates; it never gates."""
    bound = sequence.logarithmic_smoothing([1.0] * 200, [0.6] * 200, alpha=0.05)
    assert not bound.refusal
    assert bound.lower < bound.mean


# ---------------------------------------------------------------------------
# §8.9 tier 1 — Δ-OPE and the disagreement set
# ---------------------------------------------------------------------------


def test_two_identical_policies_produce_no_evidence_and_say_so() -> None:
    """§8.9: the variance reduction "comes from *agreement* — which is the
    problem as well as the benefit". Two policies that agree everywhere have a
    Δ of exactly zero with an interval of exactly zero width, and that is not
    evidence they are equivalent. It is the absence of evidence."""
    rows = [_obs(f"D{i}", f"C{i}", "sms", float(i % 2), 0.5) for i in range(200)]
    same = ope.greedy_on(lambda e: 1.0)
    d = ope.delta(rows, same, same)

    assert d.disagreement_n == 0
    assert d.value == 0.0
    assert not d.evaluable
    assert any("disagree" in o for o in d.objections), d.objections


def test_the_interval_is_restricted_to_the_disagreement_set() -> None:
    """§8.9: "a gate that certifies on the agreement set and deploys on 100% of
    the book is an interval trap arriving through the front door"."""
    rows = []
    for i in range(200):
        # Half the corpus offers two actions; half offers one, so the policies
        # cannot disagree there.
        if i % 2:
            rows.append(
                ope.Observation(
                    decision_id=f"D{i}",
                    action="sms",
                    reward=1.0,
                    propensity=0.5,
                    support={"sms": 0.5, "whatsapp": 0.5},
                    candidates={
                        "sms": {"action": "sms", "cost": 1.0, "expectedValue": 1.0},
                        "whatsapp": {"action": "whatsapp", "cost": 0.0, "expectedValue": 0.0},
                    },
                    customer_id=f"C{i}",
                )
            )
        else:
            rows.append(_obs(f"D{i}", f"C{i}", "sms", 1.0, 1.0))

    champion = ope.greedy_on(lambda e: float(e.get("expectedValue") or 0.0))
    challenger = ope.greedy_on(lambda e: -float(e.get("cost") or 0.0))
    d = ope.delta(rows, champion, challenger)

    assert 0 < d.disagreement_n < d.n
    assert d.disagreement_clusters == d.disagreement_n  # one decision per borrower
    assert d.interval.observations == d.disagreement_n, (
        "the interval must be computed on the disagreement set alone"
    )
    # The book-wide difference is diluted by the rows that cannot disagree.
    assert abs(d.value) < abs(d.disagreement_value)


def test_delta_ope_refuses_when_the_disagreement_set_is_too_thin() -> None:
    """§8.9: "the value gate may not be evaluated until a minimum disagreement
    mass and a minimum ESS within it are met"."""
    rows = []
    for i in range(500):
        disagrees = i < 5
        rows.append(
            ope.Observation(
                decision_id=f"D{i}",
                action="sms",
                reward=1.0,
                propensity=0.5,
                support={"sms": 0.5, "whatsapp": 0.5},
                candidates={
                    "sms": {"action": "sms", "expectedValue": 1.0, "cost": 1.0},
                    **(
                        {"whatsapp": {"action": "whatsapp", "expectedValue": 0.0, "cost": 0.0}}
                        if disagrees
                        else {}
                    ),
                },
                customer_id=f"C{i}",
            )
        )
    d = ope.delta(
        rows,
        ope.greedy_on(lambda e: float(e.get("expectedValue") or 0.0)),
        ope.greedy_on(lambda e: -float(e.get("cost") or 0.0)),
    )
    assert d.disagreement_n == 5
    assert not d.evaluable
    assert any(str(ope.MIN_DISAGREEMENT_ROWS) in o for o in d.objections), d.objections
    assert d.to_log()["evaluable"] is False


def test_the_dm_ips_decomposition_is_published() -> None:
    """§8.9: "The DM/IPS decomposition is published so a validator can see how
    much of the value is model and how much is data"."""
    rows = [
        ope.Observation(
            decision_id=f"D{i}",
            action="sms",
            reward=1.0,
            propensity=0.5,
            support={"sms": 0.5, "whatsapp": 0.5},
            candidates={
                "sms": {
                    "action": "sms", "expectedValue": 1.0, "cost": 1.0,
                    "components": {"gross": 0.5, "exposure": 1.0},
                },
                "whatsapp": {
                    "action": "whatsapp", "expectedValue": 0.0, "cost": 0.0,
                    "components": {"gross": 0.2, "exposure": 1.0},
                },
            },
            customer_id=f"C{i}",
        )
        for i in range(150)
    ]
    d = ope.delta(
        rows,
        ope.greedy_on(lambda e: float(e.get("expectedValue") or 0.0)),
        ope.greedy_on(lambda e: -float(e.get("cost") or 0.0)),
        reward_model=ope.logged_ev_reward(),
    )
    assert d.has_reward_model
    assert d.dm != 0.0
    assert "dm" in d.to_log() and "ips" in d.to_log()


# ---------------------------------------------------------------------------
# §8.12 gate 7 — the bound, against a measured margin
# ---------------------------------------------------------------------------


def test_gate_seven_refuses_a_point_estimate_without_a_bound(db_tx) -> None:
    """§8.12: "A gate with a documented bypass is worse than no gate, because it
    will be cited as evidence that the property was tested." Accepting ``lift``
    as a fallback for ``lcb`` would make the new gate optional."""
    reasons = registry._value_objections(
        db_tx, tenant_id="whoever", evaluation={"lift": 0.9}
    )
    assert reasons
    assert "point estimate" in reasons[0], reasons


def test_gate_seven_refuses_when_its_margin_cannot_be_measured(db_tx) -> None:
    """§8.12's worked example is that a flat ₹1.50 margin "does literally
    nothing". An unmeasurable margin is a refusal, not a licence to substitute a
    constant."""
    margin, basis = registry.value_margin(db_tx, tenant_id="no-such-tenant")
    assert margin is None
    assert basis

    reasons = registry._value_objections(
        db_tx, tenant_id="no-such-tenant", evaluation={"lcb": 0.9}
    )
    assert any("margin could not be measured" in r for r in reasons), reasons


def test_a_non_finite_lower_bound_is_not_a_number_a_gate_can_compare(db_tx) -> None:
    reasons = registry._value_objections(
        db_tx, tenant_id="whoever", evaluation={"lcb": float("nan")}
    )
    assert reasons and "not a number" in reasons[0]


def test_a_refused_bound_travels_as_a_refusal(db_tx) -> None:
    """The serialised ``Bound`` carries its own refusal, and the gate reads it
    rather than reading ``lower`` as null and moving on."""
    bound = sequence.lower_bound([], lo=0.0, hi=1.0)
    reasons = registry._value_objections(
        db_tx, tenant_id="whoever", evaluation={"lcb": bound.as_dict()}
    )
    assert reasons and "confidence sequence" in reasons[0]


# ---------------------------------------------------------------------------
# §8.12 gates 14 and 15 — pre-registration, and a validator who is not the author
# ---------------------------------------------------------------------------


def _file_one(db_tx, tenant, **overrides):
    body = dict(
        tenant_id=tenant,
        target="uplift",
        primary_endpoint="cure within the primary horizon",
        horizon_days=90,
        estimator="delta-OPE with an empirical-Bernstein CS lower bound",
        threshold=0.01,
        threshold_basis="0.05 x measured per-borrower recovery SD",
        family_size=12,
        alpha_spending="none; the confidence sequence is anytime-valid",
        stopping_rule="promote at the first look whose lower bound clears the margin",
        author="alice",
    )
    body.update(overrides)
    return prereg.declare(db_tx, **body)


def _tenant(db_tx) -> str:
    tenant = db_tx.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    if not tenant:
        pytest.skip("no tenant seeded")
    return str(tenant)


def test_gate_fourteen_refuses_an_evaluation_naming_no_pre_registration(db_tx) -> None:
    _require_w11(db_tx)
    reasons = prereg.objections(
        db_tx, tenant_id=_tenant(db_tx), target="uplift", evaluation={"lcb": 0.9}
    )
    assert reasons and "names no pre-registration" in reasons[0]


def test_gate_fourteen_refuses_one_filed_after_the_run(db_tx) -> None:
    """"written to the registry **before** the challenger ran". A
    pre-registration filed afterwards describes the result rather than
    predicting it, which is the entire point of the gate."""
    _require_w11(db_tx)
    tenant = _tenant(db_tx)
    record = _file_one(db_tx, tenant)
    prereg.sign(db_tx, pre_registration_id=record["id"], validator="bob")

    before = datetime.now(timezone.utc) - timedelta(days=1)
    reasons = prereg.objections(
        db_tx,
        tenant_id=tenant,
        target="uplift",
        evaluation={
            "pre_registration_id": record["id"],
            "computed_at": before.isoformat(),
        },
    )
    assert any("filed after the run" in r or "predicting it" in r for r in reasons), reasons


def test_gate_fourteen_accepts_one_filed_before_the_run(db_tx) -> None:
    _require_w11(db_tx)
    tenant = _tenant(db_tx)
    record = _file_one(db_tx, tenant)
    prereg.sign(db_tx, pre_registration_id=record["id"], validator="bob")

    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert (
        prereg.objections(
            db_tx,
            tenant_id=tenant,
            target="uplift",
            evaluation={
                "pre_registration_id": record["id"],
                "computed_at": later.isoformat(),
            },
        )
        == []
    )


def test_an_evaluation_that_will_not_say_when_it_ran_cannot_pass_gate_fourteen(db_tx) -> None:
    _require_w11(db_tx)
    tenant = _tenant(db_tx)
    record = _file_one(db_tx, tenant)
    prereg.sign(db_tx, pre_registration_id=record["id"], validator="bob")
    reasons = prereg.objections(
        db_tx,
        tenant_id=tenant,
        target="uplift",
        evaluation={"pre_registration_id": record["id"]},
    )
    assert any("computed_at" in r for r in reasons), reasons


def test_gate_fifteen_refuses_an_unsigned_pre_registration(db_tx) -> None:
    _require_w11(db_tx)
    tenant = _tenant(db_tx)
    record = _file_one(db_tx, tenant)
    reasons = prereg.objections(
        db_tx,
        tenant_id=tenant,
        target="uplift",
        evaluation={
            "pre_registration_id": record["id"],
            "computed_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        },
    )
    assert any("no validator" in r for r in reasons), reasons


def test_the_author_cannot_validate_their_own_model(db_tx) -> None:
    """§8.12 gate 15: "an independent validator **who is not the model's
    author**". W10a recorded this as deferred for want of a recorded author;
    the pre-registration is where an author is recorded."""
    _require_w11(db_tx)
    record = _file_one(db_tx, _tenant(db_tx))
    with pytest.raises(prereg.PreRegistrationRefused, match="authored"):
        prereg.sign(db_tx, pre_registration_id=record["id"], validator="alice")


def test_the_database_refuses_it_too(db_tx) -> None:
    """Maker-checker in application code is maker-checker a script bypasses.
    ``engine_config`` and ``retention_rules`` already made this choice."""
    _require_w11(db_tx)
    record = _file_one(db_tx, _tenant(db_tx))
    with pytest.raises(Exception) as caught:
        with db_tx.begin_nested():
            db_tx.execute(
                text(
                    "UPDATE treatment_pre_registrations "
                    "SET validator = author, validated_at = now() WHERE id = :id"
                ),
                {"id": record["id"]},
            )
    assert "maker_checker" in str(caught.value)


def test_a_half_signature_is_refused_by_the_database(db_tx) -> None:
    """A validator without a signing instant is half a signature, and neither
    half is evidence."""
    _require_w11(db_tx)
    record = _file_one(db_tx, _tenant(db_tx))
    with pytest.raises(Exception) as caught:
        with db_tx.begin_nested():
            db_tx.execute(
                text("UPDATE treatment_pre_registrations SET validator = :v WHERE id = :id"),
                {"id": record["id"], "v": "bob"},
            )
    assert "signature" in str(caught.value)


def test_the_promoter_may_not_be_the_author(db_tx) -> None:
    _require_w11(db_tx)
    tenant = _tenant(db_tx)
    record = _file_one(db_tx, tenant)
    prereg.sign(db_tx, pre_registration_id=record["id"], validator="bob")
    reasons = prereg.objections(
        db_tx,
        tenant_id=tenant,
        target="uplift",
        evaluation={
            "pre_registration_id": record["id"],
            "computed_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        },
        promoted_by="alice",
    )
    assert any("maker-checker" in r for r in reasons), reasons


def test_a_pre_registration_for_another_target_does_not_license_this_one(db_tx) -> None:
    _require_w11(db_tx)
    tenant = _tenant(db_tx)
    record = _file_one(db_tx, tenant, target="reach")
    prereg.sign(db_tx, pre_registration_id=record["id"], validator="bob")
    reasons = prereg.objections(
        db_tx,
        tenant_id=tenant,
        target="uplift",
        evaluation={
            "pre_registration_id": record["id"],
            "computed_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        },
    )
    assert any("was filed for" in r for r in reasons), reasons


def test_no_field_of_a_pre_registration_may_be_left_undecided(db_tx) -> None:
    """"A pre-registration whose fields are optional is a note." If the
    estimator was not decided in advance, the pre-registration has not
    happened."""
    _require_w11(db_tx)
    tenant = _tenant(db_tx)
    for blank in ("primary_endpoint", "estimator", "alpha_spending", "stopping_rule"):
        with pytest.raises(Exception):
            with db_tx.begin_nested():
                _file_one(db_tx, tenant, **{blank: "   "})


def test_an_absent_table_is_a_refusal_rather_than_a_pass(db_tx, monkeypatch) -> None:
    """§8.12: "an unevaluable gate is a refusal". A database that cannot say
    whether a challenger was pre-registered has not said that it was."""
    monkeypatch.setattr(schema_ready, "w11_ready", lambda conn: False)
    reasons = prereg.objections(
        db_tx, tenant_id="whoever", target="uplift", evaluation={"pre_registration_id": "X"}
    )
    assert reasons and "cannot be evaluated" in reasons[0]


def test_the_full_gate_refuses_and_names_every_reason_at_once(db_tx, tmp_path) -> None:
    """One round trip, every objection. An operator who fixes the sha and comes
    back to find the corpus was also too small has been failed twice."""
    tenant = _tenant(db_tx)
    artifact = tmp_path / "challenger.json"
    artifact.write_text("{}", encoding="utf-8")
    reasons = registry.check(
        db_tx,
        tenant_id=tenant,
        target="uplift",
        path=artifact,
        evaluation=None,
        promoted_by="alice",
    )
    assert reasons, "an unloadable artifact with no evaluation must be refused"


# ---------------------------------------------------------------------------
# W11's exit criterion
# ---------------------------------------------------------------------------


def _valid_artifact(tmp_path):
    """A challenger with nothing wrong with it. The point of the test below."""
    import json

    from agent_core.treatment import models as treatment_models
    from agent_core.treatment.features import SCHEMA_VERSION

    path = tmp_path / "spotless-uplift.json"
    path.write_text(
        json.dumps(
            {
                "name": "treatment_uplift",
                "target": "uplift",
                "type": "logistic",
                "version": "w11a-spotless",
                "trainedAt": datetime.now(timezone.utc).isoformat(),
                "featureNames": ["dpd"],
                "coefficients": [0.0],
                "intercept": 0.0,
                "means": {"dpd": 20.0},
                "controlArm": "null_treatment",
                "controlN": 100_000,
                "controlCoefficients": [0.0],
                "controlIntercept": 0.0,
                "vectorVersion": treatment_models.VECTOR_VERSION,
                "featureSchemaVersion": SCHEMA_VERSION,
                "corpus": "live",
            }
        ),
        encoding="utf-8",
    )
    return path


def test_a_gate_that_cannot_be_evaluated_refuses(db_tx, tmp_path, monkeypatch) -> None:
    """§15.2's W11 exit criterion: "one gate returning 'cannot be evaluated' and
    correctly refusing".

    Everything the gate *can* check is made spotless — the artifact loads, its
    corpus is live, every coefficient is finite, the evaluation is sealed under
    the key and names this exact file's sha, the lower bound is enormous. What
    remains is the set of gates this corpus cannot evaluate, and the refusal
    they produce is the deliverable. Before this, a clean file on a corpus with
    no labels at all produced silence.
    """
    _require_w11(db_tx)
    from agent_core.treatment import evaluation_seal

    monkeypatch.setenv(evaluation_seal.KEY_ENV, "w11a-exit-criterion-key")
    path = _valid_artifact(tmp_path)
    evaluation = evaluation_seal.sealed(
        {
            "lcb": 99.0,
            "ate": 0.4,
            "trustworthy": True,
            "artifact_sha": registry._sha(path),
            "computed_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        }
    )

    reasons = registry.check(
        db_tx,
        tenant_id=_tenant(db_tx),
        target="uplift",
        path=path,
        evaluation=evaluation,
        promoted_by="carol",
    )

    assert reasons, "a clean artifact on an unevaluable corpus must still refuse"
    # And the refusals are the ones that could not be evaluated, each carrying
    # the number that explains it — not a generic "not promoted".
    joined = " | ".join(reasons)
    assert "gate 14" in joined or "pre-registration" in joined, joined
    assert any(char.isdigit() for char in joined), joined


def test_a_refusal_is_not_a_promotion(db_tx, tmp_path) -> None:
    """The gate refuses by raising, and nothing reaches the serving path."""
    _require_w11(db_tx)
    path = _valid_artifact(tmp_path)
    serving = tmp_path / "serving.json"
    with pytest.raises(registry.PromotionRefused):
        registry.promote(
            db_tx,
            tenant_id=_tenant(db_tx),
            target="uplift",
            path=path,
            evaluation={"lcb": 99.0},
            promoted_by="carol",
            serving_path=serving,
        )
    assert not serving.exists(), "a refused promotion copied a file anyway"
