"""The Inbox list polls every few seconds; it must not evaluate the contact Gate per thread.

``context`` (four reads and a Gate evaluation) is on the thread detail and on
every write's response; the list omits it and reads in a fixed number of
statements however many threads there are.
"""

from __future__ import annotations

import pytest
from sqlalchemy import event

import db
import db_core


@pytest.fixture
def statements(db_tx):
    seen: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(db_core.engine, "before_cursor_execute", _count)
    try:
        yield seen
    finally:
        event.remove(db_core.engine, "before_cursor_execute", _count)


def test_the_list_omits_context_and_reads_in_bounded_statements(statements) -> None:
    rows = db.list_conversations()
    if len(rows) < 2:
        pytest.skip("the dev DB seeds conversations")
    assert all(r["context"] is None for r in rows)
    # base rows, messages, suggestions (three), typing, plus the transaction bookkeeping
    assert len(statements) <= 12, len(statements)


def test_the_detail_carries_context(db_tx) -> None:
    rows = db.list_conversations()
    if not rows:
        pytest.skip("the dev DB seeds conversations")
    detail = db.get_conversation(rows[0]["id"])
    assert detail is not None
    assert detail["context"] is not None
    assert "contactableNow" in detail["context"]
