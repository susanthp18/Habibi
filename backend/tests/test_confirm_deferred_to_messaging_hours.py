"""A statutory promise confirmation outside messaging hours waits for them (run 90)."""

from datetime import datetime, timezone

import promise_fulfillment as pf


def test_the_next_slot_is_this_mornings_or_tomorrows_0815_ist():
    evening = datetime(2026, 9, 30, 16, 20, tzinfo=timezone.utc)   # 21:50 IST
    early = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc)       # 06:30 IST
    assert pf._next_messaging_slot(evening) == datetime(2026, 10, 1, 2, 45, tzinfo=timezone.utc)
    assert pf._next_messaging_slot(early) == datetime(2026, 9, 30, 2, 45, tzinfo=timezone.utc)


def test_a_deferred_confirmation_is_not_called_an_opt_out_or_a_follow_up():
    spoken = pf._spoken(amount=5000, promised_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
                        channel=None, last4="2324", suppressed=True, deferred=True)
    assert "in the morning" in spoken
    assert "opted out" not in spoken and "follow up" not in spoken
