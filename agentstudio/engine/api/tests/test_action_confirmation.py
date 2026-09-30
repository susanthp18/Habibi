"""The write guard's confirmation check: one model call, any language, fails closed."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.workflow.action_confirmation import (
    UNAVAILABLE,
    ActionConfirmationService,
    Confirmation,
    Verdict,
)
from api.services.workflow.pipecat_engine import PipecatEngine


class _Llm:
    """Answers with the next scripted reply and keeps what it was asked."""

    def __init__(self, *replies):
        self._replies = list(replies)
        self._settings = SimpleNamespace(model="judge", temperature=0.7)
        self.asked = []

    async def run_inference(self, context, *, system_instruction, max_tokens):
        self.asked.append((system_instruction, context.messages[0]["content"]))
        return self._replies.pop(0)


TERMS = {"amount": 5000, "date": "2026-10-07",
         "parts": [{"amount": 3000, "date": "2026-10-02"}, {"amount": 2000, "date": "2026-10-07"}]}
TURNS = [("assistant", "So that's 3,000 rupees on Friday the 2nd and 2,000 on Wednesday the 7th. Shall I record it?"),
         ("user", "نعم، سجّلها")]  # Arabic: "Yes, record it"


@pytest.mark.asyncio
async def test_the_verdict_is_read_from_the_models_json():
    llm = _Llm('```json\n{"status": "confirmed", "reason": "agreed"}\n```')
    verdict = await ActionConfirmationService(llm).confirm("promise_to_pay", TERMS, TURNS)
    assert verdict == Verdict(Confirmation.CONFIRMED, "agreed") and verdict.confirmed
    system, user = llm.asked[0]
    # The rule for a commitment, the terms with their weekdays, and the words as spoken.
    assert "which amount goes with which date" in system
    assert "2026-10-02 is a Friday" in user and "2026-10-07 is a Wednesday" in user
    assert "Customer: نعم، سجّلها" in user and user.rstrip().endswith("</conversation>")
    assert llm._settings.temperature == 0.0  # its own instance: sampling pinned


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, expected", [
    ('{"status": "none", "reason": "conditional"}', Verdict(Confirmation.NONE, "conditional")),
    ('{"status": "denied", "reason": "declined"}', Verdict(Confirmation.DENIED, "declined")),
    ('{"status": "none", "reason": "made up"}', Verdict(Confirmation.NONE, "unsure")),
    ('{"status": "maybe"}', UNAVAILABLE),
    ("I think they agreed.", UNAVAILABLE),
    ("", UNAVAILABLE),
])
async def test_anything_but_a_clear_confirmation_is_not_one(reply, expected):
    assert await ActionConfirmationService(_Llm(reply)).confirm("request_callback", {}, TURNS) == expected


@pytest.mark.asyncio
async def test_a_dispute_is_judged_on_the_customers_account_not_a_yes():
    llm = _Llm('{"status": "confirmed", "reason": "agreed"}')
    await ActionConfirmationService(llm).confirm("flag_dispute", {"type": "not_my_transaction"},
                                                 [("user", "No, I never took this loan.")])
    assert "is the dispute, not a refusal" in llm.asked[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, digits", [
    ('{"digits": "2324"}', "2324"), ('{"digits": "٢٣٢٤"}', ""), ('{"digits": "23 24"}', ""), ("none", ""),
])
async def test_spoken_digits_come_back_as_ascii_or_not_at_all(reply, digits):
    assert await ActionConfirmationService(_Llm(reply)).digits("اثنان ثلاثة اثنان أربعة") == digits


def _engine(llm=None):
    engine = object.__new__(PipecatEngine)
    note = {"role": "user", "content": "[engine note]"}
    summary = {"role": "user", "content": "[summary]"}
    engine._engine_notes = [note]
    engine._context_summary_message = summary
    engine.context = SimpleNamespace(messages=[
        summary,
        {"role": "assistant", "content": "Shall I record 4,000 for Friday?"},
        {"role": "assistant", "tool_calls": [{"id": "1"}]},
        {"role": "tool", "content": "{}"},
        note,
        {"role": "user", "content": [{"type": "text", "text": "हाँ जी"}]},
    ])
    engine._active_agent = SimpleNamespace(confirmation_llm=llm)
    engine._get_otel_context = lambda: None
    return engine


def test_the_check_sees_the_conversation_not_the_engines_own_messages():
    assert _engine().recent_turns() == [("assistant", "Shall I record 4,000 for Friday?"), ("user", "हाँ जी")]


@pytest.mark.asyncio
async def test_the_engine_fails_closed(monkeypatch):
    assert await _engine(llm=None).confirm_action("promise_to_pay", {}) == UNAVAILABLE

    broken = SimpleNamespace(_settings=None, run_inference=AsyncMock(side_effect=RuntimeError("down")))
    assert await _engine(broken).confirm_action("promise_to_pay", {}) == UNAVAILABLE
    assert await _engine(broken).spoken_digits("two three") == ""

    from api.services.workflow import pipecat_engine

    async def slow(*_a, **_k):
        await asyncio.sleep(1)

    monkeypatch.setattr(pipecat_engine, "CHECK_TIMEOUT_SECS", 0.01)
    hung = SimpleNamespace(_settings=None, run_inference=slow)
    assert await _engine(hung).confirm_action("promise_to_pay", {}) == UNAVAILABLE
