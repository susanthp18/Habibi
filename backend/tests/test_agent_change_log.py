"""The record of what an agent was configured to say.

Publishing changes the words a regulated agent speaks to every caller. These
tests pin the four properties that make the record evidence rather than a log:
it is written, it is complete, it is accurate about what changed, and it cannot
be quietly rewritten.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

import db
from tests.conftest import owner_engine
from agent_core import change_log


def _reset_chain_head() -> None:
    """Drop the tenant's persisted chain head so a test starts from genesis.

    `db_tx` rolls the test's own writes back, but `audit_chain_heads` is a
    committed row that survives — so one run that committed a head leaves every
    later run chaining onto a hash no surviving row has, and `verify_chain`
    reports `tail_truncated` forever. Clearing it at *setup* is what makes the
    suite repeatable; a teardown cannot, because after the rollback there are no
    rows left to identify the tenant by.

    Safe, not merely convenient: `_write` falls back to `_chain_head`, which
    re-derives the head from whatever rows survive and returns genesis when none
    do. Deliberately not done in `_persisted_head` itself — automatic self-heal
    in the library would erase exactly the tamper evidence the chain exists to
    provide. Repairing production is an explicit, audited operator action.
    """
    with db.engine.begin() as conn:
        conn.execute(
            text("DELETE FROM audit_chain_heads WHERE tenant_id = :t"),
            {"t": db._tenant()},
        )


def _tamperer():
    """Rewriting history is the owner's act by construction (sql/43): the app
    role cannot UPDATE or DELETE audit_log at all. The chain still has to
    notice the owner doing it, which is what these tests prove."""
    owner = owner_engine()
    if owner is None:
        pytest.skip("MIGRATION_DATABASE_URL unset: cannot act as the owner")
    return owner


def test_the_screen_knows_every_verb_the_log_can_write() -> None:
    """The half the Python-only test could not see. The two TypeScript maps
    drifted from this list twice (`agent.restore`, then `agent.role_grants`
    rendered as wire strings); there is one table now, and it is pinned here."""
    from pathlib import Path

    table = Path(__file__).resolve().parents[2] / "Habibi" / "src" / "lib" / "change-log-actions.ts"
    if not table.exists():
        pytest.skip("frontend not checked out beside the backend")
    src = table.read_text(encoding="utf-8")
    emitted = {
        value
        for name, value in vars(change_log).items()
        if name.isupper() and isinstance(value, str) and value.startswith("agent.")
    }
    missing = sorted(a for a in emitted if f'"{a}"' not in src)
    assert not missing, f"change-log-actions.ts has no row for {missing}"


# ---------------------------------------------------------------------------
# Tampering. audit_log is append-only for the application role (sql/43), so
# these run as the owner -- the only role that can rewrite history -- against
# committed rows (db_real). The chain still has to notice the owner doing it.
# ---------------------------------------------------------------------------


def _committed_chain(db_real, n: int = 2) -> tuple[str, list[str]]:
    """``n`` archive entries for a probe bot, committed; returns (bot_id, entry ids)."""
    from agent_core import change_log

    bot_id = f"chain-tamper-{uuid.uuid4().hex[:8]}"
    db_real.track("audit_log", entity_id=bot_id)
    ids: list[str] = []
    for _ in range(n):
        entry_id = db._id("AUD")
        with db.engine.begin() as conn:
            change_log.record_archive(
                conn,
                tenant_id=db.current_tenant(),
                actor_user_id=db._actor_user_id(),
                entry_id=entry_id,
                bot_id=bot_id,
                retired_deployment_id=None,
            )
        ids.append(entry_id)
    return bot_id, ids


def test_the_application_role_cannot_rewrite_history(db_real) -> None:
    """The stronger property: not "we would notice" but "it cannot be done"."""
    from sqlalchemy.exc import DBAPIError

    _bot, (first, _second) = _committed_chain(db_real)
    with pytest.raises(DBAPIError, match="append-only"):
        with db.engine.begin() as conn:
            conn.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": first})
    with pytest.raises(DBAPIError, match="append-only"):
        with db.engine.begin() as conn:
            conn.execute(
                text("UPDATE audit_log SET action = 'agent.rollback' WHERE id = :id"), {"id": first}
            )


# ---------------------------------------------------------------------------
# The three evidence writes that left no chain entry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Concurrency. Two publishes of the same tenant's chain at once must serialise
# on the advisory lock in `_write`, or both read the same head and the chain
# forks: two entries with one `seq`, one of them chaining onto a hash the other
# replaced. Untestable under db_tx (one connection, the lock held for the whole
# test), so db_real.
# ---------------------------------------------------------------------------


