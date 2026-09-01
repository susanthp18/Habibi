"""``search_knowledge_base`` is one handler, not two look-alikes.

Unification acceptance criterion §8.1 names this tool alongside the CRM writes,
but retrieval kept a private copy of the policy per channel: the text path owned
the intent gate, query expansion and exclusion steering; the voice path owned
node-scoped product keys, snapshot pinning and the confidence threshold.

These tests pin the shared behaviour and the two channel-shaped differences that
are still legitimately parameters (``apply_intent_gate``, ``prefer_policy``).
"""

from __future__ import annotations

import pytest

from agent_core.tools import kb


class _FakeRetrieve:
    """Stand-in for kb_retrieve.retrieve — records kwargs, returns fixed rows."""

    def __init__(self, rows=None, raises=None):
        self.calls: list[dict] = []
        self._rows = rows if rows is not None else _rows(3)
        self._raises = raises

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return {"results": self._rows, "latencyMs": 12, "logId": "LOG-1"}

    @property
    def last(self) -> dict:
        return self.calls[-1]


def _rows(n: int, top: float = 0.91):
    return [
        {
            "chunkId": f"CH-{i}",
            "docTitle": f"Doc {i}",
            "docType": "policy",
            "heading": f"H{i}",
            "snippet": "x" * 4000,
            "score": top - (i * 0.1),
        }
        for i in range(n)
    ]


@pytest.fixture
def fake_retrieve(monkeypatch):
    import kb_retrieve

    fake = _FakeRetrieve()
    monkeypatch.setattr(kb_retrieve, "retrieve", fake)
    return fake


# --------------------------------------------------------------------------
# Both adapters reach the same handler
# --------------------------------------------------------------------------


def test_both_channels_call_the_shared_handler(monkeypatch):
    """No second implementation survives in either channel module."""
    import bot_tools
    import voice.tools  # noqa: F401 - import proves the adapter wires up

    seen: list[str] = []

    def _spy(**kwargs):
        seen.append(kwargs["channel"])
        return kb.ToolResult(ok=True, data={"available": False, "results": []})

    monkeypatch.setattr(bot_tools.kb_tool, "search_knowledge_base", _spy)

    ctx = bot_tools.ToolContext(
        conversation_id="C1",
        customer_id="CUST-1",
        job_id="J1",
        customer_text="is scuba diving covered by my travel policy",
        interaction_id=None,
        bot_id=None,
        intent="product_faq",
    )
    bot_tools._tool_search_knowledge_base(ctx, {"query": "scuba exclusions"})
    assert seen == ["text"]


def test_text_channel_shapes_the_historical_payload(fake_retrieve):
    import bot_tools

    ctx = bot_tools.ToolContext(
        conversation_id="C1",
        customer_id="CUST-1",
        job_id="J1",
        customer_text="what does my travel insurance cover",
        interaction_id=None,
        bot_id=None,
        intent="product_faq",
    )
    out = bot_tools._tool_search_knowledge_base(ctx, {"query": "coverage"})
    assert out["available"] is True
    # Chunk plumbing stays Inspector-only, but the confidence verdict must
    # reach text too: without it a sub-threshold passage was handed to the
    # model as ground truth with no directive at all.
    assert set(out) == {
        "available",
        "intent",
        "queryUsed",
        "results",
        "confident",
        "answer_policy",
        "logId",
    }
    assert fake_retrieve.last["source"] == "bot"


# --------------------------------------------------------------------------
# Gate — text only
# --------------------------------------------------------------------------


def test_gate_blocks_collections_money_question(fake_retrieve):
    result = kb.search_knowledge_base(
        query="how much do I owe",
        channel="text",
        customer_text="how much do I owe this month",
        intent="payment_promise",
    )
    assert result.ok
    assert result.data["available"] is False
    assert result.data["reason"] == "kb_gated_for_intent"
    assert not fake_retrieve.calls, "gated query must not spend an embed + ANN"


def test_gate_opens_on_product_vocabulary(fake_retrieve):
    result = kb.search_knowledge_base(
        query="what does my travel insurance policy exclude",
        channel="text",
        intent="payment_promise",
    )
    assert result.data["available"] is True
    assert fake_retrieve.calls


def test_voice_skips_the_gate(fake_retrieve):
    """The Flows node already scopes the corpus; the gate would double-block."""
    result = kb.search_knowledge_base(
        query="how do I dispute a charge",
        channel="voice",
        intent="payment_promise",
        apply_intent_gate=False,
    )
    assert result.data["available"] is True


# --------------------------------------------------------------------------
# Retrieval shape per channel
# --------------------------------------------------------------------------


def test_voice_takes_few_short_snippets(fake_retrieve):
    kb.search_knowledge_base(
        query="policy exclusions",
        channel="voice",
        apply_intent_gate=False,
        prefer_policy=True,
    )
    assert fake_retrieve.last["top_k"] == 3


def test_text_widens_for_policy_questions(fake_retrieve):
    kb.search_knowledge_base(
        query="list all exclusions in the policy wording",
        channel="text",
        customer_text="list all exclusions in the policy wording",
    )
    # prefer_policy derived from the customer's words → the wider pool.
    assert fake_retrieve.last["prefer_policy"] is True
    assert fake_retrieve.last["top_k"] == 8


def test_snippet_cap_differs_by_channel(fake_retrieve):
    voice = kb.search_knowledge_base(
        query="q", channel="voice", apply_intent_gate=False, prefer_policy=False
    )
    text = kb.search_knowledge_base(
        query="what does the policy cover", channel="text", intent="product_faq"
    )
    assert len(voice.data["results"][0]["snippet"]) == 600
    assert len(text.data["results"][0]["snippet"]) == 1400


def test_explicit_prefer_policy_wins_over_derivation(fake_retrieve):
    """Voice decides scope by node, so its explicit False must not be re-derived."""
    kb.search_knowledge_base(
        query="list all exclusions",
        channel="voice",
        customer_text="list all exclusions",
        apply_intent_gate=False,
        prefer_policy=False,
    )
    assert fake_retrieve.last["prefer_policy"] is False


# --------------------------------------------------------------------------
# Snapshot pinning + confidence
# --------------------------------------------------------------------------


def test_snapshot_and_product_keys_reach_retrieve(fake_retrieve):
    kb.search_knowledge_base(
        query="premium",
        channel="voice",
        apply_intent_gate=False,
        kb_snapshot_id="KBS-9",
        product_keys=["collections"],
    )
    assert fake_retrieve.last["kb_snapshot_id"] == "KBS-9"
    assert fake_retrieve.last["product_keys"] == ["collections"]


def test_bad_snapshot_never_widens_to_whole_corpus(monkeypatch):
    import kb_retrieve

    monkeypatch.setattr(
        kb_retrieve, "retrieve", _FakeRetrieve(raises=ValueError("unknown snapshot"))
    )
    result = kb.search_knowledge_base(
        query="premium", channel="voice", apply_intent_gate=False, kb_snapshot_id="KBS-gone"
    )
    assert result.ok is False
    assert result.error == "retrieval_unavailable"
    assert result.spoken_summary


def test_a_weak_score_no_longer_gates_answering(monkeypatch):
    """The 0.70 gate is gone; only "did anything come back" still gates.

    The old rule refused 5 of 46 correct answers over the golden set while
    admitting 12 of 14 wrong ones, because the absolute top score does not
    predict retrieval success (AUC 0.548). Whether these passages answer this
    question is now asked of the model that reads them.
    """
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=_rows(2, top=0.42)))
    result = kb.search_knowledge_base(
        query="premium", channel="voice", apply_intent_gate=False
    )
    assert result.data["confident"] is True

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=[]))
    result = kb.search_knowledge_base(
        query="premium", channel="voice", apply_intent_gate=False
    )
    assert result.data["confident"] is False


def test_chunk_ids_line_up_with_returned_results(fake_retrieve):
    """rag.hits must never report passages the model was not shown."""
    result = kb.search_knowledge_base(
        query="premium", channel="voice", apply_intent_gate=False
    )
    assert len(result.data["chunkIds"]) == len(result.data["results"])


def test_empty_query_is_a_soft_failure(fake_retrieve):
    result = kb.search_knowledge_base(query="   ", channel="voice")
    assert result.ok is False
    assert result.error == "empty_query"
    assert not fake_retrieve.calls


# --------------------------------------------------------------------------
# Steering heuristics (moved out of bot_tools, behaviour must be identical)
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("is scuba diving covered", True),
        ("what does my travel insurance cover", True),
        ("what are the travel insurance exclusions", True),
        ("i want a payment plan", False),
        ("i claim i already paid the terms", False),
        ("the terms of my insurance policy", True),
    ],
)
def test_product_vocabulary_detection(text, expected):
    assert kb.query_looks_product(text) is expected


@pytest.mark.parametrize(
    "customer,query,expected",
    [
        ("list all exclusions", "exclusions", "exclusions"),
        ("is scuba diving covered", "scuba", "exclusions"),
        ("what does it include", "benefits", "coverage"),
        ("i want to pay next friday", "payment", "none"),
    ],
)
def test_kb_intent_classification(customer, query, expected):
    assert kb.classify_kb_intent(customer, query) == expected


def test_expansion_adds_exclusion_terms_once():
    out = kb.expand_query(
        "exclusions", customer_text="list all exclusions", product_hint="Protect360"
    )
    assert "Protect360" in out
    assert out.count("policy exclusions invalidation") == 1
