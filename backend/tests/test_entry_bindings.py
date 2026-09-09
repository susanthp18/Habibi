"""The Door's routing seam, before any caller is switched.

`runtime_entry_bot_id()` takes no arguments — not the channel, not the dialled
number — so every inbound contact on every channel resolves the same card.
`resolve_entry` is its replacement, and the property that matters most here is
what it does when it is *not* sure: a door that guesses when it cannot read its
own bindings routes calls to an arbitrary card.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import text

import db
from agent_core.cards.routing import door_enabled, resolve_entry, runtime_entry_bot_id

_SQL = Path(__file__).resolve().parents[1] / "sql" / "29_entry_bindings.sql"


@pytest.fixture
def door_on(monkeypatch):
    monkeypatch.setenv("DOOR_ENABLED", "1")
    assert door_enabled()


def _create_table(conn) -> None:
    conn.execute(text(_SQL.read_text(encoding="utf-8")))


def test_the_flag_off_is_todays_behaviour_exactly(monkeypatch) -> None:
    monkeypatch.delenv("DOOR_ENABLED", raising=False)
    assert resolve_entry("voice", "+914412345678") == runtime_entry_bot_id()
    assert resolve_entry("whatsapp") == runtime_entry_bot_id()


def test_an_absent_table_falls_back_rather_than_raising(db_tx, door_on) -> None:
    """The migration ships unapplied, so this is the live shape today."""
    db_tx.execute(text("DROP TABLE IF EXISTS entry_bindings"))
    assert resolve_entry("voice", "+914412345678") == runtime_entry_bot_id()


def test_an_empty_table_falls_back(db_tx, door_on) -> None:
    _create_table(db_tx)
    assert resolve_entry("voice", "+914412345678") == runtime_entry_bot_id()


def test_the_dialled_number_chooses_the_card(db_tx, door_on) -> None:
    _create_table(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO entry_bindings (id, tenant_id, channel, address, bot_id)
            VALUES ('EB-1', :t, 'voice', '+914412345678', 'intake-v1')
            """
        ),
        {"t": db.current_tenant()},
    )
    assert resolve_entry("voice", "+914412345678") == "intake-v1"
    # A number nobody bound is not this door's business.
    assert resolve_entry("voice", "+919999999999") == runtime_entry_bot_id()


def test_the_exact_address_beats_the_channel_default(db_tx, door_on) -> None:
    """Most-specific-first. Without the ORDER BY the planner picks either row."""
    _create_table(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO entry_bindings (id, tenant_id, channel, address, bot_id)
            VALUES ('EB-D', :t, 'voice', NULL,               'kaia-v2-4'),
                   ('EB-A', :t, 'voice', '+914412345678',    'intake-v1')
            """
        ),
        {"t": db.current_tenant()},
    )
    assert resolve_entry("voice", "+914412345678") == "intake-v1"
    assert resolve_entry("voice", "+910000000000") == "kaia-v2-4"


def test_the_text_mouth_reaches_the_channel_default_with_no_address(db_tx, door_on) -> None:
    """`bot_runtime._bot_id()` has no address to pass. That asymmetry is
    inherent to address-keyed routing; both shapes live in one table so it does
    not become a second mechanism for WhatsApp."""
    _create_table(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO entry_bindings (id, tenant_id, channel, address, bot_id)
            VALUES ('EB-W', :t, 'whatsapp', NULL, 'intake-v1')
            """
        ),
        {"t": db.current_tenant()},
    )
    assert resolve_entry("whatsapp") == "intake-v1"
    # A channel with no binding is untouched.
    assert resolve_entry("voice") == runtime_entry_bot_id()


def test_a_disabled_binding_does_not_answer(db_tx, door_on) -> None:
    _create_table(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO entry_bindings (id, tenant_id, channel, address, bot_id, enabled)
            VALUES ('EB-X', :t, 'voice', '+914412345678', 'intake-v1', false)
            """
        ),
        {"t": db.current_tenant()},
    )
    assert resolve_entry("voice", "+914412345678") == runtime_entry_bot_id()


def test_only_one_default_per_channel_is_storable(db_tx, door_on) -> None:
    """NULL is distinct from NULL in a UNIQUE constraint, so a plain unique over
    (channel, address) would accept four channel defaults and route by whichever
    the planner returned first. The partial index is what forbids it."""
    _create_table(db_tx)
    db_tx.execute(
        text(
            """
            INSERT INTO entry_bindings (id, tenant_id, channel, address, bot_id)
            VALUES ('EB-1', :t, 'voice', NULL, 'kaia-v2-4')
            """
        ),
        {"t": db.current_tenant()},
    )
    # Inside a SAVEPOINT: a constraint violation aborts the surrounding
    # transaction, and `db_tx` shares one connection across the whole test, so
    # an unguarded raise here would fail whatever test ran next rather than
    # this one.
    with pytest.raises(Exception):
        with db_tx.begin_nested():
            db_tx.execute(
                text(
                    """
                    INSERT INTO entry_bindings (id, tenant_id, channel, address, bot_id)
                    VALUES ('EB-2', :t, 'voice', NULL, 'intake-v1')
                    """
                ),
                {"t": db.current_tenant()},
            )

    # And the transaction is still usable, which is the point of the savepoint.
    assert resolve_entry("voice") == "kaia-v2-4"
