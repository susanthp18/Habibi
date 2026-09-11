"""``db_real`` — real connections, real COMMITs, contention becomes testable.

``db_tx`` makes two ``engine.begin()`` blocks the same connection. Advisory
locks stay held for the whole test, and every ``SKIP LOCKED`` claim path is
verified by a harness that cannot produce a second locker. This file is the
mutation check for the fixture that closes that: delete
``pg_advisory_xact_lock`` in ``_idempotent_response`` and
``test_two_concurrent_posts_with_the_same_key_create_one_promise`` goes red.

The sequential suite in ``test_idempotency.py`` / ``test_idempotency_tenant_scope.py``
stays green either way — that is the whole finding.
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import timedelta

from agent_core import clock
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


def test_db_real_leaves_the_engine_unwrapped(db_real) -> None:
    """The savepoint proxy is ``db_tx``. This fixture must not install one."""
    import db
    import db_core

    assert isinstance(db.engine, Engine)
    assert db.engine is db_core.engine
    assert type(db.engine).__name__ != "_EngineProxy"
    assert db_real.engine is db.engine


def test_db_real_two_begins_are_two_backend_pids(db_real) -> None:
    """The property ``db_tx`` structurally cannot provide."""
    pids: list[int] = []
    with db_real.begin() as first, db_real.begin() as second:
        pids.append(first.execute(text("SELECT pg_backend_pid()")).scalar())
        pids.append(second.execute(text("SELECT pg_backend_pid()")).scalar())
    assert pids[0] != pids[1], pids


def test_db_real_commit_is_visible_on_a_second_connection(db_real) -> None:
    """A COMMIT on one connection is a row the next connection can read."""
    import db

    key = f"db-real-vis-{uuid.uuid4().hex}"
    endpoint = "POST /db-real-fixture"
    db_real.track("idempotency_keys", key=key, endpoint=endpoint)
    with db_real.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO idempotency_keys (tenant_id, key, endpoint, response)
                VALUES (:t, :k, :e, CAST(:r AS jsonb))
                """
            ),
            {
                "t": db.current_tenant(),
                "k": key,
                "e": endpoint,
                "r": '{"ok": true}',
            },
        )
    with db_real.begin() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM idempotency_keys WHERE key = :k AND endpoint = :e"
            ),
            {"k": key, "e": endpoint},
        ).scalar()
    assert n == 1


def _seeded_customer(db_real) -> tuple[str, str]:
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


class _SilentFulfillment:
    """``create_promise`` always calls fulfill(); we want no outbound side effects."""

    spoken_summary = ""

    def as_dict(self) -> dict:
        return {}


def test_two_concurrent_posts_with_the_same_key_create_one_promise(
    db_real, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two requests, one key, one promise — the reason the advisory lock exists.

    The read alone was not enough: both callers saw no ``idempotency_keys``
    row, both inserted a promise, and the second ``ON CONFLICT DO NOTHING``
    store discarded its response. ``pg_advisory_xact_lock`` makes the second
    wait for the first to COMMIT, so its SELECT sees the stored body.

    That wait is a no-op under ``db_tx`` (one connection, no COMMIT). This
    test uses ``db_real`` so removing the lock turns it red.
    """
    import db
    import promise_fulfillment

    monkeypatch.setattr(
        promise_fulfillment,
        "fulfill",
        lambda *_a, **_k: _SilentFulfillment(),
    )

    customer_id, account_id = _seeded_customer(db_real)
    if not db.user_exists("priya-nair"):
        pytest.skip("priya-nair required for human-owned PTP")

    key = f"ptp-contention-{uuid.uuid4().hex}"
    amount = 10_000 + (uuid.uuid4().int % 89_999)
    promised = (clock.today_local() + timedelta(days=14)).isoformat()
    payload = {
        "customerId": customer_id,
        "accountId": account_id,
        "amount": amount,
        "promisedDate": promised,
        "channel": "whatsapp",
        "ownerUserId": "priya-nair",
        "reminderStatus": "off",
    }

    def _sweep(conn) -> None:
        conn.execute(
            text(
                """
                DELETE FROM payment_intents
                 WHERE promise_id IN (
                    SELECT id FROM promises
                     WHERE customer_id = :c AND amount = :a
                 )
                """
            ),
            {"c": customer_id, "a": amount},
        )
        conn.execute(
            text(
                """
                DELETE FROM activity_events
                 WHERE entity_type = 'promise'
                   AND entity_id IN (
                    SELECT id FROM promises
                     WHERE customer_id = :c AND amount = :a
                   )
                """
            ),
            {"c": customer_id, "a": amount},
        )
        conn.execute(
            text("DELETE FROM promises WHERE customer_id = :c AND amount = :a"),
            {"c": customer_id, "a": amount},
        )
        conn.execute(
            text(
                "DELETE FROM idempotency_keys WHERE key = :k AND endpoint = :e"
            ),
            {"k": key, "e": "POST /promises"},
        )

    db_real.on_teardown(_sweep)

    orig = db._idempotent_response
    both_in = threading.Barrier(2)

    def _gated(conn, idem_key, endpoint):
        # Both callers hold a transaction before either takes the lock, so the
        # unlocked race is two empty SELECTs rather than one finishing before
        # the other has begun. The sleep after an empty read widens the window
        # between SELECT and INSERT; with the lock the partner is blocked on
        # Postgres for that whole sleep, not sitting at this barrier.
        both_in.wait(timeout=5)
        found = orig(conn, idem_key, endpoint)
        if found is None:
            time.sleep(0.1)
        return found

    monkeypatch.setattr(db, "_idempotent_response", _gated)

    results: list[dict | BaseException | None] = [None, None]
    errors: list[BaseException] = []

    def caller(idx: int) -> None:
        try:
            results[idx] = db.create_promise(payload, idempotency_key=key)
        except BaseException as exc:  # noqa: BLE001 — surface in the main thread
            errors.append(exc)
            results[idx] = exc
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
        raise AssertionError(f"{len(alive)} create_promise thread(s) did not finish")

    assert not errors, errors
    bodies = [row for row in results if isinstance(row, dict)]
    assert len(bodies) == 2, results
    assert bodies[0]["id"] == bodies[1]["id"], (
        f"two promises for one idempotent POST: {bodies[0]['id']} vs {bodies[1]['id']}"
    )

    with db_real.begin() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM promises WHERE customer_id = :c AND amount = :a"
            ),
            {"c": customer_id, "a": amount},
        ).scalar()
    assert n == 1, f"expected one promise row, found {n}"


def test_two_concurrent_first_messages_open_one_whatsapp_thread(
    db_real, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two first messages, one thread — `_open_whatsapp_conversation` is serialised.

    The get-or-create was SELECT-latest-then-INSERT with nothing between
    them, so two webhooks arriving together both read "no thread" and both
    inserted one; the customer's history then lived on two rows the Inbox
    showed as two people. The per-customer advisory lock makes the second
    wait for the first COMMIT. A no-op under `db_tx`; red without the lock
    here.
    """
    import db
    import db_inbox

    with db_real.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT c.id FROM customers c
                 WHERE c.id <> 'UNKNOWN-CALLER'
                   AND NOT EXISTS (
                     SELECT 1 FROM conversations v
                      WHERE v.customer_id = c.id AND v.channel = 'whatsapp'
                   )
                 ORDER BY c.id LIMIT 1
                """
            )
        ).mappings().first()
    if not row:
        pytest.skip("every seeded customer already has a WhatsApp thread")
    customer_id = row["id"]

    def _sweep(conn) -> None:
        conn.execute(
            text("DELETE FROM conversations WHERE customer_id = :c AND channel = 'whatsapp'"),
            {"c": customer_id},
        )
        conn.execute(
            text(
                "DELETE FROM interactions WHERE customer_id = :c AND channel = 'whatsapp' "
                "AND started_at >= now() - interval '5 minutes'"
            ),
            {"c": customer_id},
        )

    db_real.on_teardown(_sweep)

    orig = db_inbox._one
    both_in = threading.Barrier(2)
    gate_armed = {"n": 0}

    def _gated(result):
        # Hold both callers at the thread SELECT so the unlocked race is two
        # empty reads. With the lock, the partner is blocked in Postgres and
        # never reaches this barrier, hence the timeout-tolerant wait.
        found = orig(result)
        if gate_armed["n"] < 2:
            gate_armed["n"] += 1
            try:
                both_in.wait(timeout=1)
            except threading.BrokenBarrierError:
                pass
        return found

    monkeypatch.setattr(db_inbox, "_one", _gated)

    results: list[str | BaseException | None] = [None, None]

    def caller(idx: int) -> None:
        try:
            with db.engine.begin() as conn:
                results[idx] = db_inbox._open_whatsapp_conversation(conn, customer_id)
        except BaseException as exc:  # noqa: BLE001 — surface in the main thread
            results[idx] = exc

    threads = [threading.Thread(target=caller, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert all(isinstance(r, str) for r in results), results
    assert results[0] == results[1]
    with db_real.begin() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM conversations WHERE customer_id = :c AND channel = 'whatsapp'"),
            {"c": customer_id},
        ).scalar_one()
    assert n == 1
