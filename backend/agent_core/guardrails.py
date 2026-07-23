"""Guardrail evaluation — shared across sandbox, WhatsApp, and voice."""

from __future__ import annotations

import os
import re
from typing import Any

# Default ceiling when channel does not pass hard_max_turns (sandbox overrides via env).
_DEFAULT_HARD_MAX_TURNS = max(1, int(os.getenv("SANDBOX_HARD_MAX_TURNS", "3")))


def evaluate_guardrails(
    *,
    customer_text: str,
    bot_text: str,
    intent: str,
    guardrails: dict[str, Any],
    turn_index: int,
    elapsed_seconds: float,
    customer_bot_exchanges: int,
    hard_max_turns: int | None = None,
) -> list[str]:
    flags: list[str] = []
    prohibited = [str(p).lower() for p in (guardrails.get("prohibited") or []) if str(p).strip()]
    bot_l = (bot_text or "").lower()
    cust_l = (customer_text or "").lower()

    for p in prohibited:
        if p and p in bot_l:
            flags.append(f"prohibited:{p}")

    if guardrails.get("neverPromiseWaiver") and intent == "waiver_request":
        if re.search(r"\b(waive|waiver|waived)\b", bot_l) and "goodwill" not in bot_l:
            flags.append("waiver-blocked")

    # Hard enforce: never quote rates / APR (not prompt-only).
    if guardrails.get("neverQuoteRate"):
        if re.search(
            r"\b(\d{1,2}(\.\d+)?\s*%|apr|interest\s+rate|roi\b|per\s+annum|p\.a\.)\b",
            bot_l,
        ):
            flags.append("rate-quoted")

    # Hard enforce: refuse politics / religion (customer trigger or bot engagement).
    if guardrails.get("refusePoliticsReligion"):
        politics_re = re.compile(
            r"\b(politic|election|minister|bjp|congress|party|religion|hindu|muslim|"
            r"christian|temple|mosque|church|god\b|allah|bible|quran)\b",
            re.I,
        )
        if politics_re.search(cust_l):
            flags.append("politics-religion")
        elif politics_re.search(bot_l) and not re.search(
            r"\b(cannot|can't|won't|refuse|not discuss|avoid|redirect)\b", bot_l
        ):
            flags.append("politics-religion-engaged")

    if guardrails.get("escalateLegal") and intent == "escalation":
        flags.append("auto-escalate")
    # Also trip on explicit legal language in the customer's words (not intent-only).
    if guardrails.get("escalateLegal") and re.search(
        r"\b(lawyer|advocate|attorney|court|lawsuit|sue\b|legal\s+action|"
        r"consumer\s+forum|ombudsman|police\s+complaint)\b",
        cust_l,
    ):
        flags.append("auto-escalate")
    if guardrails.get("escalateAbuse") and any(
        w in cust_l
        for w in (
            "idiot",
            "stupid",
            "shut up",
            "stfu",
            "harass",
            "kill",
            "fuck",
            "asshole",
            "bastard",
        )
    ):
        flags.append("auto-escalate")

    ceiling = hard_max_turns if hard_max_turns is not None else _DEFAULT_HARD_MAX_TURNS
    max_turns = int(guardrails.get("maxTurns") or 0)
    effective_max = min(ceiling, max_turns) if max_turns else ceiling
    if customer_bot_exchanges >= effective_max:
        flags.append("max-turns")

    max_seconds = int(guardrails.get("maxSeconds") or 0)
    if max_seconds and elapsed_seconds >= max_seconds:
        flags.append("max-seconds")

    if guardrails.get("alwaysDiscloseRecording") and turn_index <= 1:
        if "record" not in bot_l:
            flags.append("missing-recording-disclosure")

    return flags


def should_halt(flags: list[str]) -> bool:
    return any(
        f.startswith("prohibited:")
        or f
        in (
            "max-turns",
            "max-seconds",
            "waiver-blocked",
            "rate-quoted",
            "politics-religion-engaged",
        )
        for f in flags
    )
