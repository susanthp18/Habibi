"""QA rubric edits are versions, and the QA KPIs count what they say.

A rubric edit must never change what an existing scorecard means: it creates
a new rubric row that new scorecards use, while old scorecards keep loading
their own tree. An unchanged criterion keeps its lineage across versions.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import text


def _body(sections):
    from schemas import RubricVersionCreateRequest

    return RubricVersionCreateRequest.model_validate({"sections": sections})


def _crit(label, weight, **kw):
    return {"label": label, "description": "", "weight": weight, **kw}


def test_weights_must_sum_to_100():
    ok = _body([
        {"label": "A", "weight": 60, "criteria": [_crit("a1", 50), _crit("a2", 50)]},
        {"label": "B", "weight": 40, "criteria": [_crit("b1", 100)]},
    ])
    assert len(ok.sections) == 2
    with pytest.raises(ValidationError, match="section weights must sum to 100"):
        _body([{"label": "A", "weight": 90, "criteria": [_crit("a1", 100)]}])
    with pytest.raises(ValidationError, match="criterion weights in section 'A'"):
        _body([{"label": "A", "weight": 100, "criteria": [_crit("a1", 60), _crit("a2", 30)]}])
    with pytest.raises(ValidationError):  # a section needs a criterion
        _body([{"label": "A", "weight": 100, "criteria": []}])
    with pytest.raises(ValidationError):  # and a blank label is no criterion
        _body([{"label": "A", "weight": 100, "criteria": [_crit("  ", 100)]}])


def _sections(tree):
    return [
        {
            "label": s["label"],
            "weight": s["weight"],
            "criteria": [
                {"id": c["id"], "label": c["label"], "description": c["description"],
                 "weight": c["weight"], "critical": bool(c.get("critical"))}
                for c in s["criteria"]
            ],
        }
        for s in tree["sections"]
    ]


def test_edit_creates_active_version_and_keeps_the_old_tree(db_tx):
    import db

    old = db.get_rubric()
    sections = _sections(old)
    kept, reworded = sections[0]["criteria"][0], sections[0]["criteria"][1]
    reworded["label"] = reworded["label"] + " (reworded)"
    kept["weight"], reworded["weight"] = reworded["weight"], kept["weight"]  # weights alone keep lineage

    new = db.create_rubric_version(old["id"], _body(sections).model_dump()["sections"])

    assert new["id"] != old["id"] and new["name"] == old["name"]
    assert new["version"] != old["version"]
    assert db.get_rubric()["id"] == new["id"]  # the active rubric for new scorecards
    assert db.get_rubric(old["id"]) == old  # old scorecards' tree is untouched
    new_crit = {c["label"]: c for s in new["sections"] for c in s["criteria"]}
    old_crit = {c["label"]: c for s in old["sections"] for c in s["criteria"]}
    assert new_crit[kept["label"]]["id"] != kept["id"]
    assert new_crit[kept["label"]]["lineageId"] == old_crit[kept["label"]]["lineageId"]
    assert new_crit[reworded["label"]]["lineageId"] == new_crit[reworded["label"]]["id"]

    # A voice call is now scored against the new version.
    ix = db_tx.execute(
        text("SELECT id FROM interactions WHERE channel = 'voice' LIMIT 1")
    ).scalar()
    if ix:
        assert db.rubric_id_for_interaction(ix) == new["id"]

    # Editing from the superseded version would drop the new one's changes.
    with pytest.raises(ValueError, match="rubric_version_stale"):
        db.create_rubric_version(old["id"], _body(_sections(old)).model_dump()["sections"])


@pytest.fixture
def scored_call(db_tx):
    """A fresh voice call scored 0 on every critical criterion, 5 elsewhere."""
    import db

    tenant = db.current_tenant()
    cust = f"CUST-QA-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text("INSERT INTO customers_pii (id, tenant_id, name, risk) VALUES (:id, :t, 'QA test', 'low')"),
        {"id": cust, "t": tenant},
    )
    ix = f"IX-QA-{uuid.uuid4().hex[:8]}"
    db_tx.execute(
        text(
            """
            INSERT INTO interactions (id, tenant_id, customer_id, channel, direction,
              handler_kind, handler_bot_id, status, started_at, ended_at)
            VALUES (:id, :t, :c, 'voice', 'inbound', 'bot', 'intake-v1', 'completed', now(), now())
            """
        ),
        {"id": ix, "t": tenant, "c": cust},
    )
    rubric = db.get_rubric()
    criteria = [c for s in rubric["sections"] for c in s["criteria"]]
    card = db.create_scorecard({
        "interactionId": ix,
        "status": "ai_draft",
        "entries": [
            {"criterionId": c["id"], "score": 0.0 if c.get("critical") else 5.0}
            for c in criteria
        ],
    })
    return ix, card, sum(1 for c in criteria if c.get("critical"))


def test_critical_fails_counts_critical_criteria_scored_zero(db_tx, scored_call):
    import db

    _ix, card, n_critical = scored_call
    assert n_critical > 1  # else a red-card count would pass too
    before = db.qa_coverage_stats(days=7)["criticalFails"]
    db_tx.execute(
        text("UPDATE qa_scorecard_entries SET final_score = 5 WHERE scorecard_id = :id"),
        {"id": card["id"]},
    )
    assert before - db.qa_coverage_stats(days=7)["criticalFails"] == n_critical


def test_calibration_session_over_a_scored_call(db_tx, scored_call):
    import db

    ix, card, _n = scored_call
    reviewers = db_tx.execute(
        text("SELECT id FROM users WHERE tenant_id = :t ORDER BY id LIMIT 2"),
        {"t": db.current_tenant()},
    ).scalars().all()
    session = db.create_calibration_session(ix, [*reviewers, reviewers[0]])
    assert session["callId"] == ix and session["status"] == "active"
    assert session["rubricId"] == card["rubricId"]
    assert [r["submitted"] for r in session["reviewers"]] == [False] * len(reviewers)
    target = {e["criterionId"]: e["score"] for e in session["target"]}
    assert target == {e["criterionId"]: e["score"] for e in card["entries"]}

    with pytest.raises(ValueError, match="calibration_reviewers_required"):
        db.create_calibration_session(ix, [])
    with pytest.raises(KeyError):
        db.create_calibration_session(ix, ["no-such-user"])


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import actor_context
    import main as app_main

    monkeypatch.setenv("API_KEY", "qa-rubric-test-key")
    monkeypatch.delenv("API_KEY_MAP", raising=False)
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("ALLOW_ACTOR_HEADER", "true")
    actor_context.reload_api_key_map()
    return TestClient(app_main.app)


def test_route_refuses_bad_weights_before_writing(client):
    res = client.post(
        "/qa/rubrics/rubric-v1/versions",
        json={"sections": [{"label": "A", "weight": 100, "criteria": [_crit("a1", 40)]}]},
        headers={"X-API-Key": "qa-rubric-test-key", "X-Actor-User-Id": "priya-nair"},
    )
    assert res.status_code == 422, res.text
    assert "criterion weights" in res.text
