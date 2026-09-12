"""Retention: every record knows when it dies, and a citation says why.

W8b of docs/design/engines-production-design.md, §14.2. Before this module
``treatment_decisions`` had no retention and no archive path, and "until
purpose served" -- a statutory standard, not a schedule -- was answered
nowhere.

Two properties are the whole design and both are enforced here rather than
described:

**``retain_until`` is computed at write, per record.** Not a predicate
evaluated at purge time. A rule that changes must not silently re-date a
million rows that were written under the old one -- the record's expiry is a
fact about the record, and re-dating it retroactively is precisely the thing a
supervisor would ask us to prove we had not done.

**The rule is a row with a citation.** :data:`DEFAULTS` is the day-1 rule set
and it names its instrument for every kind; a ``retention_rules`` row overrides
it under maker-checker. Asked why a record was destroyed on a particular
Tuesday, the answer is an instrument.

The floor is applied as ``max(retain_days, floor_days)``, never as the tenant's
number alone: a tenant may keep a record longer than the statutory minimum and
may never keep it for less.

What expiry does, by class
--------------------------
``identified`` records are **redacted in place and reclassified**, not deleted.
§14.2's path is "PG hot partition -> redacted in place -> detached Parquet
under subject keys": the free text and the rendered message go, the decision
and its exact feature vector stay, and the row's second and longer clock starts
from the redaction. Deleting instead would destroy the evidence that
``policy_replay``, the compensation case and MRM traceability all rest on --
and §14.2 is explicit that retaining a hash of a destroyed blob proves only
that we have not altered something we cannot produce.

``pseudonymous``, ``processing_log`` and the rest are deleted when their clock
runs out, unless a hold is open.

What is deliberately absent
---------------------------
The encrypted Parquet archive, and with it any key material on
``subject_keys`` -- there is no archive, and a key column with nothing
encrypted under it is theatre. The register and its destruction record are
here, because ``subject_rights.fulfil_erasure`` needed something better than
its own docstring's "Does not shred keys."

The monthly ``retention_class`` sub-partition, which is what makes expiry a
``DETACH`` rather than an ``UPDATE``. It needs the expand/contract cutover of
§15.1 item 4 that ``treatment/partitions.py`` only scaffolds.

ponytail: the sweep is one UPDATE and one DELETE per kind per call, bounded by
``limit``. Correct at any size, slow at a billion rows -- that is what the
sub-partition and ``DETACH`` are for, and the upgrade path is to swap the
bodies of :func:`_expire_identified` and :func:`_expire_terminal`, not to
rewrite the rules.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

logger = logging.getLogger(__name__)

IDENTIFIED = "identified"
PSEUDONYMOUS = "pseudonymous"
RECORDING = "recording"
PROCESSING_LOG = "processing_log"
EVALUATION = "evaluation"

CLASSES = (IDENTIFIED, PSEUDONYMOUS, RECORDING, PROCESSING_LOG, EVALUATION)

#: DPDP Act 2023 Rule 8(3): one year, on everything. The floor under every
#: rule below, and the reason ``floor_days`` exists as a separate column.
DPDP_RULE_8_3_DAYS = 365

#: §14.2's pseudonymous window. A design choice, NOT a cited requirement --
#: "no instrument cited in this document carries the number ten", and §18.1
#: asks who signs it. Named here so the day somebody does sign it, there is one
#: place to change and one place to argue with.
PSEUDONYMOUS_YEARS_UNSIGNED = 10


@dataclass(frozen=True)
class Rule:
    """What governs one kind of record."""

    record_kind: str
    table: str
    anchor: str
    retention_class: str
    retain_days: int
    floor_days: int
    citation: str
    #: Columns emptied when an ``identified`` record is redacted in place.
    redact: tuple[str, ...] = ()
    #: Where the row goes after redaction, and for how long from that moment.
    becomes: str | None = None
    becomes_days: int = 0

    @property
    def effective_days(self) -> int:
        """The rule's own number or the statutory floor, whichever is larger."""
        return max(self.retain_days, self.floor_days)

    def expires_at(self, anchor_at: datetime) -> datetime:
        return anchor_at + timedelta(days=self.effective_days)


_YEAR = 365

#: The day-1 rule set. Every row names its instrument.
DEFAULTS: dict[str, Rule] = {
    "treatment_decision": Rule(
        record_kind="treatment_decision",
        table="treatment_decisions",
        anchor="created_at",
        retention_class=IDENTIFIED,
        retain_days=_YEAR,
        floor_days=DPDP_RULE_8_3_DAYS,
        citation="DPDP Rules 2025 r.8(3); purpose limitation s.8(7)",
        # The free text and the rendered message. Not `features`: §14.2 keeps
        # the exact feature vector and exact EV, because an EV cannot be
        # replayed from banded inputs and a decision that cannot be replayed
        # cannot be defended.
        redact=("rationale",),
        becomes=PSEUDONYMOUS,
        becomes_days=PSEUDONYMOUS_YEARS_UNSIGNED * _YEAR,
    ),
    "offer_decision": Rule(
        record_kind="offer_decision",
        table="offer_decisions",
        anchor="created_at",
        retention_class=IDENTIFIED,
        retain_days=_YEAR,
        floor_days=DPDP_RULE_8_3_DAYS,
        citation="DPDP Rules 2025 r.8(3); purpose limitation s.8(7)",
        becomes=PSEUDONYMOUS,
        becomes_days=PSEUDONYMOUS_YEARS_UNSIGNED * _YEAR,
    ),
    "contact_event": Rule(
        record_kind="contact_event",
        table="contact_events",
        anchor="occurred_at",
        # The contact ledger is what the nightly cap auditor reads and what a
        # harassment complaint is answered from. It is a processing log.
        retention_class=PROCESSING_LOG,
        retain_days=_YEAR,
        floor_days=DPDP_RULE_8_3_DAYS,
        citation="DPDP Rules 2025 r.6(1), r.8(3); RBI recovery-conduct records",
    ),
    "interaction": Rule(
        record_kind="interaction",
        table="interactions",
        anchor="started_at",
        retention_class=IDENTIFIED,
        # Audio lives on the bank's NFS; this row is its index and its summary.
        # max(6 months, Rule 8(3) one year) is the year, and an open hold in
        # `recording_holds` outranks both.
        retain_days=183,
        floor_days=DPDP_RULE_8_3_DAYS,
        citation="RBI recovery-conduct 6 months (floor); DPDP Rules 2025 r.8(3)",
        redact=("summary", "source_payload"),
        becomes=PSEUDONYMOUS,
        becomes_days=PSEUDONYMOUS_YEARS_UNSIGNED * _YEAR,
    ),
}

#: Kinds whose expiry consults ``recording_holds``. An open hold outranks every
#: schedule: destroying evidence under an open complaint is worse than keeping
#: it too long.
HELD_KINDS = frozenset({"interaction"})


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_for(conn: Any, *, tenant_id: str, record_kind: str) -> Rule | None:
    """The rule in force, tenant row over the day-1 default.

    Never raises: a retention resolver that throws stops the sweep, and a sweep
    that does not run keeps data, which is the failure that gets noticed
    latest.
    """
    base = DEFAULTS.get(record_kind)
    if base is None:
        return None
    try:
        row = conn.execute(
            text(
                """
                SELECT retention_class, anchor, retain_days, floor_days, citation
                  FROM retention_rules
                 WHERE tenant_id = :t AND record_kind = :k AND effective @> now()
                 LIMIT 1
                """
            ),
            {"t": tenant_id, "k": record_kind},
        ).mappings().first()
    except Exception:
        logger.debug("retention_rules unreadable — using the day-1 rule", exc_info=True)
        return base
    if row is None:
        return base
    from dataclasses import replace

    return replace(
        base,
        retention_class=str(row["retention_class"]),
        anchor=str(row["anchor"]),
        retain_days=int(row["retain_days"]),
        floor_days=int(row["floor_days"]),
        citation=str(row["citation"]),
    )


def stamp_for(
    conn: Any, *, tenant_id: str, record_kind: str, anchor_at: datetime
) -> tuple[str, datetime] | None:
    """``(retention_class, retain_until)`` for a row about to be written."""
    rule = rule_for(conn, tenant_id=tenant_id, record_kind=record_kind)
    if rule is None:
        return None
    at = anchor_at if anchor_at.tzinfo else anchor_at.replace(tzinfo=timezone.utc)
    return rule.retention_class, rule.expires_at(at)


def backfill(conn: Any, *, tenant_id: str, record_kind: str) -> int:
    """Stamp rows written before this module existed. Idempotent."""
    rule = rule_for(conn, tenant_id=tenant_id, record_kind=record_kind)
    if rule is None:
        return 0
    return int(
        conn.execute(
            text(
                f"""
                UPDATE {rule.table}
                   SET retention_class = :cls,
                       retain_until = {rule.anchor} + make_interval(days => :days)
                 WHERE tenant_id = :t AND retain_until IS NULL
                """  # noqa: S608 - table and anchor come from DEFAULTS, never a caller
            ),
            {"cls": rule.retention_class, "days": rule.effective_days, "t": tenant_id},
        ).rowcount
        or 0
    )


# ---------------------------------------------------------------------------
# Subject register
# ---------------------------------------------------------------------------


def pseudonym_for(conn: Any, *, tenant_id: str, subject_id: str) -> str:
    """This subject's pseudonym, minted on first use.

    Per subject, not per tenant: §14.2's whole argument is that a per-tenant
    salt cannot be destroyed for one borrower.
    """
    row = conn.execute(
        text(
            "SELECT pseudonym, destroyed_at FROM subject_keys"
            " WHERE tenant_id = :t AND subject_kind = 'customer' AND subject_id = :s"
        ),
        {"t": tenant_id, "s": subject_id},
    ).mappings().first()
    if row is not None:
        return str(row["pseudonym"])
    pseudonym = f"SUBJ-{uuid.uuid4().hex[:16].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO subject_keys (id, tenant_id, subject_kind, subject_id, pseudonym)
            VALUES (:id, :t, 'customer', :s, :p)
            ON CONFLICT (tenant_id, subject_kind, subject_id) DO NOTHING
            """
        ),
        {"id": f"SK-{uuid.uuid4().hex[:12].upper()}", "t": tenant_id, "s": subject_id, "p": pseudonym},
    )
    return str(
        conn.execute(
            text(
                "SELECT pseudonym FROM subject_keys"
                " WHERE tenant_id = :t AND subject_kind = 'customer' AND subject_id = :s"
            ),
            {"t": tenant_id, "s": subject_id},
        ).scalar()
        or pseudonym
    )


def destroy_subject_key(
    conn: Any, *, tenant_id: str, subject_id: str, reason: str, actor: str | None = None
) -> bool:
    """Mark this subject's pseudonym destroyed. Returns False if there was none.

    Idempotent: a second erasure of the same subject does not move
    ``destroyed_at``, because the date destruction happened is itself the
    evidence.
    """
    if not str(reason or "").strip():
        raise ValueError("destruction carries a reason")
    pseudonym_for(conn, tenant_id=tenant_id, subject_id=subject_id)
    return bool(
        conn.execute(
            text(
                """
                UPDATE subject_keys
                   SET destroyed_at = now(), destroyed_by = :actor,
                       destroy_reason = :reason
                 WHERE tenant_id = :t AND subject_kind = 'customer'
                   AND subject_id = :s AND destroyed_at IS NULL
                """
            ),
            {"t": tenant_id, "s": subject_id, "reason": reason, "actor": actor},
        ).rowcount
    )


# ---------------------------------------------------------------------------
# Holds
# ---------------------------------------------------------------------------

#: §14.2: an open hold keeps the recording for 90 days beyond its release.
HOLD_TAIL_DAYS = 90


def open_hold(
    conn: Any,
    *,
    tenant_id: str,
    reason: str,
    customer_id: str | None = None,
    interaction_id: str | None = None,
    basis: str | None = None,
    opened_by: str | None = None,
) -> str:
    if not (customer_id or interaction_id):
        raise ValueError("a hold on nothing is not a hold")
    hold_id = f"RH-{uuid.uuid4().hex[:12].upper()}"
    conn.execute(
        text(
            """
            INSERT INTO recording_holds (
              id, tenant_id, customer_id, interaction_id, reason, basis, opened_by
            ) VALUES (:id, :t, :cid, :iid, :reason, :basis, :by)
            """
        ),
        {
            "id": hold_id,
            "t": tenant_id,
            "cid": customer_id,
            "iid": interaction_id,
            "reason": reason,
            "basis": basis,
            "by": opened_by,
        },
    )
    return hold_id


def release_hold(conn: Any, hold_id: str, *, released_by: str | None = None) -> bool:
    return bool(
        conn.execute(
            text(
                "UPDATE recording_holds SET released_at = now(), released_by = :by"
                " WHERE id = :id AND released_at IS NULL"
            ),
            {"id": hold_id, "by": released_by},
        ).rowcount
    )


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def sweep(
    conn: Any,
    *,
    tenant_id: str,
    record_kind: str | None = None,
    limit: int = 5_000,
) -> list[dict[str, Any]]:
    """Expire what is due. One run row per kind, whether or not it did anything.

    §7.8's discipline applied to retention: a sweep that found nothing is a
    logged decision, not a silence. "Retention ran and destroyed nothing" and
    "retention did not run" look identical in an empty table, and only one of
    them is a finding.
    """
    kinds = [record_kind] if record_kind else list(DEFAULTS)
    out: list[dict[str, Any]] = []
    for kind in kinds:
        rule = rule_for(conn, tenant_id=tenant_id, record_kind=kind)
        if rule is None:
            continue
        try:
            counts = _expire(conn, rule, tenant_id=tenant_id, limit=limit)
            error = None
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("retention sweep failed kind=%s", kind)
            counts = {"scanned": 0, "redacted": 0, "deleted": 0, "held": 0}
            error = type(exc).__name__
        conn.execute(
            text(
                """
                INSERT INTO retention_runs (
                  id, tenant_id, record_kind, scanned, redacted, deleted, held,
                  rule_id, error
                ) VALUES (
                  :id, :t, :kind, :scanned, :redacted, :deleted, :held, :rule, :error
                )
                """
            ),
            {
                "id": f"RR-{uuid.uuid4().hex[:12].upper()}",
                "t": tenant_id,
                "kind": kind,
                "rule": rule.citation[:200],
                "error": error,
                **counts,
            },
        )
        out.append({"recordKind": kind, "error": error, **counts})
    return out


def _expire(conn: Any, rule: Rule, *, tenant_id: str, limit: int) -> dict[str, int]:
    due = conn.execute(
        text(
            f"""
            SELECT id FROM {rule.table}
             WHERE tenant_id = :t
               AND retain_until IS NOT NULL
               AND retain_until <= now()
               AND retention_class = :cls
             ORDER BY retain_until
             LIMIT :limit
            """  # noqa: S608 - table comes from DEFAULTS, never a caller
        ),
        {"t": tenant_id, "cls": rule.retention_class, "limit": limit},
    ).scalars().all()
    if not due:
        return {"scanned": 0, "redacted": 0, "deleted": 0, "held": 0}

    held: list[str] = []
    if rule.record_kind in HELD_KINDS:
        held = list(
            conn.execute(
                text(
                    """
                    SELECT DISTINCT i.id
                      FROM interactions i
                      JOIN recording_holds h
                        ON h.tenant_id = i.tenant_id
                       AND (h.interaction_id = i.id OR h.customer_id = i.customer_id)
                     WHERE i.id = ANY(:ids)
                       AND (
                         h.released_at IS NULL
                         OR h.released_at > now() - make_interval(days => :tail)
                       )
                    """
                ),
                {"ids": due, "tail": HOLD_TAIL_DAYS},
            ).scalars()
        )

    actionable = [row for row in due if row not in set(held)]
    counts = {
        "scanned": len(due),
        "held": len(held),
        "redacted": 0,
        "deleted": 0,
    }
    if not actionable:
        return counts

    if rule.retention_class == IDENTIFIED and rule.becomes:
        counts["redacted"] = _expire_identified(conn, rule, ids=actionable)
    else:
        counts["deleted"] = _expire_terminal(conn, rule, ids=actionable)
    return counts


def _expire_identified(conn: Any, rule: Rule, *, ids: list[str]) -> int:
    """Redact in place and start the second, longer clock."""
    blanks = ", ".join(f"{column} = NULL" for column in rule.redact)
    sets = f"{blanks}, " if blanks else ""
    return int(
        conn.execute(
            text(
                f"""
                UPDATE {rule.table}
                   SET {sets}
                       retention_class = :becomes,
                       retain_until = now() + make_interval(days => :days)
                 WHERE id = ANY(:ids)
                """  # noqa: S608 - table and columns come from DEFAULTS
            ),
            {"becomes": rule.becomes, "days": rule.becomes_days, "ids": ids},
        ).rowcount
        or 0
    )


def _expire_terminal(conn: Any, rule: Rule, *, ids: list[str]) -> int:
    return int(
        conn.execute(
            text(f"DELETE FROM {rule.table} WHERE id = ANY(:ids)"),  # noqa: S608
            {"ids": ids},
        ).rowcount
        or 0
    )
