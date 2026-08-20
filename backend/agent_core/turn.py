"""Shared turn brain — assemble LLM messages from prompt + history + KB."""

from __future__ import annotations

from typing import Any

from prompt_render import (
    format_untrusted_crm_card,
    render_system_prompt,
    strip_unrendered_crm_tokens,
)

from agent_core.compaction import RAW_LAST_N, bound_history
from agent_core.prompt import build_system_prompt, default_context
from agent_core.understanding import analyze_turn

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
    history_limit: int = RAW_LAST_N,
    prior_summary: str | None = None,
    skill_catalog: str = "",
    active_skill_message: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build chat messages + intent/sentiment for one customer turn.

    Returns keys: messages, rendered_prompt, intent, intent_scores, sentiment,
    sentiment_label, context.
    """
    ctx = default_context(context if isinstance(context, dict) else None)
    # System policy: static tokens only. CRM fields ride a delimited developer card.
    # A CRM token cannot render here, so leaving it in means the model reads
    # "{account_no}" aloud. Same treatment as voice and the text channel.
    rendered = strip_unrendered_crm_tokens(render_system_prompt(prompt_template, ctx))
    # Sandbox only, and the sandbox already makes two Azure calls per turn
    # (retrieval embedding + the reply), so one more is in keeping. It is also
    # the surface where the Inspector's Intent and Sentiment tabs are read, so
    # a Hinglish turn shown as out_of_scope / 0.00 here is the most visible
    # form of the bug this replaces. Degrades to the keyword classifiers.
    understanding = analyze_turn(customer_text, channel="sandbox_text")
    intent = understanding.intent
    intent_scores = understanding.intent_scores
    sentiment = understanding.sentiment
    sent_label = understanding.sentiment_label

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": build_system_prompt(
                rendered_prompt=rendered,
                persona=persona,
                guardrails=guardrails,
                context_blocks=list(context_blocks or []),
                skill_catalog=skill_catalog,
            ),
        },
        {
            "role": "developer",
            "content": format_untrusted_crm_card(ctx),
        },
    ]
    if active_skill_message and active_skill_message.get("content"):
        messages.append(active_skill_message)
    recent_history, summary = bound_history(
        list(history or []),
        last_n=history_limit,
        prior_summary=prior_summary,
    )
    if summary:
        messages.append(
            {
                "role": "developer",
                "content": "Prior turns (summarized, analysis profile):\n" + summary.strip(),
            }
        )
    for h in recent_history:
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
