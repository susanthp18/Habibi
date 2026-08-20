"""Every detector in the catalog, proved against a positive and a negative case.

This file exists because of a specific failure mode. ``detector_coverage``
reports a rule as ``clean`` when a detector ran and found nothing — but a regex
that can never match anything also reports ``clean``, forever, on every call.
A compliance screen that cannot tell those apart is worse than one with no
rules at all, because it reads as assurance.

So each rule gets two tests: one input that must fire it, one that must not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_core.compliance.context import ScanContext, Turn
from agent_core.compliance.detectors import DETECTORS

IST = timezone(timedelta(hours=5, minutes=30))


def ctx(
    *turns: tuple[str, str],
    channel: str = "voice",
    direction: str = "outbound",
    handler_kind: str = "bot",
    disposition: str | None = "answered",
    started_at: datetime | None = None,
    disclosures: frozenset[str] = frozenset(),
    on_dnd: bool = False,
    at_sec: list[int] | None = None,
) -> ScanContext:
    """Build a context from ``(speaker, text)`` pairs."""
    built = tuple(
        Turn(
            index=i,
            speaker=speaker,
            at_sec=(at_sec[i] if at_sec and i < len(at_sec) else i * 10),
            text=text,
            sentiment_delta=None,
            intent=None,
        )
        for i, (speaker, text) in enumerate(turns)
    )
    return ScanContext(
        interaction_id="IX-TEST",
        tenant_id="hdfc.retail",
        customer_id="CU-TEST",
        channel=channel,
        direction=direction,
        status="completed",
        disposition=disposition,
        handler_kind=handler_kind,
        handler_user_id="priya-nair" if handler_kind == "human" else None,
        handler_bot_id=None if handler_kind == "human" else "bot-kaia",
        started_at=started_at or datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc),  # 11:30 IST
        duration_sec=120,
        avg_sentiment=0.0,
        turns=built,
        disclosures_read=disclosures,
        timezone="Asia/Kolkata",
        on_dnd=on_dnd,
    )


def fires(rule_id: str, context: ScanContext) -> bool:
    found = DETECTORS[rule_id](context)
    return found is not None and found.rule_id == rule_id


# A compliant outbound collections call, used as the negative case for the
# disclosure family. Every mandatory element is present and in order.
CLEAN_CALL = (
    ("bot", "Hello, am I speaking with Mr Sharma? This call is recorded for quality and compliance."),
    ("customer", "Yes, speaking."),
    ("bot", "Thank you. This is a debt collection call from HDFC regarding your loan account."),
    ("customer", "Okay."),
    ("bot", "Your outstanding balance is 42,000 rupees. You may dispute this amount if you disagree."),
    ("customer", "I will pay next week."),
    ("bot", "Noted. You can opt-out of these calls at any time by replying STOP."),
)


def test_every_catalog_rule_has_a_detector():
    """The registry is the contract detector_coverage reports against."""
    assert len(DETECTORS) == 16


# ------------------------------------------------------------------ disclosure


def test_missing_recording_notice_fires():
    assert fires("r-rec", ctx(("bot", "Hello, this is HDFC about your loan."), ("customer", "Yes?")))


def test_recording_notice_given_late_still_fires():
    """The obligation is to disclose up front. A notice read at the end of the
    call is not a notice — the customer has already spoken unaware."""
    assert fires(
        "r-rec",
        ctx(
            ("bot", "Hello, this is HDFC about your loan."),
            ("customer", "Yes?"),
            ("bot", "By the way, this call is recorded."),
            at_sec=[0, 40, 95],
        ),
    )


def test_recording_notice_up_front_does_not_fire():
    assert not fires("r-rec", ctx(*CLEAN_CALL))


def test_a_voicemail_is_not_a_disclosure_breach():
    """Nobody was there to be disclosed to. Filing these would bury the real
    breaches under every unreachable number in the book."""
    assert not fires("r-rec", ctx(("bot", "Please call us back."), disposition="voicemail"))


def test_missing_mini_miranda_fires():
    assert fires("r-mm", ctx(("bot", "Hi, calling about your account."), ("customer", "Yes?")))


def test_mini_miranda_present_does_not_fire():
    assert not fires("r-mm", ctx(*CLEAN_CALL))


def test_inbound_calls_are_not_judged_for_mini_miranda():
    """A borrower who dialled us already knows who they called."""
    assert not fires(
        "r-mm",
        ctx(("agent", "Hi, how can I help?"), ("customer", "About my loan"), direction="inbound"),
    )


def test_missing_opt_out_reminder_fires():
    assert fires("r-dnd-disc", ctx(("bot", "Please pay soon."), ("customer", "Okay")))


def test_opt_out_reminder_present_does_not_fire():
    assert not fires("r-dnd-disc", ctx(*CLEAN_CALL))


def test_dispute_notice_only_required_once_an_amount_is_named():
    """A courtesy call that never named a balance has nothing to dispute."""
    assert not fires("r-disp", ctx(("bot", "Just checking in on you."), ("customer", "Fine")))
    assert fires(
        "r-disp",
        ctx(("bot", "Your outstanding balance is 42,000 rupees."), ("customer", "Okay")),
    )


def test_dispute_notice_present_does_not_fire():
    assert not fires("r-disp", ctx(*CLEAN_CALL))


# ------------------------------------------------------------------- checklist


@pytest.mark.parametrize(
    "rule_id,spoken",
    [
        ("rule-recording", "this call is recorded for compliance"),
        ("rule-mini-miranda", "this is a debt collection call"),
        ("rule-payment", "we can set up a payment plan with a due date"),
        ("rule-identity", "can you confirm your date of birth"),
    ],
)
def test_checklist_rules_fire_when_neither_ticked_nor_spoken(rule_id: str, spoken: str):
    silent = ctx(("agent", "Right, so about the money."), ("customer", "Yes"), handler_kind="human")
    assert fires(rule_id, silent)

    said = ctx(("agent", spoken), ("customer", "Yes"), handler_kind="human")
    assert not fires(rule_id, said)

    ticked = ctx(
        ("agent", "Right, so about the money."),
        ("customer", "Yes"),
        handler_kind="human",
        disclosures=frozenset({rule_id}),
    )
    assert not fires(rule_id, ticked)


def test_checklist_rules_do_not_double_judge_a_bot_call():
    """A bot call is judged by the RBI-DISC-* family. Scoring it under both
    would file two violations for one missed disclosure."""
    silent = ctx(("bot", "About the money."), ("customer", "Yes"), handler_kind="bot")
    assert not fires("rule-recording", silent)


# ---------------------------------------------------------- prohibited language


def test_threatening_language_fires():
    assert fires(
        "r-threat",
        ctx(("agent", "We will take legal action and file a case against you."), ("customer", "Please no")),
    )


def test_abusive_language_fires():
    assert fires("r-abuse", ctx(("agent", "You are an idiot and a fraud."), ("customer", "Excuse me?")))


def test_the_borrowers_own_words_are_never_a_breach_by_us():
    """The single most important negative in this file. A borrower swearing at
    a collections agent is not the lender breaching conduct rules, and scanning
    both sides of the transcript would file one against them."""
    abusive_customer = ctx(
        ("bot", "This call is recorded. This is a debt collection call about your balance, which you may dispute. You can opt-out any time."),
        ("customer", "You people are bloody thieves and idiots, I will sue you and have you arrested."),
    )
    assert not fires("r-abuse", abusive_customer)
    assert not fires("r-threat", abusive_customer)
    assert not fires("r-false", abusive_customer)


def test_false_legal_claim_fires():
    assert fires(
        "r-false",
        ctx(("agent", "If you do not pay you will go to jail, this is a criminal case."), ("customer", "What?")),
    )


def test_lawful_legal_notice_is_not_a_false_claim():
    """Stating a real, available civil remedy is allowed. Only the criminal
    threat is the breach — otherwise the rule would suppress lawful notice."""
    assert not fires(
        "r-false",
        ctx(("agent", "We may issue a demand notice under the loan agreement."), ("customer", "I see")),
    )


def test_guarantee_of_outcome_fires():
    assert fires(
        "r-guarantee",
        ctx(("agent", "Pay today and I guarantee your CIBIL score will improve."), ("customer", "Really?")),
    )


def test_third_party_leverage_fires():
    """One of the eight practices RBI banned outright on 6 August 2026."""
    assert fires(
        "r-third",
        ctx(("agent", "If you don't pay we will call your employer and inform your family."), ("customer", "Please don't")),
    )


def test_mentioning_a_co_borrower_is_not_third_party_leverage():
    assert not fires(
        "r-third",
        ctx(("agent", "Your co-applicant is also listed on this loan account."), ("customer", "Yes")),
    )


# ------------------------------------------------------- consent / verify / tone


def test_contact_outside_calling_hours_fires_in_the_customers_timezone():
    """20:30 IST. The server may be anywhere; the borrower's clock is the one
    RBI's 08:00-19:00 restriction is written against."""
    late = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)  # 20:30 IST
    assert fires("r-dnd-win", ctx(("bot", "Hello"), ("customer", "Yes"), started_at=late))


def test_contact_inside_calling_hours_does_not_fire():
    fine = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)  # 11:30 IST
    assert not fires("r-dnd-win", ctx(("bot", "Hello"), ("customer", "Yes"), started_at=fine))


def test_contacting_a_dnd_customer_fires_whatever_the_hour():
    fine = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)
    assert fires("r-dnd-win", ctx(("bot", "Hello"), ("customer", "Yes"), started_at=fine, on_dnd=True))


def test_inbound_contact_is_never_a_window_breach():
    """The borrower chose the hour. Penalising us for answering is wrong."""
    late = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)
    assert not fires(
        "r-dnd-win",
        ctx(("agent", "Hello"), ("customer", "Hi"), started_at=late, direction="inbound"),
    )


def test_account_detail_before_verification_fires():
    assert fires(
        "r-verify",
        ctx(("bot", "Your outstanding balance is 42,000 rupees."), ("customer", "Who is this?")),
    )


def test_verification_after_disclosure_is_still_a_breach():
    """Ordering is the whole rule — verifying afterwards does not un-disclose."""
    assert fires(
        "r-verify",
        ctx(
            ("bot", "Your outstanding balance is 42,000 rupees."),
            ("customer", "Sorry, who?"),
            ("bot", "Can you confirm your date of birth?"),
        ),
    )


def test_verification_before_disclosure_does_not_fire():
    assert not fires("r-verify", ctx(*CLEAN_CALL))


def test_unaddressed_distress_fires():
    assert fires(
        "r-distress",
        ctx(
            ("bot", "Your payment is overdue."),
            ("customer", "My father passed away last week, I have no money."),
            ("bot", "So when can you make the payment?"),
        ),
    )


def test_acknowledged_distress_does_not_fire():
    assert not fires(
        "r-distress",
        ctx(
            ("bot", "Your payment is overdue."),
            ("customer", "My father passed away last week, I have no money."),
            ("bot", "I am so sorry to hear that. We can look at pausing this for now."),
        ),
    )


def test_empathy_must_be_the_next_turn_not_an_afterthought():
    """Sympathy offered three turns after the payment push is not a response to
    what the borrower said — it is damage control."""
    assert fires(
        "r-distress",
        ctx(
            ("bot", "Your payment is overdue."),
            ("customer", "I lost my job and I have no money."),
            ("bot", "When can you pay?"),
            ("customer", "I don't know."),
            ("bot", "I understand, that must be hard."),
        ),
    )
