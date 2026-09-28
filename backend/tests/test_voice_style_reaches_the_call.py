"""VOICE-3: the Voice tab's speaking-style selector was dead config -- the
preview ignored it and the runtime derived a style from warmth alone."""

from __future__ import annotations


def test_a_missions_per_day_lowers_the_daily_cap() -> None:
    """OUTBOUND-09 / RUNTIME-11: `cadence.per_day` bounded nothing at runtime."""
    from contact_policy import daily_cap

    assert daily_cap(card_cap=1) == 1
    assert daily_cap(card_cap=99) == daily_cap()
