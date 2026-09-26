"""Rehearsing an outbound scenario runs the outbound door, not "how can I help you today?"."""

from types import SimpleNamespace

import mission
from agent_core.cards.defaults import _collections_outbound

CARD = SimpleNamespace(outbound=_collections_outbound())
RAHUL = {"name": "Rahul Sharma", "dpd": 12, "overdue": 18450, "language": "English"}


def test_a_typed_persona_gets_the_cards_outbound_mission():
    m = mission.rehearsal(None, card=CARD, objective="dpd_reminder", persona=RAHUL)
    assert m["rehearsal"] is True
    assert m["objective"] == "dpd_reminder"
    assert m["entryNode"] == "confirm_identity"
    assert m["firstName"] == "Rahul" and m["customerName"] == "Rahul Sharma"
    assert m["allowedOffers"] == [] and "cross_sell" in m["prohibited"]

    brief = mission.briefing(m)
    assert brief.startswith("OUTBOUND CALL")
    assert "ask for Rahul by name" in brief
    assert "18,450" in brief and "12 days overdue" in brief


def test_an_objective_the_card_does_not_run_falls_back_to_its_first():
    m = mission.rehearsal(None, card=CARD, objective="cross_sell", persona=RAHUL)
    assert m["objective"] == CARD.outbound.objectives[0].key
    assert m["entryNode"] == "confirm_identity"


def test_no_card_and_no_figures_still_briefs_the_direction():
    m = mission.rehearsal(None, card=None, objective=None, persona={"name": "Neha"})
    assert m["objective"] == "dpd_reminder"
    assert m["context"] == {}
    assert mission.briefing(m).startswith("OUTBOUND CALL")
