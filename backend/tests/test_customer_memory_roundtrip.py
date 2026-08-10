"""customer_memory against a real database — write, read, render, purge.

tests/test_customer_memory.py covers the filters and rendering in isolation.
This covers the SQL: the upsert's ON CONFLICT arithmetic, the commitment
queries' column names (which did not match the tables on the first attempt —
promises has ``promised_at``, not ``promised_date``), and the retention delete.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from voice import memory


def _pick_customer() -> str:
    import db

    customers = db.list_customers()
    if not customers:
        pytest.skip("no customers seeded")
    return customers[0]["id"]


@pytest.fixture
def customer_id():
    import db

    cid = _pick_customer()
    with db.engine.begin() as conn:
        conn.execute(text("DELETE FROM customer_memory WHERE customer_id = :c"), {"c": cid})
    try:
        yield cid
    finally:
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM customer_memory WHERE customer_id = :c"), {"c": cid})


def test_open_commitments_queries_run_against_the_real_schema(customer_id: str) -> None:
    """Every column name in the four queries must exist, or the memory silently
    degrades to empty for that kind."""
    rows = memory.open_commitments(customer_id)
    assert isinstance(rows, list)
    for row in rows:
        assert row["kind"] in {"promise", "dispute", "callback", "document"}
        assert row.get("id")


def test_open_commitments_come_from_sql_not_the_llm(
    customer_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The authoritative half must not depend on Azure being reachable."""
    import azure_openai

    def _boom(*_a, **_kw):
        raise RuntimeError("azure down")

    monkeypatch.setattr(azure_openai, "chat_complete", _boom)

    commitments = memory.open_commitments(customer_id)
    memory.upsert_memory(
        customer_id=customer_id,
        summary=memory.summarize_call(interaction_id="IX-nope", customer_id=customer_id),
        open_commitments=commitments,
    )

    loaded = memory.load_memory(customer_id)
    assert loaded is not None
    assert loaded["summary"] is None, "a failed summariser must store NULL, not a stub"
    assert len(loaded["open_commitments"]) == len(commitments)


def test_upsert_is_idempotent_and_counts_calls(customer_id: str) -> None:
    memory.upsert_memory(customer_id=customer_id, summary="First call.", open_commitments=[])
    first = memory.load_memory(customer_id)
    memory.upsert_memory(customer_id=customer_id, summary="Second call.", open_commitments=[])
    second = memory.load_memory(customer_id)

    assert first["call_count"] == 1
    assert second["call_count"] == 2, "ON CONFLICT must increment, not reset"
    assert second["summary"] == "Second call."


def test_open_commitments_defaults_to_an_empty_array_never_null(customer_id: str) -> None:
    """So it can never render as the literal string "null" inside a prompt."""
    import db

    with db.engine.begin() as conn:
        conn.execute(
            text("INSERT INTO customer_memory (customer_id) VALUES (:c)"), {"c": customer_id}
        )
    loaded = memory.load_memory(customer_id)
    assert loaded["open_commitments"] == []


def test_round_trip_renders_a_memory_message(customer_id: str) -> None:
    memory.upsert_memory(
        customer_id=customer_id,
        summary="Caller asked to be contacted in Hindi.",
        open_commitments=[{"kind": "promise", "id": "PR-X", "status": "upcoming"}],
        last_sentiment=0.25,
        last_channel="smallwebrtc",
    )
    msg = memory.memory_message(memory.load_memory(customer_id))
    assert msg is not None
    assert "PR-X" in msg["content"]
    assert "Hindi" in msg["content"]
    assert "NOT authoritative" in msg["content"]


def test_purge_stale_removes_only_expired_rows(customer_id: str) -> None:
    import db

    memory.upsert_memory(customer_id=customer_id, summary="Recent.", open_commitments=[])
    # Age this row past the TTL without touching anyone else's.
    with db.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE customer_memory SET updated_at = now() - interval '400 days' "
                "WHERE customer_id = :c"
            ),
            {"c": customer_id},
        )

    dropped = memory.purge_stale(180 * 24 * 3600)

    assert dropped >= 1
    assert memory.load_memory(customer_id) is None


def test_load_memory_of_an_unknown_customer_is_none() -> None:
    assert memory.load_memory(f"C-{uuid.uuid4().hex[:8]}") is None
