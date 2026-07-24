"""Azure OpenAI client for embeddings + chat (deployment names from env)."""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from typing import Any, Iterator

from openai import AzureOpenAI

from env_loader import load_env

logger = logging.getLogger(__name__)

EXPECTED_EMBEDDING_DIMS = 1536

_client: AzureOpenAI | None = None
_client_lock = threading.Lock()
_azure_sem: threading.Semaphore | None = None
_azure_sem_lock = threading.Lock()

# Process-local embedding LRU. Correct for one API worker; with
# uvicorn --workers >1 each process has its own cache (low hit rate → Redis).
_embed_cache: OrderedDict[str, list[float]] = OrderedDict()
_embed_cache_lock = threading.Lock()
_EMBED_CACHE_HITS = 0
_EMBED_CACHE_MISSES = 0


class AzureOpenAIConfigError(RuntimeError):
    pass


class AzureBusyError(RuntimeError):
    """Raised when the Azure concurrency semaphore times out waiting for a slot."""


def _require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise AzureOpenAIConfigError(f"Missing required env var: {name}")
    return value


def _env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _api_timeout_s() -> float:
    # Prefer shorter timeouts on the CRM request path; workers can raise via env.
    return float(max(5, _env_int("AZURE_OPENAI_TIMEOUT_S", 20)))


def _concurrency_limit() -> int:
    return max(1, _env_int("AZURE_OPENAI_MAX_CONCURRENT", 6))


def _semaphore() -> threading.Semaphore:
    global _azure_sem
    if _azure_sem is not None:
        return _azure_sem
    with _azure_sem_lock:
        if _azure_sem is None:
            _azure_sem = threading.Semaphore(_concurrency_limit())
        return _azure_sem


def _acquire_timeout_s() -> float:
    return float(max(1, _env_int("AZURE_OPENAI_ACQUIRE_TIMEOUT_S", 10)))


@contextmanager
def _azure_slot() -> Iterator[None]:
    """Cap concurrent Azure calls so DB pool + threadpool aren't unbounded.

    Bounded acquire: if all slots are busy, shed with AzureBusyError (→ 503)
    instead of queuing forever while holding a threadpool slot (and possibly a
    DB connection on a buggy caller path).
    """
    sem = _semaphore()
    if not sem.acquire(timeout=_acquire_timeout_s()):
        raise AzureBusyError("azure_concurrency_saturated")
    try:
        yield
    finally:
        sem.release()


def _azure_call(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Semaphore + circuit breaker around a single Azure HTTP call."""
    import circuit_breaker

    breaker = circuit_breaker.get_breaker("azure_openai")

    def _inner() -> Any:
        with _azure_slot():
            return fn(*args, **kwargs)

    return breaker.call(_inner)


def get_embedding_dims() -> int:
    load_env()
    raw = (os.getenv("AZURE_OPENAI_EMBEDDING_DIMS") or str(EXPECTED_EMBEDDING_DIMS)).strip()
    try:
        dims = int(raw)
    except ValueError as exc:
        raise AzureOpenAIConfigError(f"AZURE_OPENAI_EMBEDDING_DIMS must be an int, got {raw!r}") from exc
    if dims != EXPECTED_EMBEDDING_DIMS:
        raise AzureOpenAIConfigError(
            f"AZURE_OPENAI_EMBEDDING_DIMS={dims} but kb_chunks.embedding is vector({EXPECTED_EMBEDDING_DIMS})"
        )
    return dims


def get_chat_deployment() -> str:
    load_env()
    return _require("AZURE_OPENAI_CHAT_DEPLOYMENT")


def _reasoning_override() -> bool | None:
    """Explicit config: reasoning models (o-series / GPT-5) reject a custom
    ``temperature`` and require ``max_completion_tokens``. Deployment names are
    user-defined aliases (an o-series model may be named ``prod-chat``), so an
    explicit flag must be able to force the behaviour. Returns True/False when the
    flag is set, else None to fall back to the name heuristic.
    """
    raw = (os.getenv("AZURE_OPENAI_REASONING_MODEL") or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


def _is_reasoning_deployment(deployment: str) -> bool:
    """Whether the chat deployment is a reasoning model. Explicit override wins;
    otherwise fall back to matching the common family substrings in the name.
    """
    override = _reasoning_override()
    if override is not None:
        return override
    d = (deployment or "").lower()
    return (
        d.startswith(("o1", "o3", "o4"))
        or "gpt-5" in d
        or "gpt5" in d
        or "-o1" in d
        or "-o3" in d
        or "-o4" in d
    )


def get_embedding_deployment() -> str:
    load_env()
    return _require("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")


def get_client() -> AzureOpenAI:
    """Process-wide singleton — reuses HTTP keep-alive / TLS to Azure.

    Creating a client per call paid a fresh handshake on every embed/chat
    (painful on India→East US RTT). Do not construct AzureOpenAI elsewhere.
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        load_env()
        get_embedding_dims()  # fail fast on dim mismatch
        _client = AzureOpenAI(
            api_key=_require("AZURE_OPENAI_API_KEY"),
            api_version=_require("AZURE_OPENAI_API_VERSION"),
            azure_endpoint=_require("AZURE_OPENAI_ENDPOINT").rstrip("/") + "/",
            timeout=_api_timeout_s(),
            max_retries=2,
        )
        return _client


def _embed_cache_max() -> int:
    return max(0, _env_int("AZURE_EMBED_CACHE_MAX", 256))


def _embed_cache_key(deployment: str, text: str) -> str:
    digest = hashlib.sha256(f"{deployment}\0{text}".encode("utf-8")).hexdigest()
    return digest


def embed_cache_stats() -> dict[str, int]:
    with _embed_cache_lock:
        return {
            "size": len(_embed_cache),
            "max": _embed_cache_max(),
            "hits": _EMBED_CACHE_HITS,
            "misses": _EMBED_CACHE_MISSES,
        }


def embed_texts(texts: list[str], *, batch_size: int | None = None) -> list[list[float]]:
    """Embed texts via the configured Azure embedding deployment. Returns 1536-d vectors."""
    global _EMBED_CACHE_HITS, _EMBED_CACHE_MISSES
    if not texts:
        return []
    load_env()
    if batch_size is None:
        raw = (os.getenv("AZURE_OPENAI_EMBED_BATCH_SIZE") or "16").strip()
        try:
            batch_size = max(1, min(128, int(raw)))
        except ValueError:
            batch_size = 16
    client = get_client()
    deployment = get_embedding_deployment()
    dims = get_embedding_dims()
    cache_max = _embed_cache_max()

    out: list[list[float] | None] = [None] * len(texts)
    miss_indices: list[int] = []
    miss_texts: list[str] = []

    if cache_max > 0:
        with _embed_cache_lock:
            for i, raw_text in enumerate(texts):
                cleaned = raw_text if raw_text.strip() else " "
                key = _embed_cache_key(deployment, cleaned)
                hit = _embed_cache.get(key)
                if hit is not None:
                    _embed_cache.move_to_end(key)
                    out[i] = list(hit)
                    _EMBED_CACHE_HITS += 1
                else:
                    miss_indices.append(i)
                    miss_texts.append(cleaned)
                    _EMBED_CACHE_MISSES += 1
    else:
        miss_indices = list(range(len(texts)))
        miss_texts = [t if t.strip() else " " for t in texts]

    if miss_texts:
        embedded: list[list[float]] = []
        for i in range(0, len(miss_texts), batch_size):
            batch = miss_texts[i : i + batch_size]
            t0 = time.perf_counter()
            resp = _azure_call(client.embeddings.create, model=deployment, input=batch)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            ordered = sorted(resp.data, key=lambda d: d.index)
            for item in ordered:
                vec = list(item.embedding)
                if len(vec) != dims:
                    raise AzureOpenAIConfigError(
                        f"Embedding length {len(vec)} != expected {dims} (deployment={deployment})"
                    )
                embedded.append(vec)
            usage = getattr(resp, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            logger.info(
                "azure_embed deployment=%s batch=%s latency_ms=%s prompt_tokens=%s",
                deployment,
                len(batch),
                latency_ms,
                prompt_tokens,
            )
            try:
                import usage_meter

                usage_meter.record_embed_usage(
                    prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
                    deployment=deployment,
                    batch_size=len(batch),
                    source_ref="azure_openai.embed_texts",
                )
            except Exception:
                logger.exception("embed usage metering failed")

        if cache_max > 0:
            with _embed_cache_lock:
                for local_i, idx in enumerate(miss_indices):
                    vec = embedded[local_i]
                    out[idx] = vec
                    key = _embed_cache_key(deployment, miss_texts[local_i])
                    _embed_cache[key] = list(vec)
                    _embed_cache.move_to_end(key)
                    while len(_embed_cache) > cache_max:
                        _embed_cache.popitem(last=False)
        else:
            for local_i, idx in enumerate(miss_indices):
                out[idx] = embedded[local_i]

    return [v if v is not None else [] for v in out]


def chat_complete(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_completion_tokens: int = 800,
) -> str:
    return chat_complete_detailed(
        messages,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
    )["content"]


def chat_complete_detailed(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_completion_tokens: int = 800,
) -> dict[str, Any]:
    """Chat completion with latency + token usage for Sandbox/runtime telemetry."""
    result = chat_with_tools(
        messages,
        tools=None,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
    )
    return {
        "content": result["content"],
        "latencyMs": result["latencyMs"],
        "promptTokens": result["promptTokens"],
        "completionTokens": result["completionTokens"],
        "totalTokens": result["totalTokens"],
        "model": result["model"],
    }


def chat_with_tools(
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
    temperature: float = 0.2,
    max_completion_tokens: int = 800,
) -> dict[str, Any]:
    """OpenAI-compatible chat completion with optional tool calls (Azure).

    Returns content, tool_calls (list of {id,name,arguments}), finish_reason,
    and usage/latency fields.
    """
    client = get_client()
    deployment = get_chat_deployment()
    kwargs: dict[str, Any] = {
        "model": deployment,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }
    # Reasoning deployments (o-series / GPT-5) only accept the default temperature.
    if not _is_reasoning_deployment(deployment):
        kwargs["temperature"] = temperature
    if tools:
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

    t0 = time.perf_counter()
    resp = _azure_call(client.chat.completions.create, **kwargs)
    latency_ms = int((time.perf_counter() - t0) * 1000)

    choice = resp.choices[0]
    message = choice.message
    content = (message.content or "").strip() if message.content else ""
    finish_reason = getattr(choice, "finish_reason", None)

    tool_calls_out: list[dict[str, Any]] = []
    raw_tool_calls = getattr(message, "tool_calls", None) or []
    for tc in raw_tool_calls:
        fn = getattr(tc, "function", None)
        tool_calls_out.append(
            {
                "id": getattr(tc, "id", None) or "",
                "name": getattr(fn, "name", None) or "",
                "arguments": getattr(fn, "arguments", None) or "{}",
            }
        )

    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
    total_tokens = getattr(usage, "total_tokens", None) if usage else None
    logger.info(
        "azure_chat deployment=%s latency_ms=%s prompt_tokens=%s completion_tokens=%s tools=%s",
        deployment,
        latency_ms,
        prompt_tokens,
        completion_tokens,
        len(tool_calls_out),
    )
    try:
        import usage_meter

        usage_meter.record_chat_usage(
            prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
            completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
            total_tokens=int(total_tokens) if total_tokens is not None else None,
            model=deployment,
            source_ref="azure_openai.chat_with_tools",
        )
    except Exception:
        logger.exception("chat usage metering failed")

    return {
        "content": content,
        "toolCalls": tool_calls_out,
        "finishReason": finish_reason,
        "latencyMs": latency_ms,
        "promptTokens": int(prompt_tokens) if prompt_tokens is not None else None,
        "completionTokens": int(completion_tokens) if completion_tokens is not None else None,
        "totalTokens": int(total_tokens) if total_tokens is not None else None,
        "model": deployment,
        "rawMessage": {
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls_out
            ]
            or None,
        },
    }


def smoke_test() -> dict[str, Any]:
    """Minimal connectivity check for ops / ingest bootstrap."""
    vecs = embed_texts(["knowledge base smoke test"])
    reply = chat_complete(
        [
            {"role": "system", "content": "Reply with exactly: ok"},
            {"role": "user", "content": "ping"},
        ],
        max_completion_tokens=16,
    )
    return {
        "embedding_dims": len(vecs[0]),
        "embedding_deployment": get_embedding_deployment(),
        "chat_deployment": get_chat_deployment(),
        "chat_reply": reply,
    }
