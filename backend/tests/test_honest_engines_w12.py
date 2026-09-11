"""W12 — the absorbed offer family, and the ladder that can refuse.

§15.2's W12 exit criterion has two halves and both are reachable:

    A segment promotion under the repaired gate, **or an honest refusal with the
    FDR-adjusted numbers filed**; **0** code paths in which an offer is utterable
    on a collections call, asserted in CI.

Measured read-only against ``collections`` on 2026-09-10, which is what shapes
the wave:

    offer_decisions rows                          16 (9 live, 7 shadow)
    ...carrying a response, ever                  0
    ...on logging_contract_version = 2            0 of 16
    ...carrying arm_propensity                    0 of 16
    analysis_panel                                0 cases, 0 borrowers

So the offer corpus is simultaneously unevaluable (no propensity) and unlabelled
(no response), and the panel cannot measure the shrinkage constant §8.10 asks
for. Two of those this wave fixes going forward — the propensity contract and
the response route — and the third is a refusal, which is the point.

The load-bearing test in this file is
:func:`test_no_offer_is_utterable_on_a_collections_call`. Everything else here
is arithmetic; that one is the lawful invariant §9.7 turns on.
"""

from __future__ import annotations

import inspect
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import text

from agent_core.reco import decisions as reco_decisions
from agent_core.reco import engine as reco_engine
from agent_core.reco import followthrough as offer_followthrough
from agent_core.reco import suitability
from agent_core.treatment import cluster, hierarchy, models, schema_ready

BACKEND = Path(__file__).resolve().parents[1]


def _trainer():
    """`scripts/train_treatment_models.py` is a script, not an importable module.

    Loaded by path, the way `tests/test_decision_intelligence_p1.py` already
    loads it. Cached because `load_env()` runs at import.
    """
    import importlib.util

    global _TRAINER
    if _TRAINER is None:
        spec = importlib.util.spec_from_file_location(
            "train_treatment_models",
            BACKEND / "scripts" / "train_treatment_models.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _TRAINER = module
    return _TRAINER


_TRAINER = None


@pytest.fixture(autouse=True)
def _reset():
    schema_ready.reset_cache()
    yield
    schema_ready.reset_cache()


def _require_w12(db_tx) -> None:
    """``action_family`` is this wave's own column (sql/32, migration 0121).

    Absent from the running database because 0121 is deliberately unapplied
    there — the same condition ``decisions._mirror`` checks before writing the
    second log, so this skip is that fact seen from the test's side.
    """
    if not schema_ready.w12_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("treatment_decisions.action_family absent (migration 0121)")
        pytest.skip("action_family absent (migration 0121 unapplied)")


# ---------------------------------------------------------------------------
# §9.7 — the invariant that makes the absorption lawful
# ---------------------------------------------------------------------------


def test_no_offer_is_utterable_on_a_collections_call() -> None:
    """W12's second exit criterion, and the reason the wave is lawful.

    A promotional utterance inside a recorded collections call is three breaches
    at once: it reclassifies the entire communication as Promotional — which
    then subjects the collections call itself to the borrower's DND — it markets
    without a suitability finding, where an explicit consent artefact does not
    cure unsuitability, and on a delinquent borrower it is the textbook
    mis-selling fact pattern carrying refund **plus** compensation.

    The gate is structural rather than a prompt line, and it lives in exactly
    one function, because both mouths and every future one route through it. A
    model that is never told a product name cannot be prompted, jailbroken or
    flow-graphed into saying one.
    """
    result = reco_engine.RecommendationResult(
        offers=[],
        suppressed=False,
        decision_id="OD-TEST",
    )
    payload = result.to_tool_payload()
    assert payload["offers"] == []
    assert payload["say"] == reco_engine.DEFERRED_SAY
    for word in ("product", "offer", "top-up", "upgrade"):
        assert word in reco_engine.DEFERRED_SAY, word


def test_the_payload_is_the_same_whether_or_not_an_offer_survived() -> None:
    """Otherwise the absence of a product becomes the signal about the product.

    A payload that said ``suppressed: false`` and named nothing would tell the
    model there was something it was not being told, and a model that knows an
    offer exists is one turn of pressure away from alluding to it.
    """

    class _Offer:
        product_id = "PRD-TOPUP"
        name = "Top-up loan"
        suggested_amount = 150000.0
        roi = 12.5
        talk_track = "A top-up of one point five lakh rupees is available."
        reason_codes = ("clean_repayment",)

    scored = reco_engine.RecommendationResult(
        offers=[_Offer()], suppressed=False, decision_id="OD-A"
    ).to_tool_payload()
    empty = reco_engine.RecommendationResult(
        offers=[], suppressed=True, decision_id="OD-B"
    ).to_tool_payload()

    assert scored["offers"] == empty["offers"] == []
    assert scored["say"] == empty["say"]
    assert scored["suppressed"] is empty["suppressed"] is True
    blob = repr(scored)
    for leak in ("PRD-TOPUP", "Top-up loan", "150000", "12.5", "one point five"):
        assert leak not in blob, f"{leak} crossed the boundary to the model"


def test_no_call_path_reads_a_talk_track_off_a_recommendation() -> None:
    """The close probe used to, bypassing ``to_tool_payload`` entirely.

    It read ``top.talk_track`` and ``top.name`` straight off the result and
    folded a ready-phrased sentence into the ``pre_close`` prompt. A gate that
    one caller can go around is not a gate, so this asserts the going-around is
    gone rather than that the gate exists.
    """
    for name in ("voice/tools.py", "bot_tools.py"):
        code = [
            line
            for line in (BACKEND / name).read_text(encoding="utf-8").splitlines()
            if not line.lstrip().startswith("#")
        ]
        src = "\n".join(code)
        assert "talk_track" not in src, f"{name} reads a talk track"
        assert "mention this ONE product" not in src, f"{name} still pitches"


def test_the_close_probe_template_has_no_slot_for_an_offer() -> None:
    """An empty string is a policy; an absent placeholder is a property."""
    from voice import tools as voice_tools

    assert "{offer}" not in voice_tools._PRE_CLOSE_TASK
    src = (BACKEND / "voice" / "tools.py").read_text(encoding="utf-8")
    assert "close_probe_offer_clause" not in src


def test_a_scored_offer_is_logged_on_the_deferred_promotional_channel() -> None:
    """Not a channel a message goes out on — a state (§9.7).

    Held for the promotional series, and the collections channels are exactly
    the ones it may not become without a fresh, consented, suitability-gated
    decision.
    """
    assert reco_decisions.DEFERRED_PROMOTIONAL == "deferred_promotional"
    sql = (BACKEND / "sql" / "32_offer_absorption.sql").read_text(encoding="utf-8")
    assert "'deferred_promotional'" in sql
    assert "ck_treatment_decisions_channel" in sql


# ---------------------------------------------------------------------------
# Suitability — an absent finding is a refusal
# ---------------------------------------------------------------------------


def _tenant(db_tx) -> str:
    tenant = db_tx.execute(text("SELECT id FROM tenants LIMIT 1")).scalar()
    if not tenant:
        pytest.skip("no tenant seeded")
    return str(tenant)


def _assess(db_tx, tenant, *, customer, product, verdict="suitable", expires=None):
    db_tx.execute(
        text(
            """
            INSERT INTO suitability_assessments
              (id, tenant_id, customer_id, product_id, assessor, verdict,
               evidence_ref, expires_at)
            VALUES (:id, :tenant, :customer, :product, 'compliance-desk',
                    :verdict, 'SUIT-EV-1', :expires)
            """
        ),
        {
            "id": f"SA-{random.randrange(10**9)}",
            "tenant": tenant,
            "customer": customer,
            "product": product,
            "verdict": verdict,
            "expires": expires,
        },
    )


def _borrower_and_product(db_tx, tenant):
    customer = db_tx.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t LIMIT 1"), {"t": tenant}
    ).scalar()
    product = db_tx.execute(text("SELECT id FROM products LIMIT 1")).scalar()
    if not customer or not product:
        pytest.skip("no seeded customer/product")
    return str(customer), str(product)


def test_an_unassessed_borrower_may_not_be_offered_anything(db_tx) -> None:
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    reason = suitability.objection(
        db_tx, customer_id=customer, product_id=product, tenant_id=tenant
    )
    assert reason == suitability.REASON_ABSENT


def test_a_current_suitable_finding_clears_the_gate(db_tx) -> None:
    """The half that stops this being a deletion. A gate that can only ever
    refuse has removed the feature rather than governed it."""
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    _assess(db_tx, tenant, customer=customer, product=product)
    assert (
        suitability.objection(
            db_tx, customer_id=customer, product_id=product, tenant_id=tenant
        )
        is None
    )


def test_an_expired_finding_is_not_a_current_one(db_tx) -> None:
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    # `db_tx` freezes now() at transaction start, so back-date rather than
    # wall-clock: a row written "an hour ago" by the process clock can still be
    # in the future by the transaction's.
    now = db_tx.execute(text("SELECT now()")).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO suitability_assessments
              (id, tenant_id, customer_id, product_id, assessed_at, expires_at,
               assessor, verdict, evidence_ref)
            VALUES ('SA-EXPIRED', :tenant, :customer, :product,
                    :assessed, :expires, 'compliance-desk', 'suitable', 'EV')
            """
        ),
        {
            "tenant": tenant,
            "customer": customer,
            "product": product,
            "assessed": now - timedelta(days=400),
            "expires": now - timedelta(days=30),
        },
    )
    assert (
        suitability.objection(
            db_tx, customer_id=customer, product_id=product, tenant_id=tenant
        )
        == suitability.REASON_EXPIRED
    )


def test_an_unsuitable_finding_refuses(db_tx) -> None:
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    _assess(db_tx, tenant, customer=customer, product=product, verdict="unsuitable")
    assert (
        suitability.objection(
            db_tx, customer_id=customer, product_id=product, tenant_id=tenant
        )
        == suitability.REASON_UNSUITABLE
    )


def test_a_database_that_cannot_say_has_not_said_yes() -> None:
    """§8.12's rule, applied to a table: an unevaluable gate is a refusal."""
    assert suitability.objection(None, customer_id="C", product_id="P") == (
        suitability.REASON_UNEVALUABLE
    )


def test_the_audit_trail_refuses_an_empty_evidence_pointer(db_tx) -> None:
    """A mis-selling record whose evidence pointer is optional is a note.

    Enforced by the database rather than by the writer, on the spelling
    ``sql/27`` and ``sql/28`` already use for maker-checker.
    """
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    with pytest.raises(Exception) as exc:
        with db_tx.begin_nested():
            db_tx.execute(
                text(
                    """
                    INSERT INTO suitability_assessments
                      (id, tenant_id, customer_id, product_id, assessor,
                       verdict, evidence_ref)
                    VALUES ('SA-BLANK', :tenant, :customer, :product,
                            'desk', 'suitable', '   ')
                    """
                ),
                {"tenant": tenant, "customer": customer, "product": product},
            )
    assert "ck_suitability_evidence" in str(exc.value)


# ---------------------------------------------------------------------------
# The absorbed log
# ---------------------------------------------------------------------------


def test_a_treatment_row_may_not_carry_a_product(db_tx) -> None:
    """The family column is a fact the table holds, not a label somebody sets.

    Without the shape constraint the first mis-set row is invisible until an
    estimator averages across two action spaces.
    """
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    with pytest.raises(Exception) as exc:
        with db_tx.begin_nested():
            db_tx.execute(
                text(
                    """
                    INSERT INTO treatment_decisions
                      (id, tenant_id, customer_id, trigger_kind, mode,
                       recommender, recommender_version, feature_schema_version,
                       action_family, product_id)
                    VALUES ('TD-BAD', :tenant, :customer, 'inbound', 'shadow',
                            'ev', '1.0.0', 'v1', 'treatment', :product)
                    """
                ),
                {"tenant": tenant, "customer": customer, "product": product},
            )
    assert "ck_treatment_decisions_family_shape" in str(exc.value)


def test_the_mirror_writes_the_offer_family(db_tx) -> None:
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    decision_id = reco_decisions.record(
        conn=db_tx,
        customer_id=customer,
        interaction_id=None,
        channel="voice",
        mode="shadow",
        variant=None,
        recommender="rule",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_product_id=product,
        suggested_amount=150000.0,
        score=0.8,
        suppression_reason=None,
        latency_ms=12,
        arm_propensity=0.5,
        action_propensity=0.25,
    )
    assert decision_id
    row = db_tx.execute(
        text(
            "SELECT action_family, chosen_action, chosen_channel, product_id,"
            " propensity, arm_propensity, action_propensity"
            " FROM treatment_decisions WHERE id = :id"
        ),
        {"id": decision_id},
    ).mappings().first()
    assert row is not None, "the offer never reached the absorbed log"
    assert row["action_family"] == "offer"
    assert row["chosen_action"] == "offer"
    assert row["chosen_channel"] == "deferred_promotional"
    assert row["product_id"] == product
    # §8.6: the two halves stored separately, and the fused figure beside them.
    assert float(row["arm_propensity"]) == 0.5
    assert float(row["action_propensity"]) == 0.25
    assert float(row["propensity"]) == 0.25


def test_a_suppressed_offer_is_a_wait_that_still_carries_its_propensity(db_tx) -> None:
    """W11a's repair to ``ope.py``, applied to the absorbed family on day one.

    Dropping suppressed decisions scores every policy against the population the
    engine had already decided to act on.
    """
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, _ = _borrower_and_product(db_tx, tenant)
    decision_id = reco_decisions.record(
        conn=db_tx,
        customer_id=customer,
        interaction_id=None,
        channel="voice",
        mode="shadow",
        variant=None,
        recommender="rule",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={"PRD-X": "suitability:no assessment on file"},
        chosen_product_id=None,
        suggested_amount=None,
        score=None,
        suppression_reason="no_eligible_candidates",
        latency_ms=9,
        arm_propensity=1.0,
        action_propensity=1.0,
    )
    row = db_tx.execute(
        text(
            "SELECT chosen_action, chosen_channel, propensity, suppression_reason"
            " FROM treatment_decisions WHERE id = :id"
        ),
        {"id": decision_id},
    ).mappings().first()
    assert row["chosen_action"] == "wait"
    assert row["chosen_channel"] is None
    assert row["propensity"] is not None
    assert row["suppression_reason"] == "no_eligible_candidates"


def test_a_response_lands_in_both_logs(db_tx) -> None:
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    decision_id = reco_decisions.record(
        conn=db_tx,
        customer_id=customer,
        interaction_id=None,
        channel="voice",
        mode="shadow",
        variant=None,
        recommender="rule",
        recommender_version="1.0.0",
        feature_schema_version="v1",
        features={},
        candidates=[],
        excluded={},
        chosen_product_id=product,
        suggested_amount=1.0,
        score=0.5,
        suppression_reason=None,
        latency_ms=1,
    )
    reco_decisions.mirror_update(
        db_tx,
        "offer_response = :response, responded_at = now()",
        {"id": decision_id, "response": "interested"},
    )
    assert (
        db_tx.execute(
            text("SELECT offer_response FROM treatment_decisions WHERE id = :id"),
            {"id": decision_id},
        ).scalar()
        == "interested"
    )


# ---------------------------------------------------------------------------
# Silence is a label
# ---------------------------------------------------------------------------


def test_an_undelivered_offer_is_censored_not_declined(db_tx) -> None:
    """§11.5. Nobody was asked, so nobody declined.

    An estimator that scores these as rejections is measuring the promotional
    series' delivery rate and calling it demand — the same mistake §4.6 records
    on the collections side, where an undelivered SMS was labelled a *failed
    treatment* rather than a *failed reach*.
    """
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    now = db_tx.execute(text("SELECT now()")).scalar()
    old = now - timedelta(days=offer_followthrough.GRACE_DAYS + 1)
    for suffix, presented in (("SENT", True), ("UNSENT", False)):
        db_tx.execute(
            text(
                """
                INSERT INTO offer_decisions
                  (id, tenant_id, customer_id, channel, mode, recommender,
                   recommender_version, feature_schema_version,
                   chosen_product_id, presented, created_at)
                VALUES (:id, :tenant, :customer, 'whatsapp', 'live', 'rule',
                        '1.0.0', 'v1', :product, :presented, :at)
                """
            ),
            {
                "id": f"OD-W12-{suffix}",
                "tenant": tenant,
                "customer": customer,
                "product": product,
                "presented": presented,
                "at": old,
            },
        )
    counts = offer_followthrough.sweep(db_tx, now=now)
    assert counts["deferred"] >= 1 and counts["not_reached"] >= 1
    got = dict(
        db_tx.execute(
            text(
                "SELECT id, response FROM offer_decisions"
                " WHERE id IN ('OD-W12-SENT','OD-W12-UNSENT')"
            )
        ).all()
    )
    assert got["OD-W12-SENT"] == "deferred"
    assert got["OD-W12-UNSENT"] == "not_reached"


def test_the_sweep_does_not_close_an_offer_inside_its_grace(db_tx) -> None:
    """The window never closes early (§11.6), and it does not close late either
    because somebody looked at the row."""
    _require_w12(db_tx)
    tenant = _tenant(db_tx)
    customer, product = _borrower_and_product(db_tx, tenant)
    now = db_tx.execute(text("SELECT now()")).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO offer_decisions
              (id, tenant_id, customer_id, channel, mode, recommender,
               recommender_version, feature_schema_version, chosen_product_id,
               presented, created_at)
            VALUES ('OD-W12-FRESH', :tenant, :customer, 'whatsapp', 'live',
                    'rule', '1.0.0', 'v1', :product, true, :at)
            """
        ),
        {
            "tenant": tenant,
            "customer": customer,
            "product": product,
            "at": now - timedelta(days=offer_followthrough.GRACE_DAYS - 1),
        },
    )
    offer_followthrough.sweep(db_tx, now=now)
    assert (
        db_tx.execute(
            text("SELECT response FROM offer_decisions WHERE id = 'OD-W12-FRESH'")
        ).scalar()
        is None
    )


def test_the_sweep_never_writes_a_word_a_person_said() -> None:
    """``interested`` and ``declined`` are things a borrower said. Silence is
    not entitled to either."""
    src = inspect.getsource(offer_followthrough)
    assert '"interested"' not in src and '"declined"' not in src
    assert offer_followthrough.DEFERRED == "deferred"
    assert offer_followthrough.NOT_REACHED == "not_reached"


# ---------------------------------------------------------------------------
# The hierarchy — §8.10's `k`, measured or refused
# ---------------------------------------------------------------------------


def _panel(rng, *, borrowers=60, cases=5, between=10.0, within=5.0):
    rows = []
    for c in range(borrowers):
        mu = rng.gauss(0.0, between)
        for _ in range(cases):
            rows.append(
                {
                    "customer_id": f"c{c}",
                    "tenant_id": "t1",
                    "reward_inr": mu + rng.gauss(0.0, within),
                }
            )
    return rows


def test_k_is_measured_from_the_panel_not_chosen_on_a_simulator() -> None:
    """§8.10: ``k = sigma2_within / sigma2_between``, which is the ICC
    rearranged — so the named estimator is ``cluster.icc``, already built and
    tested in W7, rather than a second one with its own assumptions."""
    rows = _panel(random.Random(7))
    k, band, basis = hierarchy.shrinkage_k(rows, level="borrower")
    assert k is not None and band is not None
    # between=10, within=5 -> ICC ~ 0.8 -> k = (1-0.8)/0.8 ~ 0.25
    assert 0.1 < k < 0.5, k
    assert band.low <= k <= band.high, "the interval excludes its own point"
    assert "cluster.icc" in basis and "ICC" in basis


def test_a_wider_within_borrower_spread_shrinks_harder() -> None:
    """More noise inside a borrower and less between them means the pool knows
    more than the individual, which is a larger ``k``."""
    rng = random.Random(11)
    tight, _, _ = hierarchy.shrinkage_k(
        _panel(rng, between=10.0, within=2.0), level="borrower"
    )
    loose, _, _ = hierarchy.shrinkage_k(
        _panel(rng, between=2.0, within=10.0), level="borrower"
    )
    assert tight is not None and loose is not None
    assert loose > tight


def test_an_empty_panel_refuses_rather_than_keeping_seven_fifty() -> None:
    """§8.12's rule applied to a hyperparameter. An unmeasured constant is
    indistinguishable from no constant, and 750 was selected on a simulator
    whose reported n is thirty times its own information content."""
    k, band, basis = hierarchy.shrinkage_k([], level="borrower")
    assert k is None and band is None
    assert "0 panel cases" in basis and "750" in basis


def test_a_level_the_panel_has_no_column_for_refuses_by_name() -> None:
    """Enumerable but unreachable is the honest shape. §18.1 makes cross-tenant
    pooling an open legal question, so ``global`` is named and unread."""
    rows = _panel(random.Random(3))
    for level in ("global", "portfolio", "product", "dpd_band", "region"):
        k, _, basis = hierarchy.shrinkage_k(rows, level=level)
        assert k is None
        assert level in basis and "no column" in basis


def test_too_few_clusters_is_a_refusal_not_a_wide_interval() -> None:
    rows = _panel(random.Random(3), borrowers=5)
    k, _, basis = hierarchy.shrinkage_k(rows, level="borrower")
    assert k is None and "cluster floor" in basis


def test_the_live_panel_cannot_measure_k_today(db_tx) -> None:
    """The measured state of the book, asserted rather than assumed: the panel
    holds 0 cases, so every level refuses and no segment may be promoted."""
    if not schema_ready.w7_ready(db_tx):
        pytest.skip("analysis_panel absent (migration 0115)")
    out = hierarchy.measure(db_tx)
    if out["cases"]:
        pytest.skip(f"panel is populated ({out['cases']} cases) on this database")
    assert all(level["k"] is None for level in out["levels"].values())


# ---------------------------------------------------------------------------
# The shrinkage weight, and Benjamini-Hochberg
# ---------------------------------------------------------------------------


def _segment(**over):
    body = dict(
        key="b0030/open/timing",
        coefficients=(0.0,),
        intercept=0.0,
        control_coefficients=(0.0,),
        control_intercept=0.0,
        n=50_000,
        control_n=180,
    )
    body.update(over)
    return models.SegmentModel(**body)


def test_shrinkage_weighs_the_control_arm_not_the_treated_one() -> None:
    """§8.10: tau's variance is driven by the control arm, because withholding
    treatment is the expensive half and that arm is always the thinner one.

    A stratum with 50,000 treated cases and 180 controls used to take 98.5% of
    the answer on a difference whose standard error came almost entirely from
    those 180 `[models-segment-shrinkage-weight-uses-treated-n]`.
    """
    thin_control = _segment(n=50_000, control_n=180)
    fat_control = _segment(n=180, control_n=50_000)
    k = models.DEFAULT_SHRINKAGE_K
    assert thin_control.weight(k) < 0.25
    assert fat_control.weight(k) > 0.98
    assert thin_control.weight(k) < fat_control.weight(k)


def test_benjamini_hochberg_matches_its_own_worked_example() -> None:
    """The 1995 paper's fifteen p-values at FDR 0.05 reject exactly four."""
    p = [
        0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
        0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0000,
    ]
    assert sum(cluster.bh_reject(p, fdr=0.05)) == 4


def test_bh_is_step_up_so_a_high_p_below_the_cutoff_still_rejects() -> None:
    """The part that gets reimplemented wrongly. 0.04 exceeds its own critical
    value of 0.033 and is rejected anyway, because rank 3 sets the threshold."""
    assert cluster.bh_reject([0.001, 0.04, 0.045], fdr=0.05) == [True, True, True]


def test_bh_rejects_nothing_when_nothing_is_there() -> None:
    assert cluster.bh_reject([0.4, 0.6, 0.9]) == [False, False, False]
    assert cluster.bh_reject([]) == []


def test_bh_is_more_permissive_than_the_bonferroni_it_replaces() -> None:
    """Which is the point. Bonferroni over thirty strata tests each at 0.0017,
    and §8.10's ladder is built to climb *down* to homogeneity — not to be
    unable to climb at all."""
    p = [0.003] + [0.5] * 29
    assert cluster.bh_reject(p, fdr=0.10)[0] is True
    # Bonferroni at FWER 0.05 over thirty strata tests each at 0.00167, so it
    # would have refused this cell; BH at rank 1 of 30 tests it at 0.00333.
    assert 0.003 > 0.05 / 30
    assert 0.003 <= cluster.bh_critical(1, 30, fdr=0.10)


def test_the_critical_value_is_published_per_rank() -> None:
    """A refusal that says only "rejected" is a refusal nobody can audit."""
    assert cluster.bh_critical(5, 30, fdr=0.10) == pytest.approx(0.01667, abs=1e-4)
    assert cluster.bh_critical(30, 30, fdr=0.10) == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# The repaired heterogeneity gate, both directions
# ---------------------------------------------------------------------------

_LADDER_NAMES = (
    "dpd",
    "digital_attempts_since_connect",
    "salary_timing_gap_days",
    "exposure",
)


def _ladder_corpus(*, heterogeneous: bool, seed: int = 5):
    """Four strata over 1,600 borrowers per arm, one decision each.

    When ``heterogeneous``, the ``b3160/open/timing`` cell responds far more
    strongly **and** its response depends on ``exposure`` — both are needed,
    because the causal gate and the holdout-fit gate ask different questions and
    §9's ladder requires both.
    """
    Sample = _trainer().Sample

    rng = random.Random(seed)
    at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    treated, control = [], []
    for i in range(1600):
        dpd = rng.choice([10.0, 45.0])
        vec = {
            "dpd": dpd,
            "digital_attempts_since_connect": 0.0,
            "salary_timing_gap_days": rng.choice([2.0, 40.0]),
            "exposure": rng.random(),
        }
        special = dpd == 45.0 and vec["salary_timing_gap_days"] == 2.0
        for arm in ("t", "c"):
            lift = 0.0
            if arm == "t":
                lift = (
                    0.30 + 0.5 * vec["exposure"]
                    if (heterogeneous and special)
                    else 0.10
                )
            sample = Sample(
                vec=dict(vec),
                label=1 if rng.random() < 0.30 + lift else 0,
                customer_id=f"{arm}-{i}",
                at=at + timedelta(days=i % 60),
                mature_at=at + timedelta(days=(i % 60) + 1),
            )
            (treated if arm == "t" else control).append(sample)
    return treated, control


def _run_ladder(heterogeneous: bool):
    trainer = _trainer()
    treated, control = _ladder_corpus(heterogeneous=heterogeneous)
    rows = treated + control
    means = {
        n: sum(float(s.vec[n]) for s in rows) / len(rows) for n in _LADDER_NAMES
    }
    return trainer.fit_segments(
        treated,
        control,
        names=_LADDER_NAMES,
        means=means,
        scales=[1.0] * len(_LADDER_NAMES),
        cal=(1.0, 0.0),
        holdout=0.3,
        seed=11,
    )


def test_a_homogeneous_book_promotes_no_segment() -> None:
    """The literature's prior is that heterogeneity is small, and §16.2 says
    most cells should fail. The ladder is built to say so."""
    promoted, report = _run_ladder(heterogeneous=False)
    assert promoted == {}
    tested = [e for e in report if "pValue" in e]
    assert tested, "no cell reached the causal gate at all"
    assert all(e["verdict"] == "rejected" for e in tested)
    assert all(e["reason"] == "no_heterogeneity" for e in tested)


def test_a_genuinely_different_segment_is_found_and_promoted() -> None:
    """A gate that can only refuse is a deletion, not a gate.

    The planted cell must be found, and it must be found *first* — rank 1, with
    a p-value inside its own BH critical value. What this deliberately does NOT
    assert is that it is the only cell promoted. Benjamini-Hochberg controls the
    expected **share** of discoveries that are false, not their number in any
    one run, so a companion at FDR 0.10 is the procedure working rather than
    failing. Pinning "exactly one" would be asserting a guarantee BH does not
    make, and the test would then fail on a seed rather than on a defect.
    """
    promoted, report = _run_ladder(heterogeneous=True)
    assert "b3160/open/timing" in promoted, promoted
    winner = next(e for e in report if e["segment"] == "b3160/open/timing")
    assert winner["verdict"] == "promoted"
    assert winner["pValue"] < winner["bhCritical"]
    assert winner["bhRank"] == 1
    # The planted effect is 0.30-0.80 against a population 0.10, so the winner's
    # evidence has to be an order of magnitude stronger than any companion's.
    others = [e["pValue"] for e in report if e.get("verdict") == "promoted"
              and e["segment"] != "b3160/open/timing"]
    assert all(winner["pValue"] < p / 100 for p in others), others


def test_the_gate_is_measured_against_the_leave_one_segment_out_population() -> None:
    """A subset is always closer to a mean it is part of, so testing a segment
    against a pool containing it is biased toward finding no heterogeneity
    `[heterogeneity-gate-is-in-sample-and-subset-vs-pool]`."""
    _, report = _run_ladder(heterogeneous=True)
    winner = next(e for e in report if e["segment"] == "b3160/open/timing")
    assert winner["losoAte"] < winner["ate"]
    assert winner["difference"] == pytest.approx(
        winner["ate"] - winner["losoAte"], abs=1e-6
    )


def test_every_cell_files_its_fdr_adjusted_numbers_whether_it_passed_or_not() -> None:
    """§15.2's W12 exit criterion is "a segment promotion under the repaired
    gate, **or an honest refusal with the FDR-adjusted numbers filed**". The
    report is the deliverable, not a by-product."""
    _, report = _run_ladder(heterogeneous=False)
    tested = [e for e in report if "pValue" in e]
    for entry in tested:
        for field in (
            "pValue", "bhRank", "bhTested", "bhCritical", "bhFdr",
            "ate", "losoAte", "difference", "differenceInterval", "clusters",
            "treatedCustomers", "controlCustomers",
        ):
            assert field in entry, f"{entry['segment']} filed no {field}"
        assert entry["differenceInterval"]["clusters"] >= cluster.MIN_CLUSTERS
        assert entry["bhFdr"] == 0.10


def test_the_power_floors_count_customers_not_rows() -> None:
    """§8.10 rung 3 states them in customers. On a corpus where one borrower
    contributes fourteen decisions, a 150-row stratum can be eleven people."""
    trainer = _trainer()
    treated, control = _ladder_corpus(heterogeneous=False)
    # Collapse every row onto four borrowers: the row counts are untouched and
    # the customer counts collapse, which is exactly the case the row-based
    # floor could not see.
    treated = [s._replace(customer_id=f"t-{i % 4}") for i, s in enumerate(treated)]
    control = [s._replace(customer_id=f"c-{i % 4}") for i, s in enumerate(control)]
    rows = treated + control
    means = {
        n: sum(float(s.vec[n]) for s in rows) / len(rows) for n in _LADDER_NAMES
    }
    promoted, report = trainer.fit_segments(
        treated, control, names=_LADDER_NAMES, means=means,
        scales=[1.0] * len(_LADDER_NAMES), cal=(1.0, 0.0), holdout=0.3, seed=11,
    )
    assert promoted == {}
    skipped = [e for e in report if e.get("reason") == "underpowered"]
    assert skipped, "a four-borrower book reached the causal gate"
    assert any(e["treatedN"] > e["treatedCustomers"] for e in skipped)
