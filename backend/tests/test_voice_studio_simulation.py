"""AI customer runs: an LLM plays the customer, the engine plays the agent, graded like checks."""

import pytest

import azure_openai
import voice_studio
import voice_studio_checks as checks


class Engine:
    def __init__(self, agent_lines):
        self.agent = iter(agent_lines)
        self.sent = []
        self.ended = False

    def __call__(self, method, path, json=None, timeout=None):
        if path.endswith("/text-chat/sessions"):
            return self._session(next(self.agent))
        if path.endswith("/messages"):
            self.sent.append(json["text"])
            return self._session(next(self.agent, ""))
        if path.endswith("/end"):
            self.ended = True
        return {}

    @staticmethod
    def _session(said):
        return {"workflow_run_id": 55, "revision": 1, "is_completed": False,
                "session_data": {"turns": [{"assistant_message": {"text": said}, "events": []}]}}


RULES = {"prohibited": ["legal action"]}


def test_ai_customer_talks_until_it_ends_and_the_run_is_graded(monkeypatch):
    engine = Engine(["Hello, this call is recorded. Am I speaking with you?", "Thanks, how can I help?"])
    monkeypatch.setattr(voice_studio, "engine_call", engine)
    lines = iter(["Yes, but I lost my job.", "[END]"])
    monkeypatch.setattr(azure_openai, "chat_complete", lambda messages, **kw: next(lines))
    result = checks.simulate(7, "A worried customer who recently lost their job.", RULES)
    assert engine.sent == ["Yes, but I lost my job."]
    assert engine.ended and result["error"] is None and result["passed"] is True
    assert result["scenarioId"] == checks.SIMULATION_ID and len(result["turns"]) == 2


def test_a_guardrail_break_by_the_agent_fails_the_run(monkeypatch):
    engine = Engine(["Hello, this call is recorded.", "Pay today or we take legal action."])
    monkeypatch.setattr(voice_studio, "engine_call", engine)
    lines = iter(["I can't pay this month.", "[END]"])
    monkeypatch.setattr(azure_openai, "chat_complete", lambda messages, **kw: next(lines))
    result = checks.simulate(7, "A customer who cannot pay this month.", RULES)
    assert result["passed"] is False and result["flags"]


def test_the_customer_llm_sees_the_agent_as_the_other_party(monkeypatch):
    seen = {}

    def fake(messages, **kw):
        seen["messages"] = messages
        return "Hi."

    monkeypatch.setattr(azure_openai, "chat_complete", fake)
    assert checks._customer_line("Polite customer", [("", "Hello from the bank"), ("Hi", "How can I help?")]) == "Hi."
    roles = [m["role"] for m in seen["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_a_vague_persona_is_refused():
    with pytest.raises(ValueError):
        checks.start_simulation(7, "rude", "u-1")


def test_a_placeholder_spoken_to_the_customer_fails_the_run(monkeypatch):
    engine = Engine(["Hello, this call is recorded.", "Your loan is overdue by $[overdue_amount]."])
    monkeypatch.setattr(voice_studio, "engine_call", engine)
    lines = iter(["How much do I owe?", "[END]"])
    monkeypatch.setattr(azure_openai, "chat_complete", lambda messages, **kw: next(lines))
    result = checks.simulate(7, "A customer asking what they owe.", RULES)
    assert "template-leak" in result["flags"] and result["passed"] is False
