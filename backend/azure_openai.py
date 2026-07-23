"""Azure OpenAI client for embeddings + chat (deployment names from env)."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from openai import AzureOpenAI

from env_loader import load_env

logger = logging.getLogger(__name__)

EXPECTED_EMBEDDING_DIMS = 1536


class AzureOpenAIConfigError(RuntimeError):
    pass


def _require(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise AzureOpenAIConfigError(f"Missing required env var: {name}")
    return value


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


def get_embedding_deployment() -> str:
    load_env()
    return _require("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")


def get_client() -> AzureOpenAI:
    load_env()
    get_embedding_dims()  # fail fast on dim mismatch
    return AzureOpenAI(
        api_key=_require("AZURE_OPENAI_API_KEY"),
        api_version=_require("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=_require("AZURE_OPENAI_ENDPOINT").rstrip("/") + "/",
        timeout=60.0,
        max_retries=3,
    )


def embed_texts(texts: list[str], *, batch_size: int | None = None) -> list[list[float]]:
    """Embed texts via the configured Azure embedding deployment. Returns 1536-d vectors."""
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
    out: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        # Azure rejects empty strings; keep alignment with placeholders.
        cleaned = [t if t.strip() else " " for t in batch]
        t0 = time.perf_counter()
        resp = client.embeddings.create(model=deployment, input=cleaned)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        ordered = sorted(resp.data, key=lambda d: d.index)
        for item in ordered:
            vec = list(item.embedding)
            if len(vec) != dims:
                raise AzureOpenAIConfigError(
                    f"Embedding length {len(vec)} != expected {dims} (deployment={deployment})"
                )
            out.append(vec)
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
    return out


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
        "temperature": temperature,
        "max_completion_tokens": max_completion_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

    t0 = time.perf_counter()
    resp = client.chat.completions.create(**kwargs)
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
