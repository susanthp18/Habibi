"""W7 — the analysis panel, the case, and intervals that carry their clusters.

The design-effect test is the one that earns the wave: a borrower delinquent for
a run of consecutive days is ONE case, not one case per day. §8.7 measures that
difference as a factor of three on the minimum detectable effect and nine on the
sample size.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from agent_core.treatment import cluster, metrics, panel, schema_ready

# A fixed instant, back-dated well inside every window under test. The db_tx
# fixture freezes now() at transaction start, so rows are back-dated from a
# passed-in clock rather than wall-clocked.
NOW = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _reset_schema_cache():
    schema_ready.reset_cache()
    yield
    schema_ready.reset_cache()


def _require(db_tx) -> None:
    if not schema_ready.w7_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W7 schema not applied (migration 0115)")
        pytest.skip("W7 schema not applied")


def _identity(db_tx) -> tuple[str, str, str]:
    row = db_tx.execute(
        text(
            """
            SELECT c.tenant_id, c.id AS customer_id, a.id AS account_id
              FROM customers c JOIN accounts a ON a.customer_id = c.id
             ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded account")
    return str(row["tenant_id"]), str(row["customer_id"]), str(row["account_id"])


def _decide(
    db_tx,
    *,
    tenant: str,
    customer: str,
    account: str | None,
    ref: str,
    at: datetime,
    variant: str = "treated",
    kind: str = "dpd_tick",
    outcome: str = "paid",
    cure: str | None = "paid",
    enacted: bool = True,
) -> str:
    """One decision row, back-dated. mode='shadow' so nothing here is 'live'."""
    decision_id = f"TD-W7-{uuid.uuid4().hex[:12]}"
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions (
              id, tenant_id, customer_id, account_id, trigger_kind, trigger_ref,
              mode, variant, recommender, recommender_version,
              feature_schema_version, chosen_action, enacted, outcome,
              cure_outcome, reach_outcome, observed_days, label_mature_at,
              label_definition_version, logging_contract_version, created_at
            ) VALUES (
              :id, :tid, :cid, :aid, :kind, :ref,
              'shadow', :variant, 'test', 'v1',
              'v1', 'sms', :enacted, :outcome,
              :cure, 'reached', 14, :mature,
              'w3-v1', 2, :at
            )
            """
        ),
        {
            "id": decision_id,
            "tid": tenant,
            "cid": customer,
            "aid": account,
            "kind": kind,
            "ref": ref,
            "variant": variant,
            "enacted": enacted,
            "outcome": outcome,
            "cure": cure,
            "mature": at,
            "at": at,
        },
    )
    return decision_id


def test_a_delinquency_spell_is_one_case_not_one_case_per_day(db_tx) -> None:
    """The wave's reason for existing.

    Sixty consecutive daily ticks are one delinquency spell. Counted per day the
    design effect is 12.8 at ICC 0.2; counted per spell it is 1.4. That is a
    factor of three on the minimum detectable effect, in an unknown direction,
    on the number that gates the product (§8.7).
    """
    _require(db_tx)
    tenant, customer, account = _identity(db_tx)
    start = NOW - timedelta(days=70)
    for day in range(60):
        at = start + timedelta(days=day)
        _decide(
            db_tx,
            tenant=tenant,
            customer=customer,
            account=account,
            ref=at.date().isoformat(),
            at=at,
        )

    built = panel.build(db_tx, now=NOW, since=start - timedelta(days=1))
    assert built["cases"] == 1, (
        "sixty consecutive daily ticks are one delinquency spell; "
        f"the panel made {built['cases']}"
    )

    row = db_tx.execute(
        text(
            """
            SELECT spell_ref, decisions FROM analysis_panel
             WHERE customer_id = :cid AND trigger_kind = 'dpd_tick'
            """
        ),
        {"cid": customer},
    ).mappings().first()
    assert row["decisions"] == 60
    assert row["spell_ref"] == start.date().isoformat(), (
        "the case key is the first tick of the spell, not the last and not today"
    )


def test_a_gap_in_the_ticks_opens_a_new_spell(db_tx) -> None:
    """A borrower who cures and re-defaults is two cases, not one."""
    _require(db_tx)
    tenant, customer, account = _identity(db_tx)
    start = NOW - timedelta(days=60)
    days = [0, 1, 2, 30, 31]  # a 27-day gap in the middle
    for offset in days:
        at = start + timedelta(days=offset)
        _decide(
            db_tx,
            tenant=tenant,
            customer=customer,
            account=account,
            ref=at.date().isoformat(),
            at=at,
        )
    built = panel.build(db_tx, now=NOW, since=start - timedelta(days=1))
    assert built["cases"] == 2


def test_building_twice_produces_the_same_panel(db_tx) -> None:
    _require(db_tx)
    tenant, customer, account = _identity(db_tx)
    start = NOW - timedelta(days=20)
    for day in range(5):
        at = start + timedelta(days=day)
        _decide(
            db_tx,
            tenant=tenant,
            customer=customer,
            account=account,
            ref=at.date().isoformat(),
            at=at,
        )
    first = panel.build(db_tx, now=NOW, since=start - timedelta(days=1))
    second = panel.build(db_tx, now=NOW, since=start - timedelta(days=1))
    assert first == second
    total = db_tx.execute(text("SELECT count(*) FROM analysis_panel")).scalar()
    assert total == first["cases"]


def test_a_case_our_executor_cancelled_is_censored_not_a_failure(db_tx) -> None:
    """§11.5: cancelled is censoring, not failure — and it stays visible."""
    _require(db_tx)
    tenant, customer, account = _identity(db_tx)
    at = NOW - timedelta(days=10)
    decision_id = _decide(
        db_tx,
        tenant=tenant,
        customer=customer,
        account=account,
        ref=at.date().isoformat(),
        at=at,
        outcome="cancelled",
        cure=None,
    )
    db_tx.execute(
        text(
            "UPDATE treatment_decisions SET cancel_reason = 'no_executor' "
            "WHERE id = :id"
        ),
        {"id": decision_id},
    )
    panel.build(db_tx, now=NOW, since=at - timedelta(days=1))
    row = db_tx.execute(
        text("SELECT censored, censor_reason FROM analysis_panel WHERE customer_id = :c"),
        {"c": customer},
    ).mappings().first()
    assert row["censored"] is True
    assert row["censor_reason"] == "no_executor", (
        "the reason must survive into the panel, or the censoring rate is invisible"
    )


def test_the_causal_gate_refuses_and_says_which_floor_it_missed(db_tx) -> None:
    """On today's book the honest answer is a refusal with a cluster count."""
    _require(db_tx)
    tenant, customer, account = _identity(db_tx)
    at = NOW - timedelta(days=5)
    _decide(
        db_tx,
        tenant=tenant,
        customer=customer,
        account=account,
        ref=at.date().isoformat(),
        at=at,
    )
    panel.build(db_tx, now=NOW, since=at - timedelta(days=30))
    result = metrics.causal(db_tx, days=90, modes=["shadow", "live"])
    assert result["available"] is False
    assert "floor of 40" in result["reason"]
    assert result["controlClusters"] < cluster.MIN_CLUSTERS
    assert "designEffect" in result, (
        "a refusal must still publish what it measured, or nobody learns why"
    )


# ---------------------------------------------------------------------------
# Synthetic panel. Exercises the estimators past their floors; never a source of
# any published number.
#
# ponytail: fixture-only corpus. §15.3 demotes the simulator -- "it may exercise
# code paths; it may never again select a hyperparameter, a shrinkageK or a
# segment ladder" -- and this obeys that: every row is mode='shadow', the guard
# below asserts no synthetic row is ever 'live', and nothing here feeds a
# promotion. Replace with eight weeks of real panel when the book has it.
# ---------------------------------------------------------------------------


def _synthetic_panel(db_tx, *, borrowers: int, cases_each: int) -> None:
    tenant, _, account = _identity(db_tx)
    start = NOW - timedelta(days=80)
    for b in range(borrowers):
        customer = f"w7-synthetic-{b:04d}"
        db_tx.execute(
            text(
                "INSERT INTO customers_pii (id, tenant_id, name, risk) "
                "VALUES (:id, :t, :n, 'low') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": customer, "t": tenant, "n": f"W7 Synthetic {b}"},
        )
        # Treated borrowers cure more often than control. A real effect, so the
        # estimator has something to find; the size is arbitrary and is never
        # read as a result.
        control = b % 5 == 0
        for c in range(cases_each):
            # 30 days apart so three cases span ~8.6 weeks: the panel must
            # clear MIN_PANEL_WEEKS before m and ICC count as measurements.
            at = start + timedelta(days=c * 30)
            cured = (b + c) % (2 if not control else 3) == 0
            _decide(
                db_tx,
                tenant=tenant,
                customer=customer,
                account=None,
                ref=f"synthetic-{b}-{c}",
                at=at,
                kind="bounce",
                variant="null_treatment" if control else "treated",
                outcome="paid" if cured else "refused",
                cure="paid" if cured else None,
                enacted=not control,
            )


def test_the_synthetic_panel_is_never_live(db_tx) -> None:
    """The guard that keeps the fixture a fixture."""
    _require(db_tx)
    _synthetic_panel(db_tx, borrowers=10, cases_each=2)
    live = db_tx.execute(
        text(
            "SELECT count(*) FROM treatment_decisions "
            "WHERE customer_id LIKE 'w7-synthetic-%' AND mode = 'live'"
        )
    ).scalar()
    assert live == 0, "a synthetic row must never be able to reach a live estimate"


def test_past_the_cluster_floor_the_gate_opens_and_the_interval_carries_clusters(
    db_tx,
) -> None:
    _require(db_tx)
    # 220 borrowers at the shipped 80/20 split is 44 in the control arm --
    # barely past the 40-cluster floor, which is itself the point: an 80/20
    # split needs 200+ borrowers before the control arm can carry an interval.
    _synthetic_panel(db_tx, borrowers=220, cases_each=3)
    panel.build(db_tx, now=NOW, since=NOW - timedelta(days=120))

    stats = panel.clustering(db_tx)
    assert stats["controlClusters"] >= cluster.MIN_CLUSTERS
    assert stats["treatedClusters"] >= cluster.MIN_CLUSTERS
    assert stats["weeks"] >= metrics.MIN_PANEL_WEEKS

    result = metrics.causal(db_tx, days=120, modes=["shadow"])
    assert result["available"] is True, result.get("reason")
    interval = result["incrementalCureRateInterval"]
    assert interval["clusters"] >= cluster.MIN_CLUSTERS
    assert interval["method"] == cluster.METHOD_PERCENTILE
    assert interval["low"] <= interval["value"] <= interval["high"]
    assert result["designEffect"] >= 1.0
    assert result["casesPerCustomer"] > 1.0


def test_below_the_floor_the_bootstrap_falls_back_to_the_wild_variant() -> None:
    """§8.8: under ~40 clusters the percentile bootstrap is not trustworthy."""
    rows = [
        {"customer_id": f"c{i}", "value": float(i % 3)}
        for i in range(30)
    ]
    interval = cluster.bootstrap(
        rows, lambda rs: sum(r["value"] for r in rs) / len(rs)
    )
    assert interval.method == cluster.METHOD_WILD
    assert interval.clusters == 30
    assert interval.low < interval.value < interval.high


def test_clustered_errors_are_wider_than_pretending_rows_are_independent() -> None:
    """The whole point, as one number.

    Ten borrowers with ten identical decisions each carry ten observations of
    information, not a hundred. The i.i.d. error shrinks with the hundred; the
    clustered error does not.
    """
    from agent_core.treatment.ope import Observation, _clustered_stderr

    observations = []
    terms = []
    for b in range(10):
        for _ in range(10):
            observations.append(
                Observation(
                    decision_id=f"d{len(terms)}",
                    action="sms",
                    reward=float(b % 2),
                    propensity=0.5,
                    customer_id=f"cust-{b}",
                )
            )
            terms.append(float(b % 2))

    clustered = _clustered_stderr(observations, terms)
    n = len(terms)
    mean = sum(terms) / n
    iid = (sum((t - mean) ** 2 for t in terms) / (n - 1) / n) ** 0.5
    assert clustered > iid * 2, (
        f"clustered {clustered:.4f} must dwarf the i.i.d. {iid:.4f} when every "
        "decision on a borrower carries the same value"
    )


def test_icc_is_measured_not_assumed() -> None:
    """Perfectly correlated within borrower is ICC 1; pure noise is near 0."""
    identical = [
        {"customer_id": f"c{b}", "reward_inr": float(b)}
        for b in range(20)
        for _ in range(5)
    ]
    assert cluster.icc(identical, value_key="reward_inr") > 0.95

    alternating = [
        {"customer_id": f"c{b}", "reward_inr": float(i % 2)}
        for b in range(20)
        for i in range(5)
    ]
    assert cluster.icc(alternating, value_key="reward_inr") < 0.2


def test_design_effect_matches_the_documented_arithmetic() -> None:
    """§8.7's worked numbers, so a change to the formula fails here."""
    assert cluster.design_effect(1.0, 0.2) == pytest.approx(1.0)
    assert cluster.design_effect(3.0, 0.2) == pytest.approx(1.4)
    assert cluster.design_effect(12.8, 0.2) == pytest.approx(3.36)
    # ICC 0 means the clustering costs nothing, whatever m is.
    assert cluster.design_effect(50.0, 0.0) == pytest.approx(1.0)
