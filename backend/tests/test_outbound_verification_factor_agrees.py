"""Every place that tells the outbound agent how to verify says the same thing.

The factor moved to the last four digits of the registered mobile in
``verify_identity``, the ``confirm_identity`` node and the verify-and-disclose
pack. Two owners were missed: the runtime directive in
``voice/node_contracts.py`` still asked for "the confirmation question", and
``mission.briefing`` still said "open by confirming you are speaking to
{first}". On VS-8C1B760F1B the node prompt the model received carried both
ceremonies back to back; the call before it asked for a first name.
"""

from __future__ import annotations

import mission
from voice.flow_export import built_in_collections_graph
from voice.node_contracts import NODE_DIRECTIVES

_BRIEF = {"firstName": "Susanth", "brief": "Their account is overdue.", "allowedOffers": []}


def _node_prompt() -> str:
    node = next(n for n in built_in_collections_graph()["nodes"] if n["key"] == "confirm_identity")
    return node["data"]["instructions"]


def test_every_owner_names_the_last_four_digits() -> None:
    for text in (_node_prompt(), NODE_DIRECTIVES["confirm_identity"], mission.briefing(_BRIEF)):
        assert "last four digits" in text


def test_no_owner_treats_a_spoken_confirmation_as_verification() -> None:
    for text in (NODE_DIRECTIVES["confirm_identity"], mission.briefing(_BRIEF)):
        low = text.lower()
        assert "confirmation question" not in low
        assert "open by confirming you are speaking to" not in low
        assert "not verification" in low


def test_the_briefing_still_asks_for_the_borrower_by_name() -> None:
    """Right-party contact, which the outbound_opens_by_confirming grader pins."""
    assert "ask for Susanth by name" in mission.briefing(_BRIEF)


def test_a_mission_without_offers_forbids_pitching_but_not_answering() -> None:
    brief = mission.briefing(_BRIEF)
    assert "Do NOT mention any product" in brief
    assert "unless they ask about one first" in brief
    assert "never recommend or pitch" in brief
