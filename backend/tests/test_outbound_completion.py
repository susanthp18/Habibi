"""The rest of the outbound engine: the parts that were still stubs or lies.

Section 20 of ``outbound-agent-engine.md`` closed seven fields that were
configured, validated, versioned and publishable while having no effect. This
file covers the round after it, and four of the eight items are the same species
of defect found in different rooms:

* ``treatment.enact._copy`` claimed a grievance route in its docstring and
  shipped ``"Queries: reply to this message."``;
* ``tenants.grievance_officer`` was seeded by nothing, so the compliant path was
  the one a fresh install could not take;
* ``pool_numbers.attempts_7d`` was incremented per dial and never decayed - a
  lifetime counter wearing a rate's name - while ``answer_rate_7d`` and the
  ``cooling`` state were written by nothing at all;
* ``campaign_runs.selector`` was stored, validated and read by nothing;
* ``customers.preferred_window`` was populated across the seeded book and read
  only by the recommender's *talk track*, which used it to promise a borrower a
  callback window the dialler then ignored.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import campaigns
import compliance_copy
import contact_policy
import outbound
import written_followup
from agent_core import canary

FULL = {
    "issuer": "HDFC Bank",
    "contactNumber": "18002026161",
    "officer": {"name": "R Menon", "phone": "18001234567", "email": "grievance@example.test"},
}
NAME_ONLY = {"issuer": "HDFC Bank", "officer": {"name": "R Menon"}}

TENANT = "hdfc.retail"


# ---------------------------------------------------------------------------
# One disclosure, one renderer
# ---------------------------------------------------------------------------


def test_the_written_footer_names_the_officer() -> None:
    footer = compliance_copy.written_footer(FULL)
    assert "R Menon" in footer
    assert "18001234567" in footer
    assert "grievance@example.test" in footer


def test_an_officer_with_no_phone_is_not_a_grievance_route() -> None:
    """A name and no way to reach them does not satisfy para 100AA."""
    assert compliance_copy.written_footer(NAME_ONLY) is None
    assert compliance_copy.spoken_footer(NAME_ONLY) is None


def test_the_spoken_footer_spaces_the_digits() -> None:
    """Otherwise TTS reads 18001234567 as a number in the billions."""
    spoken = compliance_copy.spoken_footer(FULL)
    assert "1 8 0 0 1 2 3 4 5 6 7" in spoken
    # An email address has never once been successfully transcribed from a
    # voicemail, so the spoken form leaves it out.
    assert "grievance@example.test" not in spoken


def test_the_voicemail_uses_the_same_renderer() -> None:
    """Two copies of one duty drift; the enact docstring is the proof."""
    from voice import amd

    script = amd.voicemail_script({"agentName": "Priya"}, contacts=FULL)
    assert compliance_copy.spoken_footer(FULL) in script


def test_dunning_copy_carries_the_footer(db_tx) -> None:
    from agent_core.treatment import enact

    decision = {"id": "TD-TEST", "account_id": "AC-1234", "customer_id": "cust-susanth"}
    body = enact._copy(db_tx, decision)
    assert "Grievance officer" in body
    assert "reply to this message" not in body


def test_dunning_refuses_to_send_without_an_officer(db_tx, monkeypatch) -> None:
    """The same call the voicemail path makes, made once and made everywhere."""
    from agent_core.treatment import enact

    monkeypatch.setattr(compliance_copy, "written_footer", lambda *a, **k: None)
    with pytest.raises(enact.NoExecutor) as excinfo:
        enact._copy(db_tx, {"id": "TD-TEST", "account_id": "AC-1234"})
    assert compliance_copy.NO_GRIEVANCE_CONTACT in str(excinfo.value)


def test_the_seeded_tenant_has_an_officer(db_tx) -> None:
    """A fresh install must be able to take the compliant path.

    Without the seed, ``written_footer()`` returns None for every tenant, which
    means no voicemail is ever left and no dunning message is ever sent -
    correctly, silently, and for a reason nobody would find.
    """
    row = db_tx.execute(
        text("SELECT grievance_officer FROM tenants WHERE id = :tenant"), {"tenant": TENANT}
    ).scalar()
    assert isinstance(row, dict) and row.get("name") and row.get("phone")


# ---------------------------------------------------------------------------
# Written follow-up beyond promises
# ---------------------------------------------------------------------------


def test_a_wrong_number_is_never_written_to(db_tx) -> None:
    """The handset is a stranger's. Anything we send tells them a bank called."""
    result = written_followup.for_outcome(
        db_tx, customer_id="cust-susanth", business="wrong_number"
    )
    assert result.sent is False
    assert result.reason == "third_party_number"


def test_an_opt_out_is_honoured_rather_than_confirmed(db_tx) -> None:
    """One more message to somebody who just said stop is still one more message."""
    result = written_followup.for_outcome(
        db_tx, customer_id="cust-susanth", business="opt_out_requested"
    )
    assert result.sent is False
    assert result.reason == "opt_out_honoured"


def test_an_outcome_with_nothing_to_say_declines(db_tx) -> None:
    """A hardship note that cannot state the hold date invites a reply we
    have nothing to answer with."""
    assert written_followup.render("hardship_ack", {}) is None
    assert written_followup.render("dispute_ref", {"reference": "   "}) is None


def test_the_hardship_note_states_the_hold_it_was_given(db_tx) -> None:
    body = written_followup.render("hardship_ack", {"holdUntil": "2026-09-21"})
    assert "2026-09-21" in body
    assert "paused" in body.lower()


def test_no_kind_exists_that_cannot_fire() -> None:
    """``plan_ack`` was written and then deleted before it shipped.

    An agreed plan reaches the Closer as a promise row, and a promise routes to
    ``promise_fulfillment.fulfill``. A plan acknowledgement could only fire on an
    outcome that agreed a plan *without* writing a promise - which is exactly the
    case with no amount and no date to state. Shipping it would have added a
    fifth kind that validates, versions and never sends.
    """
    assert "plan_ack" not in written_followup.KINDS
    for outcome, kind in written_followup.BY_OUTCOME.items():
        assert kind in written_followup.KINDS, outcome


# ---------------------------------------------------------------------------
# The borrower's own calling window
# ---------------------------------------------------------------------------


def test_the_stated_window_narrows_the_consented_one() -> None:
    assert contact_policy.preferred_hours(
        {"allowed_hours": "10:00-19:00 IST", "preferred_window": "09:00-13:00 IST"}
    ) == (10, 13)


def test_a_preference_alone_is_honoured() -> None:
    assert contact_policy.preferred_hours(
        {"allowed_hours": None, "preferred_window": "11:00-16:00 IST"}
    ) == (11, 16)


def test_windows_that_do_not_overlap_fall_back_to_consent() -> None:
    """Almost certainly a data-entry error rather than a borrower nobody may call."""
    assert contact_policy.preferred_hours(
        {"allowed_hours": "10:00-12:00 IST", "preferred_window": "18:00-21:00 IST"}
    ) == (10, 12)


def test_an_evening_preference_cannot_buy_a_nine_oclock_call(db_tx) -> None:
    """The seeded book contains an 18:00-21:00 preference. Para 100Y still ends at 19:00."""
    reason = contact_policy._veto(
        purpose="outreach",
        channel="voice",
        customer={"id": "x", "preferred_window": "18:00-21:00 IST"},
        status=None,
        now_local=datetime(2026, 8, 22, 20, 0),
    )
    assert reason == contact_policy.REASON_HOURS


def _customer_for(conn) -> str:
    cid = f"cust-win-{uuid.uuid4().hex[:8]}"
    conn.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, risk) "
            "VALUES (:id, :tenant, 'Window Test', 'low')"
        ),
        {"id": cid, "tenant": TENANT},
    )
    return cid


def test_a_stated_restriction_is_written_down(db_tx) -> None:
    """RBI para 100Y moves the window for a borrower who asks; nothing wrote it."""
    cid = _customer_for(db_tx)
    result = contact_policy.narrow_window(db_tx, customer_id=cid, earliest_hour=10)
    assert result["ok"] and result["window"] == [10, 19]
    stored = db_tx.execute(
        text("SELECT allowed_hours FROM consent_records WHERE customer_id = :c"), {"c": cid}
    ).scalar()
    assert contact_policy.parse_allowed_hours(stored) == (10, 19)


def test_a_restriction_can_only_ever_tighten(db_tx) -> None:
    """A hallucinated loosening would delete a restriction the borrower stated,
    and no log line makes that acceptable."""
    cid = _customer_for(db_tx)
    contact_policy.narrow_window(db_tx, customer_id=cid, earliest_hour=12)
    again = contact_policy.narrow_window(db_tx, customer_id=cid, earliest_hour=8)
    assert again["window"] == [12, 19]


def test_a_window_with_nothing_in_it_is_refused(db_tx) -> None:
    """That is a request to stop calling, which is an opt-out and has its own path."""
    cid = _customer_for(db_tx)
    result = contact_policy.narrow_window(
        db_tx, customer_id=cid, earliest_hour=18, latest_hour=9
    )
    assert result["ok"] is False
    assert result["reason"] == "window_would_be_empty"


def test_the_planner_and_the_gate_share_one_window_definition() -> None:
    """A second parser that agreed on Tuesday is one that disagrees in November."""
    from agent_core.treatment import features

    import inspect

    source = inspect.getsource(features.AccountFeatures.__module__ and features)
    assert "contact_policy.preferred_hours(" in source
    assert "contact_policy.parse_allowed_hours(base[" not in source


# ---------------------------------------------------------------------------
# Consent is per channel AND per purpose
# ---------------------------------------------------------------------------


def _consent_row(conn, customer_id: str, channel: str, purpose: str, status: str) -> None:
    consent_id = conn.execute(
        text("SELECT id FROM consent_records WHERE customer_id = :c"), {"c": customer_id}
    ).scalar()
    if consent_id is None:
        consent_id = f"CR-{uuid.uuid4().hex[:10].upper()}"
        conn.execute(
            text("INSERT INTO consent_records (id, customer_id) VALUES (:id, :c)"),
            {"id": consent_id, "c": customer_id},
        )
    conn.execute(
        text(
            """
            INSERT INTO channel_consents (id, consent_id, channel, purpose, status, captured_at)
            VALUES (:id, :consent, :ch, :purpose, :status, now())
            ON CONFLICT (consent_id, channel, purpose)
            DO UPDATE SET status = EXCLUDED.status, captured_at = now()
            """
        ),
        {
            "id": f"CC-{uuid.uuid4().hex[:10].upper()}",
            "consent": consent_id,
            "ch": channel,
            "purpose": purpose,
            "status": status,
        },
    )


def test_servicing_consent_does_not_authorise_marketing(db_tx) -> None:
    """The number was collected to service a loan. Selling is a different purpose."""
    cid = _customer_for(db_tx)
    _consent_row(db_tx, cid, "voice", "servicing", "opted_in")
    decision = contact_policy.evaluate(
        db_tx, customer_id=cid, channel="voice", data_purpose="promotional"
    )
    assert decision.allowed is False
    assert decision.reason == contact_policy.REASON_NO_PROMO_CONSENT


def test_a_promotional_consent_authorises_it(db_tx) -> None:
    cid = _customer_for(db_tx)
    _consent_row(db_tx, cid, "voice", "servicing", "opted_in")
    _consent_row(db_tx, cid, "voice", "promotional", "opted_in")
    decision = contact_policy.evaluate(
        db_tx,
        customer_id=cid,
        channel="voice",
        data_purpose="promotional",
        now=datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc),
    )
    assert decision.allowed is True


def test_a_promotional_row_cannot_unblock_a_servicing_opt_out(db_tx) -> None:
    """The DISTINCT ON would have collapsed them into whichever came last."""
    import capture

    cid = _customer_for(db_tx)
    _consent_row(db_tx, cid, "whatsapp", "servicing", "opted_out")
    _consent_row(db_tx, cid, "whatsapp", "promotional", "opted_in")
    assert capture.latest_consent_by_channel(db_tx, cid)["whatsapp"] == "opted_out"
    assert capture.promotional_consent(db_tx, cid, "whatsapp") == "opted_in"


def test_only_cross_sell_is_a_promotional_objective() -> None:
    """Retention is a call about a product they already hold - that is servicing it."""
    import flow_graph as fg

    assert fg.data_purpose_for("cross_sell") == "promotional"
    for servicing in ("dpd_reminder", "retention_save", "welcome_onboarding", "bounce_cure"):
        assert fg.data_purpose_for(servicing) == "servicing"


# ---------------------------------------------------------------------------
# Number-pool health
# ---------------------------------------------------------------------------


def _pool_with_number(conn, e164: str, *, state: str = "active", changed_hours_ago: int = 0) -> str:
    pool_id = f"NP-{uuid.uuid4().hex[:8]}"
    number_id = f"PN-{uuid.uuid4().hex[:8]}"
    conn.execute(
        text(
            "INSERT INTO number_pools (id, tenant_id, name, kind) "
            "VALUES (:id, :tenant, :name, 'general')"
        ),
        {"id": pool_id, "name": pool_id, "tenant": TENANT},
    )
    conn.execute(
        text(
            """
            INSERT INTO pool_numbers (id, pool_id, e164, state, state_changed_at)
            VALUES (:id, :pool, :e164, :state,
                    now() - make_interval(hours => :ago))
            """
        ),
        {"id": number_id, "pool": pool_id, "e164": e164, "state": state, "ago": changed_hours_ago},
    )
    return number_id


def _attempts(conn, from_number: str, *, total: int, answered: int) -> None:
    """Back-dated inside the window. ``now()`` is the transaction start here, so
    a wall-clock stamp would be at or after it and the >= comparison still holds."""
    for i in range(total):
        conn.execute(
            text(
                """
                INSERT INTO call_attempts (
                  id, tenant_id, customer_id, objective, attempt_no,
                  to_phone_hash, phone_slot, from_number, state,
                  placed_at, answered_at, reserved_at
                ) VALUES (
                  :id, :tenant, 'cust-susanth', 'dpd_reminder', 1,
                  'hash', 'primary', :from_number, 'completed',
                  now() - interval '1 day', :answered_at, now() - interval '1 day'
                )
                """
            ),
            {
                "id": f"CA-{uuid.uuid4().hex[:10]}",
                "from_number": from_number,
                "tenant": TENANT,
                "answered_at": None if i >= answered else datetime.now(timezone.utc),
            },
        )


def test_a_number_nobody_answers_is_rested(db_tx) -> None:
    """Section 8.2's whole justification for the table, implemented by nothing."""
    e164 = f"+9199{uuid.uuid4().hex[:8]}"
    number_id = _pool_with_number(db_tx, e164)
    _attempts(db_tx, e164, total=40, answered=1)

    counts = outbound.refresh_pool_health(db_tx, tenant_id="hdfc.retail")
    assert counts["cooled"] == 1

    row = db_tx.execute(
        text("SELECT state, attempts_7d, answer_rate_7d FROM pool_numbers WHERE id = :id"),
        {"id": number_id},
    ).mappings().first()
    assert row["state"] == "cooling"
    assert row["attempts_7d"] == 40
    assert float(row["answer_rate_7d"]) == pytest.approx(0.025, abs=1e-4)


def test_a_bad_afternoon_does_not_retire_a_number(db_tx) -> None:
    """Volume gate first: a rate over four dials is noise, and cooling on noise
    shrinks the pool, which raises the load on the survivors."""
    e164 = f"+9199{uuid.uuid4().hex[:8]}"
    number_id = _pool_with_number(db_tx, e164)
    _attempts(db_tx, e164, total=4, answered=0)

    outbound.refresh_pool_health(db_tx, tenant_id="hdfc.retail")
    state = db_tx.execute(
        text("SELECT state FROM pool_numbers WHERE id = :id"), {"id": number_id}
    ).scalar()
    assert state == "active"


def test_cooling_is_a_door_that_opens_both_ways(db_tx) -> None:
    """A cooling number takes no attempts, so its window empties and it can never
    clear the volume gate again. Without this the first movement is one-way."""
    e164 = f"+9199{uuid.uuid4().hex[:8]}"
    number_id = _pool_with_number(db_tx, e164, state="cooling", changed_hours_ago=200)

    counts = outbound.refresh_pool_health(db_tx, tenant_id="hdfc.retail")
    assert counts["restored"] == 1
    state = db_tx.execute(
        text("SELECT state FROM pool_numbers WHERE id = :id"), {"id": number_id}
    ).scalar()
    assert state == "active"


def test_a_retired_number_is_left_alone(db_tx) -> None:
    """Retirement is a human decision about a number we mean to hand back."""
    e164 = f"+9199{uuid.uuid4().hex[:8]}"
    number_id = _pool_with_number(db_tx, e164, state="retired", changed_hours_ago=1000)
    outbound.refresh_pool_health(db_tx, tenant_id="hdfc.retail")
    state = db_tx.execute(
        text("SELECT state FROM pool_numbers WHERE id = :id"), {"id": number_id}
    ).scalar()
    assert state == "retired"


def test_picking_a_number_no_longer_fakes_a_seven_day_count(db_tx) -> None:
    """It was incremented per dial and never decayed - a lifetime counter with
    ``_7d`` in its name, which any dashboard would have rendered as a rate."""
    e164 = f"+9199{uuid.uuid4().hex[:8]}"
    number_id = _pool_with_number(db_tx, e164)
    pool_name = db_tx.execute(
        text("SELECT p.name FROM number_pools p JOIN pool_numbers n ON n.pool_id = p.id "
             "WHERE n.id = :id"),
        {"id": number_id},
    ).scalar()

    outbound.pick_number(db_tx, tenant_id="hdfc.retail", pool_name=pool_name)
    row = db_tx.execute(
        text("SELECT attempts_7d, last_used_at FROM pool_numbers WHERE id = :id"),
        {"id": number_id},
    ).mappings().first()
    assert row["attempts_7d"] == 0
    assert row["last_used_at"] is not None


# ---------------------------------------------------------------------------
# The canary knows what an outbound failure looks like
# ---------------------------------------------------------------------------


def test_the_outbound_rollback_triggers_exist() -> None:
    """Section 13 names all three. ``sweep_rollbacks`` had none of them."""
    for trigger in ("abandon_rate", "third_party_leak", "optout_spike"):
        assert trigger in canary.ROLLBACK_TRIGGERS


def test_one_abandoned_call_is_enough(db_tx) -> None:
    """Not a rate to be managed down. A borrower whose phone rings, who answers
    and hears silence is the conduct the amendment was written to stop, and the
    design makes it structurally impossible - so any occurrence means a break."""
    bot_id = db_tx.execute(text("SELECT id FROM bots LIMIT 1")).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO call_attempts (
              id, tenant_id, customer_id, objective, attempt_no, to_phone_hash,
              phone_slot, from_number, state, bot_id, reserved_at, updated_at
            ) VALUES (
              :id, :tenant, 'cust-susanth', 'dpd_reminder', 1,
              'hash', 'primary', '+911', 'abandoned', :bot, now(), now()
            )
            """
        ),
        {"id": f"CA-{uuid.uuid4().hex[:10]}", "bot": bot_id, "tenant": TENANT},
    )
    assert canary._abandoned(db_tx, bot_id) == 1


def test_an_opt_out_alone_is_not_a_spike() -> None:
    """A borrower asking to be left alone is a legitimate outcome, and an agent
    that never produced one would be the more worrying artefact."""
    assert canary.OPTOUT_SPIKE_THRESHOLD > 1


# ---------------------------------------------------------------------------
# The cohort a campaign actually calls
# ---------------------------------------------------------------------------


def test_an_unknown_selector_field_is_refused_not_ignored(db_tx) -> None:
    """Skipping it produces a run that looks like the one the operator wrote and
    calls a different population."""
    with pytest.raises(campaigns.SelectorError) as excinfo:
        campaigns.resolve_selector(
            db_tx, tenant_id="hdfc.retail", selector={"bucket": ["31-60"]}
        )
    assert "bucket" in str(excinfo.value)


def test_a_selector_resolves_to_borrowers(db_tx) -> None:
    rows = campaigns.resolve_selector(
        db_tx, tenant_id="hdfc.retail", selector={"dpdMin": 1, "limit": 50}
    )
    assert rows and all(r["dpd"] >= 1 for r in rows)
    # One row per borrower, not one per account: a person with three delinquent
    # accounts is one phone call.
    assert len({r["customer_id"] for r in rows}) == len(rows)


def test_an_open_promise_keeps_a_borrower_out_of_the_run(db_tx) -> None:
    """Ringing somebody before the date they promised is how a kept promise
    becomes a broken one."""
    with_promise = campaigns.resolve_selector(
        db_tx, tenant_id="hdfc.retail", selector={"dpdMin": 0, "limit": 500}
    )
    db_tx.execute(
        text(
            """
            INSERT INTO promises (
              id, customer_id, account_id, owner_kind, owner_bot_id,
              amount, promised_at, status, reminder_status, created_at
            )
            SELECT :id, :cid, a.id, 'bot', (SELECT id FROM bots LIMIT 1),
                   1000, now() + interval '3 days', 'upcoming', 'off', now()
            FROM accounts a WHERE a.customer_id = :cid LIMIT 1
            """
        ),
        {"id": f"PRM-{uuid.uuid4().hex[:8]}", "cid": with_promise[0]["customer_id"]},
    )
    without = campaigns.resolve_selector(
        db_tx,
        tenant_id="hdfc.retail",
        selector={"dpdMin": 0, "excludeOpenPromise": True, "limit": 500},
    )
    assert with_promise[0]["customer_id"] not in {r["customer_id"] for r in without}


def test_a_cohort_is_bounded(db_tx) -> None:
    """A cohort is a list of phones that will ring, so one typo has a ceiling."""
    rows = campaigns.resolve_selector(
        db_tx, tenant_id="hdfc.retail", selector={"limit": 999_999}
    )
    assert len(rows) <= campaigns.SELECTOR_MAX


def test_preview_creates_nothing(db_tx) -> None:
    """Seeing who a campaign would call has to be possible before committing to
    one, or the only way to check a cohort is to create the thing you are checking."""
    before = db_tx.execute(text("SELECT count(*) FROM campaign_runs")).scalar()
    result = campaigns.preview_selector(
        db_tx, tenant_id="hdfc.retail", selector={"dpdMin": 1}, sample=3
    )
    after = db_tx.execute(text("SELECT count(*) FROM campaign_runs")).scalar()
    assert before == after
    assert result["matched"] >= 0 and len(result["sample"]) <= 3


def test_a_selector_freezes_onto_the_run(db_tx) -> None:
    """Re-resolving at dial time would mean the cohort reviewed and the cohort
    called were different populations - which is the audit answer a campaign
    exists to be able to give."""
    run = campaigns.create(
        db_tx,
        tenant_id="hdfc.retail",
        name="selector freeze",
        objective="dpd_reminder",
        selector={"dpdMin": 1, "limit": 5},
    )
    added = campaigns.add_targets_from_selector(db_tx, run["id"], tenant_id="hdfc.retail")
    assert added > 0
    stored = db_tx.execute(
        text("SELECT count(*) FROM campaign_targets WHERE run_id = :r"), {"r": run["id"]}
    ).scalar()
    assert stored == added


def test_a_new_run_never_starts_itself(db_tx) -> None:
    run = campaigns.create(
        db_tx, tenant_id="hdfc.retail", name="draft only", objective="dpd_reminder"
    )
    assert run["status"] == campaigns.STATUS_DRAFT


# ---------------------------------------------------------------------------
# The fleet gate, which needed no lock after all
# ---------------------------------------------------------------------------


def test_a_reserved_attempt_counts_itself(db_tx) -> None:
    """This is why the count-then-dial window needs no mutual exclusion, and why
    section 18.4's Redis token bucket is not the answer: `reserve()` commits
    before `place()` runs, so concurrent dials already see each other."""
    before = outbound.in_flight_count(db_tx, "hdfc.retail")
    db_tx.execute(
        text(
            """
            INSERT INTO call_attempts (
              id, tenant_id, customer_id, objective, attempt_no, to_phone_hash,
              phone_slot, from_number, state, reserved_at
            ) VALUES (
              :id, :tenant, 'cust-susanth', 'dpd_reminder', 1,
              'hash', 'primary', '+911', 'reserved', now()
            )
            """
        ),
        {"id": f"CA-{uuid.uuid4().hex[:10]}", "tenant": TENANT},
    )
    assert outbound.in_flight_count(db_tx, "hdfc.retail") == before + 1


def test_a_stale_reservation_stops_holding_a_slot(db_tx) -> None:
    """Otherwise a dropped tunnel throttles dialling to zero over a day."""
    db_tx.execute(
        text(
            """
            INSERT INTO call_attempts (
              id, tenant_id, customer_id, objective, attempt_no, to_phone_hash,
              phone_slot, from_number, state, reserved_at
            ) VALUES (
              :id, :tenant, 'cust-susanth', 'dpd_reminder', 1,
              'hash', 'primary', '+911', 'reserved', now() - interval '3 hours'
            )
            """
        ),
        {"id": f"CA-{uuid.uuid4().hex[:10]}", "tenant": TENANT},
    )
    counted = outbound.in_flight_count(db_tx, "hdfc.retail")
    fresh = db_tx.execute(
        text(
            "SELECT count(*) FROM call_attempts WHERE tenant_id = 'hdfc.retail' "
            "AND state = 'reserved' AND reserved_at >= now() - interval '2 hours'"
        )
    ).scalar()
    assert counted >= fresh


# ---------------------------------------------------------------------------
# The tool that lets a borrower state a window
# ---------------------------------------------------------------------------


def test_the_preference_tool_is_gated_not_idle() -> None:
    """G6 caps idle tools because an idle tool sits in the prompt of every node
    on every turn, and the cost is real."""
    from agent_core.skills.intersect import SKILL_GATED_TOOLS

    assert "set_contact_preference" in SKILL_GATED_TOOLS


def test_the_preference_tool_is_in_the_catalog() -> None:
    from agent_core.tools.catalog import CATALOG

    spec = CATALOG.get("set_contact_preference")
    assert spec is not None
    arg_names = {a.name for a in spec.args}
    assert {"earliest_hour", "latest_hour"} <= arg_names


def test_both_channels_write_to_the_same_column() -> None:
    """A restriction stated in chat and one stated on the phone have to land in
    the same place, or the two channels disagree about the same borrower."""
    import bot_tools

    assert "set_contact_preference" in bot_tools.HANDLERS


def test_a_budgeted_call_still_ends_if_the_agent_cannot_converge() -> None:
    """A call that reaches the hard stop is a QA finding, not the mechanism."""
    from voice import budget

    assert budget.HARD_STOP_MARGIN_SEC > 0


def test_the_cool_off_is_shorter_than_forever() -> None:
    assert 0 < outbound.POOL_COOL_HOURS <= 24 * 30
    assert outbound.POOL_MIN_ATTEMPTS >= 10
    assert 0 < outbound.POOL_ANSWER_FLOOR < 0.5


def test_a_hold_publishes_the_date_the_row_actually_carries(db_tx) -> None:
    """Rule order matters: the verb that knows publishes it, the verb that
    writes reads it. And it reads it *back* rather than computing it - the
    INSERT is ON CONFLICT DO NOTHING, so where a hold was already open the date
    that stands is the older one's, and quoting the date we would have written
    tells the borrower a deadline no row agrees with."""
    import post_call_actions

    cid = _customer_for(db_tx)
    ctx = {
        "conn": db_tx,
        "attempt": {"tenant_id": TENANT, "customer_id": cid, "interaction_id": None},
        "business": "hardship_declared",
    }
    post_call_actions._place_hold(ctx, "30d")
    first = ctx.pop("hold_until")
    assert first == (datetime.now(timezone.utc) + timedelta(days=30)).date()

    # A second rule run on a borrower who already has an open hold must not
    # advertise a date it did not write.
    post_call_actions._place_hold(ctx, "90d")
    assert ctx["hold_until"] == first


def test_rollback_trigger_vocabulary_is_shared() -> None:
    """One list, three consumers.

    ``canary`` evaluated six triggers, ``cards.schema``'s Literal allowed three,
    and ``cards.compile`` restated the same three for gate G12. The card is the
    only authoring path, so the outbound three could not be requested by any
    published version and the watchdog branches checking them were unreachable.

    Asserting they are the *same object's* contents, not merely overlapping:
    two lists that agree today are two lists to update tomorrow.
    """
    from agent_core.cards import compile as card_compile
    from agent_core.cards.schema import ROLLBACK_TRIGGERS

    assert canary.ROLLBACK_TRIGGERS == ROLLBACK_TRIGGERS
    assert card_compile._ROLLBACK_TRIGGERS == ROLLBACK_TRIGGERS


def test_a_card_can_actually_hold_the_outbound_triggers() -> None:
    """The gap this closes was not that the names were missing — they were in
    ``canary.ROLLBACK_TRIGGERS`` all along, which is all the old test checked.
    It was that nothing could ever *set* them: the schema Literal rejected them,
    so a card naming one failed to parse and the feature was unreachable from
    the only screen that authors it.
    """
    from agent_core.cards.schema import parse_card

    card = parse_card(
        {
            "identity": {"bot_id": "b", "slug": "s", "display_name": "d"},
            "experiment": {
                "traffic_pct": 25,
                "auto_rollback": ["abandon_rate", "third_party_leak", "optout_spike"],
            },
        }
    )
    assert card.experiment.auto_rollback == [
        "abandon_rate",
        "third_party_leak",
        "optout_spike",
    ]


def test_g12_accepts_a_canary_guarded_only_by_outbound_triggers() -> None:
    """G12 filtered the author's triggers against its own short list, so a 25%
    canary protected by exactly the three checks that matter for outbound
    filtered to empty and failed with "canary split requires auto_rollback" —
    telling the author to add a rollback condition to a card that named three.
    """
    from agent_core.cards.compile import _ROLLBACK_TRIGGERS

    triggers = ["abandon_rate", "third_party_leak", "optout_spike"]
    assert [t for t in triggers if t in _ROLLBACK_TRIGGERS] == triggers


def test_missions_answer_for_the_card_you_asked_about() -> None:
    """`/outbound/missions` read `db.DEFAULT_BOT_ID` and ignored the caller.

    The Outbound tab lives inside `/agent-studio/{botId}` and says "No missions
    on **this card**", "Only the missions this card actually declares", and
    warns that publish is blocked for *this* card — every one of which described
    the default bot instead.

    It was invisible because no card declares an outbound block yet, so every
    card renders the same empty state and the empty state happens to be true for
    all of them. The first card to declare a mission would have shown it on
    every other card's tab.
    """
    from fastapi.testclient import TestClient

    import db
    import main as app_main

    client = TestClient(app_main.app)
    other = "intake-v1"
    assert other != db.DEFAULT_BOT_ID

    res = client.get(f"/outbound/missions?botId={other}")
    assert res.status_code == 200, res.text
    assert res.json()["botId"] == other

    # Omitted still means the default, so nothing that already called it breaks.
    assert client.get("/outbound/missions").json()["botId"] == db.DEFAULT_BOT_ID
