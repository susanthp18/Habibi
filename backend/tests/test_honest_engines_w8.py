"""W8a — configuration is data, and `config_version` names a row.

Six of these tests are regression tests for defects that were live in
``treatment/config.py``: a misspelled arm renormalising the split, a config
value redefining the control arm, ``bool("false")`` minting one, an
unvalidated negative cost, and an action the price book does not carry costing
zero in an arbitration that subtracts cost from value.

The other half is the wave's exit criterion: ``config_version`` on a decision
row resolves to an ``engine_config`` row instead of naming a sha over four
environment variables.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from agent_core import engine_config, logging_contract
from agent_core.reco import config as reco_config
from agent_core.treatment import config as treatment_config
from agent_core.treatment import schema_ready

MAKER = "maker@example.test"
CHECKER = "checker@example.test"


@pytest.fixture(autouse=True)
def _reset():
    schema_ready.reset_cache()
    engine_config.invalidate()
    yield
    schema_ready.reset_cache()
    engine_config.invalidate()


def _require(db_tx) -> None:
    if not schema_ready.w8_ready(db_tx):
        if os.getenv("HONEST_ENGINES_REQUIRE_SCHEMA") == "1":
            pytest.fail("W8 schema not applied (migration 0116)")
        pytest.skip("W8 schema not applied")


def _tenant(db_tx) -> str:
    found = db_tx.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).scalar()
    if not found:
        pytest.skip("no seeded tenant")
    return str(found)


def _put(db_tx, key, value, *, tenant, portfolio_id="", reason="test") -> int:
    return engine_config.put(
        db_tx,
        key,
        value,
        tenant_id=tenant,
        portfolio_id=portfolio_id,
        changed_by=MAKER,
        approved_by=CHECKER,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# The five silent-corruption classes §13.2 names
# ---------------------------------------------------------------------------


def test_a_split_naming_an_unknown_arm_refuses_rather_than_renormalising(monkeypatch):
    # Two named arms, one of them misspelled. The old behaviour dropped the
    # typo and gave the survivor 100% -- so arm_probability returned 1.0 for a
    # borrower who had actually been assigned with probability 0.5, and that
    # number multiplies into the propensity logged on every decision row.
    monkeypatch.setenv("TREATMENT_AB_SPLIT", "control:50,pateint:50")
    engine_config.invalidate()

    assert treatment_config.ab_split() == []
    assert treatment_config.assign_variant("cust-1") is None
    assert treatment_config.arm_probability("control") == 1.0

    monkeypatch.setenv("TREATMENT_AB_SPLIT", "control:50,patient:50")
    engine_config.invalidate()
    assert dict(treatment_config.ab_split()) == {"control": 0.5, "patient": 0.5}


def test_configuration_cannot_redefine_the_control_arm(monkeypatch):
    monkeypatch.setenv(
        "TREATMENT_VARIANTS",
        '{"null_treatment": {"suppressDiscretionary": false}, '
        '"challenger": {"minExpectedValue": 5.0}}',
    )
    engine_config.invalidate()

    table = treatment_config.variants()
    # The control arm is the one every incremental number is measured against.
    assert table["null_treatment"].suppress_discretionary is True
    # A genuinely new arm is still allowed.
    assert table["challenger"].min_expected_value == 5.0


def test_the_string_false_does_not_mint_a_control_arm(monkeypatch):
    monkeypatch.setenv(
        "TREATMENT_VARIANTS", '{"challenger": {"suppressDiscretionary": "false"}}'
    )
    engine_config.invalidate()
    assert treatment_config.variants()["challenger"].suppress_discretionary is False


def test_a_negative_cost_is_refused_at_both_layers(db_tx, monkeypatch):
    with pytest.raises(engine_config.ConfigRejected):
        engine_config.coerce("TREATMENT_COST_FIELD_VISIT", -100.0)

    # And the environment is held to the same bound, which it never was: a
    # negative cost reached `ev = gross - cost` and made a doorstep visit
    # profitable.
    monkeypatch.setenv("TREATMENT_COST_FIELD_VISIT", "-100")
    engine_config.invalidate()
    assert treatment_config.costs().field_visit == 1150.0


def test_an_unpriced_action_costs_infinity_not_zero():
    book = treatment_config.costs()
    assert book.for_action("field_visit") == pytest.approx(1150.0)
    # scoring.py computes ev = gross - cost - fatigue. At 0.0 a new action
    # family added without a price would outrank every priced one on day one.
    assert book.for_action("send_carrier_pigeon") == float("inf")


def test_a_non_finite_value_is_not_a_configuration():
    for bad in ("nan", "inf", "-inf"):
        with pytest.raises(engine_config.ConfigRejected):
            engine_config.coerce("TREATMENT_MIN_EV", bad)


def test_an_unknown_key_cannot_be_written():
    with pytest.raises(engine_config.ConfigRejected):
        engine_config.coerce("TREATMENT_COST_TELEPATHY", 1.0)


def test_a_write_is_told_what_a_read_quietly_drops(db_tx):
    # The structural validators are the difference between the two paths: on a
    # write there is an operator present to be told, so redefining the control
    # arm or naming a non-existent arm is an error rather than a skipped entry.
    _require(db_tx)
    tenant = _tenant(db_tx)
    with pytest.raises(engine_config.ConfigRejected, match="built in"):
        _put(
            db_tx,
            "TREATMENT_VARIANTS",
            {"null_treatment": {"suppressDiscretionary": False}},
            tenant=tenant,
        )
    with pytest.raises(engine_config.ConfigRejected, match="unknown arm"):
        _put(db_tx, "TREATMENT_AB_SPLIT", "control:50,pateint:50", tenant=tenant)
    # ...and a split naming only real arms is accepted.
    _put(db_tx, "TREATMENT_AB_SPLIT", "control:80,null_treatment:20", tenant=tenant)


def test_reco_reads_the_same_rows_and_keeps_its_own_arms(monkeypatch):
    monkeypatch.setenv("RECO_VARIANTS", '{"holdout": {"mode": "live"}}')
    monkeypatch.setenv("RECO_AB_SPLIT", "control:50,ghost:50")
    engine_config.invalidate()
    # holdout is what "did the offer engine help at all" is measured against.
    assert reco_config.variants()["holdout"].mode == reco_config.MODE_SHADOW
    assert reco_config.ab_split() == []


# ---------------------------------------------------------------------------
# Resolution, scope and hot reload
# ---------------------------------------------------------------------------


def test_a_tenant_row_wins_over_the_environment(db_tx, monkeypatch):
    _require(db_tx)
    tenant = _tenant(db_tx)
    monkeypatch.setenv("TREATMENT_COST_FIELD_VISIT", "900")
    engine_config.invalidate()
    assert treatment_config.costs(conn=db_tx).field_visit == 900.0

    _put(db_tx, "TREATMENT_COST_FIELD_VISIT", 1400.0, tenant=tenant)
    assert treatment_config.costs(conn=db_tx).field_visit == 1400.0


def test_a_portfolio_row_wins_over_the_tenant_row(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)
    _put(db_tx, "TREATMENT_MODE", "shadow", tenant=tenant)
    _put(db_tx, "TREATMENT_MODE", "live", tenant=tenant, portfolio_id="unsecured")

    # §15.2 W8's per-portfolio mode: one book live while another stays in
    # shadow, without a second deployment.
    assert treatment_config.mode(conn=db_tx) == treatment_config.MODE_SHADOW
    assert (
        treatment_config.mode(conn=db_tx, portfolio_id="unsecured")
        == treatment_config.MODE_LIVE
    )
    assert (
        treatment_config.mode(conn=db_tx, portfolio_id="secured")
        == treatment_config.MODE_SHADOW
    )


def test_superseding_a_key_leaves_one_row_in_force(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)
    _put(db_tx, "TREATMENT_MIN_EV", 5.0, tenant=tenant)
    _put(db_tx, "TREATMENT_MIN_EV", 9.0, tenant=tenant, reason="raised the floor")

    in_force = db_tx.execute(
        text(
            "SELECT count(*) FROM engine_config"
            " WHERE tenant_id = :t AND key = 'TREATMENT_MIN_EV'"
            "   AND effective @> now()"
        ),
        {"t": tenant},
    ).scalar()
    assert in_force == 1
    assert treatment_config.policy(conn=db_tx).min_expected_value == 9.0


def test_a_row_outside_its_own_bounds_falls_back_rather_than_clamping(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)
    # Written straight past put(), the way a bound tightening after the fact
    # would leave it. A cost clamped to zero is still a free action.
    db_tx.execute(
        text(
            """
            INSERT INTO engine_config (
              id, tenant_id, portfolio_id, key, value_json, effective,
              version, changed_by, approved_by, reason
            ) VALUES (
              'CFG-legacy', :t, '', 'TREATMENT_COST_FIELD_VISIT', '-50'::jsonb,
              tstzrange(now(), NULL), 1, :m, :c, 'written before the bound'
            )
            """
        ),
        {"t": tenant, "m": MAKER, "c": CHECKER},
    )
    assert treatment_config.costs(conn=db_tx).field_visit == 1150.0


def test_the_resolver_never_raises_without_a_connection():
    # No table, no database, a broken row: the environment is the floor, and a
    # resolver that throws takes every decision in the book down with it.
    resolved, epoch = engine_config.snapshot(tenant_id="no-such-tenant")
    assert isinstance(resolved, dict)
    assert epoch is None or isinstance(epoch, int)


# ---------------------------------------------------------------------------
# The exit criterion
# ---------------------------------------------------------------------------


def test_config_version_resolves_to_a_row(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)

    # Before any row: W2's stated day-1 value, non-null and naming nothing.
    assert logging_contract.config_version(conn=db_tx).startswith("env:")

    epoch = _put(db_tx, "TREATMENT_COST_SMS", 0.25, tenant=tenant)
    stamped = logging_contract.config_version(conn=db_tx)
    assert stamped == f"cfg:{epoch}"

    # "Resolves" means the rows in force at that version can be read back.
    rows = db_tx.execute(
        text(
            "SELECT key, value_json FROM engine_config"
            " WHERE tenant_id = :t AND version <= :v AND effective @> now()"
        ),
        {"t": tenant, "v": int(stamped.split(":")[1])},
    ).mappings().all()
    assert {str(r["key"]) for r in rows} == {"TREATMENT_COST_SMS"}


def test_every_write_bumps_the_epoch(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)
    first = _put(db_tx, "TREATMENT_MIN_EV", 3.0, tenant=tenant)
    second = _put(db_tx, "TREATMENT_COST_SMS", 0.30, tenant=tenant)
    assert second == first + 1


# ---------------------------------------------------------------------------
# The structural controls
# ---------------------------------------------------------------------------


def test_a_self_approved_change_is_refused_by_the_database(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)
    with pytest.raises(Exception) as caught:
        engine_config.put(
            db_tx,
            "TREATMENT_MIN_EV",
            4.0,
            tenant_id=tenant,
            changed_by=MAKER,
            approved_by=MAKER,
            reason="approving my own change",
        )
    assert "maker_checker" in str(caught.value)


def test_a_change_without_a_reason_is_refused(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)
    with pytest.raises(engine_config.ConfigRejected):
        _put(db_tx, "TREATMENT_MIN_EV", 4.0, tenant=tenant, reason="  ")


def test_two_rows_cannot_be_in_force_for_the_same_key(db_tx):
    _require(db_tx)
    tenant = _tenant(db_tx)
    _put(db_tx, "TREATMENT_MIN_EV", 4.0, tenant=tenant)
    with pytest.raises(Exception) as caught:
        db_tx.execute(
            text(
                """
                INSERT INTO engine_config (
                  id, tenant_id, portfolio_id, key, value_json, effective,
                  version, changed_by, approved_by, reason
                ) VALUES (
                  'CFG-overlap', :t, '', 'TREATMENT_MIN_EV', '7'::jsonb,
                  tstzrange(now(), NULL), 99, :m, :c, 'a second truth'
                )
                """
            ),
            {"t": tenant, "m": MAKER, "c": CHECKER},
        )
    assert "ex_engine_config_current" in str(caught.value)
