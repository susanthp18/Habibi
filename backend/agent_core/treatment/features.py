"""Account + reachability feature vector for the treatment engine.

The plug-and-play seam, exactly as ``reco.features`` is for offers: candidates,
policy, scoring and arbitration depend only on :class:`AccountFeatures` and
:class:`Trigger`, never on a table name. A lender with a different core banking
schema implements one :class:`FeatureProvider` and changes nothing else.

Two rules carried over from reco because they are what keep a scorer honest:

* **Every uncertain field is nullable and ``None`` is a real value.** It means
  "we do not know". A borrower we have never dialled must not be ranked as
  though they had never answered.
* **The vector is versioned.** ``SCHEMA_VERSION`` lands on every decision row,
  because a model trained on v1 cannot be scored against v2 and something has
  to be able to tell them apart a year later.

The reachability half is the part offer recommendation has no analogue for. A
collections decision is mostly a bet about whether anyone will pick up, and the
cheapest evidence for that is what happened the last dozen times we tried — per
channel, and per hour of the day.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Mapping, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from agent_core.treatment import actions as A

logger = logging.getLogger(__name__)

#: v2 added the case-history fields (``case_attempts`` and friends) when the
#: follow-through loop landed. Bumped rather than sneaked in: a row logged
#: before the loop existed has no attempt count, and a model trained across the
#: boundary would read "absent" as "first attempt".
#:
#: v3 added the mandate and salary-timing fields. Same reasoning, and it matters
#: more here: a decision logged at v2 had no mandate state, so an uplift model
#: trained across the boundary would read every pre-v3 row as "no mandate on
#: this account" and learn that mandates are rare.
SCHEMA_VERSION = "v3"

DEFAULT_TZ = "Asia/Kolkata"

#: A voice interaction shorter than this never reached a person: it is a ring-
#: out, a voicemail beep or an immediate hang-up. Counting those as connects
#: would tell the engine the borrower is reachable at exactly the hours they
#: are not.
CONNECT_MIN_SECONDS = 20

#: Attempts needed before an observed connect rate beats the channel prior.
#: One dial that was answered is not a 100% reachable borrower, and treating it
#: as one produced an expected value an order of magnitude too high — the
#: scorer would send a ₹45 agent call at a ₹1,600 instalment on the strength of
#: a single data point.
MIN_ATTEMPTS_FOR_RATE = 3

#: Trigger kinds. These mirror the CHECK on ``treatment_decisions.trigger_kind``
#: — a kind this module does not know is a kind the log will reject.
TRIGGER_BOUNCE = "bounce"
TRIGGER_BROKEN_PTP = "broken_ptp"
TRIGGER_PRE_DUE = "pre_due"
TRIGGER_DPD_TICK = "dpd_tick"
TRIGGER_INBOUND = "inbound"
TRIGGER_MANUAL = "manual"
TRIGGER_NO_CONTACT = "no_contact"
TRIGGER_WRAP_UP = "wrap_up"

TRIGGERS = frozenset(
    {
        TRIGGER_BOUNCE,
        TRIGGER_BROKEN_PTP,
        TRIGGER_PRE_DUE,
        TRIGGER_DPD_TICK,
        TRIGGER_INBOUND,
        TRIGGER_MANUAL,
        TRIGGER_NO_CONTACT,
        TRIGGER_WRAP_UP,
    }
)


def _f(value: Any) -> float | None:
    """Decimal/str/None → float|None without inventing a zero."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def zone(name: str | None) -> ZoneInfo:
    label = (name or "").strip() or DEFAULT_TZ
    try:
        return ZoneInfo(label)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


@dataclass(frozen=True)
class Trigger:
    """Why we are deciding now.

    ``at`` is when the *event* happened, not when we got round to it. The gap
    between the two is the delay this whole product exists to close, so the
    scorer reads it directly.
    """

    kind: str = TRIGGER_MANUAL
    at: datetime | None = None
    ref: str | None = None

    def normalised(self) -> "Trigger":
        if self.kind in TRIGGERS:
            return self
        logger.warning("unknown treatment trigger %r — treating as manual", self.kind)
        return Trigger(kind=TRIGGER_MANUAL, at=self.at, ref=self.ref)

    def age_hours(self, now: datetime) -> float | None:
        at = _aware(self.at)
        if at is None:
            return None
        return max(0.0, (now - at).total_seconds() / 3600.0)

    def to_log(self, now: datetime) -> dict[str, Any]:
        return {"kind": self.kind, "ref": self.ref, "ageHours": self.age_hours(now)}


@dataclass(frozen=True)
class AccountFeatures:
    """What we know about this borrower and this account, right now."""

    customer_id: str
    tenant_id: str
    account_id: str | None = None
    schema_version: str = SCHEMA_VERSION

    # --- exposure -----------------------------------------------------------
    dpd: int | None = None
    bucket: str = A.B_0_30
    outstanding: float | None = None
    minimum_due: float | None = None
    instalment_amount: float | None = None
    days_overdue: int | None = None
    account_status: str | None = None
    product_category: str | None = None
    secured: bool = False

    # --- the live event -----------------------------------------------------
    open_bounce_id: str | None = None
    bounce_reason: str | None = None
    bounce_age_hours: float | None = None
    bounce_first_touch_channel: str | None = None
    #: Salary-credit hint from the CBS. Retrying a mandate against the credit
    #: rather than the calendar is the single highest-yield timing decision in
    #: the early buckets.
    next_credit_at: datetime | None = None

    # --- the payment mandate ------------------------------------------------
    #: The mandate this account is collected through, if any. Absent means we
    #: have no standing instruction, so ``represent_mandate`` is not an option —
    #: which is a different thing from having one that keeps failing.
    mandate_id: str | None = None
    mandate_rail: str | None = None
    mandate_status: str | None = None
    mandate_debit_day: int | None = None
    mandate_max_amount: float | None = None
    #: The cycle a re-presentment would settle: the due date of the oldest
    #: unpaid instalment. Presentations are counted against *this*, because two
    #: attempts at one cycle are a retry and two attempts at different cycles
    #: are ordinary collection.
    mandate_cycle: date | None = None
    mandate_attempts_this_cycle: int = 0
    #: The most recent return, whatever cycle it came from. This is the
    #: diagnostic: a mandate that failed for insufficient funds is a timing
    #: problem, one that failed because it was cancelled is not a problem any
    #: amount of contact can fix.
    mandate_last_return_reason: str | None = None
    mandate_last_presented_at: datetime | None = None

    # --- the timing mismatch ------------------------------------------------
    #: Day of month the EMI falls due, and the day the salary lands. A standing
    #: gap between them is a *timing* problem rather than a willingness one,
    #: and it is the only condition under which moving the date is a cure
    #: rather than a concession.
    emi_due_day: int | None = None
    salary_credit_day: int | None = None

    # --- promise history ----------------------------------------------------
    promises_total: int = 0
    promises_kept: int = 0
    promises_broken: int = 0
    #: None with no promise history — absent, not zero. A first-time borrower
    #: is not a serial breaker.
    ptp_keep_rate: float | None = None
    open_promise_id: str | None = None
    last_promise_status: str | None = None
    hours_since_promise_broken: float | None = None

    # --- contact budget -----------------------------------------------------
    touches_today: int = 0
    daily_cap: int = 3
    touches_7d: int = 0
    last_touch_at: datetime | None = None
    last_denied_reason: str | None = None
    #: Digital sends since the last time anyone actually reached this borrower.
    #: The exhaustion counter a field visit has to clear.
    digital_attempts_since_connect: int = 0

    # --- reachability -------------------------------------------------------
    #: channel → historical connect/response rate, or None where we have never
    #: tried on that channel.
    connect_rate: Mapping[str, float | None] = field(default_factory=dict)
    attempts_90d: Mapping[str, int] = field(default_factory=dict)
    #: Local hours at which this borrower has actually answered.
    responsive_hours: tuple[int, ...] = ()
    last_connect_at: datetime | None = None
    last_inbound_at: datetime | None = None

    # --- contactability -----------------------------------------------------
    dnd: bool = False
    consent_by_channel: Mapping[str, str] = field(default_factory=dict)
    #: The consented contact window, already parsed. ``timing`` plans against
    #: exactly what ``contact_policy`` vetoes against — see
    #: ``contact_policy.parse_allowed_hours``.
    allowed_hours: tuple[int, int] | None = None
    allowed_days: tuple[int, ...] | None = None
    preferred_window: str | None = None
    timezone_name: str | None = None
    language: str | None = None
    has_phone: bool = False
    has_email: bool = False

    # --- vetoes -------------------------------------------------------------
    holds: tuple[str, ...] = ()
    open_dispute_count: int = 0
    field_visits_90d: int = 0
    legal_notice_at: datetime | None = None

    # --- this case's own history -------------------------------------------
    #: Treatments already *enacted* for this trigger reference. The ladder is
    #: about what the borrower has experienced, so shadow and suppressed
    #: decisions do not count.
    case_attempts: int = 0
    #: action → times it has been enacted on *this* case. Distinct from
    #: ``case_attempts`` and load-bearing: "we already sent exactly this message
    #: about exactly this bounce and they ignored it" is far stronger evidence
    #: against repeating it than "we have contacted them a few times".
    case_actions_tried: Mapping[str, int] = field(default_factory=dict)
    case_last_action: str | None = None
    case_last_outcome: str | None = None
    hours_since_last_attempt: float | None = None

    # --- who owns it --------------------------------------------------------
    assigned_user_id: str | None = None
    segment: str | None = None
    risk: str | None = None
    risk_score: int | None = None

    @property
    def exposure(self) -> float:
        """Rupees at risk on this decision.

        The instalment, not the balance: curing a 1–30 DPD account means
        collecting the EMI and stopping the roll-forward, and pricing the whole
        sanctioned amount would make every early-bucket action look infinitely
        worthwhile.
        """
        for value in (self.instalment_amount, self.minimum_due, self.outstanding):
            if value is not None and value > 0:
                return float(value)
        return 0.0

    @property
    def salary_timing_gap_days(self) -> int | None:
        """Days the salary lands *after* the EMI falls due. None if unknown.

        Positive means the borrower is asked for money before they have it,
        every single month — which is a calendar problem the lender created and
        can fix, not a willingness problem to be dunned about.

        Wrapped to a half-month window because the days are days-of-month and
        the distance between the 29th and the 2nd is four days, not
        twenty-seven. Negative means the salary lands comfortably first.
        """
        if self.emi_due_day is None or self.salary_credit_day is None:
            return None
        gap = self.salary_credit_day - self.emi_due_day
        if gap > 15:
            gap -= 30
        elif gap < -15:
            gap += 30
        return gap

    @property
    def budget_left(self) -> int:
        return max(0, self.daily_cap - self.touches_today)

    def to_log(self) -> dict[str, Any]:
        """PII-minimised snapshot. Ids, counts and money bands only.

        The log is retained for training and for the regulator, so it must not
        become a second copy of the customer record: no name, no phone, no free
        text the borrower said.
        """
        return {
            "schemaVersion": self.schema_version,
            "accountId": self.account_id,
            "dpd": self.dpd,
            "bucket": self.bucket,
            "outstanding": self.outstanding,
            "minimumDue": self.minimum_due,
            "instalmentAmount": self.instalment_amount,
            "exposure": self.exposure,
            "daysOverdue": self.days_overdue,
            "accountStatus": self.account_status,
            "productCategory": self.product_category,
            "secured": self.secured,
            "openBounce": bool(self.open_bounce_id),
            "bounceReason": self.bounce_reason,
            "bounceAgeHours": self.bounce_age_hours,
            "bounceFirstTouchChannel": self.bounce_first_touch_channel,
            "hasNextCreditHint": self.next_credit_at is not None,
            # The mandate's *state*, never its identifiers. A UMRN and a bank
            # account tail are exactly the kind of thing an append-only log
            # retained for training must not accumulate, and nothing downstream
            # needs them to decide whether to present.
            "hasMandate": self.mandate_id is not None,
            "mandateRail": self.mandate_rail,
            "mandateStatus": self.mandate_status,
            "mandateAttemptsThisCycle": self.mandate_attempts_this_cycle,
            "mandateLastReturnReason": self.mandate_last_return_reason,
            "emiDueDay": self.emi_due_day,
            "salaryCreditDay": self.salary_credit_day,
            "salaryTimingGapDays": self.salary_timing_gap_days,
            "promisesTotal": self.promises_total,
            "promisesKept": self.promises_kept,
            "promisesBroken": self.promises_broken,
            "ptpKeepRate": self.ptp_keep_rate,
            "lastPromiseStatus": self.last_promise_status,
            "hoursSincePromiseBroken": self.hours_since_promise_broken,
            "touchesToday": self.touches_today,
            "dailyCap": self.daily_cap,
            "touches7d": self.touches_7d,
            "lastDeniedReason": self.last_denied_reason,
            "digitalAttemptsSinceConnect": self.digital_attempts_since_connect,
            "connectRate": dict(self.connect_rate),
            "attempts90d": dict(self.attempts_90d),
            "responsiveHours": list(self.responsive_hours),
            "dnd": self.dnd,
            "consentByChannel": dict(self.consent_by_channel),
            "allowedHours": list(self.allowed_hours) if self.allowed_hours else None,
            "allowedDays": list(self.allowed_days) if self.allowed_days else None,
            "preferredWindow": self.preferred_window,
            "timezone": self.timezone_name,
            "hasPhone": self.has_phone,
            "hasEmail": self.has_email,
            "holds": list(self.holds),
            "openDisputeCount": self.open_dispute_count,
            "fieldVisits90d": self.field_visits_90d,
            "legalNoticeSent": self.legal_notice_at is not None,
            "caseAttempts": self.case_attempts,
            "caseActionsTried": dict(self.case_actions_tried),
            "caseLastAction": self.case_last_action,
            "caseLastOutcome": self.case_last_outcome,
            "hoursSinceLastAttempt": self.hours_since_last_attempt,
            "segment": self.segment,
            "risk": self.risk,
            "riskScore": self.risk_score,
        }


class FeatureProvider(Protocol):
    """The seam. Implement against your own schema and the rest works.

    ``conn`` is a hint, not a requirement: the engine holds a connection open
    anyway, and passing it means one checkout per decision instead of several.
    A provider backed by a feature store or a REST API ignores it.
    """

    def build(
        self,
        customer_id: str,
        *,
        account_id: str | None,
        trigger: Trigger,
        now: datetime,
        conn: Any | None = None,
    ) -> AccountFeatures: ...


# ---------------------------------------------------------------------------
# The default provider, over this schema
# ---------------------------------------------------------------------------


class SqlFeatureProvider:
    """Reads the CRM directly. Every query is indexed and customer-scoped."""

    def build(
        self,
        customer_id: str,
        *,
        account_id: str | None,
        trigger: Trigger,
        now: datetime,
        conn: Any | None = None,
    ) -> AccountFeatures:
        if conn is None:
            import db

            with db.engine.connect() as owned:
                return self._build(owned, customer_id, account_id, trigger, now)
        return self._build(conn, customer_id, account_id, trigger, now)

    # -------------------------------------------------------------- internals

    def _build(
        self,
        conn: Any,
        customer_id: str,
        account_id: str | None,
        trigger: Trigger,
        now: datetime,
    ) -> AccountFeatures:
        base = conn.execute(
            text(
                """
                SELECT c.id, c.tenant_id, c.assigned_user_id, c.dnd, c.timezone,
                       c.language, c.preferred_window, c.segment, c.risk,
                       c.risk_score, c.phone_primary, c.phone_alt, c.email,
                       cr.allowed_days, cr.allowed_hours, cr.dnd_registry
                FROM customers c
                LEFT JOIN consent_records cr ON cr.customer_id = c.id
                WHERE c.id = :cid
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
        if base is None:
            raise LookupError(f"customer_not_found:{customer_id}")

        account = self._account(conn, customer_id, account_id)
        tz = zone(base["timezone"])

        bounce = self._bounce(conn, customer_id, account)
        promises = self._promises(conn, customer_id, account, now)
        contact = self._contact(conn, customer_id, now, tz)
        reach = self._reachability(conn, customer_id, now, tz)
        holds = self._holds(conn, customer_id, account)
        history = self._treatment_history(conn, customer_id, now)
        case = self._case_history(conn, customer_id, trigger, now)

        dpd = int(account["dpd"]) if account and account.get("dpd") is not None else None
        instalment = self._instalment(conn, account)
        mandate = self._mandate(conn, account, instalment, bounce, tz)

        import capture
        import contact_policy

        try:
            consent = capture.latest_consent_by_channel(conn, customer_id)
        except Exception:
            logger.exception("consent read failed for %s", customer_id)
            consent = {}

        parsed_hours = contact_policy.parse_allowed_hours(base["allowed_hours"])
        _hours = tuple(parsed_hours) if parsed_hours else None
        parsed_days = contact_policy.parse_allowed_days(base["allowed_days"])
        _days = tuple(parsed_days) if parsed_days else None

        return AccountFeatures(
            customer_id=customer_id,
            tenant_id=base["tenant_id"],
            account_id=account["id"] if account else None,
            dpd=dpd,
            bucket=A.bucket_for(dpd),
            outstanding=_f(account.get("outstanding")) if account else None,
            minimum_due=_f(account.get("minimum_due")) if account else None,
            instalment_amount=instalment["amount"],
            days_overdue=instalment["days_overdue"],
            account_status=account.get("status") if account else None,
            product_category=account.get("category") if account else None,
            secured=bool(account.get("secured")) if account else False,
            assigned_user_id=base["assigned_user_id"],
            # ``dnd_registry`` is the TRAI/NDND scrub; ``customers.dnd`` is the
            # account-level flag. Either one blocks outreach, so the feature is
            # their OR rather than one of them.
            dnd=bool(base["dnd"] or base["dnd_registry"]),
            consent_by_channel=consent,
            allowed_hours=_hours,
            allowed_days=_days,
            preferred_window=base["preferred_window"],
            timezone_name=base["timezone"],
            language=base["language"],
            has_phone=bool(base["phone_primary"] or base["phone_alt"]),
            has_email=bool(base["email"]),
            segment=base["segment"],
            risk=base["risk"],
            risk_score=base["risk_score"],
            **bounce,
            **mandate,
            **promises,
            **contact,
            **reach,
            **holds,
            **history,
            **case,
        )

    def _account(
        self, conn: Any, customer_id: str, account_id: str | None
    ) -> dict[str, Any] | None:
        """The account this decision is about.

        Without an explicit id, the worst account wins: a borrower with one
        clean card and one 45-DPD loan is a 45-DPD borrower, and treating them
        as the average of the two is how a bot ends up dialling a distress case
        with a pre-due script.
        """
        params: dict[str, Any] = {"cid": customer_id}
        where = "a.customer_id = :cid"
        if account_id:
            where += " AND a.id = :aid"
            params["aid"] = account_id
        row = conn.execute(
            text(
                f"""
                SELECT a.id, a.dpd, a.bucket, a.outstanding, a.minimum_due,
                       a.status, COALESCE(p.category, p.type) AS category,
                       -- Secured lending is what makes a field visit
                       -- proportionate at 31-60 and mandatory at 61-90.
                       -- category is frequently NULL in practice, so type is
                       -- the fallback rather than a silent "unsecured".
                       (lower(COALESCE(p.category, p.type, '')) IN
                          ('loan','auto','home','mortgage','gold','vehicle')) AS secured
                FROM accounts a
                LEFT JOIN products p ON p.id = a.product_id
                WHERE {where}
                ORDER BY a.dpd DESC NULLS LAST, a.outstanding DESC NULLS LAST, a.id
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()
        return dict(row) if row else None

    def _instalment(self, conn: Any, account: dict[str, Any] | None) -> dict[str, Any]:
        """Oldest unpaid instalment: amount, how overdue, id and due date.

        The id and the due date are here rather than in a second query because
        they are the cycle a mandate re-presentment would settle, and asking the
        same table twice for the same row is a query the book sweep pays for
        once per account per day.
        """
        empty: dict[str, Any] = {
            "amount": None,
            "days_overdue": None,
            "emi_id": None,
            "due_at": None,
        }
        if not account:
            return empty
        row = conn.execute(
            text(
                """
                SELECT id, amount, paid_amount, due_date
                FROM emi_installments
                WHERE account_id = :aid AND status IN ('overdue','partial','upcoming')
                ORDER BY due_date ASC, installment_index ASC
                LIMIT 1
                """
            ),
            {"aid": account["id"]},
        ).mappings().first()
        if row is None:
            return empty
        amount = _f(row["amount"])
        paid = _f(row["paid_amount"]) or 0.0
        due = _aware(row["due_date"])
        days = None
        if due is not None:
            days = int((datetime.now(timezone.utc) - due).total_seconds() // 86400)
        return {
            "amount": None if amount is None else max(0.0, amount - paid),
            "days_overdue": days,
            "emi_id": row["id"],
            "due_at": due,
        }

    def _mandate(
        self,
        conn: Any,
        account: dict[str, Any] | None,
        instalment: dict[str, Any],
        bounce: Mapping[str, Any],
        tz: ZoneInfo,
    ) -> dict[str, Any]:
        """The standing instruction, and what it has done lately.

        Absent is not the same as broken, and both differ from exhausted. The
        three are told apart here rather than in the veto, because "we have no
        mandate on this account" and "we have one and it has already been
        presented twice this cycle" call for opposite next actions and the
        scorer must be able to see which it is.
        """
        blank: dict[str, Any] = {
            "mandate_id": None,
            "mandate_rail": None,
            "mandate_status": None,
            "mandate_debit_day": None,
            "mandate_max_amount": None,
            "mandate_cycle": None,
            "mandate_attempts_this_cycle": 0,
            "mandate_last_return_reason": None,
            "mandate_last_presented_at": None,
            "emi_due_day": None,
            "salary_credit_day": None,
        }

        due_at = instalment.get("due_at")
        credit_at = bounce.get("next_credit_at")
        local_due = due_at.astimezone(tz) if isinstance(due_at, datetime) else None
        local_credit = credit_at.astimezone(tz) if isinstance(credit_at, datetime) else None
        blank["emi_due_day"] = local_due.day if local_due else None
        blank["salary_credit_day"] = local_credit.day if local_credit else None

        if not account:
            return blank

        row = conn.execute(
            text(
                """
                SELECT id, rail, status, debit_day, max_amount
                FROM mandates
                WHERE account_id = :aid
                -- An active mandate outranks a dead one even if the dead one is
                -- newer: the question this answers is "what can we present?",
                -- not "what was registered last".
                ORDER BY (status = 'active') DESC, registered_at DESC NULLS LAST, id
                LIMIT 1
                """
            ),
            {"aid": account["id"]},
        ).mappings().first()
        if row is None:
            return blank

        cycle = local_due.date() if local_due else None
        counts = conn.execute(
            text(
                """
                SELECT
                  count(*) FILTER (
                    WHERE :cycle IS NOT NULL AND presented_for = CAST(:cycle AS date)
                      AND status <> 'cancelled'
                  )::int AS this_cycle,
                  (ARRAY_AGG(return_reason ORDER BY
                     COALESCE(settled_at, presented_at, created_at) DESC)
                   FILTER (WHERE return_reason IS NOT NULL))[1] AS last_reason,
                  max(presented_at) AS last_presented_at
                FROM mandate_presentations
                WHERE mandate_id = :mid
                """
            ),
            {"mid": row["id"], "cycle": cycle},
        ).mappings().first()

        return {
            **blank,
            "mandate_id": row["id"],
            "mandate_rail": row["rail"],
            "mandate_status": row["status"],
            "mandate_debit_day": (
                int(row["debit_day"]) if row["debit_day"] is not None else None
            ),
            "mandate_max_amount": _f(row["max_amount"]),
            "mandate_cycle": cycle,
            "mandate_attempts_this_cycle": int((counts or {}).get("this_cycle") or 0),
            "mandate_last_return_reason": (counts or {}).get("last_reason"),
            "mandate_last_presented_at": _aware((counts or {}).get("last_presented_at")),
        }

    def _bounce(
        self, conn: Any, customer_id: str, account: dict[str, Any] | None
    ) -> dict[str, Any]:
        row = conn.execute(
            text(
                """
                SELECT id, reason, occurred_at, first_touch_channel, next_credit_at
                FROM payment_events
                WHERE customer_id = :cid
                  AND kind = 'bounce'
                  AND status IN ('open','in_progress')
                  -- CAST because Postgres cannot infer a parameter's type from
                  -- IS NULL alone, and the null test is what it sees first.
                  AND (CAST(:aid AS TEXT) IS NULL OR account_id = :aid)
                ORDER BY occurred_at DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id, "aid": account["id"] if account else None},
        ).mappings().first()
        if row is None:
            return {
                "open_bounce_id": None,
                "bounce_reason": None,
                "bounce_age_hours": None,
                "bounce_first_touch_channel": None,
                "next_credit_at": None,
            }
        occurred = _aware(row["occurred_at"])
        age = (
            None
            if occurred is None
            else max(0.0, (datetime.now(timezone.utc) - occurred).total_seconds() / 3600.0)
        )
        return {
            "open_bounce_id": row["id"],
            "bounce_reason": row["reason"],
            "bounce_age_hours": age,
            "bounce_first_touch_channel": row["first_touch_channel"],
            "next_credit_at": _aware(row["next_credit_at"]),
        }

    def _promises(
        self,
        conn: Any,
        customer_id: str,
        account: dict[str, Any] | None,
        now: datetime,
    ) -> dict[str, Any]:
        agg = conn.execute(
            text(
                """
                SELECT
                  count(*)::int AS total,
                  count(*) FILTER (WHERE status = 'kept')::int AS kept,
                  count(*) FILTER (WHERE status = 'broken')::int AS broken
                FROM promises
                WHERE customer_id = :cid
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
        total = int((agg or {}).get("total") or 0)
        kept = int((agg or {}).get("kept") or 0)
        broken = int((agg or {}).get("broken") or 0)
        # Only settled promises carry information. An upcoming promise is not
        # evidence of anything yet, and folding it into the denominator would
        # make every borrower look less reliable the moment they promised.
        settled = kept + broken
        keep_rate = (kept / settled) if settled else None

        latest = conn.execute(
            text(
                """
                SELECT id, status, promised_at, updated_at
                FROM promises
                WHERE customer_id = :cid
                ORDER BY promised_at DESC, created_at DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
        open_promise = conn.execute(
            text(
                """
                SELECT id FROM promises
                WHERE customer_id = :cid AND status IN ('upcoming','due_today','partial')
                ORDER BY promised_at ASC
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).scalar()

        broken_at = None
        if latest is not None and latest["status"] == "broken":
            updated = _aware(latest["updated_at"]) or _aware(latest["promised_at"])
            if updated is not None:
                broken_at = max(0.0, (now - updated).total_seconds() / 3600.0)

        return {
            "promises_total": total,
            "promises_kept": kept,
            "promises_broken": broken,
            "ptp_keep_rate": keep_rate,
            "open_promise_id": open_promise,
            "last_promise_status": latest["status"] if latest else None,
            "hours_since_promise_broken": broken_at,
        }

    def _contact(
        self, conn: Any, customer_id: str, now: datetime, tz: ZoneInfo
    ) -> dict[str, Any]:
        import contact_policy

        local_date = now.astimezone(tz).date()
        today = conn.execute(
            text(
                """
                SELECT outreach_sessions FROM contact_day_counters
                WHERE customer_id = :cid AND local_date = :d
                """
            ),
            {"cid": customer_id, "d": local_date},
        ).scalar()
        week = conn.execute(
            text(
                """
                SELECT count(*)::int FROM contact_events
                WHERE customer_id = :cid
                  AND outcome = 'allowed' AND touch_counted
                  AND occurred_at >= :since
                """
            ),
            {"cid": customer_id, "since": now - timedelta(days=7)},
        ).scalar()
        last = conn.execute(
            text(
                """
                SELECT occurred_at FROM contact_events
                WHERE customer_id = :cid AND outcome = 'allowed' AND touch_counted
                ORDER BY occurred_at DESC LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).scalar()
        denied = conn.execute(
            text(
                """
                SELECT reason FROM contact_events
                WHERE customer_id = :cid AND outcome = 'denied'
                ORDER BY occurred_at DESC LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).scalar()
        return {
            "touches_today": int(today or 0),
            "daily_cap": contact_policy.daily_cap(),
            "touches_7d": int(week or 0),
            "last_touch_at": _aware(last),
            "last_denied_reason": denied,
        }

    def _reachability(
        self, conn: Any, customer_id: str, now: datetime, tz: ZoneInfo
    ) -> dict[str, Any]:
        """Per-channel connect rates and the hours this borrower answers.

        Attempts come from the contact ledger; connects come from the two
        places a borrower can actually respond — a voice interaction that
        lasted long enough to be a conversation, and an inbound message. SMS
        has no inbound path in this stack, so its rate is legitimately unknown
        and stays ``None`` rather than being reported as zero.
        """
        since = now - timedelta(days=90)
        attempt_rows = conn.execute(
            text(
                """
                SELECT channel, count(*)::int AS n, min(occurred_at) AS first_at
                FROM contact_events
                WHERE customer_id = :cid
                  AND outcome = 'allowed'
                  AND direction = 'outbound'
                  AND occurred_at >= :since
                GROUP BY channel
                """
            ),
            {"cid": customer_id, "since": since},
        ).mappings().all()
        attempts = {r["channel"]: int(r["n"] or 0) for r in attempt_rows}
        # The two halves of the ratio come from different tables with different
        # histories: ``interactions`` goes back to the seed, ``contact_events``
        # only began when the contact ledger shipped. Counting a call that
        # predates the ledger against an attempt the ledger recorded is how a
        # borrower ends up with a connect rate above 1.
        first_attempt = {
            r["channel"]: _aware(r["first_at"])
            for r in attempt_rows
            if r["first_at"] is not None
        }

        voice_rows = conn.execute(
            text(
                """
                SELECT started_at, duration_sec
                FROM interactions
                WHERE customer_id = :cid
                  AND channel = 'voice'
                  AND status = 'completed'
                  AND started_at >= :since
                ORDER BY started_at DESC
                LIMIT 200
                """
            ),
            {"cid": customer_id, "since": since},
        ).mappings().all()
        connects = [
            r for r in voice_rows if int(r["duration_sec"] or 0) >= CONNECT_MIN_SECONDS
        ]
        voice_floor = first_attempt.get("voice")
        countable_voice = [
            r
            for r in connects
            if voice_floor is None or (_aware(r["started_at"]) or since) >= voice_floor
        ]
        wa_floor = first_attempt.get("whatsapp")

        inbound = conn.execute(
            text(
                """
                SELECT m.created_at
                FROM messages m
                JOIN conversations cv ON cv.id = m.conversation_id
                WHERE cv.customer_id = :cid
                  AND cv.channel = 'whatsapp'
                  AND m.sender = 'customer'
                  AND m.created_at >= :since
                ORDER BY m.created_at DESC
                LIMIT 200
                """
            ),
            {"cid": customer_id, "since": since},
        ).mappings().all()

        countable_inbound = [
            r
            for r in inbound
            if wa_floor is None or (_aware(r["created_at"]) or since) >= wa_floor
        ]

        rate: dict[str, float | None] = {}
        for channel, responded in (
            ("voice", len(countable_voice)),
            ("whatsapp", len(countable_inbound)),
        ):
            tried = attempts.get(channel, 0)
            # Below the sample floor the prior is the better estimate, and
            # saying so is what keeps "we have never really tried" out of the
            # decision log disguised as "they always answer".
            rate[channel] = (
                min(1.0, responded / tried) if tried >= MIN_ATTEMPTS_FOR_RATE else None
            )
        # No inbound SMS path exists in this stack. Absent, not zero.
        rate["sms"] = None
        rate["field"] = None

        hours = sorted(
            {
                _aware(r["started_at"]).astimezone(tz).hour
                for r in connects
                if _aware(r["started_at"]) is not None
            }
        )

        last_connect = _aware(connects[0]["started_at"]) if connects else None
        last_inbound = _aware(inbound[0]["created_at"]) if inbound else None

        floor = max(
            [d for d in (last_connect, last_inbound) if d is not None],
            default=None,
        )
        digital_since = conn.execute(
            text(
                """
                SELECT count(*)::int FROM contact_events
                WHERE customer_id = :cid
                  AND outcome = 'allowed'
                  AND direction = 'outbound'
                  AND channel IN ('sms','whatsapp','email')
                  AND occurred_at >= COALESCE(:floor, :since)
                """
            ),
            {"cid": customer_id, "floor": floor, "since": since},
        ).scalar()

        return {
            "connect_rate": rate,
            "attempts_90d": attempts,
            "responsive_hours": tuple(hours),
            "last_connect_at": last_connect,
            "last_inbound_at": last_inbound,
            "digital_attempts_since_connect": int(digital_since or 0),
        }

    def _holds(
        self, conn: Any, customer_id: str, account: dict[str, Any] | None
    ) -> dict[str, Any]:
        rows = conn.execute(
            text(
                """
                SELECT kind FROM treatment_holds
                WHERE customer_id = :cid
                  AND released_at IS NULL
                  AND starts_at <= now()
                  AND (expires_at IS NULL OR expires_at > now())
                  AND (account_id IS NULL OR account_id = :aid)
                """
            ),
            {"cid": customer_id, "aid": account["id"] if account else None},
        ).scalars().all()
        disputes = conn.execute(
            text(
                """
                SELECT count(*)::int FROM disputes
                WHERE customer_id = :cid
                  AND status IN ('new','under_review','awaiting_customer')
                """
            ),
            {"cid": customer_id},
        ).scalar()
        return {
            "holds": tuple(sorted(set(rows))),
            "open_dispute_count": int(disputes or 0),
        }

    def _treatment_history(
        self, conn: Any, customer_id: str, now: datetime
    ) -> dict[str, Any]:
        """What this engine has already done. Its own escalation memory.

        Field visits and statutory notices have no other home in the schema
        yet, and a ladder that cannot remember it already sent someone to the
        door is not a ladder.
        """
        field_n = conn.execute(
            text(
                """
                SELECT count(*)::int FROM treatment_decisions
                WHERE customer_id = :cid AND chosen_action = 'field_visit'
                  AND enacted IS TRUE AND enacted_at >= :since
                """
            ),
            {"cid": customer_id, "since": now - timedelta(days=90)},
        ).scalar()
        legal_at = conn.execute(
            text(
                """
                SELECT enacted_at FROM treatment_decisions
                WHERE customer_id = :cid AND chosen_action = 'legal_notice'
                  AND enacted IS TRUE
                ORDER BY enacted_at DESC LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).scalar()
        return {
            "field_visits_90d": int(field_n or 0),
            "legal_notice_at": _aware(legal_at),
        }


    def _case_history(
        self, conn: Any, customer_id: str, trigger: Trigger, now: datetime
    ) -> dict[str, Any]:
        """What this engine has already tried, for *this* case.

        A case is ``(customer, trigger kind, trigger ref)``. Without a ref there
        is no case to speak of — a manual "what would you do here?" from a
        screen is a question, not an attempt — so those come back at zero rather
        than inheriting somebody else's ladder.
        """
        empty: dict[str, Any] = {
            "case_attempts": 0,
            "case_actions_tried": {},
            "case_last_action": None,
            "case_last_outcome": None,
            "hours_since_last_attempt": None,
        }
        if not trigger.ref:
            return empty
        row = conn.execute(
            text(
                """
                SELECT count(*)::int AS attempts,
                       max(enacted_at) AS last_at,
                       (array_agg(chosen_action ORDER BY enacted_at DESC, id DESC))[1]
                         AS last_action,
                       (array_agg(outcome ORDER BY enacted_at DESC, id DESC))[1]
                         AS last_outcome
                FROM treatment_decisions
                WHERE customer_id = :cid
                  AND trigger_kind = :kind
                  AND trigger_ref = :ref
                  AND enacted IS TRUE
                """
            ),
            {"cid": customer_id, "kind": trigger.kind, "ref": trigger.ref},
        ).mappings().first()
        if row is None or not row["attempts"]:
            return empty
        tried = conn.execute(
            text(
                """
                SELECT chosen_action, count(*)::int AS n
                FROM treatment_decisions
                WHERE customer_id = :cid AND trigger_kind = :kind
                  AND trigger_ref = :ref AND enacted IS TRUE
                GROUP BY chosen_action
                """
            ),
            {"cid": customer_id, "kind": trigger.kind, "ref": trigger.ref},
        ).mappings().all()
        last_at = _aware(row["last_at"])
        return {
            "case_attempts": int(row["attempts"]),
            "case_actions_tried": {
                str(r["chosen_action"]): int(r["n"]) for r in tried if r["chosen_action"]
            },
            "case_last_action": row["last_action"],
            "case_last_outcome": row["last_outcome"],
            "hours_since_last_attempt": (
                None if last_at is None else max(0.0, (now - last_at).total_seconds() / 3600.0)
            ),
        }


def build_features(
    customer_id: str,
    *,
    account_id: str | None,
    trigger: Trigger,
    now: datetime,
    provider: FeatureProvider | None = None,
    conn: Any | None = None,
) -> AccountFeatures:
    return (provider or SqlFeatureProvider()).build(
        customer_id, account_id=account_id, trigger=trigger, now=now, conn=conn
    )
