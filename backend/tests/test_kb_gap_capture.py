"""The bot records what it could not answer.

``unanswered_questions`` and the whole gap→FAQ→prompt-version workflow above it
(``GET /kb/gaps``, ``POST /kb/gaps/{id}/link``, ``POST /kb/faqs`` with ``gapId``,
``AnalyticsGapsTable``, ``UnansweredTable``) shipped against hand-seeded rows —
nothing outside ``seed_postgres`` ever wrote to the table. So the KB-gap screen
could display demo data and nothing else, and a live caller asking something the
corpus does not cover left no trace at all.

These tests pin the writer and, just as importantly, the four cases that must
*not* create a gap. A gap table that fills with infrastructure failures and
speculative prefetches is worse than an empty one: it buries the real signal.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from agent_core.tools import kb


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRetrieve:
    def __init__(self, rows=None, raises=None):
        self.calls: list[dict] = []
        self._rows = [] if rows is None else rows
        self._raises = raises

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        return {"results": self._rows, "latencyMs": 5, "logId": "LOG-1"}


def _rows(top: float):
    return [
        {
            "chunkId": "CH-1",
            "docTitle": "Doc",
            "docType": "policy",
            "heading": "H",
            "snippet": "text",
            "score": top,
        }
    ]


@pytest.fixture
def gap_enabled(monkeypatch):
    monkeypatch.setenv("KB_GAP_CAPTURE_ENABLED", "true")
    monkeypatch.delenv("KB_GAP_THRESHOLD", raising=False)


@pytest.fixture
def captured(monkeypatch):
    """Capture db.record_kb_gap calls without touching the database."""
    import db

    calls: list[dict] = []
    monkeypatch.setattr(db, "record_kb_gap", lambda **kw: calls.append(kw) or "GAP-X")
    return calls


def _search(**overrides):
    kwargs = {
        "query": "does the policy cover a cracked windscreen",
        "channel": "text",
        "interaction_id": "IX-1",
        "apply_intent_gate": False,
        "should_expand_query": False,
        "record_offer": False,
    }
    kwargs.update(overrides)
    return kb.search_knowledge_base(**kwargs)


# ---------------------------------------------------------------------------
# A gap is recorded
# ---------------------------------------------------------------------------


def test_no_results_records_a_gap(monkeypatch, gap_enabled, captured):
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=[]))

    result = _search()

    assert result.ok is True
    assert result.data["results"] == []
    assert len(captured) == 1
    assert captured[0]["question"] == "does the policy cover a cracked windscreen"
    assert captured[0]["interaction_id"] == "IX-1"


def test_weak_results_record_a_gap(monkeypatch, gap_enabled, captured):
    """Hits exist but score below the threshold — the corpus nearly has it."""
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=_rows(0.41)))

    result = _search()

    assert result.data["confident"] is False
    assert len(captured) == 1


def test_the_gap_stores_the_callers_words_not_the_expanded_query(
    monkeypatch, gap_enabled, captured
):
    """An operator reading the screen needs the question, not our rewrite."""
    import kb_retrieve

    fake = _FakeRetrieve(rows=[])
    monkeypatch.setattr(kb_retrieve, "retrieve", fake)
    monkeypatch.setattr(kb, "expand_query", lambda q, **kw: q + " insurance policy coverage")

    _search(should_expand_query=True)

    assert fake.calls[0]["query"].endswith("insurance policy coverage")
    assert captured[0]["question"] == "does the policy cover a cracked windscreen"


# ---------------------------------------------------------------------------
# A gap is NOT recorded
# ---------------------------------------------------------------------------


def test_confident_answer_records_nothing(monkeypatch, gap_enabled, captured):
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=_rows(0.93)))

    result = _search()

    assert result.data["confident"] is True
    assert captured == []


def test_retrieval_failure_is_not_a_content_gap(monkeypatch, gap_enabled, captured):
    """An Azure/DB outage must not manufacture hundreds of phantom gaps."""
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(raises=RuntimeError("boom")))

    result = _search()

    assert result.ok is False
    assert result.error == "retrieval_failed"
    assert captured == []


def test_stale_snapshot_is_not_a_content_gap(monkeypatch, gap_enabled, captured):
    import kb_retrieve

    monkeypatch.setattr(
        kb_retrieve, "retrieve", _FakeRetrieve(raises=ValueError("unknown snapshot"))
    )

    result = _search()

    assert result.error == "retrieval_unavailable"
    assert captured == []


def test_intent_gated_question_is_not_a_gap(monkeypatch, gap_enabled, captured):
    """A money question routed away from the corpus is the gate working."""
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=[]))

    result = _search(
        query="what is my outstanding balance",
        apply_intent_gate=True,
        intent="balance_query",
    )

    assert result.data["reason"] == "kb_gated_for_intent"
    assert captured == []


def test_no_interaction_id_records_nothing(monkeypatch, gap_enabled, captured):
    """Excludes the operator's POST /kb/retrieve test panel by construction."""
    import kb_retrieve

    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=[]))

    _search(interaction_id=None)

    assert captured == []


def test_flag_off_records_nothing(monkeypatch, captured):
    import kb_retrieve

    monkeypatch.setenv("KB_GAP_CAPTURE_ENABLED", "false")
    monkeypatch.setattr(kb_retrieve, "retrieve", _FakeRetrieve(rows=[]))

    _search()

    assert captured == []


def test_speculative_prefetch_never_reaches_this_handler():
    """The two non-customer retrieval callers bypass the shared handler.

    ``voice/kb_enrich.py`` (speculative prefetch, discarded most of the time)
    and ``POST /kb/retrieve`` (the operator's KB test panel) both call
    ``kb_retrieve.retrieve`` directly. That is what keeps a wasted prefetch and
    an operator's experiment out of the gap table — without it, the KB screen
    would fill with questions no customer ever asked.

    The exclusion is structural rather than a flag, so it is worth pinning: a
    refactor that routes either through ``search_knowledge_base`` has to decide
    what to do about gaps rather than silently poisoning the table.
    """
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    for relative in ("voice/kb_enrich.py", "main.py"):
        source = (backend / relative).read_text(encoding="utf-8")
        assert "search_knowledge_base(" not in source, (
            f"{relative} now calls search_knowledge_base — decide whether its "
            "retrievals should create KB gaps before allowing this"
        )


# ---------------------------------------------------------------------------
# db.record_kb_gap — upsert semantics
# ---------------------------------------------------------------------------


def _gap_row(conn, gap_id: str) -> dict:
    row = conn.execute(
        text(
            "SELECT question, hit_count, top_intent, suggested_fix_type "
            "FROM unanswered_questions WHERE id = :id"
        ),
        {"id": gap_id},
    ).mappings().first()
    return dict(row) if row else {}


def test_record_kb_gap_inserts_then_increments(db_tx):
    import db

    first = db.record_kb_gap(
        question="what happens if I miss two EMIs in a row",
        intent="product_faq",
        channel="whatsapp",
    )
    assert first is not None
    assert _gap_row(db_tx, first)["hit_count"] == 1

    # Same question, different case and spacing — one row, not two.
    second = db.record_kb_gap(
        question="  What Happens If I Miss Two EMIs In A Row  ",
        intent="balance_query",
        channel="voice",
    )

    assert second == first
    row = _gap_row(db_tx, first)
    assert row["hit_count"] == 2
    # First intent wins: one off-topic sighting must not relabel a gap.
    assert row["top_intent"] == "product_faq"


def test_record_kb_gap_does_not_revert_operator_triage(db_tx):
    """suggested_fix_type is an operator decision, not a per-sighting field."""
    import db

    gap_id = db.record_kb_gap(question="is a windscreen chip covered", channel="voice")
    db_tx.execute(
        text("UPDATE unanswered_questions SET suggested_fix_type = 'prompt' WHERE id = :id"),
        {"id": gap_id},
    )

    db.record_kb_gap(question="Is a windscreen chip covered", channel="voice")

    assert _gap_row(db_tx, gap_id)["suggested_fix_type"] == "prompt"


def test_record_kb_gap_redacts_identifiers(db_tx):
    import db

    gap_id = db.record_kb_gap(
        question="my card 4111 1111 1111 1111 was charged twice, is that covered",
        channel="whatsapp",
    )

    stored = _gap_row(db_tx, gap_id)["question"]
    assert "4111" not in stored
    assert "covered" in stored


def test_record_kb_gap_collapses_placeholder_intents(db_tx):
    """The KB gate emits "unknown" when no intent resolved (always, on voice).

    Stored verbatim that becomes a literal "unknown" bucket on the gap screen,
    sitting beside the "other" bucket NULL already renders as.
    """
    import db

    gap_id = db.record_kb_gap(
        question="is flood damage to a parked car covered",
        intent="unknown",
        channel="voice",
    )

    assert _gap_row(db_tx, gap_id)["top_intent"] is None


def test_record_kb_gap_ignores_fragments(db_tx):
    """"ok", "haan", a barge-in fragment — not content gaps."""
    import db

    assert db.record_kb_gap(question="ok", channel="voice") is None
    assert db.record_kb_gap(question="   ", channel="voice") is None


def test_record_kb_gap_truncates(db_tx):
    import db

    gap_id = db.record_kb_gap(question="cover " * 200, channel="voice")

    assert len(_gap_row(db_tx, gap_id)["question"]) <= db.KB_GAP_MAX_CHARS


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def test_purge_keeps_linked_and_repeated_gaps(db_tx):
    """analytics_kb_gap_links cascades from this table — a linked gap is the
    record that someone already fixed it, and must survive retention."""
    import db

    once = db.record_kb_gap(question="does the plan cover overseas dental", channel="voice")
    twice = db.record_kb_gap(question="does the plan cover baggage delay", channel="voice")
    db.record_kb_gap(question="does the plan cover baggage delay", channel="voice")
    linked = db.record_kb_gap(question="does the plan cover rental car excess", channel="voice")

    db_tx.execute(
        text(
            "INSERT INTO analytics_kb_gap_links (id, unanswered_question_id) "
            "VALUES ('GL-TEST-1', :gid)"
        ),
        {"gid": linked},
    )
    db_tx.execute(
        text("UPDATE unanswered_questions SET last_seen_at = now() - interval '200 days'")
    )

    removed = db.purge_stale_kb_gaps(ttl_days=90)

    assert removed == 1
    assert _gap_row(db_tx, once) == {}
    assert _gap_row(db_tx, twice)["hit_count"] == 2
    assert _gap_row(db_tx, linked) != {}


def test_purge_keeps_recent_gaps(db_tx):
    import db

    gap_id = db.record_kb_gap(question="does the plan cover trip cancellation", channel="voice")

    assert db.purge_stale_kb_gaps(ttl_days=90) == 0
    assert _gap_row(db_tx, gap_id) != {}
