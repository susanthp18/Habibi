"""The action space, and the DPD ladder that bounds it.

Nine actions, one of which is silence. ``WAIT`` being a first-class action
rather than the absence of one is the design decision the rest of the module
hangs on: it means "do nothing" carries an expected value that competes on the
same axis as everything else, gets logged with a reason, and can win.

Two of the nine do not contact the borrower at all, and adding them is what
changes the question the engine can ask from *"who should we call?"* to *"what
intervention should we make, if any?"*. In Indian retail lending the
highest-yield early-bucket action is frequently not a contact: it is
re-presenting the mandate timed to the salary credit. It costs approximately
nothing, annoys nobody, and — because ``channel`` is ``None`` — is invisible to
the contact-frequency budget.

That exemption is the reason those two carry vetoes of their own in
:mod:`policy`. An action nothing caps is an action that needs its own limit, or
the goodwill budget stops being the thing that bounds how often we touch a
borrower's bank account.

**There is deliberately no ``payment_link`` action**, despite it being the
obvious third entry. In this stack ``enact._copy`` already composes the live
pay-link into the WhatsApp and SMS bodies, so a separate action would be the
same message, on the same channel, at the same cost — a synonym rather than an
intervention. Two synonyms in one action space is worse than an omission: they
tie in the ranking, each fails to block the other as "already planned", and the
borrower gets two messages about one bounce. If a genuinely link-only
touch is wanted later it needs its own channel and its own copy, not a second
name for this one.

The ladder (``rung``) encodes escalation. A borrower who missed an EMI
yesterday and one who has been silent for ninety days need the same *ranking*
machinery and very different *reachable sets*, and the difference is structural
rather than a matter of degree — so it lives here, as a bucket→actions map,
where it can be read by a compliance officer without reading the scorer.

The bucket mix follows the roadmap's DPD operating model, which in turn follows
Caller Digital's published playbook and Finezza's trigger logic: voice AI is for
early buckets, 61–90 is triage, and 90+ belongs to a specialist with the bot
reduced to logistics.
"""

from __future__ import annotations

from dataclasses import dataclass

WAIT = "wait"
REPRESENT_MANDATE = "represent_mandate"
EMI_DATE_CHANGE = "emi_date_change"
SELF_SERVICE_PLAN = "self_service_plan"
SMS = "sms"
WHATSAPP = "whatsapp"
VOICE_BOT = "voice_bot"
HUMAN_CALL = "human_call"
FIELD_VISIT = "field_visit"
LEGAL_NOTICE = "legal_notice"


@dataclass(frozen=True)
class ActionSpec:
    key: str
    #: The contact channel this consumes, or None for actions that touch nobody.
    #: ``human_call`` is voice: a telecaller dialling counts against the same
    #: borrower frequency budget as the bot, which is the entire point of P6.
    channel: str | None
    actor_kind: str
    #: Position on the escalation ladder. Monotonicity is enforced against this.
    rung: int
    #: 0..1 — how much of the borrower's patience one attempt spends. Prices the
    #: goodwill externality that stops three cheap SMS beating one useful call.
    intrusiveness: float
    #: Digital actions are the ones a field visit must exhaust first.
    digital: bool
    requires_phone: bool = True
    #: Needs a person on our side, so it competes for floor capacity too.
    human_effort: bool = False


SPECS: dict[str, ActionSpec] = {
    WAIT: ActionSpec(WAIT, None, "system", 0, 0.0, False, requires_phone=False),
    # channel=None, rung 0, intrusiveness 0. Re-presenting a mandate is not a
    # rung on the escalation ladder — it is the ordinary collection mechanism
    # working, and a borrower whose EMI is debited on the day their salary
    # lands experiences nothing at all. It cannot advance the ladder and it
    # cannot spend the contact budget; policy._mandate_veto is what bounds it.
    REPRESENT_MANDATE: ActionSpec(
        REPRESENT_MANDATE, None, "system", 0, 0.0, False, requires_phone=False
    ),
    # Fixes the *cause* rather than chasing the symptom: a borrower whose EMI
    # falls three days before payday will bounce every month until the date
    # moves. Self-service, so it touches nobody — telling them about it is a
    # separate action that pays for its own touch.
    EMI_DATE_CHANGE: ActionSpec(
        EMI_DATE_CHANGE, None, "system", 0, 0.0, False, requires_phone=False
    ),
    # Open a borrower-initiated resolution path and let them take it in their
    # own time. channel=None because nothing is sent: the plan is enabled on
    # the account and surfaces where the borrower already is -- the app, the
    # portal, the next statement.
    #
    # This is the only one of the design note's three concession actions that
    # is genuinely an *action*. A part-payment or a restructure has to be said
    # to somebody, which makes it a property of a contact rather than an
    # alternative to one; both live on the Action Contract's allowedOffers,
    # where the authority matrix decides them. Modelling them as actions would
    # have the engine choosing between "send a WhatsApp" and "offer a
    # settlement" as if those were the same kind of thing.
    SELF_SERVICE_PLAN: ActionSpec(
        SELF_SERVICE_PLAN, None, "system", 0, 0.0, False, requires_phone=False
    ),
    SMS: ActionSpec(SMS, "sms", "system", 1, 0.10, True),
    WHATSAPP: ActionSpec(WHATSAPP, "whatsapp", "system", 1, 0.15, True),
    VOICE_BOT: ActionSpec(VOICE_BOT, "voice", "bot", 2, 0.45, False),
    HUMAN_CALL: ActionSpec(HUMAN_CALL, "voice", "human", 3, 0.50, False, human_effort=True),
    FIELD_VISIT: ActionSpec(
        FIELD_VISIT, "field", "agency", 4, 0.85, False, requires_phone=False, human_effort=True
    ),
    # channel=None on purpose. A statutory demand under NI Act s.138 or
    # SARFAESI s.13(2) is a legal instrument served by registered post, not an
    # outbound contact attempt — and it is time-barred. Letting a frequency cap
    # defer it would let a goodwill budget invalidate a recovery.
    LEGAL_NOTICE: ActionSpec(
        LEGAL_NOTICE, None, "system", 5, 0.95, False, requires_phone=False, human_effort=True
    ),
}

ALL: tuple[str, ...] = tuple(SPECS)

#: Actions that consume borrower contact budget. ``WAIT`` does not, which is
#: why it is always in the candidate set even at cap.
CONTACTING: frozenset[str] = frozenset(k for k, s in SPECS.items() if s.channel)

DIGITAL: frozenset[str] = frozenset(k for k, s in SPECS.items() if s.digital)

#: Interventions that change the borrower's position without reaching them.
#: Derived rather than listed, so a new ``channel=None`` action cannot be added
#: without inheriting the exemption *and* the obligation that comes with it —
#: nothing here is bounded by the frequency cap, so each one needs a limit of
#: its own in :mod:`policy`. ``LEGAL_NOTICE`` is excluded because it is served
#: rather than performed, and ``WAIT`` because it does nothing at all.
NON_CONTACTING: frozenset[str] = frozenset(
    k for k, s in SPECS.items() if s.channel is None and k not in {WAIT, LEGAL_NOTICE}
)


# ---------------------------------------------------------------------------
# DPD buckets
# ---------------------------------------------------------------------------

PRE_DUE = "pre_due"
B_0_30 = "0-30"
B_31_60 = "31-60"
B_61_90 = "61-90"
B_90_PLUS = "90+"

BUCKET_ORDER: tuple[str, ...] = (PRE_DUE, B_0_30, B_31_60, B_61_90, B_90_PLUS)


@dataclass(frozen=True)
class BucketPolicy:
    key: str
    allowed: frozenset[str]
    #: Published mid-point of the AI share of outreach for this bucket. Used as
    #: a soft prior on automated actions, never as a gate — the gate is
    #: ``allowed``. Keeping the two apart is what stops a share target being
    #: quietly reinterpreted as permission.
    ai_share: float
    #: A human owns the relationship in this bucket, so automation that is
    #: still permitted should read as assistance rather than as the plan.
    human_owned: bool
    #: Where the escalation ladder *starts* for this bucket, before any
    #: history. Without it a 92-DPD borrower with no contact history would sit
    #: at rung 0 and need three separate decisions to reach a person — which is
    #: backwards, since 90+ is precisely the bucket a specialist should own
    #: from the first touch. The ladder governs how fast we escalate, not
    #: whether a distress case may have a human at all.
    ladder_floor: int = 0


BUCKETS: dict[str, BucketPolicy] = {
    # Not delinquent. A reminder, never a call — the highest-ROI window in the
    # book and the one where a dial reads as harassment.
    PRE_DUE: BucketPolicy(
        PRE_DUE,
        frozenset(
            {WAIT, REPRESENT_MANDATE, EMI_DATE_CHANGE, SMS, WHATSAPP}
        ),
        1.00,
        False,
        0,
    ),
    # Forgot, or a cash-flow wobble. Still reachable, still cheap to cure. The
    # coverage bucket: contacting 100% of it inside 48h is the whole P&L.
    B_0_30: BucketPolicy(
        B_0_30,
        frozenset(
            {
                WAIT,
                REPRESENT_MANDATE,
                EMI_DATE_CHANGE,
                SELF_SERVICE_PLAN,
                SMS,
                WHATSAPP,
                VOICE_BOT,
                HUMAN_CALL,
            }
        ),
        0.75,
        False,
        0,
    ),
    # Hesitation, and bureau reporting starts to bite. Field becomes available
    # for secured lending above a ticket threshold — but only after digital has
    # actually been exhausted, which policy.py enforces separately.
    B_31_60: BucketPolicy(
        B_31_60,
        frozenset(
            {
                WAIT,
                REPRESENT_MANDATE,
                EMI_DATE_CHANGE,
                SELF_SERVICE_PLAN,
                SMS,
                WHATSAPP,
                VOICE_BOT,
                HUMAN_CALL,
                FIELD_VISIT,
            }
        ),
        0.55,
        False,
        1,
    ),
    # Triage only: willing / distress / dispute, then route. The bot may still
    # open the conversation; it may not own it.
    # EMI_DATE_CHANGE is absent from here on. Moving the due date fixes a
    # salary-timing mismatch; at 61 DPD the problem is no longer timing, and
    # offering it there is a restructure wearing a self-service label.
    B_61_90: BucketPolicy(
        B_61_90,
        frozenset(
            {
                WAIT,
                REPRESENT_MANDATE,
                # Still available where the date change is not. A borrower at
                # 61 DPD has a real arrears problem rather than a timing one,
                # and a plan they can start themselves is the cheapest route
                # out of it -- while moving the due date at that point would be
                # a restructure wearing a self-service label.
                SELF_SERVICE_PLAN,
                WHATSAPP,
                VOICE_BOT,
                HUMAN_CALL,
                FIELD_VISIT,
                LEGAL_NOTICE,
            }
        ),
        0.30,
        True,
        2,
    ),
    # NPA. Empathy, OTS, SARFAESI — a specialist's judgment, and explicitly not
    # a thing to automate. VOICE_BOT is absent from this set on purpose: the
    # published ~10% AI share at 90+ is logistics confirmation, and this engine
    # has no way to tell a logistics ping from a dunning call, so it declines to
    # emit either.
    # REPRESENT_MANDATE survives into 90+ where VOICE_BOT does not, and the
    # asymmetry is the point: a live mandate that clears recovers an EMI from a
    # borrower nobody had to speak to. It is the one action whose case gets
    # *stronger* as the account gets harder, because its cost never rises.
    B_90_PLUS: BucketPolicy(
        B_90_PLUS,
        frozenset(
            {
                WAIT,
                REPRESENT_MANDATE,
                WHATSAPP,
                HUMAN_CALL,
                FIELD_VISIT,
                LEGAL_NOTICE,
            }
        ),
        0.10,
        True,
        2,
    ),
}


def bucket_for(dpd: int | None, *, days_to_due: int | None = None) -> str:
    """Map DPD to a bucket key.

    ``days_to_due`` distinguishes "not delinquent yet" from "delinquent by
    zero days", which the DPD column alone cannot: both are 0.
    """
    if dpd is None or dpd <= 0:
        # Nothing is overdue. ``days_to_due`` is carried for the caller's
        # benefit — a pre-due reminder and a cured account are the same bucket
        # here and are told apart by the trigger, not by the ladder.
        return PRE_DUE
    if dpd <= 30:
        return B_0_30
    if dpd <= 60:
        return B_31_60
    if dpd <= 90:
        return B_61_90
    return B_90_PLUS


def bucket_policy(bucket: str) -> BucketPolicy:
    return BUCKETS.get(bucket, BUCKETS[B_0_30])


def spec(action: str) -> ActionSpec:
    return SPECS[action]


def rung(action: str) -> int:
    return SPECS[action].rung if action in SPECS else 0


def label(action: str) -> str:
    """Human-readable, for the rep-facing rationale and the work queue."""
    return {
        WAIT: "hold",
        REPRESENT_MANDATE: "re-present mandate",
        EMI_DATE_CHANGE: "EMI date change",
        SELF_SERVICE_PLAN: "self-service plan",
        SMS: "SMS",
        WHATSAPP: "WhatsApp",
        VOICE_BOT: "bot call",
        HUMAN_CALL: "agent call",
        FIELD_VISIT: "field visit",
        LEGAL_NOTICE: "legal notice",
    }.get(action, action.replace("_", " "))
