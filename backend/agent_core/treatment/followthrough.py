"""The closed loop (P5): what happened, and what happens next.

P3 decides once per event. That makes it advisory — a verdict rather than a
ladder. This module is what turns one recommendation into "reminder → bot retry
→ human → field": it watches what each attempt produced, writes the answer back,
and asks the engine again when the case is still open.

Two halves.

**Attribution.** Every enacted decision eventually gets an ``outcome``. Payment
beats a promise beats a connection beats silence, and an attempt is only called
unanswered after a grace period sized to the channel — a follow-up sitting in an
agent's queue is not a no-answer an hour later. This is the training label the
whole shadow corpus is missing without it.

Shadow decisions get attributed too, and that is deliberate: a plan the engine
made and nobody carried out, on an account that then paid anyway, is the
counterfactual. It is the only evidence that would ever say the engine is
reallocating spend rather than earning it. Those can only ever be labelled
``paid`` / ``ptp`` / ``superseded`` — never ``no_answer``, because nobody asked.

**Re-decision.** A case is ``(customer, trigger kind, trigger ref)``. When the
last attempt on an open case concluded without resolving it, the engine is asked
again — and because the attempt is in ``contact_events``, the ladder has moved
up a rung on its own. The loop stops on resolution, on the attempt cap, or when
arbitration says the ladder is exhausted, which is a case for a person rather
than for a sixth dial.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from agent_core.clock import as_utc
from agent_core.treatment import actions as A, config, decisions, kill_switch
from agent_core.treatment.features import CONNECT_MIN_SECONDS, Trigger

logger = logging.getLogger(__name__)

#: Only these carry a case identity worth chasing. A ``manual`` decision is a
#: supervisor asking "what would you do here?" — a question, not a campaign, and
#: re-deciding it on a timer would be answering a question nobody asked twice.
#:
#: ``dpd_tick`` is here because ``sweep.py``'s docstring always said it was —
#: "followthrough treats a day's sweep as an ordinary case it can walk a ladder
#: over" — and the frozenset disagreed. The sweep is the corpus generator and
#: the only trigger that fires on the silent roller, the account that never
#: bounces again because the mandate was cancelled in March. Leaving it out gave
#: the largest population in the book exactly one decision a day and no
#: escalation at all.
#:
#: The case key is the borrower's own local date, so a day's sweep is one case
#: and the ladder walks *within* the day. Tomorrow's sweep opens a new case
#: rather than continuing yesterday's, which is the property that stops a
#: quiet account accumulating an unbounded ladder over a month.
LOOPED_TRIGGERS: frozenset[str] = frozenset(
    {"bounce", "broken_ptp", "pre_due", "dpd_tick"}
)

#: Outcomes that end a case. Anything else leaves it open for another rung.
RESOLVING = frozenset({"paid", "ptp", "superseded", "cancelled"})

#: How long a withheld decision is watched before its silence counts as
#: evidence. Long enough that a borrower who was going to pay this cycle has
#: had the chance — this is the window the counterfactual is defined over, and
#: making it shorter does not produce more data, it produces the same data with
#: more of the positives mislabelled as negatives.
OBSERVATION_WINDOW = timedelta(days=14)

#: Outcomes that mean "that attempt did not work" — the loop's cue.
UNRESOLVED = frozenset(
    {"no_answer", "refused", "undeliverable", "reached", "unresolved"}
)

#: How many decisions to attribute in one pass. Bounded so a backlog cannot
#: monopolise the worker.
BATCH = 25


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def attribute_outcomes(conn: Any, *, now: datetime | None = None, limit: int = BATCH) -> int:
    """Label decisions whose result is now knowable. Returns how many."""
    if not kill_switch.labels_allowed():
        return 0
    instant = now or datetime.now(timezone.utc)
    rows = conn.execute(
        text(
            """
            SELECT id, customer_id, account_id, trigger_kind, trigger_ref,
                   chosen_action, chosen_channel, enacted, enacted_at, created_at,
                   variant, mode, enacted_ref
            FROM treatment_decisions
            WHERE outcome IS NULL
              -- The synthetic corpus writes its own outcomes, sampled from a
              -- latent truth it controls. Attributing them here too would
              -- overwrite the label with one derived from a real borrower's
              -- payments, which is exactly the leakage the simulator exists to
              -- avoid.
              AND mode <> 'simulated'
              AND chosen_action IS NOT NULL
              -- ``wait`` used to be excluded, because a decision to do nothing
              -- produced nothing to attribute. It is included now: a
              -- control-arm wait is the counterfactual observation, and it is
              -- the row the whole uplift estimate is measured against.
              -- _outcome_for still refuses to label an ordinary shadow wait.
              AND created_at >= now() - interval '30 days'
            -- Least-recently-examined first, never-examined before that.
            --
            -- Ordering by created_at alone deadlocked the loop. A row that
            -- *cannot* be labelled -- an unenacted shadow decision outside a
            -- withholding arm, where nothing was sent so there is nothing to
            -- call unanswered and silence is not evidence either -- stayed at
            -- the front of every pass and was re-examined forever. One batch of
            -- those and the loop stops labelling anything, while the worker
            -- keeps reporting that it ran and the corpus quietly stops
            -- acquiring outcomes.
            ORDER BY outcome_checked_at ASC NULLS FIRST, created_at ASC
            LIMIT :limit
            """
        ),
        {"limit": max(1, limit)},
    ).mappings().all()

    labelled = 0
    inconclusive: list[str] = []
    for row in rows:
        outcome = _outcome_for(conn, dict(row), now=instant)
        if outcome is None:
            inconclusive.append(str(row["id"]))
            continue
        reach, cure = _reach_and_cure(conn, dict(row), outcome, now=instant)
        decisions.record_outcome(
            row["id"],
            outcome,
            conn=conn,
            reach_outcome=reach,
            cure_outcome=cure,
            observed_days=(instant - since).days if (since := as_utc(row.get("created_at"))) else None,
            event_at=instant,
            label_mature_at=instant + timedelta(days=90) if cure is None else instant,
            label_definition_version="w3-v1",
        )
        labelled += 1

    if inconclusive:
        # Stamped so the next pass moves past them. Only the inconclusive ones:
        # a labelled row leaves the queue on its outcome and has no reason to
        # carry a watermark.
        conn.execute(
            text(
                "UPDATE treatment_decisions SET outcome_checked_at = :now"
                " WHERE id = ANY(:ids)"
            ),
            {"now": instant, "ids": inconclusive},
        )
    return labelled


def _outcome_for(conn: Any, row: dict[str, Any], *, now: datetime) -> str | None:
    """The strongest evidence available, or None if it is too early to say.

    Ordered by what it would be dishonest to overwrite: a borrower who paid
    after an unanswered dial has paid, and recording that as ``no_answer``
    because the phone rang out would teach the model the opposite of what
    happened.
    """
    enacted = bool(row.get("enacted"))
    since = as_utc(row.get("enacted_at")) or as_utc(row.get("created_at"))
    if since is None:
        return None

    if _superseded(conn, row):
        return "superseded"
    if _paid_since(conn, row, since):
        return "paid"
    if _promised_since(conn, row, since):
        return "ptp"

    if not enacted:
        # Nothing was sent, so there is nothing to call *unanswered* — a shadow
        # decision on a case that simply stayed open is an absence of evidence,
        # and labelling it ``no_answer`` would manufacture a training signal out
        # of a decision nobody acted on.
        #
        # But withholding on purpose is not the same as failing to act, and
        # after the observation window the silence is itself the observation:
        # we did nothing and the borrower did not pay. That row is the
        # counterfactual, and it is the only kind of row that can measure
        # self-cure — without it a control arm contains nothing but positives,
        # every cure rate it reports is 1.0, and the estimated treatment effect
        # is a finding about the labeller.
        if _withheld_on_purpose(row) and now - since >= OBSERVATION_WINDOW:
            return "unresolved"
        return None

    if _reached_since(conn, row, since):
        return "reached"
    if _send_failed(conn, row):
        return "undeliverable"

    grace = timedelta(hours=config.grace_hours(str(row.get("chosen_action") or "")))
    if now - since >= grace:
        return "no_answer"
    return None


def _withheld_on_purpose(row: dict[str, Any]) -> bool:
    """Was this a deliberate no-treatment, or merely a plan nobody carried out?

    The distinction decides whether silence is evidence. A control-arm decision
    withheld treatment by design, so "they did not pay" answers the question the
    arm was created to ask. A shadow decision that went unenacted answers
    nothing: the borrower may have been contacted by the dialler, by an agent,
    or by a reminder the engine never saw.
    """
    from agent_core.treatment import config

    arm = config.variants().get(str(row.get("variant") or "").strip().lower())
    return bool(arm and arm.suppress_discretionary)


def _reach_and_cure(
    conn: Any, row: dict[str, Any], outcome: str, *, now: datetime
) -> tuple[str | None, str | None]:
    """Split attempt reach from borrower cure.

    Reach closes at one evaluation instant. Cure stays open for the 90-day
    window; a PTP never closes it.
    """
    reach = None
    if outcome in {"reached", "no_answer", "undeliverable", "refused"}:
        reach = outcome
    elif outcome == "ptp":
        reach = "reached"
    elif outcome == "paid" and bool(row.get("enacted")):
        reach = "reached"
    cure = None
    if outcome == "paid":
        cure = "paid"
    elif outcome == "unresolved":
        cure = "unresolved"
    elif outcome == "ptp":
        cure = None
    return reach, cure


def _superseded(conn: Any, row: dict[str, Any]) -> bool:
    """A newer decision exists for the same case.

    Only ever true for un-enacted plans: an attempt that actually reached the
    borrower happened, and calling it superseded would erase it from the ladder.
    """
    if row.get("enacted") or not row.get("trigger_ref"):
        return False
    found = conn.execute(
        text(
            """
            SELECT 1 FROM treatment_decisions
            WHERE customer_id = :cid
              AND trigger_kind = :kind
              AND trigger_ref = :ref
              AND id <> :id
              -- (created_at, id) rather than created_at alone: two decisions
              -- written in one transaction share a timestamp, because Postgres
              -- now() is transaction start. Without the tiebreak neither would
              -- ever supersede the other.
              AND (created_at, id)
                  > (SELECT created_at, id FROM treatment_decisions WHERE id = :id)
            LIMIT 1
            """
        ),
        {
            "cid": row["customer_id"],
            "kind": row["trigger_kind"],
            "ref": row["trigger_ref"],
            "id": row["id"],
        },
    ).fetchone()
    return found is not None


def _paid_since(conn: Any, row: dict[str, Any], since: datetime) -> bool:
    if not row.get("account_id"):
        return False
    reversal = ""
    try:
        from agent_core.treatment import schema_ready

        if schema_ready.has_column(conn, "ledger_entries", "reverses_id"):
            reversal = """
              AND NOT EXISTS (
                SELECT 1 FROM ledger_entries r
                WHERE r.reverses_id = ledger_entries.id
              )
            """
    except Exception:
        reversal = ""
    found = conn.execute(
        text(
            f"""
            SELECT 1 FROM ledger_entries
            WHERE account_id = :aid AND type = 'payment' AND posted_at > :since
              {reversal}
            LIMIT 1
            """
        ),
        {"aid": row["account_id"], "since": since},
    ).fetchone()
    if found is not None:
        return True
    found = conn.execute(
        text(
            """
            SELECT 1 FROM payment_intents
            WHERE customer_id = :cid AND status = 'paid' AND paid_at > :since
            LIMIT 1
            """
        ),
        {"cid": row["customer_id"], "since": since},
    ).fetchone()
    return found is not None


def _promised_since(conn: Any, row: dict[str, Any], since: datetime) -> bool:
    found = conn.execute(
        text(
            """
            SELECT 1 FROM promises
            WHERE customer_id = :cid AND created_at > :since
              AND status IN ('upcoming','due_today','kept','partial')
            LIMIT 1
            """
        ),
        {"cid": row["customer_id"], "since": since},
    ).fetchone()
    return found is not None


def _reached_since(conn: Any, row: dict[str, Any], since: datetime) -> bool:
    """Did a person actually engage?

    A voice interaction long enough to be a conversation, or an inbound message.
    The duration floor is the same one the reachability features use — a
    ring-out counted as a connect would tell the engine the borrower answers at
    exactly the hours they do not.
    """
    found = conn.execute(
        text(
            """
            SELECT 1 FROM interactions
            WHERE customer_id = :cid
              AND channel = 'voice'
              AND started_at > :since
              AND COALESCE(duration_sec, 0) >= :floor
            LIMIT 1
            """
        ),
        {"cid": row["customer_id"], "since": since, "floor": CONNECT_MIN_SECONDS},
    ).fetchone()
    if found is not None:
        return True
    found = conn.execute(
        text(
            """
            SELECT 1 FROM messages m
            JOIN conversations cv ON cv.id = m.conversation_id
            WHERE cv.customer_id = :cid AND m.sender = 'customer' AND m.created_at > :since
            LIMIT 1
            """
        ),
        {"cid": row["customer_id"], "since": since},
    ).fetchone()
    if found is not None:
        return True
    try:
        found = conn.execute(
            text(
                """
                SELECT 1 FROM contact_delivery_events
                WHERE customer_id = :cid
                  AND channel = COALESCE(:ch, channel)
                  AND state IN ('delivered','read')
                  AND occurred_at > :since
                LIMIT 1
                """
            ),
            {
                "cid": row["customer_id"],
                "ch": row.get("chosen_channel"),
                "since": since,
            },
        ).fetchone()
    except Exception:
        return False
    return found is not None


def _send_failed(conn: Any, row: dict[str, Any]) -> bool:
    """The provider refused it. Distinct from the borrower ignoring it.

    Worth keeping apart: an undeliverable number is a data-quality problem for
    the ops team, whereas a no-answer is a treatment problem for the engine, and
    escalating up the ladder is the right response to only one of them.
    """
    if row.get("chosen_action") != A.WHATSAPP:
        return False
    found = conn.execute(
        text(
            """
            SELECT 1 FROM whatsapp_outbound_jobs
            WHERE customer_id = :cid
              AND source = 'treatment'
              AND status = 'failed'
              AND created_at >= COALESCE(:since, now() - interval '1 day')
            LIMIT 1
            """
        ),
        {"cid": row["customer_id"], "since": as_utc(row.get("enacted_at"))},
    ).fetchone()
    return found is not None


# ---------------------------------------------------------------------------
# Re-decision
# ---------------------------------------------------------------------------


def open_cases(conn: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    """Cases whose last attempt did not resolve them and that are still open.

    ``DISTINCT ON`` so one row per case: a case with four attempts must produce
    one candidate for re-decision, not four.
    """
    rows = conn.execute(
        text(
            """
            SELECT * FROM (
              SELECT DISTINCT ON (customer_id, trigger_kind, trigger_ref)
                     id, customer_id, account_id, trigger_kind, trigger_ref,
                     chosen_action, outcome, enacted_at, created_at
              FROM treatment_decisions
              WHERE trigger_ref IS NOT NULL
                AND mode <> 'simulated'
                AND trigger_kind = ANY(:kinds)
                AND created_at >= now() - interval '30 days'
              ORDER BY customer_id, trigger_kind, trigger_ref, created_at DESC, id DESC
            ) latest
            WHERE latest.outcome = ANY(:unresolved)
            ORDER BY latest.enacted_at ASC NULLS LAST
            LIMIT :limit
            """
        ),
        {
            "kinds": sorted(LOOPED_TRIGGERS),
            "unresolved": sorted(UNRESOLVED),
            "limit": max(1, limit),
        },
    ).mappings().all()
    return [dict(r) for r in rows if _case_still_open(conn, dict(r))]


def _case_still_open(conn: Any, case: dict[str, Any]) -> bool:
    """Is there still a reason to contact them about this?"""
    ref, kind = case.get("trigger_ref"), case.get("trigger_kind")
    if not ref:
        return False
    if kind == "bounce":
        status = conn.execute(
            text("SELECT status FROM payment_events WHERE id = :id"), {"id": ref}
        ).scalar()
        return status in {"open", "in_progress"}
    if kind == "broken_ptp":
        status = conn.execute(
            text("SELECT status FROM promises WHERE id = :id"), {"id": ref}
        ).scalar()
        return status == "broken"
    if kind == "pre_due":
        status = conn.execute(
            text("SELECT status FROM emi_installments WHERE id = :id"), {"id": ref}
        ).scalar()
        return status in {"upcoming", "partial", "overdue"}
    if kind == "dpd_tick":
        dpd = conn.execute(
            text("SELECT dpd FROM accounts WHERE id = :id"),
            {"id": case.get("account_id")},
        ).scalar()
        return dpd is not None and int(dpd) > 0
    return False


def advance(conn: Any, case: dict[str, Any], *, now: datetime | None = None) -> str | None:
    """Ask the engine again for one case. Returns the decision id, or None.

    The ladder moves on its own: the previous attempt is in ``contact_events``,
    which is what ``policy.last_rung_used`` reads, so the engine sees a borrower
    who has already been messaged and considers the next rung without anything
    here telling it to.
    """
    from agent_core.treatment.engine import recommend_treatment

    savepoint = conn.begin_nested()
    try:
        result = recommend_treatment(
            customer_id=case["customer_id"],
            account_id=case.get("account_id"),
            trigger=Trigger(
                kind=str(case["trigger_kind"]),
                at=as_utc(case.get("created_at")),
                ref=str(case["trigger_ref"]),
            ),
            now=now,
            conn=conn,
        )
    except Exception:
        # recommend_treatment promises not to raise; this catches the INSERT it
        # wraps failing on a constraint. One case's bad row must not poison
        # the worker transaction — the same savepoint sweep.py uses so one
        # borrower cannot take the rest of the batch down with them.
        savepoint.rollback()
        logger.exception(
            "queue=treatment_followthrough case=%s/%s failed",
            case.get("trigger_kind"),
            case.get("trigger_ref"),
        )
        raise
    savepoint.commit()
    logger.info(
        "treatment follow-through case=%s/%s -> %s (%s)",
        case["trigger_kind"],
        case["trigger_ref"],
        result.action,
        result.reason or "actionable",
    )
    return result.decision_id


def resolve_case(
    conn: Any, *, trigger_kind: str, trigger_ref: str, outcome: str = "superseded"
) -> int:
    """Close out a case's outstanding plans when the reason for it goes away.

    Called when a bounce cures or a promise is kept. Without it the executor
    would still be holding a scheduled dial about a debt that has been paid,
    which is the single worst thing a collections system can do.
    """
    if outcome not in decisions.OUTCOMES:
        return 0
    result = conn.execute(
        text(
            """
            UPDATE treatment_decisions
            SET outcome = :outcome, outcome_at = now()
            WHERE trigger_kind = :kind
              AND trigger_ref = :ref
              AND outcome IS NULL
              AND enacted IS FALSE
            """
        ),
        {"kind": trigger_kind, "ref": trigger_ref, "outcome": outcome},
    )
    return result.rowcount or 0


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------


def process_one(engine: Engine) -> bool:
    """One unit of follow-through work. Returns True if anything happened.

    Attribution runs in **every** mode, including shadow: labelling what
    happened is not an intervention, and the counterfactuals are most of what
    the shadow fortnight is for. Re-decision runs in every mode too — in shadow
    it produces the plan and enacts nothing, which is precisely the ladder a
    collections head needs to see before switching the executor on.
    """
    if config.mode() == config.MODE_OFF:
        return False
    with engine.begin() as conn:
        if attribute_outcomes(conn):
            return True
        cases = open_cases(conn, limit=1)
        if not cases:
            return False
        # advance rolls its own savepoint so a constraint failure does not
        # abort this transaction. Returning False (not True, not a raise) is
        # what lets every queue below us in bot_worker still drain this tick;
        # reporting work for a failed re-decision would spin on the poison
        # case and starve the sweep, webhooks and clerk.
        try:
            advance(conn, cases[0])
        except Exception:
            return False
        return True
