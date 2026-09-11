"""Shared DB fixtures: rollback (``db_tx``) and committing (``db_real``)."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")

_REPO_ROOT = Path(__file__).resolve().parents[2]


def bank_feeds_are_current(conn: Any, *, customer_id: str) -> bool:
    """Declare this borrower's tenant's bank feeds fresh, as of now.

    Returns False when the W5 schema is not applied, so a caller on an older
    database behaves exactly as it did before.

    Why this is a fixture and not a fix. ``bank_boundary/freshness.py`` vetoes
    every contacting action when the C8 feed has not been accepted inside
    ``C8_ENDPOINT_HOURS``, and *absent* counts as stale — correctly, because a
    feed that never arrived is not a fresh one. Nothing seeds ``bank_freshness``:
    it is written by the bank's own inbound contracts, not by ``seed_demo``. So
    the day W5 landed, every test asserting *which* rung the ladder picks began
    getting ``no_eligible_action`` instead — sms and whatsapp vetoed on
    freshness, voice and human on ``ladder_advance_too_far``, field and legal on
    the bucket. Nothing was wrong with those tests and nothing was wrong with
    the veto; they simply stopped establishing a precondition that had come into
    existence underneath them.

    Note for the next person to read a ``freshness:endpoint_stale`` and go
    looking at ``bank_consent_snapshots``: that label is what
    ``freshness.py:210`` reports for *any* ``contacting_blocked``, including a
    missing C8 feed row, which is a portfolio-level lag and has nothing to do
    with an endpoint. The consent snapshot is written here too so both halves
    are satisfied.

    Fail-closed on a missing feed is the right production behaviour and it is
    asserted where it belongs, in ``test_honest_engines_w5.py``. A test about
    rung ordering should not also be a test about feed freshness.
    """
    from agent_core.treatment import schema_ready as _schema_ready

    if not _schema_ready.has_table(conn, "bank_freshness"):
        return False
    row = conn.execute(
        text("SELECT tenant_id, phone_primary FROM customers WHERE id = :cid"),
        {"cid": customer_id},
    ).mappings().first()
    if row is None:
        return False

    from bank_boundary import SHADOW_STREAK_DAYS

    for code in ("C1", "C2", "C5", "C6", "C7", "C8", "C9", "C10"):
        conn.execute(
            text(
                """
                INSERT INTO bank_freshness (
                  tenant_id, portfolio_id, contract_code, last_accepted_at,
                  last_business_date, consecutive_ok_days, lag_hours, updated_at
                ) VALUES (
                  :tid, '', :code, now(), current_date, :streak, 0, now()
                )
                ON CONFLICT (tenant_id, portfolio_id, contract_code) DO UPDATE
                   SET last_accepted_at = now(),
                       last_business_date = current_date,
                       consecutive_ok_days = EXCLUDED.consecutive_ok_days,
                       lag_hours = 0,
                       updated_at = now()
                """
            ),
            {"tid": row["tenant_id"], "code": code, "streak": SHADOW_STREAK_DAYS},
        )

    if row["phone_primary"] and _schema_ready.has_table(
        conn, "bank_consent_snapshots"
    ):
        conn.execute(
            text(
                """
                INSERT INTO bank_consent_snapshots (
                  id, tenant_id, customer_id, endpoint, purpose, channel,
                  permitted, source_ref, event_time, known_from
                ) VALUES (
                  :id, :tid, :cid, :ep, 'all', 'all', TRUE, 'test-fixture',
                  now(), now()
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": f"TESTC8-{customer_id}"[:120],
                "tid": row["tenant_id"],
                "cid": customer_id,
                "ep": row["phone_primary"],
            },
        )
    return True


def frontend_file(*parts: str) -> Path:
    """A path under ``Habibi/``, or skip — except in CI, where it fails.

    Eleven test modules read the frontend tree to pin a hand-written mirror
    against its Python source. The backend container does not mount ``Habibi``,
    so each one grew its own ``pytest.skip``. That is right locally and wrong in
    CI: a pin that skips is a pin that is not holding anything, and the one
    vocabulary that has drifted so far (the card channel map) drifted while its
    pin was green.

    ``CI`` is set by GitHub Actions and unset in the backend container, which is
    exactly the distinction wanted — so the skip stays honest where the file
    genuinely is not there, and becomes a failure where it must be.
    """
    path = _REPO_ROOT.joinpath("Habibi", *parts)
    if path.exists():
        return path
    if os.environ.get("CI"):
        raise AssertionError(
            f"{path} is missing and CI is set — the frontend pin must not skip here"
        )
    pytest.skip(f"frontend tree not mounted: {path}")


@contextmanager
def acting_as(conn, tenant: str):
    """Write (or read) as ``tenant`` for the duration of the block.

    Row-level security is on and the suite runs as the application role, so
    an INSERT of another tenant's row is refused by the policy's WITH CHECK
    unless the connection *is* that tenant. ``SET LOCAL`` moves the tenant
    GUC for this transaction only -- the same thing the request layer does per
    call -- and the block restores the process tenant on the way out, so the
    assertion that follows runs as the tenant under test. Two-tenant tests
    build the rival's rows inside this and assert outside it.
    """
    import db
    import tenant_context

    conn.execute(
        text(f"SET LOCAL {tenant_context.GUC} = '{tenant_context.validate(tenant)}'")
    )
    try:
        yield
    finally:
        conn.execute(
            text(
                f"SET LOCAL {tenant_context.GUC} = "
                f"'{tenant_context.validate(db.current_tenant())}'"
            )
        )


def require_owner(conn, why: str) -> None:
    """Skip unless the connection is the schema owner.

    The suite runs as the application role, which cannot run DDL and cannot
    write rows the policies reserve for the platform (a statutory rule set, a
    platform-wide budget). A test that needs either is a test of the owner's
    path and says so, rather than failing on a privilege it should not have.
    """
    if conn.execute(text("SELECT current_user")).scalar() != "collections":
        pytest.skip(f"needs the schema owner: {why}")


@pytest.fixture
def db_tx(monkeypatch: pytest.MonkeyPatch):
    """Route ``db.engine.begin()`` / ``connect()`` through one outer transaction.

    Domain handlers open their own ``engine.begin()`` blocks; wrapping them in
    nested savepoints lets the fixture roll everything back at teardown.
    """
    import db
    import db_core
    import tenant_context

    connection = db.engine.connect()
    outer = connection.begin()

    def _set_tenant(tenant: str) -> None:
        connection.execute(
            text(f"SET LOCAL {tenant_context.GUC} = '{tenant_context.validate(tenant)}'")
        )

    @contextmanager
    def _bound_tenant():
        """What ``db_core._bind_tenant_for_transaction`` does for a real
        ``engine.begin()``: a call that bound its own tenant gets that tenant
        on the connection for the duration. The fixture's savepoints bypass
        the engine's ``begin`` event, so without this ``tenant_context.bind``
        would move the Python-side tenant and leave the policies reading the
        old one -- every write under the bind refused, every read empty."""
        bound = tenant_context.current_tenant()
        switched = bound != db_core.TENANT_ID
        if switched:
            _set_tenant(bound)
        try:
            yield
        finally:
            if switched:
                _set_tenant(db_core.TENANT_ID)

    @contextmanager
    def _begin():
        nested = connection.begin_nested()
        try:
            with _bound_tenant():
                yield connection
            nested.commit()
        except Exception:
            nested.rollback()
            raise

    class _ConnectCM:
        def __enter__(self):
            self._tenant = _bound_tenant()
            self._tenant.__enter__()
            return connection

        def __exit__(self, *_exc):
            # Do not close the shared fixture connection.
            self._tenant.__exit__(None, None, None)
            return False

        def execute(self, *args, **kwargs):
            return connection.execute(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(connection, name)

    class _EngineProxy:
        def __init__(self, engine):
            self._engine = engine

        def begin(self):
            return _begin()

        def connect(self):
            return _ConnectCM()

        def __getattr__(self, name):
            return getattr(self._engine, name)

    monkeypatch.setattr(db, "engine", _EngineProxy(db.engine))
    try:
        yield connection
    finally:
        outer.rollback()
        connection.close()


class _RealDb:
    """Unwrapped engine plus teardown deletes for tests that must COMMIT.

    ``track`` / ``on_teardown`` are the cleanup. A test that inserts and
    forgets to register the row leaves it in the shared development database
    — that is the cost of real commits, and it is why ``db_tx`` exists for
    every test that does not need a second connection.
    """

    def __init__(self, engine: Any) -> None:
        self.engine = engine
        self._cleanups: list[Callable[[Any], None]] = []

    def begin(self):
        return self.engine.begin()

    def connect(self):
        return self.engine.connect()

    def track(self, table: str, **filters: Any) -> None:
        """Delete matching rows at teardown. Filters are AND-ed equalities."""
        if not _IDENT.fullmatch(table):
            raise ValueError(f"not a table name: {table!r}")
        if not filters:
            raise ValueError("track() needs at least one column filter")
        for column in filters:
            if not _IDENT.fullmatch(column):
                raise ValueError(f"not a column name: {column!r}")
        snapshot = dict(filters)

        def _delete(conn: Any) -> None:
            where = " AND ".join(f"{column} = :{column}" for column in snapshot)
            conn.execute(
                text(f"DELETE FROM {table} WHERE {where}"),  # noqa: S608
                snapshot,
            )

        self._cleanups.append(_delete)

        if table == "audit_log":
            # Deleting audit rows without clearing the persisted chain head
            # leaves the head pointing at a hash no surviving row has, so the
            # *next* run chains onto it and `verify_chain` reports a break for
            # the rest of time. Observed: the head climbed 27 -> 33 across runs
            # while every row was cleaned, so the chain tests failed on a table
            # that was empty. One guard here covers every test that tracks
            # audit rows, rather than one per fixture.
            def _reset_chain_head(conn: Any) -> None:
                import db as _db

                conn.execute(
                    text("DELETE FROM audit_chain_heads WHERE tenant_id = :t"),
                    {"t": _db.current_tenant()},
                )

            self._cleanups.append(_reset_chain_head)

    def on_teardown(self, fn: Callable[[Any], None]) -> None:
        """Run ``fn(conn)`` inside the fixture's cleanup transaction."""
        self._cleanups.append(fn)


@pytest.fixture
def db_real(request: pytest.FixtureRequest):
    """Real pooled connections, real COMMITs, explicit cleanup.

    ``db_tx`` routes every ``engine.begin()`` onto one shared connection as a
    SAVEPOINT. Two blocks are always mutually visible; advisory locks are
    held for the whole test; ``FOR UPDATE SKIP LOCKED`` has nobody to skip.
    Concurrency is structurally untestable under that fixture.

    This sibling leaves ``db.engine`` alone. Two ``begin()`` blocks are two
    connections, visible to each other only after COMMIT — the production
    shape. Tests must register leftover rows: the fixture will not roll
    them back because there is no outer transaction to roll back.

    ``test_job_claim.py`` and ``test_voice_session_store_contention.py``
    already escape ``db_tx`` by hand. This is that pattern, promoted.
    """
    if "db_tx" in request.fixturenames:
        raise pytest.UsageError(
            "db_real and db_tx cannot be requested together: the savepoint "
            "proxy makes two begin() blocks share one connection, which is "
            "the condition db_real exists to escape."
        )

    import db

    handle = _RealDb(db.engine)
    try:
        yield handle
    finally:
        # Not `if not ...: return` — a `return` inside `finally` is a
        # SyntaxWarning on 3.12+ and suppresses in-flight exceptions in any
        # context where one is propagating.
        errors: list[BaseException] = []
        if handle._cleanups:
            with db.engine.begin() as conn:
                for fn in reversed(handle._cleanups):
                    nested = conn.begin_nested()
                    try:
                        fn(conn)
                        nested.commit()
                    except BaseException as exc:  # noqa: BLE001 — surface after the rest run
                        nested.rollback()
                        errors.append(exc)
        if errors:
            raise errors[0]


@pytest.fixture(autouse=True)
def _kb_model_path_off(monkeypatch):
    """Keep the KB planner/judge out of tests unless a test opts in.

    Both call Azure. Left on, the suite makes real network calls, takes minutes
    and — worse — becomes non-deterministic: whether a retrieval is judged
    answerable would depend on the analysis deployment being reachable from CI.
    Tests that exercise the model path enable it explicitly and stub
    ``azure_openai.chat_with_tools``.
    """
    monkeypatch.setenv("KB_PLANNER_ENABLED", "false")


@pytest.fixture(autouse=True)
def _treatment_is_deterministic_unless_a_test_says_otherwise(monkeypatch):
    """Pin the decision engine's stochastic dials to their code defaults.

    ``.env`` now switches exploration on and randomises borrowers into a
    control arm, which is the correct state for a deployment and a terrible one
    for a test suite: the same test would pass or fail depending on which arm a
    borrower's id happened to hash into, and on whether the draw picked the
    top-ranked action or the runner-up.

    That is not a hypothetical. Enabling the engine broke eleven tests at once,
    all of them asserting a specific chosen action, and none of them wrong.

    So the suite states what it is testing. A test that wants exploration or an
    arm sets the variable itself — several below do — and the rest get argmax,
    no split, and the priors, which is what their assertions are about.

    The deployment's own configuration is verified separately, by reading it,
    rather than by leaking into every unrelated assertion in the repository.
    """
    # Load .env FIRST, or the two deletions below do not survive the test.
    #
    # load_env() is lazy and once-only, so in a process where nothing has read
    # an env-backed setting yet, the first `import main` runs it — *after* this
    # fixture. It is non-destructive, so it does not clobber the two setenvs,
    # but it happily re-adds the keys this fixture just deleted, and
    # TREATMENT_AB_SPLIT comes back as control:80,null_treatment:20. The
    # borrower is then randomised into a control arm and the engine suppresses,
    # which is exactly the leakage this fixture was written to prevent.
    #
    # Whether that happened depended on collection order — on whether some
    # earlier test had already touched an env-backed setting — so a test could
    # pass alone and fail in a full run, or the reverse, with nothing about it
    # having changed. Forcing the load here makes the deletions mean what they
    # say for every test, in every order.
    from env_loader import load_env

    load_env()
    monkeypatch.setenv("TREATMENT_GREEDINESS", "1.0")
    monkeypatch.delenv("TREATMENT_AB_SPLIT", raising=False)
    monkeypatch.delenv("TREATMENT_SWEEP", raising=False)
    monkeypatch.setenv("TREATMENT_SCORER", "ev")


@pytest.fixture(scope="session")
def card_and_packs():
    """A first-party card and its skill packs, read from disk. Never empty.

    ``skills.runtime.packs_from_card`` is the runtime resolver and it fails
    *closed* to an empty list when the database is unreachable — correctly, but
    it means a suite that resolved packs the normal way passes by comparing
    empty sets to empty sets wherever pack gating is the thing under test. This
    reads the packs the card names straight off the filesystem instead, so the
    tool-grant tests characterise something whether or not Postgres is up.

    The emptiness assertion is the point of the fixture: without it, an
    environment that resolved nothing would still go green.
    """
    from agent_core.cards.defaults import card_dump
    from agent_core.cards.schema import parse_card
    from agent_core.skills.pack import pack_for_slug

    def _resolve(bot_id: str):
        card = parse_card(card_dump(bot_id))
        packs = tuple(pack_for_slug(ref.skill_id) for ref in card.skills)
        assert packs, f"{bot_id} declares no skill packs — these tests would go vacuous"
        return card, packs

    return _resolve


@pytest.fixture(scope="session")
def api_headers() -> dict[str, str]:
    """Auth headers, but only when the environment is enforcing them.

    ``authz.enforcement_enabled()`` keys off API_KEY / API_KEY_MAP. A dev machine
    sets neither, so every request is answered and a bare ``client.get(...)``
    reads as a pass. CI sets API_KEY -- and several test modules built a
    TestClient and sent no key at all, so they returned 401 on the first CI run
    that ever reached pytest, having looked green locally since they were
    written.

    Reading the ambient key rather than monkeypatching one keeps this usable from
    module- and session-scoped fixtures, and keeps the tests honest in both
    environments: enforcing where enforcement is on, silent where it is off.
    """
    key = (os.getenv("API_KEY") or "").strip()
    if not key:
        return {}
    actor = (os.getenv("ACTOR_USER_ID") or "priya-nair").strip()
    return {"X-API-Key": key, "X-Actor-User-Id": actor}
