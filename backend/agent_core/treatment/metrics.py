"""§17's scoreboard — the six categories, computed rather than asserted.

``decisions.insights`` already answers "is this safe to switch on?" — coverage,
suppression breakdown, ladder mix. This answers the different and harder
question the design note ends on: **is it working, and what is it costing?**

**The primary metric is incremental recovery per rupee spent, measured against
the control arm, and everything else is context.** Not collections rate. A
response model looks *excellent* on collections rate precisely because it
targets the borrowers who were going to pay anyway and books their payments as
its own — so a dashboard whose headline is collections rate will show the wrong
system winning, in green, for months.

**Every causal number here is a difference against the randomised arm.** Where
the arm is too thin to support one, the field says so instead of returning a
figure. A metric that silently degrades to a non-causal proxy is worse than a
missing metric, because a missing metric gets chased.

**Voice minutes per rupee recovered is deliberately prominent.** §18's whole
point is that a working decision engine's first observable effect is a drop in
call volume, and that this is the intended behaviour rather than a regression.
A metric that makes the drop visible *next to* the recovery it did not cost is
what turns an alarming chart into the value proposition.

Reads the log and touches no borrower.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

#: `customers.timezone` holds display labels ("Asia/Kolkata (IST)") in
#: seeded data. An unrecognised zone does not fail one row -- it aborts the
#: transaction. One definition, shared with contact_policy._zone's policy.
import contact_policy

_SAFE_TZ = contact_policy.safe_tz_sql("c.timezone")

logger = logging.getLogger(__name__)

CONTROL_ARM = "null_treatment"

#: Cases per arm below which no causal figure is reported. Deliberately blunt.
#: A cure-rate difference computed from forty cases is not a cure-rate
#: difference, and the whole purpose of this module is to stop a number that
#: cannot support weight from being put under one.
MIN_ARM_N = 100


def _scalar(row: Any, key: str, default: float = 0.0) -> float:
    if not row:
        return default
    value = row.get(key)
    return float(value) if value is not None else default


def causal(conn: Any, *, days: int, modes: list[str]) -> dict[str, Any]:
    """Incremental cure rate and incremental rupees per rupee spent.

    Both are differences against the control arm, and both are reported with
    their arm sizes attached so a reader can see what the number is made of.
    """
    row = conn.execute(
        text(
            """
            SELECT
              count(*) FILTER (WHERE variant = :arm AND outcome IS NOT NULL)::int
                AS control_n,
              count(*) FILTER (WHERE variant = :arm AND outcome IN ('paid','ptp'))::int
                AS control_cured,
              count(*) FILTER (
                WHERE variant <> :arm AND outcome IS NOT NULL
                  AND chosen_action IS NOT NULL AND chosen_action <> 'wait'
              )::int AS treated_n,
              count(*) FILTER (
                WHERE variant <> :arm AND outcome IN ('paid','ptp')
                  AND chosen_action IS NOT NULL AND chosen_action <> 'wait'
              )::int AS treated_cured
            FROM treatment_decisions
            WHERE mode = ANY(:modes)
              AND created_at >= now() - make_interval(days => :days)
            """
        ),
        {"arm": CONTROL_ARM, "modes": modes, "days": days},
    ).mappings().first()

    control_n = int(_scalar(row, "control_n"))
    treated_n = int(_scalar(row, "treated_n"))
    control_cured = int(_scalar(row, "control_cured"))
    treated_cured = int(_scalar(row, "treated_cured"))

    if control_n < MIN_ARM_N or treated_n < MIN_ARM_N:
        return {
            "available": False,
            "reason": (
                f"control arm holds {control_n} and the treated arm {treated_n} "
                f"labelled cases (need {MIN_ARM_N} each). Without both there is no "
                "causal number here, only a collections rate — and a collections "
                "rate is exactly what this scoreboard exists not to report."
            ),
            "controlN": control_n,
            "treatedN": treated_n,
        }

    control_rate = control_cured / control_n
    treated_rate = treated_cured / treated_n
    incremental = treated_rate - control_rate

    # What the treated arm actually cost and actually recovered, so the ratio is
    # rupees over rupees rather than a modelled expectation over a modelled cost.
    #
    # From ``ledger_entries``, not ``payment_events``. The name misleads: that
    # table's ``kind`` is CHECK-constrained to ``'bounce'`` and it is a returns
    # ledger, so a recovery figure read from it is structurally zero. Found by
    # this metric reporting nothing recovered on a book where a fifth of the
    # accounts had cured -- which is the same failure mode as the complaint rate
    # below, caught here only because the corpus was large enough for zero to be
    # obviously wrong.
    money = conn.execute(
        text(
            """
            SELECT
              COALESCE(sum(le.amount), 0)::float AS recovered,
              count(DISTINCT le.id)::int AS payments
            FROM ledger_entries le
            JOIN accounts a ON a.id = le.account_id
            WHERE le.type = 'payment'
              AND le.posted_at >= now() - make_interval(days => :days)
              AND EXISTS (
                SELECT 1 FROM treatment_decisions d
                WHERE d.customer_id = a.customer_id
                  AND d.mode = ANY(:modes)
                  AND d.variant <> :arm
                  AND d.enacted
                  AND d.created_at >= now() - make_interval(days => :days)
                  AND d.created_at <= le.posted_at
              )
            """
        ),
        {"days": days, "modes": modes, "arm": CONTROL_ARM},
    ).mappings().first()

    spend = conn.execute(
        text(
            """
            SELECT COALESCE(sum((c.entry ->> 'cost')::numeric), 0)::float AS spend
            FROM treatment_decisions d
            CROSS JOIN LATERAL jsonb_array_elements(d.candidates) AS c(entry)
            WHERE d.mode = ANY(:modes)
              AND d.enacted
              AND d.variant <> :arm
              AND d.created_at >= now() - make_interval(days => :days)
              AND c.entry ->> 'action' = d.chosen_action
            """
        ),
        {"days": days, "modes": modes, "arm": CONTROL_ARM},
    ).mappings().first()

    recovered = _scalar(money, "recovered")
    spent = _scalar(spend, "spend")
    # Only the *incremental* share of the recovery is attributable. Crediting
    # the whole of it is the response-model error in accounting form: most of
    # that money belonged to borrowers who would have paid regardless, and the
    # control arm is what says how much.
    attributable = recovered * (incremental / treated_rate) if treated_rate > 0 else 0.0

    return {
        "available": True,
        "controlN": control_n,
        "treatedN": treated_n,
        "controlCureRate": round(control_rate, 4),
        "treatedCureRate": round(treated_rate, 4),
        "incrementalCureRate": round(incremental, 4),
        "recoveredInr": round(recovered, 2),
        "attributableRecoveryInr": round(attributable, 2),
        "spendInr": round(spent, 2),
        "incrementalRecoveryPerRupee": (
            round(attributable / spent, 2) if spent > 0 else None
        ),
        "note": (
            "attributable recovery is the incremental share only — the rest belonged "
            "to borrowers the control arm says would have paid anyway"
        ),
    }


def efficiency(conn: Any, *, days: int, modes: list[str]) -> dict[str, Any]:
    """Cost, contacts and voice minutes, each per resolution.

    Voice minutes come from ``interactions.duration_sec`` rather than from
    anything the engine predicted, because §18's claim is about what actually
    happened on the phones.
    """
    row = conn.execute(
        text(
            """
            SELECT
              count(*) FILTER (WHERE outcome IN ('paid','ptp'))::int AS resolutions,
              count(*) FILTER (WHERE enacted AND chosen_channel IS NOT NULL)::int
                AS contacts,
              count(DISTINCT customer_id)::int AS customers
            FROM treatment_decisions
            WHERE mode = ANY(:modes)
              AND created_at >= now() - make_interval(days => :days)
            """
        ),
        {"modes": modes, "days": days},
    ).mappings().first()

    voice = conn.execute(
        text(
            """
            SELECT COALESCE(sum(duration_sec), 0)::float / 60.0 AS minutes,
                   count(*)::int AS calls
            FROM interactions
            WHERE channel = 'voice'
              AND started_at >= now() - make_interval(days => :days)
            """
        ),
        {"days": days},
    ).mappings().first()

    recovered = conn.execute(
        text(
            """
            SELECT COALESCE(sum(amount), 0)::float AS recovered
            FROM ledger_entries
            WHERE type = 'payment'
              AND posted_at >= now() - make_interval(days => :days)
            """
        ),
        {"days": days},
    ).mappings().first()

    resolutions = int(_scalar(row, "resolutions"))
    contacts = int(_scalar(row, "contacts"))
    minutes = _scalar(voice, "minutes")
    money = _scalar(recovered, "recovered")

    return {
        "resolutions": resolutions,
        "contacts": contacts,
        "voiceMinutes": round(minutes, 1),
        "voiceCalls": int(_scalar(voice, "calls")),
        "contactsPerResolution": round(contacts / resolutions, 2) if resolutions else None,
        "voiceMinutesPerResolution": round(minutes / resolutions, 2) if resolutions else None,
        # §18's number. Watch it fall.
        "voiceMinutesPerLakhRecovered": (
            round(minutes / (money / 100_000.0), 2) if money >= 1000 else None
        ),
        "recoveredInr": round(money, 2),
    }


def compliance(conn: Any, *, days: int) -> dict[str, Any]:
    """Denials, breaches and complaints. The breach count's target is zero.

    Reported from ``contact_events``, which is the policy gate's own ledger, not
    from the engine's opinion of what it would have done. The gate runs again at
    send time, and this is the record of that second run — the one that would
    catch an executor going around the engine.
    """
    gate = conn.execute(
        text(
            """
            SELECT outcome, COALESCE(reason, 'none') AS reason, count(*)::int AS n
            FROM contact_events
            WHERE occurred_at >= now() - make_interval(days => :days)
            GROUP BY 1, 2
            """
        ),
        {"days": days},
    ).mappings().all()

    allowed = sum(r["n"] for r in gate if r["outcome"] == "allowed")
    denied = sum(r["n"] for r in gate if r["outcome"] == "denied")
    by_reason = sorted(
        ({"reason": r["reason"], "count": r["n"]} for r in gate if r["outcome"] == "denied"),
        key=lambda d: -d["count"],
    )

    breaches = _breaches(conn, days=days)
    optouts = conn.execute(
        text(
            """
            SELECT count(*)::int AS n
            FROM optout_events
            WHERE occurred_at >= now() - make_interval(days => :days)
            """
        ),
        {"days": days},
    ).mappings().first()

    attempts = allowed + denied
    return {
        "attempts": attempts,
        "allowed": allowed,
        "denied": denied,
        "denialRate": round(denied / attempts, 4) if attempts else None,
        "denialsByReason": by_reason[:10],
        **breaches,
        "optOuts": int(_scalar(optouts, "n")),
        # §17 asks for a complaint rate and there is nowhere in this schema to
        # read one from. ``disputes.type`` is constrained to billing disputes —
        # paid_already, wrong_amount, not_my_account, fee_waiver,
        # duplicate_charge, fraud — with no conduct or harassment value, and
        # nothing else in the model records a complaint about *how* a borrower
        # was contacted.
        #
        # Reported as missing rather than as zero. A conduct-complaint rate that
        # reads 0.00 every week because its source does not exist is worse than
        # an absent metric: an absent metric gets chased, and a green one gets
        # cited in a compliance review.
        "complaints": {
            "available": False,
            "reason": (
                "no conduct-complaint source in the schema — disputes.type carries "
                "billing disputes only. Needs a complaint intake before this can be "
                "a number."
            ),
        },
    }


def _breaches(conn: Any, *, days: int) -> dict[str, Any]:
    """Contacts that got through the gate but should not have. Target: zero.

    A denial is the system working and is counted elsewhere. A *breach* is an
    outbound contact recorded as allowed that nonetheless landed outside the
    permitted calling window, or that took a borrower past the daily cap. There
    is no reason code for this and there should not be — the gate does not
    record permission it did not grant — so it is audited from the ledger after
    the fact.

    That is the point of measuring it here at all. Anything this finds got
    around ``contact_policy.evaluate()``, which means an executor reached a
    borrower without asking, and no amount of correct gate logic would have
    caught it.
    """
    from contact_policy import RBI_VOICE_END, RBI_VOICE_START, daily_cap

    window = conn.execute(
        text(
            """
            SELECT count(*)::int AS n
            FROM contact_events ce
            JOIN customers c ON c.id = ce.customer_id
            WHERE ce.outcome = 'allowed'
              AND ce.direction = 'outbound'
              AND ce.purpose = 'outreach'
              AND ce.channel = 'voice'
              AND ce.occurred_at >= now() - make_interval(days => :days)
              AND (
                EXTRACT(HOUR FROM ce.occurred_at AT TIME ZONE
                    """ + _SAFE_TZ + """) < :start
                OR EXTRACT(HOUR FROM ce.occurred_at AT TIME ZONE
                    """ + _SAFE_TZ + """) >= :end_h
              )
            """
        ),
        {"days": days, "start": RBI_VOICE_START, "end_h": RBI_VOICE_END},
    ).mappings().first()

    cap = daily_cap()
    over_cap = conn.execute(
        text(
            """
            WITH per_day AS (
              SELECT ce.customer_id,
                     (ce.occurred_at AT TIME ZONE
                        """ + _SAFE_TZ + """)::date AS day,
                     count(*)::int AS touches
              FROM contact_events ce
              JOIN customers c ON c.id = ce.customer_id
              WHERE ce.outcome = 'allowed'
                AND ce.touch_counted
                AND ce.direction = 'outbound'
                AND ce.purpose = 'outreach'
                AND ce.occurred_at >= now() - make_interval(days => :days)
              GROUP BY 1, 2
            )
            SELECT count(*)::int AS n, COALESCE(max(touches), 0)::int AS worst
            FROM per_day WHERE touches > :cap
            """
        ),
        {"days": days, "cap": cap},
    ).mappings().first()

    window_n = int(_scalar(window, "n"))
    cap_n = int(_scalar(over_cap, "n"))
    return {
        "windowBreaches": window_n,
        "capBreaches": cap_n,
        "worstDayTouches": int(_scalar(over_cap, "worst")),
        "dailyCap": cap,
        "breaches": window_n + cap_n,
        "breachTarget": 0,
        "breachNote": (
            "audited from the contact ledger after the fact, not from a denial "
            "reason. Anything counted here got past contact_policy.evaluate() — "
            "which means an executor contacted a borrower without asking."
            if (window_n + cap_n)
            else "none — every allowed outbound contact was inside its window and cap"
        ),
    }


def borrower_experience(conn: Any, *, days: int, modes: list[str]) -> dict[str, Any]:
    """What this feels like from the other end.

    Contacts per borrower per *case*, not per borrower per month — the case is
    the unit a borrower experiences as "they keep calling me about this", and
    averaging across cases would hide a borrower contacted eleven times about
    one missed instalment behind eleven borrowers contacted once.
    """
    row = conn.execute(
        text(
            """
            WITH per_case AS (
              SELECT customer_id, trigger_kind, trigger_ref,
                     count(*) FILTER (WHERE enacted AND chosen_channel IS NOT NULL)::int
                       AS contacts
              FROM treatment_decisions
              WHERE mode = ANY(:modes)
                AND created_at >= now() - make_interval(days => :days)
              GROUP BY 1, 2, 3
            )
            SELECT count(*)::int AS cases,
                   COALESCE(avg(contacts), 0)::float AS avg_contacts,
                   COALESCE(max(contacts), 0)::int AS max_contacts,
                   count(*) FILTER (WHERE contacts >= 5)::int AS heavy_cases
            FROM per_case
            """
        ),
        {"modes": modes, "days": days},
    ).mappings().first()

    cases = int(_scalar(row, "cases"))
    return {
        "cases": cases,
        "contactsPerCase": round(_scalar(row, "avg_contacts"), 2),
        "worstCaseContacts": int(_scalar(row, "max_contacts")),
        "casesOverFiveContacts": int(_scalar(row, "heavy_cases")),
        "heavyCaseShare": (
            round(_scalar(row, "heavy_cases") / cases, 4) if cases else None
        ),
    }


def capacity(conn: Any, *, days: int) -> dict[str, Any]:
    """Utilisation and dual-price stability.

    A dual price that swings wildly day to day is not a signal, it is noise
    entering the cost term — and because the cost term feeds every local
    decision, an unstable price makes the whole ladder oscillate. The spread is
    reported rather than the mean for exactly that reason.
    """
    rows = conn.execute(
        text(
            """
            SELECT resource,
                   count(*)::int AS days_solved,
                   COALESCE(avg(dual_price), 0)::float AS avg_price,
                   COALESCE(min(dual_price), 0)::float AS min_price,
                   COALESCE(max(dual_price), 0)::float AS max_price,
                   COALESCE(avg(CASE WHEN capacity > 0 THEN demand / capacity END), 0)::float
                     AS utilisation,
                   count(*) FILTER (WHERE NOT converged)::int AS non_converged
            FROM capacity_duals
            WHERE plan_date >= (now() - make_interval(days => :days))::date
            GROUP BY 1
            ORDER BY 3 DESC
            """
        ),
        {"days": days},
    ).mappings().all()

    out = []
    for r in rows:
        avg = float(r["avg_price"])
        spread = float(r["max_price"]) - float(r["min_price"])
        out.append(
            {
                "resource": r["resource"],
                "daysSolved": r["days_solved"],
                "avgDualPriceInr": round(avg, 2),
                "priceSpreadInr": round(spread, 2),
                # Coefficient of variation as a stability proxy. Unpriced
                # resources are stable at zero, which is correct and not
                # interesting.
                "stability": (
                    "unpriced" if avg <= 0
                    else "stable" if spread / avg < 0.5
                    else "volatile"
                ),
                "utilisation": round(float(r["utilisation"]), 3),
                "nonConvergedDays": r["non_converged"],
            }
        )
    return {"resources": out, "solved": bool(out)}


def report(conn: Any, *, days: int = 28, include_simulated: bool = False) -> dict[str, Any]:
    """All six §17 categories over one window."""
    modes = ["shadow", "live"] + (["simulated"] if include_simulated else [])
    from agent_core.treatment import monitor

    return {
        "windowDays": int(days),
        "causal": causal(conn, days=days, modes=modes),
        "efficiency": efficiency(conn, days=days, modes=modes),
        "modelHealth": monitor.report(
            conn, days=days, include_simulated=include_simulated
        ),
        "compliance": compliance(conn, days=days),
        "borrowerExperience": borrower_experience(conn, days=days, modes=modes),
        "capacity": capacity(conn, days=days),
    }
