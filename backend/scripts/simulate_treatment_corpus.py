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

**Reachability that varies by borrower.** Added after the first reach model
fitted on this corpus scored an AUC of 0.497 — a coin flip, and correctly so:
reach had been a per-channel constant, so there was nothing about a borrower
for a model to learn. A simulator whose latent truth has no heterogeneity
cannot demonstrate that an estimator beats a prior, because the prior is
already optimal. Each borrower now carries a private reachability drawn once,
and it correlates with the segment: an avoidant borrower is genuinely harder to
get hold of, which is most of why they are avoidant.
"""

from __future__ import annotations

import argparse
import hashlib
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
#: ``reach`` is the segment's mean probability that an attempt gets through;
#: each borrower draws their own around it. Avoidant borrowers are hard to
#: reach because avoiding is what they are doing, which makes reach and uplift
#: correlated in a way a naive engine will misread as "contact works here".
SEGMENTS: dict[str, dict[str, float]] = {
    # Salary landed late, mandate presented on the wrong day. Cures itself.
    "forgetful": {"self_cure": 0.72, "uplift": 0.04, "share": 0.35, "reach": 0.62},
    # Genuinely short this month, will pay if reminded and given a route.
    "squeezed": {"self_cure": 0.18, "uplift": 0.34, "share": 0.30, "reach": 0.55},
    # Avoiding it. Moves only for a person, and not always then.
    "avoidant": {"self_cure": 0.06, "uplift": 0.22, "share": 0.20, "reach": 0.22},
    # In real difficulty. Contact does very little and costs goodwill.
    "distressed": {"self_cure": 0.04, "uplift": 0.05, "share": 0.15, "reach": 0.38},
}

#: Per-channel multiplier on a borrower's own reachability. A borrower who
#: dodges calls still reads WhatsApp, which is the single most useful thing a
#: reach model can discover and the reason it is worth fitting one per channel
#: rather than one per borrower.
CHANNEL_REACH: dict[str, float] = {
    "sms": 0.60,
    "whatsapp": 1.15,
    "voice": 0.75,
    "field": 1.00,
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
        # A plan is over-engineering for someone who simply forgot; the debit
        # going through again solves it and they never had to do anything.
        A.SELF_SERVICE_PLAN: 0.20,
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
        # The strongest instrument for this segment after the mandate itself:
        # genuinely short this month, willing, and what they need is a route
        # rather than a reminder.
        A.SELF_SERVICE_PLAN: 0.85,
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
        # Anything requiring the borrower to act does nothing here. Not acting
        # is what they are doing.
        A.SELF_SERVICE_PLAN: 0.15,
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
        # Helps, but a catch-up plan is not the instrument someone in real
        # difficulty needs -- that is a restructure, and it is not the engine's
        # to grant.
        A.SELF_SERVICE_PLAN: 0.45,
        A.SMS: 0.10,
        A.WHATSAPP: 0.25,
        A.VOICE_BOT: 0.20,
        A.HUMAN_CALL: 0.55,
        A.FIELD_VISIT: 0.30,
        A.LEGAL_NOTICE: 0.20,
    },
}

#: Return-code mix on a bounce, **per segment**, because the return code is the
#: observable trace the borrower's type leaves behind.
#:
#: This was one mix for everybody, and that made the corpus unfittable: the
#: segment determined self-cure and uplift while leaving no signal in any
#: feature, so a model asked to tell two borrowers apart had nothing to do it
#: with and every fit came back at AUC 0.50. Which was the right answer — there
#: was genuinely nothing there.
#:
#: The correlation is also just true. A forgetful borrower bounces because the
#: money arrived late; someone in real difficulty has a closed account or a
#: mandate they cancelled to stop the debits.
RETURN_MIX: dict[str, list[tuple[str, float]]] = {
    "forgetful": [
        ("insufficient_funds", 0.82),
        ("technical", 0.14),
        ("mandate_expired", 0.02),
        ("account_closed", 0.01),
        ("unknown", 0.01),
    ],
    "squeezed": [
        ("insufficient_funds", 0.86),
        ("technical", 0.06),
        ("mandate_expired", 0.05),
        ("account_closed", 0.02),
        ("unknown", 0.01),
    ],
    "avoidant": [
        ("insufficient_funds", 0.40),
        ("technical", 0.05),
        ("mandate_expired", 0.38),
        ("account_closed", 0.14),
        ("unknown", 0.03),
    ],
    "distressed": [
        ("insufficient_funds", 0.46),
        ("technical", 0.04),
        ("mandate_expired", 0.18),
        ("account_closed", 0.29),
        ("unknown", 0.03),
    ],
}

#: Promise-keeping by segment. The other observable a type leaves behind, and
#: the one a collections floor already trusts: ``ptp_keep_rate`` has been in the
#: feature vector since the engine shipped.
PTP_KEEP: dict[str, float] = {
    "forgetful": 0.82,
    "squeezed": 0.55,
    "avoidant": 0.18,
    "distressed": 0.24,
}


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


def latent_reach(customer_id: str, segment: str) -> float:
    """This borrower's true reachability, stable across simulated days.

    Hashed from the id rather than drawn, because a borrower who is hard to
    reach on Tuesday is hard to reach on Wednesday. Redrawing each day would
    make reach pure noise and no estimator could ever beat the channel prior —
    which is exactly the state that produced an AUC of 0.497 the first time
    this corpus was fitted.
    """
    digest = hashlib.blake2b(
        customer_id.encode("utf-8"), digest_size=8, person=b"simreach"
    ).digest()
    unit = int.from_bytes(digest, "big") / float(1 << 64)
    # Box-Muller-ish: two hashed uniforms would be better, but a triangular
    # draw around the segment mean is enough spread for a linear model to find
    # and keeps this to one hash.
    spread = (unit + (unit * 7919 % 1.0)) / 2.0 - 0.5
    return _clamp01(SEGMENTS[segment]["reach"] + spread * 0.55)


def build_book(
    conn: Any,
    *,
    tenant: str,
    product_id: str,
    count: int,
    rng: random.Random,
    bot_id: str | None = None,
) -> int:
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

        # This borrower's own reachability. Derived from their id rather than
        # drawn from the shared generator, so ``_settle`` can recover exactly
        # the same value on a later day without a column to store it in —
        # reachability is a property of the person, not of the decision.
        reachability = latent_reach(customer_id, segment)
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
                # A *noisy proxy* for reachability, not a copy of it. Bureau
                # score and contactability really do correlate — a borrower
                # whose file is thin is usually a borrower whose number is
                # stale — and the noise is what stops the reach model
                # recovering the latent variable exactly and reporting an AUC
                # no real deployment will ever see.
                "score": max(
                    300, min(850, int(300 + 500 * reachability + rng.gauss(0, 55)))
                ),
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

        reason = _pick(rng, RETURN_MIX[segment])
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
        if bot_id:
            _seed_promises(
                conn,
                index=index,
                customer_id=customer_id,
                account_id=account_id,
                bot_id=bot_id,
                keep_rate=PTP_KEEP[segment],
                amount=instalment,
                now=today,
                rng=rng,
            )
        made += 1
    return made


def _seed_promises(
    conn: Any,
    *,
    index: int,
    customer_id: str,
    account_id: str,
    bot_id: str,
    keep_rate: float,
    amount: float,
    now: datetime,
    rng: random.Random,
) -> None:
    """A short promise history, so ``ptp_keep_rate`` is a real feature.

    Four promises each, kept or broken by the segment's rate. Four rather than
    one because ``MIN_ATTEMPTS_FOR_RATE`` gates the feature at three: below the
    floor the engine reports the rate as unknown, which is correct behaviour
    and would have left the column empty for every simulated borrower.
    """
    for n in range(4):
        kept = rng.random() < keep_rate
        conn.execute(
            text(
                """
                INSERT INTO promises (
                  id, customer_id, account_id, owner_kind, owner_bot_id,
                  amount, promised_at, status, reminder_status, paid_amount, channel
                ) VALUES (
                  :id, :cid, :aid, 'bot', :bot,
                  :amount, :at, :status, 'off', :paid, 'whatsapp'
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": f"{TAG}PR{index:06d}-{n}",
                "cid": customer_id,
                "aid": account_id,
                "bot": bot_id,
                "amount": amount,
                "at": now - timedelta(days=30 * (n + 1)),
                "status": "kept" if kept else "broken",
                "paid": amount if kept else 0,
            },
        )


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
    failed = 0
    ref = day.date().isoformat()
    for account in accounts:
        # A savepoint per account, exactly as sweep.py does and for the same
        # reason. Without one, a single account whose decision raises poisons
        # the enclosing transaction and every account after it fails with
        # "current transaction is aborted" -- so one transient lock timeout
        # costs the rest of the run.
        #
        # Learned the expensive way: a concurrent test run held FOR UPDATE on
        # an accounts row, the decision log's foreign-key check waited past the
        # statement timeout, and a corpus generation that was ten thousand
        # accounts from finishing produced ten thousand identical tracebacks
        # instead.
        savepoint = conn.begin_nested()
        try:
            result = recommend_treatment(
                customer_id=account["customer_id"],
                account_id=account["id"],
                trigger=Trigger(kind="dpd_tick", at=day, ref=ref),
                now=day,
                conn=conn,
                force_mode=config.MODE_SIMULATED,
            )
            if result.decision_id is None:
                savepoint.rollback()
                continue
            settled = _settle(
                conn,
                result,
                segment=str(account["segment"]),
                customer_id=str(account["customer_id"]),
                account_id=str(account["id"]),
                rng=rng,
                day=day,
            )
            savepoint.commit()
        except Exception:
            savepoint.rollback()
            failed += 1
            if failed <= 3:
                logger.exception("simulating %s failed; skipping it", account["id"])
            continue
        made += 1
        if settled:
            cured += 1
    if failed:
        logger.warning(
            "%s of %s accounts could not be simulated on %s and were skipped",
            failed, len(accounts), day.date(),
        )
    return made, cured


def _settle(
    conn: Any,
    result: Any,
    *,
    segment: str,
    customer_id: str,
    account_id: str,
    rng: random.Random,
    day: datetime,
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

    reachability = latent_reach(customer_id, segment)

    self_cured = rng.random() < profile["self_cure"] * _window_factor(action)
    incremental = 0.0
    if action != A.WAIT and not result.suppressed:
        efficacy = ACTION_EFFICACY.get(segment, {}).get(action, 0.2)
        # An intervention only has its effect if it lands. Multiplying the
        # uplift by reach here rather than treating them as independent is what
        # makes the two estimable separately: reach is observable from the
        # outcome label, uplift only from the arm comparison.
        incremental = profile["uplift"] * efficacy * _reach_probability(
            action, reachability
        )
    treated_cure = self_cured or (rng.random() < incremental)

    if action == A.WAIT or result.suppressed:
        # Nothing was done. The cure is a self-cure and the non-cure is just as
        # informative — together they are the control observation, and they are
        # the only rows in the corpus that can say what would have happened
        # anyway.
        #
        # Recording only the cures is what produced a control arm with a 100%
        # cure rate and an estimated treatment effect of −0.455. The negative is
        # the half that makes it a measurement.
        outcome = "paid" if self_cured else "unresolved"
        decisions.record_outcome(result.decision_id, outcome, conn=conn)
        if self_cured:
            _record_payment(conn, customer_id=customer_id, account_id=account_id,
                            decision_id=result.decision_id, day=day)
        return self_cured

    decisions.mark_enacted(
        result.decision_id, ref=f"{TAG}SIM", conn=conn, enacted_by="treatment_executor"
    )
    if treated_cure:
        outcome = "paid"
    elif rng.random() < _reach_probability(action, reachability):
        outcome = rng.choice(["reached", "ptp", "refused"])
    else:
        outcome = "no_answer"
    decisions.record_outcome(result.decision_id, outcome, conn=conn)
    if outcome == "paid":
        _record_payment(conn, customer_id=customer_id, account_id=account_id,
                        decision_id=result.decision_id, day=day)
    return outcome in {"paid", "ptp"}


def _record_payment(
    conn: Any, *, customer_id: str, account_id: str, decision_id: str, day: datetime
) -> None:
    """The money behind a cure: a ledger entry and a settled instalment.

    Added after the S17 scoreboard reported an incremental recovery of zero
    rupees on a corpus where a fifth of the book had cured. The decisions were
    labelled ``paid`` and no money existed anywhere, so every rupee-denominated
    metric divided by nothing -- including the headline one, incremental
    recovery per rupee.

    **Not ``payment_events``.** The name misleads: that table's ``kind`` is
    CHECK-constrained to ``'bounce'``, so it is a returns ledger and cannot hold
    a payment at all. The first version of this function wrote there, every
    insert raised a check violation, and the per-account savepoint rolled back
    the decision along with it -- which is how a run finished reporting a
    control arm with a cure rate of exactly 0.000. Every self-cure had been
    deleted, and the remaining rows were all the ones where nothing happened.

    A zero and a one are equally impossible as a measured cure rate, and both
    mean the same thing: the corpus is not recording what it thinks it is.
    """
    row = conn.execute(
        text(
            """
            SELECT (SELECT e.id FROM emi_installments e
                     WHERE e.account_id = a.id AND e.status <> 'paid'
                     ORDER BY e.due_date ASC LIMIT 1) AS emi_id,
                   (SELECT e.amount FROM emi_installments e
                     WHERE e.account_id = a.id AND e.status <> 'paid'
                     ORDER BY e.due_date ASC LIMIT 1) AS emi_amount,
                   a.outstanding
            FROM accounts a WHERE a.id = :aid
            """
        ),
        {"aid": account_id},
    ).mappings().first()
    if not row:
        return
    amount = float(row["emi_amount"] or 0.0) or float(row["outstanding"] or 0.0)
    if amount <= 0:
        return

    conn.execute(
        text(
            """
            INSERT INTO ledger_entries (
              id, account_id, type, description, amount, posted_at
            ) VALUES (
              :id, :aid, 'payment', :note, :amount, :occurred
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": f"{TAG}LE{decision_id[-10:]}",
            "aid": account_id,
            "note": f"simulated cure attributed to {decision_id}",
            "amount": round(amount, 2),
            # Wall clock, not the simulated day.
            #
            # ``treatment_decisions.created_at`` is ``clock_timestamp()`` by
            # design -- it is an append-only log and records when the row was
            # written, not when the simulation pretends it happened. Posting the
            # payment at the simulated date puts it *before* the decision that
            # caused it, and every attribution join of the form "a payment after
            # the decision" then matches nothing. S17's incremental recovery
            # read zero rupees on a corpus holding three hundred million of
            # them, while the un-joined total read correctly -- which is what
            # made the mismatch visible at all.
            "occurred": datetime.now(timezone.utc),
        },
    )
    if row["emi_id"]:
        # The instalment settles too. A ledger payment with the EMI still
        # overdue is a book that disagrees with itself, and the next day's
        # sweep would decide the same arrears again.
        conn.execute(
            text(
                """
                UPDATE emi_installments
                SET status = 'paid', paid_amount = :amount, paid_on = :occurred
                WHERE id = :eid
                """
            ),
            {"eid": row["emi_id"], "amount": round(amount, 2), "occurred": day.date()},
        )


def _window_factor(action: str) -> float:
    """Self-cure is a property of the borrower, not of what we did.

    Returned as a constant on purpose. It is here as a named seam rather than
    an inline 1.0 so that anyone tempted to make self-cure depend on the action
    has to delete a docstring saying why they must not: the moment it does, the
    control observation stops being a counterfactual and the corpus can no
    longer measure uplift at all.
    """
    return 1.0


def _reach_probability(action: str, reachability: float) -> float:
    """Whether this attempt gets through, for this borrower on this channel.

    A product rather than a lookup, and that is the whole change: a constant
    per channel means the best possible reach model is the channel prior, and
    an estimator that cannot beat a constant proves nothing when it does not.
    """
    spec = A.spec(action)
    if spec.channel is None:
        return 1.0
    return _clamp01(reachability * CHANNEL_REACH.get(spec.channel, 1.0))


def _clamp01(value: float) -> float:
    return max(0.02, min(0.97, value))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def purge(conn: Any) -> dict[str, int]:
    """Remove every simulated row. Safe to run against a real database.

    Deletes by tag and by mode, never by date or by "everything recent" — a
    cleanup that could reach a real borrower is a worse bug than the mess it
    tidies.
    """
    # The cascade from customers reaches accounts, EMIs, mandates,
    # presentations, payment events, promises and promise reminders. On a book
    # of a few hundred that is one quick statement; on eighteen thousand it is
    # minutes of cascading deletes, and the application's statement timeout kills
    # it partway through every time.
    #
    # So the timeout is lifted for this transaction only. Not raised globally
    # and not removed from the engine: an unbounded statement timeout is a
    # reasonable thing for a maintenance script that deletes its own rows and a
    # very unreasonable one for a service on the audio path of a live call.
    conn.execute(text("SET LOCAL statement_timeout = 0"))

    counts: dict[str, int] = {}
    counts["decisions"] = conn.execute(
        text(
            # Both predicates. Tagged customers with a non-simulated decision
            # would otherwise survive the first delete and then block the second
            # one on a foreign key.
            "DELETE FROM treatment_decisions"
            " WHERE mode = 'simulated' OR customer_id LIKE :tag"
        ),
        {"tag": f"{TAG}%"},
    ).rowcount
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
        bot_id = conn.execute(
            text("SELECT id FROM bots WHERE tenant_id = :t ORDER BY id LIMIT 1"),
            {"t": tenant},
        ).scalar()
        if not bot_id:
            # promises.CHECK requires an owner, and inventing a bot row to
            # satisfy it would put a fake agent in the fleet screen. Without one
            # the promise history is skipped and ptp_keep_rate stays unknown,
            # which is the correct "absent, not zero" outcome.
            logger.warning(
                "tenant %s has no bot — skipping promise history, so ptp_keep_rate "
                "will be unknown for every simulated borrower",
                tenant,
            )
        made = build_book(
            conn,
            tenant=tenant,
            product_id=product_id,
            count=args.accounts,
            rng=rng,
            bot_id=str(bot_id) if bot_id else None,
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
