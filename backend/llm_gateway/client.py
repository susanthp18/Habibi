"""LLM gateway client. All four profiles go through here when the flag is on.

LiteLLM / APIM is an OpenAI-compatible HTTP backend. If LITELLM_BASE_URL is
unset the Azure SDK is the adapter — still one client, still metered, still
spend-capped. azure_openai.chat_with_tools is the kill-switch path when
LLM_GATEWAY_ENABLED is off.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from agent_core.platform_flags import llm_gateway_enabled

logger = logging.getLogger(__name__)

PROFILES = ("voice", "text", "analysis", "internal")

_spend_inr: dict[str, float] = {p: 0.0 for p in PROFILES}


def cap_inr(profile: str) -> float:
    raw = os.getenv(f"LLM_GATEWAY_CAP_{profile.upper()}_INR") or os.getenv("LLM_GATEWAY_CAP_INR") or "0"
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _over_cap(profile: str) -> bool:
    cap = cap_inr(profile)
    return cap > 0 and _spend_inr.get(profile, 0.0) >= cap


def base_url() -> str:
    return (os.getenv("LITELLM_BASE_URL") or os.getenv("LLM_GATEWAY_URL") or "").rstrip("/")


def chat(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
    temperature: float = 0.2,
    max_completion_tokens: int = 800,
    profile: str = "text",
    reasoning_effort: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    if profile not in PROFILES:
        profile = "text"
    if _over_cap(profile):
        raise RuntimeError(f"llm_gateway_spend_cap:{profile}")
    if not base_url():
        raise RuntimeError("llm_gateway_url_missing")

    t0 = time.perf_counter()
    result = _http_chat(
        messages,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        profile=profile,
        timeout=timeout,
    )
    latency_ms = int((time.perf_counter() - t0) * 1000)
    result.setdefault("latencyMs", latency_ms)
    result["gatewayProfile"] = profile
    _meter(result, profile=profile)
    return result


def _http_chat(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict[str, Any] | None,
    temperature: float,
    max_completion_tokens: int,
    profile: str,
    timeout: float | None,
) -> dict[str, Any]:
    import httpx

    key = (os.getenv("LITELLM_API_KEY") or os.getenv("LLM_GATEWAY_KEY") or "").strip()
    model = os.getenv(f"LLM_GATEWAY_{profile.upper()}_MODEL") or os.getenv("LITELLM_MODEL") or "azure/chat"
    try:
        from llm_gateway.canary import model_for

        override = model_for(profile)
        if override:
            model = override
    except Exception:
        pass
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    retries = 2
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = httpx.post(
                base_url() + "/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout or 20.0,
            )
            if resp.status_code >= 500 and attempt < retries:
                continue
            resp.raise_for_status()
            data = resp.json()
            return _normalize_openai(data)
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
    raise RuntimeError(f"llm_gateway_http_failed:{type(last_exc).__name__}") from last_exc


def _normalize_openai(data: dict[str, Any]) -> dict[str, Any]:
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("llm_gateway_no_choices")
    message = (choices[0].get("message") or {})
    tool_calls_out = []
    for tc in message.get("tool_calls") or []:
        fn = tc.get("function") or {}
        tool_calls_out.append(
            {
                "id": tc.get("id"),
                "name": fn.get("name"),
                "arguments": fn.get("arguments") or "{}",
            }
        )
    usage = data.get("usage") or {}
    return {
        "content": (message.get("content") or "").strip(),
        "toolCalls": tool_calls_out,
        "tool_calls": tool_calls_out,
        "finishReason": choices[0].get("finish_reason"),
        "promptTokens": usage.get("prompt_tokens"),
        "completionTokens": usage.get("completion_tokens"),
        "totalTokens": usage.get("total_tokens"),
        "model": data.get("model"),
    }


def _meter(result: dict[str, Any], *, profile: str) -> None:
    try:
        import usage_meter

        pt = int(result.get("promptTokens") or 0)
        ct = int(result.get("completionTokens") or 0)
        usage_meter.record_chat_usage(
            prompt_tokens=pt,
            completion_tokens=ct,
            total_tokens=int(result.get("totalTokens") or 0) or None,
            model=str(result.get("model") or profile),
            source_ref=f"llm_gateway.{profile}",
        )
        # Approximate INR from the same meter internals if present.
        cost = 0.0
        try:
            cost = float(usage_meter.chat_cost_inr(prompt_tokens=pt, completion_tokens=ct))
        except Exception:
            cost = 0.0
        _spend_inr[profile] = _spend_inr.get(profile, 0.0) + cost
    except Exception:
        logger.exception("gateway usage meter failed")


def maybe_chat(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    """HTTP gateway when enabled and URL is set. None → Azure kill-switch."""
    if not llm_gateway_enabled() or not base_url():
        return None
    return chat(*args, **kwargs)
