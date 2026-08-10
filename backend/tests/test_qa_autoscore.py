"""The bot scores its own calls, and a human reviews the scores.

``qa_scorecard_entries.ai_suggested_score`` shipped with the QA screens and
nothing ever populated it; ``qa_scorecards.status`` already allowed
``ai_draft``. The socket was built and left empty, so a reviewer could score one
call while several hundred went unscored.

Two of these tests exist because of specific traps in the existing scoring code
that would silently publish wrong bands:

* ``db._qa_section_total`` reads ``final_score``, not ``ai_suggested_score`` —
  writing only the AI column scores every call 0 and bands it red;
* ``db._qa_compute_total`` scores a *missing* criterion as 0 against its full
  weight, so a truncated model response produces a confident red band the model
  never asserted.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

import db
import qa_autoscore


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture
def rubric():
    tree = db.load_rubric_tree()
    assert tree, "seed must provide a rubric"
    return tree


@pytest.fixture
def interaction(db_tx) -> str:
    ix = f"IX-QA-{uuid.uuid4().hex[:8].upper()}"
    customer = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel,
               status, started_at, ended_at)
            VALUES (:id, :t, :c, 'bot', (SELECT id FROM bots LIMIT 1),
                    'voice', 'completed', now() - interval '20 minutes',
                    now() - interval '10 minutes')
            """
        ),
        {"id": ix, "t": db.TENANT_ID, "c": customer},
    )
    turns = [
        ("bot", "This call is recorded for quality. I'm calling about your account."),
        ("customer", "paisa nahi hai abhi, naukri chali gayi"),
        ("bot", "I understand. Can we look at a date that works for you?"),
        ("customer", "next Friday theek rahega"),
    ]
    for idx, (speaker, body) in enumerate(turns, start=1):
        db_tx.execute(
            text(
                """
                INSERT INTO interaction_transcript
                  (id, interaction_id, turn_index, speaker, at_sec, text)
                VALUES (:id, :ix, :ti, :sp, :ti, :tx)
                """
            ),
            {"id": f"{ix}-T{idx}", "ix": ix, "ti": idx, "sp": speaker, "tx": body},
        )
    return ix


def _response(scores: list[dict]):
    return {
        "content": "",
        "toolCalls": [
            {"id": "1", "name": "submit_qa_scores", "arguments": json.dumps({"scores": scores})}
        ],
        "finishReason": "tool_calls",
    }


def _full_scores(rubric, value: float = 4.0):
    return [
        {"criterionId": c["id"], "score": value, "note": "" if value == 5 else "minor gap"}
        for s in rubric["sections"]
        for c in s["criteria"]
    ]


@pytest.fixture
def fake_llm(monkeypatch):
    import azure_openai

    state: dict = {"response": None, "raises": None, "calls": []}

    def _fake(messages, **kwargs):
        state["calls"].append({"messages": messages, **kwargs})
        if state["raises"] is not None:
            raise state["raises"]
        return state["response"]

    monkeypatch.setattr(azure_openai, "chat_with_tools", _fake)
    return state


# ---------------------------------------------------------------------------
# The happy path, and the two traps
# ---------------------------------------------------------------------------


def _stored(db_tx, interaction: str) -> dict:
    """The persisted row — the screen shape omits total_score and band."""
    return dict(
        db_tx.execute(
            text(
                "SELECT status, total_score, band FROM qa_scorecards "
                "WHERE interaction_id = :ix"
            ),
            {"ix": interaction},
        ).mappings().first()
        or {}
    )


def test_writes_an_ai_draft_scorecard(db_tx, interaction, rubric, fake_llm) -> None:
    fake_llm["response"] = _response(_full_scores(rubric, 4.0))

    card = qa_autoscore.score_interaction(interaction)

    assert card is not None
    assert card["status"] == "ai_draft"
    # The whole point: a real total, not the 0/red an ai_suggested-only write
    # would produce.
    stored = _stored(db_tx, interaction)
    assert float(stored["total_score"]) > 0
    assert stored["band"] in {"green", "amber", "red"}


def test_both_score_columns_are_written(db_tx, interaction, rubric, fake_llm) -> None:
    """_qa_section_total reads final_score, NOT ai_suggested_score.

    Writing only the AI column computes a total of 0, bands it red, and trips
    the critical-fail cap at 40 — on every single call.
    """
    fake_llm["response"] = _response(_full_scores(rubric, 5.0))

    qa_autoscore.score_interaction(interaction)

    rows = db_tx.execute(
        text(
            """
            SELECT e.ai_suggested_score, e.final_score, e.accepted
              FROM qa_scorecard_entries e
              JOIN qa_scorecards s ON s.id = e.scorecard_id
             WHERE s.interaction_id = :ix
            """
        ),
        {"ix": interaction},
    ).mappings().all()

    assert rows
    for r in rows:
        assert r["ai_suggested_score"] is not None
        assert r["final_score"] is not None
        # Unreviewed. `ai_draft` + accepted IS NULL is the state the QA screen
        # already renders as "needs review".
        assert r["accepted"] is None


def test_partial_coverage_writes_nothing(db_tx, interaction, rubric, fake_llm) -> None:
    """_qa_compute_total scores a missing criterion as 0 against full weight.

    So a truncated response would publish a red band the model never asserted.
    """
    half = _full_scores(rubric, 5.0)
    fake_llm["response"] = _response(half[: max(1, len(half) // 2)])

    assert qa_autoscore.score_interaction(interaction) is None

    count = db_tx.execute(
        text("SELECT count(*) FROM qa_scorecards WHERE interaction_id = :ix"),
        {"ix": interaction},
    ).scalar()
    assert count == 0


def test_critical_zero_caps_the_total(db_tx, interaction, rubric, fake_llm) -> None:
    criteria = [c for s in rubric["sections"] for c in s["criteria"]]
    critical = next((c for c in criteria if c.get("critical")), None)
    if critical is None:
        pytest.skip("seed rubric has no critical criterion")

    scores = _full_scores(rubric, 5.0)
    for row in scores:
        if row["criterionId"] == critical["id"]:
            row["score"] = 0
    fake_llm["response"] = _response(scores)

    card = qa_autoscore.score_interaction(interaction)

    assert card is not None
    assert float(_stored(db_tx, interaction)["total_score"]) <= 40.0


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_unknown_criteria_are_dropped(db_tx, interaction, rubric, fake_llm) -> None:
    scores = _full_scores(rubric, 4.0)
    scores.append({"criterionId": "criterion-the-model-invented", "score": 5})
    fake_llm["response"] = _response(scores)

    qa_autoscore.score_interaction(interaction)

    ids = db_tx.execute(
        text(
            "SELECT e.criterion_id FROM qa_scorecard_entries e "
            "JOIN qa_scorecards s ON s.id = e.scorecard_id WHERE s.interaction_id = :ix"
        ),
        {"ix": interaction},
    ).scalars().all()

    assert "criterion-the-model-invented" not in ids


@pytest.mark.parametrize("bad", [99, -4, "excellent", None])
def test_out_of_range_scores_are_clamped_or_dropped(
    db_tx, interaction, rubric, fake_llm, bad
) -> None:
    scores = _full_scores(rubric, 4.0)
    scores[0]["score"] = bad
    fake_llm["response"] = _response(scores)

    qa_autoscore.score_interaction(interaction)

    values = db_tx.execute(
        text(
            "SELECT e.final_score FROM qa_scorecard_entries e "
            "JOIN qa_scorecards s ON s.id = e.scorecard_id WHERE s.interaction_id = :ix"
        ),
        {"ix": interaction},
    ).scalars().all()

    assert all(0 <= float(v) <= 5 for v in values)


# ---------------------------------------------------------------------------
# Degradation
# ---------------------------------------------------------------------------


def test_azure_busy_propagates_so_the_batch_stops(db_tx, interaction, fake_llm) -> None:
    """A live call outranks QA for every Azure slot."""
    import azure_openai

    fake_llm["raises"] = azure_openai.AzureBusyError("saturated")

    with pytest.raises(azure_openai.AzureBusyError):
        qa_autoscore.score_interaction(interaction)


def test_other_failures_return_none(db_tx, interaction, fake_llm) -> None:
    fake_llm["raises"] = RuntimeError("circuit open")

    assert qa_autoscore.score_interaction(interaction) is None


def test_malformed_response_writes_nothing(db_tx, interaction, fake_llm) -> None:
    fake_llm["response"] = {"content": "sure thing", "toolCalls": []}

    assert qa_autoscore.score_interaction(interaction) is None


def test_short_transcript_is_skipped(db_tx, fake_llm) -> None:
    ix = f"IX-QA-{uuid.uuid4().hex[:8].upper()}"
    customer = db_tx.execute(text("SELECT id FROM customers LIMIT 1")).scalar()
    db_tx.execute(
        text(
            """
            INSERT INTO interactions
              (id, tenant_id, customer_id, handler_kind, handler_bot_id, channel, status)
            VALUES (:id, :t, :c, 'bot', (SELECT id FROM bots LIMIT 1), 'voice', 'completed')
            """
        ),
        {"id": ix, "t": db.TENANT_ID, "c": customer},
    )

    assert qa_autoscore.score_interaction(ix) is None
    assert fake_llm["calls"] == []


def test_existing_scorecard_is_not_overwritten(db_tx, interaction, rubric, fake_llm) -> None:
    """A human's review always wins."""
    fake_llm["response"] = _response(_full_scores(rubric, 5.0))
    db.create_scorecard({"interactionId": interaction, "status": "final", "entries": []})

    assert qa_autoscore.score_interaction(interaction) is None


# ---------------------------------------------------------------------------
# PII
# ---------------------------------------------------------------------------


def test_identifiers_never_reach_the_model(db_tx, interaction, rubric, fake_llm) -> None:
    db_tx.execute(
        text("UPDATE interaction_transcript SET text = :t WHERE interaction_id = :ix AND turn_index = 2"),
        {"t": "my mobile is 9876543210 and card 4111 1111 1111 1111", "ix": interaction},
    )
    fake_llm["response"] = _response(_full_scores(rubric, 4.0))

    qa_autoscore.score_interaction(interaction)

    sent = json.dumps(fake_llm["calls"][0]["messages"])
    assert "9876543210" not in sent
    assert "4111" not in sent


def test_transcript_is_fenced_as_untrusted(db_tx, interaction, rubric, fake_llm) -> None:
    fake_llm["response"] = _response(_full_scores(rubric, 4.0))

    qa_autoscore.score_interaction(interaction)

    user_msg = fake_llm["calls"][0]["messages"][-1]["content"]
    assert "UNTRUSTED" in user_msg


def test_uses_the_analysis_profile(db_tx, interaction, rubric, fake_llm) -> None:
    import azure_openai

    fake_llm["response"] = _response(_full_scores(rubric, 4.0))

    qa_autoscore.score_interaction(interaction)

    assert fake_llm["calls"][0]["profile"] == azure_openai.PROFILE_ANALYSIS


# ---------------------------------------------------------------------------
# Batch selection
# ---------------------------------------------------------------------------


def test_pending_excludes_already_scored(db_tx, interaction, rubric) -> None:
    assert interaction in qa_autoscore.pending_interactions(limit=50)

    db.create_scorecard({"interactionId": interaction, "status": "ai_draft", "entries": []})

    assert interaction not in qa_autoscore.pending_interactions(limit=50)


def test_pending_excludes_human_handled(db_tx, interaction) -> None:
    """Auto-scoring a human agent is a people decision, not an engineering one."""
    db_tx.execute(
        text(
            "UPDATE interactions SET handler_kind = 'human', handler_bot_id = NULL, "
            "handler_user_id = (SELECT id FROM users LIMIT 1) WHERE id = :ix"
        ),
        {"ix": interaction},
    )

    assert interaction not in qa_autoscore.pending_interactions(limit=50)


def test_pending_excludes_a_call_that_just_ended(db_tx, interaction) -> None:
    """The CrmSink's `complete` job and transcript export need to land first."""
    db_tx.execute(
        text("UPDATE interactions SET ended_at = now() WHERE id = :ix"), {"ix": interaction}
    )

    assert interaction not in qa_autoscore.pending_interactions(limit=50)


def test_flag_off_scores_nothing(db_tx, monkeypatch) -> None:
    monkeypatch.setenv("QA_AUTOSCORE_ENABLED", "false")
    assert qa_autoscore.score_pending() == 0
