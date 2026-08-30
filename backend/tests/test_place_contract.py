"""``outbound.place`` says it never raises. This is the suite that makes it true.

The docstring has claimed it since the function was written, and every caller
has believed it. ``campaigns.process_one`` calls it with no ``try`` at all,
having already committed ``state = 'dialing'`` and ``attempts + 1`` to the
target row — so an exception out of ``place`` leaves a borrower marked as being
called, by nobody, for ever. ``cadence.process_one`` grew a whole recovery path
(:func:`cadence._recover_stranded`) for exactly this, which is the right
belt-and-braces and the wrong place for the fix: one caller defended is one
caller defended.

Three things could break the promise, none of them exotic:

* ``to_e164`` on a number that is not one — a data-entry field with a name in
  it, an import that put the address in the phone column.
* either ``engine.begin()`` block, when the database is not answering. The
  first one guards the fleet cap; the second is the write that records the call
  the carrier has *already* connected.
* the carrier client failing to import at all.

And one thing must still break loudly: a bug. A ``place`` that turned the
caller's ``TypeError`` into ``{"placed": False}`` would hide a broken
deployment behind a result that reads exactly like a bad afternoon at the
carrier — every dial failing, nothing in the logs but "dial failed".
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

import db as dbmod
import outbound


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _DeadEngine:
    """A database that is not there.

    ``OperationalError`` is what SQLAlchemy raises when the connection is
    refused or the pool times out, and it is deliberately *not* one of
    :data:`outbound._BUG_EXCEPTIONS` — it is a fact about the world.
    """

    def __init__(self) -> None:
        self.calls = 0

    def begin(self):
        self.calls += 1
        from sqlalchemy.exc import OperationalError

        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


class _Carrier:
    """Stands in for ``voice.twilio_ops``. Records what it was asked to dial."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.raises = raises

    def start_outbound_call(self, *, to, custom, machine_detection=False, from_number=None):
        self.calls.append({"to": to, "custom": custom, "from": from_number})
        if self.raises is not None:
            raise self.raises
        return {"callSid": "CA-TEST-SID", "status": "queued", "from": from_number}

    def twilio_phone(self) -> str:
        return "+15550000000"


@pytest.fixture
def carrier(monkeypatch):
    from voice import twilio_ops

    fake = _Carrier()
    monkeypatch.setattr(twilio_ops, "start_outbound_call", fake.start_outbound_call)
    monkeypatch.setattr(twilio_ops, "twilio_phone", fake.twilio_phone)
    return fake


def _a_customer(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id FROM customers c
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer")
    return dict(row)


def _an_attempt(conn, phone: str = "919000000009") -> dict:
    cust = _a_customer(conn)
    attempt = outbound.reserve(
        conn,
        customer_id=cust["id"],
        to_phone=phone,
        objective="dpd_reminder",
        campaign_run_id="CR-PLACE-CONTRACT",
        tenant_id=cust["tenant_id"],
        context={"caseId": "CASE-PLACE-CONTRACT"},
    )
    assert attempt is not None
    return attempt


def _state(conn, attempt_id: str) -> str:
    return str(
        conn.execute(
            text("SELECT state FROM call_attempts WHERE id = :id"), {"id": attempt_id}
        ).scalar()
    )


def _errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------------------------------
# 3. The happy path, unchanged
# ---------------------------------------------------------------------------


def test_a_good_number_still_dials_and_still_binds_the_call_id(db_tx, carrier) -> None:
    """The control. Everything below subtracts from this, and nothing may
    subtract from it by accident."""
    attempt = _an_attempt(db_tx)

    result = outbound.place(dbmod.engine, attempt, to_phone="919000000009")

    assert result["placed"] is True
    assert result["state"] == outbound.STATE_DIALING
    assert result["callSid"] == "CA-TEST-SID"
    # Bare digits in, E.164 out: the carrier rejects the stored shape with 21211.
    assert result["to"] == "+919000000009"
    assert [c["to"] for c in carrier.calls] == ["+919000000009"]
    assert _state(db_tx, attempt["id"]) == "dialing"


# ---------------------------------------------------------------------------
# 1. A number that is not one
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["not a phone number", "n/a", "  ", "-"])
def test_a_malformed_number_is_a_result_not_an_exception(
    db_tx, carrier, caplog, bad
) -> None:
    attempt = _an_attempt(db_tx)

    with caplog.at_level(logging.INFO, logger="outbound"):
        result = outbound.place(dbmod.engine, attempt, to_phone=bad)

    assert result["placed"] is False
    assert result["state"] == outbound.STATE_FAILED
    assert result["reason"] == "invalid_number"
    assert result["attemptId"] == attempt["id"]

    assert carrier.calls == [], "an unusable number was handed to the carrier"
    # `reserved` is the one state the Closer skips, so leaving it there is the
    # same silent strand by another route.
    assert _state(db_tx, attempt["id"]) == "failed"

    errors = _errors(caplog)
    assert errors, "a dial was dropped without telling anybody"
    assert "CASE-PLACE-CONTRACT" in caplog.text, "the log does not say whose dial this was"
    assert "CR-PLACE-CONTRACT" in caplog.text


# ---------------------------------------------------------------------------
# 2. A database that is not answering
# ---------------------------------------------------------------------------


def test_a_dead_database_at_the_fleet_gate_is_a_result_not_an_exception(
    carrier, caplog
) -> None:
    """No ``db_tx``: the point is that there is no database at all.

    Refusing is the only safe answer — the alternative is a fleet cap that
    stops applying exactly when the database is already struggling.
    """
    engine = _DeadEngine()
    attempt = {
        "id": "CA-DEADDB",
        "tenantId": "T1",
        "customerId": "C1",
        "objective": "dpd_reminder",
        "context": {"caseId": "CASE-DEADDB"},
    }

    with caplog.at_level(logging.INFO, logger="outbound"):
        result = outbound.place(engine, attempt, to_phone="919000000009")

    assert result == {
        "placed": False,
        "state": outbound.STATE_FAILED,
        "reason": "fleet_gate_unavailable",
        "attemptId": "CA-DEADDB",
    }
    assert carrier.calls == [], "the fleet cap was skipped rather than enforced"
    assert _errors(caplog)
    assert "CASE-DEADDB" in caplog.text


def test_a_database_that_dies_after_the_dial_reports_the_call_it_could_not_record(
    db_tx, carrier, caplog, monkeypatch
) -> None:
    """The nastiest of the three: the borrower's phone is ringing and we cannot
    write down that it is.

    ``placed: true`` would be the more flattering answer and the wrong one — the
    row is still ``reserved``, so nothing downstream will treat this as a live
    call. The caller has to hear that, and an operator has to be told which call
    is now running unrecorded.
    """
    attempt = _an_attempt(db_tx)

    def _explode(*_a, **_k):
        from sqlalchemy.exc import OperationalError

        raise OperationalError("UPDATE call_attempts", {}, Exception("server closed"))

    monkeypatch.setattr(outbound, "_mark_dialing", _explode)

    with caplog.at_level(logging.INFO, logger="outbound"):
        result = outbound.place(dbmod.engine, attempt, to_phone="919000000009")

    assert result["placed"] is False
    assert result["reason"] == "state_write_failed"
    # The dial itself did happen, and the result says so rather than pretending
    # the carrier was never called.
    assert len(carrier.calls) == 1
    assert result["callSid"] == "CA-TEST-SID"
    assert _errors(caplog)


def test_a_carrier_that_raises_is_still_a_result(db_tx, monkeypatch) -> None:
    """The path that already worked, kept working — including its bookkeeping."""
    from voice import twilio_ops

    fake = _Carrier(raises=RuntimeError("twilio is having a day"))
    monkeypatch.setattr(twilio_ops, "start_outbound_call", fake.start_outbound_call)
    attempt = _an_attempt(db_tx)

    result = outbound.place(dbmod.engine, attempt, to_phone="919000000009")

    assert result["placed"] is False
    assert result["reason"] == "dial_failed"
    assert _state(db_tx, attempt["id"]) == "failed"


# ---------------------------------------------------------------------------
# A bug is not an operational failure
# ---------------------------------------------------------------------------


def test_a_caller_that_omits_the_attempt_id_gets_its_bug_back(carrier) -> None:
    with pytest.raises(KeyError):
        outbound.place(_DeadEngine(), {"tenantId": "T1"}, to_phone="919000000009")


def test_a_programming_error_inside_a_guarded_region_is_re_raised(
    carrier, monkeypatch
) -> None:
    """The guard converts *operational* failures. A ``TypeError`` from the fleet
    gate means this code is wrong, and a ``{"placed": False}`` for it would read
    exactly like a carrier having a bad afternoon."""

    def _bug(*_a, **_k):
        raise TypeError("in_flight_count() got an unexpected keyword argument")

    monkeypatch.setattr(outbound, "in_flight_count", _bug)

    class _Engine:
        def begin(self):
            from contextlib import contextmanager

            @contextmanager
            def _cm():
                yield object()

            return _cm()

    with pytest.raises(TypeError):
        outbound.place(
            _Engine(), {"id": "CA-BUG", "tenantId": "T1"}, to_phone="919000000009"
        )
    assert carrier.calls == []
