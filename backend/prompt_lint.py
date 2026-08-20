"""Deterministic prompt lint for Prompt Studio (DEF-1).

No LLM on the default path — optional include_llm for a checklist pass.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from prompt_render import KNOWN_VARIABLES, SYSTEM_SAFE_VARIABLES, TOKEN_RE

logger = logging.getLogger(__name__)

# Deliberately narrow: this backs a compliance gate, so it must match an actual
# *disclosure to the customer*, not any mention of recording. The previous
# pattern accepted "record call details in the CRM" — an unrelated instruction
# that let a prompt pass alwaysDiscloseRecording without disclosing anything.
_SUBJECT = r"(?:this|the|your|our)\s+(?:call|conversation|chat)"
_MODAL = r"(?:is|are|was|may\s+be|might\s+be|will\s+be|could\s+be)"
_DISCLOSURE_RE = re.compile(
    r"(?:"
    # "this call is / may be (being) recorded"
    rf"\b{_SUBJECT}\s+{_MODAL}(?:\s+being)?\s+recorded\b"
    # "we are recording this call" / "I am recording this conversation"
    rf"|\b(?:am|are|is|will\s+be)\s+recording\s+{_SUBJECT}\b"
    # "recorded for quality and training purposes"
    r"|\brecorded\s+for\s+(?:quality|training|compliance|verification|monitoring)\b"
    # "calls are recorded" (generic standing disclosure)
    rf"|\b(?:calls|conversations|chats)\s+{_MODAL}(?:\s+being)?\s+recorded\b"
    r")",
    re.IGNORECASE,
)


_NEGATION_RE = re.compile(
    r"\b(never|no|not|n't|dont|avoid|refuse|refuses|refusing|must\s+not|cannot|"
    r"can\s?not|without|instead\s+of|rather\s+than)\b",
    re.IGNORECASE,
)

_CLAUSE_BREAKS = (".", "\n", ";")


def _is_negated(text: str, start: int) -> bool:
    """True when the phrase at ``start`` sits in a clause that forbids it.

    Scoped to the clause, not the whole prompt: in "Never threaten legal
    action. Offer Promise-to-Pay options." the negation must not reach past
    the full stop, or one early "never" would excuse every later violation.
    """
    boundary = max(text.rfind(brk, 0, start) for brk in _CLAUSE_BREAKS)
    return _NEGATION_RE.search(text[boundary + 1 : start]) is not None


def lint_prompt(
    prompt: str,
    guardrails: dict[str, Any],
    *,
    include_llm: bool = False,
    role: str = "system",
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text = prompt or ""

    # System-role prompts go through render_system_prompt, which only
    # substitutes SYSTEM_SAFE_VARIABLES. Linting them against the full
    # KNOWN_VARIABLES set told authors that e.g. {overdue_amount} was fine when
    # it silently renders as a literal brace token in the live system prompt.
    allowed = SYSTEM_SAFE_VARIABLES if role == "system" else KNOWN_VARIABLES
    for match in TOKEN_RE.finditer(text):
        name = match.group(1)
        if name in allowed:
            continue
        if role == "system" and name in KNOWN_VARIABLES:
            findings.append(
                {
                    "severity": "warn",
                    "code": "crm_variable_in_system_prompt",
                    "message": (
                        f"{{{name}}} is a CRM field, which a system prompt never "
                        "substitutes — the runtime drops the whole line it sits "
                        "on. The value already reaches the model on the untrusted "
                        "CRM context card; refer to it in words here."
                    ),
                    "span": {"start": match.start(), "end": match.end()},
                }
            )
            continue
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
        for word in prohibited:
            w = str(word or "").strip()
            if not w:
                continue
            # Whole-word match. Raw substring search flagged "rate" inside
            # "accurate" / "corporate", so an author could not use ordinary
            # English once a short word was on the prohibited list.
            pattern = re.escape(w)
            if w[:1].isalnum() or w[:1] == "_":
                pattern = r"\b" + pattern
            if w[-1:].isalnum() or w[-1:] == "_":
                pattern = pattern + r"\b"
            # A clause that forbids the phrase is not a use of it. The
            # first-party collections prompt says "Never threaten legal
            # action", so the rule reported an error on the prompt the product
            # ships — and on every card cloned from it. Report the first
            # match that is not governed by a negation; if every mention is
            # negated, the author is writing a guardrail, not breaking one.
            found = next(
                (
                    m
                    for m in re.finditer(pattern, text, re.IGNORECASE)
                    if not _is_negated(text, m.start())
                ),
                None,
            )
            if found is not None:
                idx = found.start()
                findings.append(
                    {
                        "severity": "error",
                        "code": "prohibited_word_in_prompt",
                        "message": f'Prohibited phrase "{w}" appears in the system prompt.',
                        "span": {"start": idx, "end": found.end()},
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
        # Static message: this reaches the Prompt Studio UI, and an Azure
        # OpenAI exception string carries the endpoint, deployment name and
        # request id. Diagnostics stay in the log above.
        return [
            {
                "severity": "info",
                "code": "llm_lint_failed",
                "message": "LLM lint failed — see server logs.",
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
