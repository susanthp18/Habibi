"""The granularity ladder, the promotion gate, the monitors and the scoreboard.

The four things §9, §15 and §17 ask for after the estimators exist, and they
share a failure mode: every one of them produces a *number*, and a number that
is wrong is far more dangerous than a number that is missing. A missing metric
gets chased. A green one gets cited.

So most of what is tested here is refusal:

* a segment that did not beat the population model must not be in the artifact
* a challenger without holdout evidence must not be promoted
* a causal metric without both arms must not degrade to a collections rate
* a calibration check with no artifact must say so rather than return zero

The one place that is *not* about refusal is shrinkage, which is the ladder's
actual mechanism: a thin segment barely moves the pooled answer and a fat one
dominates it, continuously, so nobody has to pick a threshold that a borrower
crosses by aging one day.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from agent_core.treatment import models, monitor, segments


# ---------------------------------------------------------------------------
# The partition
# ---------------------------------------------------------------------------


def test_a_segment_key_is_a_pure_function_of_the_logged_vector() -> None:
    """Point-in-time correctness, at the granularity that most needs it.

    A borrower who was 45 DPD in March is 120 DPD now. If the key were computed
    from today's tables, replaying March's decision would file it in a stratum
    it was never in — and the segment model that scored it would be a different
    model than the one that actually ran.
    """
    vec = {"dpd": 45.0, "digital_attempts_since_connect": 1.0}
    assert segments.key_for(vec) == segments.key_for(dict(vec))
    assert segments.key_for(vec).startswith("b3160/open/")


def test_bucket_bands_land_on_the_buckets_the_rest_of_the_package_uses() -> None:
    assert segments.key_for({"dpd": 0.0}).startswith("predue/")
    assert segments.key_for({"dpd": 1.0}).startswith("b0030/")
    assert segments.key_for({"dpd": 30.0}).startswith("b0030/")
    assert segments.key_for({"dpd": 31.0}).startswith("b3160/")
    assert segments.key_for({"dpd": 91.0}).startswith("b90p/")


def test_a_vector_with_no_dpd_is_unplaceable_rather_than_guessed() -> None:
    """A stratum for "the rows whose DPD was missing" is a model of a data
    quality incident, and it would be applied to whichever accounts happen to
    be broken on the day it scores."""
    assert segments.key_for({}) == segments.UNKNOWN
    assert segments.key_for({"dpd": None}) == segments.UNKNOWN
    assert segments.UNKNOWN not in segments.all_keys()


def test_never_attempted_reads_as_reachable_not_as_going_dark() -> None:
    """Absent evidence is not negative evidence. Treating "we have not tried"
    as "they do not answer" would file every new account into the hard-to-reach
    stratum on its first decision."""
    assert "/open/" in segments.key_for({"dpd": 10.0})
    assert "/dark/" in segments.key_for(
        {"dpd": 10.0, "digital_attempts_since_connect": 3.0}
    )


def test_a_return_code_beats_an_inferred_salary_gap() -> None:
    """A bank saying the mandate is cancelled is an observation. A salary-timing
    gap inferred from credit history is an estimate, and an estimate does not
    overrule an observation."""
    both = {"dpd": 20.0, "bounce_mandate_expired": 1.0, "salary_timing_gap_days": 1.0}
    assert both and segments.cashflow_band(both) == segments.CASHFLOW_MECHANISM
    gap_only = {"dpd": 20.0, "salary_timing_gap_days": 1.0}
    assert segments.cashflow_band(gap_only) == segments.CASHFLOW_TIMING


def test_the_partition_stays_small_enough_to_have_data_in_it() -> None:
    """The temptation is to cross every dimension the design note lists and end
    up with four hundred cells holding nine observations each, which is
    individual CATE wearing a segment's name."""
    assert len(segments.all_keys()) <= 40


# ---------------------------------------------------------------------------
# Shrinkage — the ladder's mechanism
# ---------------------------------------------------------------------------


def _segment(key: str, *, n: int, control_n: int = 500, bump: float = 2.0):
    return models.SegmentModel(
        key=key,
        coefficients=(0.0,),
        intercept=bump,
        control_coefficients=(0.0,),
        control_intercept=0.0,
        n=n,
        control_n=control_n,
    )


def _artifact(segs=None):
    return models.ModelArtifact(
        name="t",
        version="v",
        kind="logistic",
        target="uplift",
        feature_names=("dpd",),
        coefficients=(0.0,),
        intercept=0.0,
        means={"dpd": 20.0},
        control_coefficients=(0.0,),
        control_intercept=0.0,
        control_arm="null_treatment",
        control_n=1000,
        segments=segs or {},
    )


def test_a_thin_segment_barely_moves_the_pooled_answer() -> None:
    """And a fat one dominates it. Continuously, so the estimate does not jump
    when a borrower crosses a boundary by aging one day."""
    key = segments.key_for({"dpd": 20.0})
    thin = _artifact({key: _segment(key, n=50)})
    fat = _artifact({key: _segment(key, n=50_000)})
    vec = {"dpd": 20.0}

    pooled = _artifact().predict(vec)
    assert thin.predict(vec) - pooled < 0.05, "a 50-row segment took over"
    assert fat.predict(vec) - pooled > 0.30, "a 50k-row segment was ignored"
    assert thin.predict(vec) < fat.predict(vec)


def test_shrinkage_weight_is_monotone_in_sample_size() -> None:
    k = models.DEFAULT_SHRINKAGE_K
    weights = [_segment("x", n=n).weight(k) for n in (10, 100, 1_000, 100_000)]
    assert weights == sorted(weights)
    assert weights[0] < 0.05 and weights[-1] > 0.99
    assert _segment("x", n=int(k)).weight(k) == pytest.approx(0.5, abs=0.01)


def test_a_negative_segment_effect_can_pull_the_population_estimate_down() -> None:
    """"Contacting this stratum makes things worse" is a finding, not a rounding
    error. Clamping each half at zero before blending would floor it away in the
    one direction a segment most needs to be able to move the answer."""
    key = segments.key_for({"dpd": 20.0})
    base = models.ModelArtifact(
        name="t", version="v", kind="logistic", target="uplift",
        feature_names=("dpd",), coefficients=(0.0,), intercept=2.0,
        means={"dpd": 20.0}, control_coefficients=(0.0,), control_intercept=0.0,
        control_arm="null_treatment", control_n=1000,
    )
    harmful = _segment(key, n=100_000, bump=-4.0)
    with_segment = models.ModelArtifact(
        **{**base.__dict__, "segments": {key: harmful}}
    )
    # sigmoid(2) - sigmoid(0) = 0.881 - 0.5
    assert base.predict({"dpd": 20.0}) == pytest.approx(0.381, abs=0.01)
    assert with_segment.predict({"dpd": 20.0}) == 0.0


# ---------------------------------------------------------------------------
# Loading segments — every rule is a reason to drop one
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, body: dict) -> Path:
    from agent_core.treatment.features import SCHEMA_VERSION

    artifact = {
        "name": "treatment_uplift",
        "target": "uplift",
        "type": "logistic",
        "version": "test",
        "trainedAt": "2026-08-21T00:00:00+00:00",
        "featureNames": ["dpd"],
        "coefficients": [0.0],
        "intercept": 0.0,
        "means": {"dpd": 20.0},
        "controlArm": "null_treatment",
        "controlN": 1000,
        "controlCoefficients": [0.0],
        "controlIntercept": 0.0,
        "vectorVersion": models.VECTOR_VERSION,
        "featureSchemaVersion": SCHEMA_VERSION,
        "corpus": "live",
        **body,
    }
    path = tmp_path / "uplift.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def test_segments_from_a_different_banding_are_ignored_wholesale(tmp_path) -> None:
    """The keys would parse and score. They would just mean a different
    population than the one they were fitted on, which no shape check can
    detect."""
    models._reset_warnings()
    key = segments.all_keys()[0]
    path = _write(
        tmp_path,
        {
            "segmentVersion": "s0",
            "segments": {
                key: {
                    "coefficients": [1.0], "intercept": 0.0,
                    "controlCoefficients": [0.0], "controlIntercept": 0.0,
                    "n": 5000, "controlN": 1000,
                }
            },
        },
    )
    artifact = models.load_artifact(path, expect_target="uplift")
    assert artifact is not None, "the population model must still load"
    assert artifact.segments == {}


def test_a_segment_with_too_thin_a_control_arm_is_dropped(tmp_path) -> None:
    """A segment is where a thin control arm hides: the artifact as a whole can
    hold twenty thousand control observations while one stratum holds nine."""
    models._reset_warnings()
    key = segments.all_keys()[0]
    path = _write(
        tmp_path,
        {
            "segments": {
                key: {
                    "coefficients": [1.0], "intercept": 0.0,
                    "controlCoefficients": [0.0], "controlIntercept": 0.0,
                    "n": 5000, "controlN": models.MIN_SEGMENT_CONTROL_N - 1,
                }
            }
        },
    )
    assert models.load_artifact(path, expect_target="uplift").segments == {}


def test_a_broken_segment_is_dropped_but_the_artifact_still_loads(tmp_path) -> None:
    """The asymmetry is deliberate. A malformed population model has nothing to
    fall back to; a malformed segment has the population model right behind it,
    so refusing the file would take the working strata down with the broken
    one."""
    models._reset_warnings()
    good, bad = segments.all_keys()[0], segments.all_keys()[1]
    path = _write(
        tmp_path,
        {
            "segments": {
                good: {
                    "coefficients": [1.0], "intercept": 0.0,
                    "controlCoefficients": [0.0], "controlIntercept": 0.0,
                    "n": 5000, "controlN": 1000,
                },
                bad: {
                    # Two coefficients for one feature.
                    "coefficients": [1.0, 2.0], "intercept": 0.0,
                    "controlCoefficients": [0.0, 0.0], "controlIntercept": 0.0,
                    "n": 5000, "controlN": 1000,
                },
                "not/a/real/key": {
                    "coefficients": [1.0], "intercept": 0.0,
                    "controlCoefficients": [0.0], "controlIntercept": 0.0,
                    "n": 5000, "controlN": 1000,
                },
            }
        },
    )
    artifact = models.load_artifact(path, expect_target="uplift")
    assert set(artifact.segments) == {good}


# ---------------------------------------------------------------------------
# Monitors
# ---------------------------------------------------------------------------


def test_a_perfectly_calibrated_model_has_no_calibration_error() -> None:
    pairs = [(0.0, 0) for _ in range(50)] + [(1.0, 1) for _ in range(50)]
    out = monitor.reliability(pairs)
    assert out["ece"] == pytest.approx(0.0, abs=1e-6)
    assert out["level"] == "ok"


def test_a_uniformly_optimistic_model_reports_its_optimism() -> None:
    """The design note's point: a model whose 0.7 does not mean 70% cannot go
    into an EV formula, because the formula multiplies it by rupees."""
    pairs = [(0.75, 1) for _ in range(50)] + [(0.75, 0) for _ in range(50)]
    out = monitor.reliability(pairs)
    assert out["ece"] == pytest.approx(0.25, abs=0.01)
    assert out["level"] == "alert"


def test_uplift_calibration_catches_a_response_model_wearing_an_uplift_label() -> None:
    """The failure every offline metric misses. A model claiming +40 points of
    uplift on a book whose control arm measured +2 has not found uplift — it has
    found the borrowers who were going to pay anyway."""
    rows = []
    for i in range(200):
        rows.append({
            "variant": "control",
            "outcome": "paid" if i < 104 else "unresolved",
            "chosen_action": "whatsapp",
            "candidates": [{"action": "whatsapp", "pResolve": 0.42}],
        })
    for i in range(200):
        rows.append({
            "variant": "null_treatment",
            "outcome": "paid" if i < 100 else "unresolved",
            "chosen_action": "wait",
            "candidates": [{"action": "wait", "pResolve": 0.0}],
        })
    out = monitor.uplift_calibration(rows, fitted=True)
    assert out["available"]
    assert out["quantity"] == "tau"
    assert out["measuredAte"] == pytest.approx(0.02, abs=0.001)
    assert out["predictedMeanTau"] == pytest.approx(0.42, abs=0.001)
    assert out["level"] == "alert"
    assert "would have cured anyway" in out["note"]

    # The same arithmetic against the EV priors is the design note's central
    # point rather than an accusation: p_resolve is P(cure | contacted) and was
    # never claiming to be an incremental effect.
    unfitted = monitor.uplift_calibration(rows, fitted=False)
    assert unfitted["quantity"] == "p_resolve_prior"
    assert "not the effect of contacting" in unfitted["note"]


def test_uplift_calibration_refuses_without_both_arms() -> None:
    rows = [{
        "variant": "control", "outcome": "paid", "chosen_action": "sms",
        "candidates": [{"action": "sms", "pResolve": 0.3}],
    }]
    assert monitor.uplift_calibration(rows)["available"] is False


def test_drift_says_it_cannot_be_measured_rather_than_reporting_none(tmp_path) -> None:
    """Inventing a scale from the recent data would measure the recent data
    against itself and report no drift, forever."""
    artifact = _artifact()
    assert not artifact.stdevs
    out = monitor.feature_drift([], artifact)
    assert out["available"] is False
    assert "stdevs" in out["reason"]


def test_drift_is_measured_in_training_sigmas() -> None:
    """"dpd has moved by 11" is not a finding until you know whether 11 is a
    tenth of a sigma or three of them."""
    artifact = models.ModelArtifact(
        name="t", version="v", kind="logistic", target="reach",
        feature_names=("dpd",), coefficients=(0.0,), intercept=0.0,
        means={"dpd": 20.0}, stdevs={"dpd": 10.0},
    )
    rows = [
        {"chosen_action": "sms", "candidates": [{"action": "sms", "vector": {"dpd": 30.0}}]}
        for _ in range(40)
    ]
    out = monitor.feature_drift(rows, artifact)
    assert out["available"]
    assert out["worst"]["shiftSigma"] == pytest.approx(1.0, abs=0.01)
    assert out["worst"]["level"] == "alert"


# ---------------------------------------------------------------------------
# The promotion gate
# ---------------------------------------------------------------------------


def _evaluation(**over):
    base = {"lift": 0.04, "trustworthy": True, "ate": 0.18}
    base.update(over)
    return base


def test_promotion_is_refused_without_holdout_evidence(db_tx, tmp_path) -> None:
    """An artifact with good training metrics and no holdout is precisely the
    thing this gate exists to stop, and it is the easiest thing in the world to
    produce by accident."""
    from agent_core.treatment import registry

    models._reset_warnings()
    path = _write(tmp_path, {})
    objections = registry.check(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path, evaluation=None
    )
    assert any("no evaluation attached" in o for o in objections)


def test_a_challenger_that_ties_the_champion_is_refused(db_tx, tmp_path) -> None:
    """It costs a deployment, a retraining cadence and an explanation, and buys
    nothing."""
    from agent_core.treatment import registry

    models._reset_warnings()
    path = _write(tmp_path, {})
    objections = registry.check(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path,
        evaluation=_evaluation(lift=0.0001),
    )
    assert any("below the" in o for o in objections)


def test_an_untrustworthy_estimate_cannot_promote_anything(db_tx, tmp_path) -> None:
    """Ten thousand rows with an effective sample size of forty is an estimate
    computed from forty rows wearing ten thousand rows' confidence interval."""
    from agent_core.treatment import registry

    models._reset_warnings()
    path = _write(tmp_path, {})
    objections = registry.check(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path,
        evaluation=_evaluation(trustworthy=False),
    )
    assert any("untrustworthy" in o for o in objections)


def test_an_uplift_model_with_no_control_arm_cannot_promote(db_tx, tmp_path) -> None:
    """It is a response model wearing the word uplift, and it will rank
    self-curers first."""
    from agent_core.treatment import registry

    models._reset_warnings()
    path = _write(tmp_path, {"controlArm": None, "controlN": 0})
    objections = registry.check(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path,
        evaluation=_evaluation(),
    )
    assert any("cannot be causal" in o for o in objections)


def test_a_negative_measured_ate_cannot_promote(db_tx, tmp_path) -> None:
    """The control arm saying the policy does not beat doing nothing is a
    finding. Promoting a tau fitted against it would promote that finding into
    the score."""
    from agent_core.treatment import registry

    models._reset_warnings()
    path = _write(tmp_path, {})
    objections = registry.check(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path,
        evaluation=_evaluation(ate=-0.02),
    )
    assert any("measured ATE" in o for o in objections)


def test_a_simulated_artifact_cannot_promote_by_accident(db_tx, tmp_path) -> None:
    from agent_core.treatment import registry

    models._reset_warnings()
    path = _write(tmp_path, {"corpus": "simulated"})
    objections = registry.check(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path,
        evaluation=_evaluation(),
    )
    assert any("does not exist" in o for o in objections)
    assert registry.check(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path,
        evaluation=_evaluation(), allow_simulated=True,
    ) == []


def test_promotion_installs_the_file_and_retires_the_incumbent(db_tx, tmp_path) -> None:
    """One champion per target, and the database is what enforces it rather
    than the promotion code remembering to demote."""
    from sqlalchemy import text

    from agent_core.treatment import registry

    models._reset_warnings()
    serving = tmp_path / "serving.json"

    _write(tmp_path, {"version": "v1"})
    (tmp_path / "v1.json").write_text(
        (tmp_path / "uplift.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = registry.promote(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=tmp_path / "v1.json",
        evaluation=_evaluation(), promoted_by="tester", serving_path=serving,
    )
    assert out["retired"] is None
    assert serving.exists(), "promotion did not install the artifact"

    _write(tmp_path, {"version": "v2"})
    (tmp_path / "v2.json").write_text(
        (tmp_path / "uplift.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = registry.promote(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=tmp_path / "v2.json",
        evaluation=_evaluation(), promoted_by="tester", serving_path=serving,
    )
    assert out["retired"] == "v1"

    champions = db_tx.execute(
        text(
            "SELECT count(*) FROM treatment_model_registry"
            " WHERE tenant_id = 'hdfc.retail' AND target = 'uplift'"
            " AND status = 'champion'"
        )
    ).scalar()
    assert champions == 1


def test_promote_raises_rather_than_installing_a_refused_artifact(db_tx, tmp_path) -> None:
    from agent_core.treatment import registry

    models._reset_warnings()
    serving = tmp_path / "serving.json"
    path = _write(tmp_path, {})
    with pytest.raises(registry.PromotionRefused):
        registry.promote(
            db_tx, tenant_id="hdfc.retail", target="uplift", path=path,
            evaluation=None, promoted_by="tester", serving_path=serving,
        )
    assert not serving.exists(), "a refused promotion still copied the file"


# ---------------------------------------------------------------------------
# The scoreboard
# ---------------------------------------------------------------------------


def test_a_causal_metric_with_thin_arms_refuses_rather_than_degrading(db_tx) -> None:
    """A metric that silently falls back to a collections rate is worse than a
    missing one: a collections rate is the number a response model wins on."""
    from sqlalchemy import text

    from agent_core.treatment import metrics

    # Scoped to the modes under test. An unqualified DELETE also removes every
    # simulated row -- twenty thousand of them on a dev database that has run
    # the corpus generator -- which is slow, rolled back, and irrelevant:
    # ``causal`` is called with modes that exclude them anyway.
    db_tx.execute(
        text("DELETE FROM treatment_decisions WHERE mode = ANY(:modes)"),
        {"modes": ["shadow", "live"]},
    )
    out = metrics.causal(db_tx, days=30, modes=["shadow", "live"])
    assert out["available"] is False
    assert "collections rate" in out["reason"]


def test_the_complaint_rate_reports_that_it_has_no_source(db_tx) -> None:
    """disputes.type is constrained to billing disputes. A conduct-complaint
    rate reading 0.00 every week because its source does not exist is worse
    than an absent one: an absent metric gets chased, a green one gets cited."""
    from agent_core.treatment import metrics

    out = metrics.compliance(db_tx, days=30)
    assert out["complaints"]["available"] is False
    assert "billing disputes only" in out["complaints"]["reason"]


def test_breaches_are_audited_from_the_ledger_not_from_a_reason_code(db_tx) -> None:
    """There is no denial reason for a breach and there should not be - the gate
    does not record permission it did not grant. Anything counted here got
    around contact_policy.evaluate() entirely."""
    from agent_core.treatment import metrics

    out = metrics.compliance(db_tx, days=30)
    assert out["breachTarget"] == 0
    assert "windowBreaches" in out and "capBreaches" in out


# ---------------------------------------------------------------------------
# The power calculation
# ---------------------------------------------------------------------------


def _power_module():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "power_control_arm.py"
    spec = importlib.util.spec_from_file_location("power_control_arm", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_smaller_detectable_effect_needs_a_much_larger_arm() -> None:
    power = _power_module()
    big, _ = power.sample_size(p_control=0.45, mde=0.05, ratio=4.0, alpha=0.05, power=0.8)
    small, _ = power.sample_size(p_control=0.45, mde=0.02, ratio=4.0, alpha=0.05, power=0.8)
    assert small > big * 4, "halving the effect should roughly quadruple the arm"


def test_an_even_split_needs_the_smallest_total() -> None:
    """Which is the whole trade-off the report exists to show: the fastest
    answer is also the one that withholds the most treatment."""
    power = _power_module()
    even = sum(power.sample_size(p_control=0.45, mde=0.05, ratio=1.0, alpha=0.05, power=0.8))
    lopsided = sum(power.sample_size(p_control=0.45, mde=0.05, ratio=9.0, alpha=0.05, power=0.8))
    assert even < lopsided


def test_clustering_costs_sample_size_rather_than_being_assumed_away() -> None:
    """A customer who goes delinquent three times contributes three cases to the
    same arm, and they are not three independent draws."""
    power = _power_module()
    plain, _ = power.sample_size(p_control=0.45, mde=0.05, ratio=4.0, alpha=0.05, power=0.8)
    clustered, _ = power.sample_size(
        p_control=0.45, mde=0.05, ratio=4.0, alpha=0.05, power=0.8, design_effect=1.6
    )
    assert clustered > plain


# ---------------------------------------------------------------------------
# The expanded action space (§6)
# ---------------------------------------------------------------------------


def test_self_service_plan_reaches_nobody_and_inherits_the_obligation() -> None:
    """channel=None buys the exemption from the frequency cap. NON_CONTACTING is
    derived rather than listed, so the exemption cannot be taken without the
    module noticing -- and the obligation that comes with it is a veto of its
    own in policy.py."""
    from agent_core.treatment import actions as A
    from agent_core.treatment import policy

    spec = A.spec(A.SELF_SERVICE_PLAN)
    assert spec.channel is None
    assert spec.intrusiveness == 0.0
    assert spec.rung == 0
    assert A.SELF_SERVICE_PLAN in A.NON_CONTACTING
    assert A.SELF_SERVICE_PLAN not in A.CONTACTING
    # The obligation, discharged.
    assert hasattr(policy, "_self_service_veto")


def test_part_payment_and_restructure_are_offers_not_actions() -> None:
    """A concession has to be said to somebody, which makes it a property of a
    contact rather than an alternative to one. Ranking "send a WhatsApp"
    against "offer a settlement" is how a bot concedes money no authority
    matrix was asked about."""
    from agent_core.treatment import actions as A

    assert "part_payment_offer" not in A.SPECS
    assert "restructure_offer" not in A.SPECS


def test_a_plan_is_not_offered_for_a_single_missed_instalment() -> None:
    """One missed EMI is a wobble that the ordinary machinery resolves. Opening
    a repayment plan for it converts a forgetful borrower into a restructured
    one."""
    from agent_core.treatment import policy
    from agent_core.treatment.features import AccountFeatures

    features = AccountFeatures(
        customer_id="C1", tenant_id="hdfc.retail",
        instalment_amount=5000.0, minimum_due=5000.0, dpd=4, has_email=True,
    )
    assert policy._instalments_in_arrears(features) == 1.0
    assert policy._self_service_veto(None, features) == policy.SELF_SERVICE_TOO_EARLY


def test_arrears_depth_is_not_measured_by_exposure_or_by_outstanding() -> None:
    """``exposure`` is a property that returns the instalment itself whenever one
    is known, so ``exposure / instalment`` is 1.0 on every account with a
    schedule -- a gate that would fire on the whole book while looking like
    arithmetic. ``outstanding`` fails the same way in reverse: a 36-month tenor
    reads as 36 instalments behind on day one."""
    from agent_core.treatment import policy
    from agent_core.treatment.features import AccountFeatures

    three_behind = AccountFeatures(
        customer_id="C1", tenant_id="hdfc.retail",
        instalment_amount=5000.0, minimum_due=15000.0,
        outstanding=180000.0, dpd=70,
    )
    assert three_behind.exposure == 5000.0  # the trap
    assert policy._instalments_in_arrears(three_behind) == pytest.approx(3.0)

    # No minimum_due: DPD stands in, one cycle per thirty days plus the one
    # that started the clock.
    no_ledger = AccountFeatures(
        customer_id="C1", tenant_id="hdfc.retail", instalment_amount=5000.0, dpd=60,
    )
    assert policy._instalments_in_arrears(no_ledger) == pytest.approx(3.0)


def test_a_plan_is_not_offered_where_it_cannot_be_seen(db_tx) -> None:
    """An offer nobody can see is not an offer. A plan surfaces in the app, the
    portal or a statement -- a borrower we hold no digital identifier for cannot
    take it up, and the engine would be scoring a cure it has no way to
    deliver."""
    from agent_core.treatment import policy
    from agent_core.treatment.features import AccountFeatures

    features = AccountFeatures(
        customer_id="C1", tenant_id="hdfc.retail",
        instalment_amount=5000.0, minimum_due=25000.0, dpd=70,
        has_email=False, has_phone=False,
    )
    assert policy._self_service_veto(db_tx, features) == policy.SELF_SERVICE_NO_SURFACE


def test_a_second_plan_is_refused_while_the_first_is_open(db_tx) -> None:
    """Two plans on one account is a borrower with two schedules and a dispute
    about which one they agreed to."""
    from sqlalchemy import text

    import db as dbmod
    from agent_core.treatment import policy
    from agent_core.treatment.features import AccountFeatures

    customer = db_tx.execute(
        text("SELECT id, tenant_id FROM customers WHERE id NOT LIKE 'SIM-%' LIMIT 1")
    ).mappings().first()
    assert customer, "no customer to test against"

    features = AccountFeatures(
        customer_id=customer["id"], tenant_id=customer["tenant_id"],
        instalment_amount=5000.0, minimum_due=25000.0, dpd=70, has_email=True,
    )
    assert policy._self_service_veto(db_tx, features) is None

    db_tx.execute(
        text(
            """
            INSERT INTO work_runtime_jobs (
              id, tenant_id, workflow_type, status, customer_id,
              payload, idempotency_key
            ) VALUES (
              :id, :tenant, 'self_service_plan', 'submitted', :cid,
              '{}'::jsonb, :idem
            )
            """
        ),
        {
            "id": dbmod._id("WRJ"), "tenant": customer["tenant_id"],
            "cid": customer["id"], "idem": "test-self-service-plan",
        },
    )
    assert policy._self_service_veto(db_tx, features) == policy.SELF_SERVICE_OPEN


def test_a_contract_without_a_connection_permits_no_waiver() -> None:
    """The honest default. An absent ceiling means the channel may not concede,
    and it degrades toward conceding less rather than more."""
    from agent_core.treatment import contract

    class _Result:
        action = "whatsapp"
        channel = "whatsapp"
        at = None
        expected_value = 42.0
        variant = "control"
        decision_id = "TD-TEST"

    out = contract.build(_Result(), features=None, policy_version=1, propensity=0.5)
    assert "maxWaiverInr" not in out
    assert "late_fee_waiver" not in out["allowedOffers"]


def test_a_contract_states_that_its_waiver_ceiling_is_conditional(db_tx) -> None:
    """Whether the person who answered is the borrower is not knowable before
    the call. A ceiling that quietly assumed verification would be a bot waiving
    a fee for whoever picked up the phone."""
    from sqlalchemy import text

    from agent_core.treatment import contract
    from agent_core.treatment.features import AccountFeatures

    row = db_tx.execute(
        text(
            """
            SELECT a.id AS account_id, a.customer_id
            FROM accounts a
            WHERE a.id NOT LIKE 'SIM-%' AND a.dpd BETWEEN 1 AND 20
            LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no low-DPD account to price a waiver against")

    class _Result:
        action = "human_call"
        channel = "voice"
        at = None
        expected_value = 68.4
        variant = "control"
        decision_id = "TD-TEST"

    features = AccountFeatures(
        customer_id=row["customer_id"], tenant_id="hdfc.retail",
        account_id=row["account_id"], bucket="0-30",
    )
    out = contract.build(
        _Result(), features=features, policy_version=1, propensity=0.5, conn=db_tx
    )
    if "maxWaiverInr" in out:
        assert out["waiverRequiresIdentityCheck"] is True
        assert "late_fee_waiver" in out["allowedOffers"]
        assert out["maxWaiverInr"] > 0
    # A restructure is never reachable from a contract: matrix.decide escalates
    # it unconditionally, so offering one would be offering something no
    # authority exists to grant.
    assert "restructure" not in out["allowedOffers"]
    assert "settlement" not in out["allowedOffers"]


# ---------------------------------------------------------------------------
# The ladder's gate, end to end
# ---------------------------------------------------------------------------


#: Fitting five thousand rows through four logistic halves takes about a minute,
#: and every test below wants the same fit. Cached across the module rather than
#: recomputed per test: the alternative was a six-minute run for five
#: assertions, which is the kind of cost that gets a test file deleted.
_LADDER_CACHE: dict[str, Any] = {}


@lru_cache(maxsize=1)
def _trainer():
    import importlib.util

    path = Path(__file__).resolve().parent.parent / "scripts" / "train_treatment_models.py"
    spec = importlib.util.spec_from_file_location("train_treatment_models", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _standard_ladder():
    """The two-strata fit every ladder test shares."""
    if "standard" not in _LADDER_CACHE:
        train = _trainer()
        _LADDER_CACHE["standard"] = _fit(train, *_two_strata())
    return _LADDER_CACHE["standard"]


def _two_strata(seed: int = 11):
    """A book with a known heterogeneous effect, and a known homogeneous one.

    Stratum A: 0-30 DPD, reachable, salary-timing -- treatment adds 30 points.
    Stratum B: 90+ DPD, going dark, capacity      -- treatment adds nothing.
    """
    import random

    rng = random.Random(seed)
    treated, control = [], []
    for dpd, attempts, gap, base, lift in (
        (15.0, 0.0, 2.0, 0.30, 0.30),
        (120.0, 5.0, 40.0, 0.20, 0.00),
    ):
        for _ in range(2000):
            treated.append((
                {
                    "dpd": dpd + rng.uniform(-3, 3),
                    "digital_attempts_since_connect": attempts,
                    "salary_timing_gap_days": gap,
                    "exposure": rng.uniform(1000, 50000),
                    "rung": float(rng.randint(1, 3)),
                },
                1 if rng.random() < base + lift else 0,
            ))
        for _ in range(700):
            control.append((
                {
                    "dpd": dpd + rng.uniform(-3, 3),
                    "digital_attempts_since_connect": attempts,
                    "salary_timing_gap_days": gap,
                    "exposure": rng.uniform(1000, 50000),
                    "rung": 0.0,
                },
                1 if rng.random() < base else 0,
            ))
    return treated, control


def _fit(train, treated, control):
    names = train.models.trainable_features(
        {k for v, _ in treated + control for k in v}
    )
    X_t, y_t, means = train._design(treated, names)
    X_c = [
        [float(v[n]) if v.get(n) is not None else means[n] for n in names]
        for v, _ in control
    ]
    y_c = [label for _, label in control]
    mu = [means[n] for n in names]
    scales = train._scales(X_t + X_c, mu)
    pop_ate = sum(y_t) / len(y_t) - sum(y_c) / len(y_c)
    promoted, report = train.fit_segments(
        treated, control,
        names=names, means=means, scales=scales, cal=(1.0, 0.0),
        population_ate=pop_ate, holdout=0.25, seed=7,
    )
    return promoted, {r["segment"]: r for r in report}, pop_ate


def test_the_ladder_promotes_a_stratum_the_pooled_model_gets_wrong() -> None:
    """The whole point of §9's middle rung, on a book where the answer is known."""
    promoted, report, pop_ate = _standard_ladder()

    heterogeneous = "b0030/open/timing"
    assert heterogeneous in promoted
    row = report[heterogeneous]
    assert row["verdict"] == "promoted"
    # The stratum's own effect is roughly double the pooled one, which is the
    # thing the pooled model cannot say.
    assert row["ate"] > pop_ate * 1.5
    assert row["holdoutLift"] > 0


def test_the_ladder_refuses_a_stratum_the_pooled_model_already_handles() -> None:
    """The interesting rejection, and the one that shows the gates are not
    redundant. The zero-uplift stratum passes the heterogeneity test easily --
    its ATE really is nothing like the pooled one -- and is still refused,
    because the population model has `dpd` as a feature and can already express
    "at 120 DPD contacting does nothing". A finer model there would fit its own
    stratum worse with fewer rows and a narrower feature range.

    A ladder with only the causal gate would have promoted it. That is the
    difference between "this segment is different" and "a segment model
    predicts it better", and only the second is a reason to ship one."""
    promoted, report, _ = _standard_ladder()

    homogeneous = "b90p/dark/capacity"
    assert homogeneous not in promoted
    row = report[homogeneous]
    assert row["verdict"] == "rejected"
    assert row["reason"] == "no_holdout_lift"
    assert row["z"] > row["zRequired"], "it passed the causal gate and was still refused"


def test_the_heterogeneity_gate_is_corrected_for_how_many_strata_were_tried() -> None:
    """Thirty candidate strata tested at an uncorrected 5% produce about one and
    a half spurious findings by construction, and each would ship a segment
    model fitted to noise."""
    train = _trainer()
    assert train.heterogeneity_z(1) == pytest.approx(1.96, abs=0.01)
    assert train.heterogeneity_z(10) > train.heterogeneity_z(1)
    assert train.heterogeneity_z(30) > train.heterogeneity_z(10)


def test_underpowered_strata_are_skipped_not_rejected() -> None:
    """Different facts about a book. "We could not test this" and "we tested it
    and it lost" should not read the same in a report."""
    train = _trainer()
    treated, control = _two_strata()
    # Starve one stratum below the control-arm floor.
    thin = [(v, label) for v, label in control if v["dpd"] < 60][:5]
    fat = [(v, label) for v, label in control if v["dpd"] >= 60]
    _, report, _ = _fit(train, treated, thin + fat)

    row = report["b0030/open/timing"]
    assert row["verdict"] == "skipped"
    assert row["reason"] == "underpowered"


def test_the_ladder_reports_every_stratum_it_considered() -> None:
    """"We tested nine strata and two beat the population" is the finding. An
    artifact that silently contained two segments would tell you half of it."""
    promoted, report, _ = _standard_ladder()
    assert len(report) >= 2
    assert len(promoted) < len(report), "everything was promoted, which is a smell"
    for row in report.values():
        assert row["verdict"] in {"promoted", "rejected", "skipped"}


def test_the_mandate_query_survives_an_unknown_cycle(db_tx) -> None:
    """A mandate on an account with no unpaid instalment must not blow up the
    feature build.

    ``:cycle IS NOT NULL`` with a NULL value gives the planner nothing to infer
    the parameter's type from, and Postgres refuses the whole statement with
    "could not determine data type of parameter $1". The CAST has to come before
    the null test, not after.

    The consequence was invisible, which is why this test exists: the feature
    build raised, ``recommend_treatment`` caught it exactly as designed and
    returned no decision, and every account holding a mandate with no current
    unpaid cycle silently dropped out of the corpus. On a 60-account run it cost
    17% of the book, and the only symptom was a decision count that looked
    plausible. The engine never failing is what kept it quiet.
    """
    from sqlalchemy import text

    from agent_core.treatment.features import SqlFeatureProvider

    account = db_tx.execute(
        text(
            """
            SELECT a.*, c.tenant_id
            FROM accounts a JOIN customers c ON c.id = a.customer_id
            WHERE a.id NOT LIKE 'SIM-%'
            LIMIT 1
            """
        )
    ).mappings().first()
    assert account, "no account in the fixture book"

    # Registered here rather than looked for, so the test runs on any database
    # rather than skipping on most of them. The transaction is rolled back.
    mandate_id = "TEST-MANDATE-CAST"
    db_tx.execute(
        text(
            """
            INSERT INTO mandates (
              id, tenant_id, customer_id, account_id, rail, umrn, status,
              debit_day, registered_at
            ) VALUES (
              :id, :tenant, :cid, :aid, 'nach', 'TESTUMRN0001', 'active',
              5, now()
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": mandate_id,
            "tenant": account["tenant_id"],
            "cid": account["customer_id"],
            "aid": account["id"],
        },
    )
    row = {"mandate_id": mandate_id}

    provider = SqlFeatureProvider()
    # instalment with no due date is exactly the NULL-cycle case.
    out = provider._mandate(
        db_tx,
        dict(account),
        {"emi_id": None, "due_at": None},
        {},
        ZoneInfo("Asia/Kolkata"),
    )
    assert out["mandate_id"] == row["mandate_id"]
    assert out["mandate_attempts_this_cycle"] == 0


def test_the_ledger_lists_every_target_when_none_is_named(db_tx, tmp_path) -> None:
    """The unfiltered call is the one nobody tries until later.

    ``AND (:target IS NULL OR target = :target)`` reads as an ordinary optional
    filter and works for every value except the one that makes it optional:
    with NULL, Postgres has nothing to infer the parameter's type from and
    refuses the statement with "could not determine data type of parameter $2".

    Third instance of this trap in this package -- the decision log's
    jsonb_build_object, the mandate feature query, and here -- and all three
    surfaced only when something passed a null. The CAST has to wrap the
    parameter, not the comparison.
    """
    from agent_core.treatment import registry

    models._reset_warnings()
    path = _write(tmp_path, {"version": "listing"})
    registry.register(
        db_tx, tenant_id="hdfc.retail", target="uplift", path=path, evaluation=None
    )

    unfiltered = registry.history(db_tx, tenant_id="hdfc.retail")
    assert any(r["version"] == "listing" for r in unfiltered)

    filtered = registry.history(db_tx, tenant_id="hdfc.retail", target="uplift")
    assert any(r["version"] == "listing" for r in filtered)
    assert registry.history(db_tx, tenant_id="hdfc.retail", target="reach") == []
