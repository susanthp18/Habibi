"""Next-Best-Offer engine — scoring, candidates, arbitration.

These run without a database on purpose. The pure layers (scoring,
arbitration, amount derivation) are where the commercial and compliance
behaviour actually lives, and they must be testable without a fixture.
"""

from __future__ import annotations

import pytest

from agent_core.reco import arbitration, candidates as cand, config
from agent_core.reco.candidates import Candidate
from agent_core.reco.features import CallSignals, CustomerFeatures
from agent_core.reco.scoring import RuleScorer, build_scorer, suggest_amount


def _candidate(pid: str = "topup-loan", **kw) -> Candidate:
    base = dict(
        product_id=pid,
        name=pid.replace("-", " ").title(),
        category="Loan",
        family="unsecured_loan",
        description=None,
        ticket_min=50_000.0,
        ticket_max=1_500_000.0,
        roi="10.75% p.a.",
        roi_numeric=10.75,
        margin_score=0.7,
        affinity=0.5,
        campaign_id=None,
        campaign_priority=None,
    )
    base.update(kw)
    return Candidate(**base)


def _features(**kw) -> CustomerFeatures:
    base = dict(customer_id="c1")
    base.update(kw)
    return CustomerFeatures(**base)


def _signals(**kw) -> CallSignals:
    return CallSignals(**kw)


def _scorer() -> RuleScorer:
    return RuleScorer(config.weights())


# ------------------------------------------------------------------- scoring


def test_score_is_bounded_and_deterministic():
    scorer = _scorer()
    f, s, c = _features(), _signals(), [_candidate()]
    first = scorer.score(f, s, c)
    second = scorer.score(f, s, c)
    assert [o.score for o in first] == [o.score for o in second]
    assert all(0.0 <= o.score <= 1.0 for o in first)


def test_a_product_the_customer_asked_for_outranks_one_they_did_not():
    """The in-call ask is the strongest signal available and it is free."""
    scorer = _scorer()
    asked, ignored = _candidate("topup-loan"), _candidate("gold-loan")
    offers = scorer.score(
        _features(),
        _signals(product_mentions=("topup-loan",)),
        [ignored, asked],
    )
    assert offers[0].product_id == "topup-loan"
    assert "customer_asked_for_it" in offers[0].reason_codes


def test_worse_dpd_scores_lower():
    scorer = _scorer()
    clean = scorer.score(_features(dpd_worst=0), _signals(), [_candidate()])[0]
    delinquent = scorer.score(_features(dpd_worst=85), _signals(), [_candidate()])[0]
    assert clean.score > delinquent.score


def test_missing_credit_history_is_absent_not_zero():
    """A customer with no payment history must not be ranked as though they had
    a terrible one — the signal drops out of the average entirely."""
    scorer = _scorer()
    unknown = scorer.score(_features(), _signals(), [_candidate()])[0]
    terrible = scorer.score(
        _features(dpd_worst=90, on_time_payment_ratio=0.0), _signals(), [_candidate()]
    )[0]
    assert "credit_health" not in unknown.components
    assert unknown.score > terrible.score


def test_offer_fatigue_penalises_a_recently_contacted_customer():
    scorer = _scorer()
    fresh = scorer.score(_features(offers_last_30d=0), _signals(), [_candidate()])[0]
    tired = scorer.score(_features(offers_last_30d=3), _signals(), [_candidate()])[0]
    assert tired.score < fresh.score
    assert "recently_contacted" in tired.reason_codes


def test_ties_break_deterministically_on_product_id():
    """Offline replay compares runs; two identical runs must not disagree."""
    scorer = _scorer()
    offers = scorer.score(
        _features(), _signals(), [_candidate("b-product"), _candidate("a-product")]
    )
    assert [o.product_id for o in offers] == ["a-product", "b-product"]


def test_unknown_scorer_name_falls_back_rather_than_failing():
    """A missing model artifact must cost lift, never availability."""
    assert isinstance(build_scorer("gradient-boosted-v9", config.weights()), RuleScorer)


# ------------------------------------------------------------- amount derivation


@pytest.mark.parametrize(
    "sanctioned,outstanding,expected_within",
    [
        (800_000.0, 200_000.0, (50_000.0, 1_500_000.0)),
        (100_000.0, 99_000.0, (50_000.0, 1_500_000.0)),  # no headroom → ticket floor
        (None, None, (50_000.0, 1_500_000.0)),  # unknown → ticket floor
    ],
)
def test_suggested_amount_always_lands_inside_the_ticket_band(
    sanctioned, outstanding, expected_within
):
    amount = suggest_amount(
        _candidate(), _features(sanctioned_amount=sanctioned, outstanding=outstanding)
    )
    lo, hi = expected_within
    assert amount is not None
    assert lo <= amount <= hi


def test_suggested_amount_is_a_number_a_person_would_say():
    amount = suggest_amount(
        _candidate(), _features(sanctioned_amount=813_137.0, outstanding=201_411.0)
    )
    assert amount % 10_000 == 0, f"{amount} is not speakable"


def test_no_ticket_band_yields_no_invented_amount():
    amount = suggest_amount(
        _candidate(ticket_min=None, ticket_max=None), _features()
    )
    assert amount is None


# --------------------------------------------------------------- arbitration


def _offers(score: float = 0.9):
    return _scorer().score(
        _features(), _signals(sentiment_current=score), [_candidate()]
    )


@pytest.mark.parametrize(
    "features_kw,signals_kw,expected",
    [
        ({"dnd": True}, {}, arbitration.SUPPRESS_DND),
        (
            {"consent_by_channel": {"voice": "opted_out"}},
            {},
            arbitration.SUPPRESS_CONSENT,
        ),
        ({}, {"escalation_flagged": True}, arbitration.SUPPRESS_ESCALATED),
        ({}, {"dispute_opened": True}, arbitration.SUPPRESS_DISPUTE),
        ({}, {"hardship_mentioned": True}, arbitration.SUPPRESS_HARDSHIP),
        ({}, {"offer_declined_this_call": True}, arbitration.SUPPRESS_ALREADY_DECLINED),
        ({}, {"sentiment_current": -0.8}, arbitration.SUPPRESS_SENTIMENT),
        ({}, {"commitment_secured": False}, arbitration.SUPPRESS_NO_COMMITMENT),
        ({"offers_last_30d": 9}, {}, arbitration.SUPPRESS_CUSTOMER_CAP),
        ({}, {"offers_presented_this_call": 5}, arbitration.SUPPRESS_CALL_CAP),
    ],
)
def test_every_gate_suppresses_with_its_own_reason(features_kw, signals_kw, expected):
    """Each gate must be individually provable — a silent gate is one nobody
    notices has stopped working."""
    signals = _signals(**{"commitment_secured": True, **signals_kw})
    verdict = arbitration.arbitrate(
        features=_features(**features_kw),
        signals=signals,
        offers=_offers(),
        policy=config.policy(),
        channel="voice",
    )
    assert verdict.suppressed is True
    assert verdict.offers == []
    assert verdict.reason == expected


def test_a_healthy_call_gets_its_offer():
    verdict = arbitration.arbitrate(
        features=_features(),
        signals=_signals(commitment_secured=True, sentiment_current=0.4),
        offers=_offers(),
        policy=config.policy(),
        channel="voice",
    )
    assert verdict.suppressed is False
    assert len(verdict.offers) >= 1


def test_offers_below_the_score_floor_are_not_worth_the_handle_time():
    weak = _scorer().score(
        _features(offers_last_30d=3, dpd_worst=89),
        _signals(sentiment_current=-0.1),
        [_candidate(affinity=0.0, margin_score=0.0, campaign_priority=0.0)],
    )
    verdict = arbitration.arbitrate(
        features=_features(),
        signals=_signals(commitment_secured=True),
        offers=weak,
        policy=config.policy(),
        channel="voice",
    )
    assert verdict.suppressed is True
    assert verdict.reason == arbitration.SUPPRESS_BELOW_THRESHOLD


def test_arbitration_never_returns_more_than_the_configured_maximum():
    many = _scorer().score(
        _features(),
        _signals(sentiment_current=0.9),
        [_candidate(f"p{i}", affinity=0.9) for i in range(6)],
    )
    verdict = arbitration.arbitrate(
        features=_features(),
        signals=_signals(commitment_secured=True, sentiment_current=0.9),
        offers=many,
        policy=config.policy(),
        channel="voice",
    )
    assert len(verdict.offers) <= config.policy().max_offers_returned


# ------------------------------------------------------------------ sourcing


def test_capture_is_refused_for_a_product_the_engine_never_offered():
    """The prompt says "never name a product you weren't given". This is what
    makes that true — the model only has to hallucinate one guessable slug."""
    from agent_core.tools import domain

    assert domain.offer_sourcing_violation("gold-loan", {"topup-loan"}) is not None
    assert domain.offer_sourcing_violation("topup-loan", {"topup-loan"}) is None


def test_nothing_may_be_pitched_before_the_engine_has_run():
    from agent_core.tools import domain

    violation = domain.offer_sourcing_violation("topup-loan", set())
    assert violation is not None
    assert violation.error == "product_not_offered"


# ------------------------------------------------------------------- config


def test_mode_defaults_to_shadow_so_a_new_recommender_earns_its_way_live(monkeypatch):
    monkeypatch.delenv("RECO_MODE", raising=False)
    assert config.mode() == config.MODE_SHADOW


def test_an_unrecognised_mode_degrades_to_shadow_not_off(monkeypatch):
    """A typo must not silently stop collecting the data the engine learns from."""
    monkeypatch.setenv("RECO_MODE", "liev")
    assert config.mode() == config.MODE_SHADOW


def test_weights_are_tunable_without_a_deploy(monkeypatch):
    monkeypatch.setenv("RECO_W_AFFINITY", "0.99")
    assert config.weights().affinity == 0.99


def test_a_malformed_weight_falls_back_instead_of_crashing(monkeypatch):
    monkeypatch.setenv("RECO_W_AFFINITY", "not-a-number")
    assert config.weights().affinity == 0.20


# --------------------------------------------------------- candidate reasons


def test_exclusion_reasons_are_stable_identifiers_not_prose():
    """They are counted in dashboards; rewording one starts a new series."""
    for name in dir(cand):
        if name.startswith("REASON_"):
            value = getattr(cand, name)
            assert value.islower() and " " not in value, f"{name}={value!r}"
