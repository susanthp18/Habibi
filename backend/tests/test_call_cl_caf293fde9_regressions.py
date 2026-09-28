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


def test_rollup_does_not_infer_upsell_from_a_product_faq() -> None:
    import capture

    src = inspect.getsource(capture.rollup_interaction)
    assert "_has_product_interest" not in src
