"""Characterization of the honest-engines baseline.

These tests pin behaviour that the W0–W3 tranche must not reverse: two scorers,
the treatment pipeline order, and a hard refusal to reach a live carrier from
pytest. They do not require the new schema.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from agent_core import carrier_guard, logging_contract
from agent_core.reco.engine import recommend as reco_recommend
from agent_core.treatment.engine import recommend_treatment


BACKEND = Path(__file__).resolve().parents[1]


def _module_source(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_treatment_and_reco_remain_separate_entrypoints() -> None:
    assert reco_recommend.__module__ == "agent_core.reco.engine"
    assert recommend_treatment.__module__ == "agent_core.treatment.engine"
    treat_src = inspect.getsource(recommend_treatment)
    reco_src = inspect.getsource(reco_recommend)
    assert "agent_core.reco" not in treat_src
    assert "agent_core.treatment" not in reco_src


def test_treatment_pipeline_order_is_timing_then_veto_then_score() -> None:
    """features → candidates (timing, veto) → score → arbitrate → log."""
    src = (BACKEND / "agent_core" / "treatment" / "engine.py").read_text(
        encoding="utf-8"
    )
    generate = src.index("def _generate(")
    decide = src.index("def _decide(")
    body = src[decide : src.index("def _horizon_for(")]
    assert body.index("candidates, excluded = _generate(") < body.index(
        "scorer.score("
    )
    assert body.index("scorer.score(") < body.index("arbitration.arbitrate(")
    assert body.index("arbitration.arbitrate(") < body.index("decisions.record(")
    gen_body = src[generate:]
    assert gen_body.index("timing.plan(") < gen_body.index("policy_mod.veto(")


def test_exploration_runs_after_arbitration_chooser() -> None:
    arb = (BACKEND / "agent_core" / "treatment" / "arbitration.py").read_text(
        encoding="utf-8"
    )
    assert "chooser(" in arb
    assert arb.index("if chooser is not None") > arb.index("affordable")


def test_logging_contract_keeps_arm_and_action_apart() -> None:
    drawn = logging_contract.draw(
        ["sms", "whatsapp"],
        greediness=0.5,
        arm_probability=0.4,
        nonce="abc",
        subject_id="c1",
        trigger_kind="bounce",
    )
    assert drawn is not None
    assert 0 < drawn.arm_propensity <= 1
    assert 0 < drawn.action_propensity <= 1
    assert drawn.propensity == pytest.approx(
        drawn.arm_propensity * drawn.action_propensity, rel=1e-9
    )
    greedy = logging_contract.draw(["sms"], greediness=1.0, arm_probability=1.0)
    assert greedy is not None
    assert greedy.action_propensity == 1.0
    assert greedy.kind == logging_contract.KIND_GREEDY


def test_carrier_guard_blocks_pytest_without_override() -> None:
    with pytest.raises(carrier_guard.RealCarrierRefused):
        carrier_guard.refuse_real_carrier("twilio.voice")


def test_real_adapters_call_the_carrier_guard() -> None:
    voice = (BACKEND / "voice" / "twilio_ops.py").read_text(encoding="utf-8")
    sms = (BACKEND / "twilio_sms.py").read_text(encoding="utf-8")
    wa = (BACKEND / "whatsapp.py").read_text(encoding="utf-8")
    assert "refuse_real_carrier" in voice
    assert "refuse_real_carrier" in sms
    assert "refuse_real_carrier" in wa


def test_offer_decisions_table_is_not_retired_this_tranche() -> None:
    sql = (BACKEND / "sql" / "06_sales.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS offer_decisions" in sql
    engine = (BACKEND / "agent_core" / "reco" / "engine.py").read_text(
        encoding="utf-8"
    )
    assert "offer_decisions" in (
        BACKEND / "agent_core" / "reco" / "decisions.py"
    ).read_text(encoding="utf-8")
    assert "treatment_decisions" not in engine
