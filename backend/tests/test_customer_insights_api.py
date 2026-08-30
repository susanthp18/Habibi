"""The insights endpoint must survive its own response model.

``GET /customers/{id}/insights`` returned 500 for every customer. Nothing was
broken in the decision engine: ``derive_insights`` emitted a top-level
``treatment`` key and six per-item NBA keys that ``CustomerInsightsResponse``
and ``NbaItemResponse`` rejected under ``extra="forbid"``, and seven of the
twelve ``action`` values the engine actually produces were outside the schema
``Literal``. Every unit test in the suite asserted on the raw dict from
``derive_insights``, so nothing ever serialised it and nothing ever failed.

The endpoint test below is the one that would have caught it. The two drift
tests after it are the ones that keep it caught: the three vocabularies
(``schemas.NbaItemResponse.action``, ``NbaActionKind`` in
Habibi/src/lib/customerInsights.ts, and ``_TREATMENT_ACTION_KIND``) drifted
because nothing compared them.
"""

from __future__ import annotations

import ast
import pathlib
import typing

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "insights-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


HEADERS = {"X-API-Key": "insights-test-key", "X-Actor-User-Id": "priya-nair"}


def test_the_insights_endpoint_serialises_the_engine_row(client) -> None:
    """The endpoint 500'd for every customer. This is the regression itself.

    Deliberately does not assert *which* action the engine reaches. Whether a
    decision is held or actionable depends on the engine's mode, and other
    tests in the suite move that — asserting "wait" here passed alone and
    failed in a full run, which tests the ordering rather than the endpoint.
    What must hold is that whatever the engine decides survives
    ``extra="forbid"`` on the way out; the held case specifically is pinned
    deterministically by the test below.
    """
    import typing

    import schemas

    res = client.get("/customers/anita-desai/insights", headers=HEADERS)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["customerId"] == "anita-desai"
    assert body["treatment"] is not None, "the engine always answers; None means it raised"
    assert body["treatment"]["decisionId"]

    engine_rows = [item for item in body["nba"] if item.get("source") == "treatment_engine"]
    assert engine_rows, "the engine's row should rank first, not be absent"
    assert body["nba"][0]["source"] == "treatment_engine"

    allowed = set(typing.get_args(schemas.NbaItemResponse.model_fields["action"].annotation))
    assert engine_rows[0]["action"] in allowed


def test_a_held_decision_reaches_the_client(db_tx) -> None:
    """"wait" is the value the old Literal could not express, and a hold is
    exactly the decision an operator has to see rather than an empty card.

    Driven from a fixed engine payload rather than a live recommendation, so
    the case stays covered whatever mode the engine is in.
    """
    import db
    import schemas
    from customer_insights import derive_insights

    customer = db.get_customer("anita-desai")
    assert customer is not None, "seed is missing anita-desai"

    held = {
        "action": "wait",
        "actionLabel": "wait",
        "channel": None,
        "at": None,
        "expectedValueInr": 0.0,
        "suppressed": True,
        "reason": "shadow_mode",
        "reasonText": "The engine is deciding but not acting.",
        "rationale": "probe",
        "decisionId": "TD-HELD-PROBE",
        "propensity": 1.0,
        "policyVersion": 3,
        "mode": "shadow",
        "variant": None,
        "latencyMs": 4,
        "alternatives": [],
        "excluded": {"human_call": "outside_calling_window"},
    }

    parsed = schemas.CustomerInsightsResponse.model_validate(
        derive_insights(customer, treatment=held)
    )

    assert parsed.nba[0].action == "wait"
    assert parsed.nba[0].source == "treatment_engine"
    assert parsed.treatment is not None
    assert parsed.treatment.decisionId == "TD-HELD-PROBE"
    assert parsed.treatment.excluded == {"human_call": "outside_calling_window"}


def test_every_action_the_backend_emits_is_expressible_in_the_response(client) -> None:
    """A card kind outside the Literal is a 500, not a rendering fallback."""
    import schemas
    from customer_insights import _TREATMENT_ACTION_KIND

    allowed = set(typing.get_args(schemas.NbaItemResponse.model_fields["action"].annotation))

    # Literals assigned to an "action" key anywhere in customer_insights, read
    # out of the source rather than hand-listed: a new NBA row added there has
    # to appear here without anyone remembering to update this test.
    tree = ast.parse((BACKEND_ROOT / "customer_insights.py").read_text(encoding="utf-8"))
    emitted: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "action"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                emitted.add(value.value)

    emitted |= set(_TREATMENT_ACTION_KIND.values())
    assert emitted, "found no action literals - the AST walk stopped working"

    missing = sorted(emitted - allowed)
    assert missing == [], f"emitted by customer_insights but not in the Literal: {missing}"


def test_the_treatment_snapshot_model_matches_what_the_engine_sends() -> None:
    """to_payload() is the contract. A key added there must land here.

    Built from a real ``TreatmentResult`` rather than a hand-written key list,
    so the test tracks the dataclass instead of a copy of it.
    """
    import schemas
    from agent_core.treatment.engine import TreatmentResult
    from agent_core.treatment.scoring import ScoredAction

    alt = ScoredAction(
        action="sms",
        channel="sms",
        at=None,
        expected_value=12.5,
        p_reach=0.4,
        p_resolve=0.1,
        cost=0.42,
        explanation="probe",
    )
    payload = TreatmentResult(alternatives=[alt]).to_payload()

    missing = sorted(set(payload) - set(schemas.TreatmentSnapshotResponse.model_fields))
    assert missing == [], f"to_payload() emits keys the response model forbids: {missing}"

    alt_missing = sorted(
        set(payload["alternatives"][0]) - set(schemas.TreatmentAlternativeResponse.model_fields)
    )
    assert alt_missing == [], f"to_log() emits keys the response model forbids: {alt_missing}"

    # Round-trips under extra="forbid" - the property that caught the original bug.
    assert schemas.TreatmentSnapshotResponse.model_validate(payload).action == payload["action"]
