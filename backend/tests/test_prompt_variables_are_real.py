"""Every variable the Studio's palette offers must produce a real value.

The palette is a promise: a token listed there substitutes at call start. Two of
the four did not.

``{time_of_day}`` substituted the literal string ``"day"`` — ``default_context``
hardcoded it and nothing anywhere computed it — so a prompt saying "greet the
caller, it is {time_of_day}" said "it is day" at 2 AM. ``{language}`` substituted
``"English"`` on every voice call regardless of the card, because
``voice.bot._system_instruction_from_bundle`` took an optional ``context`` that
its only caller never passed.

Both failures are silent by construction: the token renders, lint passes, and the
output is a grammatical sentence carrying the wrong word. Only reading a live
transcript would have caught either. These tests read the render instead.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from agent_core import clock
from agent_core.prompt import default_context
from prompt_render import SYSTEM_SAFE_VARIABLES, render_system_prompt

IST = ZoneInfo("Asia/Kolkata")


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, "night"),
        (4, "night"),
        (5, "morning"),
        (11, "morning"),
        (12, "afternoon"),
        (16, "afternoon"),
        (17, "evening"),
        (20, "evening"),
        (21, "night"),
        (23, "night"),
    ],
)
def test_part_of_day_names_the_hour_a_person_would(hour: int, expected: str) -> None:
    assert clock.part_of_day(datetime(2026, 8, 22, hour, 30, tzinfo=IST)) == expected


def test_time_of_day_is_never_the_word_day() -> None:
    """The old hardcoded value, which no operator would ever have written."""
    value = default_context()["time_of_day"]
    assert value != "day"
    assert value in {"morning", "afternoon", "evening", "night"}


def test_time_of_day_tracks_the_tenant_clock_not_the_container() -> None:
    """Containers run UTC; the caller does not.

    Asserted as a relationship rather than a fixed value so the test does not
    itself depend on when it runs — which is the bug it guards, one level up.
    """
    assert default_context()["time_of_day"] == clock.part_of_day(clock.now_local())


def test_every_palette_variable_substitutes_to_something_speakable() -> None:
    """No offered token may survive its own render, or render to an empty string.

    A surviving token is read aloud as "open brace language close brace"; an
    empty one produces "Speak in ." Both were reachable.
    """
    template = " ".join(f"[{name}={{{name}}}]" for name in sorted(SYSTEM_SAFE_VARIABLES))
    rendered = render_system_prompt(template, default_context())

    for name in SYSTEM_SAFE_VARIABLES:
        assert f"{{{name}}}" not in rendered, f"{name} was not substituted"
        assert f"[{name}=]" not in rendered, f"{name} substituted to an empty string"
