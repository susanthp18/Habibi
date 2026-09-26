"""A retrieval result says what kind of answer it is, and does not overclaim.

Live failure, CV-SUSANTH-WA1 on 2026-09-11. A customer asked three times for
travel-insurance benefits. The planner chose ``mode="catalog"``, which skipped
retrieval entirely, and the model was handed exactly this::

    {"results": [{"docTitle": "Travel Protect360",
                  "docType": "catalog",
                  "snippet": "Travel Protect360",
                  "score": null}],
     "confident": true,
     "answer_policy": "Answer ONLY from these snippets..."}

The model refused, correctly — there is nothing in a product name to answer
from. Nothing errored, every turn logged ``succeeded``, and the same corpus
returns the benefits table at 0.649-0.692 when asked.

Three separate defects, one per section below:

* a catalog verdict discarded retrieval even when the caller had named one
  product — and the planner is *not* stable on that boundary, so it cannot be
  fixed by getting the verdict right;
* ``confident`` meant "the list is non-empty", which a title-only row satisfies;
* both channel adapters dropped ``mode``, so no reader — model, operator or
  test — could tell that no search had run.
"""

from __future__ import annotations

import pytest

from agent_core.tools import kb


class _FakeRetrieve:
    def __init__(self, rows=None):
        self.calls: list[dict] = []
        self._rows = rows if rows is not None else []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": self._rows, "latencyMs": 12, "logId": "LOG-1", "margin": 0.2}

    @property
    def last(self) -> dict:
        return self.calls[-1]


def _passages(n: int = 3):
    return [
        {
            "chunkId": f"CH-{i}",
            "docTitle": "Travel Protect360 — Benefits",
            "docType": "benefits",
            "heading": f"Travel Protect360 — Benefits · §{i}",
            "snippet": "Overseas Medical Expenses is $150,000 for the Basic plan.",
            "score": 0.69 - (i * 0.01),
        }
        for i in range(n)
    ]


_TRAVEL = [{"productKey": "travel", "title": "Travel Protect360",
            "docTypes": ["benefits", "policy"], "docCount": 2}]


@pytest.fixture
def travel_catalog(monkeypatch):
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "catalog", lambda **kw: list(_TRAVEL))


@pytest.fixture
def plan(monkeypatch):
    """Pin the planner's verdict; these tests are about what happens after it."""
    from agent_core.tools import kb_plan

    def _set(mode: str, product_keys=None, prefer_policy: bool = False):
        monkeypatch.setattr(
            kb_plan,
            "plan_retrieval",
            lambda **kw: kb_plan.RetrievalPlan(
                mode=mode,
                query="Travel Protect360 benefits",
                product_keys=product_keys,
                prefer_policy=prefer_policy,
                source=kb_plan.SOURCE_LLM,
            ),
        )

    return _set


# ---------------------------------------------------------------------------
# A catalog verdict must not throw the answer away
# ---------------------------------------------------------------------------


def test_a_catalog_plan_scoped_to_one_product_still_retrieves(
    monkeypatch, travel_catalog, plan
):
    """"I am looking for travel insurance" wants what it covers, not its name."""
    import kb_retrieve

    fake = _FakeRetrieve(_passages())
    monkeypatch.setattr(kb_retrieve, "retrieve", fake)
    plan("catalog", product_keys=["travel"])

    result = kb.search_knowledge_base(
        query="travel insurance",
        channel="text",
        customer_text="i am looking for travel insurance",
        intent="product_faq",
    )
    assert fake.calls, "a scoped catalog plan must still search the corpus"
    assert fake.last["product_keys"] == ["travel"]
    data = result.data
    assert data["mode"] == "catalog"
    # The product list leads, the passages follow.
    assert data["results"][0]["docType"] == "catalog"
    assert any(r["docType"] == "benefits" for r in data["results"])
    assert data["confident"] is True


def test_an_unscoped_catalog_plan_still_skips_retrieval(monkeypatch, travel_catalog, plan):
    """"What do you sell" has no passage to find; searching for it wastes a turn."""
    import kb_retrieve

    fake = _FakeRetrieve(_passages())
    monkeypatch.setattr(kb_retrieve, "retrieve", fake)
    plan("catalog", product_keys=None)

    result = kb.search_knowledge_base(
        query="list all insurance products",
        channel="text",
        customer_text="what insurance plans do you offer?",
        intent="product_faq",
    )
    assert fake.calls == []
    assert result.data["mode"] == "catalog"


def test_chunk_ids_stay_aligned_with_the_rows_the_model_was_shown(
    monkeypatch, travel_catalog, plan
):
    """The RTVI rag.hits event reports these; a shift misattributes a passage."""
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(_passages(2)))
    plan("catalog", product_keys=["travel"])

    data = kb.search_knowledge_base(
        query="travel insurance",
        channel="text",
        customer_text="i am looking for travel insurance",
        intent="product_faq",
    ).data
    assert len(data["chunkIds"]) == len(data["results"])
    # One catalog row with no chunk behind it, then the two real ones.
    assert data["chunkIds"] == ["", "CH-0", "CH-1"]


# ---------------------------------------------------------------------------
# `confident` means answerable
# ---------------------------------------------------------------------------


def test_a_product_name_is_not_an_answer(monkeypatch, travel_catalog, plan):
    """The exact payload that reached the model on the failing turn."""
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve([]))
    plan("catalog", product_keys=None)

    data = kb.search_knowledge_base(
        query="what do you have",
        channel="text",
        customer_text="what insurance plans do you offer?",
        intent="product_faq",
    ).data
    assert data["confident"] is False
    assert data["topScore"] == 0.0


def test_answerable_rejects_a_snippet_that_is_just_the_title() -> None:
    assert kb.answerable([{"docTitle": "Travel Protect360", "snippet": "Travel Protect360"}]) is False
    assert kb.answerable([{"docTitle": "Travel Protect360", "snippet": ""}]) is False
    assert kb.answerable([]) is False
    assert kb.answerable([{"docTitle": "Travel Protect360", "snippet": "Covers $150,000."}]) is True


def test_an_empty_retrieval_is_not_confident(monkeypatch, travel_catalog, plan):
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve([]))
    plan("passage", product_keys=["travel"])

    data = kb.search_knowledge_base(
        query="benefits", channel="text", customer_text="tell me the benefits",
        intent="product_faq",
    ).data
    assert data["confident"] is False


# ---------------------------------------------------------------------------
# The envelope tells the model which kind of answer it is holding
# ---------------------------------------------------------------------------


def test_a_names_only_answer_forbids_describing_cover() -> None:
    """The honest replacement for "Answer ONLY from these snippets"."""
    payload = kb.llm_payload(
        {
            "mode": "catalog",
            "confident": False,
            "intent": "product_faq",
            "results": [{"docTitle": "Travel Protect360", "snippet": "Travel Protect360"}],
            "products": _TRAVEL,
        },
        channel="text",
    )
    assert payload["mode"] == "catalog"
    assert payload["products"] == _TRAVEL
    policy = payload["answer_policy"]
    assert "product NAMES only" in policy
    assert "do NOT describe what any of them covers" in policy


def test_a_names_only_answer_on_voice_is_never_read_out_in_full() -> None:
    """VS-8C1B760F1B: nine "...Protect360" names in one 17-second breath."""
    payload = kb.llm_payload(
        {
            "mode": "catalog",
            "confident": False,
            "intent": "product_faq",
            "results": [{"docTitle": "Travel Protect360", "snippet": "Travel Protect360"}],
            "products": _TRAVEL,
        },
        channel="voice",
    )
    policy = payload["answer_policy"]
    assert "product NAMES only" in policy
    assert "never read the list out" in policy
    assert "at most three" in policy
    assert "Never answer an unclear name with another list" in policy


def test_a_names_only_answer_on_text_may_still_list_them() -> None:
    """A chat window can hold a list; only the spoken channel gets the cap."""
    payload = kb.llm_payload(
        {"mode": "catalog", "confident": False, "intent": "product_faq",
         "results": [{"docTitle": "Travel Protect360", "snippet": "Travel Protect360"}]},
        channel="text",
    )
    assert "never read the list out" not in payload["answer_policy"]


def test_a_scoped_catalog_answer_tells_the_model_which_rows_are_evidence() -> None:
    payload = kb.llm_payload(
        {
            "mode": "catalog",
            "confident": True,
            "intent": "product_faq",
            "results": [
                {"docTitle": "Travel Protect360", "snippet": "Travel Protect360", "docType": "catalog"},
                {"docTitle": "Travel Protect360 — Benefits", "snippet": "Covers $150,000.",
                 "docType": "benefits"},
            ],
        },
        channel="text",
    )
    assert "names only, not evidence" in payload["answer_policy"]


@pytest.mark.parametrize("channel", ["text", "voice"])
def test_mode_reaches_every_channel(channel: str) -> None:
    """Dropped by both adapters, and it is the key that says a search ran."""
    payload = kb.llm_payload(
        {"mode": "passage", "confident": True, "intent": "product_faq",
         "results": [{"docTitle": "D", "snippet": "real text"}]},
        channel=channel,
    )
    assert payload["mode"] == "passage"
    assert payload["confident"] is True


def test_voice_keeps_its_spoken_length_rule() -> None:
    """Evidence-backed (VS-92CDE3F088: 353 characters, 30 seconds unbroken)."""
    payload = kb.llm_payload(
        {"mode": "passage", "confident": True, "intent": "product_faq",
         "results": [{"docTitle": "D", "snippet": "real text"}]},
        channel="voice",
    )
    assert "at most two short spoken sentences" in payload["answer_policy"]
    assert "never invent balances" in payload["note"]
    # Voice renames this field; its card's prompt refers to `title`.
    assert "title" in payload["results"][0]


# ---------------------------------------------------------------------------
# prefer_policy no longer decides the topic
# ---------------------------------------------------------------------------


def test_wanting_the_policy_corpus_is_not_the_same_as_asking_what_is_excluded(
    monkeypatch, travel_catalog, plan
):
    """Measured: prefer_policy=True on a benefits query returned 0/5 benefits.

    It set `wants_exclusions`, which suppressed `wants_coverage` and then
    reserved top_k-1 slots for policy documents. The caller asked what a product
    covers and got boilerplate about what voids it.
    """
    import kb_retrieve

    fake = _FakeRetrieve(_passages())
    monkeypatch.setattr(kb_retrieve, "retrieve", fake)

    plan("passage", product_keys=["travel"], prefer_policy=False)
    kb.search_knowledge_base(
        query="benefits", channel="text", customer_text="tell me the benefits",
        intent="product_faq",
    )
    assert fake.last["topic"] is None

    plan("passage", product_keys=["travel"], prefer_policy=True)
    kb.search_knowledge_base(
        query="exclusions", channel="text", customer_text="what is not covered?",
        intent="product_faq",
    )
    assert fake.last["topic"] == "exclusions"
