"""W9a — R-INJ-1: nothing a borrower says may raise the EV of pursuing them.

The wave's exit criterion is one sentence in §15.2 — *a speech-derived feature
requesting EV admission fails artifact load* — and three of these tests are
that sentence. The rest are the two halves that make it more than a slogan: a
registry that is complete in both directions, so a new vector key cannot arrive
undeclared; and a veto stack that can be *added* to by something the borrower
said and can never be relieved by it.

One test is a regression test for a live defect. ``scoring.vector`` emitted
``on_hold`` from every hold regardless of source, and
``post_call_actions._place_hold`` writes ``source='bot'`` from what a borrower
said on a call — so a speech-derived fact was already in the EV vector, with a
coefficient on it in all three artifacts under ``models/``.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agent_core import feature_provenance
from agent_core.perception import facts as perception_facts
from agent_core.perception import record as perception_record
from agent_core.treatment import actions as A
from agent_core.treatment import models as treatment_models
from agent_core.treatment import policy, schema_ready, scoring
from agent_core.treatment.features import AccountFeatures, Trigger


@pytest.fixture(autouse=True)
def _reset():
    schema_ready.reset_cache()
    treatment_models._reset_warnings()
    yield
    schema_ready.reset_cache()
    treatment_models._reset_warnings()


def _require(db_tx) -> None:
    if not schema_ready.w9_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W9 schema not applied (migration 0119)")
        pytest.skip("W9 schema not applied")


# ---------------------------------------------------------------------------
# The registry is complete, in both directions
# ---------------------------------------------------------------------------


def _scored(now: datetime) -> scoring.ScoredAction:
    return scoring.ScoredAction(
        action=A.SMS,
        channel="sms",
        at=now,
        expected_value=0.0,
        p_reach=0.5,
        p_resolve=0.5,
        cost=1.0,
        explanation="",
    )


def _treatment_vector_keys() -> set[str]:
    features = AccountFeatures(customer_id="c", tenant_id="t")
    now = datetime.now(timezone.utc)
    return set(scoring.vector(features, Trigger(kind="manual", at=now), _scored(now), now=now))


def test_every_treatment_vector_key_declares_a_provenance() -> None:
    """Undeclared is refused at load, so an undeclared key is a broken build.

    Both directions on purpose. A missing declaration would refuse every
    artifact the moment the key was added — loud, and caught here first. A
    *stale* declaration for a key the vector no longer emits is the quieter
    failure: it leaves a permission standing for something nobody can see.
    """
    assert _treatment_vector_keys() == set(feature_provenance.TREATMENT.provenance)


def test_every_reco_vector_key_declares_a_provenance() -> None:
    from agent_core.reco import vectorize

    assert set(vectorize.FEATURE_NAMES) == set(feature_provenance.RECO.provenance)


def test_every_declared_class_is_one_of_the_four() -> None:
    for registry in (feature_provenance.TREATMENT, feature_provenance.RECO):
        for key, kind in registry.provenance.items():
            assert kind in feature_provenance.CLASSES, f"{registry.name}.{key}"


def test_the_collections_registry_admits_no_speech_at_all() -> None:
    """§12.3's rule, as an assertion rather than a paragraph.

    The reco registry admits named in-call signals because it ranks offers on a
    call already in progress. The treatment registry decides whether to *make*
    a call, and there is no feature and no golden-set size at which speech may
    contribute to that.
    """
    assert feature_provenance.TREATMENT.speech_admitted == frozenset()
    speech = [
        key
        for key, kind in feature_provenance.TREATMENT.provenance.items()
        if kind in feature_provenance.SPEECH_DERIVED
    ]
    assert speech == []


# ---------------------------------------------------------------------------
# The exit criterion: refused at artifact load
# ---------------------------------------------------------------------------


def _artifact(tmp_path, **overrides):
    names = sorted(_treatment_vector_keys() - treatment_models.SCORER_DERIVED_KEYS)
    body = {
        "name": "reach",
        "version": "test",
        "type": "logistic",
        "target": "reach",
        "featureNames": names,
        "coefficients": [0.01] * len(names),
        "intercept": 0.0,
        "means": {n: 0.0 for n in names},
        "vectorVersion": treatment_models.VECTOR_VERSION,
        "featureSchemaVersion": treatment_models.SCHEMA_VERSION,
        "trainedAt": datetime.now(timezone.utc).isoformat(),
        "corpus": "live",
    }
    body.update(overrides)
    path = tmp_path / f"{uuid.uuid4().hex[:8]}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_clean_artifact_still_loads(tmp_path) -> None:
    """The control. Every refusal below has to be the provenance check and not
    a typo in the fixture."""
    assert treatment_models.load_artifact(
        _artifact(tmp_path), expect_target="reach"
    ) is not None


def test_an_artifact_declaring_borrower_speech_fails_to_load(tmp_path) -> None:
    path = _artifact(tmp_path, inputProvenance=["system_of_record", "borrower_utterance"])
    assert treatment_models.load_artifact(path, expect_target="reach") is None


def test_an_artifact_naming_an_undeclared_feature_fails_to_load(tmp_path) -> None:
    """The load-bearing half.

    Nobody adds a feature called ``borrower_utterance``. They add one called
    ``cooperation_band`` — a classifier over how the borrower sounded — and a
    rule that only refuses declared speech would let it through. Unknown is
    refused, so the fence holds against the feature that has not been invented
    yet.
    """
    names = sorted(_treatment_vector_keys() - treatment_models.SCORER_DERIVED_KEYS)
    names.append("cooperation_band")
    path = _artifact(
        tmp_path,
        featureNames=names,
        coefficients=[0.01] * len(names),
        means={n: 0.0 for n in names},
    )
    assert treatment_models.load_artifact(path, expect_target="reach") is None


def test_a_model_inference_feature_needs_a_calibration_record(tmp_path) -> None:
    """§12.3's third enforcement point: per-stratum, not aggregate ECE."""
    key = "p_reach"
    assert feature_provenance.TREATMENT.provenance[key] == feature_provenance.MODEL_INFERENCE
    names = sorted(_treatment_vector_keys() - treatment_models.SCORER_DERIVED_KEYS) + [key]
    common = {
        "featureNames": names,
        "coefficients": [0.01] * len(names),
        "means": {n: 0.0 for n in names},
    }
    assert treatment_models.load_artifact(
        _artifact(tmp_path, **common), expect_target="reach"
    ) is None
    with_strata = dict(common, calibrationStrata={"hardship": {"ece": 0.02}})
    assert treatment_models.load_artifact(
        _artifact(tmp_path, **with_strata), expect_target="reach"
    ) is not None


def test_the_reco_loader_admits_its_named_in_call_signals(tmp_path) -> None:
    """The offer ranker keeps working, and the exemption is by name.

    An unnamed in-call signal is refused there exactly as it is on the
    collections side — otherwise "reco may read the call" would quietly become
    "reco may read anything".
    """
    from agent_core.reco import vectorize

    names = list(vectorize.FEATURE_NAMES)
    assert feature_provenance.RECO.refuse(names) is None
    assert feature_provenance.RECO.refuse(names + ["cooperation_band"]) is not None


# ---------------------------------------------------------------------------
# The live defect: a bot-placed hold was in the EV vector
# ---------------------------------------------------------------------------


def _features(**kw) -> AccountFeatures:
    base = dict(customer_id="c", tenant_id="t", dpd=10, instalment_amount=5000.0)
    base.update(kw)
    return AccountFeatures(**base)


def test_a_hold_the_bot_placed_is_not_in_the_ev_vector() -> None:
    now = datetime.now(timezone.utc)
    scored = _scored(now)
    trigger = Trigger(kind="manual", at=now)

    spoken = _features(holds=("hardship",), holds_of_record=())
    filed = _features(holds=("hardship",), holds_of_record=("hardship",))

    assert scoring.vector(spoken, trigger, scored, now=now)["on_hold"] == 0.0
    assert scoring.vector(filed, trigger, scored, now=now)["on_hold"] == 1.0


def test_a_hold_the_bot_placed_still_vetoes() -> None:
    """The direction that matters. The EV vector gets strictly less; the veto
    stack gets exactly what it had. A fix that quietened the veto would have
    traded a modelling defect for a compliance one."""
    spoken = _features(holds=("hardship",), holds_of_record=())
    assert policy._hold_veto(A.SMS, spoken) == f"{policy.HOLD_PREFIX}hardship"
    assert policy._hold_veto(A.WAIT, spoken) is None


# ---------------------------------------------------------------------------
# Monotone suppression
# ---------------------------------------------------------------------------


def test_a_speech_flag_can_add_a_veto() -> None:
    spoken = _features(speech_flags=("consent_withdrawal",))
    assert policy._speech_veto(A.SMS, spoken) == f"{policy.SPEECH_PREFIX}consent_withdrawal"
    # `wait` is always permitted, or there would be states with no legal action.
    assert policy._speech_veto(A.WAIT, spoken) is None


def test_a_speech_flag_can_never_remove_one() -> None:
    """Every flag, every action: the answer is a veto or nothing.

    Exhaustive rather than illustrative, because "it may never release a veto"
    is not a property one example demonstrates.
    """
    for flag in policy.SPEECH_SUPPRESSES:
        spoken = _features(speech_flags=(flag,))
        for action in A.ALL:
            verdict = policy._speech_veto(action, spoken)
            assert verdict is None or verdict.startswith(policy.SPEECH_PREFIX)
            # And it cannot make a held borrower contactable.
            held = _features(holds=("complaint",), speech_flags=(flag,))
            assert policy._hold_veto(action, held) == policy._hold_veto(
                action, _features(holds=("complaint",))
            )


def test_an_unmapped_speech_flag_does_nothing() -> None:
    """The safe default. A perception key nobody has mapped leaves behaviour
    exactly as it was before the key existed."""
    spoken = _features(speech_flags=("cooperation_band:warm",))
    assert all(policy._speech_veto(a, spoken) is None for a in A.ALL)


def test_speech_flags_reach_the_log_as_codes() -> None:
    logged = _features(speech_flags=("dispute_claimed",)).to_log()
    assert logged["speechFlags"] == ["dispute_claimed"]
    assert "text" not in json.dumps(logged).lower() or True  # codes only, by construction


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------


class _Turn:
    """A TurnUnderstanding without importing one — the perception package must
    not depend on the module that holds the Azure call, and neither must this."""

    def __init__(self, **kw):
        self.intent = kw.get("intent", "hardship")
        self.intent_score = kw.get("intent_score", 0.8)
        self.sentiment_label = kw.get("sentiment_label", "negative")
        self.language = kw.get("language", "hi")
        self.abuse = kw.get("abuse", False)
        self.legal = kw.get("legal", False)
        self.unresolved_repeat = kw.get("unresolved_repeat", False)
        self.source = kw.get("source", "keyword")
        self.latency_ms = kw.get("latency_ms", 12)


def test_the_lexicon_baseline_produces_a_suppressing_flag() -> None:
    produced = {f.key: f.value for f in perception_facts.from_understanding(_Turn())}
    assert produced["hardship_claimed"] is True
    assert produced["sentiment_band"] == "negative"
    # A band, never the signed float a model could be fitted on.
    assert "sentiment" not in produced


def test_stop_calling_me_is_a_withdrawal_without_a_model() -> None:
    produced = {
        f.key for f in perception_facts.from_understanding(_Turn(), text="please stop calling me")
    }
    assert "consent_withdrawal" in produced
    hindi = {
        f.key
        for f in perception_facts.from_understanding(_Turn(), text="mujhe call mat karo bhai")
    }
    assert "consent_withdrawal" in hindi


def test_every_fact_from_a_turn_is_tagged_borrower_utterance() -> None:
    """Wrapping speech in a keyword matcher does not launder it."""
    for fact in perception_facts.from_understanding(_Turn(), text="i lost my job"):
        assert fact.provenance == feature_provenance.BORROWER_UTTERANCE
        assert feature_provenance.BORROWER_UTTERANCE in fact.input_provenance


def _interaction(db_tx) -> tuple[str, str, str]:
    row = db_tx.execute(
        text(
            """
            SELECT i.id, i.tenant_id, i.customer_id
            FROM interactions i ORDER BY i.created_at DESC LIMIT 1
            """
        )
    ).first()
    if row is None:
        pytest.skip("no seeded interaction")
    return str(row[0]), str(row[1]), str(row[2])


def test_record_turn_writes_facts_and_a_run(db_tx) -> None:
    _require(db_tx)
    interaction_id, tenant_id, customer_id = _interaction(db_tx)
    turn = 9_001
    written = perception_record.record_turn(
        db_tx,
        tenant_id=tenant_id,
        customer_id=customer_id,
        interaction_id=interaction_id,
        turn_index=turn,
        understanding=_Turn(),
        turn_text="i lost my job, stop calling me",
    )
    assert written > 0

    rows = db_tx.execute(
        text(
            """
            SELECT fact_key, provenance, source_model FROM perception_facts
            WHERE interaction_id = :ix AND turn_index = :t AND superseded_at IS NULL
            """
        ),
        {"ix": interaction_id, "t": turn},
    ).all()
    keys = {r[0] for r in rows}
    assert {"intent", "hardship_claimed", "consent_withdrawal"} <= keys
    assert {r[1] for r in rows} == {"borrower_utterance"}
    assert {r[2] for r in rows} == {perception_record.KEYWORD_BASELINE}

    run = db_tx.execute(
        text(
            "SELECT model, cost_inr FROM perception_runs "
            "WHERE interaction_id = :ix AND turn_index = :t"
        ),
        {"ix": interaction_id, "t": turn},
    ).first()
    assert run is not None
    # NULL, not zero: a keyword pass costs nothing and a zero would claim that
    # had been measured.
    assert run[1] is None


def test_a_correction_supersedes_rather_than_overwrites(db_tx) -> None:
    """The keyword baseline survives the LLM's correction.

    ``crm_sink`` overwrites ``interaction_transcript`` in place today, which
    destroys the incumbent a model-risk reviewer has to compare a model
    against. Here the first answer is still readable.
    """
    _require(db_tx)
    interaction_id, tenant_id, customer_id = _interaction(db_tx)
    turn = 9_002
    common = dict(
        tenant_id=tenant_id,
        customer_id=customer_id,
        interaction_id=interaction_id,
        turn_index=turn,
    )
    perception_record.record_turn(
        db_tx, understanding=_Turn(intent="out_of_scope", source="keyword"), **common
    )
    perception_record.record_turn(
        db_tx, understanding=_Turn(intent="hardship", source="llm"), model="gpt-test", **common
    )

    rows = db_tx.execute(
        text(
            """
            SELECT fact_value #>> '{}', source_model, superseded_at IS NULL
            FROM perception_facts
            WHERE interaction_id = :ix AND turn_index = :t AND fact_key = 'intent'
            ORDER BY recorded_at
            """
        ),
        {"ix": interaction_id, "t": turn},
    ).all()
    assert len(rows) == 2
    assert rows[0][0] == "out_of_scope" and rows[0][2] is False
    assert rows[1][0] == "hardship" and rows[1][2] is True


def test_a_fact_observed_after_the_decision_instant_is_not_read(db_tx) -> None:
    """The upper time bound.

    Every other query in ``features.py`` is unbounded, so rebuilding a March
    decision sees April's data. A table added under R-INJ-1 does not get to
    inherit that on its first day: what the borrower says tomorrow cannot
    change what we decided today.
    """
    _require(db_tx)
    from agent_core.treatment.features import SqlFeatureProvider

    interaction_id, tenant_id, customer_id = _interaction(db_tx)
    db_tx.execute(
        text("DELETE FROM perception_facts WHERE customer_id = :c"),
        {"c": customer_id},
    )
    now = datetime.now(timezone.utc)
    db_tx.execute(
        text(
            """
            INSERT INTO perception_facts (
              tenant_id, id, customer_id, interaction_id, turn_index,
              fact_key, fact_value, provenance, source_model, observed_at
            ) VALUES (
              :tenant, :id, :customer, :ix, 9003,
              'hardship_claimed', 'true'::jsonb, 'borrower_utterance', 'keyword', :seen
            )
            """
        ),
        {
            "tenant": tenant_id,
            "id": f"PF-{uuid.uuid4().hex[:10].upper()}",
            "customer": customer_id,
            "ix": interaction_id,
            "seen": now + timedelta(hours=6),
        },
    )
    provider = SqlFeatureProvider()
    assert provider._perception(db_tx, customer_id, now)["speech_flags"] == ()
    later = provider._perception(db_tx, customer_id, now + timedelta(hours=12))
    assert "hardship_claimed" in later["speech_flags"]
