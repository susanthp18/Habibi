"""Shared turn brain — assemble LLM messages from prompt + history + KB."""

from __future__ import annotations

from typing import Any

from prompt_render import render_prompt

from agent_core.intent import classify_intent
from agent_core.prompt import build_system_prompt, default_context
from agent_core.sentiment import estimate_sentiment, sentiment_label

CHAT_TEMPERATURE = 0.2
DEFAULT_TOP_K = 3


def context_blocks_from_results(results: list[dict[str, Any]]) -> list[str]:
    return [
        f"[{r.get('docTitle') or r.get('docId')}] {r.get('heading') or ''}\n{r.get('snippet') or ''}"
        for r in results
    ]


def assemble_turn_messages(
    *,
    prompt_template: str,
    persona: dict[str, Any],
    guardrails: dict[str, Any],
    customer_text: str,
    context: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    context_blocks: list[str] | None = None,
    history_limit: int = 12,
) -> dict[str, Any]:
    """Build chat messages + intent/sentiment for one customer turn.

    Returns keys: messages, rendered_prompt, intent, intent_scores, sentiment,
    sentiment_label, context.
    """
    ctx = default_context(context if isinstance(context, dict) else None)
    rendered = render_prompt(prompt_template, ctx)
    intent, intent_scores = classify_intent(customer_text)
    sentiment = estimate_sentiment(customer_text)
    sent_label = sentiment_label(sentiment)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                rendered_prompt=rendered,
                persona=persona,
                guardrails=guardrails,
                context_blocks=list(context_blocks or []),
            ),
        }
    ]
    for h in (history or [])[-history_limit:]:
        if not isinstance(h, dict):
            continue
        role = h.get("role")
        text_h = (h.get("text") or "").strip()
        if not text_h:
            continue
        if role == "bot":
            messages.append({"role": "assistant", "content": text_h})
        elif role == "customer":
            messages.append({"role": "user", "content": text_h})
    messages.append({"role": "user", "content": customer_text})

    return {
        "messages": messages,
        "rendered_prompt": rendered,
        "intent": intent,
        "intent_scores": intent_scores,
        "sentiment": sentiment,
        "sentiment_label": sent_label,
        "context": ctx,
    }
