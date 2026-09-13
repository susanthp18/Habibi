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

#: The profiles a caller can reach: `azure_openai.chat_with_tools` routes
#: analysis-profile work to `analysis` and everything else to `text`. The voice
#: runtime talks to Azure directly (voice/llm_pool) and never enters here.
PROFILES = ("text", "analysis")


def cap_inr(profile: str) -> float:
    raw = os.getenv(f"LLM_GATEWAY_CAP_{profile.upper()}_INR") or os.getenv("LLM_GATEWAY_CAP_INR") or "0"
    try:
        return float(raw)
    except ValueError:
        return 0.0


def spent_today_inr(profile: str) -> float:
    """What the tenant has spent through this profile since local midnight.

    Read from `usage_events` -- the same rows `usage_meter.record_chat_usage`
    writes for every gateway turn -- so the cap is one number across the api,
    the workers and every replica. It used to be a dict in each process,
    reset on restart and never shared, so N processes had N caps.
    """
    import db
    from sqlalchemy import text

    with db.engine.connect() as conn:
        value = conn.execute(
            text(
                """
                SELECT COALESCE(SUM(cost_inr), 0)
                FROM usage_events
                WHERE tenant_id = :tenant
                  AND source_ref = :ref
                  AND occurred_at >= date_trunc('day', now())
                """
            ),
            {"tenant": db.current_tenant(), "ref": f"llm_gateway.{profile}"},
        ).scalar()
    return float(value or 0)


def _over_cap(profile: str) -> bool:
    cap = cap_inr(profile)
    if cap <= 0:
        return False
    try:
        return spent_today_inr(profile) >= cap
    except Exception:
        # A cap that cannot be read is a cap that is spent: the caller must not
        # fall through to uncapped spend because the ledger was unreachable.
        logger.exception("gateway spend cap unreadable for profile=%s -- refusing", profile)
        return True


def base_url() -> str:
    return (os.getenv("LITELLM_BASE_URL") or os.getenv("LLM_GATEWAY_URL") or "").rstrip("/")


class SpendCapExceeded(RuntimeError):
    """The profile's spend cap is spent. Not a transport fault: the caller
    must not fall through to uncapped Azure, which is what a bare
    RuntimeError swallowed by the kill-switch made it do."""

    def __init__(self, profile: str) -> None:
        super().__init__(f"llm_gateway_spend_cap:{profile}")
        self.profile = profile


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
        raise SpendCapExceeded(profile)
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
        reasoning_effort=reasoning_effort,
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
    reasoning_effort: str | None = None,
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
    }
    # A reasoning deployment answers 400 to a temperature and takes an
    # effort instead; the direct Azure client already made this choice and
    # the gateway path sent both wrong: temperature always, effort never.
    import azure_openai

    if azure_openai._is_reasoning_deployment(model.rsplit("/", 1)[-1]):
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
    else:
        payload["temperature"] = temperature
    if tools:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    import circuit_breaker

    # The gateway had no breaker: every caller retried three times against a
    # dead gateway, on every turn. The breaker opens after the threshold and
    # the retry loop sees CircuitOpenError immediately.
    breaker = circuit_breaker.get_breaker("llm_gateway")

    def _post_once() -> Any:
        resp = httpx.post(
            base_url() + "/chat/completions",
            json=payload,
            headers=headers,
            timeout=timeout or 20.0,
        )
        if resp.status_code >= 500:
            resp.raise_for_status()
        return resp

    retries = 2
    last_exc: Exception | None = None
    pause: float | None = None
    for attempt in range(retries + 1):
        if attempt:
            # A retry with no pause hits a gateway that is still failing with
            # the same request a few milliseconds later; a throttle says how
            # long to wait and that wait replaces the backoff.
            time.sleep(pause if pause is not None else 0.25 * (2 ** (attempt - 1)))
            pause = None
        try:
            resp = breaker.call(_post_once)
            if 400 <= resp.status_code < 500:
                # The request is wrong, or we are being throttled: the same
                # bytes again will get the same answer. A 429 says when.
                if resp.status_code == 429 and attempt < retries:
                    pause = _retry_after_s(resp)
                    continue
                raise GatewayRejected(resp.status_code, resp.text[:200])
            resp.raise_for_status()
            data = resp.json()
            return _normalize_openai(data)
        except circuit_breaker.CircuitOpenError as exc:
            last_exc = exc
            break
        except GatewayRejected as exc:
            last_exc = exc
            break
        except httpx.ReadTimeout as exc:
            # The gateway may have forwarded the completion before we gave
            # up on it; a second POST is a second completion, billed twice
            # and possibly spoken twice. Report the timeout instead.
            last_exc = exc
            break
        except Exception as exc:
            last_exc = exc
            if attempt >= retries:
                break
    raise RuntimeError(f"llm_gateway_http_failed:{type(last_exc).__name__}") from last_exc


class GatewayRejected(Exception):
    """A 4xx from the gateway: the request, not the gateway, is at fault."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"{status}:{body}")
        self.status = status


def _retry_after_s(resp: Any) -> float:
    """The gateway's own pause on a 429, bounded; a short default when absent."""
    try:
        value = float(resp.headers.get("Retry-After") or 1.0)
    except (TypeError, ValueError):
        value = 1.0
    return max(0.0, min(value, 5.0))


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
    except Exception:
        logger.exception("gateway usage meter failed")


def maybe_chat(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    """HTTP gateway when enabled and URL is set. None → Azure kill-switch."""
    if not llm_gateway_enabled() or not base_url():
        return None
    return chat(*args, **kwargs)
