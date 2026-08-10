"""Process-wide Azure OpenAI client for the voice turn loop.

Pipecat's AzureLLMService.create_client() does NOT set httpx keep-alive
(unlike OpenAILLMService). Without keepalive_expiry=None every turn can
re-handshake TLS to East US 2 (~1–2s from India).

This module owns one shared AsyncAzureOpenAI with persistent keep-alives.
Prewarm and the Pipecat LLM service must share the same client.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncAzureOpenAI, DefaultAsyncHttpxClient

from pipecat.services.azure.llm import AzureLLMService

from voice import config as voice_config

logger = logging.getLogger(__name__)

_client: AsyncAzureOpenAI | None = None
# threading.Lock, not asyncio.Lock: get_shared_client_sync() is called from
# Pipecat service constructors on whatever thread builds the pipeline, so an
# async-only guard left the sync path unsynchronised — two callers could each
# build a client and the "process-wide" keep-alive pool silently became two.
# Construction is pure object setup (no I/O), so holding this briefly inside
# the coroutine does not block the loop.
_lock = threading.Lock()
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
    return _get_or_build_client(log=True)


def get_shared_client_sync() -> AsyncAzureOpenAI:
    """Sync accessor for constructors (creates if missing)."""
    return _get_or_build_client(log=False)


def _get_or_build_client(*, log: bool) -> AsyncAzureOpenAI:
    global _client
    with _lock:
        if _client is None:
            _client = _build_client()
            if log:
                logger.info(
                    "voice LLM shared client created · endpoint=%s · deployment=%s",
                    voice_config.azure_openai_voice_endpoint(),
                    voice_config.azure_openai_voice_deployment(),
                )
        return _client


class KeepAliveAzureLLMService(AzureLLMService):
    """AzureLLMService that reuses the process-wide keep-alive client."""

    def create_client(self, api_key=None, base_url=None, **kwargs):  # noqa: ANN001
        return get_shared_client_sync()


def _is_reasoning_deployment(deployment: str) -> bool:
    """gpt-5 / o-series deployments require ``max_completion_tokens`` (not
    ``max_tokens``) and reject a custom ``temperature``. Explicit config override
    wins over the name heuristic, since deployment names are user-defined aliases.
    """
    raw = (os.getenv("AZURE_OPENAI_VOICE_REASONING_MODEL")
           or os.getenv("AZURE_OPENAI_REASONING_MODEL") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    d = (deployment or "").lower()
    return d.startswith(("o1", "o3", "o4")) or "gpt-5" in d or "gpt5" in d


def build_completion_kwargs(
    deployment: str, *, max_output_tokens: int, temperature: float | None = None
) -> tuple[dict, str, str]:
    """Deployment-appropriate request kwargs plus the token-param fallback name.

    Reasoning deployments (o1/o3/o4/gpt-5) reject a custom ``temperature`` and
    require ``max_completion_tokens``. Every completion this module and
    voice.spike issue goes through here — the diagnostics used to hardcode
    ``temperature=0.2`` and 400 on exactly the deployments they exist to probe.
    """
    reasoning = _is_reasoning_deployment(deployment)
    primary, fallback = (
        ("max_completion_tokens", "max_tokens")
        if reasoning
        else ("max_tokens", "max_completion_tokens")
    )
    kwargs: dict = {"model": deployment}
    if temperature is not None and not reasoning:
        kwargs["temperature"] = temperature
    kwargs[primary] = max_output_tokens
    return kwargs, primary, fallback


async def _completion_ping(client: AsyncAzureOpenAI, deployment: str) -> None:
    # NB: use a small-but-nonzero output budget. max_(completion_)tokens=1 makes
    # gpt-5.x return 400 "could not finish the message" (the single token can't
    # complete a message), which made the prewarm fail with a scary traceback and
    # left the first real turn cold. 16 is enough to complete "ok".
    # Pick the param by deployment family up front; only fall back on the API's
    # rejection so a wording change can't silently leave prewarm cold.
    msgs = [{"role": "user", "content": "Reply with: ok"}]
    kwargs, primary, fallback = build_completion_kwargs(
        deployment, max_output_tokens=16, temperature=0
    )
    try:
        await client.chat.completions.create(messages=msgs, **kwargs)
    except Exception as exc:
        # Branch on the API's structured error, not on substrings of the message
        # text: the old check matched any exception whose text happened to
        # contain "max_tokens" or "unsupported" (including auth and quota
        # errors) and re-issued a request that could not possibly succeed.
        if not _is_unsupported_token_param(exc, primary):
            raise
        retry = {k: v for k, v in kwargs.items() if k != primary}
        retry[fallback] = 16
        await client.chat.completions.create(messages=msgs, **retry)


def _is_unsupported_token_param(exc: BaseException, param: str) -> bool:
    """True only for a 400 rejecting `param` as an unsupported parameter."""
    body = getattr(exc, "body", None)
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return False
    code = str(error.get("code") or "")
    if code not in {"unsupported_parameter", "unsupported_value", "invalid_request_error"}:
        return False
    return str(error.get("param") or "") == param


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

    msgs = [
        {
            "role": "system",
            "content": "You are a voice assistant. Respond in 1 brief sentence.",
        },
        {"role": "user", "content": "Can I pay Friday?"},
    ]
    # Pick the token-budget parameter (and drop temperature on reasoning
    # deployments) by family instead of issuing a duplicate request on failure —
    # the retry path used to leave the first, already-open stream unclosed and
    # leaked a connection per round.
    ttfb_kwargs, _, _ = build_completion_kwargs(
        deployment, max_output_tokens=40, temperature=0.2
    )
    for _ in range(rounds):
        t0 = time.perf_counter()
        first = None
        stream = await client.chat.completions.create(
            messages=msgs,
            stream=True,
            **ttfb_kwargs,
        )
        try:
            async for ev in stream:
                if ev.choices and (ev.choices[0].delta.content or ""):
                    first = time.perf_counter()
                    break
        finally:
            # Break out of the iterator early → the HTTP response stays open
            # unless it is explicitly closed.
            await stream.close()
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
