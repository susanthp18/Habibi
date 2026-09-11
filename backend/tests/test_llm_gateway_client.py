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
