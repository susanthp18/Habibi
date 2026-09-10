"""Gates 14 and 15 — what was claimed before the run, and who signed it after.

§8.12's fifteen gates are mostly statistics. These two are not, and they are the
two that make the statistics mean anything:

    **14 · Pre-registration** — "threshold, primary endpoint and horizon,
    estimator, family size, alpha-spending schedule and stopping rule written to
    the registry **before** the challenger ran."

    **15 · Human sign-off** — "an independent validator **who is not the model's
    author**, with a written record; then maker-checker."

Neither is bureaucracy. A threshold chosen after seeing the lift is not a
threshold; a family size chosen after the looks is not multiplicity control; and
an estimator picked because it gave the best number voids the concentration
bound that estimator reports — §8.9 says so in as many words, which is why
``estimator`` is one of the columns rather than an implementation detail.

**What makes the claim checkable is W10a's seal.** The gate does not trust the
evaluation's word for when it was computed: ``computed_at`` lives inside the
body the HMAC covers, so moving it to predate a pre-registration invalidates the
seal, and the operator gets *both* objections rather than a green gate. Gate 2
and Gate 14 are one mechanism read twice.

**And the author check is a database constraint**, not a comparison here. The
same choice ``engine_config`` and ``retention_rules`` already made: maker-checker
that lives in application code is maker-checker that a script bypasses. The
functions below refuse first so the operator gets a sentence instead of an
``IntegrityError``, but the constraint is what holds.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import text

logger = logging.getLogger(__name__)

#: The field on an evaluation body naming the pre-registration it ran under.
PREREG_FIELD = "pre_registration_id"

#: The field naming the instant the evaluation was computed. Gate 14 compares it
#: to ``filed_at``, so it is required rather than optional: an evaluation that
#: will not say when it ran cannot be shown to have run second.
COMPUTED_AT_FIELD = "computed_at"


class PreRegistrationRefused(Exception):
    """Raised with the reason. The reason is the useful part."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def declare(
    conn: Any,
    *,
    tenant_id: str,
    target: str,
    primary_endpoint: str,
    horizon_days: int,
    estimator: str,
    threshold: float,
    threshold_basis: str,
    family_size: int,
    alpha_spending: str,
    stopping_rule: str,
    author: str,
    filed_by: str | None = None,
) -> dict[str, Any]:
    """File a pre-registration. Returns the row, whose id the evaluation carries.

    Nothing here is optional and nothing defaults, because every default would
    be a field somebody did not decide. The one thing this does *not* take is a
    challenger: Gate 14 is filed before the challenger exists, and a
    pre-registration naming an artifact sha would be filed after it.
    """
    row_id = f"TPR-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO treatment_pre_registrations
              (id, tenant_id, target, primary_endpoint, horizon_days, estimator,
               threshold, threshold_basis, family_size, alpha_spending,
               stopping_rule, author, filed_by)
            VALUES
              (:id, :tenant, :target, :endpoint, :horizon, :estimator,
               :threshold, :basis, :family, :alpha, :stopping, :author, :filed_by)
            """
        ),
        {
            "id": row_id,
            "tenant": tenant_id,
            "target": target,
            "endpoint": primary_endpoint,
            "horizon": int(horizon_days),
            "estimator": estimator,
            "threshold": float(threshold),
            "basis": threshold_basis,
            "family": int(family_size),
            "alpha": alpha_spending,
            "stopping": stopping_rule,
            "author": author,
            "filed_by": filed_by or author,
        },
    )
    logger.info("pre-registration %s filed for %s/%s by %s", row_id, tenant_id, target, author)
    return get(conn, pre_registration_id=row_id) or {"id": row_id}


def get(conn: Any, *, pre_registration_id: str) -> dict[str, Any] | None:
    """One pre-registration, or None. Reads inside a savepoint (W0).

    The savepoint is not defensive style: this runs on a connection the caller
    lent us, and on a database without ``31_promotion_gate.sql`` the failed read
    would abort *their* transaction — the abort cascade W8a shipped.
    """
    if conn is None or not pre_registration_id:
        return None
    try:
        with conn.begin_nested():
            row = conn.execute(
                text("SELECT * FROM treatment_pre_registrations WHERE id = :id"),
                {"id": pre_registration_id},
            ).mappings().first()
    except Exception:
        logger.exception("pre-registration %s could not be read", pre_registration_id)
        return None
    return dict(row) if row else None


def sign(
    conn: Any,
    *,
    pre_registration_id: str,
    validator: str,
    note: str = "",
) -> dict[str, Any]:
    """Record Gate 15's independent sign-off.

    Refuses in process when the validator is the author, so the operator reads a
    sentence rather than a constraint violation — but the constraint is what
    actually holds, and a caller that reaches around this function meets it.
    """
    record = get(conn, pre_registration_id=pre_registration_id)
    if record is None:
        raise PreRegistrationRefused(f"no pre-registration {pre_registration_id}")
    author = str(record.get("author") or "").strip()
    if validator.strip() == author:
        raise PreRegistrationRefused(
            f"{validator} authored this challenger, so they cannot validate it — "
            "§8.12 gate 15 asks for an independent validator who is not the "
            "model's author, and a signature by its author is a record that "
            "somebody looked at their own work"
        )
    conn.execute(
        text(
            """
            UPDATE treatment_pre_registrations
            SET validator = :validator, validated_at = :now, validation_note = :note
            WHERE id = :id
            """
        ),
        {"id": pre_registration_id, "validator": validator, "now": _now(), "note": note or None},
    )
    return get(conn, pre_registration_id=pre_registration_id) or {}


def objections(
    conn: Any,
    *,
    tenant_id: str,
    target: str,
    evaluation: Mapping[str, Any] | None,
    promoted_by: str = "",
) -> list[str]:
    """Every reason Gates 14 and 15 are not satisfied. Empty means they are.

    Returned rather than raised, on the same rule as
    :func:`agent_core.treatment.evaluation_seal.objections`: an operator wants
    "it names no pre-registration *and* nobody signed it" in one round trip.
    """
    from agent_core.treatment import schema_ready

    if conn is None or not schema_ready.w11_ready(conn):
        # §8.12: "No artefact is promoted while any gate cannot be *evaluated*:
        # an unevaluable gate is a refusal." A database without the table cannot
        # tell us whether the challenger was pre-registered, which is not the
        # same as it having been.
        return [
            "gates 14 and 15 cannot be evaluated on this database — "
            "`treatment_pre_registrations` is absent (sql/31_promotion_gate.sql), "
            "and §8.12 makes an unevaluable gate a refusal rather than a pass"
        ]

    body = dict(evaluation or {})
    named = str(body.get(PREREG_FIELD) or "").strip()
    if not named:
        return [
            "the evaluation names no pre-registration, so nothing recorded the "
            "threshold, endpoint, horizon, estimator, family size, alpha "
            "schedule or stopping rule before the challenger ran (§8.12 gate 14)"
        ]

    record = get(conn, pre_registration_id=named)
    if record is None:
        return [f"the evaluation names pre-registration {named}, which does not exist"]

    out: list[str] = []
    if str(record.get("tenant_id")) != tenant_id or str(record.get("target")) != target:
        out.append(
            f"pre-registration {named} was filed for "
            f"{record.get('tenant_id')}/{record.get('target')}, not {tenant_id}/{target}"
        )

    computed_at = _as_datetime(body.get(COMPUTED_AT_FIELD))
    filed_at = _as_datetime(record.get("filed_at"))
    if computed_at is None:
        out.append(
            f"the evaluation carries no {COMPUTED_AT_FIELD}, so it cannot be shown "
            "to have run after the pre-registration was filed (§8.12 gate 14)"
        )
    elif filed_at is not None and computed_at <= filed_at:
        out.append(
            f"the evaluation was computed at {computed_at.isoformat()} and "
            f"pre-registration {named} was filed at {filed_at.isoformat()} — a "
            "pre-registration filed after the run describes the result rather "
            "than predicting it (§8.12 gate 14)"
        )

    if record.get("superseded_at"):
        out.append(f"pre-registration {named} was superseded at {record['superseded_at']}")

    validator = str(record.get("validator") or "").strip()
    author = str(record.get("author") or "").strip()
    if not validator:
        out.append(
            f"pre-registration {named} carries no validator signature — §8.12 "
            "gate 15 asks for an independent validator who did not build the model"
        )
    elif validator == author:
        # Unreachable while the CHECK constraint holds. Kept because the gate
        # must not depend on the database it happens to be pointed at.
        out.append(f"{validator} is both the author and the validator of {named}")
    if promoted_by and author and promoted_by.strip() == author:
        out.append(
            f"{promoted_by} authored this challenger and is promoting it — "
            "§8.12 gate 15 then reaches maker-checker with one person on both sides"
        )
    return out
