"""Deterministic prompt lint for Prompt Studio (DEF-1).

No LLM on the default path — optional include_llm for a checklist pass.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from prompt_render import KNOWN_VARIABLES, _TOKEN_RE

logger = logging.getLogger(__name__)

_DISCLOSURE_RE = re.compile(
    r"record(ing|ed)?|this\s+call\s+(is|may\s+be)\s+recorded",
    re.IGNORECASE,
)


def lint_prompt(
    prompt: str,
    guardrails: dict[str, Any],
    *,
    include_llm: bool = False,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text = prompt or ""

    for match in _TOKEN_RE.finditer(text):
        name = match.group(1)
        if name not in KNOWN_VARIABLES:
            findings.append(
                {
                    "severity": "warn",
                    "code": "unknown_variable",
                    "message": f"Unknown variable {{{name}}} — will not be substituted at runtime.",
                    "span": {"start": match.start(), "end": match.end()},
                }
            )

    if guardrails.get("alwaysDiscloseRecording"):
        if not _DISCLOSURE_RE.search(text):
            findings.append(
                {
                    "severity": "error",
                    "code": "missing_recording_disclosure",
                    "message": (
                        "Guardrail alwaysDiscloseRecording is on, but the prompt has no "
                        "recording-disclosure language."
                    ),
                    "span": None,
                }
            )

    prohibited = guardrails.get("prohibited") or []
    if isinstance(prohibited, list):
        lower = text.lower()
        for word in prohibited:
            w = str(word or "").strip()
            if not w:
                continue
            idx = lower.find(w.lower())
            if idx >= 0:
                findings.append(
                    {
                        "severity": "error",
                        "code": "prohibited_word_in_prompt",
                        "message": f'Prohibited phrase "{w}" appears in the system prompt.',
                        "span": {"start": idx, "end": idx + len(w)},
                    }
                )

    if include_llm:
        findings.extend(_llm_checklist(text, guardrails))

    return findings


def _llm_checklist(prompt: str, guardrails: dict[str, Any]) -> list[dict[str, Any]]:
    """Optional Azure chat pass — advisory only, never mutates the prompt."""
    try:
        from azure_openai import chat_complete
    except Exception as exc:  # pragma: no cover - import/config
        logger.warning("prompt_lint_llm_unavailable: %s", exc)
        return [
            {
                "severity": "info",
                "code": "llm_lint_unavailable",
                "message": "LLM lint skipped — Azure OpenAI unavailable.",
                "span": None,
            }
        ]

    system = (
        "You are a compliance checker for a collections voice-bot system prompt. "
        "List missing compliance behaviors vs the given guardrails. "
        "Reply with at most 5 short bullet lines. Do not rewrite the prompt."
    )
    user = (
        f"Guardrails JSON:\n{guardrails}\n\nSystem prompt:\n{prompt[:6000]}\n\n"
        "What compliance behaviors appear missing?"
    )
    try:
        content = chat_complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.1,
            max_completion_tokens=400,
        )
    except Exception as exc:
        logger.warning("prompt_lint_llm_failed: %s", exc)
        return [
            {
                "severity": "info",
                "code": "llm_lint_failed",
                "message": f"LLM lint failed: {exc}",
                "span": None,
            }
        ]

    text = (content or "").strip()
    if not text:
        return []
    return [
        {
            "severity": "info",
            "code": "llm_checklist",
            "message": text[:1500],
            "span": None,
        }
    ]
