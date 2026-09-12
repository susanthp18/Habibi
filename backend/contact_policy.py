"""Fail-closed cross-channel contact policy (P6).

Every outbound path calls :func:`admit` before a dial or send. ``admit`` never
raises — "no contact" is always valid, same as reco's ``recommend()``.

Purposes
--------
``statutory``  PTP confirm / payment receipt. Channel opt-out still binds.
               Hours, DND, window, endpoint, consent overlay, and suppression
               bind; the send is deferred to the next lawful instant. Cap and
               fatigue stay exempt. Still *counts*.
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
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import text

from agent_core.clock import as_utc
from agent_core import clock

import contact_window
import policy_rules
from env_utils import env_int
from agent_core.clock import utc_now

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
#: Nothing is owed. Cadence kept dialling a cured borrower: no refusal
#: existed for "paid", so a ladder ran to exhaustion on someone with a zero
#: balance. Outreach only -- a statutory notice to a settled account is
#: still owed (a closure letter is one).
REASON_SETTLED = "settled"
#: DPDP purpose limitation. The number was collected to service a loan; using it
#: to sell something is a different purpose and needs its own consent basis.
#: Absence of that basis is a refusal, not a fallback to the servicing one.
REASON_NO_PROMO_CONSENT = "no_promotional_consent"
REASON_SUPPRESSED = "suppressed"
REASON_ENDPOINT = "endpoint_unverified"
REASON_CONSENT_OVERLAY = "consent_withdrawn"
REASON_EXPIRED_CONSENT = "consent_expired"
REASON_NO_ENDPOINT = "endpoint_missing"
REASON_WINDOW_DEFERRED_STATUTORY = "window_deferred_statutory"

#: The DPDP purposes a contact can be made for. Deliberately a different axis
#: from :data:`PURPOSES` — that one is *why we may contact now* (outreach vs a
#: statutory notice vs a reply inside a live session), this one is *what the
#: data is being used for*. They are both called "purpose" in their respective
#: source documents and conflating them would be easy, so the parameter here is
#: named ``data_purpose`` everywhere it appears.
DATA_PURPOSES = frozenset({"servicing", "promotional"})

#: The fallback calling window, owned by ``policy_rules.STATUTORY_VOICE_WINDOW``
#: and read here under the names this module has always exported.
RBI_VOICE_START, RBI_VOICE_END = policy_rules.STATUTORY_VOICE_WINDOW
DEFAULT_TZ = clock.DEFAULT_TIMEZONE
_DAY_NAME_TO_NUM = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def _rules_for(
    conn: Any,
    customer: dict[str, Any] | None,
    at: datetime,
    product_id: str | None = None,
) -> Any:
    """Resolve the rule set in force at ``at`` for this customer's tenant.

    Resolution needs a tenant, and the tenant comes off the customer row — so
    this cannot run before the customer is loaded, which is why the callers
    compute their caps twice: once as a pre-customer default for the
    no-such-customer paths, and once for real.
    """
    import policy_rules

    if customer is None:
        return policy_rules.EMPTY
    return policy_rules.resolve(
        conn,
        tenant_id=customer.get("tenant_id"),
        at=at,
        product_id=product_id or customer.get("product_id"),
    )


def daily_cap(rules: Any | None = None, card_cap: int | None = None) -> int:
    """Touches per borrower per day. A published rule may only lower it.

    The environment variable is an operator's dial and the rule set is a
    regulator's or a client's; taking the minimum means neither can be used to
    escape the other, and it means this function keeps working unchanged on a
    deployment that has published no rules at all.

    ``card_cap`` is a mission's ``cadence.per_day``. It lowers the cap for
    that dial and never raises it -- the field's docstring promised this and
    nothing read it.
    """
    cap = max(1, env_int("CONTACT_DAILY_CAP", 3))
    from_rules = rules.daily_cap() if rules is not None else None
    if from_rules is not None:
        cap = min(cap, from_rules)
    if card_cap is not None:
        cap = min(cap, int(card_cap))
    return max(1, cap)


def tenant_daily_cap(product_id: str | None = None) -> int:
    """The cap in force for the current tenant's published rules.

    The editor's vocabulary and G-OB3 quoted `daily_cap()` -- the env dial
    alone -- so both could be wrong in the permissive direction for a tenant
    whose rule set lowers it."""
    import db
    import policy_rules

    try:
        with db.engine.connect() as conn:
            rules = policy_rules.resolve(conn, tenant_id=db.current_tenant(), product_id=product_id)
    except Exception:
        rules = None
    return daily_cap(rules)


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


#: Refusals that are a property of the clock: they stop being true on their own,
#: at a moment we can name. A caller holding one of these has been told *not
#: yet*, not *no*.
#:
#: This distinction had no representation, and one caller paid for it:
#: `whatsapp_outbound` handed every refusal to `mark_failed_or_retry`, a
#: function whose classifiers only understand Meta transport errors. A
#: `cooling_off` verdict matched none of them, fell through to "attempt >= cap"
#: and dead-lettered. Cooling-off is 120 *minutes*; that ladder is five attempts
#: with the backoff capped at 120 *seconds*. It could not survive to the retry
#: that would have worked, and 18 of 29 outbound messages died this way.
CLOCK_REFUSALS = frozenset(
    {
        REASON_COOLING,
        REASON_DAILY,
        REASON_WEEKLY,
        REASON_HOURS,
        REASON_WINDOW,
        REASON_WINDOW_DEFERRED_STATUTORY,
    }
)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None
    touch_counted: bool = False
    today_count: int = 0
    daily_cap: int = 3
    coalesced: bool = False
    policy_binding: tuple[dict[str, Any], ...] = ()
    policy_binding_hash: str | None = None
    #: When this refusal stops being true, for the clock-shaped reasons. None
    #: for a refusal that is a property of the customer — a DND flag or a
    #: withdrawn consent does not expire, and a caller must not retry it.
    next_allowed_at: datetime | None = None

    @property
    def deferrable(self) -> bool:
        """True when the honest response is to reschedule rather than fail."""
        return (
            not self.allowed
            and self.reason in CLOCK_REFUSALS
            and self.next_allowed_at is not None
        )

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "allowed": self.allowed,
            "reason": self.reason,
            "touchCounted": self.touch_counted,
            "outreachToday": self.today_count,
            "dailyCap": self.daily_cap,
            "coalesced": self.coalesced,
        }
        if self.next_allowed_at is not None:
            payload["nextAllowedAt"] = self.next_allowed_at.isoformat()
        if self.policy_binding_hash:
            payload["policyBindingHash"] = self.policy_binding_hash
            payload["policyBinding"] = list(self.policy_binding)
        return payload


def chosen_phone(customer: Mapping[str, Any] | None, *, slot: str | None = None) -> str | None:
    """The named endpoint. Never falls through from primary to alt."""
    if not customer:
        return None
    if slot == "alt":
        return str(customer.get("phone_alt") or "").strip() or None
    return str(customer.get("phone_primary") or "").strip() or None


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
    return clock.zone(name)


def safe_tz_sql(expr: str = "c.timezone") -> str:
    """SQL that turns ``customers.timezone`` into a zone Postgres will accept.

    ``expr`` is the SQL expression holding the label — a column
    (``c.timezone``) at the call sites, a bound parameter (``:tz``) in tests.

    ``customers.timezone`` is data, and this deployment's data is not clean:
    ``backend/seed/customers.json`` stores display labels like
    ``Asia/Kolkata (IST)``, so a re-seed puts them back. :func:`_zone` has always
    treated the column as untrusted; the SQL did not, and interpolating the raw
    value into ``AT TIME ZONE`` raises

        InvalidParameterValue: time zone "Asia/Kolkata (IST)" not recognized

    which aborts the whole transaction, not just the statement.

    Same policy as :func:`_zone`, expressed once here so both paths agree:

    1. take the part before any parenthetical suffix, so the label form resolves
       to the zone it actually names rather than to the default — falling back
       would be right by accident for an Indian borrower and wrong for anyone
       else;
    2. accept it only if Postgres knows it;
    3. otherwise use the tenant default.

    Returns a SQL fragment, so the caller keeps its bound parameter and nothing
    is interpolated but the parameter's own name.
    """
    return (
        "COALESCE("
        "  (SELECT n.name FROM pg_timezone_names n"
        f"    WHERE n.name = btrim(split_part(COALESCE({expr}, ''), '(', 1))"
        "    LIMIT 1),"
        f"  '{DEFAULT_TZ}')"
    )


#: Ready-made fragments for callers that bind the label as a parameter.
SQL_SAFE_TZ = safe_tz_sql(":tz")
SQL_SAFE_TZ_ALT = safe_tz_sql(":tz2")


def _parse_hours(raw: str | None) -> tuple[int, int] | None:
    if not raw or not str(raw).strip():
        return None
    m = re.search(r"(\d{1,2}):(\d{2}).*?(\d{1,2}):(\d{2})", str(raw))
    if not m:
        return None
    return int(m.group(1)), int(m.group(3))


def _parse_days(raw: str | None) -> list[int] | None:
    """Consent days, or ``None`` when nothing was recorded.

    The implementation moved to :mod:`contact_window`, which already owned the
    sibling hours rule, because ``db.py`` had a second copy that did not
    normalise the dash — see that module's note. This name stays: it is
    re-exported as ``parse_days`` below and the treatment engine plans against it.
    """
    return contact_window.allowed_days(raw)


#: Public names for the two consent-window parsers. The treatment engine plans
#: *when* to act and has to see the same window this module vetoes against; a
#: second parser that agreed with these on Tuesday is one that disagrees in
#: November.
parse_allowed_hours = _parse_hours
parse_allowed_days = _parse_days


def _preferred_hours(customer: dict[str, Any]) -> tuple[int, int] | None:
    """The borrower's own window: consent hours intersected with their preference.

    Two columns describe the same thing and only one of them was ever consulted
    here. ``consent_records.allowed_hours`` is what an operator captures at
    onboarding; ``customers.preferred_window`` is what the CRM carries, is
    populated across the seeded book, and — until now — was read by exactly one
    thing: the recommender's talk track, which used it to *phrase* an offer
    ("we can call you back in your usual window") while the dialler ignored it
    and rang at four in the afternoon anyway.

    The intersection, rather than a precedence order, is the point. Both are
    statements by or about the borrower and neither is entitled to overrule the
    other upwards; taking the tighter of the two is the only combination that
    cannot produce a call neither column would have permitted on its own. It is
    also what makes this safe to switch on against real data: the seeded book
    contains an ``18:00-21:00 IST`` preference, and intersecting it with the
    statutory 19:00 cut-off is what stops that row buying a nine o'clock call.
    """
    consent = _parse_hours(customer.get("allowed_hours"))
    stated = _parse_hours(customer.get("preferred_window"))
    if consent is None:
        return stated
    if stated is None:
        return consent
    start = max(consent[0], stated[0])
    end = min(consent[1], stated[1])
    # Two windows that do not overlap describe a borrower nobody may ever call,
    # which is almost certainly a data-entry error rather than a wish. Fall back
    # to the recorded consent — the column an operator captured deliberately —
    # and leave the statutory window doing the outer bounding it always did.
    return (start, end) if start < end else consent


#: The borrower's effective window — consent hours intersected with the CRM's
#: ``preferred_window``. Exported for the same reason as the two above: the
#: planner has to see the window the veto will apply, not a near-miss of it.
preferred_hours = _preferred_hours


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
            SELECT c.id, c.tenant_id, c.dnd, c.timezone, c.preferred_window,
                   cr.allowed_days, cr.allowed_hours, cr.dnd_registry, cr.expires_at,
                   (SELECT sum(a.outstanding) FROM accounts a WHERE a.customer_id = c.id) AS outstanding
            FROM customers c
            LEFT JOIN consent_records cr ON cr.customer_id = c.id
            WHERE c.id = :id
            """
        ),
        {"id": customer_id},
    ).mappings().first()
    return dict(row) if row else None


def _endpoint_enforcement_enabled() -> bool:
    from env_utils import env_bool

    return env_bool("ENDPOINT_ENFORCEMENT", False)


def _active_hold_kind(conn: Any, customer_id: str) -> str | None:
    try:
        row = conn.execute(
            text(
                """
                SELECT kind FROM treatment_holds
                WHERE customer_id = :cid
                  AND released_at IS NULL
                  AND starts_at <= now()
                  AND (expires_at IS NULL OR expires_at > now())
                ORDER BY starts_at DESC
                LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).mappings().first()
    except Exception:
        logger.exception("treatment hold lookup failed customer=%s", customer_id)
        return "unreadable"
    if not row:
        return None
    return str(row["kind"])


def _consent_overlay_blocks(
    conn: Any,
    *,
    customer_id: str,
    channel: str,
    endpoint: str | None,
    data_purpose: str,
) -> bool:
    from agent_core.treatment import schema_ready

    if not schema_ready.has_table(conn, "consent_events"):
        return False
    row = conn.execute(
        text(
            """
            SELECT verb FROM consent_events
            WHERE customer_id = :cid
              AND (channel = :ch OR channel = 'all')
              AND (purpose = :purpose OR purpose = 'all')
              -- CAST before the null test, the same trap the model registry
              -- documents: a bare ``:endpoint IS NULL`` gives the planner
              -- nothing to infer the parameter's type from, and Postgres
              -- refuses the whole statement with "could not determine data
              -- type of parameter $4". It stayed hidden because
              -- ``consent_events`` did not exist until migration 0108, so the
              -- ``has_table`` guard above returned before the query ran.
              AND (
                endpoint IS NULL
                OR CAST(:endpoint AS TEXT) IS NULL
                OR endpoint = CAST(:endpoint AS TEXT)
              )
            ORDER BY captured_at DESC
            LIMIT 1
            """
        ),
        {
            "cid": customer_id,
            "ch": channel,
            "purpose": data_purpose,
            "endpoint": endpoint,
        },
    ).mappings().first()
    if not row:
        return False
    return str(row["verb"]) in {"withdraw", "restrict", "expire", "opt_out"}


def _endpoint_state(
    conn: Any, *, tenant_id: str, endpoint: str | None, channel: str
) -> str | None:
    from agent_core.treatment import schema_ready

    if not endpoint or not schema_ready.has_table(conn, "endpoint_ownership"):
        return None
    row = conn.execute(
        text(
            """
            SELECT state FROM endpoint_ownership
            WHERE tenant_id = :tid AND endpoint = :ep AND channel = :ch
            """
        ),
        {"tid": tenant_id, "ep": endpoint, "ch": channel},
    ).mappings().first()
    return str(row["state"]) if row else None


def _veto_extras(
    conn: Any,
    *,
    customer: dict[str, Any] | None,
    customer_id: str,
    channel: str,
    endpoint: str | None,
    data_purpose: str,
    instant: datetime,
    purpose: str,
) -> dict[str, Any]:
    if conn is None:
        return {
            "hold_kind": None,
            "overlay_blocked": False,
            "consent_expired": False,
            "endpoint_state": None,
            "enforce_endpoint": False,
        }
    hold_kind = None
    overlay = False
    expired = False
    if customer and purpose != "in_session":
        hold_kind = _active_hold_kind(conn, customer_id)
    if customer:
        overlay = _consent_overlay_blocks(
            conn,
            customer_id=customer_id,
            channel=channel,
            endpoint=endpoint,
            data_purpose=data_purpose,
        )
        expires = as_utc(customer.get("expires_at"))
        if expires is not None:
            expired = expires <= instant
    ep_state = (
        _endpoint_state(
            conn,
            tenant_id=str(customer.get("tenant_id") or ""),
            endpoint=endpoint,
            channel=channel,
        )
        if customer
        else None
    )
    return {
        "hold_kind": hold_kind,
        "overlay_blocked": overlay,
        "consent_expired": expired,
        "endpoint_state": ep_state,
        "enforce_endpoint": _endpoint_enforcement_enabled() and bool(endpoint),
    }


def _fired_ids(rules: Any, reason: str | None) -> list[str]:
    if not reason or rules is None:
        return []
    kind_map = {
        REASON_HOURS: "calling_window",
        REASON_WINDOW_DEFERRED_STATUTORY: "calling_window",
        REASON_DAILY: "daily_cap",
        REASON_WEEKLY: "weekly_cap",
        REASON_COOLING: "cooling_off",
        REASON_SUPPRESSED: "suppression_state",
        REASON_CUSTOMER_DND: "channel_scrub",
    }
    kind = kind_map.get(reason)
    if not kind:
        return []
    return [item.rule_id for item in getattr(rules, "consulted", ()) if item.kind == kind]


def _binding_for(
    rules: Any, *, fired: list[str], at: datetime
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    try:
        import policy_binding

        bindings, digest = policy_binding.pair(rules, fired_rule_ids=fired, evaluated_at=at)
        return tuple(bindings), digest
    except Exception:
        logger.exception("policy binding failed")
        return (), None


def _channel_status(conn: Any, customer_id: str, channel: str) -> str | None:
    import capture

    by_ch = capture.latest_consent_by_channel(conn, customer_id)
    return by_ch.get(channel) or by_ch.get("voice" if channel == "call" else channel)


def _promotional_status(conn: Any, customer_id: str, channel: str) -> str | None:
    """Promotional consent for this channel, or None if never captured."""
    try:
        import capture

        return capture.promotional_consent(conn, customer_id, channel)
    except Exception:
        logger.debug("promotional consent unreadable", exc_info=True)
        return None


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
    return as_utc(row["occurred_at"])


def _statutory_window(rules: Any | None, channel: str) -> tuple[int, int]:
    """The published calling window, else the platform's conservative bound."""
    window = rules.calling_window(channel) if rules is not None else None
    return window if window is not None else (RBI_VOICE_START, RBI_VOICE_END)


def _consent_window(customer: dict[str, Any]) -> tuple[tuple[int, int], list[int] | None]:
    """The borrower's own preferred hours and days."""
    return (
        _preferred_hours(customer) or contact_window.window_hours(None),
        _parse_days(customer.get("allowed_days")),
    )


def _next_window_open(
    now_local: datetime,
    *,
    rules: Any | None,
    channel: str,
    customer: dict[str, Any],
) -> datetime:
    """The next instant both windows are open, in UTC.

    Shares :func:`_statutory_window` and :func:`_consent_window` with the veto
    that produced the refusal, so the answer to "why not now" and the answer to
    "then when" can never come from two different readings of the same rules.

    Walks forward a day at a time rather than solving it: at most eight
    iterations (seven days plus today), and a closed-form version would have to
    re-derive the intersection of two hour ranges and a day mask, which is the
    sort of arithmetic that is wrong for a year before anyone notices.
    """
    s_start, s_end = _statutory_window(rules, channel)
    (c_start, c_end), days = _consent_window(customer)
    start_h = max(s_start, c_start)
    end_h = min(s_end, c_end)
    if start_h >= end_h:
        # The published window and the borrower's preference do not overlap.
        # Nothing to schedule; the caller treats None-ish deadlines as "ask
        # again tomorrow" rather than inventing a slot neither rule allows.
        start_h, end_h = s_start, s_end

    candidate = now_local
    if now_local.hour >= start_h:
        candidate = now_local + timedelta(days=1)
    for _ in range(8):
        opens = candidate.replace(hour=start_h, minute=0, second=0, microsecond=0)
        if opens > now_local and (days is None or (opens.isoweekday() % 7) in days):
            return opens.astimezone(timezone.utc)
        candidate = candidate + timedelta(days=1)
    return (now_local + timedelta(days=1)).astimezone(timezone.utc)


def _next_allowed(
    reason: str | None,
    *,
    now_local: datetime,
    rules: Any | None,
    channel: str,
    customer: dict[str, Any] | None,
    last_counted_at: datetime | None = None,
) -> datetime | None:
    """When a clock-shaped refusal stops being true. None if it never does.

    Every fact here is already in the caller's hand at the moment it refuses —
    which is the point. Nothing in this module computed it before, so a caller
    holding a refusal had no way to tell "not yet" from "no", and the one caller
    that guessed dead-lettered 18 messages.
    """
    if reason not in CLOCK_REFUSALS or customer is None:
        return None
    if reason == REASON_COOLING:
        if last_counted_at is None:
            return None
        return (last_counted_at + cooling_off(rules)).astimezone(timezone.utc)
    if reason == REASON_DAILY:
        midnight = (now_local + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return midnight.astimezone(timezone.utc)
    if reason == REASON_WEEKLY:
        # Start of next ISO week, local. Under-estimating here would only cost a
        # wasted attempt; over-estimating holds a message the caps would allow.
        days_ahead = 8 - now_local.isoweekday()
        nxt = (now_local + timedelta(days=days_ahead)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return nxt.astimezone(timezone.utc)
    return _next_window_open(now_local, rules=rules, channel=channel, customer=customer)


def _veto(
    *,
    purpose: str,
    channel: str,
    customer: dict[str, Any] | None,
    status: str | None,
    now_local: datetime,
    rules: Any | None = None,
    data_purpose: str = "servicing",
    promo_status: str | None = None,
    hold_kind: str | None = None,
    overlay_blocked: bool = False,
    consent_expired: bool = False,
    endpoint_state: str | None = None,
    enforce_endpoint: bool = False,
) -> str | None:
    if customer is None:
        return REASON_NO_CUSTOMER if purpose == "outreach" else None

    if hold_kind:
        return REASON_SUPPRESSED

    if overlay_blocked:
        return REASON_CONSENT_OVERLAY

    if consent_expired and purpose != "in_session":
        return REASON_EXPIRED_CONSENT

    if status in BLOCKING_CONSENT:
        return _consent_reason(status)

    if data_purpose == "promotional" and promo_status != "opted_in":
        return REASON_NO_PROMO_CONSENT

    if purpose == "in_session":
        return None

    # NULL means no accounts at all (a lead, a prospect) -- not settled.
    outstanding = customer.get("outstanding")
    if purpose == "outreach" and outstanding is not None and float(outstanding) <= 0:
        return REASON_SETTLED

    if enforce_endpoint and endpoint_state in {None, "unverified", "revoked"}:
        return REASON_ENDPOINT

    if rules is not None:
        _ = rules.required_certifications()
        _ = rules.channel_scrub_lists()
        _ = rules.notice_obeys_window()

    if customer.get("dnd") or customer.get("dnd_registry"):
        return REASON_CUSTOMER_DND

    # Published window, else the conservative 08:00–19:00 platform bound.
    # Messages use that bound until counsel cites a distinct instrument.
    start_h, end_h = _statutory_window(rules, channel)
    if now_local.hour < start_h or now_local.hour >= end_h:
        if purpose == "statutory":
            return REASON_WINDOW_DEFERRED_STATUTORY
        return REASON_HOURS

    hours, days = _consent_window(customer)
    start_h, end_h = hours
    if now_local.hour < start_h or now_local.hour >= end_h:
        if purpose == "statutory":
            return REASON_WINDOW_DEFERRED_STATUTORY
        return REASON_WINDOW
    if days is not None:
        if (now_local.isoweekday() % 7) not in days:
            if purpose == "statutory":
                return REASON_WINDOW_DEFERRED_STATUTORY
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
    data_purpose: str = "servicing",
    endpoint: str | None = None,
    product_id: str | None = None,
) -> Decision:
    """Dry-run. No writes. Used by the UI and later as a P3 veto."""
    cap = daily_cap()
    purpose = purpose if purpose in PURPOSES else "outreach"
    data_purpose = data_purpose if data_purpose in DATA_PURPOSES else "servicing"
    channel = normalize_channel(channel)
    cid = (customer_id or "").strip()
    if not cid:
        if purpose == "outreach":
            return Decision(False, REASON_NO_CUSTOMER, daily_cap=cap)
        return Decision(True, daily_cap=cap)

    try:
        customer = _load_customer(conn, cid)
        instant = as_utc(now or utc_now())
        tz = _zone((customer or {}).get("timezone"))
        local = instant.astimezone(tz)
        rules = _rules_for(conn, customer, instant, product_id=product_id)
        cap = daily_cap(rules)
        status = _channel_status(conn, cid, channel) if customer else None
        extras = _veto_extras(
            conn,
            customer=customer,
            customer_id=cid,
            channel=channel,
            endpoint=endpoint,
            data_purpose=data_purpose,
            instant=instant,
            purpose=purpose,
        )
        reason = _veto(
            purpose=purpose,
            channel=channel,
            customer=customer,
            status=status,
            now_local=local,
            rules=rules,
            data_purpose=data_purpose,
            promo_status=(
                _promotional_status(conn, cid, channel)
                if customer and data_purpose == "promotional"
                else None
            ),
            **extras,
        )
        binding, digest = _binding_for(rules, fired=_fired_ids(rules, reason), at=instant)
        today = _today_count(conn, cid, local.date()) if customer else 0
        if reason:
            return Decision(
                False,
                reason,
                today_count=today,
                daily_cap=cap,
                policy_binding=binding,
                policy_binding_hash=digest,
                next_allowed_at=_next_allowed(
                    reason, now_local=local, rules=rules, channel=channel,
                    customer=customer,
                ),
            )
        coalesced = _session_coalesced(conn, customer_id=cid, session_key=session_key, now=instant)
        if coalesced or purpose == "in_session":
            return Decision(
                True,
                today_count=today,
                daily_cap=cap,
                coalesced=coalesced,
                policy_binding=binding,
                policy_binding_hash=digest,
            )
        if purpose == "outreach":
            last = _last_counted_at(conn, cid)
            cool = cooling_off(rules)
            if cool.total_seconds() > 0 and last is not None and instant - last < cool:
                return Decision(
                    False,
                    REASON_COOLING,
                    today_count=today,
                    daily_cap=cap,
                    policy_binding=binding,
                    policy_binding_hash=digest,
                    next_allowed_at=_next_allowed(
                        REASON_COOLING, now_local=local, rules=rules,
                        channel=channel, customer=customer, last_counted_at=last,
                    ),
                )
            if today >= cap:
                return Decision(
                    False,
                    REASON_DAILY,
                    today_count=today,
                    daily_cap=cap,
                    policy_binding=binding,
                    policy_binding_hash=digest,
                    next_allowed_at=_next_allowed(
                        REASON_DAILY, now_local=local, rules=rules, channel=channel,
                        customer=customer,
                    ),
                )
            week_n = _week_counted(conn, cid, channel, now=instant, tz=tz)
            if week_n >= _weekly_cap_for(conn, cid, channel, rules):
                return Decision(
                    False,
                    REASON_WEEKLY,
                    today_count=today,
                    daily_cap=cap,
                    policy_binding=binding,
                    policy_binding_hash=digest,
                    next_allowed_at=_next_allowed(
                        REASON_WEEKLY, now_local=local, rules=rules, channel=channel,
                        customer=customer,
                    ),
                )
        return Decision(
            True,
            today_count=today,
            daily_cap=cap,
            policy_binding=binding,
            policy_binding_hash=digest,
        )
    except Exception:
        logger.exception("contact_policy.evaluate failed customer=%s", cid)
        return Decision(False, REASON_UNREADABLE, daily_cap=cap)


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
        REASON_WINDOW_DEFERRED_STATUTORY,
        REASON_SUPPRESSED,
        REASON_ENDPOINT,
        REASON_CONSENT_OVERLAY,
        REASON_EXPIRED_CONSENT,
        REASON_NO_ENDPOINT,
    }
)


def narrow_window(
    conn: Any,
    *,
    customer_id: str,
    earliest_hour: int | None = None,
    latest_hour: int | None = None,
    source: str = "voice",
    note: str | None = None,
) -> dict[str, Any]:
    """Tighten a borrower's calling window because they asked. Never widens.

    RBI para 100Y sets 08:00-19:00 and adds *"unless the borrower has asked
    otherwise"*. The read path already honours a narrower window: :func:`_veto`
    checks the statutory hours and then the consent hours, so the effective
    window has always been the intersection of the two. What was missing is any
    way for the borrower's own words to reach the column — ``allowed_hours`` was
    a field an operator could type into and nothing else, so "never call me
    before ten" was a sentence the agent heard, agreed with, and forgot.

    Two directions, one of them refused
    -----------------------------------
    A stated restriction may only ever make the window smaller. That is not
    symmetry for its own sake: the value arrives from a language model reading a
    live conversation, and the failure modes are not equal. Mishearing "don't
    call before ten" tightens a window by two hours and costs us some reach.
    Mishearing agreement as *"call any time"* would delete a restriction the
    borrower actually stated, and there is no log entry that makes that all
    right. Widening therefore needs a human, and this function will not do it.

    The statutory window is the outer bound regardless — a borrower cannot
    consent us into calling at 06:00 through this path, because para 100Y's
    exception is about *narrowing* in practice and an agent that could be talked
    into a dawn call is the conduct problem the paragraph exists to stop.
    """
    result: dict[str, Any] = {"ok": False, "reason": None, "window": None}
    cid = (customer_id or "").strip()
    if not cid:
        result["reason"] = REASON_NO_CUSTOMER
        return result

    def _hour(value: Any) -> int | None:
        try:
            hour = int(value)
        except (TypeError, ValueError):
            return None
        return hour if 0 <= hour <= 23 else None

    want_start = _hour(earliest_hour)
    want_end = _hour(latest_hour)
    if want_start is None and want_end is None:
        result["reason"] = "no_bound_given"
        return result

    try:
        customer = _load_customer(conn, cid)
        if customer is None:
            result["reason"] = REASON_NO_CUSTOMER
            return result

        rules = _rules_for(conn, customer, utc_now())
        statutory = (rules.calling_window("voice") if rules is not None else None) or (
            RBI_VOICE_START,
            RBI_VOICE_END,
        )
        # The same intersection the veto uses, so narrowing composes with a
        # preference already on file instead of quietly replacing it.
        current = _preferred_hours(customer) or statutory

        start = max(current[0], statutory[0], want_start if want_start is not None else 0)
        end = min(current[1], statutory[1], want_end if want_end is not None else 23)
        if start >= end:
            # "Never before ten and never after nine in the morning" is not a
            # window, it is a request to stop calling — which is an opt-out and
            # has its own tool, its own consent row and its own audit trail.
            result["reason"] = "window_would_be_empty"
            return result
        if (start, end) == current:
            result["ok"] = True
            result["reason"] = "already_narrower"
            result["window"] = list(current)
            return result

        value = f"{start:02d}:00-{end:02d}:00 IST"
        conn.execute(
            text(
                """
                INSERT INTO consent_records (id, customer_id, allowed_hours, updated_at)
                VALUES (:id, :cid, :hours, now())
                ON CONFLICT (customer_id)
                DO UPDATE SET allowed_hours = EXCLUDED.allowed_hours, updated_at = now()
                """
            ),
            # A consent row, not a contact event — the CE- prefix would be a
            # small lie in every audit export that joins on id prefixes.
            {"id": f"CR-{uuid.uuid4().hex[:10].upper()}", "cid": cid, "hours": value},
        )
        import db as dbmod

        dbmod.record_activity(
            conn,
            "customer",
            cid,
            "contact_window_narrowed",
            f"Calling window narrowed to {value}",
            (note or source)[:500],
            cid,
        )
        logger.info("contact window narrowed for %s to %s (%s)", cid, value, source)
        result.update({"ok": True, "window": [start, end], "reason": "narrowed"})
        return result
    except Exception:
        logger.exception("narrow_window failed for %s", cid)
        result["reason"] = "failed"
        return result


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
    policy_binding: tuple[dict[str, Any], ...] | list[dict[str, Any]] = (),
    policy_binding_hash: str | None = None,
) -> None:
    extra_cols = ""
    extra_vals = ""
    params: dict[str, Any] = {
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
    }
    from agent_core.treatment import schema_ready

    if schema_ready.has_column(conn, "contact_events", "policy_binding"):
        extra_cols = ", policy_binding, policy_binding_hash"
        extra_vals = ", CAST(:policy_binding AS jsonb), :policy_binding_hash"
        params["policy_binding"] = json.dumps(list(policy_binding))
        params["policy_binding_hash"] = policy_binding_hash
    conn.execute(
        text(
            f"""
            INSERT INTO contact_events (
              id, tenant_id, customer_id, account_id, channel, direction,
              purpose, actor_kind, actor_user_id, outcome, reason,
              session_key, source, related_id, touch_counted, occurred_at
              {extra_cols}
            ) VALUES (
              :id, :tenant_id, :customer_id, :account_id, :channel, 'outbound',
              :purpose, :actor_kind, :actor_user_id, :outcome, :reason,
              :session_key, :source, :related_id, :touch_counted, :occurred_at
              {extra_vals}
            )
            """
        ),
        params,
    )


def _lock_day(conn: Any, customer_id: str, local_date: Any) -> int:
    """Take the borrower's day row lock; returns today's count so far."""
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
            SELECT outreach_sessions FROM contact_day_counters
            WHERE customer_id = :cid AND local_date = :d
            FOR UPDATE
            """
        ),
        {"cid": customer_id, "d": local_date},
    ).mappings().first()
    return int(row["outreach_sessions"] or 0) if row else 0


def _increment_day(conn: Any, customer_id: str, local_date: Any) -> int:
    """Count one outreach session on a row `_lock_day` already holds."""
    row = conn.execute(
        text(
            """
            UPDATE contact_day_counters
               SET outreach_sessions = outreach_sessions + 1
             WHERE customer_id = :cid AND local_date = :d
            RETURNING outreach_sessions
            """
        ),
        {"cid": customer_id, "d": local_date},
    ).mappings().first()
    return int(row["outreach_sessions"] or 0) if row else 0


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
    data_purpose: str = "servicing",
    endpoint: str | None = None,
    product_id: str | None = None,
    card_daily_cap: int | None = None,
) -> Decision:
    """Evaluate, reserve, log. Never raises."""
    cap = daily_cap(card_cap=card_daily_cap)
    purpose = purpose if purpose in PURPOSES else "outreach"
    data_purpose = data_purpose if data_purpose in DATA_PURPOSES else "servicing"
    channel = normalize_channel(channel)
    cid = (customer_id or "").strip()
    instant = as_utc(now or utc_now())

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
        rules = _rules_for(conn, customer, instant, product_id=product_id)
        cap = daily_cap(rules, card_cap=card_daily_cap)
        status = _channel_status(conn, cid, channel)
        extras = _veto_extras(
            conn,
            customer=customer,
            customer_id=cid,
            channel=channel,
            endpoint=endpoint,
            data_purpose=data_purpose,
            instant=instant,
            purpose=purpose,
        )
        reason = _veto(
            purpose=purpose,
            channel=channel,
            customer=customer,
            status=status,
            now_local=local,
            rules=rules,
            data_purpose=data_purpose,
            promo_status=(
                _promotional_status(conn, cid, channel)
                if data_purpose == "promotional"
                else None
            ),
            **extras,
        )
        binding, digest = _binding_for(rules, fired=_fired_ids(rules, reason), at=instant)
        today = _today_count(conn, cid, local.date())

        def _deny(
            why: str, count: int = today, *, last_counted_at: datetime | None = None
        ) -> Decision:
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
                policy_binding=binding,
                policy_binding_hash=digest,
            )
            return Decision(
                False,
                why,
                today_count=count,
                daily_cap=cap,
                policy_binding=binding,
                policy_binding_hash=digest,
                next_allowed_at=_next_allowed(
                    why,
                    now_local=local,
                    rules=rules,
                    channel=channel,
                    customer=customer,
                    last_counted_at=last_counted_at,
                ),
            )

        if reason:
            return _deny(reason)

        coalesced = _session_coalesced(conn, customer_id=cid, session_key=session_key, now=instant)
        related_done = _already_counted_related(
            conn, customer_id=cid, source=source, related_id=related_id
        )
        counts = purpose in {"outreach", "statutory"} and not coalesced and not related_done

        if purpose == "outreach" and counts:
            # The day row's lock serialises every admit for this borrower, so
            # the cooling-off and weekly reads below cannot race a sibling
            # admit -- two concurrent dials at the weekly cap both read
            # `cap - 1` when these ran before the lock, and both were admitted.
            current = _lock_day(conn, cid, local.date())
            if current >= cap:
                return _deny(REASON_DAILY, current)
            last = _last_counted_at(conn, cid)
            cool = cooling_off(rules)
            if cool.total_seconds() > 0 and last is not None and instant - last < cool:
                return _deny(REASON_COOLING, last_counted_at=last)
            week_n = _week_counted(conn, cid, channel, now=instant, tz=tz)
            if week_n >= _weekly_cap_for(conn, cid, channel, rules):
                return _deny(REASON_WEEKLY)
            today = _increment_day(conn, cid, local.date())
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
            policy_binding=binding,
            policy_binding_hash=digest,
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
            policy_binding=binding,
            policy_binding_hash=digest,
        )
    except Exception:
        logger.exception("contact_policy.admit failed customer=%s", cid)
        return Decision(False, REASON_UNREADABLE, daily_cap=cap)


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
            SELECT e.customer_id, e.channel, count(*) AS n
            FROM contact_events e
            JOIN customers cu ON cu.id = e.customer_id
            WHERE e.customer_id = ANY(:ids)
              AND e.outcome = 'allowed'
              AND e.touch_counted
              -- The week the gate counts (`_week_counted`): from local midnight
              -- six days ago in the borrower's zone, not a rolling UTC 7d.
              AND e.occurred_at >= (
                    (date_trunc('day', now() AT TIME ZONE COALESCE(
                        (SELECT n.name FROM pg_timezone_names n
                          WHERE n.name = btrim(split_part(COALESCE(cu.timezone, ''), '(', 1))
                          LIMIT 1),
                        :default_tz)) - interval '6 days')
                    AT TIME ZONE COALESCE(
                        (SELECT n.name FROM pg_timezone_names n
                          WHERE n.name = btrim(split_part(COALESCE(cu.timezone, ''), '(', 1))
                          LIMIT 1),
                        :default_tz)
              )
            GROUP BY e.customer_id, e.channel
            """
        ),
        {"ids": customer_ids, "default_tz": DEFAULT_TZ},
    ).mappings().all()
    today_rows = conn.execute(
        text(
            """
            SELECT c.customer_id, c.outreach_sessions
            FROM contact_day_counters c
            WHERE c.customer_id = ANY(:ids)
              AND c.local_date = (
                -- `customers.timezone` holds display labels in seeded data, and
                -- an unrecognised zone here aborts the whole transaction rather
                -- than just this statement. Same rule as `_zone()` in Python.
                SELECT (now() AT TIME ZONE COALESCE(
                          (SELECT n.name FROM pg_timezone_names n
                            WHERE n.name = btrim(split_part(COALESCE(cu.timezone, ''), '(', 1))
                            LIMIT 1),
                          :default_tz))::date
                FROM customers cu WHERE cu.id = c.customer_id
              )
            """
        ),
        {"ids": customer_ids, "default_tz": DEFAULT_TZ},
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
