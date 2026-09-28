"""The published card decides what closed the mission, and who owns it after.

Two authored fields that were gated at publish and read by nobody:

* ``CardObjective.success`` / ``.partial`` — the Closer scored every mission
  off a module-level table, so "Closes the case" and "Partly worked" in the
  Outbound tab were decoration. The comment above the table claimed the card
  overrode it; it never had (RUNTIME-08, OUTBOUND-01).
* ``CardCadence.escalate_to`` — validated by G-OB7, which checks the target is
  a known agent on the card's handoff allowlist, and then read by no caller at
  all. An exhausted ladder escalated to nobody (RUNTIME-09).

``escalate_to`` is *recorded*, not acted on. cadence.py's contract is that it
may retry an action and never change one, so the card's answer becomes evidence
on the case and the decision stays ``treatment/followthrough.py``'s.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

import cadence
import call_closer

TENANT = "hdfc.retail"
OBJECTIVE = "bounce_cure"


def _needs_escalate_column(conn) -> None:
    from agent_core.treatment.schema_ready import has_column

    if not has_column(conn, "call_cadence_state", "escalate_to"):
        pytest.skip("call_cadence_state.escalate_to not applied yet (20260906_0112)")


def _customer(conn) -> str:
    cid = f"cust-score-{uuid.uuid4().hex[:8]}"
    conn.execute(
        text(
            "INSERT INTO customers (id, tenant_id, name, risk, phone_primary) "
            "VALUES (:id, :tenant, 'Score Test', 'low', '+919000000003')"
        ),
        {"id": cid, "tenant": TENANT},
    )
    return cid


# ---------------------------------------------------------------------------
# What closes the mission
# ---------------------------------------------------------------------------


def test_an_unreadable_card_falls_back_rather_than_failing_the_close(monkeypatch) -> None:
    import mission as mission_mod

    def _boom(*_a, **_k):
        raise RuntimeError("card store down")

    monkeypatch.setattr(mission_mod, "card_for_bot", _boom)
    success, partial = call_closer._outcome_sets({"bot_id": "score-probe"}, OBJECTIVE)
    assert success == call_closer.SUCCESS_BY_OBJECTIVE[OBJECTIVE]
    assert partial == frozenset()


# ---------------------------------------------------------------------------
# Who owns the case once the ladder runs out
# ---------------------------------------------------------------------------


def test_cadence_records_the_target_and_does_not_act_on_it() -> None:
    """The module's stated boundary. A dialler that decided "three no-answers,
    send it to a human" would be a second escalation ladder."""
    import inspect

    src = inspect.getsource(cadence._exhaust)
    assert "escalation_target" in src
    assert "UPDATE call_cadence_state SET escalate_to" in src
    # Nothing here hands the case anywhere: no dial, no queue, no handoff.
    for verb in ("outbound.place", "reserve(", "handoff", "escalate_conversation"):
        assert verb not in src


def test_both_exhaustion_sites_go_through_one_helper() -> None:
    import inspect

    for fn in (cadence.on_outcome, cadence.process_one):
        src = inspect.getsource(fn)
        assert "_exhaust(" in src
        assert 'STATE_EXHAUSTED, "max_attempts"' not in src
