"""Invariants the demo seed has to satisfy to be believable.

Customer 360 showed Anita Desai a timeline whose latest outcome was "paid
outstanding in full ... Account is now current", directly above a ledger reading
92 DPD and Rs 12,480 outstanding. Three separate causes, none of which any test
would have caught:

* ``seed_interactions`` only ever read ``calls.json``. The ``interactions``
  array authored on each ``customers.json`` record -- alone among that record's
  children -- was never seeded, so the authored history was dropped and four
  customers had no timeline at all.
* ``calls.json`` named account ids no authored customer owned, so
  ``seed_postgres`` invented an account per unknown id with hash-derived
  outstanding/dpd. The ledger resolved one account and the timeline the other.
* The generated call summaries claimed settled accounts regardless of the
  balance they sat beside.

These are data invariants rather than code paths, so they are asserted against
the seed the demo actually loads.
"""

from __future__ import annotations

import json
import pathlib

from sqlalchemy import text

SEED = pathlib.Path(__file__).resolve().parents[1] / "seed"
TENANT = "hdfc.retail"

#: Phrases that assert the account is square. A collections seed may absolutely
#: contain a payment -- what it may not contain is a payment that closes an
#: account the ledger still shows in arrears.
SETTLED_CLAIMS = ("in full", "now current", "account is settled", "no longer overdue")


def _authored() -> list[dict]:
    return json.loads((SEED / "customers.json").read_text(encoding="utf-8"))


def _calls() -> list[dict]:
    return json.loads((SEED / "calls.json").read_text(encoding="utf-8"))


def test_no_interaction_claims_a_settled_account_the_ledger_still_shows_overdue(db_tx) -> None:
    """The contradiction a demo viewer reads first: outcome vs balance."""
    rows = db_tx.execute(
        text(
            """
            SELECT i.id, i.customer_id, i.disposition, i.summary, a.outstanding, a.dpd
              FROM interactions i
              JOIN accounts a ON a.id = i.account_id
             WHERE i.tenant_id = :t AND a.outstanding > 0 AND a.dpd > 30
            """
        ),
        {"t": TENANT},
    ).mappings().all()

    violations = sorted(
        f"{r['id']} ({r['customer_id']}): {r['disposition']!r} on an account at "
        f"{r['dpd']} DPD with {r['outstanding']} outstanding"
        for r in rows
        if any(claim in (r["summary"] or "").lower() for claim in SETTLED_CLAIMS)
    )
    assert violations == [], violations


def test_every_call_points_at_an_account_its_customer_actually_owns() -> None:
    """An unrecognised accountId does not fail the seed -- it invents an account.

    seed_postgres creates one with a hash-derived balance and DPD, which is how
    a customer ended up owning two accounts telling different stories about the
    same debt. Cheap to assert here, and it names the offending row.
    """
    owned = {c["id"]: c.get("accountId") for c in _authored()}
    violations = sorted(
        f"{call['id']}: {call['customerId']} is on {call.get('accountId')!r}, owns {owned[call['customerId']]!r}"
        for call in _calls()
        if call.get("customerId") in owned and call.get("accountId") != owned[call["customerId"]]
    )
    assert violations == [], violations


def test_an_authored_timeline_reaches_the_database(db_tx) -> None:
    """The regression itself: authored interactions silently not seeded."""
    authored = {c["id"]: c for c in _authored() if c.get("interactions")}
    assert authored, "customers.json authors no interactions - has the seed shape changed?"

    seeded = {
        r[0]
        for r in db_tx.execute(
            text(
                """
                SELECT DISTINCT customer_id FROM interactions
                 WHERE tenant_id = :t AND customer_id = ANY(:ids)
                """
            ),
            {"t": TENANT, "ids": list(authored)},
        )
    }
    missing = sorted(set(authored) - seeded)
    assert missing == [], f"authored a timeline that never reached the table: {missing}"
