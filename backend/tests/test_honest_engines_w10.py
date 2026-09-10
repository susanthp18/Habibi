"""W10a — the gate that refuses, and the money path it will one day price.

W10's exit criterion has three parts and two of them need a fitted model:
*"each promoted through the full gate, hazard first; the EV identity test in
CI; serving parity at decision-flip ≤ 0.5% per action family."* Measured
read-only against ``collections`` on 2026-09-10, a fit is not attemptable:

    treatment_decisions mode='live'   278 rows across 21 customers, 18 days
    reach_outcome IS NOT NULL           0
    cure_outcome IS NOT NULL            0
    label_mature_at <= now()            0

against §8.10 rung 1's ≥150 treated customers, ≥200 control customers and ≥40
clusters per arm, and §8.10's *"Day 91 is the earliest a fitted model may
serve"*. So this wave builds the gate that has to say so, in numbers, rather
than a model that would pass a gate which cannot evaluate it.

The identity test lives in ``tests/test_ev_identity.py``. What is here is the
refusals — Gate 2's artifact binding, Gate 13's provenance, the finite-value
gate, Gate 3's out-of-time customer-disjoint split — and the cost term, which
stops being nine constants the engine both plans against and scores itself
against.
"""

from __future__ import annotations

import json
import math
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from agent_core.treatment import evaluation_seal, registry, schema_ready
from agent_core.treatment import models as treatment_models
from agent_core.treatment.features import SCHEMA_VERSION

KEY = b"w10a-test-key"


@pytest.fixture(autouse=True)
def _reset():
    schema_ready.reset_cache()
    treatment_models._reset_warnings()
    yield
    schema_ready.reset_cache()
    treatment_models._reset_warnings()


def _artifact(tmp_path: Path, **body) -> Path:
    raw = {
        "name": "treatment_uplift",
        "target": "uplift",
        "type": "logistic",
        "version": "w10a-test",
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "featureNames": ["dpd"],
        "coefficients": [0.0],
        "intercept": 0.0,
        "means": {"dpd": 20.0},
        "controlArm": "null_treatment",
        "controlN": 1000,
        "controlCoefficients": [0.0],
        "controlIntercept": 0.0,
        "vectorVersion": treatment_models.VECTOR_VERSION,
        "featureSchemaVersion": SCHEMA_VERSION,
        "corpus": "live",
    }
    raw.update(body)
    path = tmp_path / f"uplift-{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Gate 13 — an artifact that names no corpus
# ---------------------------------------------------------------------------


def test_an_artifact_with_no_corpus_field_is_refused(tmp_path) -> None:
    """`[artifact-corpus-defaults-to-live]`, closed.

    ``corpus=str(raw.get("corpus") or "live")`` meant the one artifact nobody
    had bothered to stamp was also the one the simulated-corpus check could
    never catch. Silence read as the strongest possible claim.
    """
    path = _artifact(tmp_path)
    body = json.loads(path.read_text(encoding="utf-8"))
    del body["corpus"]
    path.write_text(json.dumps(body), encoding="utf-8")

    assert treatment_models.load_artifact(path, expect_target="uplift") is None


def test_an_artifact_naming_an_unknown_corpus_is_refused(tmp_path) -> None:
    """Not an open set. The field's whole value is that a check can act on it,
    and a corpus nobody recognises is a claim nothing can check."""
    path = _artifact(tmp_path, corpus="staging")
    assert treatment_models.load_artifact(path, expect_target="uplift") is None


def test_a_live_stamp_still_loads(tmp_path) -> None:
    """The gate has to let the correct thing through, or it is a deletion."""
    path = _artifact(tmp_path)
    assert treatment_models.load_artifact(path, expect_target="uplift") is not None


# ---------------------------------------------------------------------------
# The finite-value gate — WP-R's unmet exit criterion
# ---------------------------------------------------------------------------


def test_a_nan_does_not_propagate_as_a_nan_it_becomes_a_confident_zero() -> None:
    """Why the gate exists, demonstrated on the tree's own sigmoid.

    ``nan >= 0`` is False, so ``_sigmoid`` takes its negative branch;
    ``max(-60.0, nan)`` returns -60.0 because the comparison is also False; and
    the prediction comes back as ~8.8e-27. Not a crash, not a NaN — a confident
    zero. A NaN uplift coefficient therefore drives every EV to −cost and the
    engine falls silent, with nothing in any log saying why.
    """
    out = treatment_models._sigmoid(float("nan"))
    assert math.isfinite(out)
    assert out < 1e-20


def test_json_parses_the_literals_that_make_this_reachable() -> None:
    """The path is real end to end: a trainer that divides by a zero-variance
    column writes ``NaN`` into JSON, and ``json.loads`` reads it back."""
    parsed = json.loads('{"coefficients": [NaN, Infinity]}')
    assert not any(math.isfinite(c) for c in parsed["coefficients"])


@pytest.mark.parametrize(
    "body,where",
    [
        ({"coefficients": [float("nan")]}, "coefficients[0] (dpd)"),
        ({"coefficients": [float("inf")]}, "coefficients[0] (dpd)"),
        ({"intercept": float("nan")}, "intercept"),
        ({"controlIntercept": float("inf")}, "controlIntercept"),
        ({"calibration": {"a": float("nan"), "b": 0.0}}, "calibration.a"),
        ({"means": {"dpd": float("nan")}}, "means.dpd"),
    ],
)
def test_non_finite_values_are_refused_and_named(tmp_path, body, where) -> None:
    path = tmp_path / f"nan-{uuid.uuid4().hex[:8]}.json"
    raw = json.loads(_artifact(tmp_path).read_text(encoding="utf-8"))
    raw.update(body)
    # ``allow_nan=True`` deliberately: this is exactly what a trainer without
    # the write-side gate produces, and the point is that it loads today.
    path.write_text(json.dumps(raw, allow_nan=True), encoding="utf-8")

    artifact = treatment_models.load_artifact(path, expect_target="uplift")
    assert artifact is None

    # And the objection names the field, so somebody is sent to the column
    # rather than to a thousand-line trainer.
    permissive = treatment_models.ModelArtifact(
        name="x",
        version="x",
        kind="logistic",
        target="uplift",
        feature_names=("dpd",),
        coefficients=tuple(raw["coefficients"]),
        intercept=float(raw["intercept"]),
        means={k: float(v) for k, v in raw["means"].items()},
        calibration_a=float(raw["calibration"]["a"]) if "calibration" in raw else 1.0,
        calibration_b=float(raw["calibration"]["b"]) if "calibration" in raw else 0.0,
        control_intercept=float(raw.get("controlIntercept") or 0.0),
    )
    assert where in permissive.non_finite()


def test_a_clean_artifact_reports_nothing_non_finite(tmp_path) -> None:
    artifact = treatment_models.load_artifact(
        _artifact(tmp_path), expect_target="uplift"
    )
    assert artifact is not None
    assert artifact.non_finite() == []


# ---------------------------------------------------------------------------
# Gate 2 — the evaluation is bound to the artifact it evaluated
# ---------------------------------------------------------------------------


def _evaluation(sha: str, **over) -> dict:
    body = {"lift": 0.04, "trustworthy": True, "ate": 0.18, "artifact_sha": sha}
    body.update(over)
    return evaluation_seal.sealed(body, key=KEY)


def test_a_sealed_evaluation_binds_to_its_own_artifact(tmp_path) -> None:
    path = _artifact(tmp_path)
    sha = registry._sha(path)
    assert evaluation_seal.objections(_evaluation(sha), artifact_sha=sha, key=KEY) == []


def test_an_evaluation_of_a_different_artifact_is_refused(tmp_path) -> None:
    """The failure this actually prevents is not forgery.

    It is an engineer who evaluates three challengers, promotes the wrong path,
    and gets a green gate: the lift is real, the artifact is not the one it
    describes, and every downstream record says the model was validated.
    """
    mine = _artifact(tmp_path)
    theirs = _artifact(tmp_path, version="the-other-one")
    evaluation = _evaluation(registry._sha(theirs))

    objections = evaluation_seal.objections(
        evaluation, artifact_sha=registry._sha(mine), key=KEY
    )
    assert any("was computed against artifact" in o for o in objections)


def test_an_evaluation_naming_no_artifact_is_refused(tmp_path) -> None:
    """What shipped: any JSON with a ``lift`` key promoted any artifact."""
    path = _artifact(tmp_path)
    bare = evaluation_seal.sealed({"lift": 0.04, "trustworthy": True}, key=KEY)
    objections = evaluation_seal.objections(
        bare, artifact_sha=registry._sha(path), key=KEY
    )
    assert any("carries no artifact_sha" in o for o in objections)


def test_editing_the_lift_after_sealing_breaks_the_seal(tmp_path) -> None:
    path = _artifact(tmp_path)
    sha = registry._sha(path)
    evaluation = _evaluation(sha)
    evaluation["lift"] = 0.9

    objections = evaluation_seal.objections(evaluation, artifact_sha=sha, key=KEY)
    assert any("does not verify" in o for o in objections)


def test_the_seal_is_order_independent(tmp_path) -> None:
    """A report round-tripped through a dict, a file or a queue reorders its
    keys, and that must not read as tampering."""
    sha = registry._sha(_artifact(tmp_path))
    evaluation = _evaluation(sha)
    shuffled = dict(reversed(list(evaluation.items())))
    assert evaluation_seal.verify(shuffled, key=KEY)


def test_a_nan_lift_cannot_be_sealed(tmp_path) -> None:
    """An evaluation carrying a NaN is precisely the artifact the finite-value
    gate refuses, and a seal computed over one would launder it."""
    with pytest.raises(evaluation_seal.Unsealable):
        evaluation_seal.seal({"lift": float("nan")}, key=KEY)


def test_the_key_is_required_outside_a_non_production_environment(monkeypatch) -> None:
    """The lesson ``agent_core/skills/sign.py`` already learned: falling back to
    a built-in development key means an unconfigured production deploy verifies
    against a public constant."""
    monkeypatch.delenv(evaluation_seal.KEY_ENV, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(RuntimeError):
        evaluation_seal.evaluation_key()

    monkeypatch.setenv("APP_ENV", "test")
    assert evaluation_seal.evaluation_key()


# ---------------------------------------------------------------------------
# An unevaluable gate is a refusal (§8.12)
# ---------------------------------------------------------------------------


def test_the_corpus_gate_refuses_this_corpus_and_says_by_how_much(db_tx) -> None:
    """Where ``check`` used to return ``[]`` for a clean file.

    The numbers are the useful part. "Refused" tells an operator to try again
    later; "0 mature cases, 21 distinct customers" tells them the wait is
    months and that the labeller, not the trainer, is what is next.
    """
    objections = registry.corpus_objections(db_tx, tenant_id="hdfc.retail")
    assert objections, "a corpus with no mature labels must not pass silently"
    assert any("primary horizon" in o for o in objections)
    assert any("treated customers against a floor" in o for o in objections)


def test_no_connection_is_a_refusal_not_a_pass() -> None:
    """§8.12: 'No artefact is promoted while any gate cannot be evaluated.'"""
    objections = registry.corpus_objections(None, tenant_id="hdfc.retail")
    assert any("could not be evaluated" in o for o in objections)


def test_a_failing_corpus_read_does_not_poison_the_caller(db_tx) -> None:
    """W0's savepoint rule, on the gate.

    W8a shipped a read of a not-yet-applied table that aborted the *caller's*
    transaction and took seven unrelated tests down as ``InFailedSqlTransaction``.
    Every new read belongs inside ``begin_nested``; this proves it is.
    """
    objections = registry.corpus_objections(db_tx, tenant_id="no-such-tenant")
    assert objections
    # The connection is still usable, which is the entire assertion.
    assert db_tx.execute(text("SELECT 1")).scalar() == 1


# ---------------------------------------------------------------------------
# Gate 3 — out of time, and disjoint by borrower
# ---------------------------------------------------------------------------


def _sample(customer: str, day: int, *, mature: bool = True):
    from scripts.train_treatment_models import Sample

    at = datetime(2026, 6, 1, tzinfo=timezone.utc) + timedelta(days=day)
    return Sample(
        vec={"dpd": float(day)},
        label=day % 2,
        customer_id=customer,
        at=at,
        mature_at=(at + timedelta(days=1)) if mature else None,
    )


def test_no_borrower_appears_on_both_sides_of_the_split() -> None:
    """`[train-holdout-split-is-by-row-not-by-borrower]`.

    A row shuffle grades the model on borrowers whose almost-identical vectors
    it memorised in training, and every promotion decision reading that AUC
    compares optimistic estimates.
    """
    samples = [
        _sample(f"cust-{i % 10}", day) for i, day in enumerate(range(60))
    ]
    from scripts.train_treatment_models import holdout_split

    train, test, report = holdout_split(samples, fraction=0.25)
    train_customers = {samples[i].customer_id for i in train}
    test_customers = {samples[i].customer_id for i in test}

    assert train and test
    assert not (train_customers & test_customers)
    assert report.train_customers == len(train_customers)
    assert report.test_customers == len(test_customers)


def test_the_holdout_is_the_recent_end_of_the_corpus() -> None:
    """`[random-split-not-out-of-time]`. The policy generating the log changes
    over time — variant mix, scorer, greediness, config — so a random split
    scores the model on a period whose regime it has already seen."""
    samples = [_sample(f"cust-{day}", day) for day in range(40)]
    from scripts.train_treatment_models import holdout_split

    train, test, _ = holdout_split(samples, fraction=0.25)
    assert max(samples[i].at for i in train) < min(samples[i].at for i in test)


def test_immature_rows_are_dropped_and_counted() -> None:
    """A decision whose window is still open contributes 'has not paid yet',
    and the immature tail is always the newest slice — so training on it
    teaches the model that recent means unsuccessful."""
    samples = [_sample(f"cust-{day}", day) for day in range(20)]
    samples += [_sample(f"cust-new-{day}", 100 + day, mature=False) for day in range(8)]
    from scripts.train_treatment_models import holdout_split

    train, test, report = holdout_split(samples, fraction=0.25)
    assert report.immature == 8
    assert len(train) + len(test) == 20
    assert all(samples[i].mature_at is not None for i in train + test)


def test_a_corpus_with_no_mature_rows_splits_into_nothing() -> None:
    """Today's corpus, exactly. The trainer's caller turns this into a refusal
    with the numbers attached rather than fitting on eight rows."""
    samples = [_sample(f"cust-{day}", day, mature=False) for day in range(30)]
    from scripts.train_treatment_models import holdout_split

    train, test, report = holdout_split(samples, fraction=0.25)
    assert (train, test) == ([], [])
    assert report.immature == 30


def test_one_borrower_cannot_take_the_whole_corpus_into_the_holdout() -> None:
    """A holdout containing every customer is not a holdout. With a single
    borrower there is no honest split at all, and saying so beats returning
    one."""
    samples = [_sample("cust-only", day) for day in range(30)]
    from scripts.train_treatment_models import holdout_split

    train, test, _ = holdout_split(samples, fraction=0.25)
    assert not test
    assert len(train) == 30


def test_the_split_needs_no_seed_to_be_reproducible() -> None:
    """An ordering is not a draw. A seed here would be an invitation to
    re-roll a holdout somebody did not like."""
    samples = [_sample(f"cust-{i % 7}", i) for i in range(50)]
    from scripts.train_treatment_models import holdout_split

    assert holdout_split(samples, fraction=0.3)[:2] == holdout_split(
        samples, fraction=0.3
    )[:2]


# ---------------------------------------------------------------------------
# The money path
# ---------------------------------------------------------------------------


def _require_w10(db_tx) -> None:
    """The column is W6's (sql/25, migration 0113), not a new one.

    It is absent from the running database because 0113 is deliberately
    unapplied there, which is exactly the condition ``observed_costs`` probes
    for — so this skip is the same fact from the test's side.
    """
    if not schema_ready.w10_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("usage_events.decision_id absent (migration 0113)")
        pytest.skip("usage_events.decision_id absent (migration 0113 unapplied)")


def test_the_decision_id_survives_the_hop_into_usage_events(db_tx) -> None:
    """Decision → metered spend, proven rather than assumed.

    Every part of this was already built and none of it was ever exercised end
    to end: W6 added the column (``sql/25_decision_substrate.sql``),
    ``usage_meter`` carries a ``_current_decision`` context variable, an
    ``attribute_to(..., decision_id=...)`` scope, ``current_decision_id()``,
    the key on every buffered event and the conditional SQL in the flusher, and
    ``enact.py`` opens the scope with the decision's own id.

    What was missing is that nothing read the result: ``costs.for_action``
    returned a constant, so the engine planned against nine hand-set numbers
    and scored itself against the same nine, and could not notice that any of
    them was wrong [CRITIC G1]. This is the assertion that the hop works, so
    the reading half has something to stand on.
    """
    _require_w10(db_tx)
    import usage_meter

    tenant = db_tx.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    customer = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t LIMIT 1"), {"t": tenant}
    ).scalar()
    service = db_tx.execute(text("SELECT id FROM billing_services LIMIT 1")).scalar()
    if not (tenant and customer and service):
        pytest.skip("no seed identity")

    # Seeded rather than borrowed from whatever the corpus happens to hold, so
    # the hop is exercised on every database this runs against. The previous
    # shape skipped on the scratch DB (no decisions) and on a fresh install
    # (same), which is to say everywhere.
    decision_id = f"td-w10a-{uuid.uuid4().hex[:12]}"
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions (
              id, tenant_id, customer_id, trigger_kind, mode,
              recommender, recommender_version, feature_schema_version,
              chosen_action
            ) VALUES (
              :id, :tenant, :customer, 'dpd_tick', 'live',
              'ev', '1.0.0', :schema, 'voice_bot'
            )
            """
        ),
        {
            "id": decision_id,
            "tenant": tenant,
            "customer": customer,
            "schema": SCHEMA_VERSION,
        },
    )

    with usage_meter.attribute_to(None, decision_id=decision_id):
        assert usage_meter.current_decision_id() == decision_id
    # The scope restores on exit, so attribution cannot leak into the next job
    # on the same thread.
    assert usage_meter.current_decision_id() is None

    db_tx.execute(
        text(
            """
            INSERT INTO usage_events
              (id, tenant_id, environment, service_id, units, cost_inr, decision_id)
            VALUES (:id, :tenant, 'sandbox', :service, 1, 1.25, :decision)
            """
        ),
        {
            "id": f"ue-{uuid.uuid4().hex[:16]}",
            "tenant": tenant,
            "service": service,
            "decision": decision_id,
        },
    )

    spend = db_tx.execute(
        text(
            """
            SELECT sum(u.cost_inr)
              FROM treatment_decisions d
              JOIN usage_events u ON u.decision_id = d.id
             WHERE d.id = :id
            """
        ),
        {"id": decision_id},
    ).scalar()
    assert float(spend) == pytest.approx(1.25)


def test_an_unmeasured_action_keeps_its_constant_and_says_so() -> None:
    """§8.2: 'the planning constant survives only as a documented fallback'.

    Never a blend of the two. An average of a measurement and a guess is a
    guess with a smaller error bar drawn on it.
    """
    from agent_core.treatment.config import Costs

    priced = Costs(
        sms=0.18,
        whatsapp=0.42,
        voice_bot=7.50,
        human_call=45.0,
        field_visit=1150.0,
        legal_notice=2500.0,
        represent_mandate=0.50,
        emi_date_change=15.0,
        self_service_plan=8.0,
        observed={"voice_bot": 3.10},
    )
    assert priced.for_action("voice_bot") == pytest.approx(3.10)
    assert priced.measured("voice_bot") is True
    assert priced.for_action("field_visit") == pytest.approx(1150.0)
    assert priced.measured("field_visit") is False


def test_an_action_this_price_book_does_not_carry_still_costs_infinity() -> None:
    """The pre-existing refusal, unchanged by the observed-cost path.

    ``ev = gross − cost − fatigue``, so a missing price used to make the
    unpriced action the most profitable thing the engine could do.
    """
    from agent_core.treatment.config import Costs

    priced = Costs(
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
    assert priced.for_action("device_lock") == math.inf


def test_observed_costs_are_empty_without_the_column(db_tx) -> None:
    """The whole read is gated and savepoint-guarded, so a database without
    0113 prices from constants rather than failing — and does not poison the
    caller's transaction on the way."""
    from agent_core.treatment import config

    out = config.observed_costs(db_tx, tenant_id="hdfc.retail")
    assert isinstance(out, dict)
    assert db_tx.execute(text("SELECT 1")).scalar() == 1


def test_a_measured_cost_needs_enough_attempts_to_be_a_unit_cost(db_tx) -> None:
    """A mean over three calls is not a unit cost, it is three calls — and this
    number multiplies rupees inside an EV, so a noisy one reorders channels."""
    from agent_core.treatment import config

    assert config.MIN_OBSERVED_ATTEMPTS >= 20
    assert config.OBSERVED_COST_WINDOW_DAYS == 90
    # On this corpus there is nothing to measure, which is the correct outcome
    # rather than a degraded one: 0 of 278 live decisions carry an interaction,
    # and the 20 enacted are WhatsApp sends whose cost is a Meta conversation
    # price that appears nowhere in usage_events.
    assert config.observed_costs(db_tx, tenant_id="hdfc.retail") == {}


def test_a_nan_spend_does_not_become_a_nan_unit_cost(db_tx) -> None:
    """PostgreSQL ``numeric`` admits NaN, and ``NaN <= 0`` is false.

    So the attempts/spend guard alone would let a single poisoned ``cost_inr``
    through as the measured unit cost of an action, and ``ev = gross − cost``
    would be NaN for every candidate of that family — the same silent failure
    as a NaN coefficient, arriving from the ledger instead of the artifact. The
    finite check belongs on the read side too, not only on artifact load.
    """
    _require_w10(db_tx)
    from agent_core.treatment import config

    assert db_tx.execute(text("SELECT ('NaN'::numeric <= 0)")).scalar() is False

    tenant = db_tx.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    customer = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t LIMIT 1"), {"t": tenant}
    ).scalar()
    service = db_tx.execute(text("SELECT id FROM billing_services LIMIT 1")).scalar()
    if not (tenant and customer and service):
        pytest.skip("no seed identity")

    tag = uuid.uuid4().hex[:8]
    for i in range(config.MIN_OBSERVED_ATTEMPTS):
        decision_id = f"td-nan-{tag}-{i:02d}"
        db_tx.execute(
            text(
                """
                INSERT INTO treatment_decisions (
                  id, tenant_id, customer_id, trigger_kind, mode,
                  recommender, recommender_version, feature_schema_version,
                  chosen_action, enacted
                ) VALUES (
                  :id, :tenant, :customer, 'dpd_tick', 'live',
                  'ev', '1.0.0', :schema, 'voice_bot', true
                )
                """
            ),
            {
                "id": decision_id,
                "tenant": tenant,
                "customer": customer,
                "schema": SCHEMA_VERSION,
            },
        )
        db_tx.execute(
            text(
                """
                INSERT INTO usage_events
                  (id, tenant_id, environment, service_id, units, cost_inr, decision_id)
                VALUES (:id, :tenant, 'sandbox', :service, 1, :cost, :decision)
                """
            ),
            {
                "id": f"ue-nan-{tag}-{i:02d}",
                "tenant": tenant,
                "service": service,
                # One poisoned row is enough: sum() over a NaN is NaN.
                "cost": float("nan") if i == 0 else 7.5,
                "decision": decision_id,
            },
        )

    observed = config.observed_costs(db_tx, tenant_id=str(tenant))
    assert "voice_bot" not in observed, observed
    # And the fallback the refusal hands back is a real number.
    assert math.isfinite(config.costs(conn=db_tx, tenant_id=str(tenant)).for_action("voice_bot"))
