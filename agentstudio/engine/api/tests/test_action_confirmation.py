"""The write guard's confirmation check: one model call, any language, fails closed,
started alongside the reply and bound to the write it authorises."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.services.workflow.action_confirmation import (
    UNAVAILABLE,
    ActionConfirmationService,
    Confirmation,
    Verdict,
    decide,
    terms_key,
)
from api.services.workflow.pipecat_engine import PipecatEngine


class _Llm:
    """Answers with the next scripted reply and keeps what it was asked."""

    def __init__(self, *replies, delay=0.0):
        self._replies = list(replies)
        self._delay = delay
        self._settings = SimpleNamespace(model="judge", temperature=0.7)
        self.asked = []

    async def run_inference(self, context, *, system_instruction, max_tokens):
        self.asked.append((system_instruction, context.messages[0]["content"]))
        await asyncio.sleep(self._delay)
        return self._replies.pop(0)


TERMS = {"amount": 5000, "date": "2026-10-07",
         "parts": [{"amount": 3000, "date": "2026-10-02"}, {"amount": 2000, "date": "2026-10-07"}]}
TURNS = [("assistant", "So that's 3,000 rupees on Friday the 2nd and 2,000 on Wednesday the 7th. Shall I record it?"),
         ("user", "نعم، سجّلها")]  # Arabic: "Yes, record it"


@pytest.mark.asyncio
async def test_the_verdict_is_read_from_the_models_json():
    llm = _Llm('```json\n{"read_back": "matches", "reply": "agrees"}\n```')
    verdict = await ActionConfirmationService(llm).confirm("promise_to_pay", TERMS, TURNS)
    assert verdict == Verdict(Confirmation.CONFIRMED, "agreed") and verdict.confirmed
    system, user = llm.asked[0]
    # The rule for a commitment, the terms with their weekdays, and the words as spoken.
    assert "the pairing of an amount with a date differs" in system
    assert "2026-10-02 is a Friday" in user and "2026-10-07 is a Wednesday" in user
    assert "Customer: نعم، سجّلها" in user and user.rstrip().endswith("</conversation>")
    assert llm._settings.temperature == 0.0  # its own instance: sampling pinned


@pytest.mark.parametrize("action, answers, expected", [
    ("promise_to_pay", {"read_back": "matches", "reply": "agrees"}, Verdict(Confirmation.CONFIRMED, "agreed")),
    ("promise_to_pay", {"read_back": "matches", "reply": "conditional"}, Verdict(Confirmation.NONE, "conditional")),
    ("promise_to_pay", {"read_back": "differs", "reply": "agrees"}, Verdict(Confirmation.NONE, "other_terms")),
    ("promise_to_pay", {"read_back": "absent", "reply": "agrees"}, Verdict(Confirmation.NONE, "not_read_back")),
    ("promise_to_pay", {"read_back": "matches", "reply": "declines"}, Verdict(Confirmation.DENIED, "declined")),
    ("request_callback", {"read_back": "matches", "reply": "question"}, Verdict(Confirmation.NONE, "question")),
    ("flag_dispute", {"account": "given", "reply": "proceeds"}, Verdict(Confirmation.CONFIRMED, "agreed")),
    ("flag_dispute", {"account": "absent", "reply": "proceeds"}, Verdict(Confirmation.NONE, "unsure")),
    ("flag_dispute", {"account": "given", "reply": "declines"}, Verdict(Confirmation.DENIED, "declined")),
    ("flag_dispute", {"account": "given", "reply": "unsure"}, Verdict(Confirmation.NONE, "paused")),
    # Third review: an incomplete or unknown answer never authorises a write.
    ("promise_to_pay", {"read_back": "matches"}, UNAVAILABLE),
    ("promise_to_pay", {"reply": "agrees"}, UNAVAILABLE),
    ("promise_to_pay", {"read_back": "matches", "reply": "garbage"}, UNAVAILABLE),
    ("promise_to_pay", {"read_back": "yes", "reply": "agrees"}, UNAVAILABLE),
    ("promise_to_pay", {"status": "confirmed", "reason": "agreed"}, UNAVAILABLE),
    ("flag_dispute", {"read_back": "matches", "reply": "agrees"}, UNAVAILABLE),
    ("promise_to_pay", {}, UNAVAILABLE),
])
def test_the_verdict_is_decided_in_code_from_a_complete_checklist(action, answers, expected):
    assert decide(action, answers) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["I think they agreed.", "", '{"read_back": "matches", "reply": 1}'])
async def test_a_malformed_reply_is_no_confirmation(reply):
    assert await ActionConfirmationService(_Llm(reply)).confirm("promise_to_pay", TERMS, TURNS) == UNAVAILABLE


@pytest.mark.asyncio
async def test_a_dispute_is_judged_on_the_customers_account_not_a_yes():
    llm = _Llm('{"account": "given", "reply": "proceeds"}')
    verdict = await ActionConfirmationService(llm).confirm("flag_dispute", {"type": "not_my_transaction"},
                                                           [("user", "No, I never took this loan.")])
    assert verdict.confirmed and "is their account, not a refusal" in llm.asked[0][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("reply, digits", [
    ('{"digits": "2324"}', "2324"), ('{"digits": "٢٣٢٤"}', ""), ('{"digits": "23 24"}', ""), ("none", ""),
])
async def test_spoken_digits_come_back_as_ascii_or_not_at_all(reply, digits):
    llm = _Llm(reply)
    turns = [("assistant", "The last four digits of your mobile?"), ("user", "اثنان ثلاثة اثنان أربعة")]
    assert await ActionConfirmationService(llm).digits(turns) == digits
    # The agent's question goes with the answer: digits are read as the answer to it.
    assert "Agent: The last four digits" in llm.asked[0][1] and "not the answer" in llm.asked[0][0]


@pytest.mark.asyncio
async def test_telemetry_carries_the_decision_not_the_conversation(monkeypatch):
    """Third review: span input held the conversation and terms, span output the digits."""
    from api.services.workflow import action_confirmation

    recorded = {}

    class _Span:
        def set_attribute(self, key, value):
            recorded[key] = value

    class _Tracer:
        def start_as_current_span(self, name, context=None):
            from contextlib import contextmanager

            @contextmanager
            def cm():
                yield _Span()
            return cm()

    monkeypatch.setattr(action_confirmation.trace, "get_tracer", lambda _n: _Tracer())
    service = ActionConfirmationService(_Llm('{"read_back": "matches", "reply": "agrees"}', '{"digits": "2324"}'))
    await service.confirm("promise_to_pay", TERMS, TURNS)
    await service.digits(TURNS)
    assert recorded["confirmation.status"] == "confirmed" and recorded["digits.count"] == 4
    shown = " ".join(str(v) for v in recorded.values())
    assert "سجّلها" not in shown and "3,000" not in shown and "2324" not in shown and "5000" not in shown


def test_terms_that_differ_only_in_form_are_the_same_terms():
    assert terms_key({"amount": 5000, "date": "2026-10-07 "}) == terms_key({"date": "2026-10-07", "amount": "5000.0"})
    assert terms_key(TERMS) != terms_key({**TERMS, "amount": 4000})


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
    engine._active_agent = SimpleNamespace(confirmation_llm=llm, visit_id="visit",
                                           current_node=SimpleNamespace(id="agree"))
    engine._get_otel_context = lambda: None
    engine._pending_action = None
    engine._digit_read = None
    engine._verification_required = set()
    engine._verification_outcomes = {}
    return engine


def test_the_check_sees_the_conversation_not_the_engines_own_messages():
    assert _engine().recent_turns() == [("assistant", "Shall I record 4,000 for Friday?"), ("user", "हाँ जी")]


@pytest.mark.asyncio
async def test_the_engine_fails_closed(monkeypatch):
    assert await _engine(llm=None).confirm_action("promise_to_pay", {}) == UNAVAILABLE

    broken = SimpleNamespace(_settings=None, run_inference=AsyncMock(side_effect=RuntimeError("down")))
    assert await _engine(broken).confirm_action("promise_to_pay", {}) == UNAVAILABLE
    assert await _engine(broken).read_digits() == ""

    from api.services.workflow import pipecat_engine

    async def slow(*_a, **_k):
        await asyncio.sleep(1)

    monkeypatch.setattr(pipecat_engine, "CHECK_TIMEOUT_SECS", 0.01)
    hung = SimpleNamespace(_settings=None, run_inference=slow)
    assert await _engine(hung).confirm_action("promise_to_pay", {}) == UNAVAILABLE


@pytest.mark.asyncio
async def test_a_held_write_is_checked_as_the_answer_arrives_and_bound_to_it():
    """Third review's latency path: the check runs alongside the reply, and its
    verdict counts only for the same answer, terms, action and step."""
    llm = _Llm('{"read_back": "matches", "reply": "agrees"}', '{"read_back": "differs", "reply": "agrees"}',
               delay=0.05)
    engine = _engine(llm)
    terms = {"amount": 4000, "date": "2026-10-02"}
    engine.hold_action("promise_to_pay", terms)          # read back in the same response as the call
    engine.on_customer_message()                          # nothing new from the customer yet: no check
    assert engine._pending_action.check is None and not llm.asked

    yes = {"role": "user", "content": "Yes"}
    engine.context.messages.append(yes)
    engine.on_customer_message()                          # the answer is in context: the check starts now
    await asyncio.sleep(0)
    assert len(llm.asked) == 1
    # The write with the same terms (in another form) uses that verdict: no second call.
    assert await engine.confirm_action("promise_to_pay", {"date": "2026-10-02", "amount": 4000.0}) == \
        Verdict(Confirmation.CONFIRMED, "agreed")
    assert len(llm.asked) == 1
    # Other terms are checked afresh, never on the verdict for the held ones.
    assert (await engine.confirm_action("promise_to_pay", {"amount": 3000, "date": "2026-10-02"})).reason == \
        "other_terms"
    assert len(llm.asked) == 2


@pytest.mark.asyncio
async def test_digits_are_read_from_the_answer_as_it_arrives():
    llm = _Llm('{"digits": "2324"}')
    engine = _engine(llm)
    engine._verification_required = {("visit", "agree")}
    engine.on_customer_message()
    await asyncio.sleep(0)
    assert len(llm.asked) == 1 and await engine.read_digits() == "2324" and len(llm.asked) == 1
