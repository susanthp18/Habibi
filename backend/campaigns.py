"""Campaign runs — a batch of missions with a window, a pace and a stop button.

The treatment engine already answers *who* to call: it decides per account and
``enact`` dials one authorised plan per worker iteration. What had no
representation anywhere was the **batch** — "work the 30-60 bucket this
morning" — so there was nowhere to put a pace, a calling window narrower than
the statutory one, a progress figure, or a way to stop.

What a run is not
-----------------
It is **not** a second targeting system. A run groups missions that were already
authorised and meters them out; it never decides that a borrower who should not
be called should be. Every target still goes through ``contact_policy.admit`` at
dial time, and a run's window can only ever be narrower than the statutory one —
``_within_window`` intersects, it does not override.

That distinction is the whole reason this module is small. A campaign tool that
could pick its own cohort by SQL would be a way to route around the engine, the
consent ledger and the contact cap all at once, and it would be used that way
within a week of shipping.

Pacing
------
Two ceilings, both real:

* ``max_concurrent`` per run — so one campaign cannot consume the fleet.
* ``outbound.max_in_flight()`` across everything — the shared gate, checked
  again inside ``outbound.place`` immediately before the carrier call.

A run that cannot get a slot does not queue a dial; it simply does not claim a
target this iteration. There is no over-dial and therefore no abandoned call,
which is the property the design chose over predictive dialling.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.engine import Engine

import flow_graph as fg
import outbound

logger = logging.getLogger(__name__)

STATUS_DRAFT = "draft"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_FINISHED = "finished"
STATUS_CANCELLED = "cancelled"

DEFAULT_TZ = "Asia/Kolkata"


def enabled() -> bool:
    from agent_core.platform_flags import campaign_runtime_enabled

    return campaign_runtime_enabled()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rid() -> str:
    return f"CR-{uuid.uuid4().hex[:10].upper()}"


def _tid() -> str:
    return f"CT-{uuid.uuid4().hex[:12].upper()}"


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo((name or "").strip() or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def within_window(run: dict[str, Any], *, tz_name: str | None, now: datetime | None = None) -> bool:
    """Is this run allowed to dial right now, in the borrower's local time?

    Narrower than the statutory window by construction — the CHECK on the table
    keeps the hours inside 0..24 and ``contact_policy`` still runs afterwards,
    so a run configured 06:00–22:00 does not become permission to dial at 06:00.
    It just means the run has nothing further to add.
    """
    local = (now or _now()).astimezone(_zone(tz_name))
    return int(run["window_start_hour"]) <= local.hour < int(run["window_end_hour"])


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------


def create(
    conn: Any,
    *,
    tenant_id: str,
    name: str,
    objective: str,
    bot_id: str | None = None,
    cadence: str = "default",
    source: str = "list",
    selector: dict[str, Any] | None = None,
    window_start_hour: int = 10,
    window_end_hour: int = 18,
    max_concurrent: int = 5,
    created_by_user_id: str | None = None,
) -> dict[str, Any]:
    """Create a run in ``draft``. Nothing dials until it is started."""
    import json

    run_id = _rid()
    row = conn.execute(
        text(
            """
            INSERT INTO campaign_runs (
              id, tenant_id, bot_id, name, objective, cadence, source, selector,
              status, window_start_hour, window_end_hour, max_concurrent,
              created_by_user_id, created_at, updated_at
            ) VALUES (
              :id, :tenant, :bot, :name, :objective, :cadence, :source,
              CAST(:selector AS jsonb), 'draft', :ws, :we, :conc, :actor, now(), now()
            )
            RETURNING *
            """
        ),
        {
            "id": run_id,
            "tenant": tenant_id,
            "bot": bot_id,
            "name": name,
            "objective": objective,
            "cadence": cadence,
            "source": source,
            "selector": json.dumps(selector or {}),
            "ws": int(window_start_hour),
            "we": int(window_end_hour),
            "conc": int(max_concurrent),
            "actor": created_by_user_id,
        },
    ).mappings().first()
    return dict(row)


def add_targets(conn: Any, run_id: str, customer_ids: list[str]) -> int:
    """Add borrowers to a draft run. Duplicates are ignored, not called twice.

    ``ON CONFLICT DO NOTHING`` against the (run, customer) unique index: a
    borrower listed twice in an uploaded CSV is a data problem, and treating it
    as permission for a second call would be the worst possible reading of it.
    """
    added = 0
    for customer_id in customer_ids:
        result = conn.execute(
            text(
                """
                INSERT INTO campaign_targets (
                  id, run_id, customer_id, account_id, state, created_at, updated_at
                )
                SELECT :id, :run, c.id,
                       (SELECT a.id FROM accounts a WHERE a.customer_id = c.id
                        ORDER BY a.dpd DESC NULLS LAST LIMIT 1),
                       'pending', now(), now()
                FROM customers c WHERE c.id = :cid
                ON CONFLICT (run_id, customer_id) DO NOTHING
                """
            ),
            {"id": _tid(), "run": run_id, "cid": customer_id},
        )
        added += int(result.rowcount or 0)
    conn.execute(
        text(
            """
            UPDATE campaign_runs
            SET targets_total = (SELECT count(*) FROM campaign_targets WHERE run_id = :run),
                updated_at = now()
            WHERE id = :run
            """
        ),
        {"run": run_id},
    )
    return added


#: The only fields a selector may name. Anything else is refused rather than
#: ignored, because a cohort built from a selector the resolver silently dropped
#: is a campaign that dials the wrong people while looking correct on screen.
SELECTOR_FIELDS = frozenset(
    {
        "buckets",
        "dpdMin",
        "dpdMax",
        "minOutstandingInr",
        "maxOutstandingInr",
        "risk",
        "language",
        "excludeOpenPromise",
        "excludeOnHold",
        "excludeContactedWithinDays",
        "limit",
    }
)

#: A cohort is a list of phones that will ring. This bounds the damage a typo in
#: one field can do; a genuinely larger run is several runs, which is also how
#: it should be reviewed.
SELECTOR_MAX = 5000


class SelectorError(ValueError):
    """The selector cannot be resolved, and saying why beats resolving it wrongly."""


def _selector_clauses(selector: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    unknown = sorted(set(selector) - SELECTOR_FIELDS)
    if unknown:
        raise SelectorError(f"unknown_selector_fields:{','.join(unknown)}")

    clauses = ["c.tenant_id = :tenant", "a.status = 'active'"]
    params: dict[str, Any] = {}

    buckets = [str(b).strip() for b in (selector.get("buckets") or []) if str(b).strip()]
    if buckets:
        clauses.append("a.bucket = ANY(:buckets)")
        params["buckets"] = buckets

    for key, op, name in (
        ("dpdMin", ">=", "dpd_min"),
        ("dpdMax", "<=", "dpd_max"),
    ):
        if selector.get(key) is not None:
            clauses.append(f"a.dpd {op} :{name}")
            params[name] = int(selector[key])

    for key, op, name in (
        ("minOutstandingInr", ">=", "out_min"),
        ("maxOutstandingInr", "<=", "out_max"),
    ):
        if selector.get(key) is not None:
            clauses.append(f"a.outstanding {op} :{name}")
            params[name] = float(selector[key])

    risk = [str(r).strip() for r in (selector.get("risk") or []) if str(r).strip()]
    if risk:
        clauses.append("c.risk = ANY(:risk)")
        params["risk"] = risk

    language = [str(x).strip() for x in (selector.get("language") or []) if str(x).strip()]
    if language:
        clauses.append("c.language = ANY(:language)")
        params["language"] = language

    if selector.get("excludeOpenPromise"):
        # A borrower who has already promised has been asked and answered.
        # Ringing them again before the date is how a kept promise becomes a
        # broken one.
        clauses.append(
            # `upcoming` / `due_today` and not `open`: promises.status has no
            # such value, and the CHECK constraint would have let this clause
            # match nothing at all while the checkbox on the screen said it was
            # excluding people.
            "NOT EXISTS (SELECT 1 FROM promises p WHERE p.customer_id = c.id "
            "AND p.status IN ('upcoming','due_today') AND p.promised_at >= now())"
        )

    if selector.get("excludeOnHold"):
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM treatment_holds h WHERE h.customer_id = c.id "
            "AND h.released_at IS NULL AND (h.expires_at IS NULL OR h.expires_at > now()))"
        )

    days = selector.get("excludeContactedWithinDays")
    if days is not None:
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM contact_events e WHERE e.customer_id = c.id "
            "AND e.outcome = 'allowed' AND e.touch_counted "
            "AND e.occurred_at >= now() - make_interval(days => :recent_days))"
        )
        params["recent_days"] = max(0, int(days))

    return clauses, params


def resolve_selector(
    conn: Any,
    *,
    tenant_id: str,
    selector: dict[str, Any] | None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Turn a declarative cohort description into the borrowers it names.

    ``campaign_runs.selector`` has been a stored, validated, versioned jsonb
    column since the table was created, and nothing has ever read it: a cohort
    could only be built by POSTing a list of customer ids. The column described
    the campaign and the campaign was defined somewhere else entirely.

    The fields are a closed set on purpose. A selector is a description of whose
    phone rings, so an unrecognised key is an error rather than something to
    skip — the failure mode of skipping is a run that looks exactly like the one
    the operator wrote and calls a different population.

    This is a *selection*, not an authorisation. Every borrower it returns still
    passes ``contact_policy.admit`` at dial time, the calling window, the daily
    cap and the card's ``max_attempts``. Nothing here can widen any of those,
    and the exclusions it does offer — an open promise, a live hold, a recent
    touch — exist to keep obviously wasteful calls out of the run rather than to
    stand in for the gate.
    """
    selector = selector or {}
    clauses, params = _selector_clauses(selector)
    params["tenant"] = tenant_id
    cap = limit if limit is not None else selector.get("limit")
    params["limit"] = max(1, min(int(cap or 500), SELECTOR_MAX))

    rows = conn.execute(
        text(
            f"""
            SELECT DISTINCT ON (c.id) c.id AS customer_id, c.name, c.risk,
                   a.id AS account_id, a.dpd, a.bucket, a.outstanding
            FROM customers c
            JOIN accounts a ON a.customer_id = c.id
            WHERE {' AND '.join(clauses)}
            ORDER BY c.id, a.dpd DESC NULLS LAST
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def preview_selector(
    conn: Any, *, tenant_id: str, selector: dict[str, Any] | None, sample: int = 10
) -> dict[str, Any]:
    """Who this selector would call, before anything is created.

    A campaign is the one object in this system whose accidental creation rings
    real phones. Seeing the population first is not a convenience.
    """
    rows = resolve_selector(conn, tenant_id=tenant_id, selector=selector)
    return {
        "matched": len(rows),
        "capped": len(rows) >= max(1, min(int((selector or {}).get("limit") or 500), SELECTOR_MAX)),
        "sample": rows[: max(0, int(sample))],
    }


def add_targets_from_selector(
    conn: Any, run_id: str, *, tenant_id: str, selector: dict[str, Any] | None = None
) -> int:
    """Resolve the run's own selector and add everyone it names."""
    if selector is None:
        row = conn.execute(
            text("SELECT selector FROM campaign_runs WHERE id = :id AND tenant_id = :t"),
            {"id": run_id, "t": tenant_id},
        ).mappings().first()
        if row is None:
            raise SelectorError("run_not_found")
        selector = row["selector"] if isinstance(row["selector"], dict) else {}
    rows = resolve_selector(conn, tenant_id=tenant_id, selector=selector)
    return add_targets(conn, run_id, [r["customer_id"] for r in rows])


def set_status(conn: Any, run_id: str, status: str) -> dict[str, Any] | None:
    stamps = {
        STATUS_RUNNING: "started_at = COALESCE(started_at, now()), paused_at = NULL",
        STATUS_PAUSED: "paused_at = now()",
        STATUS_FINISHED: "finished_at = now()",
        STATUS_CANCELLED: "finished_at = now()",
    }.get(status, "")
    row = conn.execute(
        text(
            f"""
            UPDATE campaign_runs
            SET status = :status, updated_at = now()
                {(', ' + stamps) if stamps else ''}
            WHERE id = :id
            RETURNING *
            """
        ),
        {"id": run_id, "status": status},
    ).mappings().first()
    return dict(row) if row else None


def progress(conn: Any, run_id: str) -> dict[str, Any]:
    row = conn.execute(
        text(
            """
            SELECT
              count(*)                                          AS total,
              count(*) FILTER (WHERE state = 'pending')         AS pending,
              count(*) FILTER (WHERE state = 'dialing')         AS dialing,
              count(*) FILTER (WHERE state = 'done')            AS done,
              count(*) FILTER (WHERE state = 'skipped')         AS skipped,
              count(*) FILTER (WHERE state = 'failed')          AS failed
            FROM campaign_targets WHERE run_id = :run
            """
        ),
        {"run": run_id},
    ).mappings().first()
    return {k: int(v or 0) for k, v in dict(row or {}).items()}


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------


def _live_for_run(conn: Any, run_id: str) -> int:
    return int(
        conn.execute(
            text(
                """
                SELECT count(*) FROM call_attempts
                WHERE campaign_run_id = :run
                  AND state IN ('reserved','dialing','ringing','answered','live')
                """
            ),
            {"run": run_id},
        ).scalar()
        or 0
    )


def _claim_run(conn: Any) -> dict[str, Any] | None:
    return (
        conn.execute(
            text(
                """
                SELECT * FROM campaign_runs
                WHERE status = 'running'
                ORDER BY started_at ASC NULLS LAST
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            )
        )
        .mappings()
        .first()
    )


def process_one(engine: Engine) -> bool:
    """Dial one target from one running campaign. True if anything was claimed.

    Deliberately one target per call. The worker loop is shared with bot turns,
    promise settlement and the treatment loops; a campaign that drained its
    whole list in one iteration would be a dialler deciding it matters more than
    a customer waiting for a reply.
    """
    if not enabled():
        return False

    import contact_policy
    import db as dbmod
    import mission as mission_mod

    attempt = None
    phone = None
    with engine.begin() as conn:
        run = _claim_run(conn)
        if run is None:
            return False
        run = dict(run)
        run_id = run["id"]

        if _live_for_run(conn, run_id) >= int(run["max_concurrent"]):
            # At this run's ceiling. Not an error and not a reason to look at
            # another run this tick — returning True keeps the worker's fair
            # share intact instead of spinning through every campaign.
            return True

        target = conn.execute(
            text(
                """
                SELECT t.*, c.phone_primary, c.phone_alt, c.timezone, c.tenant_id
                FROM campaign_targets t
                JOIN customers c ON c.id = t.customer_id
                WHERE t.run_id = :run
                  AND t.state = 'pending'
                  AND (t.next_attempt_at IS NULL OR t.next_attempt_at <= now())
                ORDER BY t.created_at ASC
                FOR UPDATE OF t SKIP LOCKED
                LIMIT 1
                """
            ),
            {"run": run_id},
        ).mappings().first()
        if target is None:
            _finish_if_drained(conn, run_id)
            return True

        target = dict(target)
        if not within_window(run, tz_name=target.get("timezone")):
            # Push past the window rather than marking the target skipped: the
            # borrower is not unreachable, it is simply the wrong hour, and a
            # run that burned its list overnight would look complete and have
            # called nobody.
            conn.execute(
                text(
                    """
                    UPDATE campaign_targets
                    SET next_attempt_at = now() + interval '30 minutes', updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": target["id"]},
            )
            return True

        phone = target.get("phone_primary") or target.get("phone_alt")
        if not phone:
            _mark(conn, target["id"], "skipped", note="no_phone_on_file")
            return True

        bot_id = run.get("bot_id") or dbmod.DEFAULT_BOT_ID
        card = mission_mod.card_for_bot(bot_id)
        objective = str(run["objective"])
        built = mission_mod.build(
            conn,
            customer_id=target["customer_id"],
            objective=objective,
            account_id=target.get("account_id"),
            card=card,
            bot_id=bot_id,
            campaign_run_id=run_id,
            attempt_no=int(target.get("attempts") or 0) + 1,
        )
        pool = getattr(getattr(card, "outbound", None), "number_pool", None)
        attempt = outbound.reserve(
            conn,
            customer_id=target["customer_id"],
            to_phone=phone,
            objective=objective,
            account_id=target.get("account_id"),
            campaign_run_id=run_id,
            bot_id=bot_id,
            tenant_id=target.get("tenant_id"),
            number_pool=pool,
            phone_slot="primary" if target.get("phone_primary") else "alt",
            context={"source": "campaign", "runId": run_id, "mission": built},
        )
        if attempt is None:
            _mark(conn, target["id"], "skipped", note="customer_gone")
            return True

        decision = contact_policy.admit(
            conn,
            customer_id=target["customer_id"],
            channel="voice",
            purpose="outreach",
            # A cross-sell dial is a promotional use of a number collected to
            # service a loan, and needs its own consent basis. Every other
            # objective here is servicing. See flow_graph.PROMOTIONAL_OBJECTIVES.
            data_purpose=fg.data_purpose_for(objective),
            session_key=attempt["id"],
            source="campaign",
            related_id=attempt["id"],
            actor_kind="bot",
            account_id=target.get("account_id"),
        )
        if not decision.allowed:
            outbound.suppress(conn, attempt["id"], decision.reason or "contact_policy")
            # Try again later unless the refusal is about *them* rather than
            # about now. An opt-out is permanent; a daily cap is not.
            permanent = decision.reason in {
                contact_policy.REASON_OPTED_OUT,
                contact_policy.REASON_CHANNEL_DND,
                contact_policy.REASON_CUSTOMER_DND,
                contact_policy.REASON_NO_CUSTOMER,
            }
            if permanent:
                _mark(conn, target["id"], "skipped", note=decision.reason)
            else:
                conn.execute(
                    text(
                        """
                        UPDATE campaign_targets
                        SET next_attempt_at = now() + interval '2 hours', updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {"id": target["id"]},
                )
            return True

        conn.execute(
            text(
                """
                UPDATE campaign_targets
                SET state = 'dialing', attempts = attempts + 1,
                    last_attempt_id = :attempt, next_attempt_at = NULL, updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": target["id"], "attempt": attempt["id"]},
        )
        target_id = target["id"]

    result = outbound.place(engine, attempt, to_phone=phone)
    with engine.begin() as conn:
        if not result.get("placed"):
            # Back to pending: `fleet_busy` is a fact about us, not about them.
            conn.execute(
                text(
                    """
                    UPDATE campaign_targets
                    SET state = 'pending',
                        next_attempt_at = now() + interval '5 minutes',
                        updated_at = now()
                    WHERE id = :id
                    """
                ),
                {"id": target_id},
            )
        else:
            conn.execute(
                text(
                    "UPDATE campaign_runs SET targets_done = targets_done + 1, "
                    "updated_at = now() WHERE id = :run"
                ),
                {"run": run_id},
            )
    logger.info(
        "campaign %s · target=%s · placed=%s", run_id, target_id, result.get("placed")
    )
    return True


def _mark(conn: Any, target_id: str, state: str, *, note: str | None = None) -> None:
    conn.execute(
        text(
            """
            UPDATE campaign_targets
            SET state = :state, note = COALESCE(:note, note), updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": target_id, "state": state, "note": note},
    )


def _finish_if_drained(conn: Any, run_id: str) -> None:
    """Finish a run only when nothing is still in the air.

    A run with pending targets that are all waiting for their window is not
    finished, and neither is one whose last dial is still ringing.
    """
    remaining = conn.execute(
        text(
            """
            SELECT count(*) FROM campaign_targets
            WHERE run_id = :run AND state IN ('pending','dialing')
            """
        ),
        {"run": run_id},
    ).scalar()
    if int(remaining or 0) == 0:
        set_status(conn, run_id, STATUS_FINISHED)
        logger.info("campaign %s finished", run_id)


def on_attempt_closed(conn: Any, attempt: dict[str, Any], business: str | None) -> None:
    """Mark the target done once its attempt has an outcome. Never raises."""
    run_id = attempt.get("campaign_run_id")
    if not run_id:
        return
    try:
        conn.execute(
            text(
                """
                UPDATE campaign_targets
                SET state = 'done', outcome = :outcome, updated_at = now()
                WHERE run_id = :run AND customer_id = :cid AND state = 'dialing'
                """
            ),
            {"run": run_id, "cid": attempt["customer_id"], "outcome": business},
        )
    except Exception:
        logger.exception("campaign target close failed for attempt %s", attempt.get("id"))
