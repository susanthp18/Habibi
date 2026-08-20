"""*When*, not just what.

A collections engine that only answers "which channel" has answered half the
question. The roadmap's whole thesis is that the profit lever is delay: a
borrower contacted at 09:00 tomorrow and the same borrower contacted at 20:00
tonight are different bets, and an SMS timed two hours after a salary credit is
a different bet again from the same SMS on the 3rd of the month.

So every candidate action is planned to an instant, and the instant feeds back
into the score through :func:`scoring.urgency_decay`. That is what lets
"WhatsApp now" beat "agent call at 08:00 tomorrow" without either of them being
special-cased.

Everything here is pure arithmetic over the feature vector — no database. The
one authoritative feasibility check is the single
``contact_policy.evaluate(now=at)`` in :mod:`policy`, run against the instant
this module picked. Planning locally and verifying once is what keeps a
72-hour horizon from becoming 72 round trips per action.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent_core.treatment import actions as A
from agent_core.treatment.features import AccountFeatures, zone

#: RBI DOR.ORG.REC.65/21.04.158/2022-23: no recovery call before 08:00 or after
#: 19:00. Mirrored from contact_policy rather than re-decided.
from contact_policy import RBI_VOICE_END, RBI_VOICE_START  # noqa: E402

#: Hours after a salary credit at which the account balance is still intact.
#: Finezza: salary-credited accounts peak within ~48h of credit; two hours is
#: long enough for the credit to clear and short enough to beat the borrower's
#: own standing instructions.
SALARY_CREDIT_LAG_HOURS = 2

#: Longer than the message lag, and for a different reason. A pay-link only has
#: to arrive while the borrower is looking at their phone; a debit has to be
#: submitted to a rail, batched, and presented against a balance that must
#: still be there when it lands. Six hours puts the presentation comfortably
#: inside the same banking day as the credit.
CREDIT_SETTLE_LAG_HOURS = 6

#: Local hour at which a presentment is submitted. Rails batch by cut-off, so
#: this is about landing in the day's file rather than about the borrower.
PRESENTMENT_HOUR = 9

#: A field visit needs a day's notice under the reported 2027 directions, and
#: nobody is home at 08:00.
FIELD_NOTICE_HOURS = 24
FIELD_VISIT_HOUR = 10

#: Sunday. Not a calling day for field work, and a poor one for dunning calls.
_SUNDAY = 0


@dataclass(frozen=True)
class Slot:
    """A planned instant, or the reason there isn't one."""

    at: datetime | None
    rationale: str

    @property
    def feasible(self) -> bool:
        return self.at is not None


def _local_day_index(moment: datetime) -> int:
    """0=Sun … 6=Sat, matching the consent-record convention."""
    return moment.isoweekday() % 7


def _window_for(action: str, features: AccountFeatures) -> tuple[int, int]:
    """The [start, end) local-hour window this action may land in.

    Voice intersects RBI's statutory window with the borrower's consented one.
    Digital is bound only by consent: an SMS at 21:00 is not a recovery call,
    and forcing it into the voice window would push a pay-link past the moment
    the borrower was actually looking at their phone.
    """
    consented = features.allowed_hours
    if A.spec(action).channel == "voice":
        start, end = RBI_VOICE_START, RBI_VOICE_END
        if consented:
            start = max(start, consented[0])
            end = min(end, consented[1])
        return start, end
    if consented:
        return consented
    return 0, 24


def _first_instant_in_window(
    start_from: datetime,
    *,
    tz: ZoneInfo,
    window: tuple[int, int],
    days: tuple[int, ...] | None,
    horizon: timedelta,
) -> datetime | None:
    """Earliest instant at or after ``start_from`` inside the window.

    Walks hour by hour rather than solving in closed form: the window can be
    empty (a consent record narrower than RBI's), the allowed days can be an
    arbitrary set, and DST transitions make "add 24 hours" the wrong step in
    two time zones a year. A bounded loop over at most a few dozen iterations
    is cheaper than being subtly wrong.
    """
    start_h, end_h = window
    if start_h >= end_h:
        return None
    deadline = start_from + horizon
    cursor = start_from
    # Round up to the next hour boundary only when we have to move at all;
    # "now" must stay eligible so an immediately-feasible action is not
    # gratuitously delayed by up to an hour.
    for _ in range(int(horizon.total_seconds() // 3600) + 48):
        if cursor > deadline:
            return None
        local = cursor.astimezone(tz)
        day_ok = days is None or _local_day_index(local) in days
        if day_ok and start_h <= local.hour < end_h:
            return cursor
        # Jump straight to the window's opening rather than crawling: from
        # 02:00 to an 08:00 window is one step, not six.
        nxt = local.replace(minute=0, second=0, microsecond=0)
        if local.hour < start_h and day_ok:
            nxt = nxt.replace(hour=start_h)
        else:
            nxt = (nxt + timedelta(days=1)).replace(hour=start_h)
        cursor = nxt.astimezone(cursor.tzinfo)
    return None


def plan(
    action: str,
    features: AccountFeatures,
    *,
    now: datetime,
    horizon_hours: int,
) -> Slot:
    """When this action should happen, and one line of why."""
    if action == A.WAIT:
        return Slot(now, "no contact planned")

    tz = zone(features.timezone_name)
    horizon = timedelta(hours=max(1, horizon_hours))

    if action == A.LEGAL_NOTICE:
        # A statutory demand is served, not dialled. It is bound by a deadline,
        # not by a calling window, and deferring it to a convenient hour is how
        # a limitation period is missed.
        return Slot(now, "statutory clock, not a calling window")

    if action == A.EMI_DATE_CHANGE:
        # Nobody is contacted and nothing is dialled: this is a change to the
        # account's own schedule. It has no window to wait for, and delaying it
        # only costs another cycle of the mismatch it exists to fix.
        return Slot(now, "self-service change, no contact window applies")

    if action == A.REPRESENT_MANDATE:
        return _plan_representment(features, now=now, tz=tz, horizon=horizon)

    if action == A.FIELD_VISIT:
        earliest = now + timedelta(hours=FIELD_NOTICE_HOURS)
        local = earliest.astimezone(tz).replace(
            minute=0, second=0, microsecond=0
        )
        if local.hour > FIELD_VISIT_HOUR:
            local = (local + timedelta(days=1)).replace(hour=FIELD_VISIT_HOUR)
        else:
            local = local.replace(hour=FIELD_VISIT_HOUR)
        while _local_day_index(local) == _SUNDAY:
            local = local + timedelta(days=1)
        at = local.astimezone(now.tzinfo)
        if at - now > horizon:
            return Slot(None, "no visit slot inside the planning horizon")
        return Slot(at, "next working day, one day's notice given")

    window = _window_for(action, features)
    days = features.allowed_days
    earliest = now
    rationale = "next feasible moment"

    # Salary-credit timing. Retrying against the credit rather than the
    # calendar is the single highest-yield timing decision in the early
    # buckets, and it only makes sense when the bounce was about money not
    # being there.
    credit = features.next_credit_at
    if (
        credit is not None
        and credit > now
        and credit - now <= horizon
        and features.bounce_reason in {"insufficient_funds", None}
        and features.open_bounce_id
    ):
        earliest = credit + timedelta(hours=SALARY_CREDIT_LAG_HOURS)
        rationale = "shortly after the expected salary credit"

    at = _first_instant_in_window(
        earliest, tz=tz, window=window, days=days, horizon=horizon
    )
    if at is None:
        return Slot(None, "no consented slot inside the planning horizon")

    # Voice only: prefer an hour this borrower has actually answered at. A
    # missed opportunity costs a slightly later dial; guessing costs a dial.
    if A.spec(action).channel == "voice" and features.responsive_hours:
        preferred = _first_responsive(
            at,
            tz=tz,
            window=window,
            days=days,
            hours=features.responsive_hours,
            horizon=horizon - (at - now),
        )
        if preferred is not None:
            return Slot(preferred, "an hour this borrower has answered before")

    if rationale == "next feasible moment" and at > now:
        rationale = "first moment inside the consented calling window"
    return Slot(at, rationale)


def _plan_representment(
    features: AccountFeatures,
    *,
    now: datetime,
    tz: ZoneInfo,
    horizon: timedelta,
) -> Slot:
    """When to submit the mandate again — and whether to submit it at all.

    This is the one action whose timing *is* the intervention. Re-presenting a
    debit against an account that bounced for insufficient funds, on a calendar
    rule rather than against the borrower's salary credit, fails for the same
    reason it failed the first time — and every failed presentation costs a
    bounce charge the borrower pays and resents.

    So the return code decides the schedule:

    * **technical**, or a mandate that has never returned — nothing to wait
      for. The money was there; the rail was not. Submit now.
    * **insufficient funds** (or an unknown code, treated the same way out of
      caution) — wait for money to arrive. The salary-credit hint if we have
      one, the mandate's own debit day if we do not.
    * neither hint available — **no slot**. Declining to guess is the decision:
      a blind retry into an account we have no reason to think has been funded
      is a fee, not a collection.
    """
    reason = (features.mandate_last_return_reason or features.bounce_reason or "").lower()

    if reason in {"technical", ""}:
        return Slot(now, "bank-side return, nothing to wait for")

    credit = features.next_credit_at
    if credit is not None and credit > now:
        at = credit + timedelta(hours=CREDIT_SETTLE_LAG_HOURS)
        if at - now <= horizon:
            return Slot(at, "timed to land just after the expected salary credit")
        return Slot(None, "salary credit falls outside the planning horizon")

    if features.mandate_debit_day:
        at = _next_debit_instant(features.mandate_debit_day, now=now, tz=tz)
        if at is not None and at - now <= horizon:
            return Slot(at, "the mandate's own presentment day")
        return Slot(None, "next presentment day falls outside the planning horizon")

    return Slot(
        None,
        "no salary-credit or presentment-day signal — a blind retry would only earn a fee",
    )


def _next_debit_instant(debit_day: int, *, now: datetime, tz: ZoneInfo) -> datetime | None:
    """The next occurrence of this day-of-month, in the borrower's zone.

    Clamped rather than skipped: a mandate registered for the 31st presents on
    the last day of February, because that is what the rail does and a
    scheduler that quietly drops two months a year is worse than one that
    rounds.
    """
    local = now.astimezone(tz)
    for month_offset in (0, 1, 2):
        year = local.year + (local.month - 1 + month_offset) // 12
        month = (local.month - 1 + month_offset) % 12 + 1
        last = monthrange(year, month)[1]
        try:
            candidate = local.replace(
                year=year,
                month=month,
                day=min(int(debit_day), last),
                hour=PRESENTMENT_HOUR,
                minute=0,
                second=0,
                microsecond=0,
            )
        except ValueError:
            continue
        if candidate > local:
            return candidate.astimezone(now.tzinfo)
    return None


def _first_responsive(
    start_from: datetime,
    *,
    tz: ZoneInfo,
    window: tuple[int, int],
    days: tuple[int, ...] | None,
    hours: tuple[int, ...],
    horizon: timedelta,
) -> datetime | None:
    if horizon.total_seconds() <= 0:
        return None
    eligible = {h for h in hours if window[0] <= h < window[1]}
    if not eligible:
        return None
    deadline = start_from + horizon
    cursor = start_from
    for _ in range(int(horizon.total_seconds() // 3600) + 2):
        if cursor > deadline:
            return None
        local = cursor.astimezone(tz)
        if (days is None or _local_day_index(local) in days) and local.hour in eligible:
            return cursor
        cursor = (
            local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        ).astimezone(cursor.tzinfo)
    return None
