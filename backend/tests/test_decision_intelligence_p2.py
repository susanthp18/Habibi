"""Off-policy evaluation, book allocation, and the NBA card that stopped guessing.

The three things the design note calls for after the corpus and the estimators
exist, and the ones with the most room to be confidently wrong:

* **OPE** produces a number for a policy nobody ran. Its diagnostics are not
  decoration — an off-policy estimate without its effective sample size and its
  unsupported count is worse than no estimate, because it is a number.
* **The optimiser** amplifies estimator error rather than correcting it, so
  every test here is about it refusing to act, throttling correctly, or saying
  it did not converge.
* **The NBA card** carried a second copy of the contact ladder. The tests are
  that the copy is gone and that the engine's judgement is not silently
  reinterpreted on the way to the screen.
"""

from __future__ import annotations

from datetime import date

import pytest

from agent_core.treatment import allocate, ope


def _obs(action: str, reward: float, propensity: float, support=None, evs=None):
    support = support or {action: propensity}
    candidates = {
        a: {"action": a, "expectedValue": v, "propensity": support.get(a)}
        for a, v in (evs or {action: 10.0}).items()
    }
    return ope.Observation(
        decision_id=f"TD-{action}-{reward}",
        action=action,
        reward=reward,
        propensity=propensity,
        support=support,
        candidates=candidates,
    )


# ---------------------------------------------------------------------------
# Off-policy evaluation
# ---------------------------------------------------------------------------


def test_a_policy_identical_to_the_log_recovers_the_logged_average() -> None:
    """The arithmetic sanity check. If this drifts, nothing downstream means
    anything: an estimator that cannot reproduce the observed average when the
    candidate policy *is* the logging policy is not estimating anything."""
    obs = [
        _obs("whatsapp", 1.0, 0.5, evs={"whatsapp": 10.0, "sms": 1.0}),
        _obs("whatsapp", 0.0, 0.5, evs={"whatsapp": 10.0, "sms": 1.0}),
        _obs("whatsapp", 1.0, 0.5, evs={"whatsapp": 10.0, "sms": 1.0}),
    ]
    # π_new puts all mass on whatsapp; π_log gave it 0.5 — so each weight is 2
    # and IPS returns twice the logged mean, which is correct and is exactly
    # why SNIPS exists.
    est = ope.snips(obs, ope.greedy_on_logged_ev)
    assert est.value == pytest.approx(2 / 3)
    assert est.baseline == pytest.approx(2 / 3)


def test_ips_is_unbounded_and_snips_is_not() -> None:
    """Plain IPS will cheerfully report a cure rate above one.

    Unbiased in expectation and useless in the hand, which is why both are
    reported and why the gap between them is itself a diagnostic: when they
    disagree, the weights are badly behaved.
    """
    obs = [_obs("whatsapp", 1.0, 0.1, evs={"whatsapp": 10.0}) for _ in range(5)]
    assert ope.ips(obs, ope.greedy_on_logged_ev).value > 1.0
    assert ope.snips(obs, ope.greedy_on_logged_ev).value <= 1.0


def test_a_dominant_row_shows_up_as_a_collapsed_sample_size() -> None:
    """Ten thousand rows with an ESS of forty is an estimate computed from forty
    rows wearing ten thousand rows' confidence interval."""
    obs = [_obs("whatsapp", 1.0, 0.9, evs={"whatsapp": 10.0}) for _ in range(50)]
    obs.append(_obs("whatsapp", 1.0, 0.001, evs={"whatsapp": 10.0}))
    est = ope.snips(obs, ope.greedy_on_logged_ev)
    assert est.ess < est.n
    assert est.clipped >= 1, "the extreme weight was not capped"


def test_a_policy_that_wants_untried_actions_is_flagged_not_scored() -> None:
    """Common support, as a test.

    IPS is only valid where the logging policy could have taken the action the
    candidate wants. A deterministic log has support on exactly one action per
    decision, so every disagreement is unsupported — those rows simply
    contribute nothing, and without the count the policy looks evaluated when it
    was only evaluated where it happened to agree.
    """
    obs = [
        _obs(
            "whatsapp",
            1.0,
            1.0,
            support={"whatsapp": 1.0},  # deterministic: nothing else was possible
            evs={"whatsapp": 5.0, "human_call": 90.0},
        )
        for _ in range(30)
    ]
    est = ope.snips(obs, ope.greedy_on_logged_ev)  # would pick human_call
    assert est.unsupported == 30
    assert not est.trustworthy


def test_an_estimate_from_nothing_is_not_trustworthy() -> None:
    assert not ope.ips([], ope.greedy_on_logged_ev).trustworthy


def test_doubly_robust_carries_the_estimate_where_weights_cannot() -> None:
    """The direct-method term is why DR is the one to quote once a reward model
    exists: a deterministic stretch of the log contributes a modelled value
    rather than contributing nothing at all."""
    obs = [
        ope.Observation(
            decision_id="TD-1",
            action="whatsapp",
            reward=1.0,
            propensity=1.0,
            support={"whatsapp": 1.0},
            candidates={
                "whatsapp": {
                    "action": "whatsapp",
                    "expectedValue": 5.0,
                    "components": {"gross": 4.0, "exposure": 10.0},
                },
                "human_call": {
                    "action": "human_call",
                    "expectedValue": 90.0,
                    "components": {"gross": 9.0, "exposure": 10.0},
                },
            },
        )
    ]
    est = ope.doubly_robust(obs, ope.greedy_on_logged_ev, ope.logged_ev_reward())
    # IPS alone would contribute zero for this row; DR contributes the reward
    # model's view of human_call plus a zero-weight correction.
    assert est.value > 0


def test_the_treatment_effect_needs_no_importance_weights() -> None:
    """A difference of means, because the arm assignment *is* the randomisation.

    Reaching for an importance-weighted estimator here would add variance to a
    question already answered by design.
    """
    effect = ope.TreatmentEffect(
        treated_n=1000, control_n=400, treated_rate=0.55, control_rate=0.34
    )
    assert effect.ate == pytest.approx(0.21)
    assert effect.significant

    noisy = ope.TreatmentEffect(
        treated_n=20, control_n=8, treated_rate=0.55, control_rate=0.50
    )
    assert not noisy.significant, "a five-point gap on 28 rows is not a finding"


def test_a_ranking_evaluation_ties_deterministically() -> None:
    """Two runs of the same evaluation must not disagree, or a challenger's
    lift depends on dict ordering."""
    candidates = {
        "sms": {"action": "sms", "expectedValue": 10.0},
        "whatsapp": {"action": "whatsapp", "expectedValue": 10.0},
    }
    picks = {tuple(ope.greedy_on_logged_ev(candidates)) for _ in range(20)}
    assert len(picks) == 1


# ---------------------------------------------------------------------------
# Book allocation
# ---------------------------------------------------------------------------


def _book(n: int = 200):
    import random

    rng = random.Random(11)
    return [
        allocate.Demand(
            f"A{i}",
            {
                "whatsapp": rng.uniform(2, 80),
                "voice_bot": rng.uniform(5, 130),
                "human_call": rng.uniform(10, 380),
                "field_visit": rng.uniform(-150, 850),
                "represent_mandate": rng.uniform(0, 450),
            },
        )
        for i in range(n)
    ]


def test_nothing_is_priced_when_nothing_is_scarce() -> None:
    """A resource nobody configured must not throttle the book. Unmeasured and
    unlimited produce the same answer, and it is the right one."""
    solved = allocate.solve(_book(), {}, plan_date=date(2026, 8, 21))
    assert solved.binding() == []
    assert all(p == 0.0 for p in solved.prices.values())
    assert solved.converged


def test_scarcity_throttles_the_ladder_without_a_written_threshold() -> None:
    """The design note's central claim about Layer 3.

    Nobody writes down "stop making field visits below ₹900". The price of a
    scarce resource rises until demand meets capacity, the expensive actions
    fall below the value floor on their own, and the cheap ones absorb the
    displaced demand.
    """
    book = _book()
    loose = allocate.solve(book, {}, floor=2.0)
    tight = allocate.solve(book, {"agent_minutes": 400}, floor=2.0)

    assert "agent_minutes" in tight.binding()
    assert tight.demand["agent_minutes"] <= 400 * (1 + allocate.TOLERANCE)
    # The expensive human work collapses...
    assert tight.mix.get("field_visit", 0) < loose.mix.get("field_visit", 0)
    # ...and the action that consumes none of the scarce resource takes it up.
    assert tight.mix.get("represent_mandate", 0) > loose.mix.get("represent_mandate", 0)


def test_a_resource_priced_into_balance_does_not_get_un_priced() -> None:
    """The oscillation this solver had, pinned.

    "Is this resource under capacity?" asked at its *own* current price is
    circular: it is under capacity precisely because it is being charged for.
    Answering yes zeroed the price, demand flooded back, and with two
    interacting resources — pricing field slots pushes work onto agents, which
    un-prices agents, which pulls work back onto field slots — the solve
    terminated with one of them silently unpriced and oversubscribed.
    """
    book = _book()
    solved = allocate.solve(book, {"agent_minutes": 400, "field_slots": 15}, floor=2.0)
    assert solved.converged
    for resource, limit in (("agent_minutes", 400), ("field_slots", 15)):
        assert solved.demand[resource] <= limit * (1 + allocate.TOLERANCE), resource


def test_capacity_that_cannot_be_met_says_so(caplog) -> None:
    """A resource still oversubscribed at the price ceiling is undersized rather
    than merely scarce, and reporting that as a converged solve would hand a
    floor manager prices computed from a plan that cannot happen."""
    book = [
        allocate.Demand(f"A{i}", {"field_visit": 5_000_000.0}) for i in range(50)
    ]
    solved = allocate.solve(book, {"field_slots": 1}, floor=2.0)
    assert not solved.converged


def test_the_solve_is_deterministic() -> None:
    """Two solves of one book must agree, or the dual prices wander and nobody
    can tell scarcity from numerical noise."""
    book = _book()
    a = allocate.solve(book, {"agent_minutes": 500}, floor=2.0)
    b = allocate.solve(book, {"agent_minutes": 500}, floor=2.0)
    assert a.prices == b.prices
    assert a.mix == b.mix


def test_dual_prices_do_not_reach_the_cost_term_until_switched_on(monkeypatch) -> None:
    """The gate the design note is emphatic about: an optimiser over estimates
    that have not proved themselves makes the same mistake across the whole book
    at once."""
    monkeypatch.delenv("TREATMENT_DUAL_PRICING", raising=False)
    allocate.reset_cache()
    assert allocate.price_for_action("human_call") == 0.0
    assert allocate.enabled() is False


def test_a_missing_price_table_costs_accuracy_not_availability(monkeypatch) -> None:
    """``price_for_action`` sits inside the scorer, which sits on the path that
    decides whether a borrower is contacted at all."""
    monkeypatch.setenv("TREATMENT_DUAL_PRICING", "1")
    allocate.reset_cache()

    class Exploding:
        def connect(self):
            raise RuntimeError("database is on fire")

    import db as dbmod

    monkeypatch.setattr(dbmod, "engine", Exploding())
    assert allocate.price_for_action("human_call") == 0.0
    allocate.reset_cache()


def test_only_actions_that_consume_something_are_surcharged() -> None:
    """A WhatsApp message does not use an agent-minute, and a mandate
    presentment uses nobody's time at all — which is most of why it wins when
    the floor is busy."""
    assert allocate.USAGE["agent_minutes"].get("whatsapp") is None
    assert allocate.USAGE["agent_minutes"].get("represent_mandate") is None
    assert allocate.USAGE["agent_minutes"]["field_visit"] > allocate.USAGE[
        "agent_minutes"
    ]["human_call"]


# ---------------------------------------------------------------------------
# The Customer 360 card
# ---------------------------------------------------------------------------


def test_the_card_no_longer_decides_which_channel_to_use() -> None:
    """§20's duplication risk, closed.

    Three rules used to live here — "DND, so WhatsApp", "outside the preferred
    window, so schedule a callback", "over 30 DPD with no recent contact, so
    call" — written twice, once in Python and once in TypeScript, and kept in
    step by hand. All three are contact decisions the engine makes against the
    real consent record, the real calling window and the real frequency budget.
    """
    import inspect

    import customer_insights

    source = inspect.getsource(customer_insights.build_nba)
    for gone in ("nba-callback-channel", "nba-schedule-callback", "nba-outbound-call"):
        assert gone not in source, f"{gone} is still deciding contact on the card"
    # And the helper that only existed to serve them.
    assert "_within_window" not in source


def test_case_handling_items_survive() -> None:
    """The engine does not model reviewing a dispute or sending a statement, and
    folding them into it would be the same mistake in the other direction."""
    import inspect

    import customer_insights

    source = inspect.getsource(customer_insights.build_nba)
    for kept in ("nba-review-dispute", "nba-confirm-ptp", "nba-send-statement"):
        assert kept in source


def test_a_shadow_decision_is_shown_as_advice_not_as_a_hold() -> None:
    """Shadow suppresses the *enactment*, not the decision.

    Rendering it as "Hold" would make every card in the shadow fortnight report
    that the engine had nothing to suggest — the exact opposite of what the
    fortnight is for, which is showing a supervisor what it would have done
    while it does none of it.
    """
    from customer_insights import _treatment_nba

    item = _treatment_nba(
        {
            "action": "represent_mandate",
            "actionLabel": "re-present mandate",
            "suppressed": True,
            "reason": "shadow_mode",
            "expectedValueInr": 387.88,
            "rationale": "probe",
        }
    )
    assert item is not None
    assert item["action"] == "mandate"
    assert item["advisory"] is True
    assert "Hold" not in item["title"]
    assert item["priority"] == "high"


def test_a_real_hold_is_not_dressed_up_as_a_plan() -> None:
    """A borrower on a hardship hold genuinely has no recommendation, and
    presenting one would invite somebody to carry it out."""
    from customer_insights import _treatment_nba

    item = _treatment_nba(
        {
            "action": "wait",
            "suppressed": True,
            "reason": "hold:hardship",
            "reasonText": "a hardship hold is in force",
            "expectedValueInr": 0.0,
        }
    )
    assert item is not None
    assert item["action"] == "wait"
    assert item.get("advisory") is not True
    assert "Hold" in item["title"]


def test_the_engines_row_is_never_demoted_below_a_statement() -> None:
    """It is the only item on the card that priced its recommendation. Sorting
    "hold, because every attempt costs more than it is worth" below "send an
    account statement" inverts the one judgement the card exists to show."""
    from customer_insights import build_nba

    items = build_nba(
        {"account": {"dpd": 20}, "documents": [], "promises": [], "disputes": []},
        {"brokenPromiseCount": 2},
        None,
        {"action": "wait", "suppressed": True, "reason": "below_value_floor"},
    )
    assert items[0]["id"] == "nba-treatment"
    assert items[0]["priority"] == "low"
    assert any(i["priority"] in {"high", "medium"} for i in items[1:])


def test_every_engine_action_maps_to_something_the_card_can_render() -> None:
    """A treatment action with no card vocabulary renders as an empty row where
    a recommendation should be."""
    from agent_core.treatment import actions as A
    from customer_insights import _TREATMENT_ACTION_KIND

    for action in A.ALL:
        assert action in _TREATMENT_ACTION_KIND, action


# ---------------------------------------------------------------------------
# The Action Contract
# ---------------------------------------------------------------------------


def test_the_two_fields_that_carry_the_learning_loop_reach_the_channel() -> None:
    """The design note names these as the ones most easily forgotten, and they
    were — for a fortnight.

    Both were written to ``treatment_decisions`` and neither reached the
    payload. A channel that logs its own outcomes against a decision whose odds
    it never saw produces a corpus with exactly the defect P0 existed to remove.
    """
    from agent_core.treatment.engine import TreatmentResult

    payload = TreatmentResult().to_payload()
    assert "decisionId" in payload
    assert "propensity" in payload
    assert "policyVersion" in payload


def test_a_suppressed_decision_has_no_contract_at_all() -> None:
    """A contract is an authorisation to act. Handing a channel an empty one
    invites it to decide for itself what that means."""
    from agent_core.treatment.engine import TreatmentResult

    assert TreatmentResult().action_contract() is None
    assert TreatmentResult(action="whatsapp", suppressed=True).action_contract() is None


def test_the_contract_states_its_prohibitions_rather_than_assuming_them() -> None:
    """A prohibition that lives only in a system prompt is one jailbreak away
    from not existing — and a field agent has no system prompt at all."""
    from agent_core.treatment import contract
    from agent_core.treatment.engine import TreatmentResult

    envelope = contract.build(
        TreatmentResult(action="whatsapp", channel="whatsapp", suppressed=False),
        features=None,
    )
    assert "third_party_disclosure" in envelope["prohibited"]
    assert "pressure_language" in envelope["prohibited"]


def test_a_hold_narrows_what_the_channel_may_say() -> None:
    """A hold is a fact about the person, so it binds whichever channel reaches
    them. A borrower with an open dispute must not be asked for the disputed
    amount on WhatsApp any more than on a call."""
    from agent_core.treatment import contract
    from agent_core.treatment.engine import TreatmentResult
    from agent_core.treatment.features import AccountFeatures

    result = TreatmentResult(action="whatsapp", channel="whatsapp", suppressed=False)
    disputed = AccountFeatures(
        customer_id="c", tenant_id="t", holds=("dispute",), bucket="31-60"
    )
    envelope = contract.build(result, features=disputed)
    assert "demand_disputed_amount" in envelope["prohibited"]
    # And nothing may be conceded while a dispute is open.
    hardship = AccountFeatures(
        customer_id="c", tenant_id="t", holds=("hardship",), bucket="31-60"
    )
    assert contract.build(result, features=hardship)["allowedOffers"] == []


def test_a_voice_contract_is_bounded_in_time_and_a_message_is_not() -> None:
    from agent_core.treatment import contract
    from agent_core.treatment.engine import TreatmentResult
    from agent_core.treatment.features import AccountFeatures

    features = AccountFeatures(customer_id="c", tenant_id="t", bucket="0-30")
    voice = contract.build(
        TreatmentResult(action="voice_bot", channel="voice", suppressed=False),
        features=features,
    )
    text_msg = contract.build(
        TreatmentResult(action="whatsapp", channel="whatsapp", suppressed=False),
        features=features,
    )
    assert voice["maxDurationSec"] > 0
    assert "maxDurationSec" not in text_msg


def test_the_objective_follows_the_bucket_not_the_channel() -> None:
    """61-90 is triage — find out which of willing / distress / dispute this is
    and route. Asking a bot to close there exceeds what the bucket policy
    already says it may own."""
    from agent_core.treatment import contract
    from agent_core.treatment.engine import TreatmentResult
    from agent_core.treatment.features import AccountFeatures

    result = TreatmentResult(action="voice_bot", channel="voice", suppressed=False)
    early = contract.build(
        result, features=AccountFeatures(customer_id="c", tenant_id="t", bucket="0-30")
    )
    triage = contract.build(
        result, features=AccountFeatures(customer_id="c", tenant_id="t", bucket="61-90")
    )
    assert early["objective"] == "payment_commitment"
    assert triage["objective"] == "triage"
