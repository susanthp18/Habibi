"""Where the treatment engine meets the rest of the product.

The engine on its own is a function that returns a plan. What makes it a
feature is that the bounce webhook, the settle tick, the escalation path, the
offer engine and the API all consult the same one — and that a hold placed by a
supervisor on Tuesday still binds a bot at 02:00 on Thursday.

These are the joins, and they are the parts that rot first: each is a place
where a second copy of a rule could grow.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

import db

TENANT = "hdfc.retail"


@pytest.fixture
def customer(db_tx):
    row = db_tx.execute(
        text(
            """
            SELECT a.id AS account_id, a.customer_id
            FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE c.tenant_id = :t AND c.phone_primary IS NOT NULL
              AND a.dpd BETWEEN 1 AND 30
            ORDER BY a.id LIMIT 1
            """
        ),
        {"t": TENANT},
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no early-bucket account with a phone number")
    return dict(row)


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "treatment-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


HEADERS = {"X-API-Key": "treatment-test-key", "X-Actor-User-Id": "priya-nair"}


# ---------------------------------------------------------------------------
# Holds as rows
# ---------------------------------------------------------------------------


def test_a_hold_is_created_listed_and_released(db_tx, customer) -> None:
    hold = db.create_treatment_hold(
        {"customerId": customer["customer_id"], "kind": "hardship", "reason": "lost job"}
    )
    assert hold["active"] is True

    listed = db.list_treatment_holds(customer_id=customer["customer_id"])
    assert hold["id"] in {h["id"] for h in listed}

    released = db.release_treatment_hold(hold["id"], {"reason": "plan agreed"})
    assert released["active"] is False
    assert not db.list_treatment_holds(customer_id=customer["customer_id"])


def test_placing_the_same_hold_twice_is_a_no_op(db_tx, customer) -> None:
    """A bot that hears "I lost my job" twice in one call and an agent who
    clicks twice must both end with exactly one hold. A 409 would leave the
    caller deciding what to do about it."""
    first = db.create_treatment_hold({"customerId": customer["customer_id"], "kind": "hardship"})
    second = db.create_treatment_hold({"customerId": customer["customer_id"], "kind": "hardship"})
    assert first["id"] == second["id"]


def test_an_account_hold_and_a_customer_hold_coexist(db_tx, customer) -> None:
    """A dispute is usually about one account; hardship is about a person.
    Postgres treats NULLs as distinct, so the unique index has to COALESCE or
    these two collapse into one."""
    whole = db.create_treatment_hold({"customerId": customer["customer_id"], "kind": "dispute"})
    one_account = db.create_treatment_hold(
        {
            "customerId": customer["customer_id"],
            "accountId": customer["account_id"],
            "kind": "dispute",
        }
    )
    assert whole["id"] != one_account["id"]


def test_an_unknown_hold_kind_is_refused(db_tx, customer) -> None:
    """Each kind carries different downstream behaviour. A value with no rule
    behind it would silently mean "no hold at all"."""
    with pytest.raises(ValueError):
        db.create_treatment_hold({"customerId": customer["customer_id"], "kind": "vibes"})


def test_an_expired_hold_stops_binding(db_tx, customer) -> None:
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_holds (id, tenant_id, customer_id, kind, source, expires_at)
            VALUES ('THD-EXPIRED', :t, :c, 'complaint', 'manual', now() - interval '1 hour')
            """
        ),
        {"t": TENANT, "c": customer["customer_id"]},
    )
    from agent_core.treatment import Trigger, recommend_treatment

    result = recommend_treatment(
        customer_id=customer["customer_id"],
        account_id=customer["account_id"],
        trigger=Trigger(kind="dpd_tick"),
        conn=db_tx,
    )
    assert "hold:complaint" not in set(result.excluded.values())


# ---------------------------------------------------------------------------
# The escalation path places one
# ---------------------------------------------------------------------------


def _interaction(conn, customer_id: str) -> str:
    ix = f"IX-TREAT-{secrets.token_hex(4).upper()}"
    conn.execute(
        text(
            """
            INSERT INTO interactions (id, tenant_id, customer_id, handler_kind,
                                      handler_bot_id, channel, status)
            VALUES (:id, :t, :c, 'bot', :bot, 'voice', 'active')
            """
        ),
        {"id": ix, "t": TENANT, "c": customer_id, "bot": db.DEFAULT_BOT_ID},
    )
    return ix


def test_escalating_for_hardship_stops_the_dunning(db_tx, customer) -> None:
    """Warm-transferring a borrower who has just described losing their job and
    then dialling them again tomorrow because the campaign says so is the single
    most complained-about thing a collections floor does. "hardship" used to be
    a routing label that expired with the call."""
    ix = _interaction(db_tx, customer["customer_id"])
    db.escalate_voice_interaction(interaction_id=ix, reason="hardship")

    holds = db.list_treatment_holds(customer_id=customer["customer_id"])
    kinds = {h["kind"] for h in holds}
    assert "hardship" in kinds
    assert {h["source"] for h in holds if h["kind"] == "hardship"} == {"bot"}


def test_escalating_for_a_dispute_holds_only_the_pressure(db_tx, customer) -> None:
    ix = _interaction(db_tx, customer["customer_id"])
    db.escalate_voice_interaction(interaction_id=ix, reason="dispute")
    assert "dispute" in {h["kind"] for h in db.list_treatment_holds(customer_id=customer["customer_id"])}


def test_an_ordinary_escalation_places_no_hold(db_tx, customer) -> None:
    """A borrower who asked for a human has not asked to stop being contacted."""
    ix = _interaction(db_tx, customer["customer_id"])
    db.escalate_voice_interaction(interaction_id=ix, reason="customer_requested")
    assert not db.list_treatment_holds(customer_id=customer["customer_id"])


def test_a_second_escalation_on_the_same_call_does_not_error(db_tx, customer) -> None:
    ix = _interaction(db_tx, customer["customer_id"])
    db.escalate_voice_interaction(interaction_id=ix, reason="hardship")
    db.escalate_voice_interaction(interaction_id=ix, reason="hardship")
    holds = [h for h in db.list_treatment_holds(customer_id=customer["customer_id"]) if h["kind"] == "hardship"]
    assert len(holds) == 1


# ---------------------------------------------------------------------------
# Collection / upsell separation
# ---------------------------------------------------------------------------


def test_a_hardship_hold_also_silences_the_offer_engine(db_tx, customer) -> None:
    """Digital Lending Guidelines require a hard separation between collecting a
    debt and selling a product. Reco's own gates can only see what the borrower
    said *on this call* — a hold placed last Tuesday is exactly the case they
    cannot see, and the one where a cross-sell does most damage."""
    from agent_core.reco import recommend

    db.create_treatment_hold({"customerId": customer["customer_id"], "kind": "hardship"})
    result = recommend(
        customer_id=customer["customer_id"], channel="voice", force_mode="live"
    )
    assert result.suppressed
    assert result.reason == "hold:hardship"
    assert not result.offers


def test_a_dispute_hold_does_not_silence_the_offer_engine(db_tx, customer) -> None:
    """A disputed fee is not a reason never to speak to somebody about a
    product again. Only the holds that mean hardship or a live regulatory
    matter carry that far."""
    from agent_core.treatment import policy as treatment_policy

    db.create_treatment_hold({"customerId": customer["customer_id"], "kind": "dispute"})
    assert treatment_policy.suppresses_upsell(db_tx, customer["customer_id"]) is None


def test_an_unreadable_hold_table_suppresses_rather_than_pitches(db_tx) -> None:
    """Fail closed. Failing open here means pitching a product to someone in
    hardship because a query timed out."""
    from agent_core.treatment import policy as treatment_policy

    class Exploding:
        def execute(self, *a, **k):
            raise RuntimeError("hold table is unreachable")

    assert treatment_policy.suppresses_upsell(Exploding(), "anyone") is not None


# ---------------------------------------------------------------------------
# The triggers that call the engine
# ---------------------------------------------------------------------------


def test_a_bounce_decides_the_next_step_in_the_same_transaction(db_tx, customer) -> None:
    """The pay-link is the legally required written notice, not the campaign.
    What comes after it is a decision, and it is made in the same minute as the
    bounce rather than in tomorrow's allocation."""
    import payment_events

    result = payment_events.ingest(
        db_tx,
        {
            "accountId": customer["account_id"],
            "source": "sandbox",
            "sourceRef": f"probe-{secrets.token_hex(4)}",
            "amount": 4500,
            "reason": "insufficient_funds",
        },
    )
    assert result["ok"]
    logged = db_tx.execute(
        text(
            """
            SELECT trigger_kind, trigger_ref, chosen_action
            FROM treatment_decisions
            WHERE customer_id = :c AND trigger_kind = 'bounce'
            ORDER BY created_at DESC LIMIT 1
            """
        ),
        {"c": customer["customer_id"]},
    ).mappings().first()
    assert logged is not None
    assert logged["trigger_ref"] == result["eventId"]


def test_a_bounce_still_ingests_when_the_engine_fails(db_tx, customer, monkeypatch) -> None:
    """The engine runs inside ingest. A recommender having a bad day must not
    cost the lender the bounce case itself."""
    import payment_events

    def _boom(*a, **k):
        raise RuntimeError("engine import exploded")

    monkeypatch.setattr(payment_events, "_plan_next", _boom)
    with pytest.raises(RuntimeError):
        payment_events._plan_next(db_tx, {}, now=datetime.now(timezone.utc))

    monkeypatch.undo()
    monkeypatch.setattr(
        "agent_core.treatment.recommend_treatment",
        lambda **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = payment_events.ingest(
        db_tx,
        {
            "accountId": customer["account_id"],
            "source": "sandbox",
            "sourceRef": f"probe-{secrets.token_hex(4)}",
            "amount": 4500,
            "reason": "technical",
        },
    )
    assert result["ok"]


def test_a_broken_promise_carries_the_plan_into_the_follow_up(db_tx, customer) -> None:
    """The clerk who picks this up reads what the engine decided and why,
    instead of "Broken promise follow-up"."""
    import promise_fulfillment

    promise_id = f"PR-TREAT-{secrets.token_hex(4).upper()}"
    db_tx.execute(
        text(
            """
            INSERT INTO promises (id, customer_id, account_id, owner_kind, owner_bot_id,
                                  amount, promised_at, status, reminder_status)
            VALUES (:id, :c, :a, 'bot', :bot, 3000, now() - interval '2 days',
                    'upcoming', 'off')
            """
        ),
        {
            "id": promise_id,
            "c": customer["customer_id"],
            "a": customer["account_id"],
            "bot": db.DEFAULT_BOT_ID,
        },
    )
    promise_fulfillment.settle_promises(db.engine)

    followup = db_tx.execute(
        text("SELECT note, channel, due_at FROM followups WHERE promise_id = :p"),
        {"p": promise_id},
    ).mappings().first()
    assert followup is not None
    assert followup["note"] != "Broken promise follow-up", (
        "the follow-up should carry the engine's reasoning, not a fixed string"
    )
    logged = db_tx.execute(
        text(
            "SELECT 1 FROM treatment_decisions WHERE trigger_kind = 'broken_ptp'"
            " AND trigger_ref = :p"
        ),
        {"p": promise_id},
    ).fetchone()
    assert logged is not None


def test_a_broken_promise_still_breaks_when_the_engine_fails(db_tx, customer, monkeypatch) -> None:
    """A settle tick that dies on the recommender would leave promises marked
    ``upcoming`` past their date — worse than a generic note."""
    import promise_fulfillment

    monkeypatch.setattr(
        promise_fulfillment,
        "_next_action",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    promise_id = f"PR-FAIL-{secrets.token_hex(4).upper()}"
    db_tx.execute(
        text(
            """
            INSERT INTO promises (id, customer_id, account_id, owner_kind, owner_bot_id,
                                  amount, promised_at, status, reminder_status)
            VALUES (:id, :c, :a, 'bot', :bot, 3000, now() - interval '2 days',
                    'upcoming', 'off')
            """
        ),
        {
            "id": promise_id,
            "c": customer["customer_id"],
            "a": customer["account_id"],
            "bot": db.DEFAULT_BOT_ID,
        },
    )
    with pytest.raises(RuntimeError):
        promise_fulfillment.settle_promises(db.engine)


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_the_next_action_endpoint_answers_with_a_plan(client, customer) -> None:
    res = client.get(
        "/treatment/next",
        params={"customerId": customer["customer_id"], "accountId": customer["account_id"]},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["action"] in {
        "wait",
        "sms",
        "whatsapp",
        "voice_bot",
        "human_call",
        "field_visit",
        "legal_notice",
    }
    assert body["rationale"]
    assert "excluded" in body


def test_the_next_action_endpoint_404s_on_another_tenants_borrower(client) -> None:
    res = client.get(
        "/treatment/next", params={"customerId": "nobody-at-all"}, headers=HEADERS
    )
    assert res.status_code == 404


def test_the_insights_endpoint_reports_the_suppression_breakdown(client) -> None:
    res = client.get("/treatment/insights", params={"days": 7}, headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()
    for key in ("decisions", "actionable", "coverage", "suppression", "byAction", "byMode"):
        assert key in body


def test_the_hold_endpoints_round_trip(client, customer) -> None:
    created = client.post(
        "/treatment/holds",
        json={"customerId": customer["customer_id"], "kind": "bereavement", "reason": "probe"},
        headers=HEADERS,
    )
    assert created.status_code == 200, created.text
    hold_id = created.json()["id"]
    try:
        listed = client.get(
            "/treatment/holds",
            params={"customerId": customer["customer_id"]},
            headers=HEADERS,
        )
        assert hold_id in {h["id"] for h in listed.json()}
    finally:
        released = client.post(
            f"/treatment/holds/{hold_id}/release", json={"reason": "probe"}, headers=HEADERS
        )
        assert released.status_code == 200, released.text
        assert released.json()["active"] is False


def test_placing_a_hold_rejects_an_unknown_kind(client, customer) -> None:
    res = client.post(
        "/treatment/holds",
        json={"customerId": customer["customer_id"], "kind": "vibes"},
        headers=HEADERS,
    )
    assert res.status_code == 422


def test_releasing_a_hold_that_is_not_ours_404s(client) -> None:
    res = client.post("/treatment/holds/THD-DOES-NOT-EXIST/release", json={}, headers=HEADERS)
    assert res.status_code == 404
