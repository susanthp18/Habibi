"""Phrasing for an approved offer.

The talk track is generated here, deterministically, and not by the model. The
model's job is to deliver a sentence naturally; deciding *what claim to make
about a financial product* is not a job to hand to a text generator that has no
access to the sanction letter.

That said, this is a suggestion, not a script. The tool payload carries it as
``talkTrack`` and the node instruction tells the model it may rephrase for flow
— what it may not do is change the product, the amount, or add a promise.

Channel matters more than it looks. Voice TTS reads "150000" as "one hundred
fifty thousand" at best and digit-by-digit at worst, so the spoken form is
"one point five lakh rupees". Chat is read, not heard, and there "₹1,50,000" is
clearer and looks like a real quote. Same number, two renderings, one place
that knows the difference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agent_core.reco.scoring import ScoredOffer

VOICE_CHANNELS = frozenset({"voice", "voice_mesh", "phone"})


def speakable_amount(amount: float | None) -> str:
    """Indian-format an amount the way a person says it out loud."""
    if not amount or amount <= 0:
        return ""
    if amount >= 10_000_000:
        return f"{amount / 10_000_000:.2f}".rstrip("0").rstrip(".") + " crore rupees"
    if amount >= 100_000:
        return f"{amount / 100_000:.2f}".rstrip("0").rstrip(".") + " lakh rupees"
    if amount >= 1_000:
        return f"{int(round(amount / 1_000))} thousand rupees"
    return f"{int(round(amount))} rupees"


def written_amount(amount: float | None) -> str:
    """Indian digit grouping (1,50,000) for channels that are read."""
    if not amount or amount <= 0:
        return ""
    whole = int(round(amount))
    s = str(whole)
    if len(s) <= 3:
        return f"₹{s}"
    head, tail = s[:-3], s[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return "₹" + ",".join(groups + [tail])


def format_amount(amount: float | None, channel: str) -> str:
    if (channel or "").strip().lower() in VOICE_CHANNELS:
        return speakable_amount(amount)
    return written_amount(amount)


# Reason codes the scorer emits, mapped to a clause a human would actually say.
# Only the ones that are safe to voice appear here: "tight_headroom" and
# "recently_contacted" are real inputs to the rank and are nobody's business
# but ours — telling a customer we ranked them down is not transparency, it is
# an argument.
_REASON_CLAUSES: dict[str, str] = {
    "customer_asked_for_it": "since you asked about it",
    "complements_existing_product": "which works alongside what you already hold",
    "comfortable_headroom": "which fits comfortably within your existing limit",
    "clean_repayment_record": "given your repayment record",
    "product_interest_in_call": "based on what we discussed",
    "positive_sentiment": "",
    "campaign_priority": "",
}


def _lead_clause(reason_codes: tuple[str, ...] | list[str]) -> str:
    """First safe-to-say reason, or nothing. Never more than one — stacking
    justifications reads as a pitch, and a pitch is what gets complained about.
    """
    for code in reason_codes:
        clause = _REASON_CLAUSES.get(code)
        if clause:
            return clause
    return ""


def talk_track(
    offer: "ScoredOffer",
    *,
    channel: str = "voice",
    preferred_window: str | None = None,
) -> str:
    """One sentence the agent can say, plus the callback ask.

    Deliberately does not quote the ROI. An interest rate spoken on a call is
    heard as a commitment, and the rate that eventually applies depends on
    underwriting this engine has not done. ``roi`` stays in the payload for the
    rep and the UI, where it is displayed next to the terms.
    """
    amount = format_amount(offer.suggested_amount, channel)
    clause = _lead_clause(offer.reason_codes)

    subject = f"{_article(offer.name)} {offer.name}"
    if amount:
        subject += f" of about {amount}"
    if clause:
        # Comma before the clause: "a top-up of about 3.2 lakh rupees which
        # works alongside…" runs on when spoken, and TTS needs the pause.
        subject += f", {clause}"

    ask = "Would you like a specialist to call you"
    window = (preferred_window or "").strip()
    if window:
        # Reading their own stated window back is the difference between a
        # callback that happens and one that goes to voicemail twice.
        ask += (
            f" between {window}"
            if _looks_like_a_range(window)
            else f" during your usual {window}"
        )
    return f"You may be eligible for {subject}. {ask}?"


def _article(name: str) -> str:
    """"a" / "an". A crude vowel test, because the alternative is a
    pronunciation dictionary for a two-letter word."""
    first = (name or "").strip()[:1].lower()
    return "an" if first in "aeiou" else "a"


def _looks_like_a_range(window: str) -> bool:
    return any(sep in window for sep in ("-", "–", "to "))
