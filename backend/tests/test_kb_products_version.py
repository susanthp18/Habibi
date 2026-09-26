"""Product profiles are never downgraded by older code running beside newer code.

On 2026-09-25 the old worker and the new code each read the other's fingerprint
as stale and regenerated every five minutes, the old one with its older prompt.
"""

from __future__ import annotations

import kb_products


def test_the_same_version_and_documents_are_current(monkeypatch):
    monkeypatch.setattr(kb_products, "PROFILE_VERSION", "2026-09-25.4")
    assert kb_products._current("2026-09-25.4:abc", "2026-09-25.4:abc")


def test_changed_documents_regenerate(monkeypatch):
    monkeypatch.setattr(kb_products, "PROFILE_VERSION", "2026-09-25.4")
    assert not kb_products._current("2026-09-25.4:abc", "2026-09-25.4:def")


def test_a_profile_from_newer_code_is_left_alone(monkeypatch):
    monkeypatch.setattr(kb_products, "PROFILE_VERSION", "2026-09-25.4")
    assert kb_products._current("2026-09-26.1:abc", "2026-09-25.4:def")


def test_older_and_unstamped_profiles_regenerate(monkeypatch):
    monkeypatch.setattr(kb_products, "PROFILE_VERSION", "2026-09-25.4")
    assert not kb_products._current("2026-09-25.1:abc", "2026-09-25.4:abc")
    assert not kb_products._current("0f3a9c", "2026-09-25.4:abc")
    assert not kb_products._current(None, "2026-09-25.4:abc")


_TITLES = [
    "Personal Accident Protect360",
    "Travel Protect360",
    "Choice Protect360",
    "Fraud Protect360",
]


def test_the_brand_is_read_off_the_catalog():
    assert kb_products.brand_words(_TITLES) == ["Protect360"]
    assert kb_products.brand_words(["Gold Card", "Silver Card"]) == []


def test_other_names_are_read_off_the_documents():
    texts = [
        "Can my children be included in the Family Protect360?",
        "How do I make a claim for my Family Protect360 Insurance?",
        "Personal Accident Protect360 covers you worldwide.",  # its own title
        "Unlike Travel Protect360, this plan ...",  # another product's name
    ]
    got = kb_products.names_in_documents(
        texts, ["Protect360"], "Personal Accident Protect360", [t for t in _TITLES if not t.startswith("Personal")]
    )
    assert got == {"Family Protect360": 2}


def test_a_variant_of_the_own_title_is_not_a_new_name():
    got = kb_products.names_in_documents(
        ["Choice Protect360 Gold gives more.", "The Choice Protect360 plan"],
        ["Protect360"],
        "Choice Protect360",
        ["Travel Protect360"],
    )
    assert got == {}


def test_a_name_goes_to_the_product_whose_documents_use_it_most():
    assigned = kb_products.assign_names(
        {
            "personal_accident": {"Family Protect360": 6},
            "choice": {"Family Protect360": 1, "Choice Protect360 Gold": 2},
            "travel": {"Shared Protect360": 1},
            "home": {"Shared Protect360": 1},
        }
    )
    assert assigned == {"personal_accident": ["Family Protect360"], "choice": ["Choice Protect360 Gold"]}
