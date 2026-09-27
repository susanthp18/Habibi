"""One decision, end to end, in terms a reviewer can check.

Everything here is read from what the engine stored at decision time plus the
rows the decision's own id links to afterwards. Nothing is recomputed: a trace
that re-ran the engine would show today's answer, not the one that was acted
on, and the point of the trace is to defend the one that was acted on.

Sections: why now (trigger + facts + data freshness), options (every action,
scored or blocked with the reason), choice (what, how it was picked, what it
beat), what happened (enactment → call → disposition → promise → payment →
label), and people's feedback.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any

from sqlalchemy import text

from db_core import _tenant

logger = logging.getLogger(__name__)

#: Facts shown under "why now", in reading order. Everything else stays in
#: ``raw`` for anyone who needs it.
_FACTS: tuple[tuple[str, str], ...] = (
    ("Days past due", "dpd"),
    ("Bucket", "bucket"),
    ("Amount at stake", "exposure"),
    ("Outstanding", "outstanding"),
    ("Instalment", "instalmentAmount"),
    ("Product", "productCategory"),
    ("Open bounce", "openBounce"),
    ("Bounce reason", "bounceReason"),
    ("Auto-debit mandate", "mandateStatus"),
    ("Promises kept / made", "_promises"),
    ("Contacts today / daily cap", "_touches"),
    ("Contacts in 7 days", "touches7d"),
    ("Answer rate by channel", "connectRate"),
    ("Consent by channel", "consentByChannel"),
    ("On DND", "dnd"),
    ("Holds", "holds"),
    ("Said on a call", "speechFlags"),
    ("Open disputes", "openDisputeCount"),
    ("Attempts on this case", "caseAttempts"),
    ("Last attempt", "caseLastAction"),
    ("Last attempt's outcome", "caseLastOutcome"),
    ("Segment", "segment"),
    ("Risk", "risk"),
    ("Inputs that were stale", "staleInputs"),
)

_HOW = {
    "greedy": "best-scoring option",
    "ranked": "exploration: a lower-ranked option picked on purpose to keep learning",
    "control_arm": "comparison group: discretionary contact held back to measure lift",
}


def _facts(features: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for label, key in _FACTS:
        if key == "_promises":
            value: Any = f"{features.get('promisesKept') or 0} / {features.get('promisesTotal') or 0}"
        elif key == "_touches":
            value = f"{features.get('touchesToday') or 0} / {features.get('dailyCap') or 0}"
        else:
            value = features.get(key)
        if value in (None, "", [], {}):
            continue
        out.append({"label": label, "key": key, "value": value})
    return out


def _options(row: dict[str, Any]) -> list[dict[str, Any]]:
    from agent_core.treatment import actions as A, narrate

    candidates = {str(c.get("action")): c for c in (row.get("candidates") or [])}
    excluded = row.get("excluded") or {}
    ranked = [str(c.get("action")) for c in (row.get("candidates") or [])]
    chosen = row.get("chosen_action")
    out = []
    for action in A.ALL:
        base = {"action": action, "label": A.label(action), "chosen": action == chosen}
        if action in candidates:
            c = candidates[action]
            out.append(
                base
                | {
                    "status": "scored",
                    "rank": ranked.index(action) + 1,
                    "expectedValue": c.get("expectedValue"),
                    "pReach": c.get("pReach"),
                    "pResolve": c.get("pResolve"),
                    "cost": c.get("cost"),
                    "at": c.get("at"),
                    "explanation": c.get("explanation"),
                    "timingRationale": c.get("timingRationale"),
                    "evidence": c.get("evidence") or {},
                    "pickProbability": c.get("propensity"),
                    "reasonCodes": c.get("reasonCodes") or [],
                }
            )
        elif action in excluded:
            code = str(excluded[action])
            out.append(base | {"status": "blocked", "code": code, "reason": narrate.humanise(code)})
        else:
            out.append(base | {"status": "not_considered"})
    return out


def _choice(row: dict[str, Any], options: list[dict[str, Any]]) -> dict[str, Any]:
    from agent_core.treatment import actions as A, narrate

    scored = sorted(
        (o for o in options if o["status"] == "scored"), key=lambda o: o.get("rank") or 99
    )
    chosen = next((o for o in scored if o["chosen"]), None)
    runner = next((o for o in scored if not o["chosen"]), None)
    reason = row.get("suppression_reason")
    beat = None
    if chosen and runner and chosen.get("expectedValue") is not None and runner.get("expectedValue") is not None:
        beat = {
            "action": runner["action"],
            "label": runner["label"],
            "byInr": round(float(chosen["expectedValue"]) - float(runner["expectedValue"]), 2),
        }
    kind = row.get("explore_kind") or "greedy"
    return {
        "action": row.get("chosen_action"),
        "label": A.label(str(row.get("chosen_action") or "wait")),
        "channel": row.get("chosen_channel"),
        "scheduledAt": row.get("scheduled_at"),
        "expectedValue": row.get("expected_value"),
        "held": bool(reason),
        "holdReason": reason,
        "holdReasonText": narrate.humanise(reason) if reason else None,
        "how": kind,
        "howText": _HOW.get(kind, kind),
        "pickProbability": row.get("propensity"),
        "beat": beat,
        "rationale": row.get("rationale"),
    }


def _freshness(conn: Any, tenant_id: str) -> list[dict[str, Any]]:
    """Each bank feed's age: missing or stale feeds block contact (always)."""
    try:
        with conn.begin_nested():
            rows = conn.execute(
                text(
                    """
                    SELECT c.code, f.last_accepted_at, f.lag_hours
                      FROM bank_contracts c
                      LEFT JOIN bank_freshness f
                        ON f.contract_code = c.code AND f.tenant_id = :t AND f.portfolio_id = ''
                     WHERE c.code LIKE 'C%'
                     ORDER BY c.code
                    """
                ),
                {"t": tenant_id},
            ).mappings().all()
    except Exception:
        return []
    return [
        {
            "feed": r["code"],
            "name": _FEED_NAMES.get(r["code"], r["code"]),
            "lastReceivedAt": r["last_accepted_at"],
            "lagHours": r["lag_hours"],
        }
        for r in rows
    ]


#: The bank's inbound feeds, named for the person reading the screen.
_FEED_NAMES = {
    "C1": "accounts", "C2": "instalment schedule", "C3": "mandates",
    "C4": "mandate presentations", "C5": "mandate returns", "C6": "payments",
    "C7": "bank and agency contact log", "C8": "customer consent",
    "C9": "staff and field capacity", "C10": "customer protections",
}


def _happened(conn: Any, row: dict[str, Any]) -> dict[str, Any]:
    """Everything the decision's id links to, oldest first."""
    decision_id = row["id"]

    def q(sql: str, **params: Any) -> list[dict[str, Any]]:
        try:
            with conn.begin_nested():
                return [dict(r) for r in conn.execute(text(sql), {"id": decision_id, **params}).mappings()]
        except Exception:
            return []

    calls = q(
        """
        SELECT a.id, a.state, a.placed_at, a.answered_at, a.ended_at, a.suppressed_reason,
               a.interaction_id, i.disposition, i.duration_sec,
               o.connection, o.business, o.summary
          FROM call_attempts a
          LEFT JOIN interactions i ON i.id = a.interaction_id
          LEFT JOIN call_outcomes o ON o.attempt_id = a.id
         WHERE a.decision_id = :id
         ORDER BY a.reserved_at
        """
    )
    messages = q(
        """
        SELECT id, status, template_name, created_at, post_attempted_at FROM whatsapp_outbound_jobs
         WHERE decision_id = :id ORDER BY created_at
        """
    )
    since = row.get("enacted_at") or row.get("created_at")
    promises = q(
        """
        SELECT id, amount, promised_at, status, interaction_id, created_at FROM promises
         WHERE customer_id = :cid AND created_at > :since
         ORDER BY created_at LIMIT 5
        """,
        cid=row["customer_id"],
        since=since,
    )
    payments = q(
        """
        SELECT id, abs(amount) AS amount, posted_at FROM ledger_entries
         WHERE account_id = :aid AND type = 'payment' AND posted_at > :since
         ORDER BY posted_at LIMIT 5
        """,
        aid=row.get("account_id"),
        since=since,
    )
    return {
        "enacted": bool(row.get("enacted")),
        "enactedAt": row.get("enacted_at"),
        "enactedBy": row.get("enacted_by"),
        "enactedRef": row.get("enacted_ref"),
        "cancelReason": row.get("cancel_reason"),
        "calls": calls,
        "messages": messages,
        "promisesSince": promises,
        "paymentsSince": payments,
        "label": {
            "outcome": row.get("outcome"),
            "outcomeAt": row.get("outcome_at"),
            "reach": row.get("reach_outcome"),
            "cure": row.get("cure_outcome"),
            "matureAt": row.get("label_mature_at"),
            "definition": row.get("label_definition_version"),
        },
    }


def trace(decision_id: str) -> dict[str, Any]:
    """The decision trace. ``KeyError`` when it is not this tenant's."""
    import db

    tenant = _tenant()
    with db.engine.connect() as conn:
        found = conn.execute(
            text("SELECT * FROM treatment_decisions WHERE id = :id AND tenant_id = :t"),
            {"id": decision_id, "t": tenant},
        ).mappings().first()
        if found is None:
            raise KeyError("decision_not_found")
        row = dict(found)
        features = row.get("features") or {}
        options = _options(row)
        name = conn.execute(
            text("SELECT name FROM customers WHERE id = :c"), {"c": row["customer_id"]}
        ).scalar()
        feedback = [
            dict(r)
            for r in conn.execute(
                text(
                    """
                    SELECT verdict, reason_code, corrected_outcome, note_redacted, actor_role, created_at
                      FROM decision_feedback WHERE decision_id = :id ORDER BY created_at
                    """
                ),
                {"id": decision_id},
            ).mappings()
        ]
        happened = _happened(conn, row)
        freshness = _freshness(conn, tenant)
    contract = features.get("loggingContract") or {}
    return {
        "id": row["id"],
        "family": row.get("action_family") or "collections",
        "customerId": row["customer_id"],
        "customerName": name,
        "accountId": row.get("account_id"),
        "createdAt": row.get("created_at"),
        "mode": row.get("mode"),
        "variant": row.get("variant"),
        "whyNow": {
            "trigger": row.get("trigger_kind"),
            "triggerRef": row.get("trigger_ref"),
            "triggerDetail": features.get("trigger"),
            "facts": _facts(features),
            "dataFreshness": freshness,
            "policyRules": features.get("policy"),
        },
        "options": options,
        "choice": _choice(row, options),
        "versions": {
            "policy": row.get("policy_version"),
            "config": row.get("config_version"),
            "recommender": f"{row.get('recommender')} {row.get('recommender_version')}",
            "featureSchema": row.get("feature_schema_version"),
            "vetoStack": row.get("veto_stack_version"),
            "engineImage": row.get("engine_image_digest"),
            "greediness": contract.get("greediness"),
            "policyBindingHash": row.get("policy_binding_hash"),
        },
        "happened": happened,
        "feedback": feedback,
        "raw": {"features": features},
    }


def decide_now(*, customer_id: str, account_id: str | None = None) -> dict[str, Any]:
    """Ask the engine now, and keep the answer.

    Recorded in shadow mode: the decision is logged and traceable like any
    other, and nothing is carried out because somebody opened a screen. A
    supervisor who wants it done uses the enact route on a live plan.
    """
    import uuid

    import db
    from agent_core.treatment import Trigger, recommend_treatment
    from db_core import _assert_tenant_owns, _assert_tenant_owns_customer

    with db.engine.begin() as conn:
        _assert_tenant_owns_customer(conn, customer_id)
        if account_id:
            _assert_tenant_owns(conn, "accounts", account_id)
        result = recommend_treatment(
            customer_id=customer_id,
            account_id=account_id,
            trigger=Trigger(kind="manual", ref=f"manual:{uuid.uuid4().hex[:12]}"),
            conn=conn,
            force_mode="shadow",
        )
    if not result.decision_id:
        raise RuntimeError("decision_not_recorded")
    return trace(result.decision_id)


def current(customer_id: str, account_id: str | None = None) -> dict[str, Any] | None:
    """The account's next best action, as a trace. None if nothing recent."""
    import db
    from agent_core.treatment import decisions

    with db.engine.connect() as conn:
        row = decisions.current(conn, customer_id=customer_id, account_id=account_id, tenant_id=_tenant())
    return trace(row["id"]) if row else None


def snapshot(conn: Any, customer_id: str) -> dict[str, Any] | None:
    """The current decision in the engine's payload shape, for the customer card."""
    from agent_core.treatment import actions as A, decisions, narrate

    row = decisions.current(conn, customer_id=customer_id, tenant_id=_tenant())
    if row is None:
        return None
    action = str(row.get("chosen_action") or "wait")
    reason = row.get("suppression_reason")
    chosen = next((c for c in (row.get("candidates") or []) if c.get("action") == action), {})
    return {
        "action": action,
        "actionLabel": A.label(action),
        "channel": row.get("chosen_channel"),
        "at": str(row.get("scheduled_at") or chosen.get("at")) if (row.get("scheduled_at") or chosen.get("at")) else None,
        "expectedValueInr": float(row.get("expected_value") or 0),
        "suppressed": bool(reason),
        "reason": reason,
        "reasonText": narrate.humanise(reason) if reason else None,
        "rationale": row.get("rationale") or "",
        "decisionId": row["id"],
        "propensity": float(row.get("propensity") or 1.0),
        "policyVersion": row.get("policy_version"),
        "mode": row.get("mode"),
        "variant": row.get("variant"),
        "latencyMs": row.get("latency_ms"),
        "decidedAt": str(row.get("created_at")),
        "enacted": bool(row.get("enacted")),
        # The training vector stays in the log; the card needs the reading.
        "alternatives": [
            {k: v for k, v in c.items() if k != "vector"}
            for c in (row.get("candidates") or [])
            if c.get("action") != action
        ],
        "excluded": dict(row.get("excluded") or {}),
    }


_LIST_COLUMNS = """
    td.id, td.created_at, td.customer_id, c.name AS customer_name, td.account_id,
    td.trigger_kind, td.trigger_ref, td.mode, td.variant, td.chosen_action,
    td.chosen_channel, td.scheduled_at, td.expected_value, td.suppression_reason,
    td.explore_kind, td.enacted, td.enacted_at, td.outcome, td.rationale
"""


def list_decisions(
    *,
    customer_id: str | None = None,
    action: str | None = None,
    outcome: str | None = None,
    held: bool | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """The searchable decision log, newest first. Real decisions only."""
    import db
    from agent_core.treatment import narrate

    where = ["td.tenant_id = :t", "td.mode <> 'simulated'",
             "COALESCE(to_jsonb(td) ->> 'action_family', '') <> 'offer'"]
    params: dict[str, Any] = {"t": _tenant(), "limit": max(1, min(limit, 5000)), "offset": max(0, offset)}
    for clause, key, value in (
        ("td.customer_id = :cid", "cid", customer_id),
        ("td.chosen_action = :action", "action", action),
        ("td.outcome = :outcome", "outcome", outcome),
        ("td.created_at >= :since", "since", since),
        ("td.created_at < :until", "until", until),
    ):
        if value:
            where.append(clause)
            params[key] = value
    if held is True:
        where.append("td.suppression_reason IS NOT NULL")
    elif held is False:
        where.append("td.suppression_reason IS NULL")
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT {_LIST_COLUMNS}
                  FROM treatment_decisions td
                  JOIN customers c ON c.id = td.customer_id
                 WHERE {' AND '.join(where)}
                 ORDER BY td.created_at DESC, td.id DESC
                 LIMIT :limit OFFSET :offset
                """
            ),
            params,
        ).mappings().all()
    out = []
    for r in rows:
        d = dict(r)
        d["holdReasonText"] = narrate.humanise(d["suppression_reason"]) if d.get("suppression_reason") else None
        out.append(d)
    return out


def to_csv(rows: list[dict[str, Any]]) -> str:
    """Flat export for an auditor's spreadsheet."""
    buf = io.StringIO()
    fields = [
        "id", "created_at", "customer_id", "customer_name", "account_id", "trigger_kind",
        "trigger_ref", "mode", "variant", "chosen_action", "chosen_channel", "scheduled_at",
        "expected_value", "suppression_reason", "holdReasonText", "explore_kind", "enacted",
        "enacted_at", "outcome", "rationale",
    ]
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Health: is every stage of the engine actually running?
# ---------------------------------------------------------------------------

#: (key, label, what it does, hours after which it is late, SQL for its last run)
_STAGES: tuple[tuple[str, str, str, int, str], ...] = (
    ("decide", "Deciding", "Bounces, broken promises and the daily sweep produce decisions", 26,
     "SELECT max(created_at) FROM treatment_decisions WHERE tenant_id = :t AND mode <> 'simulated'"),
    ("sweep", "Daily sweep", "Every overdue account is re-decided once a day", 26,
     "SELECT max(completed_at) FROM treatment_sweep_runs WHERE tenant_id = :t"),
    ("snapshot", "Account data build", "Today's account facts, rebuilt every 3 hours", 4,
     "SELECT max(finished_at) FROM feature_snapshot_builds WHERE tenant_id = :t AND state = 'loaded'"),
    ("labels", "Outcome labelling", "What happened after each decision is recorded", 26,
     "SELECT max(outcome_at) FROM treatment_decisions WHERE tenant_id = :t AND mode <> 'simulated'"),
    ("learn", "Learning", "Response rates are re-learned from outcomes, nightly", 26,
     "SELECT max(updated_at) FROM work_runtime_jobs WHERE tenant_id = :t AND workflow_type = 'di.learn'"),
    ("train", "Model training", "Challenger models are fitted weekly", 24 * 8,
     "SELECT max(updated_at) FROM work_runtime_jobs WHERE tenant_id = :t AND workflow_type = 'di.train'"),
    ("evaluate", "Model evaluation", "Challengers are scored off-policy, weekly", 24 * 8,
     "SELECT max(updated_at) FROM work_runtime_jobs WHERE tenant_id = :t AND workflow_type = 'di.evaluate'"),
    ("advise", "Weekly advisor", "An AI review of the results proposes setting changes for a person to approve", 24 * 8,
     "SELECT max(updated_at) FROM work_runtime_jobs WHERE tenant_id = :t AND workflow_type = 'di.advise'"),
    ("capacity", "Capacity pricing", "Tomorrow's book is priced against capacity, nightly", 26,
     "SELECT max(updated_at) FROM work_runtime_jobs WHERE tenant_id = :t AND workflow_type = 'w13.capacity_solve' AND status = 'completed'"),
)


def _last_result(conn: Any, tenant: str, job: str) -> dict[str, Any] | None:
    row = conn.execute(
        text(
            """
            SELECT status, result, error, updated_at FROM work_runtime_jobs
             WHERE tenant_id = :t AND workflow_type = :j
             ORDER BY updated_at DESC LIMIT 1
            """
        ),
        {"t": tenant, "j": job},
    ).mappings().first()
    return dict(row) if row else None


def health(days: int = 1) -> dict[str, Any]:
    """Every stage's last run, the bank feeds, and what is blocking contact."""
    import db
    from agent_core.clock import utc_now
    from agent_core.treatment import config, kill_switch, narrate

    tenant = _tenant()
    now = utc_now()
    stages = []
    with db.engine.connect() as conn:
        for key, label, does, late_after, sql in _STAGES:
            try:
                with conn.begin_nested():
                    last = conn.execute(text(sql), {"t": tenant}).scalar()
            except Exception:
                last = None
            if last is None:
                status = "never"
            elif (now - last).total_seconds() > late_after * 3600:
                status = "late"
            else:
                status = "ok"
            stage = {"key": key, "label": label, "does": does, "lastAt": last, "status": status}
            job = {"learn": "di.learn", "train": "di.train", "evaluate": "di.evaluate", "advise": "di.advise"}.get(key)
            if job:
                try:
                    with conn.begin_nested():
                        stage["lastResult"] = _last_result(conn, tenant, job)
                except Exception:
                    pass
            stages.append(stage)
        blockers = []
        try:
            with conn.begin_nested():
                rows = conn.execute(
                    text(
                        """
                        SELECT e.value AS code, count(DISTINCT d.customer_id)::int AS borrowers
                          FROM treatment_decisions d, jsonb_each_text(d.excluded) e
                         WHERE d.tenant_id = :t AND d.mode <> 'simulated'
                           AND d.created_at >= now() - make_interval(days => :days)
                         GROUP BY 1 ORDER BY 2 DESC LIMIT 8
                        """
                    ),
                    {"t": tenant, "days": days},
                ).mappings().all()
            blockers = [
                {"code": r["code"], "text": narrate.humanise(r["code"]), "borrowers": r["borrowers"]}
                for r in rows
            ]
        except Exception:
            pass
        feeds = _freshness(conn, tenant)
    return {
        "mode": config.mode(),
        "enactSwitchOn": kill_switch.enact_allowed(),
        "labelsOn": kill_switch.labels_allowed(),
        "stages": stages,
        "feeds": feeds,
        "blockers": blockers,
    }


def learned_rates() -> list[dict[str, Any]]:
    """Every probability the scorer starts from, beside what it has learned."""
    import db
    from agent_core.treatment import actions as A, beliefs, scoring

    with db.engine.connect() as conn:
        counts = beliefs.load(conn, tenant_id=_tenant())
    out = []
    for channel, prior in scoring.REACH_PRIOR.items():
        e = beliefs.blend(prior, counts.get(("reach", channel)))
        out.append({"metric": "reach", "key": channel, "label": f"Reach a person by {channel}", **e.to_log()})
    for action, prior in scoring.RESOLVE_PRIOR.items():
        e = beliefs.blend(prior, counts.get(("resolve", action)))
        out.append({"metric": "resolve", "key": action, "label": f"Cured after {A.label(action)}", **e.to_log()})
    return out
