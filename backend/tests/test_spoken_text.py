"""Text that reaches Azure TTS must be text a person could say aloud.

These lock in the fix for the transcript corruption on call VS-6B252E0479
(2026-08-01), where the model's parenthetical asides produced duplicated spans
in both the assistant context and the CRM transcript:

    turn 15 [bot] ... what's the age range of the travellers roughly)? (roughly)?
    turn 17 [bot] ... or highest cover Basic, Silver /Gold, or Platinum)? (Basic, Silver/Gold, or Platinum)?

Azure's word-boundary events never reported the bracket-adjacent tokens, so
``AggregatedFrameSequencer`` emitted them once as passthrough and again from
``force_complete``. Removing the brackets before synthesis removes the trigger.
"""

from __future__ import annotations

import asyncio

import pytest

from voice.spoken_text import SpokenTextFilter, to_spoken


# ------------------------------------------------------------------ brackets


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The exact strings from the call that broke.
        (
            "what's the age range of the travellers (roughly)?",
            "what's the age range of the travellers roughly?",
        ),
        (
            "(and is it for you only or for family too)?",
            "and is it for you only or for family too?",
        ),
        # The words inside a bracket carry meaning — keep them, drop the marks.
        ("cover for an adult (up to age 70)", "cover for an adult up to age 70"),
        ("see [the schedule] and {terms}", "see the schedule and terms"),
    ],
)
def test_brackets_are_removed_and_their_contents_kept(raw: str, expected: str) -> None:
    assert to_spoken(raw) == expected


def test_no_bracket_characters_survive() -> None:
    out = to_spoken("a (b) [c] {d} <e>")
    assert not any(ch in out for ch in "()[]{}<>")


# ------------------------------------------------------------- other markup


def test_markdown_emphasis_is_stripped() -> None:
    assert to_spoken("Use **bold** and _italics_ and `code`.") == "Use bold and italics and code."


def test_slash_alternatives_become_spoken_alternatives() -> None:
    """Azure reads "Basic/Silver/Gold" as one run-on token; a caller needs the "or"."""
    assert to_spoken("choose Basic/Silver/Gold") == "choose Basic or Silver or Gold"


def test_dates_and_numbers_keep_their_slashes() -> None:
    """The rule is letter/letter only — a date must not become "01 or 08"."""
    assert to_spoken("due on 01/08/2026") == "due on 01/08/2026"


def test_plain_text_is_untouched() -> None:
    line = "Your outstanding balance is sixty two thousand four hundred rupees."
    assert to_spoken(line) == line


# -------------------------------------------------------------- chunk safety


def test_a_bracket_split_across_chunks_still_resolves() -> None:
    """``filter`` runs per aggregated chunk, so an opener and its closer can
    arrive in different calls. Every rule is character-local for this reason."""
    assert to_spoken("travellers (rough") + to_spoken("ly)? next") == "travellers roughly? next"


def test_boundary_whitespace_is_preserved() -> None:
    """Chunks are concatenated downstream — eating an edge space glues words."""
    assert to_spoken(" and then ") == " and then "


def test_whitespace_only_chunk_passes_through() -> None:
    assert to_spoken(" ") == " "
    assert to_spoken("") == ""


# ------------------------------------------------------------ filter adapter


def test_filter_delegates_and_survives_the_lifecycle_hooks() -> None:
    f = SpokenTextFilter()

    async def run() -> str:
        await f.update_settings({"anything": True})
        await f.handle_interruption()
        await f.reset_interruption()
        return await f.filter("hello (there)")

    # Stateless by construction: the hooks must not change the outcome.
    assert asyncio.run(run()) == "hello there"
