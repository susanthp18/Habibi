"""The Door's routing seam, before any caller is switched.

`db.DEFAULT_BOT_ID` takes no arguments — not the channel, not the dialled
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
from agent_core.cards.routing import door_enabled, resolve_entry

_SQL = Path(__file__).resolve().parents[1] / "sql" / "29_entry_bindings.sql"


@pytest.fixture
def door_on(monkeypatch):
    monkeypatch.setenv("DOOR_ENABLED", "1")
    assert door_enabled()


def _create_table(conn) -> None:
    """The table, for a database that predates migration 0118.

    DDL needs the schema owner and the suite runs as the application role, so
    on a migrated database this is a no-op and on an unmigrated one the test
    is skipped rather than failed -- the row-level policies are the reason the
    role cannot create tables, and that is a feature.
    """
    if conn.execute(text("SELECT to_regclass('public.entry_bindings')")).scalar():
        return
    if conn.execute(text("SELECT current_user")).scalar() != "collections":
        pytest.skip("entry_bindings is absent and the test role cannot create it")
    conn.execute(text(_SQL.read_text(encoding="utf-8")))


def _owner_only(conn) -> None:
    from tests.conftest import require_owner

    require_owner(conn, "DDL -- only the owner can drop the table")


def test_the_flag_off_is_todays_behaviour_exactly(monkeypatch) -> None:
    monkeypatch.delenv("DOOR_ENABLED", raising=False)
    assert resolve_entry("voice", "+914412345678") == db.DEFAULT_BOT_ID
    assert resolve_entry("whatsapp") == db.DEFAULT_BOT_ID


def test_an_absent_table_falls_back_rather_than_raising(db_tx, door_on) -> None:
    """A database that never ran 0118 -- still the shape of any environment
    behind on migrations.

    The DROP is rolled back with the fixture's transaction, but it takes ACCESS
    EXCLUSIVE for the length of the test, so this one blocks (and is blocked by)
    anything else touching the table. That is the cost of testing an absent
    table against a real one, and it is why this is the only test here that does
    DDL."""
    _owner_only(db_tx)
    db_tx.execute(text("DROP TABLE IF EXISTS entry_bindings"))
    assert resolve_entry("voice", "+914412345678") == db.DEFAULT_BOT_ID


def test_an_empty_table_falls_back(db_tx, door_on) -> None:
    _create_table(db_tx)
    assert resolve_entry("voice", "+914412345678") == db.DEFAULT_BOT_ID


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
    assert resolve_entry("voice", "+919999999999") == db.DEFAULT_BOT_ID


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
    assert resolve_entry("voice") == db.DEFAULT_BOT_ID


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
    assert resolve_entry("voice", "+914412345678") == db.DEFAULT_BOT_ID


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


# ---------------------------------------------------------------------------
# Authoring a binding
# ---------------------------------------------------------------------------


def test_an_authored_binding_answers_the_number_it_names(db_tx, door_on) -> None:
    from agent_core.cards.routing import upsert_entry_binding

    upsert_entry_binding(channel="voice", address="+914412345678", bot_id="intake-v1")

    assert resolve_entry("voice", "+914412345678") == "intake-v1"
    # A number nobody bound is still today's behaviour, not the door.
    assert resolve_entry("voice", "+914499999999") == db.DEFAULT_BOT_ID


def test_an_exact_address_beats_the_channel_default(db_tx, door_on) -> None:
    from agent_core.cards.routing import upsert_entry_binding

    upsert_entry_binding(channel="voice", bot_id="kaia-v2-4", note="default")
    upsert_entry_binding(channel="voice", address="+914412345678", bot_id="intake-v1")

    assert resolve_entry("voice", "+914412345678") == "intake-v1"
    assert resolve_entry("voice", "+914499999999") == "kaia-v2-4"


def test_the_text_mouths_reach_the_channel_default(db_tx, door_on) -> None:
    """`bot_runtime._bot_id()` has no address to pass, which is why the default
    row and the per-number row live in one table rather than WhatsApp growing a
    second mechanism."""
    from agent_core.cards.routing import upsert_entry_binding

    upsert_entry_binding(channel="whatsapp", bot_id="intake-v1")

    assert resolve_entry("whatsapp") == "intake-v1"


def test_rebinding_a_number_moves_it_rather_than_duplicating_it(db_tx, door_on) -> None:
    """Two enabled rows for one number would make the answering card depend on
    whichever the planner returned first."""
    from agent_core.cards.routing import list_entry_bindings, upsert_entry_binding

    upsert_entry_binding(channel="voice", address="+914412345678", bot_id="kaia-v2-4")
    upsert_entry_binding(channel="voice", address="+914412345678", bot_id="intake-v1")

    rows = [b for b in list_entry_bindings() if b["address"] == "+914412345678"]
    assert len(rows) == 1
    assert resolve_entry("voice", "+914412345678") == "intake-v1"


def test_disabling_a_binding_falls_back_rather_than_stranding(db_tx, door_on) -> None:
    from agent_core.cards.routing import upsert_entry_binding

    upsert_entry_binding(
        channel="voice", address="+914412345678", bot_id="intake-v1", enabled=False
    )

    assert resolve_entry("voice", "+914412345678") == db.DEFAULT_BOT_ID


def test_a_binding_changes_nothing_while_the_flag_is_off(db_tx, monkeypatch) -> None:
    """The row can be authored, reviewed and left in place before anything
    routes by it -- which is what makes the switch-on a flag flip and not a
    data migration."""
    from agent_core.cards.routing import upsert_entry_binding

    monkeypatch.setenv("DOOR_ENABLED", "1")
    upsert_entry_binding(channel="voice", address="+914412345678", bot_id="intake-v1")
    assert resolve_entry("voice", "+914412345678") == "intake-v1"

    monkeypatch.delenv("DOOR_ENABLED", raising=False)
    assert resolve_entry("voice", "+914412345678") == db.DEFAULT_BOT_ID


def test_a_bound_card_cannot_be_archived(db_tx, door_on) -> None:
    """The archive guard used to compare against one env var, so with the door
    on it would archive a card a dialled number still points at -- the binding
    survives and routes to an archived card."""
    from agent_core.cards.routing import is_entry_card, upsert_entry_binding

    # insurance-v1, not intake-v1: this database already carries the production
    # door binding, and a test that asserts "unbound" about a bound card is
    # asserting the fixture, not the code.
    assert not is_entry_card("insurance-v1")

    upsert_entry_binding(channel="voice", address="+914412345678", bot_id="insurance-v1")
    assert is_entry_card("insurance-v1")

    upsert_entry_binding(
        channel="voice", address="+914412345678", bot_id="insurance-v1", enabled=False
    )
    assert not is_entry_card("insurance-v1")


def test_the_env_default_is_always_an_entry_card(db_tx) -> None:
    from agent_core.cards.routing import is_entry_card

    assert is_entry_card(db.DEFAULT_BOT_ID)
