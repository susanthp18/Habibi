"""Missions, cadence and the outbound compile gates — O2 through O5.

The claims these defend, in rough order of what it would cost to lose them:

* **An outbound call knows why it is happening.** The whole point of a mission.
  Without it every dial ran ``discover_intent`` and asked the borrower why they
  thought we were calling — on a call we placed, for a reason we chose.
* **The graph has more than one door.** One agent, one persona, one authority
  envelope, one compliance surface; several ways in. The alternative is a second
  card per direction, and then two of everything that has to stay in step.
* **Nothing about the debt is said to the wrong person.** The third-party
  protocol is the single place an outbound collections agent is most likely to
  cause real harm.
* **Cadence retries; it never escalates.** A dialler that could change the
  action would be a second treatment engine with no expected value, no
  propensity and no audit trail.
* **A card that cannot work does not publish.** Outbound failures are invisible
  until they are at scale: an inbound bug annoys one caller, an outbound bug
  rings ten thousand phones.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text

import cadence
import mission
from agent_core.tools.catalog import CATALOG


def _gate(report, gate: str):
    return next((g for g in report.gates if g.gate == gate), None)


# ---------------------------------------------------------------------------
# The graph has several doors
# ---------------------------------------------------------------------------


def _graph(entries: dict[str, list[str]], *, start: str = "greet") -> dict:
    nodes = []
    for i, (key, claims) in enumerate(entries.items()):
        nodes.append(
            {
                "id": f"n-{key}",
                "key": key,
                "type": "conversation",
                "position": {"x": 0, "y": i * 150},
                "data": {
                    "name": key,
                    "instructions": "say something",
                    "isStart": key == start,
                    "entryFor": claims,
                    "respondImmediately": True,
                },
            }
        )
    return {"version": 1, "globalTools": [], "nodes": nodes, "edges": []}


# ---------------------------------------------------------------------------
# The mission itself
# ---------------------------------------------------------------------------


def _a_customer(conn) -> dict:
    row = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id, a.id AS account_id
            FROM customers c JOIN accounts a ON a.customer_id = c.id
            WHERE c.id <> 'UNKNOWN-CALLER'
            ORDER BY c.id LIMIT 1
            """
        )
    ).mappings().first()
    if row is None:
        pytest.skip("no seeded customer with an account")
    return dict(row)


def test_trigger_maps_to_one_mission_in_one_place() -> None:
    assert mission.objective_for_trigger("broken_ptp") == "broken_ptp_chase"
    assert mission.objective_for_trigger("bounce") == "bounce_cure"
    assert mission.objective_for_trigger(None) == "dpd_reminder"


# ---------------------------------------------------------------------------
# Cadence
# ---------------------------------------------------------------------------


def test_a_short_backoff_curve_repeats_rather_than_running_out() -> None:
    """[4, 24] on a three-attempt cadence means 4h, 24h, 24h — which is what an
    author writing two numbers means."""
    assert cadence.backoff_for(1, [4, 24]) == timedelta(hours=4)
    assert cadence.backoff_for(2, [4, 24]) == timedelta(hours=24)
    assert cadence.backoff_for(3, [4, 24]) == timedelta(hours=24)


def test_a_backoff_is_capped_however_long_the_card_asks_for() -> None:
    """A 30-day wait is not a cadence, it is a case somebody forgot about."""
    assert cadence.backoff_for(1, [24 * 90]) <= timedelta(
        hours=cadence.max_backoff_hours()
    )


def _open_case(conn, cust, objective="dpd_reminder", case_ref="TD-CADENCE"):
    return cadence.ensure_case(
        conn,
        tenant_id=cust["tenant_id"],
        customer_id=cust["id"],
        objective=objective,
        case_ref=case_ref,
        max_attempts=3,
    )


def _attempt_row(cust, *, state, objective="dpd_reminder", case_ref="TD-CADENCE"):
    return {
        "id": "CA-PROBE",
        "tenant_id": cust["tenant_id"],
        "customer_id": cust["id"],
        "objective": objective,
        "decision_id": case_ref,
        "campaign_run_id": None,
        "state": state,
        "attempt_no": 1,
    }


def test_a_manual_dial_does_not_open_a_ladder(db_tx) -> None:
    """Somebody pressed a button. That is not a campaign."""
    assert cadence._case_ref({"decision_id": None, "campaign_run_id": None}) == ""


# ---------------------------------------------------------------------------
# The outbound compile gates
# ---------------------------------------------------------------------------


