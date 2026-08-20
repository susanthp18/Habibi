"""Account feature vector for the authority matrix.

Candidates, the matrix and the log depend only on :class:`AccountAuthority`,
never on a table name. Unknown facts are ``None``, not zero — a borrower whose
tenure we do not know is not treated as a brand-new account.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import text

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "v1"

FEE_LATE = "late_fee"
FEE_BOUNCE = "bounce_charge"
FEE_SETTLEMENT = "settlement"
FEE_RESTRUCTURE = "restructuring"

FEE_TYPES = frozenset({FEE_LATE, FEE_BOUNCE, FEE_SETTLEMENT, FEE_RESTRUCTURE})

#: Holds that stop live goodwill. ``dispute`` is deliberately absent: a fee
#: waiver *is* often the open dispute, and treating it as a veto would make
#: in-policy close-on-the-call impossible.
SILENCING_HOLDS = frozenset({"hardship", "complaint", "bereavement", "legal"})


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class AccountAuthority:
    """What the matrix is allowed to know."""

    customer_id: str
    tenant_id: str
    account_id: str | None = None
    dpd: int | None = None
    outstanding: float | None = None
    product_type: str | None = None
    tenure_months: int | None = None
    posted_late_fee: float | None = None
    goodwill_12m: float = 0.0
    goodwill_count_12m: int = 0
    holds: tuple[str, ...] = ()
    identity_verified: bool = True

    def to_log(self) -> dict[str, Any]:
        return {
            "customerId": self.customer_id,
            "accountId": self.account_id,
            "dpd": self.dpd,
            "outstanding": self.outstanding,
            "productType": self.product_type,
            "tenureMonths": self.tenure_months,
            "postedLateFee": self.posted_late_fee,
            "goodwill12m": self.goodwill_12m,
            "goodwillCount12m": self.goodwill_count_12m,
            "holds": list(self.holds),
            "identityVerified": self.identity_verified,
        }


class FeatureProvider(Protocol):
    def build(
        self,
        conn: Any,
        *,
        customer_id: str,
        account_id: str | None = None,
    ) -> AccountAuthority: ...


class SqlFeatureProvider:
    """Postgres-backed provider. One round-trip of indexed reads."""

    def build(
        self,
        conn: Any,
        *,
        customer_id: str,
        account_id: str | None = None,
    ) -> AccountAuthority:
        import db

        tenant_id = db.current_tenant()
        account = conn.execute(
            text(
                """
                SELECT
                  a.id, a.dpd, a.outstanding, a.opened_on, p.type AS product_type
                FROM accounts a
                LEFT JOIN products p ON p.id = a.product_id
                WHERE a.customer_id = :cid
                  AND (CAST(:aid AS text) IS NULL OR a.id = CAST(:aid AS text))
                ORDER BY a.outstanding DESC NULLS LAST, a.id
                LIMIT 1
                """
            ),
            {"cid": customer_id, "aid": account_id},
        ).mappings().first()

        aid = (account["id"] if account else None) or account_id
        opened = _aware(account["opened_on"]) if account else None
        tenure = None
        if opened is not None:
            tenure = max(0, int((datetime.now(timezone.utc) - opened).days // 30))

        holds: tuple[str, ...] = ()
        posted_fee = None
        goodwill_sum = 0.0
        goodwill_n = 0
        if aid:
            hold_rows = conn.execute(
                text(
                    """
                    SELECT kind FROM treatment_holds
                    WHERE customer_id = :cid
                      AND released_at IS NULL
                      AND (account_id IS NULL OR account_id = :aid)
                      AND (expires_at IS NULL OR expires_at > now())
                    """
                ),
                {"cid": customer_id, "aid": aid},
            ).mappings().all()
            holds = tuple(sorted({str(r["kind"]) for r in hold_rows if r.get("kind")}))

            since = datetime.now(timezone.utc) - timedelta(days=365)
            fee_row = conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(amount), 0) AS amt
                    FROM ledger_entries
                    WHERE account_id = :aid
                      AND type = 'fee'
                      AND amount > 0
                      AND posted_at >= :since
                    """
                ),
                {"aid": aid, "since": since},
            ).mappings().first()
            posted_fee = _float(fee_row["amt"]) if fee_row else None
            if posted_fee == 0:
                posted_fee = None

            good = conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(ABS(amount)), 0) AS amt, COUNT(*) AS n
                    FROM ledger_entries
                    WHERE account_id = :aid
                      AND type = 'waiver'
                      AND posted_at >= :since
                    """
                ),
                {"aid": aid, "since": since},
            ).mappings().first()
            if good:
                goodwill_sum = float(good["amt"] or 0)
                goodwill_n = int(good["n"] or 0)

        return AccountAuthority(
            customer_id=customer_id,
            tenant_id=tenant_id,
            account_id=aid,
            dpd=int(account["dpd"]) if account and account["dpd"] is not None else None,
            outstanding=_float(account["outstanding"]) if account else None,
            product_type=(account["product_type"] if account else None) or None,
            tenure_months=tenure,
            posted_late_fee=posted_fee,
            goodwill_12m=goodwill_sum,
            goodwill_count_12m=goodwill_n,
            holds=holds,
        )


def build_features(
    conn: Any,
    *,
    customer_id: str,
    account_id: str | None = None,
    provider: FeatureProvider | None = None,
) -> AccountAuthority:
    impl = provider or SqlFeatureProvider()
    return impl.build(conn, customer_id=customer_id, account_id=account_id)
