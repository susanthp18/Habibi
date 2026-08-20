"""Run the catalog over an interaction, and keep a ledger of what was judged.

The ledger (``compliance_scans``) is what separates this from the live
guardrail hook it replaces. Because every scan records *which version of the
rules* judged the interaction, three things become possible that were not:

* a rule change is a **backfill**, not a fresh start — bump
  :data:`RULES_VERSION` and every interaction re-enters the queue;
* the sweep is **resumable and idempotent**; a crash re-does at most one batch;
* the screen can distinguish "no breach" from "never evaluated", which is the
  distinction the Compliance Risk page was previously unable to make.

Nothing here raises into a caller. A detector that throws costs that one rule
on that one interaction, recorded as an error, not the sweep.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from agent_core.compliance.context import ScanContext, load_context
from agent_core.compliance.detectors import DETECTORS, Finding

logger = logging.getLogger(__name__)

#: Bump when a detector's behaviour changes in a way that should re-judge
#: history. The ledger stores this per row, so raising it queues every
#: interaction for a re-scan without anybody writing a migration.
RULES_VERSION = 1

# Statuses worth judging. A call still in progress has no complete transcript,
# so scanning it would file disclosure breaches for things not yet said.
SCANNABLE_STATUSES = ("completed", "abandoned")


def _sid(prefix: str) -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def scan_interaction(conn: Any, interaction_id: str) -> list[Finding]:
    """Every enabled rule, against one interaction. Never raises.

    Returns the findings; writing them is :func:`_persist`'s job so that a
    caller wanting a dry run (the API preview, a test) can have one.
    """
    ctx = load_context(conn, interaction_id)
    if ctx is None:
        return []
    return evaluate(conn, ctx)


def evaluate(conn: Any, ctx: ScanContext) -> list[Finding]:
    """Pure-ish: reads the enabled-rule set, runs detectors, returns findings."""
    enabled = {
        r["id"]
        for r in conn.execute(
            text("SELECT id FROM compliance_rules WHERE tenant_id = :t AND enabled IS TRUE"),
            {"t": ctx.tenant_id},
        ).mappings()
    }
    findings: list[Finding] = []
    for rule_id, detect in DETECTORS.items():
        if rule_id not in enabled:
            continue
        try:
            found = detect(ctx)
        except Exception:
            # One rule, one interaction. A regex that blows up on an unusual
            # transcript must not stop the other fifteen from being applied.
            logger.exception(
                "compliance detector %s failed on %s", rule_id, ctx.interaction_id
            )
            continue
        if found is not None:
            findings.append(found)
    return findings


def _persist(conn: Any, ctx: ScanContext, findings: list[Finding]) -> int:
    """File findings as violations. Idempotent per (interaction, rule).

    The actor is taken from the interaction's handler, which is what finally
    lets a **human** agent be recorded: the table has always accepted
    ``actor_kind='human'`` with ``actor_user_id``, and the live hook this
    replaces could only ever write ``'bot'``.
    """
    if not findings:
        return 0
    if ctx.handler_kind == "human" and ctx.handler_user_id:
        actor_kind, user_id, bot_id = "human", ctx.handler_user_id, None
    elif ctx.handler_bot_id:
        actor_kind, user_id, bot_id = "bot", None, ctx.handler_bot_id
    else:
        # The CHECK constraint requires one or the other. An interaction with
        # neither is a data problem, not a compliance one.
        logger.warning("interaction %s has no handler — cannot attribute", ctx.interaction_id)
        return 0

    written = 0
    for finding in findings:
        result = conn.execute(
            text(
                """
                INSERT INTO violations (
                  id, interaction_id, customer_id, rule_id,
                  actor_kind, actor_user_id, actor_bot_id,
                  status, description, at_sec, created_at, updated_at
                )
                SELECT :id, :iid, :cid, :rule,
                       :actor_kind, :user_id, :bot_id,
                       'open', :description, :at_sec, now(), now()
                WHERE NOT EXISTS (
                  SELECT 1 FROM violations v
                  WHERE v.interaction_id = :iid AND v.rule_id = :rule
                )
                """
            ),
            {
                "id": _sid("VIO"),
                "iid": ctx.interaction_id,
                "cid": ctx.customer_id,
                "rule": finding.rule_id,
                "actor_kind": actor_kind,
                "user_id": user_id,
                "bot_id": bot_id,
                "description": finding.description[:2000],
                "at_sec": max(int(finding.at_sec), 0),
            },
        )
        written += result.rowcount or 0
    return written


def _record_scan(conn: Any, ctx: ScanContext, findings: int) -> None:
    conn.execute(
        text(
            """
            INSERT INTO compliance_scans
              (interaction_id, tenant_id, rules_version, findings, scanned_at)
            VALUES (:iid, :tid, :ver, :n, now())
            ON CONFLICT (interaction_id) DO UPDATE
              SET rules_version = EXCLUDED.rules_version,
                  findings      = EXCLUDED.findings,
                  scanned_at    = EXCLUDED.scanned_at
            """
        ),
        {"iid": ctx.interaction_id, "tid": ctx.tenant_id, "ver": RULES_VERSION, "n": findings},
    )


def scan_and_file(conn: Any, interaction_id: str) -> dict[str, Any]:
    """Scan one interaction, file what it finds, stamp the ledger."""
    ctx = load_context(conn, interaction_id)
    if ctx is None:
        return {"interactionId": interaction_id, "scanned": False, "reason": "not_found"}
    findings = evaluate(conn, ctx)
    written = _persist(conn, ctx, findings)
    _record_scan(conn, ctx, len(findings))
    return {
        "interactionId": interaction_id,
        "scanned": True,
        "findings": len(findings),
        "filed": written,
        "rules": [f.rule_id for f in findings],
    }


def sweep(limit: int = 200) -> dict[str, Any]:
    """Scan every interaction the ledger has not judged at this rules version.

    ``FOR UPDATE SKIP LOCKED`` on the interaction rows so two workers can run
    the sweep concurrently without doing each other's batch.
    """
    import db

    scanned = 0
    filed = 0
    with db.engine.begin() as conn:
        rows = [
            r["id"]
            for r in conn.execute(
                text(
                    """
                    SELECT i.id
                    FROM interactions i
                    LEFT JOIN compliance_scans s ON s.interaction_id = i.id
                    WHERE i.status = ANY(:statuses)
                      AND (s.interaction_id IS NULL OR s.rules_version < :ver)
                    ORDER BY i.started_at DESC NULLS LAST
                    LIMIT :lim
                    FOR UPDATE OF i SKIP LOCKED
                    """
                ),
                {
                    "statuses": list(SCANNABLE_STATUSES),
                    "ver": RULES_VERSION,
                    "lim": max(1, int(limit)),
                },
            ).mappings()
        ]
        for interaction_id in rows:
            result = scan_and_file(conn, interaction_id)
            if result.get("scanned"):
                scanned += 1
                filed += result.get("filed", 0)
    return {"scanned": scanned, "filed": filed, "rulesVersion": RULES_VERSION}


def backfill(batch: int = 200, max_batches: int = 100) -> dict[str, Any]:
    """Drain the whole queue. For a rules bump or a first run over history."""
    total_scanned = total_filed = 0
    for _ in range(max(1, int(max_batches))):
        result = sweep(limit=batch)
        if not result["scanned"]:
            break
        total_scanned += result["scanned"]
        total_filed += result["filed"]
    return {"scanned": total_scanned, "filed": total_filed, "rulesVersion": RULES_VERSION}


def detector_coverage() -> dict[str, Any]:
    """Per rule: is it enabled, does a detector exist, has it ever evaluated?

    This is the answer to the question the Compliance Risk page could not
    previously ask. Fifteen of the sixteen seeded rules had never produced a
    violation, and a rule with no detector looked exactly like a rule with a
    spotless record — the more dangerous of the two by a wide margin.
    """
    import db

    with db.engine.connect() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT cr.id, cr.code, cr.label, cr.severity, cr.enabled,
                           COUNT(v.id)::int                                   AS total,
                           COUNT(v.id) FILTER (
                             WHERE v.status IN ('open', 'in_review')
                           )::int                                             AS open,
                           MAX(v.created_at)                                  AS last_seen
                    FROM compliance_rules cr
                    LEFT JOIN violations v ON v.rule_id = cr.id
                    WHERE cr.tenant_id = :t
                    GROUP BY cr.id, cr.code, cr.label, cr.severity, cr.enabled
                    ORDER BY cr.code
                    """
                ),
                {"t": db.current_tenant()},
            ).mappings()
        ]
        evaluated = conn.execute(
            text(
                "SELECT COUNT(*)::int FROM compliance_scans WHERE rules_version >= :v"
            ),
            {"v": RULES_VERSION},
        ).scalar()

    out = []
    for row in rows:
        has_detector = row["id"] in DETECTORS
        out.append(
            {
                "ruleId": row["id"],
                "code": row["code"],
                "label": row["label"],
                "severity": row["severity"],
                "enabled": bool(row["enabled"]),
                "hasDetector": has_detector,
                # The three-way answer the page needs. "clean" is only ever
                # claimed for a rule that is actually being looked for.
                "state": (
                    "unverified"
                    if not has_detector
                    else "disabled"
                    if not row["enabled"]
                    else "breached"
                    if row["total"]
                    else "clean"
                ),
                "total": row["total"],
                "open": row["open"],
                "lastSeen": row["last_seen"].isoformat() if row["last_seen"] else None,
            }
        )
    return {
        "rules": out,
        "interactionsEvaluated": int(evaluated or 0),
        "rulesVersion": RULES_VERSION,
        "detectorsRegistered": len(DETECTORS),
    }
