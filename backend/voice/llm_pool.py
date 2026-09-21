"""Process-wide Azure OpenAI client for the voice turn loop.

Pipecat's AzureLLMService.create_client() does NOT set httpx keep-alive
(unlike OpenAILLMService). Without keepalive_expiry=None every turn can
re-handshake TLS to East US 2 (~1–2s from India).

This module owns one shared AsyncAzureOpenAI with persistent keep-alives.
Prewarm and the Pipecat LLM service must share the same client.
"""

from __future__ import annotations

from typing import Any
import asyncio
import logging
import threading
import time

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
#: When the last real warm-up completion actually ran. ``_prewarmed`` only says
#: it happened once; this says how long ago, which is the difference between a
#: warm process and one that has been idle past the deployment's cold threshold.
_last_prewarm_at: float | None = None


def warm_state() -> dict[str, Any]:
    """Whether this process is warm, and how stale that claim is.

    The cheapest possible detector for the two prewarming gaps: boot warmers
    that never ran in this process at all, and a process warmed at boot that
    has since gone cold. Both are invisible today -- ``_prewarmed`` latches
    True forever and the per-call prewarm returns without doing anything.
    """
    age = (time.monotonic() - _last_prewarm_at) if _last_prewarm_at else None
    return {
        "prewarmed": 1 if _prewarmed else 0,
        "prewarm_age_s": round(age, 1) if age is not None else None,
        "prewarm_ms": int(_last_prewarm_ms) if _last_prewarm_ms else None,
    }


def _guard_completions(client: AsyncAzureOpenAI) -> AsyncAzureOpenAI:
    """Route `chat.completions.create` through the `voice_llm` breaker.

    Every other Azure caller sits behind `circuit_breaker`; the voice client
    did not, so a dead deployment was rediscovered by every call in flight,
    each waiting its full timeout. Wrapped at the one seam pipecat uses.
    """
    import circuit_breaker

    breaker = circuit_breaker.get_breaker("voice_llm")
    create = client.chat.completions.create

    async def guarded(*args, **kwargs):
        return await breaker.acall(create, *args, **kwargs)

    client.chat.completions.create = guarded  # type: ignore[method-assign]
    return client


def _build_client() -> AsyncAzureOpenAI:
    return _guard_completions(_unguarded_client())


def _client_timeouts() -> tuple[httpx.Timeout, int]:
    """Voice-turn timeouts. Analysis profile stays 8s×0 in azure_openai."""
    return httpx.Timeout(connect=3.0, read=15.0, write=5.0, pool=2.0), 1


def _unguarded_client() -> AsyncAzureOpenAI:
    timeout, max_retries = _client_timeouts()
    return AsyncAzureOpenAI(
        api_key=voice_config.azure_openai_voice_api_key(),
        api_version=voice_config.azure_openai_voice_api_version(),
        azure_endpoint=voice_config.azure_openai_voice_endpoint().rstrip("/") + "/",
        max_retries=max_retries,
        timeout=timeout,
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
    """The one definition, with the voice override read first."""
    import azure_openai

    return azure_openai._is_reasoning_deployment(
        deployment, envs=azure_openai.VOICE_REASONING_OVERRIDE_ENVS
    )


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
    # openai types messages as a TypedDict union; a plain dict is what it takes.
    msgs: Any = [{"role": "user", "content": "Reply with: ok"}]
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


#: How long the process may sit idle before the keep-warm loop pings again.
#: Mirrors azure_openai.PREWARM_IDLE_SECONDS, which exists for the same reason:
#: httpx reaps keep-alive connections after a few minutes and Azure lets a
#: deployment go cold, so an outbound campaign runner that spends most of its
#: life between dials is cold nearly every time it is needed.
_KEEP_WARM_INTERVAL_S = 180.0

_keep_warm_task: Any = None


async def ensure_keep_warm() -> None:
    """Start the idle re-warm loop once per process. Idempotent.

    ``_prewarmed`` latches True at boot and never clears, so the per-call
    ``prewarm_shared_client()`` returned without doing any work and the voice
    process had no idle re-warm at all -- the text path has had one since it
    shipped (``azure_openai.PREWARM_IDLE_SECONDS``, re-called per idle tick by
    ``bot_worker.warm_while_idle``). The first caller after a quiet stretch paid
    a cold deployment inside their silent line.

    Deliberately NOT a re-warm on the call path. Warming when a cold call
    arrives just moves the cost into that call -- a real Azure completion
    competing with the same shared client and the same breaker, on the greeting
    least able to afford it. This loop sleeps first and pings only while the
    process is idle, so the ping is always paid by nobody.
    """
    global _keep_warm_task
    if _keep_warm_task is not None and not _keep_warm_task.done():
        return
    _keep_warm_task = asyncio.create_task(_keep_warm_loop())


def _calls_in_flight() -> int:
    try:
        from voice import admission

        return int(admission.snapshot().get("activeCalls") or 0)
    except Exception:
        # Unknown means "assume busy": skipping a warm costs a slow turn,
        # pinging mid-call costs the turn the caller is in.
        return 1


def _warm_text_path() -> None:
    """The chat+embedding deployment the KB path uses, not the voice one.

    ``azure_openai.prewarm`` is called once at boot by the voice runner and
    never again, so the first KB retrieval after a quiet stretch pays the cold
    connection the module documents at ~1.2s. It is synchronous and guards
    itself with its own idle window, so calling it bare each tick is the same
    shape as bot_worker's on_idle hook.
    """
    try:
        import azure_openai

        azure_openai.prewarm()
    except Exception:
        logger.debug("text-path idle warm failed", exc_info=True)


async def _keep_warm_loop() -> None:
    while True:
        try:
            # Sleep first: the call that started this loop must never pay for it.
            await asyncio.sleep(_KEEP_WARM_INTERVAL_S)
            if _calls_in_flight() > 0:
                continue
            await prewarm_shared_client(force=True)
            await asyncio.to_thread(_warm_text_path)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("keep-warm tick failed", exc_info=True)


async def prewarm_shared_client(*, force: bool = False) -> float:
    """Warm TLS + HTTP on the shared client. Does NOT close it.

    Returns elapsed ms of the warm-up completion (0 on failure).
    """
    global _prewarmed, _last_prewarm_ms, _last_prewarm_at
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
        _last_prewarm_at = time.monotonic()
        logger.info(
            "voice LLM prewarm OK · deployment=%s · %.0f ms (shared client kept open)",
            deployment,
            ms,
        )
        return ms
    except Exception:
        logger.exception("voice LLM prewarm failed · deployment=%s", deployment)
        return 0.0
