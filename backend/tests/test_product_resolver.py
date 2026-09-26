"""Semantic product routing: which product a question is about, and when not to say.

Pure -- no database, no model: vectors are hand-built so each case is about the
decision rule, not the embedding. The embedding itself is measured against real
phrasings by scripts/eval_product_routing.py.
"""

from __future__ import annotations

import pytest

from agent_core import product_resolver as pr
from agent_core.product_resolver import ProductProfile, ProductRouter

_CATALOG = [
    ProductProfile("travel", "Travel Protect360", "Cover for trips abroad."),
    ProductProfile("car", "Car Protect360"),
    ProductProfile("home", "Home Protect360"),
    ProductProfile("early", "Early Protect360 Plus"),
    ProductProfile("personal_accident", "Personal Accident Protect360"),
    ProductProfile("collections", "BigTapp Bank Collections"),
]

# One axis per product, plus one no product lives on. Similarity is cosine,
# so magnitude means nothing: "far from every product" has to point elsewhere.
_AXES = {p.key: i for i, p in enumerate(_CATALOG)} | {"elsewhere": len(_CATALOG)}


def _vec(**weights: float) -> list[float]:
    v = [0.0] * len(_AXES)
    for key, w in weights.items():
        v[_AXES[key]] = w
    return v


def _router(extra: list[tuple[str, str, list[float]]] | None = None) -> ProductRouter:
    utterances = [(p.key, p.title, _vec(**{p.key: 1.0})) for p in _CATALOG] + (extra or [])
    return ProductRouter(_CATALOG, utterances)


@pytest.fixture(autouse=True)
def _thresholds(monkeypatch):
    monkeypatch.setenv("KB_ROUTE_MIN_SCORE", "0.5")
    monkeypatch.setenv("KB_ROUTE_MIN_MARGIN", "0.1")
    monkeypatch.setenv("KB_ROUTE_SOFT_MIN_SCORE", "0.3")


# -- speech-shaped names -----------------------------------------------------


@pytest.mark.parametrize(
    "said, expected",
    [
        ("Protect360", "protect360"),
        ("protect 360", "protect360"),
        ("protect three sixty", "protect360"),
        ("protect three six zero", "protect360"),
        ("protect three hundred and sixty", "protect360"),
        ("Maid's cover", "maid s cover"),
    ],
)
def test_normalize_makes_a_spoken_title_match_a_written_one(said, expected):
    assert pr.normalize(said) == expected


@pytest.mark.parametrize(
    "said, expected",
    [
        ("tell me about car protect", ["car"]),
        ("home protect three sixty please", ["home"]),
        ("early protect 360 plus", ["early"]),
        ("travel protect360 and home protect360", ["travel", "home"]),
        ("the card protect 360", []),  # "card" is not "car"
        ("can I pay early", []),  # a common word is not a title
        ("protect 360", []),  # the shared brand names no product
    ],
)
def test_a_title_said_outright_is_found(said, expected):
    assert _router().titles_named(said) == expected


def test_a_tool_argument_is_validated_against_the_catalog():
    router = _router()
    assert router.match_key("travel") == "travel"
    assert router.match_key("Travel Protect360") == "travel"
    assert router.match_key("personal accident") == "personal_accident"
    assert router.match_key("personal_accident") == "personal_accident"
    assert router.match_key("spaceflight") is None
    assert router.match_key("") is None


# -- routing -----------------------------------------------------------------


def test_a_clear_winner_scopes():
    route = _router().route(_vec(travel=0.9, home=0.2))
    assert route.tier == pr.ROUTED and route.keys == ("travel",)
    assert route.scoped


def test_a_title_beats_the_embedding():
    route = _router().route(_vec(travel=0.9), text="what about home protect 360")
    assert route.tier == pr.NAMED and route.keys == ("home",)


def test_too_close_to_call_falls_back_to_what_the_call_settled_on():
    route = _router().route(_vec(travel=0.6, home=0.55), fallback=["travel"])
    assert route.tier == pr.FALLBACK and route.keys == ("travel",)


def test_too_close_to_call_with_nothing_settled_searches_everything_and_boosts():
    route = _router().route(_vec(travel=0.6, home=0.55))
    assert route.tier == pr.UNCERTAIN
    assert not route.scoped
    assert set(route.candidates) == {"travel", "home"}


def test_nothing_near_any_product_is_not_scoped():
    route = _router().route(_vec(elsewhere=1.0, travel=0.1, home=0.1))
    assert route.tier == pr.NONE and not route.scoped


def test_a_collections_fallback_does_not_capture_an_insurance_question():
    """VS-7956F27B36: a travel question on a collections node went to the collections FAQ."""
    route = _router().route(_vec(travel=0.45, home=0.42), fallback=["collections"])
    assert route.tier == pr.UNCERTAIN
    assert not route.scoped


def test_a_collections_fallback_still_holds_for_a_collections_question():
    route = _router().route(_vec(collections=0.45, travel=0.4), fallback=["collections"])
    assert route.tier == pr.FALLBACK and route.keys == ("collections",)


def test_an_unknown_fallback_is_ignored():
    route = _router().route(_vec(elsewhere=1.0, travel=0.1), fallback=["spaceflight"])
    assert route.tier == pr.NONE


def test_a_phrasing_that_fits_two_products_is_dropped():
    shared = _vec(travel=0.7, home=0.7)
    router = _router(extra=[("travel", "what does it cover", shared), ("home", "what does it cover?", shared)])
    assert router.excluded == 2
    assert router.utterance_count == len(_CATALOG)


def test_is_product_question_ignores_collections():
    router = _router()
    assert router.is_product_question(_vec(travel=0.8))
    assert not router.is_product_question(_vec(collections=0.8))
    assert not router.is_product_question(_vec(elsewhere=1.0, travel=0.1))


def test_an_empty_router_never_scopes():
    route = ProductRouter(()).route([0.1, 0.2], text="travel protect360", fallback=["travel"])
    assert route.tier == pr.NONE and not route.scoped


def test_a_question_about_any_product_is_not_pinned_on_one():
    """"What are the exclusions" scored 0.77 against Early Protect360 before the
    generic class existed, and would have hidden every other product's wording."""
    generic = [(pr.GENERIC_KEY, "what are the exclusions", _vec(elsewhere=1.0))]
    router = _router(extra=generic)
    asked = _vec(elsewhere=1.0, early=0.6)
    assert router.route(asked).tier == pr.GENERAL
    assert not router.route(asked).scoped
    # ...but on a call already about travel, it is about travel.
    assert router.route(asked, fallback=["travel"]).keys == ("travel",)
    # ...and it is still an insurance question, not a collections one.
    assert router.is_product_question(asked)


def test_a_product_phrasing_that_reads_generic_is_dropped():
    generic = [(pr.GENERIC_KEY, "how do I claim", _vec(elsewhere=1.0))]
    near_generic = [("early", "how do I make a claim", _vec(elsewhere=1.0, early=0.2))]
    router = _router(extra=generic + near_generic)
    assert router.excluded == 1


def test_a_generic_phrasing_that_points_at_one_product_is_dropped():
    """The model wrote "home burglary coverage?" into the generic class; it would
    have swallowed every burglary question Home Protect360 answers."""
    generic = [(pr.GENERIC_KEY, "home burglary coverage?", _vec(home=0.8, elsewhere=0.6))]
    router = _router(extra=generic)
    assert router.excluded == 1
    assert router.route(_vec(home=0.9, elsewhere=0.3)).keys == ("home",)


def test_other_names_from_the_documents_match_exactly():
    catalog = [
        ProductProfile("personal_accident", "Personal Accident Protect360", names=("Family Protect360",)),
        ProductProfile("home", "Home Protect360"),
    ]
    router = ProductRouter(catalog)
    assert router.titles_named("my family protect three sixty policy") == ["personal_accident"]
    assert router.titles_named("personal accident please") == ["personal_accident"]
    assert router.titles_named("my family") == []
