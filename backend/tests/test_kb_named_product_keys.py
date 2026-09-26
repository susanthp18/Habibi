"""Which product did the caller name? Whole words that tell products apart.

The Protect360 corpus (``scripts/kb_corpus_manifest.py``) has nine products
whose titles all end in "Protect360". The old matcher took words longer than
three letters as substrings, so ``car`` could never match -- "car protect"
named nothing -- while the shared ``protect360`` matched all nine at once.
"""

from __future__ import annotations

import pytest

from agent_core.tools.kb_plan import _named_product_keys

_CORPUS = [
    {"productKey": key, "title": title}
    for key, title in [
        ("car", "Car Protect360"),
        ("choice", "Choice Protect360"),
        ("early", "Early Protect360 Plus"),
        ("fraud", "Fraud Protect360"),
        ("home", "Home Protect360"),
        ("hospital", "Hospital Protect360"),
        ("maid", "Maid Protect360"),
        ("personal_accident", "Personal Accident Protect360"),
        ("travel", "Travel Protect360"),
    ]
]


@pytest.mark.parametrize(
    "said, expected",
    [
        ("tell me about car protect", ["car"]),
        ("what does Car Protect360 cover", ["car"]),
        ("my car", ["car"]),
        ("the personal accident one", ["personal_accident"]),
        ("travel and home please", ["home", "travel"]),
    ],
)
def test_a_named_product_is_found(said: str, expected: list[str]) -> None:
    assert sorted(_named_product_keys(said, _CORPUS)) == expected


@pytest.mark.parametrize(
    "said",
    [
        "tell me about protect 360",  # the shared suffix names none of them
        "the card protect 360",  # "card" is not "car"; ambiguous stays unnamed
        "is there a scar on my record",  # a substring is not a word
        "homework",
        "plus the fees",  # a generic title word
        "",
    ],
)
def test_nothing_is_named_by_a_word_that_does_not_single_one_out(said: str) -> None:
    assert _named_product_keys(said, _CORPUS) == []


def test_a_one_product_corpus_is_named_by_its_brand_even_when_split() -> None:
    only = [{"productKey": "travel", "title": "Travel Protect360"}]
    assert _named_product_keys("does protect 360 cover delays", only) == ["travel"]
