"""Outbound call attempts — the object every outbound metric is measured on.

Before this module the product placed calls with ``twilio_ops.start_outbound_call``
and kept nothing. ``interactions`` rows are created by ``persist.start_voice_call``
from ``on_client_connected``, so a ring-out, a busy tone, a rejected call, a dead
number and a call the contact gate refused all produced identical evidence: none.
``/twilio/voice/call-status`` received every one of those transitions and returned
204 without a write.

The damage was not a missing dashboard. ``treatment/features.py`` computes
``connect_rate`` and ``responsive_hours`` from voice interactions lasting at least
``CONNECT_MIN_SECONDS``, i.e. from connects only — the denominator was never
recorded, so the single most important input to "when should we call this
borrower" was being fitted to its own numerator.

The order of operations
-----------------------
Deliberate, and the reason each step sits where it does:

1. **Reserve.** A ``reserved`` row is written and committed *before* anything
   else. A crash between the contact gate and the carrier previously spent a
   borrower's daily budget with nothing to show what spent it.
2. **Gate.** Callers run ``contact_policy.admit`` themselves — it is their
   existing, reviewed code and it must keep running on their connection so the
   budget reservation and the send share a transaction. A denial calls
   :func:`suppress`, so a refused attempt is still a row and "our denial rate is
   14%" becomes a query rather than a log-grep.
3. **Fleet gate.** :func:`place` refuses when too many attempts are already in
   flight. See below.
4. **Dial**, then mark ``dialing`` with the carrier's call id.

Concurrency, honestly
---------------------
``voice/admission.py`` is a *per-process* counted gate, and it caps the process
that serves the media. The dialler runs in the API or worker process, so
acquiring a slot there would reserve nothing in the voice worker. Rather than a
gate that looks right and protects nothing, the in-flight count here is a query
over ``call_attempts`` — which is shared by every process by construction, needs
no new infrastructure, and is exactly the quantity we want to bound.

It is a cap on *our own dialling*, not a fleet-wide admission control: an inbound
surge can still fill the voice worker. The cap's job is to stop a campaign
outrunning the fleet, and for that it is sufficient. A Redis token bucket is the
next step and is an open question in ``outbound-agent-engine.md`` §18.

Nothing here raises on the dial path. "The call was not placed" is always a valid
outcome, same discipline as ``reco.recommend()`` and ``contact_policy.admit()``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from env_utils import env_int

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Vocabulary — kept in step with the CHECK constraints in sql/21_outbound.sql
# ---------------------------------------------------------------------------

STATE_RESERVED = "reserved"
STATE_SUPPRESSED = "suppressed"
STATE_DIALING = "dialing"
STATE_RINGING = "ringing"
STATE_ANSWERED = "answered"
STATE_LIVE = "live"
STATE_COMPLETED = "completed"
STATE_VOICEMAIL_LEFT = "voicemail_left"
STATE_VOICEMAIL_SKIPPED = "voicemail_skipped"
STATE_NO_ANSWER = "no_answer"
STATE_BUSY = "busy"
STATE_REJECTED = "rejected"
STATE_FAILED = "failed"
STATE_INVALID_NUMBER = "invalid_number"
STATE_CANCELED = "canceled"
STATE_TRANSFERRED = "transferred"
STATE_ABANDONED = "abandoned"

#: An attempt in one of these is still holding a slot in the fleet gate.
IN_FLIGHT: frozenset[str] = frozenset(
    {STATE_RESERVED, STATE_DIALING, STATE_RINGING, STATE_ANSWERED, STATE_LIVE}
)

TERMINAL: frozenset[str] = frozenset(
    {
        STATE_SUPPRESSED,
        STATE_COMPLETED,
        STATE_VOICEMAIL_LEFT,
        STATE_VOICEMAIL_SKIPPED,
        STATE_NO_ANSWER,
        STATE_BUSY,
        STATE_REJECTED,
        STATE_FAILED,
        STATE_INVALID_NUMBER,
        STATE_CANCELED,
        STATE_TRANSFERRED,
        STATE_ABANDONED,
    }
)

#: Cadence input. A ``rejected`` number retried three times is a number to
#: retire, not a number to keep dialling — that rule lives in the cadence, not
#: here, but it starts from this set.
RETRYABLE: frozenset[str] = frozenset(
    {STATE_NO_ANSWER, STATE_BUSY, STATE_VOICEMAIL_LEFT, STATE_VOICEMAIL_SKIPPED, STATE_REJECTED}
)

#: Twilio can deliver status callbacks out of order, and it retries them. Rank
#: makes the state machine monotonic: a late ``ringing`` cannot overwrite a
#: ``completed`` that already landed. Terminal states share the top rank because
#: the first terminal answer is the true one.
_RANK: dict[str, int] = {
    STATE_RESERVED: 0,
    STATE_DIALING: 1,
    STATE_RINGING: 2,
    STATE_ANSWERED: 3,
    STATE_LIVE: 4,
    **{s: 9 for s in TERMINAL},
}

#: Twilio ``CallStatus`` → our state. ``completed`` means the call was answered
#: and has ended; the un-answered endings are their own statuses, which is why
#: this mapping is not lossy.
_TWILIO_STATUS: dict[str, str] = {
    "queued": STATE_DIALING,
    "initiated": STATE_DIALING,
    "ringing": STATE_RINGING,
    "in-progress": STATE_ANSWERED,
    "completed": STATE_COMPLETED,
    "busy": STATE_BUSY,
    "no-answer": STATE_NO_ANSWER,
    "failed": STATE_FAILED,
    "canceled": STATE_CANCELED,
}

#: Twilio error codes that mean the number itself is wrong, as opposed to a
#: transient carrier failure. Separating them is what lets the cadence retire a
#: phone slot and promote the alternate rather than retrying a dead number
#: three times — the cheapest form of skip-tracing there is.
_INVALID_NUMBER_CODES: frozenset[str] = frozenset(
    {
        "13224",  # Invalid phone number format
        "21211",  # Invalid 'To' phone number
        "21214",  # 'To' phone number cannot be reached
        "21215",  # Geo permissions
        "21217",  # Not a valid phone number
        "21219",  # 'To' number not verified (trial)
        "21401",  # Invalid phone number
        "21421",  # Phone number is not a valid E.164
        "21614",  # 'To' number is not a mobile
    }
)

#: Twilio ``AnsweredBy`` → our coarse classification. The four machine_* values
#: differ only in *how* the detector concluded it was a machine, which is a
#: detector-tuning fact rather than a business one.
_ANSWERED_BY: dict[str, str] = {
    "human": "human",
    "machine_start": "machine",
    "machine_end_beep": "machine",
    "machine_end_silence": "machine",
    "machine_end_other": "machine",
    "fax": "fax",
    "unknown": "unknown",
}


class DialRefused(RuntimeError):
    """The attempt was recorded but no call was placed. Never a bug."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def max_in_flight() -> int:
    """How many of our own dials may be alive at once.

    Default 10 against ``voice/admission.py``'s per-process cap of 25: outbound
    must leave headroom for inbound, because an inbound caller who is refused
    dialled us on purpose and an outbound attempt we defer costs nothing but a
    minute. Raise it only together with that cap and the Azure semaphore.
    """
    return max(1, env_int("OUTBOUND_MAX_IN_FLIGHT", 10))


def stale_after() -> timedelta:
    """How long an in-flight attempt may go unheard from before it is reaped.

    A status callback that never arrives — a tunnel that dropped, a signature
    that failed, a process killed between ``calls.create`` and the response —
    would otherwise hold a slot in the fleet gate forever. Longer than any
    plausible call so the reaper can never close a live one.
    """
    return timedelta(minutes=max(5, env_int("OUTBOUND_STALE_MINUTES", 30)))


def amd_enabled() -> bool:
    """Ask the carrier for answering-machine detection as a second signal.

    Pipecat's in-band ``VoicemailDetector`` (``voice/amd.py``) is the accurate
    one and it already runs. Twilio's is faster and free with the call, and it
    arrives on the status callback where the in-band verdict never does. Off by
    default: it delays connect while the carrier listens, which is a real cost
    paid on every dial for a signal we mostly already have.
    """
    return (os.getenv("OUTBOUND_CARRIER_AMD") or "").strip().lower() in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _attempt_id() -> str:
    return f"CA-{uuid.uuid4().hex[:12].upper()}"


def _outcome_id() -> str:
    return f"CO-{uuid.uuid4().hex[:12].upper()}"


def digits(phone: str | None) -> str:
    return re.sub(r"\D+", "", phone or "")


def default_country_code() -> str:
    return (os.getenv("OUTBOUND_DEFAULT_COUNTRY_CODE") or "91").strip().lstrip("+")


def to_e164(phone: str | None) -> str:
    """Normalise a stored number into what a carrier will accept.

    ``customers.phone_primary`` holds bare digits — ``919655282324`` — because
    that is the shape the WhatsApp Graph API wants. Twilio wants E.164 and
    rejects the same value with error 21211, so every dial to a correctly
    stored Indian mobile would have failed as an invalid number. Normalising
    here rather than at each call site keeps the two channels' conventions from
    leaking into each other.

    A ten-digit number is assumed to be domestic; anything already carrying a
    country code is left alone. This does not attempt to be libphonenumber —
    it attempts to be correct for the numbers this system actually stores, and
    to leave anything it does not recognise untouched rather than mangled.
    """
    raw = (phone or "").strip()
    if not raw:
        return ""
    if raw.startswith("+"):
        return "+" + digits(raw)
    d = digits(raw)
    if not d:
        return ""
    cc = default_country_code()
    if len(d) == 10:
        return f"+{cc}{d}"
    if d.startswith("00"):
        return f"+{d[2:]}"
    return f"+{d}"


def phone_hash(phone: str | None) -> str:
    """Stable correlation key for a number, without storing the number.

    Not a security control — the space of Indian mobile numbers is small enough
    to enumerate, and pretending otherwise would be worse than saying so. It is
    here so attempts can be grouped by destination (retry counts, dead-slot
    detection, per-number answer rate) without this table becoming a second,
    unredactable copy of borrower PII with its own retention argument.
    """
    return hashlib.sha256(digits(phone).encode("utf-8")).hexdigest()[:32]


def _last4(phone: str | None) -> str | None:
    d = digits(phone)
    return d[-4:] if len(d) >= 4 else None


def _rank(state: str) -> int:
    return _RANK.get(state, 0)


def _tenant_for(conn: Any, customer_id: str) -> str | None:
    return conn.execute(
        text("SELECT tenant_id FROM customers WHERE id = :id"), {"id": customer_id}
    ).scalar()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def reserve(
    conn: Any,
    *,
    customer_id: str,
    to_phone: str,
    objective: str,
    account_id: str | None = None,
    decision_id: str | None = None,
    mission_id: str | None = None,
    campaign_run_id: str | None = None,
    bot_id: str | None = None,
    deployment_id: str | None = None,
    purpose: str = "outreach",
    phone_slot: str = "primary",
    policy_version: int | None = None,
    context: dict[str, Any] | None = None,
    tenant_id: str | None = None,
    number_pool: str | None = None,
) -> dict[str, Any] | None:
    """Write the ``reserved`` row. Returns None only if the customer is gone.

    Called before the contact gate so that a denial has something to attach to.
    ``attempt_no`` counts prior non-suppressed attempts on the same case, which
    is what the cadence's ``max_attempts`` is compared against — a suppressed
    attempt was never made, so counting it would let a busy day silently consume
    a borrower's retry budget.
    """
    tenant = tenant_id or _tenant_for(conn, customer_id)
    if not tenant:
        logger.warning("outbound.reserve: no such customer %s", customer_id)
        return None

    attempt_id = _attempt_id()
    to_hash = phone_hash(to_phone)
    # Attempts already made on this case. Suppressed rows are excluded on
    # purpose: an attempt the gate refused was never made, so counting it would
    # let a busy day silently consume the borrower's retry budget without their
    # phone ever ringing.
    #
    # The decision filter is applied in Python rather than as a nullable bind.
    # A `WHERE (:x IS NULL OR col = :x)` needs an explicit cast for the NULL
    # case, and SQLAlchemy's text() parses `::` as a bind marker — building the
    # clause is shorter than fighting that.
    case_filter = "AND decision_id = :decision_id" if decision_id else ""
    params: dict[str, Any] = {"cid": customer_id, "objective": objective}
    if decision_id:
        params["decision_id"] = decision_id
    prior = conn.execute(
        text(
            f"""
            SELECT count(*) FROM call_attempts
            WHERE customer_id = :cid
              AND objective = :objective
              AND state <> 'suppressed'
              AND reserved_at >= now() - interval '30 days'
              {case_filter}
            """
        ),
        params,
    ).scalar()

    conn.execute(
        text(
            """
            INSERT INTO call_attempts (
              id, tenant_id, customer_id, account_id, mission_id, campaign_run_id,
              decision_id, bot_id, deployment_id, objective, purpose, attempt_no,
              to_phone_hash, to_phone_last4, phone_slot, policy_version, state,
              context, reserved_at, created_at, updated_at
            ) VALUES (
              :id, :tenant_id, :customer_id, :account_id, :mission_id, :campaign_run_id,
              :decision_id, :bot_id, :deployment_id, :objective, :purpose, :attempt_no,
              :to_hash, :last4, :phone_slot, :policy_version, 'reserved',
              CAST(:context AS jsonb), now(), now(), now()
            )
            """
        ),
        {
            "id": attempt_id,
            "tenant_id": tenant,
            "customer_id": customer_id,
            "account_id": account_id,
            "mission_id": mission_id,
            "campaign_run_id": campaign_run_id,
            "decision_id": decision_id,
            "bot_id": bot_id,
            "deployment_id": deployment_id,
            "objective": objective,
            "purpose": purpose if purpose in {"outreach", "statutory", "in_session"} else "outreach",
            "attempt_no": int(prior or 0) + 1,
            "to_hash": to_hash,
            "last4": _last4(to_phone),
            "phone_slot": phone_slot,
            "policy_version": policy_version,
            "context": _json(context or {}),
        },
    )
    return {
        "id": attempt_id,
        "tenantId": tenant,
        "customerId": customer_id,
        "accountId": account_id,
        "objective": objective,
        "attemptNo": int(prior or 0) + 1,
        "decisionId": decision_id,
        "missionId": mission_id,
        "numberPool": number_pool,
        # Carried so that a failure inside `place` can say *whose* dial did not
        # happen. `place` returns its failures rather than raising them, so the
        # log line is the only thing an operator gets, and "outbound CA-... :
        # invalid number" with no borrower, campaign or case on it is a line
        # nobody can act on.
        "campaignRunId": campaign_run_id,
        "context": dict(context or {}),
    }


def suppress(conn: Any, attempt_id: str, reason: str) -> None:
    """The gate said no. Record it against the attempt rather than only in a log."""
    conn.execute(
        text(
            """
            UPDATE call_attempts
            SET state = 'suppressed', suppressed_reason = :reason,
                ended_at = now(), updated_at = now()
            WHERE id = :id AND state = 'reserved'
            """
        ),
        {"id": attempt_id, "reason": (reason or "unknown")[:200]},
    )


def in_flight_count(conn: Any, tenant_id: str) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT count(*) FROM call_attempts
                WHERE tenant_id = :tid
                  AND state IN ('reserved','dialing','ringing','answered','live')
                  AND reserved_at >= now() - interval '2 hours'
                """
            ),
            {"tid": tenant_id},
        ).scalar()
        or 0
    )


def _card_wants_carrier_amd(attempt: dict[str, Any]) -> bool:
    """``card.outbound.carrier_amd`` for the agent placing this call.

    False on any failure. A card lookup that fails must not change how a dial is
    placed — the platform default already decided that, and this only widens it.
    """
    try:
        import mission as mission_mod

        card = mission_mod.card_for_bot(attempt.get("botId") or attempt.get("bot_id"))
        return bool(getattr(getattr(card, "outbound", None), "carrier_amd", False))
    except Exception:
        logger.debug("carrier_amd lookup failed for attempt %s", attempt.get("id"), exc_info=True)
        return False


#: Exceptions that mean *this code is wrong*, not *the world is wrong*.
#:
#: :func:`place` promises never to raise, and the promise is worth keeping only
#: for operational failures — a number the carrier will not accept, a database
#: that is not answering, a carrier client that will not import. A ``TypeError``
#: from a bad argument is a bug in the caller, and a dialler that swallowed it
#: would report ``placed: false`` for a broken deployment and look exactly like
#: a carrier having a bad afternoon. Those keep travelling up the stack.
_BUG_EXCEPTIONS = (
    TypeError,
    AttributeError,
    IndexError,
    NameError,
    AssertionError,
    KeyError,
)


def _ctx(attempt: dict[str, Any]) -> str:
    """Campaign and case identifiers for a log line, best effort.

    An operational failure inside :func:`place` becomes a return value, so the
    log line is the only place an operator learns *whose* dial did not happen.
    """
    context = attempt.get("context")
    context = context if isinstance(context, dict) else {}
    return (
        f"customer={attempt.get('customerId') or attempt.get('customer_id') or '?'} "
        f"campaign={attempt.get('campaignRunId') or attempt.get('campaign_run_id') or '-'} "
        f"case={context.get('caseId') or attempt.get('decisionId') or '-'} "
        f"objective={attempt.get('objective') or '-'}"
    )


def _failed(attempt_id: str, reason: str) -> dict[str, Any]:
    """The result shape a caller gets instead of an exception."""
    return {
        "placed": False,
        "state": STATE_FAILED,
        "reason": reason,
        "attemptId": attempt_id,
    }


def _fail_quietly(engine: Any, attempt_id: str, reason: str) -> None:
    """Move the attempt out of ``reserved`` if the database will let us.

    Best effort by construction. This runs on paths where the database is often
    the thing that broke, and a bookkeeping write that raised would hand the
    caller back the exception :func:`place` just promised it would not — while
    leaving the row in ``reserved``, the one state the Closer skips.
    """
    try:
        with engine.begin() as conn:
            fail(conn, attempt_id, reason=reason[:400])
    except Exception:
        logger.exception("outbound %s: could not mark the attempt failed", attempt_id)


def place(
    engine: Any,
    attempt: dict[str, Any],
    *,
    to_phone: str,
    custom: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Dial. Returns ``{"placed": bool, "state": str, ...}``; never raises.

    The fleet gate is checked in its own transaction immediately before the
    carrier call, not at plan time, for the same reason ``enact`` re-runs the
    contact gate at send time: capacity is a fact about now.

    "Never raises" is a contract, not a hope
    ----------------------------------------
    Every caller relies on it and most of them call this undefended.
    ``campaigns.process_one`` commits the attempt counter before dialling, so a
    throw from here leaves a target marked ``dialing`` that nothing will ever
    claim again — the same silent strand ``cadence.process_one`` had to grow a
    recovery path for. So every region that can fail operationally is wrapped:
    both ``engine.begin()`` blocks, the carrier client import, the E.164
    conversion and the carrier call. Each returns a failure result of the shape
    a provider failure already returns, and logs at ERROR with the campaign and
    case the dial belonged to.

    What is *not* wrapped is a bug. ``attempt["id"]`` and ``attempt["tenantId"]``
    are read before anything is guarded, and :data:`_BUG_EXCEPTIONS` is
    re-raised out of every guarded region: a contract that turned a caller's
    programming error into a quiet ``placed: false`` would be worse than one
    that was never kept.
    """
    # Unguarded on purpose: a caller that hands us an attempt without these has
    # a bug, and the KeyError is the honest answer to it.
    attempt_id = attempt["id"]
    tenant_id = attempt["tenantId"]

    # Reserved rows count themselves, so the comparison is `>` not `>=`.
    #
    # No lock, and that is not an oversight. `reserve()` commits on its own
    # short transaction before this function is ever called, so every dial that
    # is concurrently in flight already exists as a committed `reserved` row and
    # is already inside this count. Two workers arriving together therefore see
    # each other rather than racing: the classic count-then-act window is closed
    # by the ordering of the writes, not by mutual exclusion.
    #
    # Which also answers section 18.4 of the design doc. A Redis token bucket
    # would be a second store on the dial path, with its own partition
    # behaviour, guarding a number whose source of truth is these rows. It buys
    # nothing here; a rate limiter earns its keep when the *rate* is what needs
    # bounding across tenants, and what this bounds is a live count of rows we
    # own. The cap is fleet-wide already, because the count is.
    try:
        with engine.begin() as conn:
            live = in_flight_count(conn, tenant_id)
            if live > max_in_flight():
                suppress(conn, attempt_id, "fleet_busy")
                logger.info(
                    "outbound %s deferred: %s attempts in flight (cap %s)",
                    attempt_id,
                    live,
                    max_in_flight(),
                )
                return {"placed": False, "state": STATE_SUPPRESSED, "reason": "fleet_busy",
                        "attemptId": attempt_id}
    except _BUG_EXCEPTIONS:
        raise
    except Exception as exc:
        # The gate could not be read, so we do not know whether there is room.
        # Refusing is the only safe answer: the alternative is a fleet cap that
        # stops applying exactly when the database is already struggling.
        logger.error(
            "outbound %s: the fleet gate could not be read · %s · %s",
            attempt_id,
            _ctx(attempt),
            exc,
            exc_info=True,
        )
        _fail_quietly(engine, attempt_id, f"fleet_gate_unavailable: {exc}")
        return _failed(attempt_id, "fleet_gate_unavailable")

    try:
        from voice import twilio_ops
    except _BUG_EXCEPTIONS:
        raise
    except Exception as exc:
        logger.error(
            "outbound %s: the carrier client would not import · %s · %s",
            attempt_id,
            _ctx(attempt),
            exc,
            exc_info=True,
        )
        _fail_quietly(engine, attempt_id, f"carrier_client_unavailable: {exc}")
        return _failed(attempt_id, "carrier_client_unavailable")

    params = {
        "call_type": "outbound",
        "attempt_id": attempt_id,
        "objective": attempt.get("objective") or "",
        **{k: str(v) for k, v in (custom or {}).items() if v is not None},
    }
    if attempt.get("customerId"):
        params["customer_id"] = str(attempt["customerId"])
    if attempt.get("accountId"):
        params["account_id"] = str(attempt["accountId"])
    if attempt.get("decisionId"):
        params["treatment_decision_id"] = str(attempt["decisionId"])
    if attempt.get("missionId"):
        params["mission_id"] = str(attempt["missionId"])

    # `customers.phone_primary` holds bare digits because that is what the
    # WhatsApp Graph API wants. Twilio rejects the same value as an invalid
    # number, so every dial to a correctly stored Indian mobile would have
    # failed at the carrier with error 21211 — and, before `call_attempts`,
    # failed invisibly.
    try:
        dial_to = to_e164(to_phone)
    except _BUG_EXCEPTIONS:
        raise
    except Exception as exc:  # pragma: no cover - to_e164 is total over strings
        logger.error(
            "outbound %s: number normalisation failed · %s · %s",
            attempt_id,
            _ctx(attempt),
            exc,
            exc_info=True,
        )
        _fail_quietly(engine, attempt_id, f"invalid_number: {exc}")
        return _failed(attempt_id, "invalid_number")

    # `to_e164` leaves anything it does not recognise untouched rather than
    # mangling it, which for a value with no digits in it at all means an empty
    # string. Dialling that is a guaranteed carrier rejection with a worse error
    # message, so it is caught here and recorded against the attempt instead.
    if not dial_to:
        logger.error(
            "outbound %s: %r is not a dialable number · %s",
            attempt_id,
            to_phone,
            _ctx(attempt),
        )
        _fail_quietly(engine, attempt_id, "invalid_number")
        return _failed(attempt_id, "invalid_number")

    # Caller ID. A configured pool wins; otherwise the deployment's single
    # TWILIO_PHONE_NUMBER, which is what every dial used before pools existed.
    from_number: str | None = None
    pool_name = attempt.get("numberPool")
    if pool_name:
        try:
            with engine.begin() as conn:
                picked = pick_number(conn, tenant_id=tenant_id, pool_name=pool_name)
            if picked:
                from_number = picked["e164"]
            else:
                logger.warning(
                    "outbound %s: pool %r has no active number — using the default",
                    attempt_id,
                    pool_name,
                )
        except Exception:
            # Not fatal: a caller ID we could not pick falls back to the
            # deployment's own number, which is what every dial used before
            # pools existed.
            logger.exception("outbound %s: number pool lookup failed", attempt_id)

    try:
        result = twilio_ops.start_outbound_call(
            to=dial_to,
            custom=params,
            # The env flag is the platform default; the card may turn it on for
            # its own missions. `carrier_amd` was a schema field with no reader
            # at all — an operator could tick it, publish, see the diff and get
            # exactly the detection they had before.
            #
            # Or-ed rather than overriding, and only in the permissive
            # direction: carrier AMD adds a second verdict alongside the in-band
            # detector, so a card enabling it cannot make detection worse, while
            # a card *disabling* what the platform turned on would let an
            # authored field weaken an operational safeguard.
            machine_detection=amd_enabled() or _card_wants_carrier_amd(attempt),
            from_number=from_number,
        )
    except twilio_ops.OutboundDisabled:
        # Not a failure. The master switch is off, so we declined to dial —
        # nothing reached the carrier and retrying changes nothing until an
        # operator turns it on. Recording it as `failed` would quietly deflate
        # answer rate, the metric the whole outbound operation is judged on,
        # every time the switch was off. Suppressed is what "we chose not to"
        # already means everywhere else in this module.
        #
        # Discovered here rather than pre-flighted before the fleet gate, so
        # there is exactly one place that decides whether a dial is permitted.
        # A second check up here would be a second thing to keep in agreement.
        logger.info(
            "outbound %s suppressed: the outbound switch is OFF · %s",
            attempt_id,
            _ctx(attempt),
        )
        try:
            with engine.begin() as conn:
                suppress(conn, attempt_id, "outbound_disabled")
        except _BUG_EXCEPTIONS:
            raise
        except Exception:
            # Losing the bookkeeping is not a reason to report a dial we did
            # not make, so the result stands either way.
            logger.exception("outbound %s: could not record the switch refusal", attempt_id)
        return {"placed": False, "state": STATE_SUPPRESSED, "reason": "outbound_disabled",
                "attemptId": attempt_id}
    except Exception as exc:
        # The carrier boundary is deliberately not filtered through
        # `_BUG_EXCEPTIONS`: a third-party client raising `TypeError` is a fact
        # about their SDK, not evidence of a bug in ours, and either way this
        # dial genuinely did not happen.
        logger.exception("outbound %s dial failed · %s", attempt_id, _ctx(attempt))
        _fail_quietly(engine, attempt_id, str(exc))
        return {"placed": False, "state": STATE_FAILED, "reason": "dial_failed",
                "attemptId": attempt_id}

    call_sid = str(result.get("callSid") or "")
    try:
        _mark_dialing(engine, attempt_id, result, pool_name, twilio_ops)
    except _BUG_EXCEPTIONS:
        raise
    except Exception as exc:
        # The borrower's phone is ringing and we cannot write down that it is.
        # Reporting `placed: true` would be the more flattering answer and the
        # wrong one — the row is still `reserved`, so nothing downstream will
        # treat this as a live call, and the caller has to hear that. The stale
        # sweep reaps the row; ERROR is what tells an operator why.
        logger.error(
            "outbound %s: the call was placed but could not be recorded · %s · %s",
            attempt_id,
            _ctx(attempt),
            exc,
            exc_info=True,
        )
        unrecorded = _failed(attempt_id, "state_write_failed")
        unrecorded["to"] = dial_to
        unrecorded["callSid"] = call_sid
        return unrecorded
    logger.info("outbound %s placed call_sid=%s", attempt_id, call_sid or "?")
    return {
        "placed": True,
        "state": STATE_DIALING,
        "attemptId": attempt_id,
        "to": dial_to,
        "callSid": call_sid,
        "status": result.get("status"),
    }


def _mark_dialing(
    engine: Any,
    attempt_id: str,
    result: dict[str, Any],
    pool_name: str | None,
    twilio_ops: Any,
) -> None:
    """Bind the carrier's call id to the reserved row."""
    call_sid = str(result.get("callSid") or "")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE call_attempts
                SET state = 'dialing', placed_at = now(),
                    provider_call_id = :sid, provider_status = :status,
                    from_number = :from_number, number_pool = :number_pool,
                    updated_at = now()
                WHERE id = :id AND state = 'reserved'
                """
            ),
            {
                "id": attempt_id,
                "sid": call_sid or None,
                "status": str(result.get("status") or "") or None,
                "from_number": result.get("from") or twilio_ops.twilio_phone() or None,
                "number_pool": pool_name,
            },
        )


def fail(conn: Any, attempt_id: str, *, reason: str) -> None:
    conn.execute(
        text(
            """
            UPDATE call_attempts
            SET state = 'failed', provider_error = :reason,
                ended_at = now(), updated_at = now()
            WHERE id = :id AND state IN ('reserved','dialing','ringing')
            """
        ),
        {"id": attempt_id, "reason": reason[:400]},
    )


# ---------------------------------------------------------------------------
# The status webhook's state machine
# ---------------------------------------------------------------------------


def apply_provider_status(
    conn: Any,
    *,
    provider_call_id: str,
    status: str,
    provider: str = "twilio",
    duration_sec: int | None = None,
    error_code: str | None = None,
    answered_by: str | None = None,
) -> dict[str, Any] | None:
    """Drive one attempt's state machine from a carrier callback.

    Idempotent and order-insensitive. Twilio retries callbacks and does not
    guarantee ordering, so the write is guarded by ``_rank``: a late ``ringing``
    cannot overwrite a ``completed`` that already landed, and a repeated
    terminal callback is a no-op rather than a second set of timings.

    Returns the row as it now stands, or None when the call id is unknown to us
    — which is the normal case for an inbound call and must not be an error.
    """
    row = conn.execute(
        text(
            """
            SELECT id, state, placed_at, answered_at, answered_by
            FROM call_attempts
            WHERE provider = :provider AND provider_call_id = :sid
            FOR UPDATE
            """
        ),
        {"provider": provider, "sid": provider_call_id},
    ).mappings().first()
    if row is None:
        return None

    current = str(row["state"])
    mapped = _TWILIO_STATUS.get((status or "").strip().lower())
    if mapped is None:
        logger.info("outbound: unmapped carrier status %r for %s", status, row["id"])
        return dict(row)

    # A carrier failure caused by the number itself is a different fact from a
    # carrier failure caused by the carrier, and only one of them should retire
    # the phone slot.
    if mapped == STATE_FAILED and (error_code or "").strip() in _INVALID_NUMBER_CODES:
        mapped = STATE_INVALID_NUMBER

    if _rank(mapped) < _rank(current):
        logger.debug(
            "outbound %s ignoring out-of-order %s behind %s", row["id"], mapped, current
        )
        return dict(row)
    if current in TERMINAL and mapped in TERMINAL:
        # First terminal answer wins; a retried callback must not re-stamp times.
        return dict(row)

    coarse = _ANSWERED_BY.get((answered_by or "").strip().lower()) if answered_by else None

    # `completed` from the carrier means answered-then-ended. A zero-duration
    # completion is a call that connected and produced nothing; it is still a
    # connect for reach purposes, which is why duration is recorded rather than
    # used to reclassify the state.
    sets = [
        "state = :state",
        "provider_status = :provider_status",
        "updated_at = now()",
    ]
    params: dict[str, Any] = {
        "id": row["id"],
        "state": mapped,
        "provider_status": (status or "")[:64],
    }
    if error_code:
        sets.append("provider_error = :error_code")
        params["error_code"] = str(error_code)[:64]
    if coarse:
        sets.append("answered_by = COALESCE(answered_by, :answered_by)")
        params["answered_by"] = coarse
    if mapped == STATE_ANSWERED and row["answered_at"] is None:
        sets.append("answered_at = now()")
        # Ring time is the only place the carrier gives us dial-to-answer, and
        # it is a direct input to per-hour reachability.
        sets.append(
            "ring_sec = COALESCE(ring_sec, "
            "GREATEST(0, EXTRACT(EPOCH FROM (now() - placed_at))::int))"
        )
    if mapped in TERMINAL:
        sets.append("ended_at = COALESCE(ended_at, now())")
        if duration_sec is not None:
            sets.append("talk_sec = COALESCE(talk_sec, :duration)")
            params["duration"] = max(0, int(duration_sec))
        if row["answered_at"] is None and mapped != STATE_COMPLETED:
            sets.append(
                "ring_sec = COALESCE(ring_sec, "
                "GREATEST(0, EXTRACT(EPOCH FROM (now() - placed_at))::int))"
            )

    conn.execute(
        text(f"UPDATE call_attempts SET {', '.join(sets)} WHERE id = :id"), params
    )
    return conn.execute(
        text("SELECT * FROM call_attempts WHERE id = :id"), {"id": row["id"]}
    ).mappings().first()


# ---------------------------------------------------------------------------
# Signals from the voice runtime
# ---------------------------------------------------------------------------


def bind_interaction(
    conn: Any,
    *,
    attempt_id: str | None = None,
    provider_call_id: str | None = None,
    interaction_id: str,
    provider: str = "twilio",
) -> bool:
    """Media connected: join the attempt to the interaction it produced.

    Also advances ``dialing``/``ringing``/``answered`` to ``live``. Without this
    join a completed call and the conversation it contained sit in two tables
    with nothing linking them, which is the state the product was in.
    """
    if not attempt_id and not provider_call_id:
        return False
    where = "id = :attempt_id" if attempt_id else "provider = :provider AND provider_call_id = :sid"
    result = conn.execute(
        text(
            f"""
            UPDATE call_attempts
            SET interaction_id = COALESCE(interaction_id, :ix),
                state = CASE WHEN state IN ('dialing','ringing','answered')
                             THEN 'live' ELSE state END,
                answered_at = COALESCE(answered_at, now()),
                updated_at = now()
            WHERE {where}
            """
        ),
        {
            "ix": interaction_id,
            "attempt_id": attempt_id,
            "provider": provider,
            "sid": provider_call_id,
        },
    )
    return bool(result.rowcount)


def mark(
    conn: Any,
    attempt_id: str,
    *,
    answered_by: str | None = None,
    right_party: bool | None = None,
    state: str | None = None,
) -> None:
    """Record what the runtime learned that the carrier cannot tell us.

    ``right_party`` is the one that matters: it is what makes RPC rate — the
    metric every collections operation actually manages — computable at all.
    """
    sets = ["updated_at = now()"]
    params: dict[str, Any] = {"id": attempt_id}
    if answered_by:
        sets.append("answered_by = :answered_by")
        params["answered_by"] = _ANSWERED_BY.get(answered_by, answered_by)[:16]
    if right_party is not None:
        sets.append("right_party = :right_party")
        params["right_party"] = bool(right_party)
    if state:
        # Never walk backwards: a runtime signal arriving after the carrier's
        # terminal callback must not reopen a closed attempt. Bound parameter
        # rather than an interpolated IN-list — the set is ours, but building
        # SQL by string-joining values is the habit that eventually meets one
        # that is not.
        sets.append("state = :state")
        params["state"] = state
        params["terminal"] = list(TERMINAL)
        conn.execute(
            text(
                f"UPDATE call_attempts SET {', '.join(sets)} "
                f"WHERE id = :id AND NOT (state = ANY(:terminal))"
            ),
            params,
        )
        return
    if len(sets) == 1:
        return
    conn.execute(text(f"UPDATE call_attempts SET {', '.join(sets)} WHERE id = :id"), params)


def sweep_stale(engine: Any) -> int:
    """Reap attempts whose carrier callback never arrived.

    A dropped tunnel, a failed signature check or a process killed between
    ``calls.create`` and its response would otherwise leave a row in flight
    forever, holding a slot in the fleet gate and never reaching the Closer.
    Marked ``failed`` rather than deleted: an attempt we cannot account for is
    evidence, and pretending it never happened is how a reach metric quietly
    becomes optimistic.
    """
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE call_attempts
                SET state = 'failed',
                    provider_error = COALESCE(provider_error, 'no_carrier_callback'),
                    ended_at = now(), updated_at = now()
                WHERE state IN ('reserved','dialing','ringing','answered','live')
                  AND reserved_at < :cutoff
                """
            ),
            {"cutoff": _now() - stale_after()},
        )
        reaped = int(result.rowcount or 0)
    if reaped:
        logger.warning("outbound: reaped %s stale attempt(s)", reaped)
    return reaped


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def pick_number(conn: Any, *, tenant_id: str, pool_name: str | None) -> dict[str, Any] | None:
    """Least-recently-used active number from the named pool.

    Three problems this solves, and only the first is obvious:

    * **TRAI.** BFSI service and transactional calls must originate from the
      1600 series, and one ``TWILIO_PHONE_NUMBER`` in the environment cannot be
      two series at once.
    * **Multi-tenancy.** Two banks on one deployment cannot share a caller ID
      without one of them appearing to call the other's customers.
    * **Spam decay.** A number enough handsets have flagged simply stops
      connecting. Rotating LRU spreads the load; ``answer_rate_7d`` is what
      eventually lets a bad one be retired on evidence rather than on a hunch.

    Returns None when no pool is configured, which is the normal state today —
    the caller then falls back to ``TWILIO_PHONE_NUMBER`` exactly as before.
    """
    if not pool_name:
        return None
    row = conn.execute(
        text(
            """
            SELECT n.id, n.e164, p.kind
            FROM pool_numbers n
            JOIN number_pools p ON p.id = n.pool_id
            WHERE p.tenant_id = :tid AND p.name = :pool AND p.enabled IS TRUE
              AND n.state = 'active'
            ORDER BY n.last_used_at ASC NULLS FIRST
            FOR UPDATE OF n SKIP LOCKED
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "pool": pool_name},
    ).mappings().first()
    if row is None:
        return None
    # Only `last_used_at`, which is what LRU rotation turns on. `attempts_7d` is
    # deliberately not incremented here: incrementing per dial and never decaying
    # produced a lifetime counter with `_7d` in its name, which reads as a rate
    # on any dashboard that renders it. `refresh_pool_health` recomputes both it
    # and `answer_rate_7d` from `call_attempts` over an actual seven days.
    conn.execute(
        text("UPDATE pool_numbers SET last_used_at = now(), updated_at = now() WHERE id = :id"),
        {"id": row["id"]},
    )
    return {"e164": row["e164"], "kind": row["kind"], "pool": pool_name}


def get(conn: Any, attempt_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        text("SELECT * FROM call_attempts WHERE id = :id"), {"id": attempt_id}
    ).mappings().first()
    return dict(row) if row else None


def by_provider_call(conn: Any, provider_call_id: str, provider: str = "twilio") -> dict[str, Any] | None:
    row = conn.execute(
        text(
            "SELECT * FROM call_attempts WHERE provider = :p AND provider_call_id = :sid"
        ),
        {"p": provider, "sid": provider_call_id},
    ).mappings().first()
    return dict(row) if row else None


def reach_stats(conn: Any, *, tenant_id: str, days: int = 14) -> dict[str, Any]:
    """The numbers that did not exist before this table.

    Suppressed attempts are excluded from the reach denominator and reported
    separately: a call the gate refused is not a call the borrower ignored, and
    folding the two together would make a compliant week look like an
    unreachable book.
    """
    row = conn.execute(
        text(
            """
            SELECT
              count(*) FILTER (WHERE state <> 'suppressed')                   AS attempts,
              count(*) FILTER (WHERE state = 'suppressed')                    AS suppressed,
              count(*) FILTER (WHERE answered_at IS NOT NULL)                 AS answered,
              count(*) FILTER (WHERE right_party IS TRUE)                     AS right_party,
              count(*) FILTER (WHERE answered_by = 'machine')                 AS voicemail,
              count(*) FILTER (WHERE state = 'invalid_number')                AS invalid_number,
              count(*) FILTER (WHERE state = 'no_answer')                     AS no_answer,
              count(*) FILTER (WHERE state = 'busy')                          AS busy,
              avg(ring_sec) FILTER (WHERE ring_sec IS NOT NULL)               AS avg_ring_sec,
              avg(talk_sec) FILTER (WHERE talk_sec > 0)                       AS avg_talk_sec,
              sum(talk_sec)                                                   AS talk_sec_total
            FROM call_attempts
            WHERE tenant_id = :tid
              AND reserved_at >= now() - make_interval(days => :days)
            """
        ),
        {"tid": tenant_id, "days": max(1, int(days))},
    ).mappings().first()
    stats = {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in dict(row or {}).items()}
    attempts = float(stats.get("attempts") or 0)
    answered = float(stats.get("answered") or 0)
    stats["answerRate"] = round(answered / attempts, 4) if attempts else None
    stats["rightPartyRate"] = (
        round(float(stats.get("right_party") or 0) / answered, 4) if answered else None
    )
    stats["attemptsPerConnect"] = round(attempts / answered, 2) if answered else None
    stats["windowDays"] = int(days)
    return stats


def hourly_reach(conn: Any, *, customer_id: str, days: int = 90) -> list[dict[str, Any]]:
    """Per-hour answer rate for one borrower, in their own local time.

    This is the query ``treatment/features.responsive_hours`` should eventually
    read: it has a denominator. Timezone comes off the customer row rather than
    being assumed, because "when is this borrower reachable" is a question about
    their day, not about UTC.
    """
    rows = conn.execute(
        text(
            """
            SELECT
              -- Same guard as contact_policy: `customers.timezone` holds display
              -- labels ("Asia/Kolkata (IST)") in seeded data, and an unknown zone
              -- here does not fail this row — it aborts the transaction.
              EXTRACT(HOUR FROM (a.reserved_at AT TIME ZONE COALESCE(
                (SELECT n.name FROM pg_timezone_names n
                  WHERE n.name = btrim(split_part(COALESCE(c.timezone, ''), '(', 1))
                  LIMIT 1),
                'Asia/Kolkata')))::int AS hour,
              count(*)                                        AS attempts,
              count(*) FILTER (WHERE a.answered_at IS NOT NULL) AS answered
            FROM call_attempts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.customer_id = :cid
              AND a.state <> 'suppressed'
              AND a.reserved_at >= now() - make_interval(days => :days)
            GROUP BY 1
            ORDER BY 1
            """
        ),
        {"cid": customer_id, "days": max(1, int(days))},
    ).mappings().all()
    return [
        {
            "hour": int(r["hour"]),
            "attempts": int(r["attempts"]),
            "answered": int(r["answered"]),
            "answerRate": round(int(r["answered"]) / int(r["attempts"]), 4)
            if r["attempts"]
            else None,
        }
        for r in rows
    ]


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)


# ---------------------------------------------------------------------------
# Number-pool health
# ---------------------------------------------------------------------------

#: A number needs this many attempts inside the window before its answer rate is
#: allowed to say anything. Three dials and no answer is a Tuesday; forty dials
#: and no answer is a number the carriers have stopped putting through.
POOL_MIN_ATTEMPTS = 30

#: Below this connect rate, with enough volume behind it, the number rests.
POOL_ANSWER_FLOOR = 0.05

#: How long it rests. Long enough for handset spam lists to age, short enough
#: that a pool of four numbers is not permanently a pool of three.
POOL_COOL_HOURS = 168


def refresh_pool_health(
    conn: Any,
    *,
    tenant_id: str,
    min_attempts: int = POOL_MIN_ATTEMPTS,
    answer_floor: float = POOL_ANSWER_FLOOR,
    cool_hours: int = POOL_COOL_HOURS,
) -> dict[str, int]:
    """Recompute the 7-day pool stats and rotate spam-decayed caller IDs.

    Section 8.2 of the design doc justifies number pools on three grounds, and
    the third — *"a number that has been marked spam by enough handsets stops
    connecting, and there is currently no way to observe that, let alone
    rotate"* — was the one nothing implemented. The columns shipped empty:
    ``answer_rate_7d`` was never computed, no number was ever moved to
    ``cooling``, and ``attempts_7d`` was incremented on every dial and never
    decayed, which made it a lifetime counter wearing a rate's name.

    Two movements, and the second is the one that is easy to leave out:

    * **active -> cooling** when there are enough attempts behind the number to
      judge it and its answer rate has collapsed. The volume gate comes first: a
      rate over four dials is noise, and cooling a good number on noise shrinks
      the pool, which raises the load on the survivors, which is how a rotation
      scheme eats itself.
    * **cooling -> active** once the rest is over. A cooling number takes no
      attempts, so its window empties and it can never again clear the volume
      gate. Without this, the first movement is a one-way door and every caller
      ID eventually ends up behind it.

    ``retired`` is left alone in both directions. Retirement is a human decision
    about a number we intend to hand back to the carrier, and a sweep that could
    undo it would make it mean nothing.
    """
    counts = {"scored": 0, "cooled": 0, "restored": 0}
    params = {
        "tid": tenant_id,
        "min_attempts": max(1, int(min_attempts)),
        "floor": float(answer_floor),
        "hours": max(1, int(cool_hours)),
    }

    scored = conn.execute(
        text(
            """
            WITH windowed AS (
              SELECT from_number,
                     count(*)                                          AS attempts,
                     count(*) FILTER (WHERE answered_at IS NOT NULL)   AS answered
              FROM call_attempts
              WHERE tenant_id = :tid
                AND placed_at >= now() - interval '7 days'
              GROUP BY from_number
            )
            UPDATE pool_numbers n
            SET attempts_7d       = s.attempts,
                answer_rate_7d    = s.rate,
                health_checked_at = now(),
                updated_at        = now()
            FROM (
              SELECT pn.id,
                     COALESCE(w.attempts, 0) AS attempts,
                     CASE WHEN COALESCE(w.attempts, 0) > 0
                          THEN round(w.answered::numeric / w.attempts, 4)
                     END AS rate
              FROM pool_numbers pn
              JOIN number_pools p ON p.id = pn.pool_id AND p.tenant_id = :tid
              LEFT JOIN windowed w ON w.from_number = pn.e164
            ) s
            WHERE n.id = s.id
            """
        ),
        params,
    )
    counts["scored"] = int(scored.rowcount or 0)

    cooled = conn.execute(
        text(
            """
            UPDATE pool_numbers n
            SET state = 'cooling',
                state_changed_at = now(),
                updated_at = now(),
                note = 'answer rate ' || COALESCE(n.answer_rate_7d::text, '?')
                       || ' over ' || n.attempts_7d || ' attempts'
            FROM number_pools p
            WHERE p.id = n.pool_id
              AND p.tenant_id = :tid
              AND n.state = 'active'
              AND n.attempts_7d >= :min_attempts
              AND n.answer_rate_7d IS NOT NULL
              AND n.answer_rate_7d < :floor
            """
        ),
        params,
    )
    counts["cooled"] = int(cooled.rowcount or 0)

    restored = conn.execute(
        text(
            """
            UPDATE pool_numbers n
            SET state = 'active',
                state_changed_at = now(),
                updated_at = now(),
                note = NULL
            FROM number_pools p
            WHERE p.id = n.pool_id
              AND p.tenant_id = :tid
              AND n.state = 'cooling'
              AND n.state_changed_at < now() - make_interval(hours => :hours)
            """
        ),
        params,
    )
    counts["restored"] = int(restored.rowcount or 0)

    if counts["cooled"] or counts["restored"]:
        logger.info(
            "number pool health · tenant=%s · scored=%s cooled=%s restored=%s",
            tenant_id,
            counts["scored"],
            counts["cooled"],
            counts["restored"],
        )
    return counts


def sweep_pool_health(engine: Any, *, tenant_id: str | None = None) -> dict[str, int]:
    """Transaction wrapper for :func:`refresh_pool_health`. Never raises.

    Sweeps **every** tenant that owns a pool rather than the ambient one. The
    worker drains a queue that spans tenants and never binds one, so resolving
    the tenant from ``current_tenant()`` would have kept exactly one bank's
    caller IDs healthy and left every other bank's rotting quietly — with the
    columns populated, which is the version of the bug that survives review.
    """
    totals = {"scored": 0, "cooled": 0, "restored": 0}
    try:
        with engine.begin() as conn:
            if tenant_id:
                tenants = [tenant_id]
            else:
                tenants = [
                    str(r[0])
                    for r in conn.execute(
                        text("SELECT DISTINCT tenant_id FROM number_pools WHERE enabled IS TRUE")
                    ).fetchall()
                ]
            for tid in tenants:
                counts = refresh_pool_health(conn, tenant_id=tid)
                for key in totals:
                    totals[key] += counts.get(key, 0)
        return totals
    except Exception:
        logger.exception("pool health sweep failed")
        return totals
