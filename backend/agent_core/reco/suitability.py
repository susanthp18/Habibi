"""The mis-selling audit trail — §9.7's precondition for offering anything.

`capture.evaluate_product_eligibility` already answers *"is this borrower
eligible for this product"* from the catalog's rules. This module answers the
different question a supervisor and an inspection actually ask, which is whether
the product was **suitable** for them, who says so, and on what evidence.

The two are not interchangeable and the design note is explicit about why: an
explicit consent artefact **does not cure unsuitability**. A borrower can be
perfectly eligible for a top-up loan under every catalog rule and still be a
borrower to whom selling one is the textbook mis-selling fact pattern, carrying
refund *plus* compensation. Eligibility is a property of the product; suitability
is a finding about the person, and a finding needs an assessor and a date.

**An absent finding is a refusal, not a pass**, on the same rule §8.12 applies to
an unevaluable promotion gate. That extends to the table: a database that cannot
say whether a borrower was assessed has not said they were. Every deployment is
in that state until `sql/32_offer_absorption.sql` is applied, which is why the
reason string names the file.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from sqlalchemy import text

from agent_core.clock import as_utc
from agent_core.clock import utc_now

logger = logging.getLogger(__name__)

#: Prefix on every reason this module produces, so a decision log's `excluded`
#: map can be filtered on one string. Matches the `eligibility:` convention
#: `agent_core/reco/engine.py` already uses for the catalog vetoes.
PREFIX = "suitability:"

REASON_UNEVALUABLE = (
    f"{PREFIX}no `suitability_assessments` table on this database "
    "(sql/32_offer_absorption.sql) — an unevaluable finding is a refusal"
)
REASON_ABSENT = f"{PREFIX}no assessment on file"
REASON_EXPIRED = f"{PREFIX}the assessment on file has expired"
REASON_UNSUITABLE = f"{PREFIX}assessed unsuitable"
REASON_UNREADABLE = f"{PREFIX}the assessment could not be read"


def current(
    conn: Any, *, customer_id: str, product_id: str, tenant_id: str | None = None
) -> Mapping[str, Any] | None:
    """The most recent assessment for this borrower and product, or ``None``.

    Reads inside a savepoint: this runs on a connection the caller owns, in the
    middle of the reco pipeline, and on a database behind
    ``sql/32_offer_absorption.sql`` a failed read would abort the caller's
    transaction and take the decision-log INSERT with it (W0).

    Returns the row whether the verdict is ``suitable`` or ``unsuitable`` and
    whether or not it has expired. :func:`objection` decides what that means;
    this only reads, so a caller wanting to *display* the finding gets the real
    one rather than a filtered view of it.
    """
    from agent_core.treatment import schema_ready

    if conn is None or not schema_ready.suitability_ready(conn):
        return None
    import db

    try:
        with conn.begin_nested():
            row = conn.execute(
                text(
                    """
                    SELECT id, verdict, assessed_at, expires_at, assessor,
                           policy_version, evidence_ref
                    FROM suitability_assessments
                    WHERE tenant_id = :tenant
                      AND customer_id = :customer_id
                      AND product_id = :product_id
                    ORDER BY assessed_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "tenant": tenant_id or db.current_tenant(),
                    "customer_id": customer_id,
                    "product_id": product_id,
                },
            ).mappings().first()
    except Exception:
        logger.exception(
            "suitability lookup failed for %s/%s", customer_id, product_id
        )
        return None
    return dict(row) if row else None


def objection(
    conn: Any, *, customer_id: str, product_id: str, tenant_id: str | None = None
) -> str | None:
    """Why this product may not be offered to this borrower, or ``None``.

    Fails closed at every branch. The one thing this must never do is return
    ``None`` because something was unreadable — absence of evidence is what the
    whole table exists to stop being read as evidence of absence.
    """
    from agent_core.treatment import schema_ready

    if conn is None or not schema_ready.suitability_ready(conn):
        return REASON_UNEVALUABLE
    row = current(
        conn, customer_id=customer_id, product_id=product_id, tenant_id=tenant_id
    )
    if row is None:
        # Either nothing on file, or the read failed and said so in the log.
        # Both are the same answer to the caller and neither is a pass.
        return REASON_ABSENT
    if str(row.get("verdict")) != "suitable":
        return REASON_UNSUITABLE
    expires = row.get("expires_at")
    if expires is not None:
        at = as_utc(expires)
        if at is None:
            # A column we cannot read is not a window we can say has not closed.
            logger.warning("unreadable expires_at on assessment %s", row.get("id"))
            return REASON_UNREADABLE
        if at <= utc_now():
            return REASON_EXPIRED
    return None
