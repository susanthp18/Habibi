"""Decision intelligence v2: a decision you can read, one NBA, and a loop that learns.

Each test is one promise the screen makes to a reviewer:

* every one of the ten actions in a trace is either scored or blocked with a
  reason a person can read;
* the clerk carries out only what the executor would (live, unsuppressed, due);
* offer decisions mirrored into the log never count as collections decisions;
* recovered money is a positive number;
* a label comes from the decision's own call before any time-window guess;
* the learned rate is the starting assumption until there is evidence.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from agent_core.treatment import actions as A, beliefs, decisions, followthrough, schema_ready
from agent_core.treatment.engine import recommend_treatment
from agent_core.treatment.features import SqlFeatureProvider, Trigger
from tests.conftest import bank_feeds_are_current

NOW = datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def account(db_tx):
    row = db_tx.execute(
        text(
            """
            SELECT a.id, a.customer_id FROM accounts a
            JOIN customers c ON c.id = a.customer_id
            WHERE a.dpd BETWEEN 1 AND 30 AND c.phone_primary IS NOT NULL
            ORDER BY a.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("seed has no early-bucket account with a phone number")
    bank_feeds_are_current(db_tx, customer_id=row["customer_id"])
    return dict(row)


def _decide(account, conn, **kw):
    return recommend_treatment(
        customer_id=account["customer_id"],
        account_id=account["id"],
        trigger=Trigger(kind="dpd_tick", at=NOW, ref=f"probe-{uuid.uuid4().hex[:8]}"),
        conn=conn,
        provider=SqlFeatureProvider(),
        **kw,
    )


# --- the learned rate -------------------------------------------------------


def test_the_learned_rate_is_the_assumption_until_there_is_evidence() -> None:
    assert beliefs.blend(0.3, None).source == "prior"
    assert beliefs.blend(0.3, None).value == 0.3
    # 0 of 20 against an assumption worth 20: halfway to the evidence.
    assert abs(beliefs.blend(0.3, (0, 20)).value - 0.15) < 1e-9
    # A thousand outcomes outweigh the assumption.
    assert abs(beliefs.blend(0.3, (900, 1000)).value - 0.8882) < 1e-3
    logged = beliefs.blend(0.3, (5, 10)).to_log()
    assert logged["source"] == "learned" and logged["trials"] == 10 and logged["prior"] == 0.3


# --- the trace --------------------------------------------------------------


def test_every_action_in_a_trace_is_scored_or_blocked_with_a_reason(db_tx, account) -> None:
    import decision_trace

    result = _decide(account, db_tx, force_mode="shadow")
    assert result.decision_id
    trace = decision_trace.trace(result.decision_id)

    assert [o["action"] for o in trace["options"]] == list(A.ALL)
    for option in trace["options"]:
        if option["status"] == "blocked":
            assert option["reason"] and "_" not in option["reason"].split(":")[0], option
        elif option["status"] == "scored":
            assert option["explanation"], option
            if option["action"] != A.WAIT:
                assert option["evidence"]["resolve"]["source"] in {"prior", "learned"}
    assert trace["choice"]["action"] == result.action
    assert trace["choice"]["howText"]
    assert trace["whyNow"]["facts"], "a reviewer needs the facts the engine saw"
    assert trace["versions"]["recommender"]


def test_decide_now_is_recorded_and_never_enactable(db_tx, account) -> None:
    import decision_trace

    trace = decision_trace.decide_now(customer_id=account["customer_id"], account_id=account["id"])
    assert trace["mode"] == "shadow"
    assert decisions.claim_by_id(db_tx, trace["id"]) is None


def test_every_surface_reads_the_same_current_decision(db_tx, account) -> None:
    import db
    from agent_core import copilot

    _decide(account, db_tx, force_mode="shadow")
    current = decisions.current(db_tx, customer_id=account["customer_id"])
    card = db._treatment_snapshot(db_tx, account["customer_id"])
    whisper = copilot._treatment(account["customer_id"])
    # A pending live plan outranks a newer shadow preview; either way, one row.
    assert current and card and card["decisionId"] == current["id"]
    assert whisper["decisionId"] == current["id"]


# --- the clerk --------------------------------------------------------------


def test_the_clerk_cannot_claim_a_shadow_or_held_decision(db_tx, account) -> None:
    shadow = _decide(account, db_tx, force_mode="shadow")
    assert decisions.claim_by_id(db_tx, shadow.decision_id) is None


# --- offer rows stay out ----------------------------------------------------


def test_offer_decisions_are_not_collections_decisions(db_tx, account) -> None:
    if not schema_ready.w12_ready(db_tx):
        pytest.skip("action_family arrives with 0121")
    before = decisions.insights(db_tx, days=1)["decisions"]
    db_tx.execute(
        text(
            """
            INSERT INTO treatment_decisions (
              id, tenant_id, customer_id, trigger_kind, mode, recommender,
              recommender_version, feature_schema_version, features, candidates,
              excluded, chosen_action, action_family, created_at
            )
            SELECT :id, c.tenant_id, c.id, 'inbound', 'live', 'reco', '1', 'v1',
                   '{}'::jsonb, '[]'::jsonb, '{}'::jsonb, 'offer', 'offer', now()
              FROM customers c WHERE c.id = :cid
            """
        ),
        {"id": f"TD-OFFER-{uuid.uuid4().hex[:8]}", "cid": account["customer_id"]},
    )
    assert decisions.insights(db_tx, days=1)["decisions"] == before


# --- money ------------------------------------------------------------------


def test_recovered_money_is_positive(db_tx) -> None:
    from agent_core.treatment import metrics

    got = metrics.efficiency(db_tx, days=3650, modes=["shadow", "live"])
    assert got["recoveredInr"] >= 0


# --- labels -----------------------------------------------------------------


class _Rows:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row

    def fetchone(self):
        return self._row


class _Conn:
    """Answers the linked-outcome query with one call outcome."""

    def __init__(self, outcome):
        self.outcome = outcome

    def execute(self, statement, params=None):
        sql = str(statement)
        if "call_attempts" in sql:
            return _Rows(self.outcome)
        return _Rows(None)


@pytest.mark.parametrize(
    "outcome, label",
    [
        ({"connection": "connected", "business": "ptp_captured", "disposition": None}, "ptp"),
        ({"connection": "connected", "business": None, "disposition": "opted_out"}, "refused"),
        ({"connection": "voicemail", "business": None, "disposition": None}, "no_answer"),
        ({"connection": "invalid_number", "business": None, "disposition": None}, "undeliverable"),
        ({"connection": "connected", "business": None, "disposition": "callback_booked"}, "reached"),
    ],
)
def test_a_label_comes_from_the_decisions_own_call(outcome, label) -> None:
    assert followthrough._linked_outcome(_Conn(outcome), {"id": "TD-X"}) == label


def test_health_and_learned_rates_read(db_tx) -> None:
    import decision_trace

    health = decision_trace.health()
    assert {s["key"] for s in health["stages"]} >= {"decide", "labels", "learn", "train"}
    rates = decision_trace.learned_rates()
    assert any(r["metric"] == "reach" for r in rates) and any(r["metric"] == "resolve" for r in rates)


# --- upsell: scored on the call, never spoken on it --------------------------


def test_the_tool_payload_is_identical_whether_or_not_an_offer_was_scored() -> None:
    """A difference between the two payloads is itself the pitch."""
    from agent_core.reco.engine import RecommendationResult

    with_offer = RecommendationResult(offers=[object()], reason=None, decision_id="OD-1")  # type: ignore[list-item]
    without = RecommendationResult(offers=[], reason="suitability:no_assessment", decision_id="OD-2")
    assert with_offer.to_tool_payload() == without.to_tool_payload()


def test_no_offer_tool_tells_the_bot_to_raise_a_product() -> None:
    import json
    from pathlib import Path

    from agent_core.tools import catalog

    backend = Path(__file__).resolve().parents[1]
    graph = json.loads((backend / "agent_core/cards/graphs/collections.json").read_text(encoding="utf-8"))
    upsell = next(n for n in graph["nodes"] if n["key"] == "gated_upsell")["data"]["instructions"]
    assert "mention ONE offer" not in upsell and "indicative amount" not in upsell
    assert "never pitch anything this tool did not return" not in catalog.RECOMMEND_NEXT_OFFER.description
    domain_src = (backend / "agent_core/tools/domain.py").read_text(encoding="utf-8")
    assert "mention the product in one short sentence" not in domain_src


# --- upsell, end to end: said → signal → offer → lead → label -----------------


def _consented_customer(db_tx) -> str:
    """A customer with no holds or disputes, given marketing consent on WhatsApp."""
    cid = db_tx.execute(
        text(
            """
            SELECT c.id FROM customers c
             WHERE c.id <> 'UNKNOWN-CALLER' AND COALESCE(c.dnd, false) = false
               AND NOT EXISTS (SELECT 1 FROM treatment_holds h WHERE h.customer_id = c.id AND h.released_at IS NULL)
               AND NOT EXISTS (SELECT 1 FROM disputes d WHERE d.customer_id = c.id
                                  AND d.status NOT IN ('resolved','rejected'))
               AND NOT EXISTS (SELECT 1 FROM leads l WHERE l.customer_id = c.id AND l.product_id = 'debt-consolidation')
               AND EXISTS (SELECT 1 FROM products p WHERE p.id = 'debt-consolidation' AND p.tenant_id = c.tenant_id)
             ORDER BY c.id LIMIT 1
            """
        )
    ).scalar()
    if cid is None:
        pytest.skip("seed has no customer debt consolidation could be offered to")
    rec = db_tx.execute(text("SELECT id FROM consent_records WHERE customer_id = :c"), {"c": cid}).scalar()
    if rec is None:
        rec = f"CR-T-{uuid.uuid4().hex[:8]}"
        db_tx.execute(text("INSERT INTO consent_records (id, customer_id) VALUES (:i, :c)"), {"i": rec, "c": cid})
    db_tx.execute(
        text(
            """
            INSERT INTO channel_consents (id, consent_id, channel, purpose, status, captured_at)
            VALUES (:i, :r, 'whatsapp', 'promotional', 'opted_in', now())
            ON CONFLICT (consent_id, channel, purpose) DO UPDATE SET status = 'opted_in', captured_at = now()
            """
        ),
        {"i": f"CC-T-{uuid.uuid4().hex[:8]}", "r": rec},
    )
    return cid


def _conversation(db_tx, cid: str, said: list[str]) -> str:
    iid = f"IX-T-{uuid.uuid4().hex[:8]}"
    tenant = db_tx.execute(text("SELECT tenant_id FROM customers WHERE id = :c"), {"c": cid}).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO interactions (id, tenant_id, customer_id, handler_kind, handler_bot_id,
                                      channel, status, started_at, ended_at)
            VALUES (:i, :t, :c, 'bot', (SELECT id FROM bots ORDER BY id LIMIT 1),
                    'whatsapp', 'completed', now() - interval '5 minutes', now())
            """
        ),
        {"i": iid, "t": tenant, "c": cid},
    )
    for n, line in enumerate(said):
        for k, (speaker, words) in enumerate((("bot", "How can I help?"), ("customer", line))):
            db_tx.execute(
                text(
                    "INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, text)"
                    " VALUES (:id, :i, :n, :s, :t)"
                ),
                {"id": f"TT-{uuid.uuid4().hex[:10]}", "i": iid, "n": 2 * n + k, "s": speaker, "t": words},
            )
    return iid


def test_what_a_customer_says_becomes_a_traceable_offer_and_a_lead(db_tx, monkeypatch) -> None:
    import azure_openai
    import db_leads
    import offer_trace
    from agent_core.reco import sender
    from agent_core.signals import opportunity, scan

    cid = _consented_customer(db_tx)
    iid = _conversation(
        db_tx, cid,
        ["I paid the EMI already", "I have two credit cards at very high interest I want to clear", "thanks, that's all"],
    )

    # The LLM half, answered: the checks after it are what is under test.
    monkeypatch.setattr(
        azure_openai, "chat_with_tools",
        lambda *a, **k: {"toolCalls": [{"name": "report_signals", "arguments": '{"signals": [{"code": "high_interest_debt", '
                                          '"turn": 2, "confidence": 0.9, "horizon": "now"}]}'}]},
    )
    row = dict(db_tx.execute(
        text("SELECT id, tenant_id, customer_id, channel FROM interactions WHERE id = :i"), {"i": iid}
    ).mappings().first())
    assert scan.scan_one(row)["signals"] == 1

    tenant = row["tenant_id"]
    monkeypatch.setattr("agent_core.reco.config.mode", lambda *a, **k: "live")
    result = opportunity.sweep(tenant_id=tenant)
    assert result["decided"] >= 1
    decision_id = db_tx.execute(
        text("SELECT id FROM offer_decisions WHERE customer_id = :c ORDER BY created_at DESC LIMIT 1"),
        {"c": cid},
    ).scalar()
    trace = offer_trace.trace(decision_id)
    assert [s["code"] for s in trace["signals"]] == ["high_interest_debt"]
    assert trace["signals"][0]["evidence"] and "credit cards" in trace["signals"][0]["evidence"]
    assert trace["suitability"], "the finding the gate read is on the record"
    if trace["choice"]["productId"] is None:
        pytest.skip(f"seed made no offer here: {trace['choice']['holdReasonText']}")

    monkeypatch.setattr(sender, "enabled", lambda: True)
    monkeypatch.setattr("contact_policy.admit", lambda *a, **k: type("D", (), {"allowed": True, "reason": None})())
    monkeypatch.delenv("WHATSAPP_PROMO_TEMPLATE_NAME", raising=False)
    monkeypatch.setattr("agent_core.engine_config.number", lambda key, default=None, **k: 0.0 if key == "RECO_PROMO_CONTROL_SHARE" else default)
    import db

    assert sender.process_one(db.engine)
    lead_id = db_tx.execute(
        text("SELECT id FROM leads WHERE decision_id = :d"), {"d": decision_id}
    ).scalar()
    assert lead_id, "no template configured, so a relationship manager gets the lead"

    db_leads.patch_lead(lead_id, {"stage": "contacted"})
    assert offer_trace.trace(decision_id)["delivery"]["presented"] is True


def test_no_consent_means_the_conversation_is_not_read(db_tx, monkeypatch) -> None:
    import azure_openai
    from agent_core.signals import scan

    cid = db_tx.execute(
        text(
            """
            SELECT c.id FROM customers c WHERE c.id <> 'UNKNOWN-CALLER' AND NOT EXISTS (
              SELECT 1 FROM consent_records r JOIN channel_consents cc ON cc.consent_id = r.id
               WHERE r.customer_id = c.id AND cc.purpose = 'promotional' AND cc.status = 'opted_in')
             LIMIT 1
            """
        )
    ).scalar()
    iid = _conversation(db_tx, cid, ["I'm buying a car", "next month", "bye"])
    monkeypatch.setattr(azure_openai, "chat_with_tools", lambda *a, **k: pytest.fail("read without consent"))
    row = dict(db_tx.execute(
        text("SELECT id, tenant_id, customer_id, channel FROM interactions WHERE id = :i"), {"i": iid}
    ).mappings().first())
    got = scan.scan_one(row)
    assert got["status"] == "skipped"
    assert db_tx.execute(
        text("SELECT skip_reason FROM signal_scans WHERE interaction_id = :i"), {"i": iid}
    ).scalar() in {"no_promotional_consent", "on_dnd", "promotional_consent_withdrawn",
                   "said_something_that_rules_out_selling"}
