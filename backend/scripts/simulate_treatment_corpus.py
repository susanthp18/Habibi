#!/usr/bin/env python
"""Development tool — synthesise a delinquent book and a decision corpus.

    TREATMENT_SIMULATION_OK=1 .venv/Scripts/python scripts/simulate_treatment_corpus.py
    TREATMENT_SIMULATION_OK=1 .venv/Scripts/python scripts/simulate_treatment_corpus.py \\
        --accounts 2000 --days 60 --greediness 0.6 --control-share 0.2
    .venv/Scripts/python scripts/simulate_treatment_corpus.py --purge

**This is not production data and must never be run against a production
database.** It refuses to run without ``TREATMENT_SIMULATION_OK=1``, every
borrower it creates is tagged, and every decision it writes carries
``mode='simulated'`` so the executor, the follow-through loop, the trainers and
the dashboards all exclude it with one predicate.

Why it exists
-------------

The live book is twenty customers and no payment events. An uplift model is the
difference between two noisy quantities and needs an order of magnitude more
data than a response model; a randomised control arm needs enough accounts to
power a comparison. Neither is reachable here, and waiting for real traffic
means every part of the pipeline downstream of a corpus — off-policy
evaluation, the granularity ladder, the champion/challenger gate — ships
untested.

So the *engine* is real: this calls ``recommend_treatment`` against the real
schema, through the real vetoes, with the real scorer and the real exploration
policy. Only the borrowers are invented, and the outcomes are drawn from a
latent truth the simulator controls.

The latent truth, and why it is shaped this way
-----------------------------------------------

Three properties, each of which exists to make a specific claim testable rather
than to make the numbers look good:

**A genuine self-cure process.** A share of early-bucket borrowers pay with no
contact at all. Without them the corpus cannot tell a response model from an
uplift model, because every cure would be attributable to something we did —
which is precisely the illusion the whole design note is written against. The
share is a *parameter*, not a published figure: the real number is whatever a
real control arm measures on a real book, and quoting an industry statistic
here would smuggle in exactly the unfounded number this simulator exists to
avoid needing.

**Heterogeneous treatment effects.** Uplift varies by segment, and — this is
the part that matters — it varies *inversely* with self-cure. The borrowers
most likely to pay anyway are the ones our contact changes least. A response
model ranks them first; an uplift model ranks them last. If the simulator did
not encode that inversion there would be nothing for an uplift model to
discover that a propensity model would not find first.

**A different function from the scorer.** ``EVScorer``'s priors are not used to
draw outcomes. A simulated customer who accepted exactly what the shipped
scorer already ranks first would teach a model trained on the corpus to imitate
the baseline, and the exercise would prove only that the code runs.

What it does not simulate
-------------------------

Reach is drawn per channel and per hour, but there is no delivery-receipt
ledger in this stack, so the WhatsApp "reach" it generates is the same
reply-shaped proxy the real feature builder uses. That is a faithful copy of a
real gap rather than a fix for it, and a reach model trained on this corpus
inherits the gap honestly.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from env_loader import load_env

load_env()

import db  # noqa: E402
from sqlalchemy import text  # noqa: E402

from agent_core.treatment import actions as A, config, decisions  # noqa: E402
from agent_core.treatment.engine import recommend_treatment  # noqa: E402
from agent_core.treatment.features import Trigger  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("simulate_treatment")

#: Every generated borrower carries this prefix. One predicate deletes the
#: whole synthetic book, and no query can mistake one for a real customer.
TAG = "SIM-"

GUARD_ENV = "TREATMENT_SIMULATION_OK"

#: Segments, and the two numbers that make the corpus worth fitting.
#:
#: ``self_cure`` is P(the borrower pays within the window with no contact).
#: ``uplift`` is the *additional* probability a well-chosen contact buys.
#:
#: Note the inversion, which is the entire point: ``forgetful`` borrowers cure
#: on their own most of the time and our contact adds almost nothing, while
#: ``squeezed`` borrowers rarely cure alone and respond strongly. A response
#: model ranks forgetful first and books their self-cures as its own success.
SEGMENTS: dict[str, dict[str, float]] = {
    # Salary landed late, mandate presented on the wrong day. Cures itself.
    "forgetful": {"self_cure": 0.72, "uplift": 0.04, "share": 0.35},
    # Genuinely short this month, will pay if reminded and given a route.
    "squeezed": {"self_cure": 0.18, "uplift": 0.34, "share": 0.30},
    # Avoiding it. Moves only for a person, and not always then.
    "avoidant": {"self_cure": 0.06, "uplift": 0.22, "share": 0.20},
    # In real difficulty. Contact does very little and costs goodwill.
    "distressed": {"self_cure": 0.04, "uplift": 0.05, "share": 0.15},
}

#: How much of a segment's uplift each action actually realises. Deliberately
#: *not* the shape of RESOLVE_PRIOR: a mandate presentment is the strongest
#: instrument here for the squeezed borrower whose account is simply empty on
#: the 3rd, and the cheapest channels do almost nothing for the avoidant one.
#: A scorer that learned this from the corpus would rank differently from the
#: one that generated it, which is what makes the corpus worth fitting.
ACTION_EFFICACY: dict[str, dict[str, float]] = {
    "forgetful": {
        A.REPRESENT_MANDATE: 1.00,
        A.EMI_DATE_CHANGE: 0.80,
        A.SMS: 0.55,
        A.WHATSAPP: 0.70,
        A.VOICE_BOT: 0.60,
        A.HUMAN_CALL: 0.60,
        A.FIELD_VISIT: 0.50,
        A.LEGAL_NOTICE: 0.30,
    },
    "squeezed": {
        A.REPRESENT_MANDATE: 0.95,
        A.EMI_DATE_CHANGE: 0.90,
        A.SMS: 0.35,
        A.WHATSAPP: 0.60,
        A.VOICE_BOT: 0.70,
        A.HUMAN_CALL: 0.90,
        A.FIELD_VISIT: 0.75,
        A.LEGAL_NOTICE: 0.55,
    },
    "avoidant": {
        A.REPRESENT_MANDATE: 0.45,
        A.EMI_DATE_CHANGE: 0.25,
        A.SMS: 0.10,
        A.WHATSAPP: 0.20,
        A.VOICE_BOT: 0.35,
        A.HUMAN_CALL: 0.85,
        A.FIELD_VISIT: 1.00,
        A.LEGAL_NOTICE: 0.90,
    },
    "distressed": {
        A.REPRESENT_MANDATE: 0.30,
        A.EMI_DATE_CHANGE: 0.60,
        A.SMS: 0.10,
        A.WHATSAPP: 0.25,
        A.VOICE_BOT: 0.20,
        A.HUMAN_CALL: 0.55,
        A.FIELD_VISIT: 0.30,
        A.LEGAL_NOTICE: 0.20,
    },
}

#: Return-code mix on a bounce. Insufficient funds dominates, which is what
#: makes salary-timed re-presentment the highest-value action in the book.
RETURN_MIX: list[tuple[str, float]] = [
    ("insufficient_funds", 0.68),
    ("technical", 0.12),
    ("mandate_expired", 0.11),
    ("account_closed", 0.06),
    ("unknown", 0.03),
]


# ---------------------------------------------------------------------------
# The book
# ---------------------------------------------------------------------------


def _pick(rng: random.Random, weighted: list[tuple[str, float]]) -> str:
    position = rng.random() * sum(w for _, w in weighted)
    cumulative = 0.0
    for key, weight in weighted:
        cumulative += weight
        if position < cumulative:
            return key
    return weighted[-1][0]


def _segment(rng: random.Random) -> str:
    return _pick(rng, [(k, v["share"]) for k, v in SEGMENTS.items()])


def build_book(conn: Any, *, tenant: str, product_id: str, count: int, rng: random.Random) -> int:
    """Create synthetic borrowers, accounts, EMIs, mandates and bounces.

    Written straight to the tables the feature builder reads, rather than
    through the API, because the point is to exercise the decision path and not
    the ingest path — and because a thousand accounts through HTTP is a slow
    way to find out that ``p_reach`` has the wrong sign.
    """
    made = 0
    today = datetime.now(timezone.utc)
    for index in range(count):
        segment = _segment(rng)
        customer_id = f"{TAG}C{index:06d}"
        account_id = f"{TAG}A{index:06d}"

        # DPD skewed early: a real book is mostly 0-30, and a simulator that
        # produces a uniform spread would over-represent exactly the buckets
        # where the engine has fewest options.
        dpd = int(min(150, max(1, rng.lognormvariate(2.6, 0.9))))
        instalment = round(rng.lognormvariate(8.3, 0.55), 2)
        outstanding = round(instalment * rng.uniform(3, 30), 2)

        # The salary lands on a day of its own. The gap between it and the EMI
        # due day is what emi_date_change exists to close, so it has to be real
        # rather than always aligned.
        salary_day = rng.randint(1, 28)
        due_day = rng.choice([salary_day - rng.randint(1, 6), salary_day + rng.randint(1, 4)])
        due_day = max(1, min(28, due_day))

        conn.execute(
            text(
                """
                INSERT INTO customers (
                  id, tenant_id, name, phone_primary, email, language,
                  timezone, segment, risk, risk_score, dnd
                ) VALUES (
                  :id, :tenant, :name, :phone, :email, 'en',
                  'Asia/Kolkata', :segment, :risk, :score, false
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": customer_id,
                "tenant": tenant,
                "name": f"Simulated Borrower {index:06d}",
                # Reserved test range, never routable. A generator that emitted
                # plausible Indian mobile numbers would be one misconfigured
                # env away from messaging a stranger.
                "phone": f"+15005550{index % 1000:03d}",
                "email": f"sim{index:06d}@example.invalid",
                "segment": segment,
                "risk": "high" if segment in {"avoidant", "distressed"} else "medium",
                "score": rng.randint(300, 800),
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO accounts (
                  id, customer_id, product_id, outstanding, minimum_due,
                  dpd, bucket, status, opened_on
                ) VALUES (
                  :id, :cid, :pid, :outstanding, :minimum_due,
                  :dpd, :bucket, 'active', :opened
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": account_id,
                "cid": customer_id,
                "pid": product_id,
                "outstanding": outstanding,
                "minimum_due": instalment,
                "dpd": dpd,
                "bucket": A.bucket_for(dpd),
                "opened": today - timedelta(days=rng.randint(120, 900)),
            },
        )

        due_at = _month_day(today - timedelta(days=dpd), due_day)
        conn.execute(
            text(
                """
                INSERT INTO emi_installments (
                  id, account_id, installment_index, due_date, amount, status
                ) VALUES (:id, :aid, 1, :due, :amount, 'overdue')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": f"{TAG}E{index:06d}",
                "aid": account_id,
                "due": due_at,
                "amount": instalment,
            },
        )

        # Most accounts have a live mandate; some do not, and some have one the
        # borrower cancelled. All three states have to appear or the veto that
        # tells them apart is never exercised.
        mandate_state = _pick(
            rng, [("active", 0.72), ("cancelled", 0.12), ("expired", 0.06), ("none", 0.10)]
        )
        if mandate_state != "none":
            conn.execute(
                text(
                    """
                    INSERT INTO mandates (
                      id, tenant_id, customer_id, account_id, rail, umrn,
                      status, max_amount, debit_day, registered_at
                    ) VALUES (
                      :id, :tenant, :cid, :aid, :rail, :umrn,
                      :status, :max_amount, :debit_day, :registered
                    )
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                {
                    "id": f"{TAG}M{index:06d}",
                    "tenant": tenant,
                    "cid": customer_id,
                    "aid": account_id,
                    "rail": _pick(rng, [("nach", 0.6), ("enach", 0.25), ("upi_autopay", 0.15)]),
                    "umrn": f"{TAG}UMRN{index:06d}",
                    "status": mandate_state,
                    "max_amount": round(instalment * rng.uniform(1.0, 2.0), 2),
                    "debit_day": due_day,
                    "registered": today - timedelta(days=rng.randint(200, 900)),
                },
            )

        reason = _pick(rng, RETURN_MIX)
        conn.execute(
            text(
                """
                INSERT INTO payment_events (
                  id, tenant_id, customer_id, account_id, emi_installment_id,
                  kind, reason, amount, source, source_ref, status,
                  next_credit_at, occurred_at
                ) VALUES (
                  :id, :tenant, :cid, :aid, :eid,
                  'bounce', :reason, :amount, 'nach', :ref, 'open',
                  :credit, :occurred
                )
                ON CONFLICT (tenant_id, source, source_ref) DO NOTHING
                """
            ),
            {
                "id": f"{TAG}P{index:06d}",
                "tenant": tenant,
                "cid": customer_id,
                "aid": account_id,
                "eid": f"{TAG}E{index:06d}",
                "reason": reason,
                "amount": instalment,
                "ref": f"{TAG}REF{index:06d}",
                # The salary-credit hint the timing module plans against. In
                # the future, or the module has nothing to aim at.
                "credit": _next_month_day(today, salary_day),
                "occurred": today - timedelta(days=min(dpd, 45)),
            },
        )
        made += 1
    return made


def _month_day(base: datetime, day: int) -> datetime:
    from calendar import monthrange

    last = monthrange(base.year, base.month)[1]
    return base.replace(day=min(day, last), hour=9, minute=0, second=0, microsecond=0)


def _next_month_day(base: datetime, day: int) -> datetime:
    candidate = _month_day(base, day)
    if candidate > base:
        return candidate
    nxt = (base.replace(day=1) + timedelta(days=32)).replace(day=1)
    return _month_day(nxt, day)


# ---------------------------------------------------------------------------
# The corpus
# ---------------------------------------------------------------------------


def sweep_day(
    conn: Any, *, day: datetime, rng: random.Random, limit: int
) -> tuple[int, int]:
    """One simulated day of decisions and their outcomes.

    Returns (decisions, cures).
    """
    accounts = conn.execute(
        text(
            """
            SELECT a.id, a.customer_id, c.segment
            FROM accounts a JOIN customers c ON c.id = a.customer_id
            WHERE a.id LIKE :tag AND a.status = 'active' AND a.dpd > 0
            ORDER BY a.id
            LIMIT :limit
            """
        ),
        {"tag": f"{TAG}%", "limit": limit},
    ).mappings().all()

    made = cured = 0
    ref = day.date().isoformat()
    for account in accounts:
        result = recommend_treatment(
            customer_id=account["customer_id"],
            account_id=account["id"],
            trigger=Trigger(kind="dpd_tick", at=day, ref=ref),
            now=day,
            conn=conn,
            force_mode=config.MODE_SIMULATED,
        )
        if result.decision_id is None:
            continue
        made += 1
        if _settle(conn, result, segment=str(account["segment"]), rng=rng, day=day):
            cured += 1
    return made, cured


def _settle(
    conn: Any, result: Any, *, segment: str, rng: random.Random, day: datetime
) -> bool:
    """Draw the outcome from the latent truth and write it to the decision.

    The counterfactual is drawn *first* and independently of the action: this
    borrower either would have cured on their own this window or not, and the
    treatment then gets its own chance on top. Drawing them jointly would make
    self-cure and uplift statistically inseparable, and separating them is the
    only reason the corpus is worth generating.
    """
    profile = SEGMENTS.get(segment, SEGMENTS["squeezed"])
    action = result.action

    self_cured = rng.random() < profile["self_cure"] * _window_factor(action)
    incremental = 0.0
    if action != A.WAIT and not result.suppressed:
        efficacy = ACTION_EFFICACY.get(segment, {}).get(action, 0.2)
        incremental = profile["uplift"] * efficacy
    treated_cure = self_cured or (rng.random() < incremental)

    if action == A.WAIT or result.suppressed:
        # Nothing was done. A cure here is a self-cure and is recorded as one —
        # this is the control observation, and it is the only row in the corpus
        # that can say what would have happened anyway.
        outcome = "paid" if self_cured else None
        if outcome:
            decisions.record_outcome(result.decision_id, outcome, conn=conn)
        return bool(outcome)

    decisions.mark_enacted(
        result.decision_id, ref=f"{TAG}SIM", conn=conn, enacted_by="treatment_executor"
    )
    if treated_cure:
        outcome = "paid"
    elif rng.random() < _reach_probability(action):
        outcome = rng.choice(["reached", "ptp", "refused"])
    else:
        outcome = "no_answer"
    decisions.record_outcome(result.decision_id, outcome, conn=conn)
    return outcome in {"paid", "ptp"}


def _window_factor(action: str) -> float:
    """Self-cure is a property of the borrower, not of what we did.

    Returned as a constant on purpose. It is here as a named seam rather than
    an inline 1.0 so that anyone tempted to make self-cure depend on the action
    has to delete a docstring saying why they must not: the moment it does, the
    control observation stops being a counterfactual and the corpus can no
    longer measure uplift at all.
    """
    return 1.0


def _reach_probability(action: str) -> float:
    spec = A.spec(action)
    if spec.channel is None:
        return 1.0
    return {"sms": 0.30, "whatsapp": 0.50, "voice": 0.28, "field": 0.55}.get(
        spec.channel, 0.3
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def purge(conn: Any) -> dict[str, int]:
    """Remove every simulated row. Safe to run against a real database.

    Deletes by tag and by mode, never by date or by "everything recent" — a
    cleanup that could reach a real borrower is a worse bug than the mess it
    tidies.
    """
    counts: dict[str, int] = {}
    counts["decisions"] = conn.execute(
        text("DELETE FROM treatment_decisions WHERE mode = 'simulated'")
    ).rowcount
    # Customers cascade to accounts, EMIs, mandates, presentations and payment
    # events, so the tagged delete is one statement rather than six.
    counts["customers"] = conn.execute(
        text("DELETE FROM customers WHERE id LIKE :tag"), {"tag": f"{TAG}%"}
    ).rowcount
    return counts


def _product(conn: Any, tenant: str) -> str | None:
    return conn.execute(
        text("SELECT id FROM products WHERE tenant_id = :t ORDER BY id LIMIT 1"),
        {"t": tenant},
    ).scalar()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accounts", type=int, default=500)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=20260820)
    parser.add_argument(
        "--greediness",
        type=float,
        default=0.6,
        help="exploration dial for the simulated run; 1.0 is pure argmax",
    )
    parser.add_argument(
        "--control-share",
        type=float,
        default=0.2,
        help="fraction of borrowers randomised into the null-treatment arm",
    )
    parser.add_argument("--purge", action="store_true", help="delete the simulated book")
    args = parser.parse_args()

    if args.purge:
        with db.engine.begin() as conn:
            logger.info("purged %s", purge(conn))
        return

    if (os.getenv(GUARD_ENV) or "").strip() != "1":
        logger.error(
            "refusing to run without %s=1 — this writes synthetic borrowers into "
            "whatever database DATABASE_URL points at",
            GUARD_ENV,
        )
        raise SystemExit(2)

    rng = random.Random(args.seed)
    tenant = db.current_tenant()

    # The exploration dial and the control arm are set for the duration of the
    # run rather than baked in, so the corpus is generated by exactly the
    # production code path with production configuration — a simulator that
    # took a shortcut here would produce a corpus the real engine could never
    # have produced.
    control = max(0.0, min(0.9, args.control_share))
    os.environ["TREATMENT_GREEDINESS"] = str(args.greediness)
    os.environ["TREATMENT_AB_SPLIT"] = (
        f"control:{round((1 - control) * 100)},null_treatment:{round(control * 100)}"
    )

    with db.engine.begin() as conn:
        product_id = _product(conn, tenant)
        if not product_id:
            logger.error("tenant %s has no product to attach accounts to", tenant)
            raise SystemExit(1)
        made = build_book(
            conn, tenant=tenant, product_id=product_id, count=args.accounts, rng=rng
        )
    logger.info("book: %s accounts under tenant %s", made, tenant)

    start = datetime.now(timezone.utc) - timedelta(days=args.days)
    total = cures = 0
    for offset in range(args.days):
        day = start + timedelta(days=offset)
        with db.engine.begin() as conn:
            made, cured = sweep_day(conn, day=day, rng=rng, limit=args.accounts)
        total += made
        cures += cured
        if offset % 10 == 0 or offset == args.days - 1:
            logger.info("day %s/%s — %s decisions, %s cures", offset + 1, args.days, total, cures)

    logger.info("corpus: %s decisions, %s cures", total, cures)
    _report()


def _report() -> None:
    with db.engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT chosen_action, variant, count(*)::int AS n,
                       round(avg(propensity)::numeric, 4) AS mean_p,
                       count(*) FILTER (WHERE outcome = 'paid')::int AS paid
                FROM treatment_decisions
                WHERE mode = 'simulated'
                GROUP BY chosen_action, variant
                ORDER BY n DESC
                """
            )
        ).mappings().all()
    logger.info("%-20s %-16s %8s %8s %8s", "action", "arm", "n", "mean_pi", "paid")
    for row in rows:
        logger.info(
            "%-20s %-16s %8s %8s %8s",
            row["chosen_action"],
            row["variant"] or "-",
            row["n"],
            row["mean_p"],
            row["paid"],
        )


if __name__ == "__main__":
    main()
