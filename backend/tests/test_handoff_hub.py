"""Handoff Hub: the follow-up desk for calls handed to a person.

Claim, ownership, the case's lifecycle against the call's, wrap-up evidence,
disclosures, and what the transfer hook records."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import acting_as

import actor_context
import authz
import db

AGENT = "sara-khan"
OTHER = "arjun-mehta"
ADMIN = "priya-nair"


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setenv("VISIBILITY_ENFORCE", "1")
    authz.invalidate_permission_cache()
    yield
    authz.invalidate_permission_cache()


@pytest.fixture
def as_actor():
    tokens = []

    def _use(user_id: str):
        tokens.append(actor_context.set_actor_user_id(user_id))

    yield _use
    for token in reversed(tokens):
        actor_context.reset_actor_user_id(token)


def _seed_unclaimed(conn, *, team: str = "card-collections", suffix: str = "a") -> tuple[str, str, str]:
    cust = conn.execute(text("SELECT id FROM customers ORDER BY id LIMIT 1")).scalar()
    acct = conn.execute(
        text("SELECT id FROM accounts WHERE customer_id = :c ORDER BY id LIMIT 1"),
        {"c": cust},
    ).scalar()
    if not cust or not acct:
        pytest.skip("no customers")
    ix = f"IX-HO-{suffix}"
    ho = f"HO-{suffix}"
    conn.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, account_id, channel, direction, status,
              handler_kind, handler_bot_id, started_at, created_at, updated_at
            ) VALUES (
              :id, :tenant, :cid, :aid, 'voice', 'inbound', 'active',
              'bot', :bot, now(), now(), now()
            )
            """
        ),
        {
            "id": ix,
            "tenant": db.current_tenant(),
            "cid": cust,
            "aid": acct,
            "bot": db.DEFAULT_BOT_ID,
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO interaction_handoffs (
              id, interaction_id, from_kind, from_bot_id, to_kind, to_team_id,
              reason, queue, requested_at, created_at
            ) VALUES (
              :id, :iid, 'bot', :bot, 'human', :team,
              'dispute', 'Card Collections', now(), now()
            )
            """
        ),
        {"id": ho, "iid": ix, "bot": db.DEFAULT_BOT_ID, "team": team},
    )
    conn.execute(
        text(
            """
            INSERT INTO interaction_transcript (
              id, interaction_id, turn_index, speaker, at_sec, text, sentiment_delta
            ) VALUES (
              :id, :iid, 0, 'customer', 4, 'I already paid', -0.4
            )
            """
        ),
        {"id": f"T-{suffix}", "iid": ix},
    )
    return ix, str(cust), str(acct)


def test_the_queue_offers_my_open_case_to_resume(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="mine")
    as_actor(AGENT)
    assert db.list_handoff_queue()["activeInteractionId"] is None
    db.claim_handoff(ix)
    assert db.list_handoff_queue()["activeInteractionId"] == ix


def test_queue_scoped_to_actor_team(db_tx, as_actor) -> None:
    _seed_unclaimed(db_tx, team="card-collections", suffix="card")
    _seed_unclaimed(db_tx, team="retail-collections", suffix="ret")
    as_actor(AGENT)
    queue = db.list_handoff_queue()
    ids = {item["interactionId"] for item in queue["items"]}
    assert "IX-HO-card" in ids
    assert "IX-HO-ret" not in ids


def test_admin_sees_all_unclaimed(db_tx, as_actor) -> None:
    _seed_unclaimed(db_tx, team="retail-collections", suffix="adm")
    as_actor(ADMIN)
    queue = db.list_handoff_queue()
    ids = {item["interactionId"] for item in queue["items"]}
    assert "IX-HO-adm" in ids


def test_claim_then_second_caller_conflicts(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="race")
    as_actor(AGENT)
    session = db.claim_handoff(ix)
    assert session["claimed"] is True
    assert session["activeCall"]["escalationReason"] == "dispute"
    assert session["status"] == "active"
    as_actor(OTHER)
    with pytest.raises(ValueError, match="handoff_already_claimed"):
        db.claim_handoff(ix)


def test_snapshot_uses_handoff_reason_not_disposition(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="reason")
    db_tx.execute(
        text("UPDATE interactions SET disposition = 'escalated' WHERE id = :id"),
        {"id": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    session = db.get_handoff_session(ix)
    assert session["activeCall"]["escalationReason"] == "dispute"
    assert session["transcriptScript"][0]["text"] == "I already paid"
    assert session["sentimentSeries"]


def test_non_assignee_cannot_read_claimed_session(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="forbid")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.get_handoff_session(ix)


def test_supervisor_can_monitor_claimed_session(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="mon")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(ADMIN)
    session = db.get_handoff_session(ix)
    assert session["monitor"] is True
    assert session["claimed"] is True
    assert session["interactionId"] == ix


def test_wrap_up_completes_handoff_row(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="wrap")
    as_actor(AGENT)
    db.claim_handoff(ix)
    result = db.wrap_up_interaction(ix, {"disposition": "Info provided", "notes": "explained the charge"})
    assert result["id"] == ix
    row = db_tx.execute(
        text(
            """
            SELECT i.status, i.disposition, h.completed_at
            FROM interactions i
            JOIN interaction_handoffs h ON h.interaction_id = i.id
            WHERE i.id = :id
            """
        ),
        {"id": ix},
    ).mappings().one()
    # No call is live on it, so the wrap-up closes the interaction too.
    assert row["status"] == "completed"
    assert row["disposition"] == "Info provided"
    assert row["completed_at"] is not None


def test_disclosure_write_and_identity_lock(db_tx, as_actor) -> None:
    ix, cust, _acct = _seed_unclaimed(db_tx, suffix="disc")
    as_actor(AGENT)
    db.claim_handoff(ix)
    session = db.record_handoff_disclosure(
        ix, {"itemId": "rule-recording", "ruleId": "rule-recording", "label": "Recording disclosure read"}
    )
    rec = next(i for i in session["complianceItems"] if i["ruleId"] == "rule-recording")
    assert rec["checked"] is True
    db.record_handoff_disclosure(ix, {"itemId": "identity", "ruleId": "rule-identity"})
    with pytest.raises(ValueError, match="identity_locked"):
        db.record_handoff_disclosure(ix, {"itemId": "identity", "ruleId": "rule-identity"})


def test_suggestion_accept(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="sug")
    db_tx.execute(
        text(
            """
            INSERT INTO ai_response_suggestions (id, interaction_id, suggestion_text, source)
            VALUES ('sug-ho', :iid, 'Offer a PTP today', 'playbook')
            """
        ),
        {"iid": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    session = db.accept_handoff_suggestion(ix, "sug-ho")
    hit = next(s for s in session["suggestions"] if s["id"] == "sug-ho")
    assert hit["accepted"] is True


def test_cross_tenant_handoff_is_not_found(db_tx, as_actor) -> None:
    as_actor(ADMIN)
    with acting_as(db_tx, 'rival.bank'):
        db_tx.execute(text("INSERT INTO tenants (id, name) VALUES ('rival.bank', 'Rival')"))
        db_tx.execute(
            text("INSERT INTO users (id, tenant_id, name) VALUES ('rv-user', 'rival.bank', 'Rival')")
        )
        db_tx.execute(
            text(
                "INSERT INTO products (id, tenant_id, name, type, is_active)"
                " VALUES ('rv-prod', 'rival.bank', 'Rival Card', 'card', true)"
            )
        )
        db_tx.execute(
            text(
                "INSERT INTO customers (id, tenant_id, name, risk)"
                " VALUES ('rv-cust', 'rival.bank', 'Rival Customer', 'low')"
            )
        )
        db_tx.execute(
            text(
                "INSERT INTO accounts (id, customer_id, product_id, status)"
                " VALUES ('rv-acct', 'rv-cust', 'rv-prod', 'active')"
            )
        )
        db_tx.execute(
            text(
                """
                INSERT INTO interactions (
                  id, tenant_id, customer_id, account_id, handler_kind, handler_user_id,
                  channel, status
                ) VALUES (
                  'rv-ix', 'rival.bank', 'rv-cust', 'rv-acct', 'human', 'rv-user',
                  'voice', 'active'
                )
                """
            )
        )
        db_tx.execute(
            text(
                """
                INSERT INTO interaction_handoffs (
                  id, interaction_id, from_kind, from_bot_id, to_kind, reason, requested_at
                ) VALUES (
                  'rv-ho', 'rv-ix', 'bot', :bot, 'human', 'dispute', now()
                )
                """
            ),
            {"bot": db.DEFAULT_BOT_ID},
        )
    with pytest.raises(KeyError):
        db.get_handoff_session("rv-ix")
    with pytest.raises(KeyError):
        db.claim_handoff("rv-ix")


# --- the case outlives the call ---------------------------------------------


def _handoff_row(conn, ix):
    return conn.execute(
        text(
            "SELECT to_team_id, queue, transfer_outcome, completed_at FROM interaction_handoffs "
            "WHERE interaction_id = :ix AND to_kind = 'human' ORDER BY created_at"
        ),
        {"ix": ix},
    ).mappings().all()


def test_the_call_ending_leaves_the_escalation_on_the_hub(db_tx, as_actor) -> None:
    import voice_studio

    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="end")
    assert voice_studio.call_ended_disposition(ix, "ptp_captured") == "escalated"
    db_tx.execute(text("UPDATE interactions SET status = 'completed' WHERE id = :ix"), {"ix": ix})
    assert _handoff_row(db_tx, ix)[0]["completed_at"] is None
    as_actor(AGENT)
    assert ix in {i["interactionId"] for i in db.list_handoff_queue()["items"]}


def test_the_call_ending_keeps_a_wrap_up_already_saved(db_tx, as_actor) -> None:
    import voice_studio

    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="kept")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, {"disposition": "Info provided", "notes": "explained the charge"})
    assert voice_studio.call_ended_disposition(ix, "escalated") == "Info provided"


def test_the_call_ending_closes_a_supervisors_takeover(db_tx) -> None:
    import voice_studio

    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="barge")
    db_tx.execute(text("UPDATE interaction_handoffs SET queue = 'Supervisor barge' WHERE interaction_id = :ix"), {"ix": ix})
    voice_studio.call_ended_disposition(ix, None)
    assert _handoff_row(db_tx, ix)[0]["completed_at"] is not None


def test_a_wrap_up_on_a_live_call_leaves_the_call_to_the_engine(db_tx, as_actor, monkeypatch) -> None:
    import voice_studio_supervision

    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="live")
    monkeypatch.setattr(voice_studio_supervision, "live_run", lambda conn, iid: "77")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, {"disposition": "Info provided", "notes": "explained the charge"})
    status = db_tx.execute(text("SELECT status FROM interactions WHERE id = :ix"), {"ix": ix}).scalar()
    assert status == "active"
    assert _handoff_row(db_tx, ix)[0]["completed_at"] is not None


def test_the_queue_ignores_bot_to_bot_hops(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="hop")
    db_tx.execute(
        text("UPDATE interaction_handoffs SET to_kind = 'bot', reason = 'specialist_route' WHERE interaction_id = :ix"),
        {"ix": ix},
    )
    as_actor(ADMIN)
    assert ix not in {i["interactionId"] for i in db.list_handoff_queue()["items"]}


# --- what the transfer hook records -----------------------------------------


def test_a_repeated_transfer_files_one_handoff(db_tx) -> None:
    from voice import persist

    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="dup")
    db_tx.execute(text("DELETE FROM interaction_handoffs WHERE interaction_id = :ix"), {"ix": ix})
    first = persist.record_handoff(interaction_id=ix, reason="dispute", transfer_outcome="callback_line")
    again = persist.record_handoff(interaction_id=ix, reason="dispute", transfer_outcome="callback_line")
    assert first == again
    assert len(_handoff_row(db_tx, ix)) == 1


def test_a_handoff_goes_to_the_team_of_the_customers_agent(db_tx) -> None:
    from voice import persist

    ix, cust, _acct = _seed_unclaimed(db_tx, suffix="team")
    db_tx.execute(text("DELETE FROM interaction_handoffs WHERE interaction_id = :ix"), {"ix": ix})
    team = db_tx.execute(text("SELECT team_id FROM users WHERE id = :u"), {"u": OTHER}).scalar()
    db_tx.execute(text("UPDATE customers SET assigned_user_id = :u WHERE id = :c"), {"u": OTHER, "c": cust})
    persist.record_handoff(interaction_id=ix, reason="dispute")
    assert _handoff_row(db_tx, ix)[0]["to_team_id"] == team


def test_an_unowned_customers_handoff_goes_to_the_whole_queue(db_tx) -> None:
    from voice import persist

    ix, cust, _acct = _seed_unclaimed(db_tx, suffix="pool")
    db_tx.execute(text("DELETE FROM interaction_handoffs WHERE interaction_id = :ix"), {"ix": ix})
    db_tx.execute(text("UPDATE customers SET assigned_user_id = NULL WHERE id = :c"), {"c": cust})
    persist.record_handoff(interaction_id=ix, reason="dispute")
    row = _handoff_row(db_tx, ix)[0]
    assert row["to_team_id"] is None and row["queue"] is None


@pytest.mark.parametrize(("number", "outcome"), [("+919800000000", "callback_line"), ("", "no_one_available")])
def test_the_transfer_hook_records_whether_anyone_could_take_the_caller(monkeypatch, number, outcome) -> None:
    import contextlib

    import voice_studio
    from voice import persist

    seen: dict = {}
    monkeypatch.setenv("SUPERVISOR_CALLBACK_PHONE", number)
    monkeypatch.setattr(voice_studio, "_as_agent", lambda ctx: contextlib.nullcontext())
    monkeypatch.setattr(voice_studio, "_interaction", lambda ctx: "IX-hook")
    monkeypatch.setattr(voice_studio, "_ctx_bot_id", lambda ctx: None)
    monkeypatch.setattr(persist, "record_handoff", lambda **kw: seen.update(kw) or "HO-1")
    out = voice_studio.transfer_destination({"workflow_run_id": 9, "channel": "voice", "direction": "inbound"})
    assert seen["transfer_outcome"] == outcome
    assert bool(out["transfer_context"]["destination"]) == bool(number)


# --- wrap-up: the owner, and evidence for the outcome --------------------------


def test_only_the_cases_holder_may_wrap_it_up(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="own")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.wrap_up_interaction(ix, {"disposition": "Info provided", "notes": "x"})


@pytest.mark.parametrize(
    ("outcome", "need"),
    [
        ("PTP captured", "promise"),
        ("Callback scheduled", "callback"),
        ("Dispute - under review", "dispute"),
        ("Customer says they paid", "notes"),
        ("Info provided", "notes"),
        ("Unresolved - retry", "notes"),
    ],
)
def test_an_outcome_is_refused_without_what_it_claims(db_tx, as_actor, outcome, need) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix=f"need-{need}-{len(outcome)}")
    as_actor(AGENT)
    db.claim_handoff(ix)
    with pytest.raises(ValueError, match=f"disposition_needs:{need}"):
        db.wrap_up_interaction(ix, {"disposition": outcome, "notes": "   "})


def test_an_outcome_outside_the_catalogue_is_refused(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="unknown")
    as_actor(AGENT)
    db.claim_handoff(ix)
    with pytest.raises(ValueError, match="unknown_disposition"):
        db.wrap_up_interaction(ix, {"disposition": "Escalated to supervisor", "notes": "x"})


def test_a_ptp_wrap_up_files_its_promise_on_the_calls_channel(db_tx, as_actor) -> None:
    ix, cust, acct = _seed_unclaimed(db_tx, suffix="ptp")
    db_tx.execute(text("UPDATE interactions SET channel = 'whatsapp' WHERE id = :ix"), {"ix": ix})
    # One open promise per loan: clear the seeded one so this wrap-up may file.
    db_tx.execute(
        text("UPDATE promises SET status = 'broken' WHERE account_id = :a AND status IN ('upcoming', 'due_today')"),
        {"a": acct},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    out = db.wrap_up_interaction(
        ix,
        {
            "disposition": "PTP captured",
            "promise": {"customerId": cust, "amount": 1500, "promisedDate": "2030-01-15", "channel": "voice"},
        },
    )
    assert out["spawned"]["promise"]
    channel = db_tx.execute(text("SELECT channel FROM promises WHERE interaction_id = :ix"), {"ix": ix}).scalar()
    assert channel == "whatsapp"


# --- what the case shows -----------------------------------------------------


def test_an_unreadable_policy_is_unavailable_not_empty(db_tx, as_actor, monkeypatch) -> None:
    from agent_core.authority import policy

    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="pol")

    def _boom(*_a, **_k):
        raise RuntimeError("policy store down")

    monkeypatch.setattr(policy, "snapshot", _boom)
    as_actor(AGENT)
    session = db.claim_handoff(ix)
    assert session["customerContext"]["authorityPolicy"] is None


def test_the_case_has_no_invented_consent(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="consent")
    as_actor(AGENT)
    session = db.claim_handoff(ix)
    assert "dnd" not in session["customerContext"]
    assert "liveQa" not in session["customerContext"]


def test_a_disclosure_records_when_in_the_call_it_was_read(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="offset")
    db_tx.execute(text("UPDATE interactions SET started_at = now() - interval '90 seconds' WHERE id = :ix"), {"ix": ix})
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.record_handoff_disclosure(ix, {"itemId": "rule-recording", "ruleId": "rule-recording"})
    at = db_tx.execute(
        text("SELECT read_at_sec FROM interaction_disclosures WHERE interaction_id = :ix AND rule_id = 'rule-recording'"),
        {"ix": ix},
    ).scalar()
    assert at == 90


def test_the_copilot_opens_for_the_holder_and_not_a_stranger(db_tx, as_actor) -> None:
    ix, _cust, _acct = _seed_unclaimed(db_tx, suffix="cop")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.assert_handoff_readable(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.assert_handoff_readable(ix)
