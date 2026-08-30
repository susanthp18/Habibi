"""The two ways a retry ladder can stop being a ladder.

Both are failures of the *worker*, not of the cadence rules — ``on_outcome``
decides the next rung correctly in either case and never gets asked.

* **A pause that only pauses half the campaign.** An operator pulls the
  handbrake on a run and the list stops being worked through — but every ladder
  the run has already opened keeps its own clock, so second and third attempts
  carry on going out for days. The handbrake has to hold the ladders too, and
  hold them without deleting anything: a pause is not a cancellation, so the
  borrower keeps their place and the run resumes where it stopped.

* **A placement that throws.** ``outbound.place`` says it never raises, and
  ``process_one`` believed it. The attempt counter is committed before the dial,
  so a throw leaves ``next_attempt_at`` NULL — invisible to ``claim_due`` for
  ever — and an attempt row stuck in ``reserved``, the one state the Closer
  skips. Nobody is dialled, nothing is exhausted, and no operator is told. A
  silently stranded case is worse than a failed one; the borrower simply stops
  being called and the ladder reports itself as open.
"""

from __future__ import annotations

import logging

import pytest
from sqlalchemy import text

import cadence
import campaigns
import contact_policy
import db as dbmod
import outbound


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _cadence_runs(monkeypatch):
    """The runtime flag is a deployment decision; these tests are about the loop."""
    monkeypatch.setattr(cadence, "enabled", lambda: True)
    cadence._PAUSE_LOGGED.clear()
    yield
    cadence._PAUSE_LOGGED.clear()


@pytest.fixture(autouse=True)
def _contact_gate_allows(monkeypatch):
    """The gate has its own suite. Here it must not be the reason nothing dials."""
    monkeypatch.setattr(
        contact_policy, "admit", lambda *a, **k: contact_policy.Decision(allowed=True)
    )


class _Dialler:
    """Stands in for the carrier. Records, or raises on demand."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.raises = raises

    def __call__(self, engine, attempt, *, to_phone, custom=None):
        self.calls.append({"attempt": attempt, "to": to_phone})
        if self.raises is not None:
            raise self.raises
        return {"placed": True, "state": "dialing", "attemptId": attempt["id"]}


def _a_customer(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id
            FROM customers c JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer with an account")
    conn.execute(
        text("UPDATE customers SET phone_primary = '919000000001' WHERE id = :id"),
        {"id": row["id"]},
    )
    return dict(row)


def _only_due_case(
    conn,
    cust: dict,
    *,
    case_ref: str,
    run_id: str | None = None,
    max_attempts: int = 3,
    attempts: int = 0,
) -> str:
    """One ladder, due now, and the only one in the whole book that is.

    Seed and fixture data is shared, and ``claim_due`` takes the oldest due case
    in the deployment — so a test that did not quiet the others would be
    asserting about somebody else's borrower. Rolled back with everything else.
    """
    conn.execute(
        text("UPDATE call_cadence_state SET next_attempt_at = NULL WHERE next_attempt_at IS NOT NULL")
    )
    case = cadence.ensure_case(
        conn,
        tenant_id=cust["tenant_id"],
        customer_id=cust["id"],
        objective="dpd_reminder",
        case_ref=case_ref,
        max_attempts=max_attempts,
        campaign_run_id=run_id,
        attempts=attempts,
    )
    conn.execute(
        text(
            """
            UPDATE call_cadence_state
            SET next_attempt_at = now() - interval '5 minutes', campaign_run_id = :run
            WHERE id = :id
            """
        ),
        {"id": case["id"], "run": run_id},
    )
    return str(case["id"])


def _a_run(conn, cust: dict, *, status: str) -> str:
    run_id = "CR-TEST-CADENCE-PAUSE"
    conn.execute(
        text(
            """
            INSERT INTO campaign_runs (id, tenant_id, name, objective, status)
            VALUES (:id, :tenant, 'cadence pause probe', 'dpd_reminder', :status)
            ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status
            """
        ),
        {"id": run_id, "tenant": cust["tenant_id"], "status": status},
    )
    return run_id


def _case(conn, case_id: str) -> dict:
    return dict(
        conn.execute(
            text("SELECT * FROM call_cadence_state WHERE id = :id"), {"id": case_id}
        ).mappings().first()
    )


def _attempts_for(conn, case_id: str) -> list[dict]:
    rows = conn.execute(
        text(
            """
            SELECT id, state FROM call_attempts
            WHERE context ->> 'caseId' = :case
            ORDER BY reserved_at ASC
            """
        ),
        {"case": case_id},
    ).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Control: the ladder still fires
# ---------------------------------------------------------------------------


def test_a_due_ladder_under_a_running_campaign_still_fires(db_tx, monkeypatch) -> None:
    """The control. Everything below subtracts from this, and nothing may
    subtract from it by accident."""
    cust = _a_customer(db_tx)
    run_id = _a_run(db_tx, cust, status=campaigns.STATUS_RUNNING)
    case_id = _only_due_case(db_tx, cust, case_ref="CASE-CAD-RUNNING", run_id=run_id)

    dialler = _Dialler()
    monkeypatch.setattr(outbound, "place", dialler)

    assert cadence.process_one(dbmod.engine) is True
    assert len(dialler.calls) == 1

    case = _case(db_tx, case_id)
    assert case["attempts"] == 1
    assert case["state"] == cadence.STATE_OPEN
    # Spent, not scheduled: the outcome of this dial decides the next rung.
    assert case["next_attempt_at"] is None
    assert [a["state"] for a in _attempts_for(db_tx, case_id)] == ["reserved"]


# ---------------------------------------------------------------------------
# A pause holds the ladders the campaign already opened
# ---------------------------------------------------------------------------


def test_pausing_a_campaign_holds_the_ladders_it_already_opened(
    db_tx, monkeypatch, caplog
) -> None:
    cust = _a_customer(db_tx)
    run_id = _a_run(db_tx, cust, status=campaigns.STATUS_PAUSED)
    case_id = _only_due_case(db_tx, cust, case_ref="CASE-CAD-PAUSED", run_id=run_id)

    dialler = _Dialler()
    monkeypatch.setattr(outbound, "place", dialler)

    with caplog.at_level(logging.INFO, logger="cadence"):
        assert cadence.process_one(dbmod.engine) is False

    assert dialler.calls == [], "a paused campaign dialled a borrower"
    assert _attempts_for(db_tx, case_id) == [], "a held firing still reserved an attempt"
    assert run_id in caplog.text

    # Held, not cancelled. The borrower keeps their place in their own cadence.
    case = _case(db_tx, case_id)
    assert case["state"] == cadence.STATE_OPEN
    assert case["attempts"] == 0
    assert case["next_attempt_at"] is not None, "the queued row was dropped, not held"


def test_a_held_ladder_fires_on_the_first_poll_after_the_campaign_resumes(
    db_tx, monkeypatch
) -> None:
    """Within one poll cycle, and with no operator having to re-queue anything."""
    cust = _a_customer(db_tx)
    run_id = _a_run(db_tx, cust, status=campaigns.STATUS_PAUSED)
    case_id = _only_due_case(db_tx, cust, case_ref="CASE-CAD-RESUME", run_id=run_id)

    dialler = _Dialler()
    monkeypatch.setattr(outbound, "place", dialler)

    assert cadence.process_one(dbmod.engine) is False
    assert dialler.calls == []

    campaigns.set_status(db_tx, run_id, campaigns.STATUS_RUNNING)

    assert cadence.process_one(dbmod.engine) is True
    assert len(dialler.calls) == 1
    assert _case(db_tx, case_id)["attempts"] == 1


def test_a_paused_campaign_does_not_starve_everybody_elses_retries(
    db_tx, monkeypatch
) -> None:
    """The held case is the oldest due one, so a queue that only looked at
    ``next_attempt_at`` would hand it back every poll for as long as the pause
    lasted — and no other borrower would ever be dialled again."""
    cust = _a_customer(db_tx)
    run_id = _a_run(db_tx, cust, status=campaigns.STATUS_PAUSED)
    held = _only_due_case(db_tx, cust, case_ref="CASE-CAD-HELD", run_id=run_id)
    free = _only_due_case(db_tx, cust, case_ref="CASE-CAD-FREE")
    # The held ladder is older, so it sorts first on time alone.
    db_tx.execute(
        text(
            "UPDATE call_cadence_state SET next_attempt_at = now() - interval '1 hour' WHERE id = :id"
        ),
        {"id": held},
    )
    db_tx.execute(
        text(
            "UPDATE call_cadence_state SET next_attempt_at = now() - interval '1 minute' WHERE id = :id"
        ),
        {"id": free},
    )

    dialler = _Dialler()
    monkeypatch.setattr(outbound, "place", dialler)

    assert cadence.process_one(dbmod.engine) is True
    assert _case(db_tx, free)["attempts"] == 1
    assert _case(db_tx, held)["attempts"] == 0


def test_a_ladder_with_no_campaign_behind_it_is_never_held(db_tx, monkeypatch) -> None:
    """The engine's own cases have no run to read a status from, and a LEFT JOIN
    that dropped them would silence the ladders nobody can unpause."""
    cust = _a_customer(db_tx)
    case_id = _only_due_case(db_tx, cust, case_ref="CASE-CAD-NORUN")

    dialler = _Dialler()
    monkeypatch.setattr(outbound, "place", dialler)

    assert cadence.process_one(dbmod.engine) is True
    assert len(dialler.calls) == 1
    assert _case(db_tx, case_id)["attempts"] == 1


# ---------------------------------------------------------------------------
# A placement that throws leaves nothing stranded
# ---------------------------------------------------------------------------


def test_a_placement_that_throws_puts_the_case_back_on_the_ladder(
    db_tx, monkeypatch, caplog
) -> None:
    cust = _a_customer(db_tx)
    case_id = _only_due_case(db_tx, cust, case_ref="CASE-CAD-THROW")

    dialler = _Dialler(raises=RuntimeError("carrier client exploded"))
    monkeypatch.setattr(outbound, "place", dialler)

    with caplog.at_level(logging.INFO, logger="cadence"):
        # The worker is told work happened, because it did: an attempt was
        # reserved and spent.
        assert cadence.process_one(dbmod.engine) is True

    assert len(dialler.calls) == 1

    case = _case(db_tx, case_id)
    assert case["state"] == cadence.STATE_OPEN
    assert case["attempts"] == 1
    assert case["next_attempt_at"] is not None, "the case was silently stranded"

    # And the reserved row is not left dangling either: `reserved` is the one
    # state the Closer skips, so it would have sat there for ever.
    assert [a["state"] for a in _attempts_for(db_tx, case_id)] == ["failed"]

    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors, "a stranded case was recovered without telling anybody"
    assert case_id in caplog.text


def test_a_placement_that_throws_on_the_last_attempt_exhausts_the_ladder(
    db_tx, monkeypatch, caplog
) -> None:
    """Re-queueing a ladder ``on_outcome`` would refuse to walk is a slower
    strand, not a recovery."""
    cust = _a_customer(db_tx)
    case_id = _only_due_case(
        db_tx, cust, case_ref="CASE-CAD-THROW-LAST", max_attempts=3, attempts=2
    )

    monkeypatch.setattr(outbound, "place", _Dialler(raises=RuntimeError("boom")))

    with caplog.at_level(logging.INFO, logger="cadence"):
        assert cadence.process_one(dbmod.engine) is True

    case = _case(db_tx, case_id)
    assert case["state"] == cadence.STATE_EXHAUSTED
    assert case["stopped_reason"] == "place_failed:max_attempts"
    assert case["next_attempt_at"] is None
    assert [r for r in caplog.records if r.levelno >= logging.ERROR]


# ---------------------------------------------------------------------------
# The ceiling is checked before the dial, not after it
# ---------------------------------------------------------------------------


def test_a_case_already_at_its_ceiling_is_exhausted_without_dialling(
    db_tx, monkeypatch, caplog
) -> None:
    """The ceiling is arithmetic ``on_outcome`` gets right — when it runs.

    It only runs on an *outcome*, so a ladder that arrives here already at its
    ceiling and still carrying a ``next_attempt_at`` gets dialled once more and
    is only then told it had run out. That extra dial is a real call to a real
    borrower, past a limit somebody authored specifically to stop it.
    """
    cust = _a_customer(db_tx)
    case_id = _only_due_case(
        db_tx, cust, case_ref="CASE-CAD-AT-CEILING", max_attempts=3, attempts=3
    )

    dialler = _Dialler()
    monkeypatch.setattr(outbound, "place", dialler)

    with caplog.at_level(logging.INFO, logger="cadence"):
        # True: a case was claimed and dealt with, which is what the worker is
        # being told. It simply was not dialled.
        assert cadence.process_one(dbmod.engine) is True

    assert dialler.calls == [], "a borrower was dialled past the authored ceiling"
    assert _attempts_for(db_tx, case_id) == [], "an attempt was reserved and never spent"

    # The same mechanism the failure path uses, so an operator reads one story.
    case = _case(db_tx, case_id)
    assert case["state"] == cadence.STATE_EXHAUSTED
    assert case["stopped_reason"] == "max_attempts"
    assert case["next_attempt_at"] is None
    assert case["attempts"] == 3, "the counter moved for a dial that never happened"

    assert case_id in caplog.text
    assert any(r.levelno == logging.INFO for r in caplog.records)


def test_the_last_authored_attempt_is_still_placed(db_tx, monkeypatch) -> None:
    """The boundary, from the other side. ``attempts`` counts dials already
    spent, so at 2 of 3 the third is owed and a check that refused it would
    quietly turn every three-attempt cadence into a two-attempt one."""
    cust = _a_customer(db_tx)
    case_id = _only_due_case(
        db_tx, cust, case_ref="CASE-CAD-LAST-RUNG", max_attempts=3, attempts=2
    )

    dialler = _Dialler()
    monkeypatch.setattr(outbound, "place", dialler)

    assert cadence.process_one(dbmod.engine) is True
    assert len(dialler.calls) == 1
    case = _case(db_tx, case_id)
    assert case["attempts"] == 3
    assert case["state"] == cadence.STATE_OPEN
