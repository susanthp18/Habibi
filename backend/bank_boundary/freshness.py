"""Portfolio readiness — one resolver for features, veto, enactment, APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from bank_boundary import (
    C1_WAIT_ONLY_HOURS,
    C5_MANDATE_HOURS,
    C6_NON_CONTACTING_HOURS,
    C6_WAIT_ONLY_HOURS,
    C7_RESERVED_CAP_HOURS,
    C8_ENDPOINT_HOURS,
    C9_ROSTER_HOURS,
    DAY1_INBOUND,
    SHADOW_STREAK_DAYS,
    schema_ready,
)

WAIT_ONLY = "freshness:wait_only"
NON_CONTACTING = "freshness:non_contacting"
MANDATE_STALE = "freshness:mandate_stale"
ENDPOINT_STALE = "freshness:endpoint_stale"
#: The C8 feed itself has not been accepted inside its window. Distinct
#: from ENDPOINT_STALE, which is one borrower's consent snapshot: this is
#: the whole portfolio, and the fix is a feed run, not a consent record.
C8_FEED_STALE = "freshness:c8_feed_stale"
FIELD_STALE = "freshness:field_stale"
MFI_UNPROTECTED = "freshness:c10_absent"
C7_RESERVED = "freshness:c7_reserved_cap"


@dataclass(frozen=True)
class Readiness:
    wait_only: bool = False
    non_contacting: bool = False
    mandate_blocked: bool = False
    field_blocked: bool = False
    contacting_blocked: bool = False
    reserved_cap: bool = False
    shadow_unlocked: bool = False
    veto: str | None = None
    reasons: tuple[str, ...] = ()
    consecutive_ok: dict[str, int] = field(default_factory=dict)


def lag_hours(conn: Any, *, tenant_id: str, portfolio_id: str, code: str) -> float | None:
    if not schema_ready.w5_ready(conn):
        return None
    row = conn.execute(
        text(
            """
            SELECT last_accepted_at FROM bank_freshness
             WHERE tenant_id = :tid AND portfolio_id = :pid AND contract_code = :code
            """
        ),
        {"tid": tenant_id, "pid": portfolio_id or "", "code": code},
    ).scalar()
    if row is None:
        return None
    at = row if getattr(row, "tzinfo", None) else row.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - at).total_seconds() / 3600.0


def streak(conn: Any, *, tenant_id: str, portfolio_id: str, code: str) -> int:
    if not schema_ready.w5_ready(conn):
        return 0
    value = conn.execute(
        text(
            """
            SELECT consecutive_ok_days FROM bank_freshness
             WHERE tenant_id = :tid AND portfolio_id = :pid AND contract_code = :code
            """
        ),
        {"tid": tenant_id, "pid": portfolio_id or "", "code": code},
    ).scalar()
    return int(value or 0)


def resolve(
    conn: Any,
    *,
    tenant_id: str,
    portfolio_id: str = "",
    action: str | None = None,
    channel: str | None = None,
    endpoint: str | None = None,
    customer_id: str | None = None,
    product_category: str | None = None,
    mfi: bool = False,
) -> Readiness:
    """Encode §7.8 exactly. Missing schema does not invent a green book."""
    if not schema_ready.w5_ready(conn):
        if action == "represent_mandate":
            return Readiness(
                mandate_blocked=True,
                veto=MANDATE_STALE,
                reasons=("w5_schema_absent",),
            )
        if action == "field_visit" or channel == "field":
            return Readiness(
                field_blocked=True,
                veto=FIELD_STALE,
                reasons=("w5_schema_absent",),
            )
        return Readiness(
            wait_only=True,
            contacting_blocked=bool(channel),
            veto=WAIT_ONLY if channel else None,
            reasons=("w5_schema_absent",),
        )

    reasons: list[str] = []
    wait_only = False
    non_contacting = False
    mandate_blocked = False
    field_blocked = False
    contacting_blocked = False
    reserved_cap = False

    c6 = lag_hours(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code="C6")
    if c6 is None or c6 > C6_WAIT_ONLY_HOURS:
        wait_only = True
        reasons.append("C6>24h" if c6 is not None else "C6_absent")
    elif c6 > C6_NON_CONTACTING_HOURS:
        non_contacting = True
        reasons.append("C6>4h")

    c1 = lag_hours(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code="C1")
    if c1 is None or c1 > C1_WAIT_ONLY_HOURS:
        wait_only = True
        reasons.append("C1>48h" if c1 is not None else "C1_absent")

    c5 = lag_hours(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code="C5")
    if action == "represent_mandate" and (c5 is None or c5 > C5_MANDATE_HOURS):
        mandate_blocked = True
        reasons.append("C5>72h" if c5 is not None else "C5_absent")

    c8 = lag_hours(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code="C8")
    if channel and (c8 is None or c8 > C8_ENDPOINT_HOURS):
        contacting_blocked = True
        reasons.append("C8>24h" if c8 is not None else "C8_absent")

    c7 = lag_hours(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code="C7")
    if c7 is None or c7 > C7_RESERVED_CAP_HOURS:
        reserved_cap = True
        reasons.append("C7>6h" if c7 is not None else "C7_absent")
        if action == "field_visit" or channel == "field":
            field_blocked = True

    c9 = lag_hours(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code="C9")
    roster_expired = _roster_stale(conn, tenant_id=tenant_id)
    if action == "field_visit" or channel == "field":
        if c9 is None or c9 > C9_ROSTER_HOURS or roster_expired:
            field_blocked = True
            reasons.append("C9_roster_stale")

    is_mfi = mfi or (product_category or "").lower() in {"mfi", "microfinance"}
    if is_mfi and channel:
        c10 = lag_hours(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code="C10")
        if c10 is None or not customer_id or not _protection_present(
            conn, tenant_id=tenant_id, customer_id=customer_id
        ):
            contacting_blocked = True
            reasons.append("C10_absent_or_unmatched")

    if endpoint and _endpoint_stale(
        conn,
        tenant_id=tenant_id,
        endpoint=endpoint,
        channel=channel,
        customer_id=customer_id,
    ):
        contacting_blocked = True
        reasons.append("endpoint_consent_stale")

    streaks = {
        code: streak(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code=code)
        for code in DAY1_INBOUND
    }
    shadow_unlocked = all(v >= SHADOW_STREAK_DAYS for v in streaks.values())
    if action == "represent_mandate":
        inbound_ready = all(
            streak(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code=code)
            >= 1
            for code in ("C3", "C4", "C5")
        )
        from agent_core.treatment import config

        outbound_code = (
            "O2"
            if config.mandate_executor() == config.MANDATE_EXECUTOR_RAIL
            else "O6"
        )
        if not inbound_ready or not _binding_ready(
            conn,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            code=outbound_code,
        ):
            mandate_blocked = True
            reasons.append("mandate_contracts_unready")

    veto = None
    if mandate_blocked and action == "represent_mandate":
        veto = MANDATE_STALE
    elif field_blocked and (action == "field_visit" or channel == "field"):
        veto = FIELD_STALE
    elif contacting_blocked and channel:
        # Both arms of the old ternary returned ENDPOINT_STALE, so a missing
        # C8 *feed* -- a portfolio-level lag -- reported itself as a stale
        # endpoint, and every investigation went to bank_consent_snapshots
        # rather than to bank_freshness. Three causes, three labels.
        if "C10" in ",".join(reasons):
            veto = MFI_UNPROTECTED
        elif "C8" in ",".join(reasons):
            veto = C8_FEED_STALE
        else:
            veto = ENDPOINT_STALE
    elif wait_only and channel:
        veto = WAIT_ONLY
    elif non_contacting and channel:
        veto = NON_CONTACTING
    elif reserved_cap and channel and action not in {None, "wait", "represent_mandate"}:
        veto = C7_RESERVED

    return Readiness(
        wait_only=wait_only,
        non_contacting=non_contacting,
        mandate_blocked=mandate_blocked,
        field_blocked=field_blocked,
        contacting_blocked=contacting_blocked,
        reserved_cap=reserved_cap,
        shadow_unlocked=shadow_unlocked,
        veto=veto,
        reasons=tuple(reasons),
        consecutive_ok=streaks,
    )


def require_shadow_exit(
    conn: Any, *, tenant_id: str, portfolio_id: str = ""
) -> bool:
    """Five consecutive reconciled business days on C1/C2/C6/C8/C10."""
    return all(
        streak(conn, tenant_id=tenant_id, portfolio_id=portfolio_id, code=code)
        >= SHADOW_STREAK_DAYS
        for code in DAY1_INBOUND
    )


def _roster_stale(conn: Any, *, tenant_id: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM bank_agency_roster
             WHERE tenant_id = :tid AND expires_at <= now()
            LIMIT 1
            """
        ),
        {"tid": tenant_id},
    ).first()
    empty = conn.execute(
        text("SELECT 1 FROM bank_agency_roster WHERE tenant_id = :tid LIMIT 1"),
        {"tid": tenant_id},
    ).first()
    return empty is None or row is not None


def _binding_ready(
    conn: Any,
    *,
    tenant_id: str,
    portfolio_id: str,
    code: str,
) -> bool:
    state = conn.execute(
        text(
            """
            SELECT state FROM bank_contract_bindings
             WHERE tenant_id = :tid AND portfolio_id = :pid
               AND contract_code = :code
            """
        ),
        {"tid": tenant_id, "pid": portfolio_id, "code": code},
    ).scalar()
    return state in {"ready", "live"}


def _endpoint_stale(
    conn: Any,
    *,
    tenant_id: str,
    endpoint: str,
    channel: str | None,
    customer_id: str | None,
) -> bool:
    row = conn.execute(
        text(
            """
            SELECT known_from, permitted FROM bank_consent_snapshots
             WHERE tenant_id = :tid AND endpoint = :ep
               AND (CAST(:cid AS text) IS NULL OR customer_id = CAST(:cid AS text))
               AND purpose IN ('servicing','all')
               AND channel IN (CAST(:channel AS text), 'all')
             ORDER BY known_from DESC LIMIT 1
            """
        ),
        {
            "tid": tenant_id,
            "ep": endpoint,
            "channel": channel or "all",
            "cid": customer_id,
        },
    ).mappings().first()
    if row is None:
        return True
    if not bool(row["permitted"]):
        return True
    at = row["known_from"]
    at = at if getattr(at, "tzinfo", None) else at.replace(tzinfo=timezone.utc)
    hours = (datetime.now(timezone.utc) - at).total_seconds() / 3600.0
    return hours > C8_ENDPOINT_HOURS


def _protection_present(
    conn: Any, *, tenant_id: str, customer_id: str
) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1 FROM bank_protections
             WHERE tenant_id = :tid AND customer_id = :cid
               AND active IS TRUE
             ORDER BY known_from DESC LIMIT 1
            """
        ),
        {"tid": tenant_id, "cid": customer_id},
    ).first()
    return row is not None
