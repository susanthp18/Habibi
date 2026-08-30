"""The upsell pipeline's seams: attribution, scheduling, escalation, metrics.

Each test here covers a defect where the system disagreed with itself and no
exception was ever raised. That is the expensive kind: a funnel that undercounts
and a queue that is permanently overdue both look like working software, and
both quietly make every number computed from them meaningless.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import db

IST = timezone(timedelta(hours=5, minutes=30))


def _a_customer(conn) -> str:
    row = conn.execute(
        text("SELECT id FROM customers WHERE tenant_id = :t ORDER BY id LIMIT 1"),
        {"t": db._tenant()},
    ).scalar()
    if row is None:
        pytest.skip("no seeded customer in this database")
    return row


def _a_product(conn) -> str:
    row = conn.execute(text("SELECT id FROM products ORDER BY id LIMIT 1")).scalar()
    if row is None:
        pytest.skip("no seeded product in this database")
    return row


def _events(conn, lead_id: str, kind: str) -> int:
    return conn.execute(
        text(
            "SELECT COUNT(*) FROM activity_events"
            " WHERE entity_type = 'lead' AND entity_id = :id AND kind = :k"
        ),
        {"id": lead_id, "k": kind},
    ).scalar()


# --------------------------------------------------------------- attribution


def test_a_lead_captured_from_the_ui_lands_in_the_offer_funnel(db_tx):
    """The numerator used to come from one caller of three.

    `lead_captured` was emitted only by the bot's own tool, so a lead a rep
    raised in the UI — including one captured straight off an offer the engine
    had recommended — counted for nothing in close-probe conversion, while the
    denominator kept counting the call it came from.
    """
    customer_id = _a_customer(db_tx)
    emitted: list[str] = []
    lead = db.create_lead(
        {
            "customerId": customer_id,
            "productId": _a_product(db_tx),
            "source": "agent",
            "channel": "voice",
        },
        allow_duplicate=True,
        emitted=emitted,
    )

    assert emitted == ["lead_captured"]
    assert _events(db_tx, lead["id"], "lead_captured") == 1
    # The CRM audit entry is a separate fact and still written.
    assert _events(db_tx, lead["id"], "lead_created") == 1


def test_a_ui_capture_is_attributed_to_the_person_not_a_bot(db_tx):
    """emit_commercial_event defaults to a bot actor and falls back to
    DEFAULT_BOT_ID. Routing human captures through it without saying so would
    have credited every rep's lead to whichever bot the process configured."""
    lead = db.create_lead(
        {
            "customerId": _a_customer(db_tx),
            "productId": _a_product(db_tx),
            "source": "agent",
        },
        allow_duplicate=True,
    )
    row = db_tx.execute(
        text(
            "SELECT actor_kind, actor_bot_id FROM activity_events"
            " WHERE entity_type = 'lead' AND entity_id = :id AND kind = 'lead_captured'"
        ),
        {"id": lead["id"]},
    ).mappings().first()

    assert row["actor_kind"] == "human"
    assert row["actor_bot_id"] is None


def test_the_capture_event_does_not_double_the_lead_timeline(db_tx):
    """`lead_captured` and `lead_created` record the same act. Both belong in
    the table; only one belongs on the drawer's timeline."""
    lead = db.create_lead(
        {
            "customerId": _a_customer(db_tx),
            "productId": _a_product(db_tx),
            "source": "agent",
        },
        allow_duplicate=True,
    )
    kinds = [e["kind"] for e in db._lead_events(db_tx, lead["id"])]
    assert kinds.count("created") == 1


# ---------------------------------------------------------------- scheduling


def _slot_at_ist_hour(hour: int) -> str:
    """A slot tomorrow at a given IST hour, as an ISO string.

    Safe for the *refusal* case at any hour outside 08:00–19:00: the RBI check
    runs ahead of the consent window, so an illegal hour is always reported as
    ``outside_calling_hours`` whatever day tomorrow happens to be.
    """
    tomorrow = datetime.now(IST) + timedelta(days=1)
    return tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def _slot_the_customer_permits(conn, lead_id: str, hour: int = 11) -> str:
    """A future slot that breaks neither the RBI window nor *this* customer's
    own consent window.

    Two separate gates return two different reasons, and the booking test is
    about the first one — so the second has to be satisfied rather than tripped
    over. Hardcoding "tomorrow at 11:00" tripped over it: every seeded customer
    carries ``allowed_days = 'Mon-Sat'``, so the test refused its own legal slot
    with ``outside_allowed_window`` on precisely one day of the week, and the
    suite was red every Saturday for a reason that had nothing to do with what
    it was testing.

    The window is read with contact_policy's own exported parsers rather than a
    second copy: a copy agrees on Tuesday and disagrees in November, which is
    the exact failure those exports exist to prevent.
    """
    import contact_policy

    row = (
        conn.execute(
            text(
                "SELECT cr.allowed_days, cr.allowed_hours FROM leads l"
                " LEFT JOIN consent_records cr ON cr.customer_id = l.customer_id"
                " WHERE l.id = :id"
            ),
            {"id": lead_id},
        )
        .mappings()
        .first()
    )
    days = contact_policy.parse_allowed_days(row["allowed_days"]) if row else None
    hours = contact_policy.parse_allowed_hours(row["allowed_hours"]) if row else None

    # Intersect the customer's hours with RBI's, then sit inside both.
    start_h = max(contact_policy.RBI_VOICE_START, hours[0] if hours else 0)
    end_h = min(contact_policy.RBI_VOICE_END, hours[1] if hours else 24)
    if start_h >= end_h:
        pytest.skip("this customer's consent window excludes every legal calling hour")
    hour = min(max(hour, start_h), end_h - 1)

    when = datetime.now(IST) + timedelta(days=1)
    for _ in range(7):
        # Consent days: 0=Sun … 6=Sat, same convention evaluate() compares with.
        if days is None or (when.isoweekday() % 7) in days:
            break
        when += timedelta(days=1)
    else:  # pragma: no cover - a consent record allowing no day at all
        pytest.skip("this customer's consent window excludes every day")
    return when.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def test_a_follow_up_outside_the_calling_window_is_refused(db_tx):
    """RBI's 08:00–19:00 restriction bound every collections contact and none
    of the sales ones. A voice follow-up could be diaried for 02:00 and the
    first person to discover it was the rep who dialled."""
    lead_id = db_tx.execute(
        text("SELECT id FROM leads WHERE stage = ANY(:s) LIMIT 1"),
        {"s": list(db.OPEN_LEAD_STAGES)},
    ).scalar()
    if lead_id is None:
        pytest.skip("no open lead in this database")

    with pytest.raises(ValueError) as exc:
        db.add_lead_followup(
            lead_id,
            {"scheduledAt": _slot_at_ist_hour(2), "channel": "voice", "note": "x"},
        )
    assert "outside_calling_hours" in str(exc.value)


def test_a_follow_up_inside_the_calling_window_is_booked(db_tx):
    """The gate must refuse the illegal slot, not the feature."""
    lead_id = db_tx.execute(
        text("SELECT id FROM leads WHERE stage = ANY(:s) LIMIT 1"),
        {"s": list(db.OPEN_LEAD_STAGES)},
    ).scalar()
    if lead_id is None:
        pytest.skip("no open lead in this database")

    result = db.add_lead_followup(
        lead_id,
        {
            "scheduledAt": _slot_the_customer_permits(db_tx, lead_id),
            "channel": "voice",
            "note": "x",
        },
    )
    assert result["status"] == "open"


def test_the_window_is_checked_at_the_scheduled_time_not_at_booking_time():
    """The whole point: `blocks_scheduling` takes the moment being booked.
    Evaluating "now" instead would let anyone book 03:00 during the day."""
    import contact_policy

    assert "at" in contact_policy.blocks_scheduling.__code__.co_varnames
    # Volume limits are counted against today and cannot describe next week, so
    # they must not be able to veto a booking.
    assert contact_policy.REASON_DAILY not in contact_policy.SCHEDULING_VETOES
    assert contact_policy.REASON_WEEKLY not in contact_policy.SCHEDULING_VETOES
    assert contact_policy.REASON_HOURS in contact_policy.SCHEDULING_VETOES


# ---------------------------------------------------------------- escalation


def test_an_overdue_follow_up_is_escalated_exactly_once(db_tx):
    """Nothing acted on a due follow-up — the pipeline waited to be noticed.

    Idempotence matters more than the escalation here: the sweep runs every ten
    minutes, and a second pass must not re-raise work somebody has already
    triaged back down.
    """
    lead_id = db_tx.execute(
        text("SELECT id FROM leads WHERE stage = ANY(:s) LIMIT 1"),
        {"s": list(db.OPEN_LEAD_STAGES)},
    ).scalar()
    if lead_id is None:
        pytest.skip("no open lead in this database")

    # Back-dated rather than wall-clocked: the fixture's now() is frozen at the
    # start of the transaction, so "a minute ago" has to be written as one.
    db_tx.execute(
        text("UPDATE leads SET priority = 'normal' WHERE id = :id"), {"id": lead_id}
    )
    db_tx.execute(
        text(
            "INSERT INTO followups (id, lead_id, customer_id, status, priority, due_at, note, channel)"
            " SELECT 'FU-TEST-SWEEP', id, customer_id, 'open', 'normal',"
            "        now() - interval '1 hour', 'due', 'voice' FROM leads WHERE id = :id"
        ),
        {"id": lead_id},
    )

    first = db.sweep_due_followups()
    assert lead_id in first["leads"]

    second = db.sweep_due_followups()
    assert lead_id not in second["leads"]

    escalated = db_tx.execute(
        text("SELECT priority FROM followups WHERE id = 'FU-TEST-SWEEP'")
    ).scalar()
    assert escalated == "high"
    # The board sorts and colours by the lead's priority, so escalating only
    # the follow-up would raise it in the queue and leave it looking routine.
    assert (
        db_tx.execute(text("SELECT priority FROM leads WHERE id = :id"), {"id": lead_id}).scalar()
        == "high"
    )


def test_the_sweep_never_contacts_anyone():
    """It escalates. Reaching out is a contact-policy decision with consent,
    hours and frequency caps attached, and a background sweep must not make one
    silently — so nothing in here may enqueue an outbound touch."""
    import inspect

    source = inspect.getsource(db.sweep_due_followups)
    for forbidden in ("whatsapp_outbound", "twilio", "enqueue", "place_call", "admit("):
        assert forbidden not in source


# ------------------------------------------------------------------- metrics


def test_the_kpi_strip_is_computed_over_the_whole_book(db_tx):
    """These numbers were derived in the browser from one page of GET /leads,
    which pages at 200. Below that the answer happened to be right."""
    metrics = db.lead_metrics()
    truth = db_tx.execute(
        text(
            """
            SELECT
              COUNT(*)::int AS total,
              COUNT(*) FILTER (WHERE l.stage IN ('interested','contacted','qualified'))::int AS open
            FROM leads l
            JOIN customers c ON c.id = l.customer_id AND c.tenant_id = :t
            """
        ),
        {"t": db._tenant()},
    ).mappings().first()

    assert metrics["total"] == truth["total"]
    assert metrics["openLeads"] == truth["open"]


def test_an_empty_denominator_is_a_dash_not_a_zero(db_tx):
    """"Nothing was captured this month" and "none of what we captured
    converted" call for opposite responses. Rendering both as 0% is how a quiet
    month looks identical to a broken pipeline."""
    metrics = db.lead_metrics({"q": "no-such-lead-anywhere-xyzzy"})

    assert metrics["total"] == 0
    assert metrics["conversionRate"] is None
    assert metrics["avgDaysToClose"] is None


def test_filters_narrow_the_metrics_and_the_list_together(db_tx):
    """The strip and the board have to describe the same set. They are computed
    by different queries, so this is the only thing keeping them honest."""
    rows = db.list_leads(filters={"stage": "won"})
    metrics = db.lead_metrics({"stage": "won"})

    assert metrics["total"] == len(rows)
    assert all(r["stage"] == "won" for r in rows)
    assert metrics["openLeads"] == 0


def test_a_multi_select_filter_matches_any_of_its_values(db_tx):
    """Priority and sentiment are multi-select on the screen. A single-value
    filter here would have forced them to stay client-side, and then the strip
    and the board would be describing different sets again."""
    both = db.list_leads(filters={"priority": "high,normal"})
    high = db.list_leads(filters={"priority": "high"})
    normal = db.list_leads(filters={"priority": "normal"})

    assert len(both) == len(high) + len(normal)


# ----------------------------------------------------------------- work queue


def test_a_lead_is_due_when_its_follow_up_is_due(db_tx):
    """`sla_due_at` was `captured_at`, which is in the past by construction —
    so every open lead sat in My Workspace as permanently overdue and the one
    row that knows when the work is actually due was ignored."""
    row = db_tx.execute(
        text(
            """
            SELECT w.sla_due_at, f.due_at
            FROM work_items w
            JOIN followups f ON f.lead_id = w.entity_id
             AND f.status IN ('open','in_progress','snoozed')
            WHERE w.entity_type = 'lead'
            LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no open lead with an open follow-up in this database")

    assert row["sla_due_at"] == row["due_at"]


def test_one_piece_of_work_appears_in_the_queue_once(db_tx):
    """A lead and its follow-up were both emitted, under two entity types, with
    two contradictory due dates."""
    duplicated = db_tx.execute(
        text(
            """
            SELECT COUNT(*) FROM work_items w
            JOIN followups f ON f.id = w.entity_id
            WHERE w.entity_type = 'followup' AND f.lead_id IS NOT NULL
            """
        )
    ).scalar()
    assert duplicated == 0
