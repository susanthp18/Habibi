"""Concurrent goodwill posts: one decision, one dispute, one ledger row.

``db_tx`` makes two ``engine.begin()`` blocks the same connection, so the
``SELECT … FOR UPDATE`` serialisation WP-041 / WP-073 need is structurally
untestable there. This file uses ``db_real``.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from sqlalchemy import text

from agent_core.authority.enact import AuthorityError, apply_goodwill, post_waiver_for_dispute


def _insert_eligible(db_real) -> tuple[str, str]:
    """A throwaway account the matrix will auto-approve. Not a seed mutation."""
    import db

    suffix = uuid.uuid4().hex[:10]
    customer_id = f"wp041-c-{suffix}"
    account_id = f"wp041-a-{suffix}"
    fee_id = f"wp041-fee-{suffix}"

    with db_real.begin() as conn:
        product_id = conn.execute(
            text("SELECT id FROM products WHERE tenant_id = :t ORDER BY id LIMIT 1"),
            {"t": db.current_tenant()},
        ).scalar()
    if not product_id:
        pytest.skip("seed has no product for the default tenant")

    with db_real.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO customers (id, tenant_id, name, risk)
                VALUES (:id, :t, 'WP-041', 'low')
                """
            ),
            {"id": customer_id, "t": db.current_tenant()},
        )
        conn.execute(
            text(
                """
                INSERT INTO accounts (
                  id, customer_id, product_id, status, dpd, outstanding, opened_on
                ) VALUES (
                  :id, :cid, :pid, 'active', 12, 25000, now() - interval '18 months'
                )
                """
            ),
            {"id": account_id, "cid": customer_id, "pid": product_id},
        )
        conn.execute(
            text(
                """
                INSERT INTO ledger_entries (id, account_id, type, description, amount, posted_at)
                VALUES (:id, :aid, 'fee', 'Late fee', 800, now())
                """
            ),
            {"id": fee_id, "aid": account_id},
        )

    def _sweep(conn) -> None:
        conn.execute(
            text(
                """
                DELETE FROM activity_events
                 WHERE entity_id = :cid
                    OR entity_id IN (
                        SELECT id FROM disputes WHERE customer_id = :cid
                    )
                    OR entity_id IN (
                        SELECT id FROM authority_decisions WHERE customer_id = :cid
                    )
                """
            ),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM authority_decisions WHERE customer_id = :cid"),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM disputes WHERE customer_id = :cid"),
            {"cid": customer_id},
        )
        conn.execute(
            text("DELETE FROM ledger_entries WHERE account_id = :aid"),
            {"aid": account_id},
        )
        conn.execute(text("DELETE FROM accounts WHERE id = :aid"), {"aid": account_id})
        conn.execute(text("DELETE FROM customers WHERE id = :cid"), {"cid": customer_id})

    db_real.on_teardown(_sweep)
    return customer_id, account_id


def test_two_concurrent_apply_goodwill_calls_post_one_waiver(
    db_real, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Acceptance for WP-041 / MF-041. Removing the row lock and the rowcount
    check (and the unique indexes) turns this red.
    """
    monkeypatch.setenv("AUTHORITY_MODE", "live")
    customer_id, account_id = _insert_eligible(db_real)

    from agent_core.authority import recommend_authority

    with db_real.begin() as conn:
        result = recommend_authority(
            customer_id=customer_id,
            account_id=account_id,
            asked_amount=400,
            conn=conn,
        )
    assert result.decision_id
    assert result.actionable is True

    both_in = threading.Barrier(2)
    outcomes: list[dict | BaseException | None] = [None, None]
    errors: list[BaseException] = []

    def caller(idx: int) -> None:
        try:
            both_in.wait(timeout=5)
            outcomes[idx] = apply_goodwill(
                decision_id=result.decision_id, amount=400
            )
        except BaseException as exc:  # noqa: BLE001 — surface in the main thread
            errors.append(exc)
            outcomes[idx] = exc
            try:
                both_in.abort()
            except RuntimeError:
                pass

    threads = [threading.Thread(target=caller, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    alive = [thread for thread in threads if thread.is_alive()]
    if alive:
        raise AssertionError(f"{len(alive)} apply_goodwill thread(s) did not finish")

    posted = [row for row in outcomes if isinstance(row, dict)]
    refused = [
        exc
        for exc in outcomes
        if isinstance(exc, AuthorityError) and "already_applied" in str(exc)
    ]
    surprises = [
        exc
        for exc in errors
        if not (isinstance(exc, AuthorityError) and "already_applied" in str(exc))
    ]
    assert not surprises, surprises
    assert len(posted) == 1, outcomes
    assert len(refused) == 1, outcomes
    assert posted[0]["amount"] == 400

    with db_real.begin() as conn:
        n = conn.execute(
            text(
                """
                SELECT count(*) FROM ledger_entries
                 WHERE account_id = :aid AND type = 'waiver'
                """
            ),
            {"aid": account_id},
        ).scalar()
        outstanding = conn.execute(
            text("SELECT outstanding FROM accounts WHERE id = :aid"),
            {"aid": account_id},
        ).scalar()
    assert n == 1, f"expected one waiver row, found {n}"
    assert float(outstanding) == pytest.approx(24600.0)


def _insert_open_dispute(db_real, *, amount: float = 350) -> tuple[str, str, str]:
    """Throwaway dispute the specialist desk would resolve as waived."""
    customer_id, account_id = _insert_eligible(db_real)
    dispute_id = f"wp073-d-{uuid.uuid4().hex[:10]}"
    with db_real.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO disputes (
                  id, customer_id, account_id, type, disputed_amount, source,
                  status, priority
                ) VALUES (
                  :id, :cid, :aid, 'fee_waiver', :amount, 'agent',
                  'new', 'normal'
                )
                """
            ),
            {
                "id": dispute_id,
                "cid": customer_id,
                "aid": account_id,
                "amount": amount,
            },
        )
    return customer_id, account_id, dispute_id


def _join_two(caller) -> tuple[list, list[BaseException]]:
    both_in = threading.Barrier(2)
    outcomes: list[object | BaseException | None] = [None, None]
    errors: list[BaseException] = []

    def run(idx: int) -> None:
        try:
            both_in.wait(timeout=5)
            outcomes[idx] = caller(idx)
        except BaseException as exc:  # noqa: BLE001 — surface in the main thread
            errors.append(exc)
            outcomes[idx] = exc
            try:
                both_in.abort()
            except RuntimeError:
                pass

    threads = [threading.Thread(target=run, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    alive = [thread for thread in threads if thread.is_alive()]
    if alive:
        raise AssertionError(f"{len(alive)} thread(s) did not finish")
    return outcomes, errors


def test_two_concurrent_dispute_waivers_post_one_ledger_row(db_real) -> None:
    """Acceptance for WP-073. Removing the row lock and the unique on
    ``ledger_entries.dispute_id`` turns this red.
    """
    import db

    _customer_id, account_id, dispute_id = _insert_open_dispute(db_real)

    def caller(_idx: int):
        with db.engine.begin() as conn:
            return post_waiver_for_dispute(conn, dispute_id=dispute_id)

    outcomes, errors = _join_two(caller)
    posted = [row for row in outcomes if isinstance(row, dict)]
    skipped = [row for row in outcomes if row is None]
    refused = [
        exc
        for exc in outcomes
        if isinstance(exc, AuthorityError) and "already_applied" in str(exc)
    ]
    surprises = [
        exc
        for exc in errors
        if not (isinstance(exc, AuthorityError) and "already_applied" in str(exc))
    ]
    assert not surprises, surprises
    assert len(posted) == 1, outcomes
    assert len(skipped) + len(refused) == 1, outcomes
    assert posted[0]["amount"] == 350

    with db_real.begin() as conn:
        n = conn.execute(
            text(
                """
                SELECT count(*) FROM ledger_entries
                 WHERE account_id = :aid AND type = 'waiver'
                """
            ),
            {"aid": account_id},
        ).scalar()
        keyed = conn.execute(
            text(
                """
                SELECT count(*) FROM ledger_entries
                 WHERE dispute_id = :id AND type = 'waiver'
                """
            ),
            {"id": dispute_id},
        ).scalar()
        outstanding = conn.execute(
            text("SELECT outstanding FROM accounts WHERE id = :aid"),
            {"aid": account_id},
        ).scalar()
        status = conn.execute(
            text("SELECT status, resolution_code FROM disputes WHERE id = :id"),
            {"id": dispute_id},
        ).mappings().first()
    assert n == 1, f"expected one waiver row, found {n}"
    assert keyed == 1
    assert float(outstanding) == pytest.approx(24650.0)
    assert status["status"] == "resolved"
    assert status["resolution_code"] == "valid_waive_fee"


def test_two_concurrent_resolves_post_one_waiver(db_real) -> None:
    """The operator path: two PATCH resolves of one dispute."""
    import db

    _customer_id, account_id, dispute_id = _insert_open_dispute(db_real)

    def caller(_idx: int):
        return db.patch_dispute(
            dispute_id,
            {"status": "resolved", "resolutionCode": "valid_waive_fee"},
        )

    outcomes, errors = _join_two(caller)
    succeeded = [row for row in outcomes if isinstance(row, dict)]
    refused = [
        exc
        for exc in outcomes
        if isinstance(exc, AuthorityError) and "already_applied" in str(exc)
    ]
    surprises = [
        exc
        for exc in errors
        if not (isinstance(exc, AuthorityError) and "already_applied" in str(exc))
    ]
    assert not surprises, surprises
    assert len(succeeded) + len(refused) == 2, outcomes
    assert len(succeeded) >= 1, outcomes

    with db_real.begin() as conn:
        n = conn.execute(
            text(
                """
                SELECT count(*) FROM ledger_entries
                 WHERE account_id = :aid AND type = 'waiver'
                """
            ),
            {"aid": account_id},
        ).scalar()
        outstanding = conn.execute(
            text("SELECT outstanding FROM accounts WHERE id = :aid"),
            {"aid": account_id},
        ).scalar()
        status = conn.execute(
            text("SELECT status, resolution_code FROM disputes WHERE id = :id"),
            {"id": dispute_id},
        ).mappings().first()
    assert n == 1, f"expected one waiver row, found {n}"
    assert float(outstanding) == pytest.approx(24650.0)
    assert status["status"] == "resolved"
    assert status["resolution_code"] == "valid_waive_fee"
