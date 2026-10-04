"""Handoff Hub: the follow-up desk for calls handed to a person.

Claim and takeover, the case's lifecycle against the call's, wrap-up
authority and evidence, disclosures, the caseload, and what the transfer hook
and the end of the call record. Every row a test reads is made here: no
seeded staff, bot or customer."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.conftest import acting_as

import actor_context
import authz
import db

TEAM = "hub-team-cards"
OTHER_TEAM = "hub-team-retail"
AGENT = "hub-agent"
OTHER = "hub-other"
SUP = "hub-sup"
ADMIN = "hub-admin"
BOT = "hub-bot"
CUST = "hub-cust"
ACCT = "hub-acct"


@pytest.fixture(autouse=True)
def _enforce(monkeypatch):
    monkeypatch.setenv("VISIBILITY_ENFORCE", "1")
    authz.invalidate_permission_cache()
    yield
    authz.invalidate_permission_cache()


@pytest.fixture
def hub(db_tx):
    """Two teams, an agent in each, the cards team's supervisor, an admin, a
    bot, and one customer with one loan -- all synthetic, all this test's."""
    t = db.current_tenant()
    for tid, name in ((TEAM, "Hub Cards"), (OTHER_TEAM, "Hub Retail")):
        db_tx.execute(text("INSERT INTO teams (id, tenant_id, name) VALUES (:id, :t, :n)"), {"id": tid, "t": t, "n": name})
    for role in ("agent", "supervisor", "admin"):
        db_tx.execute(
            text("INSERT INTO roles (id, tenant_id, name) VALUES (:id, :t, :n)"),
            {"id": f"hub-role-{role}", "t": t, "n": role},
        )
    for uid, team, role in (
        (AGENT, TEAM, "agent"),
        (OTHER, OTHER_TEAM, "agent"),
        (SUP, TEAM, "supervisor"),
        (ADMIN, None, "admin"),
    ):
        db_tx.execute(
            text("INSERT INTO users (id, tenant_id, team_id, name) VALUES (:id, :t, :team, :id)"),
            {"id": uid, "t": t, "team": team},
        )
        db_tx.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (:u, :r)"),
            {"u": uid, "r": f"hub-role-{role}"},
        )
    db_tx.execute(text("UPDATE teams SET supervisor_user_id = :s WHERE id = :t"), {"s": SUP, "t": TEAM})
    db_tx.execute(text("INSERT INTO bots (id, tenant_id, name, version) VALUES (:id, :t, 'Kaia', '1')"), {"id": BOT, "t": t})
    # The Hub's checklist cites these rules; a fresh tenant may not have them.
    for rule_id, code, label in (
        ("rule-recording", "recording", "Recording disclosure"),
        ("rule-identity", "identity", "Identity verified"),
        ("r-rec", "RBI-DISC-01", "Missed call recording notice"),
    ):
        db_tx.execute(
            text(
                "INSERT INTO compliance_rules (id, tenant_id, code, label) VALUES (:id, :t, :code, :label) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": rule_id, "t": t, "code": code, "label": label},
        )
    db_tx.execute(
        text("INSERT INTO products (id, tenant_id, name, type, is_active) VALUES ('hub-prod', :t, 'Hub Card', 'card', true)"),
        {"t": t},
    )
    db_tx.execute(
        text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, 'Synthetic Borrower', 'medium')"),
        {"id": CUST, "t": t},
    )
    db_tx.execute(
        text("INSERT INTO accounts (id, customer_id, product_id, status, outstanding) VALUES (:id, :c, 'hub-prod', 'active', 5000)"),
        {"id": ACCT, "c": CUST},
    )
    authz.invalidate_permission_cache()
    return db_tx


@pytest.fixture
def as_actor():
    tokens = []

    def _use(user_id: str):
        tokens.append(actor_context.set_actor_user_id(user_id))

    yield _use
    for token in reversed(tokens):
        actor_context.reset_actor_user_id(token)


def _case(conn, *, suffix: str, team: str | None = TEAM, channel: str = "voice", name: str | None = None) -> str:
    """A bot call handed to a person, waiting on the Hub."""
    ix = f"IX-HO-{suffix}"
    cust = CUST
    if name:
        cust = f"hub-cust-{suffix}"
        conn.execute(
            text("INSERT INTO customers (id, tenant_id, name, risk) VALUES (:id, :t, :n, 'low')"),
            {"id": cust, "t": db.current_tenant(), "n": name},
        )
    conn.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, account_id, channel, direction, status,
              handler_kind, handler_bot_id, started_at, created_at, updated_at
            ) VALUES (
              :id, :tenant, :cid, :aid, :ch, 'inbound', 'active', 'bot', :bot, now(), now(), now()
            )
            """
        ),
        {"id": ix, "tenant": db.current_tenant(), "cid": cust, "aid": ACCT if cust == CUST else None, "ch": channel, "bot": BOT},
    )
    conn.execute(
        text(
            """
            INSERT INTO interaction_handoffs (
              id, interaction_id, from_kind, from_bot_id, to_kind, to_team_id,
              reason, queue, requested_at, created_at
            ) VALUES (:id, :iid, 'bot', :bot, 'human', :team, 'dispute', 'Hub Cards', now(), now())
            """
        ),
        {"id": f"HO-{suffix}", "iid": ix, "bot": BOT, "team": team},
    )
    conn.execute(
        text(
            "INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, at_sec, text, sentiment_delta) "
            "VALUES (:id, :iid, 0, 'customer', 4, 'I already paid', -0.4)"
        ),
        {"id": f"T-{suffix}", "iid": ix},
    )
    return ix


def _handoffs(conn, ix):
    return conn.execute(
        text(
            "SELECT id, to_user_id, to_team_id, queue, transfer_outcome, completed_at, wrap_up_notes "
            "FROM interaction_handoffs WHERE interaction_id = :ix AND to_kind = 'human' ORDER BY created_at"
        ),
        {"ix": ix},
    ).mappings().all()


def _interaction(conn, ix):
    return conn.execute(
        text("SELECT status, disposition, summary, handler_user_id FROM interactions WHERE id = :ix"), {"ix": ix}
    ).mappings().one()


INFO = {"disposition": "Info provided", "notes": "explained the charge"}


# --- the queue and the caseload ---------------------------------------------


def test_the_caseload_lists_every_open_case_the_agent_holds(hub, as_actor) -> None:
    first, second = _case(hub, suffix="one"), _case(hub, suffix="two")
    as_actor(AGENT)
    assert db.list_handoff_queue()["mine"] == []
    db.claim_handoff(first)
    db.claim_handoff(second)
    queue = db.list_handoff_queue()
    assert {c["interactionId"] for c in queue["mine"]} == {first, second}
    assert not {first, second} & {i["interactionId"] for i in queue["items"]}


def test_queue_scoped_to_actor_team(hub, as_actor) -> None:
    mine, theirs = _case(hub, suffix="card"), _case(hub, suffix="ret", team=OTHER_TEAM)
    as_actor(AGENT)
    ids = {item["interactionId"] for item in db.list_handoff_queue()["items"]}
    assert mine in ids and theirs not in ids


def test_admin_sees_all_unclaimed(hub, as_actor) -> None:
    ix = _case(hub, suffix="adm", team=OTHER_TEAM)
    as_actor(ADMIN)
    assert ix in {item["interactionId"] for item in db.list_handoff_queue()["items"]}


def test_the_queue_searches_names_and_accounts_literally(hub, as_actor) -> None:
    named = _case(hub, suffix="zeph", name="Zephyrine Quillfeather")
    percent = _case(hub, suffix="pct", name="Xylo 100% Quillfeather")
    on_loan = _case(hub, suffix="loan")
    as_actor(ADMIN)
    assert [i["interactionId"] for i in db.list_handoff_queue(search="zephyrine")["items"]] == [named]
    assert [i["interactionId"] for i in db.list_handoff_queue(search="100%")["items"]] == [percent]
    assert {i["interactionId"] for i in db.list_handoff_queue(search="quillfeather")["items"]} == {named, percent}
    assert on_loan in {i["interactionId"] for i in db.list_handoff_queue(search=ACCT)["items"]}


def test_the_queue_ignores_bot_to_bot_hops(hub, as_actor) -> None:
    ix = _case(hub, suffix="hop")
    hub.execute(
        text("UPDATE interaction_handoffs SET to_kind = 'bot', reason = 'specialist_route' WHERE interaction_id = :ix"),
        {"ix": ix},
    )
    as_actor(ADMIN)
    assert ix not in {i["interactionId"] for i in db.list_handoff_queue()["items"]}


def test_floor_counts_only_handoffs_to_people(hub, as_actor) -> None:
    import db_floor

    as_actor(ADMIN)
    before = db_floor.get_floor_snapshot()["stats"]["queueDepth"]
    ix = _case(hub, suffix="floorhop")
    hub.execute(
        text("UPDATE interaction_handoffs SET to_kind = 'bot', reason = 'specialist_route' WHERE interaction_id = :ix"),
        {"ix": ix},
    )
    assert db_floor.get_floor_snapshot()["stats"]["queueDepth"] == before


# --- claim, reading, takeover ------------------------------------------------


def test_claim_then_second_caller_conflicts(hub, as_actor) -> None:
    ix = _case(hub, suffix="race")
    as_actor(AGENT)
    session = db.claim_handoff(ix)
    assert session["claimed"] is True and session["status"] == "active"
    assert session["activeCall"]["escalationReason"] == "dispute"
    as_actor(OTHER)
    with pytest.raises(ValueError, match="handoff_already_claimed"):
        db.claim_handoff(ix)


def test_snapshot_uses_handoff_reason_not_disposition(hub, as_actor) -> None:
    ix = _case(hub, suffix="reason")
    hub.execute(text("UPDATE interactions SET disposition = 'escalated' WHERE id = :id"), {"id": ix})
    as_actor(AGENT)
    session = db.claim_handoff(ix)
    assert session["activeCall"]["escalationReason"] == "dispute"
    assert session["transcriptScript"][0]["text"] == "I already paid"
    assert session["sentimentSeries"]


def test_non_assignee_cannot_read_claimed_session(hub, as_actor) -> None:
    ix = _case(hub, suffix="forbid")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.get_handoff_session(ix)


def test_supervisor_can_monitor_claimed_session(hub, as_actor) -> None:
    ix = _case(hub, suffix="mon")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(SUP)
    session = db.get_handoff_session(ix)
    assert session["monitor"] is True and session["claimed"] is True
    assert session["activeCall"]["handlerUserId"] == AGENT


def _thread(conn, ix, holder):
    conn.execute(
        text(
            "INSERT INTO conversations (id, interaction_id, customer_id, status, channel, assigned_user_id) "
            "VALUES (:id, :ix, :c, 'assigned', 'whatsapp', :u)"
        ),
        {"id": f"CV-{ix}", "ix": ix, "c": CUST, "u": holder},
    )
    return f"CV-{ix}"


def test_a_supervisors_takeover_moves_the_case_the_call_and_the_thread(hub, as_actor) -> None:
    ix = _case(hub, suffix="take", channel="whatsapp")
    as_actor(AGENT)
    db.claim_handoff(ix)
    cv = _thread(hub, ix, AGENT)
    as_actor(SUP)
    session = db.claim_handoff(ix, {"expectedAssigneeId": AGENT})
    assert session["monitor"] is False and session["activeCall"]["handlerUserId"] == SUP
    assert _handoffs(hub, ix)[0]["to_user_id"] == SUP
    assert _interaction(hub, ix)["handler_user_id"] == SUP
    held = hub.execute(text("SELECT assigned_user_id FROM conversations WHERE id = :cv"), {"cv": cv}).scalar()
    assert held == SUP


def test_a_takeover_is_refused_when_the_holder_changed(hub, as_actor) -> None:
    ix = _case(hub, suffix="moved")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(SUP)
    with pytest.raises(ValueError, match="handoff_owner_changed"):
        db.claim_handoff(ix, {"expectedAssigneeId": OTHER})
    assert _handoffs(hub, ix)[0]["to_user_id"] == AGENT


def test_only_a_supervisor_takes_over_a_colleagues_case(hub, as_actor) -> None:
    ix = _case(hub, suffix="peer")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="reassign_requires_supervisor"):
        db.claim_handoff(ix, {"expectedAssigneeId": AGENT})


def test_barging_a_live_call_leaves_the_case_with_its_holder(hub, as_actor, monkeypatch) -> None:
    import db_floor
    import voice_studio_supervision

    monkeypatch.setattr(voice_studio_supervision, "live_run", lambda conn, iid: "77")
    ix = _case(hub, suffix="barge")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(SUP)
    db_floor.create_supervisor_action({"interactionId": ix, "action": "barge"})
    cases = _handoffs(hub, ix)
    assert cases[0]["to_user_id"] == AGENT  # the case
    assert [c["queue"] for c in cases[1:]] == ["Supervisor barge"]
    assert db.get_handoff_session(ix)["handoffId"] == cases[0]["id"]


def test_barging_with_no_call_takes_the_case_and_its_thread(hub, as_actor, monkeypatch) -> None:
    import db_floor
    import voice_studio_supervision

    monkeypatch.setattr(voice_studio_supervision, "live_run", lambda conn, iid: None)
    ix = _case(hub, suffix="bargechat", channel="whatsapp")
    as_actor(AGENT)
    db.claim_handoff(ix)
    cv = _thread(hub, ix, AGENT)
    as_actor(SUP)
    db_floor.create_supervisor_action({"interactionId": ix, "action": "barge"})
    cases = _handoffs(hub, ix)
    assert len(cases) == 1 and cases[0]["to_user_id"] == SUP
    assert hub.execute(text("SELECT assigned_user_id FROM conversations WHERE id = :cv"), {"cv": cv}).scalar() == SUP


def test_barging_with_no_call_and_no_open_case_is_refused(hub, as_actor, monkeypatch) -> None:
    """No call to join and no case to take: a barge row would never be closed."""
    import db_floor
    import voice_studio_supervision

    monkeypatch.setattr(voice_studio_supervision, "live_run", lambda conn, iid: None)
    ix = _case(hub, suffix="bargenone")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, INFO)
    as_actor(SUP)
    with pytest.raises(ValueError, match="nothing_to_take_over"):
        db_floor.create_supervisor_action({"interactionId": ix, "action": "barge"})
    assert len(_handoffs(hub, ix)) == 1
    assert _interaction(hub, ix)["handler_user_id"] == AGENT
    assert hub.execute(text("SELECT count(*) FROM supervisor_actions WHERE interaction_id = :ix"), {"ix": ix}).scalar() == 0


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import main as app_main

    monkeypatch.setenv("API_KEY", "hub-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


def test_a_refused_floor_takeover_is_a_conflict_not_a_server_error(hub, as_actor, client, monkeypatch) -> None:
    import voice_studio_supervision

    monkeypatch.setattr(voice_studio_supervision, "live_run", lambda conn, iid: None)
    ix = _case(hub, suffix="bargehttp")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, INFO)
    res = client.post(
        "/supervisor-actions",
        json={"interactionId": ix, "action": "barge"},
        headers={"X-API-Key": "hub-test-key", "X-Actor-User-Id": SUP},
    )
    assert (res.status_code, res.json()["detail"]) == (409, "nothing_to_take_over")


def test_hanging_up_a_takeover_does_not_close_the_case(hub, as_actor) -> None:
    import voice_studio_supervision

    ix = _case(hub, suffix="hangup")
    as_actor(SUP)
    db.claim_handoff(ix)
    hub.execute(
        text(
            "INSERT INTO supervisor_actions (id, interaction_id, supervisor_user_id, action, target_bot_id, created_at) "
            "VALUES ('sup-hub', :ix, :sup, 'barge', :bot, now())"
        ),
        {"ix": ix, "sup": SUP, "bot": BOT},
    )
    voice_studio_supervision.closed({"interaction_id": ix, "mode": "takeover", "actor": SUP})
    assert _handoffs(hub, ix)[0]["completed_at"] is None


def test_cross_tenant_handoff_is_not_found(hub, as_actor) -> None:
    as_actor(ADMIN)
    with acting_as(hub, "rival.bank"):
        hub.execute(text("INSERT INTO tenants (id, name) VALUES ('rival.bank', 'Rival')"))
        hub.execute(text("INSERT INTO users (id, tenant_id, name) VALUES ('rv-user', 'rival.bank', 'Rival')"))
        hub.execute(
            text("INSERT INTO products (id, tenant_id, name, type, is_active) VALUES ('rv-prod', 'rival.bank', 'Rival Card', 'card', true)")
        )
        hub.execute(text("INSERT INTO customers (id, tenant_id, name, risk) VALUES ('rv-cust', 'rival.bank', 'Rival Customer', 'low')"))
        hub.execute(text("INSERT INTO accounts (id, customer_id, product_id, status) VALUES ('rv-acct', 'rv-cust', 'rv-prod', 'active')"))
        hub.execute(
            text(
                "INSERT INTO interactions (id, tenant_id, customer_id, account_id, handler_kind, handler_user_id, channel, status) "
                "VALUES ('rv-ix', 'rival.bank', 'rv-cust', 'rv-acct', 'human', 'rv-user', 'voice', 'active')"
            )
        )
        hub.execute(
            text(
                "INSERT INTO interaction_handoffs (id, interaction_id, from_kind, to_kind, reason, requested_at) "
                "VALUES ('rv-ho', 'rv-ix', 'bot', 'human', 'dispute', now())"
            )
        )
    with pytest.raises(KeyError):
        db.get_handoff_session("rv-ix")
    with pytest.raises(KeyError):
        db.claim_handoff("rv-ix")


# --- the case outlives the call ---------------------------------------------


@pytest.fixture
def _quiet_completion(monkeypatch):
    """The scorecard pass after a call is its own concern; keep it out."""
    from agent_core.live_qa import scorecard

    monkeypatch.setattr(scorecard, "score_completed_interaction", lambda _ix: None)


def _complete(ix, *, disposition=None, transferred=False):
    from voice import persist

    persist.complete_voice_call(
        session_id=f"VS-{ix}", interaction_id=ix, disposition=disposition, transferred=transferred
    )


def test_the_call_ending_leaves_the_escalation_on_the_hub(hub, as_actor, _quiet_completion) -> None:
    ix = _case(hub, suffix="end")
    _complete(ix, disposition="ptp_captured")
    assert _interaction(hub, ix)["disposition"] == "escalated"
    assert _handoffs(hub, ix)[0]["completed_at"] is None
    as_actor(AGENT)
    assert ix in {i["interactionId"] for i in db.list_handoff_queue()["items"]}


def test_the_call_ending_keeps_the_persons_wrap_up(hub, as_actor, _quiet_completion) -> None:
    ix = _case(hub, suffix="kept")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, INFO)
    _complete(ix, disposition="escalated")
    assert _interaction(hub, ix)["disposition"] == "Info provided"
    assert _handoffs(hub, ix)[0]["wrap_up_notes"] == "explained the charge"


def test_the_call_ending_closes_a_supervisors_takeover(hub, _quiet_completion) -> None:
    ix = _case(hub, suffix="bargeend")
    hub.execute(text("UPDATE interaction_handoffs SET queue = 'Supervisor barge' WHERE interaction_id = :ix"), {"ix": ix})
    _complete(ix)
    assert _handoffs(hub, ix)[0]["completed_at"] is not None


@pytest.mark.parametrize(("transferred", "settled"), [(True, "connected"), (False, "not_connected")])
def test_the_call_ending_settles_what_the_transfer_did(hub, _quiet_completion, transferred, settled) -> None:
    ix = _case(hub, suffix=f"ring-{settled}")
    hub.execute(text("UPDATE interaction_handoffs SET transfer_outcome = 'ringing' WHERE interaction_id = :ix"), {"ix": ix})
    _complete(ix, transferred=transferred)
    assert _handoffs(hub, ix)[0]["transfer_outcome"] == settled


def test_a_wrap_up_on_a_live_call_leaves_the_call_to_the_engine(hub, as_actor, monkeypatch) -> None:
    import voice_studio_supervision

    ix = _case(hub, suffix="live")
    monkeypatch.setattr(voice_studio_supervision, "live_run", lambda conn, iid: "77")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, INFO)
    assert _interaction(hub, ix)["status"] == "active"
    assert _handoffs(hub, ix)[0]["completed_at"] is not None


# --- what the transfer hook records -----------------------------------------


def test_a_repeated_transfer_files_one_handoff(hub) -> None:
    from voice import persist

    ix = _case(hub, suffix="dup")
    hub.execute(text("DELETE FROM interaction_handoffs WHERE interaction_id = :ix"), {"ix": ix})
    first = persist.record_handoff(interaction_id=ix, reason="dispute", bot_id=BOT, transfer_outcome="ringing")
    again = persist.record_handoff(interaction_id=ix, reason="dispute", bot_id=BOT, transfer_outcome="ringing")
    assert first == again and len(_handoffs(hub, ix)) == 1


def test_a_late_transfer_retry_never_reopens_a_wrapped_case(hub, as_actor) -> None:
    from voice import persist

    ix = _case(hub, suffix="late")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, INFO)
    case_id = _handoffs(hub, ix)[0]["id"]
    assert persist.record_handoff(interaction_id=ix, reason="dispute", bot_id=BOT, transfer_outcome="ringing") == case_id
    cases = _handoffs(hub, ix)
    assert len(cases) == 1 and cases[0]["completed_at"] is not None
    assert ix not in {i["interactionId"] for i in db.list_handoff_queue()["items"]}


@pytest.mark.parametrize(
    ("rang", "transferred", "settled"),
    [("ringing", True, "connected"), ("ringing", False, "not_connected"), ("no_line", False, "no_line")],
)
def test_a_transfer_hook_after_the_call_ended_leaves_what_it_settled(
    hub, _quiet_completion, rang, transferred, settled
) -> None:
    from voice import persist

    ix = _case(hub, suffix=f"lateset-{settled}")
    hub.execute(text("UPDATE interaction_handoffs SET transfer_outcome = :o WHERE interaction_id = :ix"), {"o": rang, "ix": ix})
    _complete(ix, transferred=transferred)
    persist.record_handoff(interaction_id=ix, reason="dispute", bot_id=BOT, transfer_outcome="ringing")
    assert _handoffs(hub, ix)[0]["transfer_outcome"] == settled


def test_a_handoff_goes_to_the_team_of_the_customers_agent(hub) -> None:
    from voice import persist

    ix = _case(hub, suffix="team")
    hub.execute(text("DELETE FROM interaction_handoffs WHERE interaction_id = :ix"), {"ix": ix})
    hub.execute(text("UPDATE customers SET assigned_user_id = :u WHERE id = :c"), {"u": OTHER, "c": CUST})
    persist.record_handoff(interaction_id=ix, reason="dispute", bot_id=BOT)
    case = _handoffs(hub, ix)[0]
    assert case["to_team_id"] == OTHER_TEAM and case["queue"] == "Hub Retail"


def test_an_unowned_customers_handoff_goes_to_the_whole_queue(hub) -> None:
    from voice import persist

    ix = _case(hub, suffix="pool")
    hub.execute(text("DELETE FROM interaction_handoffs WHERE interaction_id = :ix"), {"ix": ix})
    persist.record_handoff(interaction_id=ix, reason="dispute", bot_id=BOT)
    case = _handoffs(hub, ix)[0]
    assert case["to_team_id"] is None and case["queue"] is None


@pytest.mark.parametrize(("number", "outcome"), [("+919800000000", "ringing"), ("", "no_line")])
def test_the_transfer_hook_records_what_it_rang(monkeypatch, number, outcome) -> None:
    """Configured is not answered: the hook only knows whether there is a line
    to ring. The end of the call says whether it was answered."""
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


# --- wrap-up: the holder, once, with evidence ---------------------------------


def test_only_the_cases_holder_may_wrap_it_up(hub, as_actor) -> None:
    ix = _case(hub, suffix="own")
    as_actor(AGENT)
    db.claim_handoff(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.wrap_up_interaction(ix, INFO)


def test_wrap_up_closes_the_case_and_keeps_the_notes_on_it(hub, as_actor) -> None:
    ix = _case(hub, suffix="wrap")
    hub.execute(text("UPDATE interactions SET summary = 'The bot explained the late fee.' WHERE id = :ix"), {"ix": ix})
    as_actor(AGENT)
    db.claim_handoff(ix)
    assert db.wrap_up_interaction(ix, INFO)["id"] == ix
    row = _interaction(hub, ix)
    assert row["status"] == "completed" and row["disposition"] == "Info provided"
    assert row["summary"] == "The bot explained the late fee."  # the conversation's, not replaced
    assert _handoffs(hub, ix)[0]["wrap_up_notes"] == "explained the charge"
    session = db.get_handoff_session(ix)
    assert session["status"] == "completed"
    assert session["wrapUp"]["outcome"] == "Info provided" and session["wrapUp"]["notes"] == "explained the charge"


def test_a_closed_case_takes_no_second_wrap_up_or_writes(hub, as_actor) -> None:
    ix = _case(hub, suffix="twice")
    hub.execute(
        text("INSERT INTO ai_response_suggestions (id, interaction_id, suggestion_text, source) VALUES ('sug-closed', :ix, 'x', 'kb')"),
        {"ix": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.wrap_up_interaction(ix, INFO, idempotency_key="wrap-HO-twice")
    with pytest.raises(ValueError, match="handoff_closed"):
        db.wrap_up_interaction(ix, {"disposition": "Unresolved - retry", "notes": "again"}, idempotency_key="other")
    with pytest.raises(ValueError, match="handoff_closed"):
        db.record_handoff_disclosure(ix, {"itemId": "rule-recording", "ruleId": "rule-recording"})
    with pytest.raises(ValueError, match="handoff_closed"):
        db.accept_handoff_suggestion(ix, "sug-closed")
    assert _interaction(hub, ix)["disposition"] == "Info provided"


def test_a_wrap_up_replay_answers_only_the_holder(hub, as_actor) -> None:
    ix = _case(hub, suffix="replay")
    as_actor(AGENT)
    db.claim_handoff(ix)
    first = db.wrap_up_interaction(ix, INFO, idempotency_key="wrap-HO-replay")
    assert db.wrap_up_interaction(ix, INFO, idempotency_key="wrap-HO-replay") == first
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.wrap_up_interaction(ix, INFO, idempotency_key="wrap-HO-replay")


@pytest.mark.parametrize(
    ("outcome", "need"),
    [
        ("PTP captured", "promise"),
        ("Callback scheduled", "callback"),
        ("Dispute raised", "dispute"),
        ("Customer says they paid", "notes"),
        ("Info provided", "notes"),
        ("Unresolved - retry", "notes"),
    ],
)
def test_an_outcome_is_refused_without_what_it_claims(hub, as_actor, outcome, need) -> None:
    ix = _case(hub, suffix=f"need-{need}-{len(outcome)}")
    as_actor(AGENT)
    db.claim_handoff(ix)
    with pytest.raises(ValueError, match=f"disposition_needs:{need}"):
        db.wrap_up_interaction(ix, {"disposition": outcome, "notes": "   "})


def test_an_outcome_outside_the_catalogue_is_refused(hub, as_actor) -> None:
    ix = _case(hub, suffix="unknown")
    as_actor(AGENT)
    db.claim_handoff(ix)
    with pytest.raises(ValueError, match="unknown_disposition"):
        db.wrap_up_interaction(ix, {"disposition": "Escalated to supervisor", "notes": "x"})


def _ptp(cust, days=10):
    from agent_core import clock

    return {"customerId": cust, "amount": 1500, "promisedDate": (clock.today_local() + timedelta(days=days)).isoformat()}


def test_a_ptp_wrap_up_files_its_promise_on_the_calls_channel(hub, as_actor) -> None:
    ix = _case(hub, suffix="ptp", channel="whatsapp")
    # A callback already on the interaction is not something this wrap-up filed.
    hub.execute(
        text(
            "INSERT INTO callbacks (id, customer_id, interaction_id, reason, scheduled_at, status, created_at) "
            "VALUES ('CB-earlier', :c, :ix, 'payment_discussion', now() + interval '1 day', 'scheduled', now() - interval '1 day')"
        ),
        {"c": CUST, "ix": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    out = db.wrap_up_interaction(ix, {"disposition": "PTP captured", "promise": _ptp(CUST)})
    assert out["spawned"]["promise"]
    assert hub.execute(text("SELECT channel FROM promises WHERE interaction_id = :ix"), {"ix": ix}).scalar() == "whatsapp"
    assert [f["kind"] for f in db.get_handoff_session(ix)["filed"]] == ["promise"]


def test_a_wrap_up_files_records_only_with_collections_rights(hub, as_actor) -> None:
    """A role that works cases but may not write collections records (as
    POST /promises refuses it) cannot file one through the wrap-up either."""
    t = db.current_tenant()
    hub.execute(
        text("INSERT INTO roles (id, tenant_id, name, configured_at) VALUES ('hub-role-casework', :t, 'casework', now())"),
        {"t": t},
    )
    for perm in (authz.INTERACTIONS_READ, authz.INTERACTIONS_WRITE):
        hub.execute(
            text("INSERT INTO role_permissions (role_id, permission_id) VALUES ('hub-role-casework', :p)"), {"p": perm}
        )
    hub.execute(text("UPDATE user_roles SET role_id = 'hub-role-casework' WHERE user_id = :u"), {"u": AGENT})
    authz.invalidate_permission_cache()
    ix = _case(hub, suffix="noperm")
    as_actor(AGENT)
    db.claim_handoff(ix)
    with pytest.raises(PermissionError, match="records_need_collections_write"):
        db.wrap_up_interaction(ix, {"disposition": "PTP captured", "promise": _ptp(CUST)})
    assert hub.execute(text("SELECT count(*) FROM promises WHERE interaction_id = :ix"), {"ix": ix}).scalar() == 0
    db.wrap_up_interaction(ix, INFO)  # a note-only outcome is the case's own
    assert _handoffs(hub, ix)[0]["completed_at"] is not None


def test_a_promise_dated_before_today_is_refused(hub, as_actor) -> None:
    ix = _case(hub, suffix="ptppast")
    as_actor(AGENT)
    db.claim_handoff(ix)
    with pytest.raises(ValueError, match="promise_date_in_past"):
        db.wrap_up_interaction(ix, {"disposition": "PTP captured", "promise": _ptp(CUST, days=-1)})


def _callback(when, assignee=None):
    return {"scheduledAt": when.isoformat(), "reason": "payment_discussion", "assigneeUserId": assignee}


def test_a_callback_in_the_past_is_refused(hub, as_actor) -> None:
    from agent_core.clock import utc_now

    ix = _case(hub, suffix="cbpast")
    as_actor(AGENT)
    db.claim_handoff(ix)
    with pytest.raises(ValueError, match="callback_in_past"):
        db.wrap_up_interaction(
            ix, {"disposition": "Callback scheduled", "callback": {**_callback(utc_now() - timedelta(hours=1), AGENT), "customerId": CUST}}
        )


def test_a_callback_lands_in_its_assignees_team(hub, as_actor) -> None:
    """Not the retail team every callback used to default to."""
    from agent_core.clock import utc_now

    ix = _case(hub, suffix="cbteam", team=OTHER_TEAM)
    as_actor(OTHER)
    db.claim_handoff(ix)
    out = db.wrap_up_interaction(
        ix, {"disposition": "Callback scheduled", "callback": {**_callback(utc_now() + timedelta(days=1), OTHER), "customerId": CUST}}
    )
    team = hub.execute(text("SELECT team_id FROM callbacks WHERE id = :id"), {"id": out["spawned"]["callback"]["id"]}).scalar()
    assert team == OTHER_TEAM


def test_an_unassigned_callback_follows_the_customers_agent(hub, as_actor) -> None:
    from agent_core.clock import utc_now

    hub.execute(text("UPDATE customers SET assigned_user_id = :u WHERE id = :c"), {"u": OTHER, "c": CUST})
    as_actor(ADMIN)
    created = db.create_callback({**_callback(utc_now() + timedelta(days=1)), "customerId": CUST})
    team = hub.execute(text("SELECT team_id FROM callbacks WHERE id = :id"), {"id": created["id"]}).scalar()
    assert team == OTHER_TEAM


# --- what the case shows -----------------------------------------------------


def test_disclosure_write_and_identity_lock(hub, as_actor) -> None:
    ix = _case(hub, suffix="disc")
    as_actor(AGENT)
    db.claim_handoff(ix)
    session = db.record_handoff_disclosure(
        ix, {"itemId": "rule-recording", "ruleId": "rule-recording", "label": "Recording disclosure read"}
    )
    assert next(i for i in session["complianceItems"] if i["ruleId"] == "rule-recording")["checked"] is True
    db.record_handoff_disclosure(ix, {"itemId": "identity", "ruleId": "rule-identity"})
    with pytest.raises(ValueError, match="identity_locked"):
        db.record_handoff_disclosure(ix, {"itemId": "identity", "ruleId": "rule-identity"})


def _item(session, rule_id):
    return next(i for i in session["complianceItems"] if i["ruleId"] == rule_id)


@pytest.mark.parametrize(
    ("rule", "label"),
    [("r-rec", "Call recording notice"), ("rule-recording", "Recording disclosure read")],
)
def test_the_bots_disclosure_stays_the_bots_evidence(hub, as_actor, rule, label) -> None:
    """Unticking what the bot said used to rewrite its row as the person's."""
    ix = _case(hub, suffix=f"botsaid-{rule}")
    hub.execute(
        text(
            "INSERT INTO interaction_disclosures (id, interaction_id, rule_id, label, read, read_at_sec, read_by_kind, read_by_bot_id) "
            "VALUES (:id, :ix, :rule, :label, true, 3, 'bot', :bot)"
        ),
        {"id": f"DISC-{rule}", "ix": ix, "rule": rule, "label": label, "bot": BOT},
    )
    as_actor(AGENT)
    rec = _item(db.claim_handoff(ix), "rule-recording")
    assert (rec["checked"], rec["locked"], rec["source"]) == (True, True, "bot")
    for item_id in (rec["id"], f"DISC-{rule}"):
        with pytest.raises(ValueError, match="disclosure_said_by_bot"):
            db.record_handoff_disclosure(ix, {"itemId": item_id, "ruleId": "rule-recording", "read": False})
    row = hub.execute(
        text("SELECT read, read_by_kind, read_by_bot_id, read_by_user_id FROM interaction_disclosures WHERE id = :id"),
        {"id": f"DISC-{rule}"},
    ).one()
    assert tuple(row) == (True, "bot", BOT, None)


def test_a_persons_tick_is_their_own_attestation(hub, as_actor) -> None:
    ix = _case(hub, suffix="attest")
    as_actor(AGENT)
    db.claim_handoff(ix)
    rec = _item(db.record_handoff_disclosure(ix, {"itemId": "rule-recording", "ruleId": "rule-recording"}), "rule-recording")
    assert (rec["checked"], rec["locked"], rec["source"]) == (True, False, "human")
    rec = _item(
        db.record_handoff_disclosure(ix, {"itemId": rec["id"], "ruleId": "rule-recording", "read": False}),
        "rule-recording",
    )
    assert (rec["checked"], rec["source"]) == (False, None)


def test_suggestion_accept(hub, as_actor) -> None:
    ix = _case(hub, suffix="sug")
    hub.execute(
        text("INSERT INTO ai_response_suggestions (id, interaction_id, suggestion_text, source) VALUES ('sug-ho', :iid, 'Offer a PTP today', 'playbook')"),
        {"iid": ix},
    )
    as_actor(AGENT)
    db.claim_handoff(ix)
    hit = next(s for s in db.accept_handoff_suggestion(ix, "sug-ho")["suggestions"] if s["id"] == "sug-ho")
    assert hit["accepted"] is True


def test_an_unreadable_policy_is_unavailable_not_empty(hub, as_actor, monkeypatch) -> None:
    from agent_core.authority import policy

    ix = _case(hub, suffix="pol")

    def _boom(*_a, **_k):
        raise RuntimeError("policy store down")

    monkeypatch.setattr(policy, "snapshot", _boom)
    as_actor(AGENT)
    assert db.claim_handoff(ix)["customerContext"]["authorityPolicy"] is None


def test_the_case_has_no_invented_consent(hub, as_actor) -> None:
    ix = _case(hub, suffix="consent")
    as_actor(AGENT)
    context = db.claim_handoff(ix)["customerContext"]
    assert "dnd" not in context and "liveQa" not in context


def test_a_disclosure_records_when_in_the_call_it_was_read(hub, as_actor) -> None:
    ix = _case(hub, suffix="offset")
    hub.execute(text("UPDATE interactions SET started_at = now() - interval '90 seconds' WHERE id = :ix"), {"ix": ix})
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.record_handoff_disclosure(ix, {"itemId": "rule-recording", "ruleId": "rule-recording"})
    at = hub.execute(
        text("SELECT read_at_sec FROM interaction_disclosures WHERE interaction_id = :ix AND rule_id = 'rule-recording'"),
        {"ix": ix},
    ).scalar()
    assert at == 90


def test_the_copilot_opens_for_the_holder_and_not_a_stranger(hub, as_actor) -> None:
    ix = _case(hub, suffix="cop")
    as_actor(AGENT)
    db.claim_handoff(ix)
    db.assert_handoff_readable(ix)
    as_actor(OTHER)
    with pytest.raises(PermissionError, match="handoff_not_assigned"):
        db.assert_handoff_readable(ix)


def _treatment(conn, action):
    conn.execute(
        text(
            "INSERT INTO treatment_decisions (id, tenant_id, customer_id, trigger_kind, mode, recommender, "
            "recommender_version, feature_schema_version, chosen_action, chosen_channel) "
            "VALUES (:id, :t, :c, 'manual', 'live', 'hub-test', '1', '1', :a, :a)"
        ),
        {"id": f"TD-hub-{action}", "t": db.current_tenant(), "c": CUST, "a": action},
    )


def _live_qa(conn, ix, action):
    conn.execute(
        text(
            "INSERT INTO live_qa_decisions (id, tenant_id, interaction_id, mode, feature_schema_version, verdict, recommended_action) "
            "VALUES (:id, :t, :ix, 'live', '1', 'fail_soft', :a)"
        ),
        {"id": f"LQ-hub-{action}", "t": db.current_tenant(), "ix": ix, "a": action},
    )


def _approval(monkeypatch, note):
    import work_runtime

    monkeypatch.setattr(work_runtime, "list_jobs", lambda **_kw: [{"id": "job-1", "note": note}])


@pytest.mark.parametrize(
    "change",
    [
        lambda hub, ix, mp: _treatment(hub, "sms"),
        lambda hub, ix, mp: _live_qa(hub, ix, "whisper"),
        lambda hub, ix, mp: _approval(mp, "waive the late fee"),
    ],
    ids=["treatment", "live-qa", "approval"],
)
def test_the_copilot_evidence_moves_with_what_the_draft_reads(hub, as_actor, monkeypatch, change) -> None:
    ix = _case(hub, suffix="evid")
    _approval(monkeypatch, "first ask")
    as_actor(AGENT)
    before = db.claim_handoff(ix)["copilotEvidence"]
    assert db.get_handoff_session(ix)["copilotEvidence"] == before  # an unchanged poll
    change(hub, ix, monkeypatch)
    assert db.get_handoff_session(ix)["copilotEvidence"] != before


def test_the_copilot_evidence_ignores_what_the_draft_does_not_read(hub, as_actor) -> None:
    """The draft is the engines' decisions, not the conversation: a new turn
    used to redraft it on every poll of a live call."""
    ix = _case(hub, suffix="evidturn")
    as_actor(AGENT)
    before = db.claim_handoff(ix)["copilotEvidence"]
    hub.execute(
        text("INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, at_sec, text) VALUES ('T-evid-2', :ix, 1, 'bot', 9, 'Noted')"),
        {"ix": ix},
    )
    assert db.get_handoff_session(ix)["copilotEvidence"] == before
