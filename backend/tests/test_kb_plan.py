"""Retrieval planning, catalog answers and model-judged answerability.

These pin the three ways the old design failed one real call at once: steering
followed the agent's tool-arg padding instead of the caller, a fixed 0.70 gate
on a heuristically-adjusted cosine score refused a corpus that had the answer at
0.667, and a "what do you have?" question had no passage to find.
"""

from __future__ import annotations

import json

import pytest

from agent_core.tools import kb, kb_plan


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _tool_response(name, **payload):
    return {
        "content": "",
        "toolCalls": [{"id": "1", "name": name, "arguments": json.dumps(payload)}],
        "finishReason": "tool_calls",
        "completionTokens": 40,
        "latencyMs": 30,
    }


@pytest.fixture
def model_on(monkeypatch):
    monkeypatch.setenv("KB_PLANNER_ENABLED", "true")
    monkeypatch.setenv("KB_JUDGE_ENABLED", "true")


@pytest.fixture
def fake_azure(monkeypatch):
    """Route each pinned tool call to a queued response, and record the calls."""
    import azure_openai

    state = {"plan": None, "judge": None, "raises": None}
    calls: list[dict] = []

    def _fake(messages, **kwargs):
        calls.append({"messages": messages, **kwargs})
        if state["raises"] is not None:
            raise state["raises"]
        name = (kwargs.get("tool_choice") or {}).get("function", {}).get("name")
        return state.get("plan" if name == kb_plan._PLAN_TOOL_NAME else "judge") or {
            "content": "",
            "toolCalls": [],
        }

    monkeypatch.setattr(azure_openai, "chat_with_tools", _fake)
    _fake.state = state  # type: ignore[attr-defined]
    _fake.calls = calls  # type: ignore[attr-defined]
    return _fake


def _rows(n, top=0.667):
    return [
        {
            "chunkId": f"c{i}",
            "docId": f"d{i}",
            "docTitle": f"Doc {i}",
            "docType": "policy",
            "heading": f"H{i}",
            "snippet": f"snippet {i}",
            "score": top - i * 0.02,
        }
        for i in range(n)
    ]


class _FakeRetrieve:
    def __init__(self, rows):
        self._rows = rows
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {"results": self._rows, "latencyMs": 5, "logId": "L1"}


# ---------------------------------------------------------------------------
# The refusal that started this
# ---------------------------------------------------------------------------


def test_a_corpus_that_has_the_answer_is_not_refused_at_0_667(
    model_on, fake_azure, monkeypatch
):
    """0.667 against a 0.70 gate refused a caller four times over ten products.

    Whether passages answer a question is a judgment about their content. The
    number the gate compared had already been through a stack of BOOST_*/
    PENALTY_* deltas, so the threshold was applied to a quantity with no stable
    meaning.
    """
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=_rows(3, top=0.667)))
    monkeypatch.setattr(kb_retrieve, "catalog", lambda **kw: [])
    fake_azure.state["plan"] = _tool_response(
        kb_plan._PLAN_TOOL_NAME, mode="passage", query="travel cover", prefer_policy=False
    )
    fake_azure.state["judge"] = _tool_response(
        kb_plan._JUDGE_TOOL_NAME, keep=[1, 0], answerable=True, reason="states the benefit"
    )

    result = kb.search_knowledge_base(
        query="what does travel cover",
        channel="voice",
        customer_text="what does travel cover",
        apply_intent_gate=False,
    )

    assert result.data["confident"] is True
    assert result.data["judgeSource"] == "llm"
    assert result.data["unvetted"] is False
    # Reranked into the judge's order, with chunkIds kept index-aligned.
    assert result.data["chunkIds"] == ["c1", "c0", "c2"]


def test_the_judge_can_still_refuse(model_on, fake_azure, monkeypatch):
    """Removing the threshold must not remove the check."""
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=_rows(3, top=0.95)))
    monkeypatch.setattr(kb_retrieve, "catalog", lambda **kw: [])
    fake_azure.state["plan"] = _tool_response(
        kb_plan._PLAN_TOOL_NAME, mode="passage", query="scuba", prefer_policy=True
    )
    fake_azure.state["judge"] = _tool_response(
        kb_plan._JUDGE_TOOL_NAME,
        keep=[0],
        answerable=False,
        reason="exclusions listed but scuba diving is not among them",
    )

    result = kb.search_knowledge_base(
        query="scuba", channel="voice", customer_text="is scuba covered",
        apply_intent_gate=False,
    )

    # A high vector score does not make it answerable.
    assert result.data["topScore"] >= 0.9
    assert result.data["confident"] is False
    assert "scuba diving is not among them" in result.data["judgeReason"]


# ---------------------------------------------------------------------------
# Catalog questions
# ---------------------------------------------------------------------------


def test_what_products_do_you_have_is_answered_from_the_corpus(
    model_on, fake_azure, monkeypatch
):
    """No passage answers this. The caller's own words scored 0.389."""
    import kb_retrieve

    retrieve = _FakeRetrieve(rows=_rows(3))
    monkeypatch.setattr(kb_retrieve, "retrieve", retrieve)
    monkeypatch.setattr(
        kb_retrieve,
        "catalog",
        lambda **kw: [
            {"productKey": "travel", "title": "Travel Protect360", "docTypes": ["policy"], "docCount": 2},
            {"productKey": "home", "title": "Home Protect360", "docTypes": ["policy"], "docCount": 2},
        ],
    )
    fake_azure.state["plan"] = _tool_response(
        kb_plan._PLAN_TOOL_NAME,
        mode="catalog",
        query="list all insurance products",
        prefer_policy=False,
    )

    result = kb.search_knowledge_base(
        query="insurance plans; exclusions and process",
        channel="voice",
        customer_text="just let me know all of the products available",
        apply_intent_gate=False,
    )

    assert result.data["mode"] == "catalog"
    assert result.data["confident"] is True
    assert [p["title"] for p in result.data["products"]] == [
        "Travel Protect360",
        "Home Protect360",
    ]
    # Similarity search is not attempted — there is nothing for it to find.
    assert retrieve.calls == []


def test_catalog_scope_narrows_to_named_products(model_on, fake_azure, monkeypatch):
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=[]))
    monkeypatch.setattr(
        kb_retrieve,
        "catalog",
        lambda **kw: [
            {"productKey": "travel", "title": "Travel Protect360", "docTypes": [], "docCount": 1},
            {"productKey": "home", "title": "Home Protect360", "docTypes": [], "docCount": 1},
        ],
    )
    fake_azure.state["plan"] = _tool_response(
        kb_plan._PLAN_TOOL_NAME,
        mode="catalog",
        query="travel products",
        product_keys=["travel"],
        prefer_policy=False,
    )

    result = kb.search_knowledge_base(
        query="travel", channel="voice", customer_text="what travel cover do you sell",
        apply_intent_gate=False,
    )

    assert [p["productKey"] for p in result.data["products"]] == ["travel"]


# ---------------------------------------------------------------------------
# Steering
# ---------------------------------------------------------------------------


def test_the_plan_follows_the_caller_not_the_agents_padding(model_on, fake_azure):
    """The regression that sent "what plans are available" to the exclusions corpus.

    The word "exclusions" appeared only in the agent's own tool-arg phrasing.
    """
    fake_azure.state["plan"] = _tool_response(
        kb_plan._PLAN_TOOL_NAME,
        mode="catalog",
        query="list available insurance plans",
        prefer_policy=False,
    )

    plan = kb_plan.plan_retrieval(
        customer_text="what insurance plans are available",
        tool_query="insurance plans; how to check availability; exclusions and process",
        available_products=[{"productKey": "travel", "title": "Travel Protect360"}],
        budget=5.0,
    )

    assert plan.prefer_policy is False
    assert plan.mode == "catalog"
    user_msg = fake_azure.calls[0]["messages"][-1]["content"]
    # Both are shown, but the caller's turn is the one labelled as the question.
    assert "Caller turn:\nwhat insurance plans are available" in user_msg
    assert "The agent's own phrasing" in user_msg


def test_invented_product_keys_are_dropped(model_on, fake_azure):
    """A key the corpus does not have would filter every row out."""
    fake_azure.state["plan"] = _tool_response(
        kb_plan._PLAN_TOOL_NAME,
        mode="passage",
        query="q",
        product_keys=["travel", "spaceflight"],
        prefer_policy=False,
    )

    plan = kb_plan.plan_retrieval(
        customer_text="what about travel",
        available_products=[{"productKey": "travel", "title": "Travel Protect360"}],
        budget=5.0,
    )

    assert plan.product_keys == ["travel"]


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


def test_planner_failure_falls_back_to_the_keyword_plan(model_on, fake_azure):
    fake_azure.state["raises"] = RuntimeError("circuit open")
    fallback = kb_plan.RetrievalPlan(query="keyword query", prefer_policy=True)

    plan = kb_plan.plan_retrieval(
        customer_text="anything", budget=5.0, fallback=fallback
    )

    assert plan is fallback
    assert plan.source == "fallback"


def test_no_budget_means_no_call(model_on, fake_azure):
    """A budget the caller cannot enforce is not a budget."""
    plan = kb_plan.plan_retrieval(customer_text="anything", budget=0.0)

    assert plan.source == "fallback"
    assert fake_azure.calls == []


def test_judge_unavailable_fails_open_and_says_so(model_on, fake_azure, monkeypatch):
    """A busy analysis lane must not become a refused caller.

    Deliberate product decision, so the compensating requirement is that it is
    never silent: `unvetted` rides along in the payload.
    """
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=_rows(2, top=0.30)))
    monkeypatch.setattr(kb_retrieve, "catalog", lambda **kw: [])
    fake_azure.state["plan"] = _tool_response(
        kb_plan._PLAN_TOOL_NAME, mode="passage", query="q", prefer_policy=False
    )
    fake_azure.state["judge"] = {"content": "", "toolCalls": []}  # no verdict

    result = kb.search_knowledge_base(
        query="q", channel="voice", customer_text="q", apply_intent_gate=False
    )

    assert result.data["confident"] is True
    assert result.data["unvetted"] is True
    assert result.data["judgeSource"] == "fallback"


def test_judge_disabled_uses_the_legacy_threshold(fake_azure, monkeypatch):
    """Switched off on purpose is not the same as broken.

    Disabling the judge falls back to the documented numeric rule rather than
    to no check at all — otherwise turning the feature off would silently make
    every retrieval answerable.
    """
    import kb_retrieve

    monkeypatch.setenv("KB_PLANNER_ENABLED", "false")
    monkeypatch.setenv("KB_JUDGE_ENABLED", "false")
    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=_rows(2, top=0.42)))
    monkeypatch.setattr(kb_retrieve, "catalog", lambda **kw: [])

    result = kb.search_knowledge_base(
        query="premium", channel="voice", apply_intent_gate=False
    )

    assert result.data["confident"] is False
    assert result.data["unvetted"] is False


def test_an_empty_keep_list_cannot_be_answerable(model_on, fake_azure):
    """Otherwise the model is handed an empty context and told to answer from it."""
    verdict = kb_plan.judge_passages(
        question="q",
        passages=[{"docTitle": "D", "snippet": "s"}],
        budget=5.0,
    )
    fake_azure.state["judge"] = _tool_response(
        kb_plan._JUDGE_TOOL_NAME, keep=[], answerable=True
    )
    verdict = kb_plan.judge_passages(
        question="q", passages=[{"docTitle": "D", "snippet": "s"}], budget=5.0
    )

    assert verdict.keep == []
    assert verdict.answerable is False


def test_voice_budget_is_tighter_than_text(monkeypatch):
    monkeypatch.delenv("KB_VOICE_PLAN_BUDGET_S", raising=False)
    monkeypatch.delenv("KB_TEXT_PLAN_BUDGET_S", raising=False)

    assert kb_plan.budget_for("voice") < kb_plan.budget_for("text")


def test_the_deadline_is_shared_across_both_calls():
    """Planning and judging share one wall clock, not one budget each."""
    d = kb_plan.Deadline(0.0)

    assert d.expired() is True
    assert d.remaining() == 0.0
