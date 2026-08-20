"""Guardrail evaluation — shared across sandbox, WhatsApp, and voice."""

from __future__ import annotations

import os
import re
from typing import Any

from agent_core import lexicon

# Default ceiling when channel does not pass hard_max_turns (sandbox overrides via env).
# A malformed value must not make agent_core unimportable at process start.
try:
    _DEFAULT_HARD_MAX_TURNS = max(1, int(os.getenv("SANDBOX_HARD_MAX_TURNS", "3")))
except ValueError:
    _DEFAULT_HARD_MAX_TURNS = 3

#: The turn by which the recording disclosure must have happened. Turn 0 is the
#: greeting, so a bot that has said nothing about recording by the time it takes
#: its second turn is late. Kept as a name because the number is a compliance
#: decision, not an implementation detail.
_DISCLOSURE_DEADLINE_TURN = 1


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
    max_waiver_inr: float | None = None,
    recording_disclosed: bool = False,
) -> list[str]:
    flags: list[str] = []
    prohibited = [str(p).lower() for p in (guardrails.get("prohibited") or []) if str(p).strip()]
    bot_l = (bot_text or "").lower()
    cust_l = (customer_text or "").lower()

    # Whole-word match, consistent with the regex guardrails below: a substring
    # test flags "guarantee" inside "guaranteed-issue" and, worse, fires on
    # innocuous words that merely contain a banned term.
    for p in prohibited:
        if p and re.search(rf"\b{re.escape(p)}\b", bot_l):
            flags.append(f"prohibited:{p}")

    if guardrails.get("neverPromiseWaiver") and intent == "waiver_request":
        if re.search(r"\b(waive|waiver|waived)\b", bot_l) and "goodwill" not in bot_l:
            flags.append("waiver-blocked")

    if max_waiver_inr is not None and intent in {"waiver_request", "dispute"}:
        for match in re.finditer(r"₹\s*([\d,]+(?:\.\d+)?)|(\d[\d,]{2,})\s*(?:rupees|rs\.?)\b", bot_l):
            raw = (match.group(1) or match.group(2) or "").replace(",", "")
            try:
                quoted = float(raw)
            except ValueError:
                continue
            if quoted > float(max_waiver_inr) + 0.009:
                flags.append("authority-cap-exceeded")
                break

    # Hard enforce: never quote rates / APR (not prompt-only).
    if guardrails.get("neverQuoteRate"):
        if re.search(
            r"(?:\b\d{1,2}(?:\.\d+)?\s*%|\bapr\b|\binterest\s+rate\b|\broi\b|"
            r"\bper\s+annum\b|\bp\.a\.)",
            bot_l,
        ):
            flags.append("rate-quoted")

    # Hard enforce: refuse politics / religion (customer trigger or bot engagement).
    # Avoid bare tokens like "party" / "congress" / "god" that collide with
    # insurance ("third party") and everyday speech.
    if guardrails.get("refusePoliticsReligion"):
        politics_re = re.compile(
            r"(?:"
            r"\b(politics?|political|election|elections|minister|bjp|"
            r"indian\s+national\s+congress|lok\s+sabha|vidhan\s+sabha|"
            r"religion|religious|hinduism|islam|muslim|christianity|christian|"
            r"temple|mosque|church|allah|bible|quran)\b|"
            r"\b(vote\s+for|political\s+party)\b"
            r")",
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
    # The pattern lives in agent_core.lexicon: the copy that used to sit here had
    # a bare `sue\b` and no `fir` handling at all, so it disagreed with the voice
    # channel about what counts as a legal threat — on the escalation path.
    if guardrails.get("escalateLegal") and lexicon.is_legal_threat(cust_l):
        flags.append("auto-escalate")
    # Word-boundary match so partial hits ("kill" in "skill") don't escalate,
    # with a trailing \w* so suffixed forms ("harassment", "fucked") still do.
    if guardrails.get("escalateAbuse") and lexicon.is_abusive(cust_l):
        flags.append("auto-escalate")

    ceiling = hard_max_turns if hard_max_turns is not None else _DEFAULT_HARD_MAX_TURNS
    max_turns = int(guardrails.get("maxTurns") or 0)
    effective_max = min(ceiling, max_turns) if max_turns else ceiling
    if customer_bot_exchanges >= effective_max:
        flags.append("max-turns")

    max_seconds = int(guardrails.get("maxSeconds") or 0)
    if max_seconds and elapsed_seconds >= max_seconds:
        flags.append("max-seconds")

    # Whether the disclosure has been made is a fact about the CALL, not about
    # one turn. This used to read `turn_index <= 1 and "record" not in bot_l`,
    # which asks every one of the first two turns to contain the disclosure
    # independently. A call that opened with "...this call is recorded for
    # quality and compliance" was therefore flagged on turn 1 for not saying it
    # a second time (VS-92CDE3F088). The flag reached the turn critic, which
    # injected "you have not yet satisfied a required disclosure — say it once,
    # early in your next reply", and the caller then heard the disclosure twice
    # more. Read the history instead: satisfied once is satisfied for the call.
    if guardrails.get("alwaysDiscloseRecording"):
        disclosed = bool(recording_disclosed) or "record" in bot_l
        if not disclosed and turn_index >= _DISCLOSURE_DEADLINE_TURN:
            flags.append("missing-recording-disclosure")

    # De-dup while preserving first-seen order: "auto-escalate" can be raised by
    # intent, legal wording and abuse detection in the same turn, and callers
    # count flags.
    return list(dict.fromkeys(flags))


def should_halt(flags: list[str]) -> bool:
    return any(
        f.startswith("prohibited:")
        or f
        in (
            "max-turns",
            "max-seconds",
            "waiver-blocked",
            "authority-cap-exceeded",
            "rate-quoted",
            "politics-religion-engaged",
        )
        for f in flags
    )
