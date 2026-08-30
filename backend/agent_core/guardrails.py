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

#: What counts as *disclosing the recording to the customer*. Deliberately
#: narrow: this backs a compliance gate, so a bare "record" substring is not
#: enough — "let me record your promise to pay" and "I'll record that in the
#: CRM" are not disclosures, and accepting them would let an undisclosed call
#: look compliant. Canonical home for the pattern; ``prompt_lint`` lints prompt
#: TEXT with the same rule so the authoring gate and the runtime detector
#: cannot drift apart.
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


def mentions_recording_disclosure(text: str) -> bool:
    """True when ``text`` states the recording disclosure to the customer.

    Channels use this to answer "has the disclosure been made on this CALL?"
    from their own history (the greeting counts) before asking
    :func:`evaluate_guardrails` to judge one turn.
    """

    return bool(_DISCLOSURE_RE.search(text or ""))

#: A *commitment* to waive, in the agent's own voice. This backs a halting
#: guardrail, so the distinction between promising a waiver and merely saying
#: the word matters: the detector used to be ``\b(waive|waiver|waived)\b``,
#: which flagged the correct refusal "late fee waivers can't be approved on
#: this chat without a supervisor review, but I can log your request for
#: escalation" exactly as hard as "sure, I'll waive it" (SBX-E8A282E083). The
#: run halted on a compliant answer and the caller was left mid-flow with no
#: resolution path. The "goodwill" escape hatch that predates this expressed
#: the same intent too narrowly -- it rescued one phrasing of a refusal and no
#: other, so it is kept but is no longer what does the work.
_WAIVE_VERB = r"waiv(?:e|ed|ing)"

#: Auxiliaries / adverbs that may sit between "I"/"we" and the verb without
#: changing the fact that the agent is the one doing the waiving. Negating
#: words ("cannot", "unable") are deliberately absent, so "I cannot waive"
#: cannot match this pattern even before the refusal check runs.
_AGENT_FILLER = (
    r"(?:'ll|'ve|'m|'re|'d|\s+(?:will|shall|can|could|would|may|am|are|have|has|had|"
    r"be|been|going|to|just|now|already|hereby|happy|glad|pleased|like|gladly|"
    r"certainly|definitely|surely|absolutely|personally|go|ahead|and|do|did))"
)

_WAIVER_COMMITMENT_RE = re.compile(
    r"(?:"
    # "I will waive" / "we'll waive" / "I can waive this" / "done, I've waived"
    rf"\b(?:i|we)\b{_AGENT_FILLER}*\s*\b{_WAIVE_VERB}\b"
    # "consider it waived" / "consider the late fee waived"
    r"|\bconsider\s+(?:it|this|that|(?:the|your)\s+(?:\w+\s+){0,2}\w+)\s+waived\b"
    # "let me waive" / "let's waive that for you"
    rf"|\blet(?:'s|\s+me|\s+us)\b[^.!?]{{0,40}}?\b{_WAIVE_VERB}\b"
    # "the late fee is waived" / "has been waived" / "will be waived"
    r"|\b(?:is|are|was|were|being|has\s+been|have\s+been|will\s+be)\s+waived\b"
    # "your waiver is approved" / "I've approved the waiver"
    r"|\bwaiver\s+(?:is|has\s+been|will\s+be)\s+(?:approved|granted|applied|processed|done)\b"
    r"|\b(?:approved|granted|applied|processed)\s+(?:the|your|this)\s+waiver\b"
    r")",
    re.IGNORECASE,
)

#: Refusal / deferral cues. Alongside a waive-term these mean the bot is
#: declining or routing the request, not granting it.
_WAIVER_REFUSAL_RE = re.compile(
    r"(?:"
    r"\b(?:can(?:'|\u2019)?t|cannot|can\s+not|couldn(?:'|\u2019)?t|could\s+not|"
    r"won(?:'|\u2019)?t|will\s+not|wouldn(?:'|\u2019)?t|would\s+not|"
    r"unable|isn(?:'|\u2019)?t|aren(?:'|\u2019)?t|doesn(?:'|\u2019)?t|"
    r"don(?:'|\u2019)?t|do\s+not|never|no\s+authority|not\s+authori[sz]ed|"
    r"not\s+able|not\s+permitted|not\s+allowed|not\s+in\s+a\s+position)\b"
    r"|\bescalat\w*"
    r"|\b(?:supervisor|manager|senior|specialist|team)\s+(?:review|approval|sign-?off)\b"
    r"|\b(?:require|requires|required|need|needs|needed|subject)\s+"
    r"(?:to\s+be\s+|a\s+|an\s+)?(?:supervisor|manager|senior|prior|further|"
    r"additional|internal|separate)?\s*"
    r"(?:approval|approved|review|reviewed|authorisation|authorization)\b"
    r"|\bwithout\s+(?:\w+\s+){0,3}(?:approval|review|authorisation|authorization)\b"
    r")",
    re.IGNORECASE,
)

_WAIVER_SENTENCE_SPLIT_RE = re.compile(r"[.!?\n]+")


def promises_waiver(text: str) -> bool:
    """True when ``text`` commits, in the agent's voice, to granting a waiver.

    Scoped per sentence: a refusal *near* the waive-term suppresses it, but a
    refusal elsewhere in the reply does not excuse a promise ("I'll waive the
    fee. I can't help with the interest." still counts). Kept pure and next to
    :func:`evaluate_guardrails` so the phrasing cases stay directly testable.
    """

    for sentence in _WAIVER_SENTENCE_SPLIT_RE.split(text or ""):
        if not _WAIVER_COMMITMENT_RE.search(sentence):
            continue
        if _WAIVER_REFUSAL_RE.search(sentence):
            continue
        return True
    return False


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
        if promises_waiver(bot_l) and "goodwill" not in bot_l:
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
        disclosed = bool(recording_disclosed) or mentions_recording_disclosure(bot_text)
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
