"""One detector per rule in the catalog.

Each is a pure function ``(ScanContext) -> Finding | None``. Registration is by
**rule id**, and :data:`DETECTORS` is the single source of truth for which
rules this system can actually judge — see ``scan.detector_coverage``. Adding a
row to ``compliance_rules`` without adding a detector here makes the rule show
up as *unverified* on the screen rather than silently clean.

Two conventions hold throughout:

* **Only our words are judged.** Every language rule reads ``ctx.our_turns``.
  A borrower swearing at a collections agent is not a breach by the lender, and
  scanning both sides would file one against them.
* **Silence is not a breach.** Disclosure rules return None unless
  ``ctx.substantive`` — a ring-out or voicemail had nobody to disclose to, and
  filing those buries the real breaches under unreachable numbers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from agent_core import lexicon
from agent_core.compliance.context import ScanContext, Turn


@dataclass(frozen=True)
class Finding:
    rule_id: str
    description: str
    at_sec: int = 0


Detector = Callable[[ScanContext], "Finding | None"]

DETECTORS: dict[str, Detector] = {}


def detector(rule_id: str) -> Callable[[Detector], Detector]:
    def register(fn: Detector) -> Detector:
        DETECTORS[rule_id] = fn
        return fn

    return register


def _hit(ctx: ScanContext, pattern: re.Pattern[str]) -> Turn | None:
    for turn in ctx.our_turns:
        if pattern.search(turn.text):
            return turn
    return None


# ---------------------------------------------------------------------------
# Disclosure rules (RBI-DISC-01..04)
#
# Detected from what was said, not from a checklist somebody ticked. The
# checklist (interaction_disclosures) is honoured as positive evidence where it
# exists, because the handoff path writes it and a human agent reading the
# script aloud will not always phrase it the way the matcher expects.
# ---------------------------------------------------------------------------

RECORDING_RE = re.compile(
    r"\b(?:is|are|being|call is)\s+(?:be(?:ing)?\s+)?record(?:ed|ing)\b"
    r"|\brecorded for\b|\brecording this call\b|\bcall is recorded\b",
    re.I,
)
MINI_MIRANDA_RE = re.compile(
    r"\bcollect(?:ing|ion)?\s+a\s+debt\b|\bdebt\s+collect|\battempt\s+to\s+collect\b"
    r"|\brecovery\s+(?:call|agent|department)\b|\bcollections?\s+(?:call|team|department)\b",
    re.I,
)
OPT_OUT_RE = re.compile(
    r"\bopt[- ]?out\b|\bdo not (?:call|disturb)\b|\bDND\b"
    r"|\bstop (?:receiving|these) (?:calls|messages)\b"
    r"|\bunsubscribe\b|\bremove (?:you|your number) from\b",
    re.I,
)
DISPUTE_RE = re.compile(
    r"\bdispute\b|\bcontest\b|\bdisagree with (?:the|this) (?:amount|balance|charge)\b"
    r"|\braise a (?:complaint|grievance)\b|\bgrievance\b",
    re.I,
)

# The window inside which a recording notice still counts as "up front". RBI
# expects it before the substance of the call, not at the end of it.
RECORDING_DEADLINE_SEC = 30


@detector("r-rec")
def missed_recording_notice(ctx: ScanContext) -> Finding | None:
    """RBI-DISC-01. The notice must land, and must land early."""
    if not ctx.substantive or ctx.channel not in {"voice", "call"}:
        return None
    if "rule-recording" in ctx.disclosures_read:
        return None
    hit = _hit(ctx, RECORDING_RE)
    if hit is None:
        return Finding("r-rec", "No call-recording notice was given to the customer.")
    if hit.at_sec > RECORDING_DEADLINE_SEC:
        return Finding(
            "r-rec",
            f"Recording notice was given {hit.at_sec}s in, after the "
            f"{RECORDING_DEADLINE_SEC}s deadline.",
            at_sec=hit.at_sec,
        )
    return None


@detector("r-mm")
def missed_mini_miranda(ctx: ScanContext) -> Finding | None:
    """RBI-DISC-02. Only outbound: the borrower who calls us already knows."""
    if not ctx.substantive or not ctx.is_outbound:
        return None
    if "rule-mini-miranda" in ctx.disclosures_read:
        return None
    if _hit(ctx, MINI_MIRANDA_RE) is not None:
        return None
    return Finding("r-mm", "The call was not identified as a debt-collection call.")


@detector("r-dnd-disc")
def missed_opt_out_reminder(ctx: ScanContext) -> Finding | None:
    """RBI-DISC-03."""
    if not ctx.substantive or not ctx.is_outbound:
        return None
    if _hit(ctx, OPT_OUT_RE) is not None:
        return None
    return Finding("r-dnd-disc", "No opt-out / DND channel was offered to the customer.")


AMOUNT_RE = re.compile(r"\b(?:balance|outstanding|overdue|amount|due|emi)\b", re.I)


@detector("r-disp")
def missed_dispute_notice(ctx: ScanContext) -> Finding | None:
    """RBI-DISC-04. Only where an amount was actually discussed — a courtesy
    call that never named a balance has nothing to dispute."""
    if not ctx.substantive or not ctx.is_outbound:
        return None
    if not any(AMOUNT_RE.search(t.text) for t in ctx.our_turns):
        return None
    if _hit(ctx, DISPUTE_RE) is not None:
        return None
    return Finding("r-disp", "An amount was discussed without stating the right to dispute it.")


# The four RULE_* ids are the handoff checklist's own view of the same
# obligations. They are scored off interaction_disclosures rather than the
# transcript, because that is the artefact the handoff screen writes and the
# one a supervisor signs.

IDENTITY_RE = re.compile(
    r"\bconfirm your\b|\bverify (?:your|the)\b|\bdate of birth\b|\blast four\b"
    r"|\blast 4\b|\bregistered (?:mobile|number)\b|\bam i speaking (?:with|to)\b",
    re.I,
)
PAYMENT_TERMS_RE = re.compile(
    r"\bpayment (?:plan|terms|link|options?)\b|\binstal?ment\b|\bpay by\b|\bdue date\b",
    re.I,
)

_CHECKLIST: dict[str, tuple[str, re.Pattern[str]]] = {
    "rule-recording": ("Recording disclosure", RECORDING_RE),
    "rule-mini-miranda": ("Collections disclosure", MINI_MIRANDA_RE),
    "rule-payment": ("Payment terms disclosure", PAYMENT_TERMS_RE),
    "rule-identity": ("Identity verification", IDENTITY_RE),
}


def _checklist_detector(rule_id: str) -> Detector:
    label, pattern = _CHECKLIST[rule_id]

    def check(ctx: ScanContext) -> Finding | None:
        # Only meaningful once a human is on the call: the checklist belongs to
        # the handoff workspace, and a pure-bot interaction is judged by the
        # RBI-DISC-* rules above rather than twice by both families.
        if not ctx.substantive or ctx.handler_kind != "human":
            return None
        if rule_id in ctx.disclosures_read:
            return None
        if pattern.search(" ".join(t.text for t in ctx.our_turns)):
            return None
        return Finding(rule_id, f"{label} was neither ticked nor spoken on a human-handled call.")

    check.__name__ = f"missing_{rule_id.replace('-', '_')}"
    check.__doc__ = f"{label} — checklist item unticked and not detectable in the transcript."
    return check


for _rid in _CHECKLIST:
    DETECTORS[_rid] = _checklist_detector(_rid)


# ---------------------------------------------------------------------------
# Prohibited language (PROH-LANG-01..05)
# ---------------------------------------------------------------------------


@detector("r-threat")
def threatening_language(ctx: ScanContext) -> Finding | None:
    """PROH-LANG-01. Reuses the same lexicon the live guardrail uses, so the
    after-the-fact scan and the real-time veto cannot drift apart."""
    for turn in ctx.our_turns:
        if lexicon.is_legal_threat(turn.text):
            return Finding(
                "r-threat", f"Threatening language: {turn.text[:180]}", at_sec=turn.at_sec
            )
    return None


@detector("r-abuse")
def abusive_tone(ctx: ScanContext) -> Finding | None:
    """PROH-LANG-02."""
    for turn in ctx.our_turns:
        if lexicon.is_abusive(turn.text):
            return Finding(
                "r-abuse",
                f"Abusive or disrespectful language: {turn.text[:180]}",
                at_sec=turn.at_sec,
            )
    return None


FALSE_LEGAL_RE = re.compile(
    r"\b(?:go to|going to|end up in|land in)\s+jail\b|\barrest(?:ed|ing)?\b"
    r"|\bcriminal (?:case|charges?|record)\b"
    r"|\bnon[- ]?bailable\b|\bpolice (?:case|complaint|will)\b|\bseize your\b|\bwarrant\b",
    re.I,
)


@detector("r-false")
def false_legal_claim(ctx: ScanContext) -> Finding | None:
    """PROH-LANG-03. Default on an unsecured retail debt is a civil matter;
    asserting arrest or a criminal case misstates the consequence, and RBI's
    August 2026 Directions name false statements of consequence explicitly."""
    hit = _hit(ctx, FALSE_LEGAL_RE)
    if hit is None:
        return None
    return Finding(
        "r-false", f"False legal consequence asserted: {hit.text[:180]}", at_sec=hit.at_sec
    )


GUARANTEE_RE = re.compile(
    r"\b(?:i|we)\s+(?:can\s+)?guarantee\b|\bguaranteed\b|\bdefinitely will\b"
    r"|\b100%\s+(?:sure|certain)\b"
    r"|\byour (?:cibil|credit)\s+score\s+will\s+(?:go up|improve|increase)\b"
    r"|\bpromise (?:you )?that your\b",
    re.I,
)


@detector("r-guarantee")
def guarantee_of_outcome(ctx: ScanContext) -> Finding | None:
    """PROH-LANG-04. Bureau score movement and waiver approval are not ours to
    promise, and a promise made on a recorded call is one we are held to."""
    hit = _hit(ctx, GUARANTEE_RE)
    if hit is None:
        return None
    return Finding(
        "r-guarantee", f"Outcome guaranteed to the customer: {hit.text[:180]}", at_sec=hit.at_sec
    )


THIRD_PARTY_RE = re.compile(
    r"\b(?:tell|inform|ask)\s+(?:your|his|her|their)\s+"
    r"(?:husband|wife|father|mother|son|daughter|brother|sister|family|employer|boss|manager|neighbou?r)\b"
    r"|\bwe(?:'ll| will)\s+(?:call|contact|speak to|inform)\s+your\s+"
    r"(?:employer|office|family|relatives?|neighbou?rs?|references?)\b"
    r"|\bat your (?:office|workplace)\b",
    re.I,
)


@detector("r-third")
def third_party_disclosure(ctx: ScanContext) -> Finding | None:
    """PROH-LANG-05. Using relatives, employers or neighbours as leverage is one
    of the eight practices RBI banned outright on 6 August 2026."""
    hit = _hit(ctx, THIRD_PARTY_RE)
    if hit is None:
        return None
    return Finding(
        "r-third",
        f"Third party invoked as recovery leverage: {hit.text[:180]}",
        at_sec=hit.at_sec,
    )


# ---------------------------------------------------------------------------
# Consent, verification, conduct
# ---------------------------------------------------------------------------

RBI_CALL_START_HOUR = 8
RBI_CALL_END_HOUR = 19


@detector("r-dnd-win")
def contact_outside_window(ctx: ScanContext) -> Finding | None:
    """CONSENT-01. Two separate breaches, one rule: contacting a customer who is
    on DND at all, and contacting anyone outside 08:00-19:00 local.

    Evaluated in the *customer's* timezone, not the server's — a call placed at
    20:30 IST is a breach no matter where the process happens to run.
    """
    if not ctx.is_outbound or ctx.started_at is None:
        return None
    if ctx.on_dnd:
        return Finding("r-dnd-win", "Outbound contact was made to a customer on the DND registry.")

    from contact_policy import _zone  # one definition of the timezone fallback

    local = ctx.started_at.astimezone(_zone(ctx.timezone))
    if RBI_CALL_START_HOUR <= local.hour < RBI_CALL_END_HOUR:
        return None
    return Finding(
        "r-dnd-win",
        f"Outbound contact at {local:%H:%M} local, outside the permitted "
        f"{RBI_CALL_START_HOUR:02d}:00-{RBI_CALL_END_HOUR:02d}:00 window.",
    )


ACCOUNT_DETAIL_RE = re.compile(
    r"\b(?:outstanding|balance|overdue|emi|due amount|loan account|principal)\b", re.I
)


@detector("r-verify")
def skipped_identity_verification(ctx: ScanContext) -> Finding | None:
    """VERIFY-01. Account detail must not precede establishing who is on the line.

    Ordering is the whole rule: verifying *after* disclosing the balance is the
    same breach as never verifying, so this compares turn positions rather than
    simply asking whether verification happened at all.
    """
    if not ctx.substantive:
        return None
    detail = next((t for t in ctx.our_turns if ACCOUNT_DETAIL_RE.search(t.text)), None)
    if detail is None:
        return None
    if "rule-identity" in ctx.disclosures_read:
        return None
    verified = next((t for t in ctx.our_turns if IDENTITY_RE.search(t.text)), None)
    if verified is not None and verified.index < detail.index:
        return None
    if verified is None:
        return Finding(
            "r-verify",
            "Account details were discussed without verifying the customer's identity.",
            at_sec=detail.at_sec,
        )
    return Finding(
        "r-verify",
        "Identity was verified only after account details had already been disclosed.",
        at_sec=detail.at_sec,
    )


DISTRESS_RE = re.compile(
    r"\bhospital\b|\bmedical\b|\bsurgery\b|\bpassed away\b|\bdeath\b|\bdied\b|\bfuneral\b"
    r"|\blost my job\b|\bunemploy|\blaid off\b|\bno money\b|\bcannot afford\b|\bcan.t afford\b"
    r"|\bsuicid|\bend my life\b|\bdepress",
    re.I,
)
EMPATHY_RE = re.compile(
    r"\bsorry to hear\b|\bunderstand\b|\bappreciate\b|\bmust be (?:hard|difficult)\b"
    r"|\btake your time\b|\bhardship\b|\bwe can (?:help|look at|pause|defer)\b|\bno rush\b",
    re.I,
)


@detector("r-distress")
def distress_not_addressed(ctx: ScanContext) -> Finding | None:
    """SENT-01. A borrower who discloses hardship, bereavement or medical trouble
    and gets a scripted push for payment is the complaint that reaches the
    regulator. The breach is not the distress — it is the next turn."""
    for turn in ctx.customer_turns:
        if not DISTRESS_RE.search(turn.text):
            continue
        after = [t for t in ctx.our_turns if t.index > turn.index]
        if not after:
            return Finding(
                "r-distress",
                f"Customer disclosed distress and the call ended without a response: {turn.text[:150]}",
                at_sec=turn.at_sec,
            )
        # Only the immediate reply counts. Empathy eight turns later, after the
        # payment push, is not a response to what they said.
        if EMPATHY_RE.search(after[0].text):
            return None
        return Finding(
            "r-distress",
            f"Customer distress was not acknowledged: {turn.text[:150]}",
            at_sec=turn.at_sec,
        )
    return None
