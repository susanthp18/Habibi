"""Process-wide Azure OpenAI client for the voice turn loop.

Pipecat's AzureLLMService.create_client() does NOT set httpx keep-alive
(unlike OpenAILLMService). Without keepalive_expiry=None every turn can
re-handshake TLS to East US 2 (~1–2s from India).

This module owns one shared AsyncAzureOpenAI with persistent keep-alives.
Prewarm and the Pipecat LLM service must share the same client.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncAzureOpenAI, DefaultAsyncHttpxClient

from pipecat.services.azure.llm import AzureLLMService

from voice import config as voice_config

logger = logging.getLogger(__name__)

_client: AsyncAzureOpenAI | None = None
_lock = asyncio.Lock()
_prewarmed = False
_last_prewarm_ms: float | None = None


def _build_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        api_key=voice_config.azure_openai_voice_api_key(),
        api_version=voice_config.azure_openai_voice_api_version(),
        azure_endpoint=voice_config.azure_openai_voice_endpoint().rstrip("/") + "/",
        max_retries=2,
        timeout=httpx.Timeout(30.0, connect=10.0),
        http_client=DefaultAsyncHttpxClient(
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=40,
                # Never idle-expire — critical for multi-turn voice calls.
                keepalive_expiry=None,
            ),
        ),
    )


async def get_shared_client() -> AsyncAzureOpenAI:
    """Return the process-wide voice LLM client (create once)."""
    global _client
    async with _lock:
        if _client is None:
            _client = _build_client()
            logger.info(
                "voice LLM shared client created · endpoint=%s · deployment=%s",
                voice_config.azure_openai_voice_endpoint(),
                voice_config.azure_openai_voice_deployment(),
            )
        return _client


def get_shared_client_sync() -> AsyncAzureOpenAI:
    """Sync accessor for constructors (creates if missing)."""
    global _client
    if _client is None:
        _client = _build_client()
    return _client


class KeepAliveAzureLLMService(AzureLLMService):
    """AzureLLMService that reuses the process-wide keep-alive client."""

    def create_client(self, api_key=None, base_url=None, **kwargs):  # noqa: ANN001
        return get_shared_client_sync()


def _needs_max_completion_tokens(deployment: str) -> bool:
    """gpt-5 / o-series deployments require ``max_completion_tokens``, not ``max_tokens``."""
    d = (deployment or "").lower()
    return d.startswith(("o1", "o3", "o4")) or "gpt-5" in d or "gpt5" in d


async def _completion_ping(client: AsyncAzureOpenAI, deployment: str) -> None:
    # NB: use a small-but-nonzero output budget. max_(completion_)tokens=1 makes
    # gpt-5.x return 400 "could not finish the message" (the single token can't
    # complete a message), which made the prewarm fail with a scary traceback and
    # left the first real turn cold. 16 is enough to complete "ok".
    # Pick the param by deployment family up front; only fall back on the API's
    # rejection so a wording change can't silently leave prewarm cold.
    msgs = [{"role": "user", "content": "Reply with: ok"}]
    primary, fallback = (
        ("max_completion_tokens", "max_tokens")
        if _needs_max_completion_tokens(deployment)
        else ("max_tokens", "max_completion_tokens")
    )
    try:
        await client.chat.completions.create(
            model=deployment, messages=msgs, temperature=0, **{primary: 16}
        )
    except Exception as exc:
        low = str(exc).lower()
        if primary not in low and "unsupported" not in low:
            raise
        await client.chat.completions.create(
            model=deployment, messages=msgs, temperature=0, **{fallback: 16}
        )


async def prewarm_shared_client(*, force: bool = False) -> float:
    """Warm TLS + HTTP on the shared client. Does NOT close it.

    Returns elapsed ms of the warm-up completion (0 on failure).
    """
    global _prewarmed, _last_prewarm_ms
    if _prewarmed and not force:
        return float(_last_prewarm_ms or 0.0)

    client = await get_shared_client()
    deployment = voice_config.azure_openai_voice_deployment()
    t0 = time.perf_counter()
    try:
        await _completion_ping(client, deployment)
        ms = (time.perf_counter() - t0) * 1000.0
        _prewarmed = True
        _last_prewarm_ms = ms
        logger.info(
            "voice LLM prewarm OK · deployment=%s · %.0f ms (shared client kept open)",
            deployment,
            ms,
        )
        return ms
    except Exception:
        logger.exception("voice LLM prewarm failed · deployment=%s", deployment)
        return 0.0


def _stat(xs: list[float]) -> dict[str, float] | None:
    if not xs:
        return None
    s = sorted(xs)
    return {
        "n": float(len(s)),
        "min": s[0],
        "p50": s[len(s) // 2],
        "max": s[-1],
        "mean": round(sum(s) / len(s), 1),
    }


async def measure_bottlenecks(rounds: int = 5) -> dict[str, Any]:
    """Break down DNS / cold HTTP / warm HTTP / LLM-TTFB on the shared client."""
    endpoint = voice_config.azure_openai_voice_endpoint().rstrip("/")
    host = urlparse(endpoint).hostname or ""
    deployment = voice_config.azure_openai_voice_deployment()
    out: dict[str, Any] = {
        "endpoint": endpoint,
        "host": host,
        "deployment": deployment,
        "region_hint": None,
        "dns_ms": None,
        "http_cold_ms": None,
        "http_warm_ms": [],
        "llm_ttfb_ms": [],
        "notes": [],
    }

    t0 = time.perf_counter()
    try:
        socket.getaddrinfo(host, 443)
        out["dns_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    except OSError as exc:
        out["dns_error"] = str(exc)
        return out

    models_url = f"{endpoint}/openai/models?api-version=2024-02-01"
    headers = {"api-key": voice_config.azure_openai_voice_api_key()}

    # Cold: no keep-alive reuse
    async with httpx.AsyncClient(
        timeout=30.0,
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=1),
    ) as cold:
        t0 = time.perf_counter()
        r = await cold.get(models_url, headers=headers)
        out["http_cold_ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        out["region_hint"] = r.headers.get("x-ms-region") or r.headers.get("x-ms-azure-region")

    # Warm HTTP keep-alive
    warm = DefaultAsyncHttpxClient(
        limits=httpx.Limits(
            max_keepalive_connections=5,
            max_connections=10,
            keepalive_expiry=None,
        )
    )
    try:
        for _ in range(4):
            t0 = time.perf_counter()
            resp = await warm.get(models_url, headers=headers)
            out["http_warm_ms"].append(round((time.perf_counter() - t0) * 1000.0, 1))
            if not out["region_hint"]:
                out["region_hint"] = resp.headers.get("x-ms-region")
    finally:
        await warm.aclose()

    # LLM TTFB on the SAME shared client (prewarm once, then measure)
    client = await get_shared_client()
    await prewarm_shared_client(force=True)

    for _ in range(rounds):
        t0 = time.perf_counter()
        first = None
        try:
            stream = await client.chat.completions.create(
                model=deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a voice assistant. Respond in 1 brief sentence.",
                    },
                    {"role": "user", "content": "Can I pay Friday?"},
                ],
                max_tokens=40,
                temperature=0.2,
                stream=True,
            )
        except Exception:
            stream = await client.chat.completions.create(
                model=deployment,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a voice assistant. Respond in 1 brief sentence.",
                    },
                    {"role": "user", "content": "Can I pay Friday?"},
                ],
                max_completion_tokens=40,
                temperature=0.2,
                stream=True,
            )
        async for ev in stream:
            if ev.choices and (ev.choices[0].delta.content or ""):
                if first is None:
                    first = time.perf_counter()
                break
        try:
            async for _ev in stream:
                pass
        except Exception:
            pass
        if first is not None:
            out["llm_ttfb_ms"].append(round((first - t0) * 1000.0, 1))

    out["http_warm_stats"] = _stat(out["http_warm_ms"])
    out["llm_ttfb_stats"] = _stat(out["llm_ttfb_ms"])

    # Interpret
    warm_http = (out["http_warm_stats"] or {}).get("p50")
    llm_p50 = (out["llm_ttfb_stats"] or {}).get("p50")
    if warm_http and llm_p50:
        model_part = max(0.0, float(llm_p50) - float(warm_http))
        out["approx_model_queue_ms_p50"] = round(model_part, 1)
        out["notes"].append(
            f"Warm HTTP RTT p50≈{warm_http}ms; LLM TTFB p50≈{llm_p50}ms; "
            f"approx model/queue beyond RTT ≈{model_part:.0f}ms"
        )
    if out.get("http_cold_ms") and warm_http:
        out["notes"].append(
            f"Cold HTTP (DNS+TCP+TLS+GET)≈{out['http_cold_ms']}ms vs warm HTTP≈{warm_http}ms — "
            f"handshake tax ≈{float(out['http_cold_ms']) - float(warm_http):.0f}ms"
        )
    out["notes"].append(
        "Shared keep-alive client must be used by both prewarm and Pipecat AzureLLMService "
        "(KeepAliveAzureLLMService)."
    )
    return out
