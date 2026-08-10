"""Pluggable scorers, the feature vector, talk tracks and A/B variants.

No database. Everything here is either pure or reads a JSON artifact from a
tmp_path, which is the point: the fallback ladder and the vector contract are
exactly the things that must be verifiable without infrastructure, because they
are what runs when the infrastructure is having a bad day.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from agent_core.reco import config, models, talk, vectorize
from agent_core.reco.candidates import Candidate
from agent_core.reco.features import SCHEMA_VERSION, CallSignals, CustomerFeatures
from agent_core.reco.scoring import (
    RuleScorer,
    ScoredOffer,
    build_scorer,
    rule_score_from_vector,
)


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
    return CustomerFeatures(customer_id=kw.pop("customer_id", "c1"), **kw)


def _artifact_dict(**overrides) -> dict:
    names = list(vectorize.FEATURE_NAMES)
    base = {
        "name": "propensity",
        "version": "test.1",
        "type": "logistic",
        "featureNames": names,
        "coefficients": [0.1] * len(names),
        "intercept": -1.0,
        "means": {n: 0.5 for n in names},
        "calibration": {"a": 1.0, "b": 0.0},
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "nSamples": 2000,
        "vectorVersion": vectorize.VECTOR_VERSION,
        "featureSchemaVersion": SCHEMA_VERSION,
        "metrics": {"baseRate": 0.15},
    }
    base.update(overrides)
    return base


def _write(tmp_path, payload, name="propensity.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clear_warn_cache():
    """`_warn_once` is process-global; a stale entry would mask a later test."""
    models._reset_warnings()
    yield
    models._reset_warnings()


# --------------------------------------------------------------- the vector


def test_vector_names_are_stable_and_complete():
    """`FEATURE_NAMES` is an artifact contract, not a convenience."""
    produced = vectorize.vector(_features(), CallSignals(), _candidate())
    assert set(produced) == set(vectorize.FEATURE_NAMES)
    assert len(vectorize.FEATURE_NAMES) == len(set(vectorize.FEATURE_NAMES))


def test_vector_preserves_missing_as_none():
    """Absent must not become zero. A customer with no payment history is not
    a customer with a terrible one, and a linear model cannot tell them apart
    once the distinction has been rounded to 0.0."""
    produced = vectorize.vector(_features(), CallSignals(), _candidate())
    assert produced["affordability"] is None
    assert produced["credit_health"] is None
    assert produced["prior_win_rate"] is None
    assert produced["utilization"] is None


def test_as_row_imputes_from_means_not_zero():
    names = ["affordability", "credit_health"]
    row = vectorize.as_row(
        _features(),
        CallSignals(),
        _candidate(),
        names,
        {"affordability": 0.42, "credit_health": 0.77},
    )
    assert row == [0.42, 0.77]


def test_as_row_tolerates_a_name_this_build_no_longer_emits():
    """A model outliving a feature is a reason to retrain, not a reason to drop
    the offer path on the floor mid-call."""
    row = vectorize.as_row(
        _features(), CallSignals(), _candidate(), ["affinity", "a_retired_feature"], {}
    )
    assert len(row) == 2
    assert row[1] == 0.5


def test_rule_score_matches_vector_score():
    """The drift guard.

    `rule_score_from_vector` duplicates the combination inside
    `RuleScorer._score_one` so that offline replay can score a logged vector.
    Duplication is a real risk, and this is the test whose whole job is to fail
    the moment the two stop agreeing. If it fails, do not relax it — reconcile
    the two implementations.
    """
    rng = random.Random(4)
    weights = config.weights()
    scorer = RuleScorer(weights)

    for _ in range(200):
        features = _features(
            sanctioned_amount=rng.choice([None, 100_000.0, 900_000.0]),
            outstanding=rng.choice([None, 10_000.0, 400_000.0]),
            utilization=rng.choice([None, 0.1, 0.9]),
            dpd_worst=rng.choice([None, 0, 45, 120]),
            on_time_payment_ratio=rng.choice([None, 0.2, 1.0]),
            offers_last_30d=rng.randint(0, 4),
            prior_leads_won=rng.randint(0, 3),
            prior_leads_lost=rng.randint(0, 3),
            document_requests_90d=rng.randint(0, 6),
            closure_documents_90d=rng.choice([0, 0, 0, 1, 2]),
        )
        signals = CallSignals(
            sentiment_current=round(rng.uniform(-1, 1), 2),
            intents_seen=rng.choice([(), ("product_faq",), ("upsell_opportunity",)]),
            dominant_intent=rng.choice([None, "upsell_opportunity", "balance_query"]),
            commitment_secured=rng.random() < 0.5,
            ptp_captured=rng.random() < 0.5,
        )
        candidate = _candidate(
            margin_score=round(rng.uniform(0.1, 1.0), 2),
            affinity=round(rng.uniform(0.0, 1.0), 2),
            campaign_priority=rng.choice([None, 0.2, 0.9]),
            ticket_min=rng.choice([None, 25_000.0, 200_000.0]),
        )

        live = scorer.score(features, signals, [candidate])[0].score
        replayed = rule_score_from_vector(
            vectorize.vector(features, signals, candidate), weights
        )
        assert live == pytest.approx(replayed, abs=1e-9), (
            "RuleScorer and rule_score_from_vector disagree — offline replay "
            "would evaluate a policy that is not the one in production"
        )


# ------------------------------------------------------- artifact + fallback


def test_artifact_round_trips(tmp_path):
    artifact = models.load_artifact(_write(tmp_path, _artifact_dict()))
    assert artifact is not None
    assert artifact.version == "test.1"
    assert artifact.base_rate == pytest.approx(0.15)
    assert 0.0 <= artifact.predict({"affinity": 0.5}) <= 1.0


def test_missing_artifact_is_none_not_an_exception(tmp_path):
    assert models.load_artifact(tmp_path / "nope.json") is None


def test_malformed_artifact_is_refused(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    assert models.load_artifact(path) is None


@pytest.mark.parametrize(
    "override, why",
    [
        ({"coefficients": [0.1, 0.2]}, "coefficient count does not match the names"),
        ({"type": "xgboost"}, "a model type this build cannot score"),
        ({"vectorVersion": "v99"}, "features whose meaning has changed"),
        ({"featureSchemaVersion": "v99"}, "a different feature schema"),
        ({"coefficients": ["a"] * len(vectorize.FEATURE_NAMES)}, "non-numeric coefficients"),
    ],
)
def test_unusable_artifacts_are_refused(tmp_path, override, why):
    """Strict on purpose: an artifact that scores *slightly* wrong is far more
    dangerous than one that refuses to load, because nothing notices."""
    assert models.load_artifact(_write(tmp_path, _artifact_dict(**override))) is None, why


def test_stale_artifact_falls_back(tmp_path, monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    monkeypatch.setenv("RECO_MODEL_PATH", str(_write(tmp_path, _artifact_dict(trainedAt=old))))
    monkeypatch.setenv("RECO_MODEL_MAX_AGE_DAYS", "90")
    assert models.load_propensity(config.weights()) is None


def test_fresh_artifact_loads(tmp_path, monkeypatch):
    monkeypatch.setenv("RECO_MODEL_PATH", str(_write(tmp_path, _artifact_dict())))
    scorer = models.load_propensity(config.weights())
    assert isinstance(scorer, models.PropensityScorer)


def test_build_scorer_degrades_to_rule_at_every_step(tmp_path, monkeypatch):
    monkeypatch.setenv("RECO_MODEL_PATH", str(tmp_path / "absent.json"))
    weights = config.weights()
    for name in ("rule", "propensity", "hybrid", "", "gradient-boosted-v9"):
        assert isinstance(build_scorer(name, weights), RuleScorer), name


def test_build_scorer_resolves_the_model_when_present(tmp_path, monkeypatch):
    monkeypatch.setenv("RECO_MODEL_PATH", str(_write(tmp_path, _artifact_dict())))
    weights = config.weights()
    assert isinstance(build_scorer("propensity", weights), models.PropensityScorer)
    assert isinstance(build_scorer("hybrid", weights), models.HybridScorer)


def test_llm_rerank_wraps_without_touching_selection(tmp_path, monkeypatch):
    monkeypatch.setenv("RECO_LLM_RERANK", "true")
    scorer = build_scorer("rule", config.weights())
    assert isinstance(scorer, models.LLMReranker)


# ------------------------------------------------------ propensity behaviour


def test_propensity_score_is_comparable_to_the_rule_scale(tmp_path):
    """`RECO_MIN_SCORE` was calibrated against the rule scorer. If the model
    emitted a raw probability under the same name, switching scorers would
    silently suppress every offer against a threshold of 0.35."""
    artifact = models.load_artifact(_write(tmp_path, _artifact_dict()))
    # A customer at exactly the base rate is an average prospect: 0.5.
    assert artifact.comparable_score(artifact.base_rate) == pytest.approx(0.5)
    # Well above the base rate scores high; well below scores low.
    assert artifact.comparable_score(artifact.base_rate * 4) > 0.75
    assert artifact.comparable_score(artifact.base_rate / 10) < 0.15
    # Monotone, so the ranking is unchanged by the mapping.
    scores = [artifact.comparable_score(p) for p in (0.01, 0.05, 0.2, 0.6, 0.95)]
    assert scores == sorted(scores)


def test_propensity_preserves_amount_and_reasons_from_the_rule_pass(tmp_path):
    """A coefficient vector has no opinion about how much to offer or why."""
    artifact = models.load_artifact(_write(tmp_path, _artifact_dict()))
    scorer = models.PropensityScorer(artifact, config.weights())
    features = _features(sanctioned_amount=1_000_000.0, outstanding=200_000.0)
    offers = scorer.score(features, CallSignals(), [_candidate()])
    assert offers[0].suggested_amount is not None
    assert offers[0].reason_codes
    assert offers[0].p_convert is not None
    assert offers[0].expected_value is not None


def test_propensity_ranks_by_expected_value(tmp_path):
    """A 20% chance on ₹5 lakh beats a 45% chance on ₹25,000."""
    artifact = models.load_artifact(_write(tmp_path, _artifact_dict()))
    scorer = models.PropensityScorer(artifact, config.weights())
    features = _features(sanctioned_amount=2_000_000.0, outstanding=100_000.0)
    small = _candidate("small-ticket", ticket_min=5_000.0, ticket_max=25_000.0)
    large = _candidate("large-ticket", ticket_min=100_000.0, ticket_max=2_000_000.0)
    offers = scorer.score(features, CallSignals(), [small, large])
    assert offers[0].product_id == "large-ticket"


def test_propensity_falls_back_to_the_rule_ranking_when_scoring_raises(tmp_path, monkeypatch):
    artifact = models.load_artifact(_write(tmp_path, _artifact_dict()))
    scorer = models.PropensityScorer(artifact, config.weights())

    def _boom(_self, _vec):
        raise RuntimeError("model exploded")

    # ModelArtifact is frozen, so the patch goes on the class.
    monkeypatch.setattr(models.ModelArtifact, "predict", _boom)
    offers = scorer.score(_features(), CallSignals(), [_candidate("a"), _candidate("b")])
    # Still two offers, still scored — by the rule pass, not the model.
    assert len(offers) == 2
    assert all(o.p_convert is None for o in offers)


def test_hybrid_blends_and_pins_its_weight(tmp_path):
    artifact = models.load_artifact(_write(tmp_path, _artifact_dict()))
    rule = RuleScorer(config.weights())
    propensity = models.PropensityScorer(artifact, config.weights())
    features = _features(sanctioned_amount=900_000.0, outstanding=100_000.0)
    candidates = [_candidate()]

    rule_only = rule.score(features, CallSignals(), candidates)[0].score
    model_only = propensity.score(features, CallSignals(), candidates)[0].score

    all_rule = models.HybridScorer(rule, propensity, 1.0).score(
        features, CallSignals(), candidates
    )[0]
    all_model = models.HybridScorer(rule, propensity, 0.0).score(
        features, CallSignals(), candidates
    )[0]
    half = models.HybridScorer(rule, propensity, 0.5).score(
        features, CallSignals(), candidates
    )[0]

    assert all_rule.score == pytest.approx(rule_only)
    assert all_model.score == pytest.approx(model_only)
    assert half.score == pytest.approx((rule_only + model_only) / 2)


# ------------------------------------------------------------- LLM reranker


class _FixedScorer:
    name = "fixed"
    version = "1.0"

    def __init__(self, offers):
        self._offers = offers

    def score(self, features, signals, candidates):
        return list(self._offers)


def _offer(pid: str, score: float) -> ScoredOffer:
    return ScoredOffer(
        product_id=pid,
        name=pid,
        score=score,
        suggested_amount=100_000.0,
        roi=None,
        category=None,
        reason_codes=(),
        explanation="",
    )


def test_reranker_drops_ids_the_engine_never_approved(monkeypatch):
    """The failure that matters: the model naming a product nobody approved.

    Dropped, and loud — a silent drop would hide a prompt-injection attempt as
    easily as a typo.
    """
    base = [_offer("a", 0.9), _offer("b", 0.8), _offer("c", 0.7)]
    reranker = models.LLMReranker(_FixedScorer(base))
    monkeypatch.setattr(
        models, "_strip_fence", lambda raw: raw
    )

    import agent_core.reco.models as m

    class _FakeAzure:
        @staticmethod
        def chat_complete(*_a, **_kw):
            return json.dumps({"order": ["c", "not-a-real-product", "a"]})

    monkeypatch.setitem(__import__("sys").modules, "azure_openai", _FakeAzure)
    result = reranker.score(_features(), CallSignals(), [])

    ids = [o.product_id for o in result]
    assert "not-a-real-product" not in ids
    assert set(ids) == {"a", "b", "c"}, "an omitted offer must keep its place, not vanish"
    assert ids[0] == "c"


def test_reranker_keeps_the_base_order_when_the_llm_fails(monkeypatch):
    base = [_offer("a", 0.9), _offer("b", 0.8)]
    reranker = models.LLMReranker(_FixedScorer(base))

    class _Broken:
        @staticmethod
        def chat_complete(*_a, **_kw):
            raise TimeoutError("azure unavailable")

    monkeypatch.setitem(__import__("sys").modules, "azure_openai", _Broken)
    result = reranker.score(_features(), CallSignals(), [])
    assert [o.product_id for o in result] == ["a", "b"]


def test_reranker_skips_the_round_trip_for_a_single_offer(monkeypatch):
    """Not worth a network call on the audio path to confirm a one-item list
    is already sorted."""

    class _Exploding:
        @staticmethod
        def chat_complete(*_a, **_kw):
            raise AssertionError("should not have been called")

    monkeypatch.setitem(__import__("sys").modules, "azure_openai", _Exploding)
    reranker = models.LLMReranker(_FixedScorer([_offer("a", 0.9)]))
    assert len(reranker.score(_features(), CallSignals(), [])) == 1


# ------------------------------------------------------------- talk tracks


@pytest.mark.parametrize(
    "amount, spoken, written",
    [
        (None, "", ""),
        (0, "", ""),
        (500, "500 rupees", "₹500"),
        (45_000, "45 thousand rupees", "₹45,000"),
        (150_000, "1.5 lakh rupees", "₹1,50,000"),
        (1_523_000, "15.23 lakh rupees", "₹15,23,000"),
        (25_000_000, "2.5 crore rupees", "₹2,50,00,000"),
    ],
)
def test_money_renders_per_channel(amount, spoken, written):
    """TTS reads "150000" digit by digit; chat is read, not heard."""
    assert talk.speakable_amount(amount) == spoken
    assert talk.written_amount(amount) == written


def test_talk_track_uses_the_right_article_and_keeps_the_window_intact():
    offer = ScoredOffer(
        product_id="auto-loan",
        name="Auto Loan",
        score=0.6,
        suggested_amount=150_000.0,
        roi="10.25% p.a.",
        category="Loan",
        reason_codes=("comfortable_headroom",),
        explanation="",
    )
    track = talk.talk_track(offer, channel="voice", preferred_window="10:00-19:00 IST")
    assert "an Auto Loan" in track
    assert "a Auto Loan" not in track
    # `.capitalize()` would have lowercased IST into "ist".
    assert "10:00-19:00 IST" in track


def test_talk_track_never_quotes_a_rate():
    """An interest rate spoken on a call is heard as a commitment, and the rate
    that eventually applies depends on underwriting this engine has not done."""
    offer = ScoredOffer(
        product_id="topup-loan",
        name="Top Up Loan",
        score=0.6,
        suggested_amount=150_000.0,
        roi="10.75% p.a.",
        category="Loan",
        reason_codes=("customer_asked_for_it",),
        explanation="",
    )
    track = talk.talk_track(offer, channel="voice")
    assert "10.75" not in track and "%" not in track


def test_talk_track_omits_reasons_that_are_not_ours_to_share():
    """Telling a customer we ranked them down is not transparency."""
    offer = ScoredOffer(
        product_id="topup-loan",
        name="Top Up Loan",
        score=0.4,
        suggested_amount=50_000.0,
        roi=None,
        category=None,
        reason_codes=("tight_headroom", "recently_contacted", "closure_documents_requested"),
        explanation="",
    )
    track = talk.talk_track(offer, channel="voice")
    for leaked in ("tight", "recently", "closure", "document"):
        assert leaked not in track.lower()


# ---------------------------------------------------------------- variants


def test_builtin_variants_are_always_available():
    names = config.variants()
    for expected in ("control", "rule", "model", "hybrid", "holdout"):
        assert expected in names


def test_unknown_variant_falls_back_without_raising():
    assert config.resolve_variant("does-not-exist") is None
    assert config.resolve_variant(None) is None
    assert config.resolve_variant("") is None


def test_variants_can_be_declared_in_env(monkeypatch):
    monkeypatch.setenv(
        "RECO_VARIANTS",
        json.dumps({"challenger": {"scorer": "hybrid", "ruleWeight": 0.3}}),
    )
    challenger = config.resolve_variant("challenger")
    assert challenger is not None
    assert challenger.scorer == "hybrid"
    assert challenger.rule_weight == pytest.approx(0.3)


def test_malformed_variant_config_degrades_to_builtins(monkeypatch):
    monkeypatch.setenv("RECO_VARIANTS", "{not json")
    assert "control" in config.variants()
    monkeypatch.setenv("RECO_VARIANTS", json.dumps({"bad": {"mode": "sideways"}}))
    # The unknown mode is dropped; the arm still exists rather than vanishing.
    assert config.resolve_variant("bad").mode is None


def test_ab_split_normalises_and_drops_unknown_arms(monkeypatch):
    monkeypatch.setenv("RECO_AB_SPLIT", "control:70,model:30,ghost:99")
    split = dict(config.ab_split())
    assert "ghost" not in split
    assert split["control"] == pytest.approx(0.7)
    assert split["model"] == pytest.approx(0.3)
    assert sum(split.values()) == pytest.approx(1.0)


def test_variant_assignment_is_stable_per_customer(monkeypatch):
    """A customer pitched by the rule scorer on Monday and the model on
    Thursday belongs to neither arm, and every number from that split is
    noise."""
    monkeypatch.setenv("RECO_AB_SPLIT", "control:50,model:50")
    for customer in (f"cust-{i}" for i in range(50)):
        first = config.assign_variant(customer)
        assert first is not None
        for _ in range(5):
            assert config.assign_variant(customer).name == first.name


def test_variant_assignment_respects_the_split(monkeypatch):
    monkeypatch.setenv("RECO_AB_SPLIT", "control:90,model:10")
    counts = {"control": 0, "model": 0}
    for i in range(4000):
        counts[config.assign_variant(f"customer-{i}").name] += 1
    share = counts["model"] / sum(counts.values())
    # Hash bucketing, so allow slack — this asserts "roughly 10%", not "exactly".
    assert 0.07 < share < 0.13, counts


def test_no_split_means_no_assignment(monkeypatch):
    monkeypatch.delenv("RECO_AB_SPLIT", raising=False)
    assert config.assign_variant("anyone") is None
