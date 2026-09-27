"""The decision engine's settings, as a business user edits them.

Every value here already existed as an ``engine_config`` key with bounds and a
maker-checker table behind it; nothing could write it except SQL by hand. This
module is the missing front door: the settings in plain words with their
current values, a proposal a person (or the weekly advisor) makes with a
reason, an estimate of what it would have changed, and approval by somebody
else, which writes through ``engine_config.put``.

ponytail: the impact estimate re-ranks the last week's logged options for the
keys whose effect is arithmetic on the logged components (costs, minimum
worth, recovery share). Other keys say "not estimated" rather than guess.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy import text

from db_core import _tenant

logger = logging.getLogger(__name__)

#: (key, group, label, help). Order is the order on screen.
SETTINGS: tuple[tuple[str, str, str, str], ...] = (
    ("TREATMENT_MODE", "Operation", "Engine mode",
     "off: nothing is decided. shadow: every decision is made and recorded, none carried out. live: decisions are carried out."),
    ("TREATMENT_AB_SPLIT", "Learning", "Comparison group",
     "Borrowers are split at random. The null_treatment share gets only what policy requires, which is how the engine proves it helps. Example: control:90,null_treatment:10."),
    ("TREATMENT_GREEDINESS", "Learning", "How often to pick the best option",
     "1 always picks the best-scoring option. Lower values sometimes pick a runner-up on purpose, so the engine keeps learning what works."),
    ("TREATMENT_MIN_EV", "Value", "Minimum worth of an action (₹)",
     "An action must be worth at least this, after its cost, or the engine waits."),
    ("TREATMENT_RECOVERY_FRACTION", "Value", "Share of the arrears a cure recovers",
     "0.35 means a cured account is worth 35% of the amount at stake."),
    ("TREATMENT_URGENCY_HALFLIFE_HOURS", "Value", "How fast waiting loses value (hours)",
     "After this many hours, an action planned for later is worth half as much."),
    ("TREATMENT_FATIGUE_COST", "Contact", "Cost of annoying a borrower (₹ per touch)",
     "Charged for every contact already made today, so the engine does not contact people repeatedly."),
    ("TREATMENT_MAX_ATTEMPTS_PER_CASE", "Contact", "Most attempts per case",
     "After this many attempts on one bounce or broken promise, the engine stops and a person decides."),
    ("TREATMENT_RETRY_BACKOFF_HOURS", "Contact", "Gap between attempts (hours)",
     "The engine will not re-decide a case sooner than this after an attempt."),
    ("TREATMENT_MAX_RUNG_ADVANCE", "Contact", "Biggest step up the escalation ladder",
     "How many rungs one decision may climb, e.g. from WhatsApp straight to a field visit."),
    ("TREATMENT_COST_SMS", "Cost per attempt (₹)", "SMS", ""),
    ("TREATMENT_COST_WHATSAPP", "Cost per attempt (₹)", "WhatsApp", ""),
    ("TREATMENT_COST_VOICE_BOT", "Cost per attempt (₹)", "Bot call", ""),
    ("TREATMENT_COST_HUMAN_CALL", "Cost per attempt (₹)", "Agent call", ""),
    ("TREATMENT_COST_FIELD_VISIT", "Cost per attempt (₹)", "Field visit", ""),
    ("TREATMENT_COST_LEGAL_NOTICE", "Cost per attempt (₹)", "Legal notice", ""),
    ("TREATMENT_COST_REPRESENT_MANDATE", "Cost per attempt (₹)", "Re-present the mandate", ""),
    ("TREATMENT_COST_EMI_DATE_CHANGE", "Cost per attempt (₹)", "EMI date change", ""),
    ("TREATMENT_COST_SELF_SERVICE_PLAN", "Cost per attempt (₹)", "Self-service plan", ""),
)
_KEYS = {k for k, *_ in SETTINGS}


def _effective() -> dict[str, Any]:
    """What the engine is using right now for each key."""
    from agent_core.treatment import config

    policy, costs = config.policy(), config.costs()
    return {
        "TREATMENT_MODE": config.mode(),
        "TREATMENT_AB_SPLIT": ",".join(f"{a}:{round(w * 100)}" for a, w in config.ab_split()) or "",
        "TREATMENT_GREEDINESS": config.greediness(),
        "TREATMENT_MIN_EV": policy.min_expected_value,
        "TREATMENT_RECOVERY_FRACTION": policy.recovery_fraction,
        "TREATMENT_URGENCY_HALFLIFE_HOURS": policy.urgency_halflife_hours,
        "TREATMENT_FATIGUE_COST": policy.fatigue_cost,
        "TREATMENT_MAX_ATTEMPTS_PER_CASE": policy.max_attempts_per_case,
        "TREATMENT_RETRY_BACKOFF_HOURS": policy.retry_backoff_hours,
        "TREATMENT_MAX_RUNG_ADVANCE": policy.max_rung_advance,
        **{
            f"TREATMENT_COST_{a.upper()}": getattr(costs, a)
            for a in ("sms", "whatsapp", "voice_bot", "human_call", "field_visit", "legal_notice",
                      "represent_mandate", "emi_date_change", "self_service_plan")
        },
    }


def settings() -> list[dict[str, Any]]:
    """Every editable setting with its value, bounds and where the value came from."""
    from agent_core import engine_config

    configured, _ = engine_config.snapshot()
    values = _effective()
    out = []
    for key, group, label, help_text in SETTINGS:
        spec = engine_config.SPEC[key]
        source = "configured" if key in configured else "environment" if os.getenv(key) else "default"
        out.append({
            "key": key, "group": group, "label": label, "help": help_text,
            "value": values.get(key), "source": source, "type": spec.kind,
            "minimum": spec.minimum, "maximum": spec.maximum,
            "choices": list(spec.choices) if spec.choices else None,
        })
    return out


def _validated(changes: dict[str, Any]) -> dict[str, Any]:
    from agent_core import engine_config

    if not changes:
        raise ValueError("a proposal changes at least one setting")
    unknown = sorted(set(changes) - _KEYS)
    if unknown:
        raise ValueError(f"not an editable setting: {', '.join(unknown)}")
    try:
        return {k: engine_config.coerce(k, v) for k, v in changes.items()}
    except engine_config.ConfigRejected as exc:
        raise ValueError(str(exc)) from exc


def impact(conn: Any, changes: dict[str, Any], *, days: int = 7) -> dict[str, Any]:
    """How many of the last week's decisions would have chosen differently.

    Re-ranks each decision's logged options with the new numbers. Only keys
    whose effect is arithmetic on the logged components are estimated.
    """
    from agent_core.treatment import config

    estimable = {k for k in changes if k.startswith("TREATMENT_COST_")} | (
        set(changes) & {"TREATMENT_MIN_EV", "TREATMENT_RECOVERY_FRACTION"}
    )
    if not estimable:
        return {"estimated": False, "note": "the effect of these settings is not estimated before they apply"}
    policy = config.policy(conn=conn)
    old_min, new_min = policy.min_expected_value, float(changes.get("TREATMENT_MIN_EV", policy.min_expected_value))
    old_rf = policy.recovery_fraction or 1.0
    new_rf = float(changes.get("TREATMENT_RECOVERY_FRACTION", old_rf))
    new_cost = {k[len("TREATMENT_COST_"):].lower(): float(v) for k, v in changes.items() if k.startswith("TREATMENT_COST_")}

    rows = conn.execute(
        text(
            """
            SELECT candidates FROM treatment_decisions
             WHERE tenant_id = :t AND mode <> 'simulated'
               AND created_at >= now() - make_interval(days => :days)
               AND COALESCE(to_jsonb(treatment_decisions) ->> 'action_family', '') <> 'offer'
            """
        ),
        {"t": _tenant(), "days": days},
    ).scalars().all()

    def best(cands: list[dict[str, Any]], *, rf: float, costs: dict[str, float], floor: float) -> str:
        top, top_ev = "wait", 0.0
        for c in cands:
            action = str(c.get("action"))
            comp = c.get("components") or {}
            if action == "wait" or "gross" not in comp:
                continue
            cost = costs.get(action, -float(comp.get("cost", 0.0)))
            ev = float(comp["gross"]) * (rf / old_rf) - cost + float(comp.get("fatigue", 0.0))
            if ev >= floor and ev > top_ev:
                top, top_ev = action, ev
        return top

    changed: dict[str, int] = {}
    n = 0
    for cands in rows:
        if not cands:
            continue
        n += 1
        before = best(cands, rf=old_rf, costs={}, floor=old_min)
        after = best(cands, rf=new_rf, costs=new_cost, floor=new_min)
        if before != after:
            key = f"{before}→{after}"
            changed[key] = changed.get(key, 0) + 1
    return {
        "estimated": True,
        "days": days,
        "decisions": n,
        "changed": sum(changed.values()),
        "moves": [{"move": k, "count": v} for k, v in sorted(changed.items(), key=lambda kv: -kv[1])],
    }


def propose(changes: dict[str, Any], *, reason: str, author: str, via: str = "person",
            evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    import db

    if not str(reason or "").strip():
        raise ValueError("a proposal carries a reason")
    stored = _validated(changes)
    pid = f"CFP-{uuid.uuid4().hex[:12].upper()}"
    with db.engine.begin() as conn:
        estimate = impact(conn, stored)
        conn.execute(
            text(
                """
                INSERT INTO engine_config_proposals
                  (id, tenant_id, changes, reason, evidence, impact, proposed_by, proposed_via)
                VALUES (:id, :t, CAST(:c AS jsonb), :r, CAST(:e AS jsonb), CAST(:i AS jsonb), :by, :via)
                """
            ),
            {"id": pid, "t": _tenant(), "c": json.dumps(stored), "r": reason.strip(),
             "e": json.dumps(evidence or {}, default=str), "i": json.dumps(estimate), "by": author, "via": via},
        )
    return get(pid)


def get(proposal_id: str) -> dict[str, Any]:
    import db

    with db.engine.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM engine_config_proposals WHERE id = :id AND tenant_id = :t"),
            {"id": proposal_id, "t": _tenant()},
        ).mappings().first()
    if row is None:
        raise KeyError("proposal_not_found")
    return dict(row)


def proposals(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    import db

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT * FROM engine_config_proposals
                 WHERE tenant_id = :t AND (CAST(:s AS text) IS NULL OR status = :s)
                 ORDER BY created_at DESC LIMIT :n
                """
            ),
            {"t": _tenant(), "s": status, "n": max(1, min(limit, 200))},
        ).mappings().all()
    return [dict(r) for r in rows]


def decide(proposal_id: str, *, approve: bool, decider: str, note: str | None = None) -> dict[str, Any]:
    """Approve (apply every change) or reject. The author cannot approve."""
    import db
    from agent_core import engine_config
    from agent_core.treatment import beliefs

    tenant = _tenant()
    with db.engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT * FROM engine_config_proposals WHERE id = :id AND tenant_id = :t FOR UPDATE"
            ),
            {"id": proposal_id, "t": tenant},
        ).mappings().first()
        if row is None:
            raise KeyError("proposal_not_found")
        if row["status"] != "pending":
            raise ValueError(f"proposal is already {row['status']}")
        if approve and row["proposed_by"] == decider:
            raise PermissionError("the author of a proposal cannot approve it")
        if approve:
            for key, value in dict(row["changes"]).items():
                engine_config.put(
                    conn, key, value, tenant_id=tenant, changed_by=row["proposed_by"],
                    approved_by=decider, reason=f"{row['reason']} [{proposal_id}]",
                )
        conn.execute(
            text(
                """
                UPDATE engine_config_proposals
                   SET status = :s, decided_by = :by, decided_at = now(), decision_note = :note
                 WHERE id = :id
                """
            ),
            {"id": proposal_id, "s": "approved" if approve else "rejected", "by": decider, "note": note},
        )
    engine_config.invalidate()
    beliefs.invalidate()
    return get(proposal_id)
