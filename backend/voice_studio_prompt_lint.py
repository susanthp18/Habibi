"""Lint a Voice Studio (engine) prompt as the engine will render it.

Voice Studio prompts use the engine's template syntax, ``{{initial_context.x}}``
with an optional ``| fallback:y``. An unresolved variable renders as nothing, so
a misspelt or unsupplied key silently drops words from what the agent says.
The older Prompt Studio lint (prompt_lint.py) checks the other runtime's
single-brace syntax and would flag valid engine prompts, so it is not reused
here; its negation-aware prohibited-phrase rule is.

Findings: {severity: error|warn|info, code, message, span|None}.
"""

from __future__ import annotations

import re
from typing import Any

from agent_core.guardrails import mentions_recording_disclosure
from prompt_lint import _is_negated

# Mirrors the engine's TEMPLATE_VAR_PATTERN (utils/template_renderer.py).
_TEMPLATE = re.compile(r"\{\{\s*([^|\s}]+)(?:\s*\|\s*([^:}]+)(?::([^}]+))?)?\s*\}\}")
# The retired runtime's single-brace token, which the engine prints literally.
_SINGLE_BRACE = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})")

#: initial_context keys PayInt or the engine supply. Sources: voice_studio.CONTEXT_KEYS,
#: voice_studio.outbound_context / _position_context / precall,
#: whatsapp_studio._initial_context, and the engine's telephony (caller/called
#: numbers). A key outside this set renders empty unless something else sets it.
PROVIDED_CONTEXT = frozenset({
    # every run
    "workflow_run_id", "workflow_id", "agent_id", "direction", "channel", "demo", "rehearsal",
    "interaction_id", "conversation_id", "language", "timezone",
    # the customer and account
    "customer_id", "customer_name", "first_name", "caller_known", "account_id", "account_tail",
    "days_past_due", "outstanding_amount", "minimum_due", "minimum_due_value", "product_name",
    "account_status",
    # outbound missions
    "attempt_id", "campaign_run_id", "decision_id", "objective", "mission_brief",
    # engine telephony
    "phone_number", "caller_number", "called_number", "from_number", "to_number", "provider",
})
_BUILTINS = ("current_time", "current_weekday")

#: Tokens per English word, used only when the tokenizer is unavailable.
_TOKENS_PER_WORD_FALLBACK = 1.35


def _count_tokens(text: str) -> int:
    try:
        from kb_chunking import count_tokens

        return count_tokens(text)
    except Exception:  # tokenizer unavailable: a word-based estimate is honest enough
        return round(len(text.split()) * _TOKENS_PER_WORD_FALLBACK)


def lint(prompt: str, guardrails: dict[str, Any], *, is_opening: bool = False,
         spoken_first: str = "") -> list[dict[str, Any]]:
    """``spoken_first``: the opening's greeting text, said before the prompt takes over."""
    text = prompt or ""
    findings: list[dict[str, Any]] = []

    for m in _TEMPLATE.finditer(text):
        path, has_filter = m.group(1), m.group(2) is not None
        if path.startswith(_BUILTINS):
            continue
        if path.startswith("initial_context."):
            key = path.split(".", 2)[1]
            if key not in PROVIDED_CONTEXT and not has_filter:
                findings.append({
                    "severity": "warn",
                    "code": "unsupplied_context",
                    "message": (f"initial_context.{key} is not supplied by PayInt or the engine, so it "
                                f"renders as nothing. Check the spelling, or add a fallback: "
                                f"{{{{initial_context.{key} | fallback:...}}}}."),
                    "span": {"start": m.start(), "end": m.end()},
                })

    for m in _SINGLE_BRACE.finditer(text):
        findings.append({
            "severity": "error",
            "code": "single_brace_variable",
            "message": (f"{{{m.group(1)}}} is the old Prompt Studio syntax and is spoken literally here. "
                        f"Use {{{{initial_context.{m.group(1)}}}}}."),
            "span": {"start": m.start(), "end": m.end()},
        })

    prohibited = guardrails.get("prohibited") or []
    for word in prohibited if isinstance(prohibited, list) else []:
        w = str(word or "").strip()
        if not w:
            continue
        pattern = re.escape(w)
        if w[:1].isalnum():
            pattern = r"\b" + pattern
        if w[-1:].isalnum():
            pattern += r"\b"
        found = next((m for m in re.finditer(pattern, text, re.IGNORECASE)
                      if not _is_negated(text, m.start())), None)
        if found:
            findings.append({
                "severity": "error",
                "code": "prohibited_phrase",
                "message": f'"{w}" is a prohibited phrase for this agent; saying it raises a compliance flag.',
                "span": {"start": found.start(), "end": found.end()},
            })

    # Voice Studio checks disclosure on calls (voice_studio.flag_turns) but does
    # not add it: the greeting or the opening prompt has to say it.
    if (is_opening and guardrails.get("alwaysDiscloseRecording")
            and not mentions_recording_disclosure(spoken_first + "\n" + text)):
        findings.append({
            "severity": "warn",
            "code": "recording_disclosure_missing",
            "message": ("This agent's guardrails require a recording disclosure on calls, and neither the "
                        "greeting nor this opening prompt mentions recording. Calls that never disclose it "
                        "are flagged."),
            "span": None,
        })
    return findings


def lint_with_estimate(prompt: str, guardrails: dict[str, Any], *, is_opening: bool = False,
                       spoken_first: str = "") -> dict[str, Any]:
    from usage_meter import chat_input_usd_per_1m

    tokens = _count_tokens(prompt or "")
    return {
        "findings": lint(prompt, guardrails, is_opening=is_opening, spoken_first=spoken_first),
        "tokens": tokens,
        # Input cost of this prompt on one model turn; it is resent every turn it is active.
        "usdPerTurn": round(tokens * chat_input_usd_per_1m() / 1_000_000, 6),
    }


if __name__ == "__main__":
    g = {"prohibited": ["legal action"], "alwaysDiscloseRecording": True}
    out = lint("Hi {{initial_context.first_nme}}, {customer_name}. We will take legal action. "
               "Never threaten legal action. {{initial_context.first_name}}", g, is_opening=True)
    codes = [f["code"] for f in out]
    assert codes.count("unsupplied_context") == 1, codes
    assert "single_brace_variable" in codes and "prohibited_phrase" in codes, codes
    assert "recording_disclosure_missing" in codes, codes
    assert lint("This call is recorded. Hello {{initial_context.x | fallback:there}}", g, is_opening=True) == []
    print("ok")
