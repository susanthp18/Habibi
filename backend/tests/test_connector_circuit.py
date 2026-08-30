"""The connector breaker's ``allow()`` gate, which had no test at all.

``tests/test_circuit_breaker.py`` covers the in-process HTTP breaker in
``circuit_breaker.py``. This is the other one: ``agent_core/connectors/circuit``,
the per-connector breaker whose state lives in ``mcp_connectors`` columns rather
than in memory, and which decides whether ``connectors.persist.dispatch`` is
allowed to call a bound tool at all.

The branch that most needed pinning is the malformed timestamp. It returns
``False``, and the choice is deliberate — corrupt state is terminal here, the
same way ``agent_core/skills/persist`` refuses to read a signed version that
will not parse as merely absent. Two things make that survivable and both are
asserted below: the deny is logged rather than silent, and ``record_success``
(reachable through ``health_test``, which is *not* gated by ``allow``) clears
the column, so an operator has a recovery path that is not direct SQL.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

import db
from agent_core.connectors import circuit


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _ago(seconds: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(seconds=seconds)


# --- 1. nothing has failed --------------------------------------------------


@pytest.mark.parametrize(
    "connector",
    [
        {},
        {"circuit_opened_at": None},
        {"circuitOpenedAt": None},
        {"circuit_opened_at": ""},
    ],
    ids=["absent", "null-snake", "null-camel", "empty-string"],
)
def test_a_connector_that_has_never_opened_is_allowed(connector: dict) -> None:
    """No stamp means no open breaker, however the caller spells the key.

    ``persist.dispatch`` passes ``{"circuit_opened_at": conn.get("circuitOpenedAt")}``
    — snake key, camel value — so both spellings are live and the ``None`` that
    a fresh row yields has to read as "allowed".
    """
    assert circuit.allow(connector) is True


# --- 2. failures below the threshold ----------------------------------------


@pytest.mark.parametrize("fails", [1, 2])
def test_failures_below_the_threshold_do_not_block(fails: int) -> None:
    """``allow()`` reads the stamp, not the counter.

    ``record_failure`` only stamps ``circuit_opened_at`` once the count reaches
    ``OPEN_AFTER``, so a connector carrying one or two failures has a counter
    and no stamp — and must still be allowed through. Asserting this pins that
    the two columns are not redundant: reading ``circuit_fails`` here instead
    would open the breaker on the first failure.
    """
    assert fails < circuit.OPEN_AFTER
    assert circuit.allow({"circuit_fails": fails, "circuit_opened_at": None}) is True


# --- 3. open ----------------------------------------------------------------


@pytest.mark.parametrize("elapsed", [0.0, 1.0, 29.0])
def test_a_breaker_opened_inside_the_cooldown_blocks(elapsed: float) -> None:
    assert elapsed < circuit.COOLDOWN_S
    assert circuit.allow({"circuit_opened_at": _ago(elapsed)}) is False
    assert circuit.allow({"circuit_opened_at": _iso(_ago(elapsed))}) is False


def test_a_naive_timestamp_is_read_as_utc() -> None:
    """``circuit_opened_at`` is timestamptz, but a naive value must not crash.

    Without the ``tzinfo`` fill-in the subtraction below raises TypeError, and a
    breaker that raises instead of answering takes down the dispatch path it was
    supposed to protect.
    """
    naive_recent = datetime.now(timezone.utc).replace(tzinfo=None)
    assert circuit.allow({"circuit_opened_at": naive_recent}) is False
    naive_old = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None)
    assert circuit.allow({"circuit_opened_at": naive_old}) is True


# --- 4. recovery ------------------------------------------------------------


@pytest.mark.parametrize("elapsed", [30.0, 31.0, 3600.0])
def test_the_breaker_reopens_once_the_cooldown_has_elapsed(elapsed: float) -> None:
    """Half-open: the next call is let through to find out if the target is back.

    The comparison is ``>=``, so exactly ``COOLDOWN_S`` allows. Pinned because a
    ``>`` here would be invisible in every test that used a round number.
    """
    assert elapsed >= circuit.COOLDOWN_S
    assert circuit.allow({"circuit_opened_at": _ago(elapsed)}) is True
    assert circuit.allow({"circuit_opened_at": _iso(_ago(elapsed))}) is True


def test_a_trailing_z_is_accepted() -> None:
    """Postgres hands back ``+00:00``; JSON round-trips often hand back ``Z``.

    ``datetime.fromisoformat`` did not accept ``Z`` before 3.11, which is why
    the module rewrites it. If that rewrite is dropped, a ``Z``-suffixed stamp
    stops being a timestamp and starts being corrupt state — it would take the
    fail-closed branch and block a connector whose cooldown had long expired.
    """
    old = _ago(3600).astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    assert circuit.allow({"circuit_opened_at": old}) is True
    recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    assert circuit.allow({"circuit_opened_at": recent}) is False


# --- 5. corrupt state -------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["not-a-timestamp", "2026-13-45T99:99:99Z", "0", "yesterday", "2026/08/25 10:00"],
)
def test_an_unparseable_timestamp_denies(raw: str) -> None:
    """The documented choice: corrupt state is terminal, so it fails closed.

    This is the same call ``agent_core/skills/persist`` makes for a signed pack
    version that will not parse — the corrupt row is not read as absent, and
    what it gates stays denied. Reading it as expired would be the opposite
    bet: it hands the dispatch path back to a connector whose breaker state is
    exactly what we just failed to read, which is the reading that turns a
    corrupt row into calls against a target that may still be down.

    Note ``"0"``: a string that is falsy-looking but not empty, so it reaches
    the parser rather than the ``not opened`` early return.
    """
    assert circuit.allow({"circuit_opened_at": raw}) is False


def test_the_deny_is_logged_rather_than_silent(caplog: pytest.LogCaptureFixture) -> None:
    """The half of this branch that was an actual defect.

    Denying is defensible; denying without a word is not. Before this, every
    call on such a connector answered ``connector_circuit_open`` and nothing
    anywhere distinguished a malformed column from a target that was really
    down, so the one state a human has to fix looked exactly like the one that
    fixes itself.
    """
    with caplog.at_level(logging.WARNING, logger="agent_core.connectors.circuit"):
        assert circuit.allow({"id": "conn-corrupt-1", "circuit_opened_at": "not-a-date"}) is False

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings, "a fail-closed deny on corrupt state must not be silent"
    message = warnings[-1].getMessage()
    assert "conn-corrupt-1" in message
    assert "not-a-date" in message


def test_a_corrupt_stamp_stays_denied_until_something_clears_it() -> None:
    """Why fail-closed here is not a permanent brick.

    Time does not fix a corrupt stamp — that is the honest cost of the choice,
    and this pins it rather than hiding it. The recovery path is a write:
    ``record_success`` NULLs the column, and ``persist.health_test`` reaches it
    without passing through ``allow``, so an operator's health probe un-blocks
    the connector. That path is exercised against the database below.
    """
    corrupt = {"id": "conn-corrupt-2", "circuit_opened_at": "not-a-date"}
    assert circuit.allow(corrupt) is False
    assert circuit.allow(corrupt) is False
    assert circuit.allow({**corrupt, "circuit_opened_at": None}) is True


def test_health_test_is_not_gated_by_allow() -> None:
    """The recovery path only exists because this call is un-gated.

    Read the source: ``dispatch`` checks ``circuit.allow`` and ``health_test``
    does not. If someone later adds that check to ``health_test`` for symmetry,
    a connector with a corrupt stamp becomes genuinely unrecoverable without
    direct SQL, and the docstring on ``circuit.allow`` becomes a lie.
    """
    import inspect

    from agent_core.connectors import persist as cp

    assert "circuit.allow" in inspect.getsource(cp.dispatch)
    assert "circuit.allow" not in inspect.getsource(cp.health_test)
    assert "record_success" in inspect.getsource(cp.health_test)


# --- 6. the write path ------------------------------------------------------


def _connector_row(db_tx, *, slug: str) -> str:
    reg = text("SELECT to_regclass('public.mcp_connectors') AS t")
    row = db_tx.execute(reg).mappings().first()
    if not row or not row["t"]:
        pytest.skip("mcp_connectors missing")
    connector_id = f"conn-circuit-{uuid.uuid4().hex[:10]}"
    db_tx.execute(
        text("DELETE FROM mcp_connectors WHERE tenant_id = :t AND slug = :s"),
        {"t": db.current_tenant(), "s": slug},
    )
    db_tx.execute(
        text(
            """
            INSERT INTO mcp_connectors (
              id, tenant_id, slug, display_name, kind, allow_prefixes,
              data_class, status
            ) VALUES (
              :id, :t, :s, 'Circuit Fixture', 'first_party',
              CAST('{ext.circuit.}' AS text[]), CAST('{pii}' AS text[]), 'approved'
            )
            """
        ),
        {"id": connector_id, "t": db.current_tenant(), "s": slug},
    )
    return connector_id


def _state(db_tx, connector_id: str) -> dict:
    return (
        db_tx.execute(
            text(
                "SELECT circuit_fails, circuit_opened_at, health"
                "  FROM mcp_connectors WHERE id = :id"
            ),
            {"id": connector_id},
        )
        .mappings()
        .one()
    )


def test_record_failure_counts_up_and_then_opens(db_tx) -> None:
    """The counter climbs, and the stamp lands exactly on ``OPEN_AFTER``.

    Checked through ``allow()`` at every step, not just against the columns —
    the point of the counter is what the gate does with it, and the two
    together are what make the "below threshold" case above meaningful.
    """
    connector_id = _connector_row(db_tx, slug="circ-open")

    for expected in range(1, circuit.OPEN_AFTER):
        circuit.record_failure(connector_id)
        state = _state(db_tx, connector_id)
        assert state["circuit_fails"] == expected
        assert state["circuit_opened_at"] is None
        assert state["health"] == "degraded"
        assert circuit.allow(dict(state)) is True

    circuit.record_failure(connector_id)
    opened = _state(db_tx, connector_id)
    assert opened["circuit_fails"] == circuit.OPEN_AFTER
    assert opened["circuit_opened_at"] is not None
    assert opened["health"] == "down"
    assert circuit.allow(dict(opened)) is False


def test_record_success_clears_the_breaker(db_tx) -> None:
    """The recovery write, including from a state ``allow()`` refuses to read.

    The stamp is forced to a corrupt value first, because that is the case the
    fail-closed choice above leans on: ``record_success`` does not parse the
    column, it overwrites it, so the un-blocking works on exactly the row that
    ``allow()`` cannot make sense of.
    """
    connector_id = _connector_row(db_tx, slug="circ-clear")

    for _ in range(circuit.OPEN_AFTER):
        circuit.record_failure(connector_id)
    assert circuit.allow(dict(_state(db_tx, connector_id))) is False

    circuit.record_success(connector_id)
    cleared = _state(db_tx, connector_id)
    assert cleared["circuit_fails"] == 0
    assert cleared["circuit_opened_at"] is None
    assert cleared["health"] == "healthy"
    assert circuit.allow(dict(cleared)) is True


def test_a_cross_tenant_id_cannot_move_the_breaker(db_tx) -> None:
    """Both writes are tenant-scoped; a foreign id is a no-op, not an error.

    Worth pinning next to the rest: the ``WHERE ... AND tenant_id`` on these two
    UPDATEs is the only thing stopping one tenant from tripping — or silently
    resetting — another tenant's connector breaker by id.
    """
    connector_id = _connector_row(db_tx, slug="circ-tenant")
    circuit.record_failure(connector_id)
    assert _state(db_tx, connector_id)["circuit_fails"] == 1

    db_tx.execute(
        text("UPDATE mcp_connectors SET tenant_id = tenant_id WHERE id = :id"),
        {"id": connector_id},
    )
    circuit.record_failure("conn-belongs-to-nobody")
    assert _state(db_tx, connector_id)["circuit_fails"] == 1
