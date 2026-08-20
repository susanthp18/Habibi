"""Agent Card compiler — G0–G8. Empty card is legacy; invalid card cannot publish."""

from __future__ import annotations

from agent_core.cards.compile import compile_card
from agent_core.cards.defaults import (
    COLLECTIONS_BOT_ID,
    INTAKE_BOT_ID,
    INSURANCE_BOT_ID,
    card_dump,
    card_for,
)
from agent_core.tools.catalog import CATALOG


def _compile(bot_id: str, card=None, flow=None, bots=None):
    raw = card if card is not None else card_dump(bot_id)
    return compile_card(
        bot_id=bot_id,
        card_raw=raw,
        flow=flow or {},
        catalog_names=set(CATALOG.specs),
        known_bot_ids=bots or {COLLECTIONS_BOT_ID, INTAKE_BOT_ID, INSURANCE_BOT_ID, "supervisor-brief"},
    )


def test_four_first_party_cards_compile_clean() -> None:
    for bot_id in (INTAKE_BOT_ID, COLLECTIONS_BOT_ID, INSURANCE_BOT_ID, "supervisor-brief"):
        report = _compile(bot_id)
        blocking = [g.gate for g in report.blocking]
        assert blocking == [], f"{bot_id} blocked on {blocking}: {report.model_dump()}"


def test_empty_card_is_legacy_not_fake_green() -> None:
    report = compile_card(
        bot_id=COLLECTIONS_BOT_ID,
        card_raw={},
        flow={},
        catalog_names=set(CATALOG.specs),
        known_bot_ids={COLLECTIONS_BOT_ID},
    )
    g0 = next(g for g in report.gates if g.gate == "G0")
    assert g0.status == "skipped"
    assert report.ok


def test_unbinding_reco_fails_g3() -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    dumped = card.model_dump()
    dumped["policy_bindings"]["reco"] = "off"
    report = _compile(COLLECTIONS_BOT_ID, card=dumped)
    g0 = next(g for g in report.gates if g.gate == "G0")
    assert g0.status == "fail"


def test_unknown_tool_fails_g4() -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    dumped = card.model_dump()
    dumped["tools"]["include"] = [*dumped["tools"]["include"], "apply_magic_waiver"]
    report = _compile(COLLECTIONS_BOT_ID, card=dumped)
    g4 = next(g for g in report.gates if g.gate == "G4")
    assert g4.status == "fail"


def test_handoff_to_missing_bot_fails_g5() -> None:
    card = card_for(COLLECTIONS_BOT_ID)
    dumped = card.model_dump()
    dumped["handoffs"] = [{"to_bot_id": "legal-v1", "payload_schema": {}, "when": "legal"}]
    report = _compile(COLLECTIONS_BOT_ID, card=dumped)
    g5 = next(g for g in report.gates if g.gate == "G5")
    assert g5.status == "fail"


def test_eval_gates_are_skipped_not_green_when_flags_off(monkeypatch) -> None:
    monkeypatch.delenv("EVAL_GATE_ENABLED", raising=False)
    monkeypatch.delenv("REDTEAM_GATE_ENABLED", raising=False)
    report = _compile(COLLECTIONS_BOT_ID)
    g7 = next(g for g in report.gates if g.gate == "G7")
    g8 = next(g for g in report.gates if g.gate == "G8")
    assert g7.status == "skipped"
    assert g8.status == "skipped"


def test_eval_gate_fails_closed_when_flag_on_and_no_report(monkeypatch) -> None:
    monkeypatch.setenv("EVAL_GATE_ENABLED", "true")
    report = _compile(COLLECTIONS_BOT_ID)
    g7 = next(g for g in report.gates if g.gate == "G7")
    assert g7.status == "fail"
    assert not report.ok


def test_g12_and_g14_are_honest_on_first_party_cards() -> None:
    report = _compile(COLLECTIONS_BOT_ID)
    g12 = next(g for g in report.gates if g.gate == "G12")
    g13 = next(g for g in report.gates if g.gate == "G13")
    g14 = next(g for g in report.gates if g.gate == "G14")
    assert g12.status == "pass"
    assert g13.status == "skipped"
    assert g14.status == "skipped"
    assert report.ok
