"""WP-037 — a rolled-back caller leaves no Locked Engine decision row.

``db_tx`` routes every ``engine.begin()`` onto one shared connection as a
SAVEPOINT, so a log write on a *second* connection is invisible to the
fixture's rollback. This file uses ``db_real``: two connections, real
COMMITs, and a rollback that only retracts what was written on the caller's
connection.

Re-introducing ``db.engine.connect()`` / ``db.engine.begin()`` inside any of
the four engines (or writing the reco log on a connection the caller does
not own) turns these red.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import text

from agent_core.authority import recommend_authority
from agent_core.live_qa import TurnFacts, evaluate_live_qa
from agent_core.reco import recommend
from agent_core.treatment import Trigger, recommend_treatment


def _seeded_account(db_real) -> tuple[str, str]:
    row = None
    with db_real.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT c.id, a.id AS account_id
                FROM customers c
                JOIN accounts a ON a.customer_id = c.id
                WHERE c.id <> 'UNKNOWN-CALLER'
                ORDER BY c.id
                LIMIT 1
                """
            )
        ).mappings().first()
    if not row:
        pytest.skip("no customers seeded")
    return row["id"], row["account_id"]


def _visible(db_real, table: str, decision_id: str) -> int:
    with db_real.begin() as conn:
        return int(
            conn.execute(
                text(f"SELECT count(*) FROM {table} WHERE id = :id"),  # noqa: S608
                {"id": decision_id},
            ).scalar()
            or 0
        )


def _rollback_call(db_real, table: str, run):
    """Call ``run(conn)``, roll back, assert the decision id is gone."""
    decision_id = None
    conn = db_real.connect()
    trans = conn.begin()
    try:
        result = run(conn)
        decision_id = getattr(result, "decision_id", None)
        assert decision_id, result
        trans.rollback()
    except Exception:
        trans.rollback()
        raise
    finally:
        conn.close()

    n = _visible(db_real, table, decision_id)
    if n:
        db_real.track(table, id=decision_id)
    assert n == 0, f"{table} {decision_id} survived the caller's rollback"


def test_recommend_treatment_requires_conn() -> None:
    with pytest.raises(TypeError):
        recommend_treatment(customer_id="x")


def test_recommend_authority_requires_conn() -> None:
    with pytest.raises(TypeError):
        recommend_authority(customer_id="x")


def test_recommend_requires_conn() -> None:
    with pytest.raises(TypeError):
        recommend(customer_id="x")


def test_evaluate_live_qa_requires_conn() -> None:
    with pytest.raises(TypeError):
        evaluate_live_qa(TurnFacts())


def test_conn_has_no_default_on_the_four_engines() -> None:
    """The fallback was a default of None. An optional conn is the bug."""
    for fn in (
        recommend_treatment,
        recommend_authority,
        recommend,
        evaluate_live_qa,
    ):
        param = inspect.signature(fn).parameters["conn"]
        assert param.default is inspect.Parameter.empty, fn.__qualname__


def test_a_rolled_back_treatment_leaves_no_decision_row(db_real) -> None:
    customer_id, account_id = _seeded_account(db_real)

    def run(conn):
        return recommend_treatment(
            customer_id=customer_id,
            account_id=account_id,
            trigger=Trigger(kind="manual"),
            conn=conn,
            force_mode="shadow",
        )

    _rollback_call(db_real, "treatment_decisions", run)


def test_a_rolled_back_authority_leaves_no_decision_row(db_real) -> None:
    customer_id, account_id = _seeded_account(db_real)

    def run(conn):
        return recommend_authority(
            customer_id=customer_id,
            account_id=account_id,
            asked_amount=200,
            conn=conn,
            force_mode="shadow",
        )

    _rollback_call(db_real, "authority_decisions", run)


def test_a_rolled_back_reco_leaves_no_decision_row(db_real) -> None:
    customer_id, _account_id = _seeded_account(db_real)

    def run(conn):
        return recommend(
            customer_id=customer_id,
            conn=conn,
            channel="voice",
            force_mode="shadow",
        )

    _rollback_call(db_real, "offer_decisions", run)


def test_a_rolled_back_live_qa_leaves_no_decision_row(db_real) -> None:
    def run(conn):
        return evaluate_live_qa(
            TurnFacts(
                channel="voice",
                bot_text="hello",
                now_hour=20,
                identity_verified=True,
                turn_index=2,
            ),
            conn=conn,
            force_mode="shadow",
        )

    _rollback_call(db_real, "live_qa_decisions", run)
