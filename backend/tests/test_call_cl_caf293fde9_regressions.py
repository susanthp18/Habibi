"""Regressions from live demo call CL-CAF293FDE9.

That call opened with the account before the recording disclosure, answered a
travel-exclusions follow-up with a names-only catalog, booked a callback the
caller had refused, sat silent for ~20s after answer, nudged after a payment
question, and closed a new PTP as ptp_recommitted / met=False.
"""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
from types import SimpleNamespace

import pytest

from agent_core.tools import ToolResult, domain
from voice.bot_handlers_idle import should_defer_question_idle
from voice.bot_handlers_scope import _QUESTION_IDLE_FLOOR_SECS
from voice.node_contracts import NODE_DIRECTIVES
from voice.tool_state import ToolBuildContext
from voice.tools_knowledge import count_scored_rag_hits
from voice.tools_preferences import (
    callback_reason_for_turn,
    declined_callback_offer,
)


def test_catalog_title_rows_do_not_count_as_rag_hits() -> None:
    rows = [
        {"score": 0, "docType": "catalog", "snippet": f"Product {i}"} for i in range(10)
    ]
    assert count_scored_rag_hits(rows) == 0
    assert count_scored_rag_hits(
        [{"score": 0.72, "docType": "policy", "snippet": "Scuba is excluded."}]
    ) == 1


def test_a_callback_decline_is_recognised() -> None:
    assert declined_callback_offer(
        bot_text="Shall I arrange a callback with a specialist?",
        customer_text="No",
    )
    assert not declined_callback_offer(
        bot_text="Shall I arrange a callback with a specialist?",
        customer_text="Yes please",
    )


def test_travel_exclusions_are_a_product_query_not_a_document_query() -> None:
    assert (
        callback_reason_for_turn("document_query", "what about travel exclusions")
        == "product_query"
    )
    assert callback_reason_for_turn("hardship_review", "salary delay") == "hardship_review"


def _callback_tools(*, customer_text: str, bot_text: str, monkeypatch: pytest.MonkeyPatch):
    booked: list[dict] = []

    def _fake_request_callback(**kwargs):
        booked.append(kwargs)
        return ToolResult(ok=True, data={"id": "CB-UT"}, spoken_summary="booked")

    async def _announce(*_a, **_k):
        return None

    monkeypatch.setattr(domain, "request_callback", _fake_request_callback)
    sink = SimpleNamespace(_recent_bot_texts=[bot_text])
    ctx = ToolBuildContext(
        _announce=_announce,
        _node=lambda *a, **k: None,
        _require_customer=lambda: ("CUST-1", None),
        _spec=lambda _name, handler: handler,
        session=SimpleNamespace(
            interaction_id="IX-1",
            account_id="AC-1",
            provider_call_id="CA-1",
        ),
        spoke_this_response=SimpleNamespace(add=lambda *_a, **_k: None),
        state=SimpleNamespace(current_node="escalate_close"),
        upsell_node="gated_upsell",
        sink=sink,
        _sink_call=lambda name, default=None: customer_text
        if name == "last_customer_text"
        else default,
    )
    from voice.tools_preferences import build

    return build(ctx), booked


def test_declining_a_callback_does_not_write_a_row(monkeypatch: pytest.MonkeyPatch) -> None:
    tools, booked = _callback_tools(
        customer_text="No",
        bot_text="Shall I arrange a callback with a specialist?",
        monkeypatch=monkeypatch,
    )
    result, nxt = asyncio.run(
        tools["request_callback"]({"scheduled_at": "2026-09-15T11:00:00+05:30"}, None)
    )
    assert nxt is None
    assert result.get("error") == "declined"
    assert booked == []


def test_accepting_a_callback_stores_the_caller_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tools, booked = _callback_tools(
        customer_text="yes, call me about travel exclusions",
        bot_text="Shall I arrange a callback with a specialist?",
        monkeypatch=monkeypatch,
    )
    result, nxt = asyncio.run(
        tools["request_callback"](
            {
                "scheduled_at": "2026-09-15T11:00:00+05:30",
                "reason": "document_query",
            },
            None,
        )
    )
    assert nxt is None
    assert result.get("ok") is not False
    assert booked
    assert booked[0]["transcript_snippet"] == "yes, call me about travel exclusions"
    assert booked[0]["reason"] == "product_query"


def test_capture_lead_rejects_a_promise_id() -> None:
    ctx = ToolBuildContext(
        _announce=lambda *a, **k: None,
        _node=lambda *a, **k: None,
        _require_customer=lambda: ("CUST-1", None),
        _schedule_context_refresh=lambda: None,
        _spec=lambda _name, handler: handler,
        bot_id="kaia-v2-4",
        session=SimpleNamespace(interaction_id="IX-1", account_id="AC-1"),
        state=SimpleNamespace(
            last_product_id="",
            offered_product_ids=set(),
            offer_decision_id=None,
            current_node="gated_upsell",
        ),
        upsell_node="gated_upsell",
        _sink_call=lambda n, default=None: default,
    )
    from voice.tools_leads import build

    tools = build(ctx)
    result, nxt = asyncio.run(
        tools["capture_lead"]({"product_id": "PTP-ABC123"}, None)
    )
    assert nxt is None
    assert result["error"] == "not_a_product"


def test_live_signals_only_use_callsignals_fields() -> None:
    from agent_core.live_qa.engine import evaluate_live_qa
    from agent_core.reco.features import CallSignals
    from voice import tools_offers

    assert callable(evaluate_live_qa)
    fields = {f.name for f in dataclasses.fields(CallSignals)}
    assert "offers_presented_this_call" not in fields
    src = inspect.getsource(tools_offers.build)
    start = src.index("return CallSignals(")
    end = src.index("async def _recommend_next_offer_handler")
    block = src[start:end]
    assert "offers_presented_this_call" not in block
    for name in (
        "interaction_id",
        "channel",
        "sentiment_current",
        "sentiment_trend",
        "customer_turns",
        "commitment_secured",
        "escalation_flagged",
        "dispute_opened",
        "offer_declined_this_call",
    ):
        assert f"{name}=" in block
        assert name in fields


def test_idle_ladder_waits_after_a_question() -> None:
    assert should_defer_question_idle(
        "What happened with the payment?", 14.8, _QUESTION_IDLE_FLOOR_SECS
    )
    assert not should_defer_question_idle(
        "What happened with the payment?", 28.0, _QUESTION_IDLE_FLOOR_SECS
    )
    assert not should_defer_question_idle("I'll wait.", 14.8, _QUESTION_IDLE_FLOOR_SECS)


def test_escalate_close_ends_the_conversation() -> None:
    from voice.flow_export import built_in_collections_graph

    node = next(
        n for n in built_in_collections_graph()["nodes"] if n["key"] == "escalate_close"
    )
    assert node["data"]["endConversation"] is True
    assert "search_knowledge_base again" in node["data"]["instructions"]
    assert "refused" in NODE_DIRECTIVES["escalate_close"]


def test_demo_reserve_passes_the_live_deployment_id() -> None:
    import db_outbound

    src = inspect.getsource(db_outbound.reserve_demo_attempt)
    assert "pick_deployment_id" in src
    assert "deployment_id=deployment_id" in src


def test_rollup_does_not_infer_upsell_from_a_product_faq() -> None:
    import capture

    src = inspect.getsource(capture.rollup_interaction)
    assert "_has_product_interest" not in src
