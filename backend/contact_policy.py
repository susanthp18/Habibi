"""Fail-closed cross-channel contact policy (P6).

Every outbound path calls :func:`admit` before a dial or send. ``admit`` never
raises — "no contact" is always valid, same as reco's ``recommend()``.

Purposes
--------
``statutory``  PTP confirm / payment receipt. Channel opt-out still binds.
               Hours, DND, cap, cooling-off do not block. Still *counts*.
``in_session`` Reply on a customer-initiated thread / live inbound call.
               Channel opt-out binds. Cap does not block or count.
``outreach``   Outbound dial, due reminder, doc chase, agent-initiated thread.
               Full veto: opt-out, DND, RBI 08:00–19:00 voice, allowed window,
               cooling-off, daily/weekly cap.

The daily budget is ``contact_day_counters`` locked ``FOR UPDATE`` so two
concurrent dials cannot both take slot 3. Session coalescing: one
``session_key`` per local day inside the window is one touch.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from env_utils import env_int

logger = logging.getLogger(__name__)

BLOCKING_CONSENT = frozenset({"opted_out", "dnd", "expired"})
PURPOSES = frozenset({"outreach", "statutory", "in_session"})
CHANNELS = frozenset({"voice", "whatsapp", "sms", "email", "chat", "field"})
ACTORS = frozenset({"human", "bot", "system", "agency"})

REASON_NO_CUSTOMER = "no_customer"
REASON_UNREADABLE = "consent_unreadable"
REASON_OPTED_OUT = "channel_opted_out"
REASON_CHANNEL_DND = "channel_dnd"
REASON_EXPIRED = "channel_expired"
REASON_CUSTOMER_DND = "customer_dnd"
REASON_HOURS = "outside_calling_hours"
REASON_WINDOW = "outside_allowed_window"
REASON_COOLING = "cooling_off"
REASON_DAILY = "daily_cap"
REASON_WEEKLY = "weekly_cap"

#: The fallback calling window, used when no statutory rule set is published.
#: These stay because "unregulated by the rules table" must not mean
#: "unrestricted" — a fresh install with no seed data still obeys the window.
RBI_VOICE_START = 8
RBI_VOICE_END = 19
DEFAULT_TZ = "Asia/Kolkata"
_DAY_NAME_TO_NUM = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _rules_for(conn: Any, customer: dict[str, Any] | None, at: datetime) -> Any:
    """Resolve the rule set in force at ``at`` for this customer's tenant.

    Resolution needs a tenant, and the tenant comes off the customer row — so
    this cannot run before the customer is loaded, which is why the callers
    compute their caps twice: once as a pre-customer default for the
    no-such-customer paths, and once for real.
    """
    import policy_rules

    if customer is None:
        return policy_rules.EMPTY
    return policy_rules.resolve(conn, tenant_id=customer.get("tenant_id"), at=at)


def daily_cap(rules: Any | None = None) -> int:
    """Touches per borrower per day. A published rule may only lower it.

    The environment variable is an operator's dial and the rule set is a
    regulator's or a client's; taking the minimum means neither can be used to
    escape the other, and it means this function keeps working unchanged on a
    deployment that has published no rules at all.
    """
    cap = max(1, env_int("CONTACT_DAILY_CAP", 3))
    from_rules = rules.daily_cap() if rules is not None else None
    return max(1, min(cap, from_rules)) if from_rules is not None else cap


def weekly_cap_default(rules: Any | None = None) -> int:
    cap = max(1, env_int("CONTACT_WEEKLY_CAP", 8))
    from_rules = rules.weekly_cap() if rules is not None else None
    return max(1, min(cap, from_rules)) if from_rules is not None else cap


def cooling_off(rules: Any | None = None) -> timedelta:
    minutes = max(0, env_int("CONTACT_COOLING_OFF_MINUTES", 120))
    from_rules = rules.cooling_off_minutes() if rules is not None else None
    # Maximum, not minimum: a longer gap between contacts is the stricter rule.
    if from_rules is not None:
        minutes = max(minutes, from_rules)
    return timedelta(minutes=minutes)


def session_window() -> timedelta:
    return timedelta(minutes=max(1, env_int("CONTACT_SESSION_WINDOW_MINUTES", 30)))


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None
    touch_counted: bool = False
    today_count: int = 0
    daily_cap: int = 3
    coalesced: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "touchCounted": self.touch_counted,
            "outreachToday": self.today_count,
            "dailyCap": self.daily_cap,
            "coalesced": self.coalesced,
        }


def normalize_channel(raw: str | None) -> str:
    ch = (raw or "").strip().lower()
    if ch in {"call", "voice", "pstn"}:
        return "voice"
    if ch in CHANNELS:
        return ch
    return ch or "voice"


def _event_id() -> str:
    return f"CE-{uuid.uuid4().hex[:10].upper()}"


def _zone(name: str | None) -> ZoneInfo:
    label = (name or "").strip() or DEFAULT_TZ
    try:
        return ZoneInfo(label)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_hours(raw: str | None) -> tuple[int, int] | None:
    if not raw or not str(raw).strip():
        return None
    m = re.search(r"(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})", str(raw))
    if not m:
        return None
    return int(m.group(1)), int(m.group(3))


def _parse_days(raw: str | None) -> list[int] | None:
    if not raw or not str(raw).strip():
        return None
    text_val = str(raw).strip().lower()
    if "-" in text_val and "," not in text_val:
        parts = [p.strip() for p in text_val.split("-", 1)]
        if len(parts) == 2 and parts[0][:3] in _DAY_NAME_TO_NUM and parts[1][:3] in _DAY_NAME_TO_NUM:
            start, end = _DAY_NAME_TO_NUM[parts[0][:3]], _DAY_NAME_TO_NUM[parts[1][:3]]
            if start <= end:
                return list(range(start, end + 1))
            return list(range(start, 7)) + list(range(0, end + 1))
    days: list[int] = []
    for token in re.split(r"[,\s]+", text_val):
        key = token[:3]
        if key in _DAY_NAME_TO_NUM:
            days.append(_DAY_NAME_TO_NUM[key])
    return days or None


#: Public names for the two consent-window parsers. The treatment engine plans
#: *when* to act and has to see the same window this module vetoes against; a
#: second parser that agreed with these on Tuesday is one that disagrees in
#: November.
parse_allowed_hours = _parse_hours
parse_allowed_days = _parse_days


def _consent_reason(status: str) -> str:
    if status == "dnd":
        return REASON_CHANNEL_DND
    if status == "expired":
        return REASON_EXPIRED
    return REASON_OPTED_OUT


def _load_customer(conn: Any, customer_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id, c.dnd, c.timezone,
                   cr.allowed_days, cr.allowed_hours, cr.dnd_registry, cr.expires_at
            FROM customers c
            LEFT JOIN consent_records cr ON cr.customer_id = c.id
            WHERE c.id = :id
            """
        ),
        {"id": customer_id},
    ).mappings().first()
    return dict(row) if row else None


def _channel_status(conn: Any, customer_id: str, channel: str) -> str | None:
    import capture

    by_ch = capture.latest_consent_by_channel(conn, customer_id)
    return by_ch.get(channel) or by_ch.get("voice" if channel == "call" else channel)


def _weekly_cap_for(
    conn: Any, customer_id: str, channel: str, rules: Any | None = None
) -> int:
    row = conn.execute(
        text(
            """
            SELECT cc.weekly_frequency_cap
            FROM channel_consents cc
            JOIN consent_records cr ON cr.id = cc.consent_id
            WHERE cr.customer_id = :cid AND cc.channel = :ch
            ORDER BY cc.captured_at DESC NULLS LAST
            LIMIT 1
            """
        ),
        {"cid": customer_id, "ch": channel},
    ).mappings().first()
    consented = (
        max(1, int(row["weekly_frequency_cap"]))
        if row and row["weekly_frequency_cap"] is not None
        else None
    )
    from_rules = rules.weekly_cap(channel) if rules is not None else None
    # The borrower's own stated preference and the published rule are both
    # ceilings, so the effective cap is whichever is lower. A borrower who asked
    # for at most two messages a week gets two even where policy permits eight.
    candidates = [c for c in (consented, from_rules) if c is not None]
    return min(candidates) if candidates else weekly_cap_default(rules)


def _today_count(conn: Any, customer_id: str, local_date: Any) -> int:
    row = conn.execute(
        text(
            """
            SELECT outreach_sessions
            FROM contact_day_counters
            WHERE customer_id = :cid AND local_date = :d
            """
        ),
        {"cid": customer_id, "d": local_date},
    ).mappings().first()
    return int(row["outreach_sessions"] or 0) if row else 0


def _week_counted(conn: Any, customer_id: str, channel: str, *, now: datetime, tz: ZoneInfo) -> int:
    local = now.astimezone(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    start_utc = start.astimezone(timezone.utc)
    row = conn.execute(
        text(
            """
            SELECT count(*) AS n
            FROM contact_events
            WHERE customer_id = :cid
              AND channel = :ch
              AND outcome = 'allowed'
              AND touch_counted
              AND occurred_at >= :start
            """
        ),
        {"cid": customer_id, "ch": channel, "start": start_utc},
    ).mappings().first()
    return int(row["n"] or 0) if row else 0


def _session_coalesced(
    conn: Any,
    *,
    customer_id: str,
    session_key: str | None,
    now: datetime,
) -> bool:
    if not session_key:
        return False
    cutoff = now - session_window()
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM contact_events
            WHERE customer_id = :cid
              AND session_key = :sk
              AND outcome = 'allowed'
              AND occurred_at >= :cutoff
            LIMIT 1
            """
        ),
        {"cid": customer_id, "sk": session_key, "cutoff": cutoff},
    ).fetchone()
    return row is not None


def _already_counted_related(
    conn: Any,
    *,
    customer_id: str,
    source: str | None,
    related_id: str | None,
) -> bool:
    if not source or not related_id:
        return False
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM contact_events
            WHERE customer_id = :cid
              AND source = :src
              AND related_id = :rid
              AND outcome = 'allowed'
              AND touch_counted
            LIMIT 1
            """
        ),
        {"cid": customer_id, "src": source, "rid": related_id},
    ).fetchone()
    return row is not None


def _last_counted_at(conn: Any, customer_id: str) -> datetime | None:
    row = conn.execute(
        text(
            """
            SELECT occurred_at
            FROM contact_events
            WHERE customer_id = :cid
              AND outcome = 'allowed'
              AND touch_counted
            ORDER BY occurred_at DESC
            LIMIT 1
            """
        ),
        {"cid": customer_id},
    ).mappings().first()
    if not row or row["occurred_at"] is None:
        return None
    return _aware(row["occurred_at"])


def _veto(
    *,
    purpose: str,
    channel: str,
    customer: dict[str, Any] | None,
    status: str | None,
    now_local: datetime,
    rules: Any | None = None,
) -> str | None:
    if customer is None:
        return REASON_NO_CUSTOMER if purpose == "outreach" else None

    if status in BLOCKING_CONSENT:
        return _consent_reason(status)

    if purpose == "in_session":
        return None

    if purpose == "outreach" and (customer.get("dnd") or customer.get("dnd_registry")):
        return REASON_CUSTOMER_DND

    if purpose == "outreach":
        # A published window applies to whatever channel it names. Absent one,
        # only voice is bounded — which is the rule this module shipped with and
        # the behaviour every existing caller depends on.
        window = rules.calling_window(channel) if rules is not None else None
        if window is None and channel == "voice":
            window = (RBI_VOICE_START, RBI_VOICE_END)
        if window is not None:
            start_h, end_h = window
            if now_local.hour < start_h or now_local.hour >= end_h:
                return REASON_HOURS

    if purpose == "outreach":
        hours = _parse_hours(customer.get("allowed_hours"))
        days = _parse_days(customer.get("allowed_days"))
        if hours is not None:
            start_h, end_h = hours
            if now_local.hour < start_h or now_local.hour >= end_h:
                return REASON_WINDOW
        if days is not None:
            # Consent days: 0=Sun … 6=Sat. isoweekday()%7 matches that.
            if (now_local.isoweekday() % 7) not in days:
                return REASON_WINDOW
    return None


def evaluate(
    conn: Any,
    *,
    customer_id: str | None,
    channel: str,
    purpose: str = "outreach",
    session_key: str | None = None,
    now: datetime | None = None,
) -> Decision:
    """Dry-run. No writes. Used by the UI and later as a P3 veto."""
    cap = daily_cap()
    purpose = purpose if purpose in PURPOSES else "outreach"
    channel = normalize_channel(channel)
    cid = (customer_id or "").strip()
    if not cid:
        if purpose == "outreach":
            return Decision(False, REASON_NO_CUSTOMER, daily_cap=cap)
        return Decision(True, daily_cap=cap)

    try:
        customer = _load_customer(conn, cid)
        instant = _aware(now or datetime.now(timezone.utc))
        tz = _zone((customer or {}).get("timezone"))
        local = instant.astimezone(tz)
        # Resolved at the instant being asked about, not at "now": this function
        # is also the scheduling gate, and a slot next January must be judged
        # against the rules that will be in force then.
        rules = _rules_for(conn, customer, instant)
        cap = daily_cap(rules)
        status = _channel_status(conn, cid, channel) if customer else None
        reason = _veto(
            purpose=purpose,
            channel=channel,
            customer=customer,
            status=status,
            now_local=local,
            rules=rules,
        )
        today = _today_count(conn, cid, local.date()) if customer else 0
        if reason:
            return Decision(False, reason, today_count=today, daily_cap=cap)
        coalesced = _session_coalesced(conn, customer_id=cid, session_key=session_key, now=instant)
        if coalesced or purpose == "in_session":
            return Decision(True, today_count=today, daily_cap=cap, coalesced=coalesced)
        if purpose == "outreach":
            last = _last_counted_at(conn, cid)
            cool = cooling_off(rules)
            if cool.total_seconds() > 0 and last is not None and instant - last < cool:
                return Decision(False, REASON_COOLING, today_count=today, daily_cap=cap)
            if today >= cap:
                return Decision(False, REASON_DAILY, today_count=today, daily_cap=cap)
            week_n = _week_counted(conn, cid, channel, now=instant, tz=tz)
            if week_n >= _weekly_cap_for(conn, cid, channel, rules):
                return Decision(False, REASON_WEEKLY, today_count=today, daily_cap=cap)
        return Decision(True, today_count=today, daily_cap=cap)
    except Exception:
        logger.exception("contact_policy.evaluate failed customer=%s", cid)
        if purpose == "outreach":
            return Decision(False, REASON_UNREADABLE, daily_cap=cap)
        return Decision(True, daily_cap=cap)


# Reasons that are properties of the customer and the clock, and are therefore
# knowable about a *future* moment. The volume limits — cooling_off, daily_cap,
# weekly_cap — are counted against today's touches, so asking them about a slot
# next Tuesday answers a question nobody asked. Those stay where they belong:
# at send time, in the callers that actually dispatch.
SCHEDULING_VETOES = frozenset(
    {
        REASON_NO_CUSTOMER,
        REASON_UNREADABLE,
        REASON_OPTED_OUT,
        REASON_CHANNEL_DND,
        REASON_EXPIRED,
        REASON_CUSTOMER_DND,
        REASON_HOURS,
        REASON_WINDOW,
    }
)


def blocks_scheduling(
    conn: Any,
    *,
    customer_id: str | None,
    channel: str,
    at: datetime,
) -> str | None:
    """Why a contact must not be *booked* for ``at``, or None if it may be.

    Booking is not contacting, so this reserves nothing and writes nothing.
    What it stops is a diary entry that could only ever be honoured by breaking
    the rules — a voice follow-up at 03:00 against RBI's 08:00–19:00 window, or
    any touch at all on a channel the customer has opted out of. Scheduling
    those and discovering it at dial time makes the agent the one who finds out.

    Never raises: an unreadable consent table is itself a veto (fail closed),
    the same way it is in :func:`evaluate`.
    """
    decision = evaluate(
        conn, customer_id=customer_id, channel=channel, purpose="outreach", now=at
    )
    if decision.allowed:
        return None
    reason = decision.reason
    return reason if reason in SCHEDULING_VETOES else None


def _insert_event(
    conn: Any,
    *,
    customer: dict[str, Any],
    channel: str,
    purpose: str,
    actor_kind: str,
    actor_user_id: str | None,
    outcome: str,
    reason: str | None,
    session_key: str | None,
    source: str | None,
    related_id: str | None,
    touch_counted: bool,
    account_id: str | None,
    occurred_at: datetime,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO contact_events (
              id, tenant_id, customer_id, account_id, channel, direction,
              purpose, actor_kind, actor_user_id, outcome, reason,
              session_key, source, related_id, touch_counted, occurred_at
            ) VALUES (
              :id, :tenant_id, :customer_id, :account_id, :channel, 'outbound',
              :purpose, :actor_kind, :actor_user_id, :outcome, :reason,
              :session_key, :source, :related_id, :touch_counted, :occurred_at
            )
            """
        ),
        {
            "id": _event_id(),
            "tenant_id": customer["tenant_id"],
            "customer_id": customer["id"],
            "account_id": account_id,
            "channel": channel,
            "purpose": purpose,
            "actor_kind": actor_kind if actor_kind in ACTORS else "system",
            "actor_user_id": actor_user_id,
            "outcome": outcome,
            "reason": reason,
            "session_key": session_key,
            "source": source,
            "related_id": related_id,
            "touch_counted": touch_counted,
            "occurred_at": occurred_at,
        },
    )


def _reserve_day(conn: Any, customer_id: str, local_date: Any, cap: int) -> tuple[bool, int]:
    """Lock the day row and increment if under cap. Returns (ok, count_after)."""
    conn.execute(
        text(
            """
            INSERT INTO contact_day_counters (customer_id, local_date, outreach_sessions)
            VALUES (:cid, :d, 0)
            ON CONFLICT (customer_id, local_date) DO NOTHING
            """
        ),
        {"cid": customer_id, "d": local_date},
    )
    row = conn.execute(
        text(
            """
            SELECT outreach_sessions
            FROM contact_day_counters
            WHERE customer_id = :cid AND local_date = :d
            FOR UPDATE
            """
        ),
        {"cid": customer_id, "d": local_date},
    ).mappings().first()
    current = int(row["outreach_sessions"] or 0) if row else 0
    if current >= cap:
        return False, current
    conn.execute(
        text(
            """
            UPDATE contact_day_counters
            SET outreach_sessions = outreach_sessions + 1
            WHERE customer_id = :cid AND local_date = :d
            """
        ),
        {"cid": customer_id, "d": local_date},
    )
    return True, current + 1


def _refresh_used_this_week(conn: Any, customer_id: str, channel: str, tz: ZoneInfo) -> None:
    local = datetime.now(tz)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    n = conn.execute(
        text(
            """
            SELECT count(*)::int AS n
            FROM contact_events
            WHERE customer_id = :cid
              AND channel = :ch
              AND outcome = 'allowed'
              AND touch_counted
              AND occurred_at >= :start
            """
        ),
        {"cid": customer_id, "ch": channel, "start": start.astimezone(timezone.utc)},
    ).scalar()
    conn.execute(
        text(
            """
            UPDATE channel_consents cc
            SET used_this_week = :n
            FROM consent_records cr
            WHERE cc.consent_id = cr.id
              AND cr.customer_id = :cid
              AND cc.channel = :ch
            """
        ),
        {"cid": customer_id, "ch": channel, "n": int(n or 0)},
    )


def admit(
    conn: Any,
    *,
    customer_id: str | None,
    channel: str,
    purpose: str = "outreach",
    session_key: str | None = None,
    source: str | None = None,
    related_id: str | None = None,
    actor_kind: str = "system",
    actor_user_id: str | None = None,
    account_id: str | None = None,
    now: datetime | None = None,
) -> Decision:
    """Evaluate, reserve, log. Never raises."""
    cap = daily_cap()
    purpose = purpose if purpose in PURPOSES else "outreach"
    channel = normalize_channel(channel)
    cid = (customer_id or "").strip()
    instant = _aware(now or datetime.now(timezone.utc))

    if not cid:
        if purpose == "outreach":
            return Decision(False, REASON_NO_CUSTOMER, daily_cap=cap)
        return Decision(True, daily_cap=cap)

    try:
        customer = _load_customer(conn, cid)
        if customer is None:
            if purpose == "outreach":
                return Decision(False, REASON_NO_CUSTOMER, daily_cap=cap)
            return Decision(True, daily_cap=cap)

        tz = _zone(customer.get("timezone"))
        local = instant.astimezone(tz)
        rules = _rules_for(conn, customer, instant)
        cap = daily_cap(rules)
        status = _channel_status(conn, cid, channel)
        reason = _veto(
            purpose=purpose,
            channel=channel,
            customer=customer,
            status=status,
            now_local=local,
            rules=rules,
        )
        today = _today_count(conn, cid, local.date())

        def _deny(why: str, count: int = today) -> Decision:
            _insert_event(
                conn,
                customer=customer,
                channel=channel,
                purpose=purpose,
                actor_kind=actor_kind,
                actor_user_id=actor_user_id,
                outcome="denied",
                reason=why,
                session_key=session_key,
                source=source,
                related_id=related_id,
                touch_counted=False,
                account_id=account_id,
                occurred_at=instant,
            )
            return Decision(False, why, today_count=count, daily_cap=cap)

        if reason:
            return _deny(reason)

        coalesced = _session_coalesced(conn, customer_id=cid, session_key=session_key, now=instant)
        related_done = _already_counted_related(
            conn, customer_id=cid, source=source, related_id=related_id
        )
        counts = purpose in {"outreach", "statutory"} and not coalesced and not related_done

        if purpose == "outreach" and counts:
            last = _last_counted_at(conn, cid)
            cool = cooling_off(rules)
            if cool.total_seconds() > 0 and last is not None and instant - last < cool:
                return _deny(REASON_COOLING)
            week_n = _week_counted(conn, cid, channel, now=instant, tz=tz)
            if week_n >= _weekly_cap_for(conn, cid, channel, rules):
                return _deny(REASON_WEEKLY)
            ok, after = _reserve_day(conn, cid, local.date(), cap)
            if not ok:
                return _deny(REASON_DAILY, after)
            today = after
        elif purpose == "statutory" and counts:
            # Statutory is never blocked by the cap, but it consumes a slot so
            # later outreach the same day is.
            _, after = _reserve_day(conn, cid, local.date(), cap + 10_000)
            today = after

        _insert_event(
            conn,
            customer=customer,
            channel=channel,
            purpose=purpose,
            actor_kind=actor_kind,
            actor_user_id=actor_user_id,
            outcome="allowed",
            reason=None,
            session_key=session_key,
            source=source,
            related_id=related_id,
            touch_counted=bool(counts),
            account_id=account_id,
            occurred_at=instant,
        )
        if counts:
            nested = conn.begin_nested()
            try:
                _refresh_used_this_week(conn, cid, channel, tz)
                nested.commit()
            except Exception:
                nested.rollback()
                logger.exception("used_this_week cache refresh failed customer=%s", cid)
        return Decision(
            True,
            touch_counted=bool(counts),
            today_count=today,
            daily_cap=cap,
            coalesced=coalesced,
        )
    except Exception:
        logger.exception("contact_policy.admit failed customer=%s", cid)
        if purpose == "outreach":
            return Decision(False, REASON_UNREADABLE, daily_cap=cap)
        return Decision(True, daily_cap=cap)


def require_admit(conn: Any, **kwargs: Any) -> Decision:
    """:func:`admit` that raises ``ValueError(reason)`` on deny — HTTP 409 path."""
    decision = admit(conn, **kwargs)
    if not decision.allowed:
        raise ValueError(decision.reason or REASON_UNREADABLE)
    return decision


def ledger_usage(conn: Any, customer_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Batch used-this-week / today / last-deny for the Consent list."""
    if not customer_ids:
        return {}
    cap = daily_cap()
    week_rows = conn.execute(
        text(
            """
            SELECT customer_id, channel, count(*) AS n
            FROM contact_events
            WHERE customer_id = ANY(:ids)
              AND outcome = 'allowed'
              AND touch_counted
              AND occurred_at >= (now() - interval '7 days')
            GROUP BY customer_id, channel
            """
        ),
        {"ids": customer_ids},
    ).mappings().all()
    today_rows = conn.execute(
        text(
            """
            SELECT c.customer_id, c.outreach_sessions
            FROM contact_day_counters c
            WHERE c.customer_id = ANY(:ids)
              AND c.local_date = (
                SELECT (now() AT TIME ZONE COALESCE(cu.timezone, 'Asia/Kolkata'))::date
                FROM customers cu WHERE cu.id = c.customer_id
              )
            """
        ),
        {"ids": customer_ids},
    ).mappings().all()
    deny_rows = conn.execute(
        text(
            """
            SELECT DISTINCT ON (customer_id) customer_id, reason
            FROM contact_events
            WHERE customer_id = ANY(:ids) AND outcome = 'denied'
            ORDER BY customer_id, occurred_at DESC
            """
        ),
        {"ids": customer_ids},
    ).mappings().all()
    out: dict[str, dict[str, Any]] = {
        cid: {"byChannel": {}, "outreachToday": 0, "dailyCap": cap, "lastDecisionReason": None}
        for cid in customer_ids
    }
    for r in week_rows:
        out[r["customer_id"]]["byChannel"][r["channel"]] = int(r["n"] or 0)
    for r in today_rows:
        out[r["customer_id"]]["outreachToday"] = int(r["outreach_sessions"] or 0)
    for r in deny_rows:
        out[r["customer_id"]]["lastDecisionReason"] = r["reason"]
    return out
