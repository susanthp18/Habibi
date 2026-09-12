"""The LLM gateway client: the spend cap is a decision, not an outage."""

from __future__ import annotations

import pytest


def test_a_spent_cap_does_not_fall_through_to_azure(monkeypatch) -> None:
    """WS8: azure_openai swallowed `llm_gateway_spend_cap` as a routing
    failure and served the turn from uncapped Azure while the meter labelled
    it gateway spend."""
    import azure_openai
    from llm_gateway import client as gw

    monkeypatch.setattr(gw, "llm_gateway_enabled", lambda: True)
    monkeypatch.setattr(gw, "base_url", lambda: "http://gateway.test")
    monkeypatch.setattr(gw, "_over_cap", lambda _profile: True)
    called = []
    monkeypatch.setattr(azure_openai, "get_client", lambda: called.append("azure") or None)
    with pytest.raises(gw.SpendCapExceeded):
        azure_openai.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])
    assert called == []


def test_the_gateway_has_a_breaker(monkeypatch) -> None:
    """Every caller retried three times against a dead gateway, on every
    turn, with no circuit between them. The breaker opens after the
    threshold and the retry loop stops at CircuitOpenError."""
    import circuit_breaker
    import httpx
    from llm_gateway import client as gw

    with circuit_breaker._breakers_lock:
        circuit_breaker._breakers.pop("llm_gateway", None)
    monkeypatch.setattr(gw, "base_url", lambda: "http://gateway.test")
    monkeypatch.setattr(gw.time, "sleep", lambda s: None)
    calls: list[int] = []

    def _dead(*a, **k):
        calls.append(1)
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "post", _dead)

    def _chat():
        return gw._http_chat(
            [{"role": "user", "content": "hi"}],
            tools=None,
            tool_choice=None,
            temperature=0.0,
            max_completion_tokens=8,
            profile="chat",
            timeout=1.0,
        )

    with pytest.raises(RuntimeError, match="llm_gateway_http_failed"):
        _chat()
    assert len(calls) >= 1
    b = circuit_breaker.get_breaker("llm_gateway")
    for _ in range(b.failure_threshold):
        with pytest.raises(RuntimeError):
            _chat()
    assert b.snapshot()["state"] == "open"
    calls.clear()
    with pytest.raises(RuntimeError, match="CircuitOpenError"):
        _chat()
    assert calls == [], "an open circuit posts nothing"
