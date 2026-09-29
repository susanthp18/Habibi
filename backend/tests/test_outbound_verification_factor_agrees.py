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

_BRIEF = {"firstName": "Susanth", "brief": "Their account is overdue.", "allowedOffers": []}


def test_the_briefing_still_asks_for_the_borrower_by_name() -> None:
    """Right-party contact, which the outbound_opens_by_confirming grader pins."""
    assert "ask for Susanth by name" in mission.briefing(_BRIEF)


def test_a_mission_without_offers_forbids_pitching_but_not_answering() -> None:
    brief = mission.briefing(_BRIEF)
    assert "Do NOT mention any product" in brief
    assert "unless they ask about one first" in brief
    assert "never recommend or pitch" in brief


def test_a_voice_studio_brief_gives_the_situation_not_a_verification_answer() -> None:
    """Run 66: the brief's "account ending 2324" matched the registered mobile,
    and the agent called verify_identity with it before the customer spoke."""
    m = {**_BRIEF, "context": {
        "position": {"outstandingInr": 62400, "minimumDueInr": 4800, "dpd": 32, "accountTail": "2324"},
        "promise": {"amountInr": 4000, "promisedDate": "2026-10-10", "status": "upcoming"},
    }}
    brief = mission.studio_briefing(m)
    assert brief.startswith("Why you are calling: Their account is overdue.")
    assert "promised" in brief and "Do NOT mention any product" in brief
    for legacy in ("2324", "get_account_position", "by name", "OUTBOUND CALL"):
        assert legacy not in brief
