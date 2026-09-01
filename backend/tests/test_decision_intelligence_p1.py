"""P1 — the estimators, and the labels they are only as good as.

Reach, payment timing and uplift replace three planning constants in the EV
formula. Most of what can go wrong here is invisible: a model that fails loads
loudly, but a model fitted on a contaminated label, on an unscaled design
matrix, or on a corpus of a book that does not exist all score perfectly
plausible numbers and rank borrowers confidently wrong.

Every test below pins something that actually went wrong while building this,
because each of those failures reported a metric that looked like a finding.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_core.treatment import models, scoring
from agent_core.treatment import actions as A
from agent_core.treatment.features import SCHEMA_VERSION

NOW = datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)


def _artifact(tmp_path, **overrides) -> str:
    body = {
        "name": "probe",
        "target": "reach",
        "type": "logistic",
        "version": "test",
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "featureNames": ["dpd", "risk_score"],
        "coefficients": [0.1, 0.002],
        "intercept": -0.5,
        "means": {"dpd": 20.0, "risk_score": 600.0},
        "calibration": {"a": 1.0, "b": 0.0},
        "metrics": {"baseRate": 0.4},
        "nSamples": 900,
        "vectorVersion": models.VECTOR_VERSION,
        "featureSchemaVersion": SCHEMA_VERSION,
        "corpus": "live",
    }
    body.update(overrides)
    path = tmp_path / f"{body['target']}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return str(path)


@pytest.fixture(autouse=True)
def _quiet_warnings():
    models._reset_warnings()
    yield
    models._reset_warnings()


# ---------------------------------------------------------------------------
# The fallback chain
# ---------------------------------------------------------------------------


def test_a_missing_artifact_costs_accuracy_not_availability(tmp_path) -> None:
    """A recommender that can fail a decision is worse than a less accurate one.

    In this package a failed decision means a borrower is either contacted for
    no reason or not contacted when they should have been.
    """
    assert models.load_artifact(tmp_path / "nope.json", expect_target="reach") is None


@pytest.mark.parametrize(
    "overrides,why",
    [
        ({"coefficients": [0.1]}, "one coefficient for two names"),
        ({"type": "xgboost"}, "a kind this build cannot score"),
        ({"vectorVersion": "t0"}, "the same names meaning something else"),
        ({"featureSchemaVersion": "v1"}, "features from a different schema"),
        ({"coefficients": ["a", "b"]}, "non-numeric coefficients"),
    ],
)
def test_a_wrong_artifact_refuses_rather_than_scoring_slightly_wrong(
    tmp_path, overrides, why
) -> None:
    """A truncated or hand-edited artifact that scores *nearly* right is far
    more dangerous than one that will not load, because nothing downstream will
    notice."""
    path = _artifact(tmp_path, **overrides)
    assert models.load_artifact(path, expect_target="reach") is None, why


def test_an_artifact_cannot_be_loaded_as_the_wrong_estimator(tmp_path) -> None:
    """Loading a reach model where uplift was asked for would score every action
    with the wrong quantity and produce numbers that look entirely reasonable."""
    path = _artifact(tmp_path, target="reach")
    assert models.load_artifact(path, expect_target="reach") is not None
    assert models.load_artifact(path, expect_target="uplift") is None


def test_a_stale_artifact_is_refused(tmp_path, monkeypatch) -> None:
    """A book drifts. The bucket mix, the mandate population and the
    reachability of a phone number all move, and scoring last quarter's book
    while calling it learned is worse than using the documented priors."""
    monkeypatch.setenv("TREATMENT_MODEL_MAX_AGE_DAYS", "30")
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    assert models.load_artifact(_artifact(tmp_path, trainedAt=old), expect_target="reach") is None


def test_a_model_of_an_imaginary_book_does_not_score_real_borrowers(
    tmp_path, monkeypatch
) -> None:
    """The simulator writes a corpus that looks exactly like a real one, so a
    model fitted on it looks exactly like a real model — same shape, same
    metrics, plausible coefficients — and would happily rank actions for
    borrowers who exist."""
    monkeypatch.delenv("TREATMENT_ALLOW_SIMULATED_MODELS", raising=False)
    path = _artifact(tmp_path, corpus="simulated")
    assert models.load_artifact(path, expect_target="reach") is None

    monkeypatch.setenv("TREATMENT_ALLOW_SIMULATED_MODELS", "1")
    models._reset_warnings()
    loaded = models.load_artifact(path, expect_target="reach")
    assert loaded is not None and loaded.corpus == "simulated"


# ---------------------------------------------------------------------------
# Uplift is gated harder, and for a reason
# ---------------------------------------------------------------------------


def test_uplift_without_a_control_arm_is_refused(tmp_path, monkeypatch) -> None:
    """An uplift model fitted on observational data is a response model wearing
    the word "uplift". It ranks self-curers first — they genuinely do have the
    highest absolute repayment probability — and the engine then spends its most
    expensive capacity on borrowers who needed nothing.

    That failure is invisible in every offline metric except one computed
    against a control arm, so the check has to be at load time rather than left
    to whoever reads the model card.
    """
    complete = dict(
        target="uplift",
        controlArm="null_treatment",
        controlCoefficients=[0.05, 0.001],
        controlIntercept=-0.9,
        controlN=5000,
    )
    monkeypatch.setenv("TREATMENT_UPLIFT_MODEL_PATH", _artifact(tmp_path, **complete))
    assert models.load_uplift() is not None

    models._reset_warnings()
    monkeypatch.setenv(
        "TREATMENT_UPLIFT_MODEL_PATH",
        _artifact(tmp_path, **{**complete, "controlArm": None}),
    )
    assert models.load_uplift() is None


def test_uplift_with_no_control_half_is_refused(tmp_path, monkeypatch) -> None:
    """τ is a difference. An artifact with only one half is a response model."""
    monkeypatch.setenv(
        "TREATMENT_UPLIFT_MODEL_PATH",
        _artifact(tmp_path, target="uplift", controlArm="null_treatment", controlN=5000),
    )
    assert models.load_uplift() is None


def test_a_control_arm_too_thin_to_have_measured_anything_is_refused(
    tmp_path, monkeypatch
) -> None:
    """τ is the difference of two noisy quantities. A few hundred control rows
    produce confident noise, which is strictly worse than the priors because it
    looks learned."""
    monkeypatch.setenv("TREATMENT_UPLIFT_MODEL_PATH", _artifact(
        tmp_path,
        target="uplift",
        controlArm="null_treatment",
        controlN=12,
        controlCoefficients=[0.05, 0.001],
        controlIntercept=-0.9,
    ))
    assert models.load_uplift() is None


def test_uplift_predicts_a_difference_not_a_response(tmp_path) -> None:
    """The T-learner, arithmetically.

    Both halves are the same model here, so τ must be exactly zero — a borrower
    the treated and untreated arms agree about is a borrower our contact does
    not move, however high their absolute repayment probability.
    """
    path = _artifact(
        tmp_path,
        target="uplift",
        controlArm="null_treatment",
        controlN=5000,
        controlCoefficients=[0.1, 0.002],
        controlIntercept=-0.5,
    )
    artifact = models.load_artifact(path, expect_target="uplift")
    assert artifact is not None
    assert artifact.predict({"dpd": 45.0, "risk_score": 700.0}) == pytest.approx(0.0)


def test_a_negative_treatment_effect_does_not_become_a_positive_expected_value(
    tmp_path,
) -> None:
    """Some contact makes things worse, and that is a real finding. But the EV
    formula multiplies τ by an exposure, so a negative τ would make the action
    look *better* the more the borrower owes."""
    path = _artifact(
        tmp_path,
        target="uplift",
        controlArm="null_treatment",
        controlN=5000,
        # The control half is far more optimistic than the treated half.
        controlCoefficients=[0.1, 0.002],
        controlIntercept=2.0,
    )
    artifact = models.load_artifact(path, expect_target="uplift")
    assert artifact is not None
    assert artifact.predict({"dpd": 45.0, "risk_score": 700.0}) == 0.0


# ---------------------------------------------------------------------------
# The scorer
# ---------------------------------------------------------------------------


def test_with_no_artifacts_the_scorer_is_the_ev_scorer() -> None:
    base = scoring.EVScorer()
    assert models.build(base) is base


def test_a_scorer_records_which_estimators_were_live(tmp_path) -> None:
    """Lands in ``treatment_decisions.recommender``. Without it a corpus
    spanning a rollout cannot be split by which model produced each row, and a
    champion/challenger comparison silently mixes them."""
    artifact = models.load_artifact(_artifact(tmp_path), expect_target="reach")
    scorer = models.EstimatorScorer(scoring.EVScorer(), reach=artifact)
    assert scorer.name == "ev+reach"


def test_the_trainer_may_not_fit_on_the_scorers_own_output() -> None:
    """A reach model fitted with ``p_reach`` among its inputs learns to copy
    ``REACH_PRIOR`` and reports an excellent holdout score for doing so. An
    uplift model fitted with ``p_resolve`` learns ``RESOLVE_PRIOR`` and calls it
    a treatment effect. Neither is visible in any metric that does not know
    where the column came from."""
    keys = {"dpd", "exposure", "p_reach", "p_resolve", "cost", "risk_score"}
    trainable = models.trainable_features(keys)
    assert "p_reach" not in trainable
    assert "p_resolve" not in trainable
    assert "cost" not in trainable
    assert {"dpd", "exposure", "risk_score"} <= set(trainable)
    # Sorted, so two trainers on the same corpus produce comparable artifacts.
    assert list(trainable) == sorted(trainable)


# ---------------------------------------------------------------------------
# The vector the estimators read
# ---------------------------------------------------------------------------


def _features(**overrides):
    from agent_core.treatment.features import AccountFeatures

    base = {
        "customer_id": "probe",
        "tenant_id": "hdfc.retail",
        "account_id": "acct",
        "dpd": 12,
        "bucket": A.B_0_30,
        "instalment_amount": 4500.0,
        "has_phone": True,
        "timezone_name": "Asia/Kolkata",
    }
    base.update(overrides)
    return AccountFeatures(**base)


def _scored(action: str = A.WHATSAPP):
    return scoring.ScoredAction(
        action=action,
        channel=A.spec(action).channel,
        at=NOW,
        expected_value=10.0,
        p_reach=0.5,
        p_resolve=0.2,
        cost=0.42,
        explanation="probe",
    )


def test_the_vector_can_tell_two_borrowers_apart() -> None:
    """The regression behind two estimators scoring an AUC of 0.50 on a corpus
    that demonstrably contained learnable heterogeneity.

    The vector had the *account* and the *attempt* in it and almost nothing
    about the borrower, so a model asked to distinguish two people had nothing
    to distinguish them with. The design note asks for segment-level uplift over
    "bucket × channel × contactability × cash-flow pattern"; the first three
    were present and the fourth was not.
    """
    from agent_core.treatment.features import Trigger

    vec = scoring.vector(
        _features(bounce_reason="mandate_expired", promises_broken=3, secured=True),
        Trigger(kind="bounce", at=NOW),
        _scored(),
        now=NOW,
    )
    # The return code is the single most diagnostic thing known about a
    # delinquent account: insufficient funds is a cash-flow problem and a
    # cancelled mandate is a willingness problem, and a model that cannot see
    # the difference prices them the same.
    assert vec["bounce_mandate_expired"] == 1.0
    assert vec["bounce_insufficient_funds"] == 0.0
    assert vec["promises_broken"] == 3.0
    assert vec["secured"] == 1.0


def test_the_vector_stays_raw_and_the_scaling_lives_in_the_trainer() -> None:
    """``exposure`` is rupees, not a normalised 0..1.

    Deliberate, and it is what a decision log should contain: ``4503.96`` is
    inspectable a year later and ``0.31`` is not. The consequence is that the
    trainer must standardise before fitting — at a learning rate that suits
    ``intrusiveness=0.15`` the rupee columns saturate every sigmoid on the first
    pass and the model predicts a constant, which scores an AUC of exactly 0.500
    and reads like "no signal" rather than "this diverged".
    """
    from agent_core.treatment.features import Trigger

    vec = scoring.vector(
        _features(instalment_amount=4503.96),
        Trigger(kind="bounce", at=NOW),
        _scored(),
        now=NOW,
    )
    assert vec["exposure"] == pytest.approx(4503.96)
    assert vec["intrusiveness"] == pytest.approx(0.15)


def test_unscaling_reproduces_the_standardised_fit_exactly() -> None:
    """The fold-back the artifact depends on.

    ``b + Σ wⱼ(xⱼ−μⱼ)/σⱼ`` and ``(b − Σ wⱼμⱼ/σⱼ) + Σ (wⱼ/σⱼ)xⱼ`` are the same
    line. If they were not, every artifact would score a systematically
    shifted probability and nothing would report an error.
    """
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "train_treatment_models",
        Path(__file__).resolve().parent.parent / "scripts" / "train_treatment_models.py",
    )
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)

    mu = [20.0, 600.0]
    scales = [8.0, 120.0]
    w, b = [0.6, -0.4], 0.2
    raw_w, raw_b = trainer._unscale(w, b, mu, scales)

    for x in ([12.0, 540.0], [45.0, 720.0], [20.0, 600.0]):
        standardised = b + sum(
            wj * (xi - m) / sd for wj, xi, m, sd in zip(w, x, mu, scales)
        )
        raw = raw_b + sum(c * xi for c, xi in zip(raw_w, x))
        assert raw == pytest.approx(standardised)


# ---------------------------------------------------------------------------
# Delivery receipts
# ---------------------------------------------------------------------------


def test_a_replayed_webhook_is_not_a_second_observation(db_tx) -> None:
    """Meta and Twilio both retry callbacks, so a replay is normal traffic.

    Counted twice, a retried "read" tells the reach model that borrowers who
    happen to sit behind a flaky webhook are unusually reachable.
    """
    import delivery_receipts
    from sqlalchemy import text

    row = db_tx.execute(
        text("SELECT id, tenant_id FROM customers ORDER BY id LIMIT 1")
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer")

    kwargs = dict(
        tenant_id=row["tenant_id"],
        customer_id=row["id"],
        channel="sms",
        provider="twilio",
        provider_ref="SM-probe-1",
        state="delivered",
    )
    first = delivery_receipts.record(db_tx, **kwargs)
    second = delivery_receipts.record(db_tx, **kwargs)
    assert first is not None
    assert second is None, "a replayed receipt was recorded twice"

    n = db_tx.execute(
        text(
            "SELECT count(*) FROM contact_delivery_events"
            " WHERE provider_ref = 'SM-probe-1'"
        )
    ).scalar()
    assert n == 1


def test_a_lifecycle_is_kept_as_transitions_not_a_status(db_tx) -> None:
    """``messages.delivery_status`` holds the current state, so a message that
    went sent → delivered → read leaves only "read" — and the moment it was
    read, which is the fact that separates a borrower reachable at 09:00 from
    one reachable at all, is overwritten and gone."""
    import delivery_receipts
    from sqlalchemy import text

    row = db_tx.execute(
        text("SELECT id, tenant_id FROM customers ORDER BY id LIMIT 1")
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer")

    for state in ("sent", "delivered", "read"):
        delivery_receipts.record(
            db_tx,
            tenant_id=row["tenant_id"],
            customer_id=row["id"],
            channel="whatsapp",
            provider="meta",
            provider_ref="wamid-probe",
            state=state,
        )
    states = db_tx.execute(
        text(
            "SELECT state FROM contact_delivery_events"
            " WHERE provider_ref = 'wamid-probe' ORDER BY occurred_at"
        )
    ).scalars().all()
    assert set(states) == {"sent", "delivered", "read"}


def test_twilio_vocabulary_is_normalised_at_the_edge() -> None:
    """Twilio and Meta describe one lifecycle in different words. Normalising
    at the boundary means the reach trainer reads one alphabet."""
    import delivery_receipts

    assert delivery_receipts.normalise_twilio("accepted") == "queued"
    assert delivery_receipts.normalise_twilio("sending") == "sent"
    assert delivery_receipts.normalise_twilio("delivered") == "delivered"
    # Kept apart from 'failed' on purpose: only one of them says the number is
    # wrong, and that is the one that should stop us dialling it again.
    assert delivery_receipts.normalise_twilio("undelivered") == "undelivered"
    assert delivery_receipts.normalise_twilio("nonsense") is None


def test_a_receipt_that_cannot_be_written_does_not_fail_the_webhook() -> None:
    """A provider webhook that errors is a provider that retries, and at scale
    that is how a delivery-status endpoint becomes an outage. The reach model
    would rather have a gap than the system have a page."""
    import delivery_receipts

    class Exploding:
        def execute(self, *_a, **_k):
            raise RuntimeError("database is on fire")

    assert (
        delivery_receipts.record(
            Exploding(),
            tenant_id="t",
            customer_id="c",
            channel="sms",
            provider="twilio",
            state="delivered",
        )
        is None
    )


# ---------------------------------------------------------------------------
# The counterfactual's negative class
# ---------------------------------------------------------------------------


def test_deliberate_withholding_is_labelled_and_shadow_silence_is_not() -> None:
    """The distinction that makes a control arm measurable.

    A control-arm decision withheld treatment by design, so "they did not pay"
    answers the question the arm exists to ask. A shadow decision that went
    unenacted answers nothing — the borrower may have been contacted by the
    dialler, an agent, or a reminder the engine never saw.
    """
    from agent_core.treatment import followthrough

    assert followthrough._withheld_on_purpose({"variant": "null_treatment"}) is True
    assert followthrough._withheld_on_purpose({"variant": "control"}) is False
    assert followthrough._withheld_on_purpose({"variant": None}) is False


def test_unresolved_is_a_recordable_outcome_and_does_not_close_a_case() -> None:
    """Without it a control arm holds nothing but positives, every cure rate it
    reports is 1.0, and the estimated treatment effect comes out large and
    negative — a finding about the labeller rather than about collections.

    Caught by the uplift trainer reporting a control cure rate of exactly 1.000.
    """
    from agent_core.treatment import decisions, followthrough

    assert "unresolved" in decisions.OUTCOMES
    assert "unresolved" in followthrough.UNRESOLVED
    assert "unresolved" not in followthrough.RESOLVING


def test_a_payment_is_not_evidence_that_the_phone_was_answered() -> None:
    """The reach label's contamination, pinned.

    A borrower who was going to pay anyway pays whether the call connected or
    not, so counting ``paid`` as a reach positive pours the entire self-cure
    population into the label and the model learns to predict payment instead.
    Measured: AUC 0.504 with ``paid`` included, on a book with real reach
    heterogeneity in it.
    """
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "train_treatment_models",
        Path(__file__).resolve().parent.parent / "scripts" / "train_treatment_models.py",
    )
    trainer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trainer)

    assert "paid" not in trainer.REACHED
    assert "paid" not in trainer.NOT_REACHED
    assert {"reached", "ptp", "refused"} == set(trainer.REACHED)

    row = {"enacted": True, "chosen_channel": "voice", "outcome": "paid"}
    assert trainer._label_reach(row) is None
