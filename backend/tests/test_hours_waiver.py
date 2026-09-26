"""The calling-window rule judges a contact attempt once, the way admission did."""

from datetime import datetime, timezone

from agent_core.live_qa.checks import TurnFacts, check_hours
from agent_core.live_qa.scorecard import _hours_fail

WINDOW = (8, 19)
AT_2004_IST = datetime(2026, 9, 25, 14, 34, tzinfo=timezone.utc)


def test_a_waived_demo_dial_is_not_rejudged_every_turn():
    """VS-36E9E26C13: admitted by operator waiver, flagged critical on all five bot turns."""
    facts = TurnFacts(now_hour=20, direction="outbound", hours_waived=True)
    assert check_hours(facts) is None


def test_an_unwaived_dial_after_hours_still_fails():
    assert check_hours(TurnFacts(now_hour=20, direction="outbound")) is not None


def test_post_call_scoring_follows_the_same_rule():
    row = {"channel": "voice", "started_at": AT_2004_IST}
    assert _hours_fail({**row, "direction": "outbound", "source_payload": {}}, WINDOW)
    # The caller rang us; the window governs contact attempts, not answers.
    assert not _hours_fail({**row, "direction": "inbound", "source_payload": {}}, WINDOW)
    assert not _hours_fail(
        {**row, "direction": "outbound", "source_payload": {"environment": "sandbox"}}, WINDOW
    )
    assert not _hours_fail({**row, "direction": "outbound", "source_payload": {"hoursWaived": True}}, WINDOW)
