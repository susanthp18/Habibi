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


def test_the_spend_cap_is_one_number_across_processes(db_tx, monkeypatch) -> None:
    """The cap was a dict in each process -- reset on restart, never shared --
    so the api and every worker each had the whole cap. It reads the same
    usage_events rows the meter writes, so a turn metered anywhere counts
    everywhere; and a ledger that cannot be read is a cap that is spent."""
    from sqlalchemy import text

    import db
    from llm_gateway import client as gw

    monkeypatch.setenv("LLM_GATEWAY_CAP_TEXT_INR", "5")
    assert gw._over_cap("text") is False
    db_tx.execute(
        text(
            "INSERT INTO usage_events (id, tenant_id, environment, service_id, units, cost_inr, source_ref) "
            "SELECT 'UE-CAP-PROBE', :t, 'production', id, 1, 6.5, 'llm_gateway.text' FROM billing_services LIMIT 1"
        ),
        {"t": db.current_tenant()},
    )
    assert gw.spent_today_inr("text") >= 6.5
    assert gw._over_cap("text") is True

    def _boom(_profile):
        raise RuntimeError("ledger unreachable")

    monkeypatch.setattr(gw, "spent_today_inr", _boom)
    assert gw._over_cap("text") is True


def _gw(monkeypatch):
    import circuit_breaker
    from llm_gateway import client as gw

    with circuit_breaker._breakers_lock:
        circuit_breaker._breakers.pop("llm_gateway", None)
    monkeypatch.setattr(gw, "base_url", lambda: "http://gateway.test")
    monkeypatch.setattr(gw.time, "sleep", lambda s: None)
    monkeypatch.delenv("AZURE_OPENAI_REASONING_MODEL", raising=False)
    return gw


def _chat(gw, **kw):
    return gw._http_chat(
        [{"role": "user", "content": "hi"}],
        tools=None,
        tool_choice=None,
        temperature=0.3,
        max_completion_tokens=8,
        profile="chat",
        timeout=1.0,
        **kw,
    )


def test_a_client_error_is_not_retried(monkeypatch) -> None:
    """The same bytes get the same 400; three of them are three bills for
    one mistake and a 4xx never trips the breaker either."""
    import circuit_breaker
    import httpx

    gw = _gw(monkeypatch)
    calls: list[int] = []

    def _bad(*a, **k):
        calls.append(1)
        return httpx.Response(400, text="bad request", request=httpx.Request("POST", "x"))

    monkeypatch.setattr(httpx, "post", _bad)
    with pytest.raises(RuntimeError, match="GatewayRejected"):
        _chat(gw)
    assert calls == [1]
    assert circuit_breaker.get_breaker("llm_gateway").snapshot()["state"] == "closed"


def test_a_throttle_waits_what_the_gateway_says_then_tries_once_more(monkeypatch) -> None:
    import httpx

    gw = _gw(monkeypatch)
    waits: list[float] = []
    monkeypatch.setattr(gw.time, "sleep", lambda s: waits.append(s))
    answers = iter(
        [
            httpx.Response(429, headers={"Retry-After": "2"}, request=httpx.Request("POST", "x")),
            httpx.Response(
                200,
                json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}},
                request=httpx.Request("POST", "x"),
            ),
        ]
    )
    monkeypatch.setattr(httpx, "post", lambda *a, **k: next(answers))
    out = _chat(gw)
    assert out["content"] == "ok"
    assert waits == [2.0]


def test_a_read_timeout_is_not_replayed(monkeypatch) -> None:
    """The gateway may have forwarded the completion before we gave up on
    it. A second POST is a second completion, billed and possibly spoken."""
    import httpx

    gw = _gw(monkeypatch)
    calls: list[int] = []

    def _slow(*a, **k):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", _slow)
    with pytest.raises(RuntimeError, match="ReadTimeout"):
        _chat(gw)
    assert calls == [1]


def test_a_reasoning_model_gets_effort_and_no_temperature(monkeypatch) -> None:
    import httpx

    gw = _gw(monkeypatch)
    seen: list[dict] = []

    def _ok(url, json, **k):
        seen.append(json)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": {}},
            request=httpx.Request("POST", "x"),
        )

    monkeypatch.setattr(httpx, "post", _ok)
    monkeypatch.setenv("LLM_GATEWAY_CHAT_MODEL", "azure/gpt-5-mini")
    _chat(gw, reasoning_effort="low")
    monkeypatch.setenv("LLM_GATEWAY_CHAT_MODEL", "azure/gpt-4o")
    _chat(gw, reasoning_effort="low")
    reasoning, plain = seen
    assert reasoning["reasoning_effort"] == "low" and "temperature" not in reasoning
    assert plain["temperature"] == 0.3 and "reasoning_effort" not in plain


def test_the_three_processes_agree_on_what_a_reasoning_deployment_is(monkeypatch) -> None:
    """The voice pool and the tuning layer carried their own copies with a
    narrower heuristic and a different override order."""
    import azure_openai
    from voice import llm_pool, tuning_apply

    monkeypatch.delenv("AZURE_OPENAI_REASONING_MODEL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_VOICE_REASONING_MODEL", raising=False)
    for name in ("gpt-5-mini", "prod-o3", "gpt-4o", "o1-preview"):
        assert (
            azure_openai._is_reasoning_deployment(name)
            == llm_pool._is_reasoning_deployment(name)
            == tuning_apply._is_reasoning_model(name)
        ), name
    monkeypatch.setenv("AZURE_OPENAI_VOICE_REASONING_MODEL", "true")
    assert llm_pool._is_reasoning_deployment("gpt-4o") is True
    assert azure_openai._is_reasoning_deployment("gpt-4o") is False  # the text override is its own
