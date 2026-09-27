"""Bot analytics headline KPIs: computed over calls, and meaning what they say.

Deflection is not containment: an inbound bot session only deflects when it
was resolved, never handed to a human, and the customer did not come back
within 7 days (and only sessions old enough for that week to have passed
count). Latency percentiles are over calls, not an average of daily
percentiles. Sentiment lift is last-minus-first customer sentiment per call.

The rows are isolated by a Voice Studio version string no real call carries,
so the filter under test is also the one that scopes the fixture.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


def _customer(db_tx, tenant: str) -> str:
    cid = f"CUST-BA-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text("INSERT INTO customers_pii (id, tenant_id, name, risk) VALUES (:id, :t, 'BA test', 'low')"),
        {"id": cid, "t": tenant},
    )
    return cid


def _call(db_tx, tenant, customer, *, days_ago, latency, resolved=True, version=None):
    ix = f"IX-BA-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO interactions (
              id, tenant_id, customer_id, channel, direction, handler_kind, handler_bot_id,
              status, started_at, query_resolved, latency_ms, source_payload
            ) VALUES (
              :id, :t, :c, 'voice', 'inbound', 'bot', 'intake-v1', 'completed',
              now() - make_interval(days => :d), :resolved, :latency,
              CAST(:payload AS jsonb)
            )
            """
        ),
        {
            "id": ix, "t": tenant, "c": customer, "d": days_ago, "resolved": resolved,
            "latency": latency,
            "payload": '{"voiceStudio": {"versionNumber": "%s"}}' % version if version else "{}",
        },
    )
    return ix


@pytest.fixture
def calls(db_tx):
    import db

    tenant = db.current_tenant()
    version = f"test-{uuid.uuid4().hex[:6]}"
    a = _call(db_tx, tenant, _customer(db_tx, tenant), days_ago=20, latency=100, version=version)
    b_customer = _customer(db_tx, tenant)
    b = _call(db_tx, tenant, b_customer, days_ago=20, latency=200, version=version)
    # B's customer called back 2 days later (outside the version filter): not deflected.
    _call(db_tx, tenant, b_customer, days_ago=18, latency=None)
    c = _call(db_tx, tenant, _customer(db_tx, tenant), days_ago=20, latency=300, version=version)
    db_tx.execute(
        text(
            "INSERT INTO interaction_handoffs (id, interaction_id, from_kind, to_kind, reason) "
            "VALUES (:id, :ix, 'bot', 'human', 'customer_requested')"
        ),
        {"id": f"HO-{c}", "ix": c},
    )
    # Two days old: contained, but its repeat-contact week has not passed.
    _call(db_tx, tenant, _customer(db_tx, tenant), days_ago=2, latency=1000, version=version)

    # A: per-turn customer sentiment -0.5 then +0.3 (lift +0.8); the bot turn is ignored.
    for idx, (speaker, score) in enumerate([("customer", -0.5), ("bot", -0.9), ("customer", 0.3)]):
        turn = f"{a}-t{idx}"
        db_tx.execute(
            text(
                "INSERT INTO interaction_transcript (id, interaction_id, turn_index, speaker, text) "
                "VALUES (:id, :ix, :i, :sp, 'x')"
            ),
            {"id": turn, "ix": a, "i": idx, "sp": speaker},
        )
        db_tx.execute(
            text(
                "INSERT INTO interaction_turn_signals "
                "(id, interaction_id, transcript_turn_id, kind, label, score, model_version) "
                "VALUES (:id, :ix, :turn, 'sentiment', 'neutral', :s, 'test')"
            ),
            {"id": f"sig-{turn}", "ix": a, "turn": turn, "s": score},
        )
    # B: no turn signals, so the call timeline: 0.2 at 5s, -0.2 at 60s (lift -0.4).
    for at, score in [(60, -0.2), (5, 0.2)]:
        db_tx.execute(
            text(
                "INSERT INTO interaction_sentiment (id, interaction_id, at_sec, score) "
                "VALUES (:id, :ix, :at, :s)"
            ),
            {"id": f"sent-{b}-{at}", "ix": b, "at": at, "s": score},
        )
    return version


def test_summary_is_computed_over_calls(calls):
    import db

    out = db.bot_analytics("30d", "all", None, calls)
    s = out["summary"]
    assert s["botSessions"] == 4
    assert s["containment"] == 75.0  # 3 of 4 never reached a human
    # A, B, C are old enough; only A was resolved, human-free and not repeated.
    assert s["deflectionEligible"] == 3
    assert s["deflection"] == pytest.approx(33.3)
    # True percentiles over [100, 200, 300, 1000]; the average of daily
    # percentiles would say p50 = 600.
    assert s["latencyP50"] == pytest.approx(250.0)
    assert s["latencyP90"] == pytest.approx(790.0)
    # Mean of +0.8 (turn signals) and -0.4 (timeline fallback).
    assert s["sentimentLiftCalls"] == 2
    assert s["sentimentLift"] == pytest.approx(0.2)
    assert sum(p["botSessions"] for p in out["dailySeries"]) == 4
    assert sum(p["botContained"] for p in out["dailySeries"]) == 3


def test_agent_filter_and_picker(calls):
    import db

    out = db.bot_analytics("30d", "all", "intake-v1", calls)
    assert out["summary"]["botSessions"] == 4
    assert db.bot_analytics("30d", "all", "no-such-bot", calls)["summary"]["botSessions"] == 0
    # The picker lists the agent and its version whatever the filter selects.
    agent = next(a for a in out["agents"] if a["botId"] == "intake-v1")
    assert calls in agent["versions"]


def test_nothing_to_measure_is_none_not_zero(calls):
    import db

    s = db.bot_analytics("7d", "all", None, calls)["summary"]
    assert s["botSessions"] == 1
    assert s["deflection"] is None and s["deflectionEligible"] == 0
    assert s["sentimentLift"] is None and s["sentimentLiftCalls"] == 0


def test_route_takes_agent_and_version(monkeypatch):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "ba-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    res = TestClient(app_main.app).get(
        "/bot-analytics?range=30d&botId=no-such-bot&version=1",
        headers={"X-API-Key": "ba-test-key", "X-Actor-User-Id": "priya-nair"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["summary"]["botSessions"] == 0
    assert body["summary"]["containment"] is None
    assert isinstance(body["agents"], list)
