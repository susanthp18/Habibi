"""A response model must not be narrower than the column it serialises.

``ConversationListResponse.channel`` allowed ``whatsapp | sms | email`` while
the ``conversations.channel`` CHECK constraint allowed those plus ``chat`` and
``voice``. The gap was invisible until something wrote a row on one of the
missing channels — and because ``response_model=list[...]`` validates the whole
list, the first voice conversation ever created did not render as one odd row.
It raised ``ResponseValidationError`` and took ``GET /conversations`` to a 500,
which the inbox surfaced as "Failed to load inbox: Failed to fetch". One
sandbox call made the entire screen unreachable.

The database constraint is the authority: it is what actually decides which
values can exist. These tests read it out of ``sql/`` and hold the Pydantic
literals to it, so widening the constraint without widening the schema fails
here rather than in someone's browser.
"""

from __future__ import annotations

import re
import typing
from pathlib import Path

import pytest

from schemas import ConversationListResponse

_SQL = Path(__file__).resolve().parents[1] / "sql" / "04_interactions.sql"


def _check_values(table: str, column: str) -> set[str]:
    """The value set a column's CHECK ... IN (...) constraint permits."""
    sql = _SQL.read_text(encoding="utf-8")
    create = re.search(
        rf"CREATE TABLE IF NOT EXISTS {table}\s*\((.*?)\n\);",
        sql,
        re.S,
    )
    assert create, f"{table} not found in {_SQL.name}"
    clause = re.search(
        rf"\b{column}\s+TEXT[^,]*?CHECK\s*\(\s*{column}\s+IN\s*\(([^)]*)\)",
        create.group(1),
        re.S | re.I,
    )
    assert clause, f"no CHECK ... IN constraint on {table}.{column}"
    return set(re.findall(r"'([^']+)'", clause.group(1)))


def _literal_values(field: str) -> set[str]:
    annotation = ConversationListResponse.model_fields[field].annotation
    args = typing.get_args(annotation)
    assert args, f"{field} is not a Literal"
    return set(args)


@pytest.mark.parametrize("field", ["channel", "status"])
def test_response_literal_matches_the_database_constraint(field: str) -> None:
    allowed = _check_values("conversations", field)
    declared = _literal_values(field)
    missing = allowed - declared
    assert not missing, (
        f"conversations.{field} permits {sorted(missing)}, which "
        f"ConversationListResponse.{field} rejects. A single row with one of "
        f"those values 500s GET /conversations and blanks the whole inbox."
    )


def test_voice_is_a_conversation_channel() -> None:
    """The regression itself: a voice call writes a conversation row."""
    assert "voice" in _literal_values("channel")
    assert "voice" in _check_values("conversations", "channel")


def test_the_schema_does_not_invent_channels_the_database_forbids() -> None:
    """Drift in the other direction: a value the DB would reject on write."""
    extra = _literal_values("channel") - _check_values("conversations", "channel")
    assert not extra, f"schema accepts {sorted(extra)} that the constraint rejects"
