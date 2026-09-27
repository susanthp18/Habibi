"""An exit that stands for one outcome records it when the call ends there."""

import pytest
from pydantic import ValidationError

from api.services.workflow.dto import EndCallNodeData
from api.services.workflow.pipecat_engine import PipecatEngine
from api.services.workflow.workflow_graph import Node


def _engine(recorded=None):
    engine = PipecatEngine.__new__(PipecatEngine)
    engine._gathered_context = dict(recorded or {})
    engine._disposition_mapping = {}

    async def no_llm(node):
        return None

    engine._setup_llm_context = no_llm
    return engine


def _end(outcome):
    return Node("close", "endCall", EndCallNodeData(name="Close", prompt="Bye.", call_disposition=outcome))


@pytest.mark.asyncio
async def test_the_exit_records_its_outcome():
    engine = _engine()
    await engine._handle_end_node(_end("wrong_number"))
    assert engine._gathered_context["call_disposition"] == "wrong_number"
    assert engine._gathered_context["mapped_call_disposition"] == "wrong_number"


@pytest.mark.asyncio
async def test_an_outcome_already_recorded_wins_and_empty_leaves_it_to_the_classifier():
    engine = _engine({"call_disposition": "transferred"})
    await engine._handle_end_node(_end("opted_out"))
    assert engine._gathered_context["call_disposition"] == "transferred"
    engine = _engine()
    await engine._handle_end_node(_end(""))
    assert "call_disposition" not in engine._gathered_context


def test_outcome_codes_are_validated():
    assert EndCallNodeData(name="c", prompt="p", call_disposition="  ").call_disposition is None
    with pytest.raises(ValidationError):
        EndCallNodeData(name="c", prompt="p", call_disposition="wrong number!")
