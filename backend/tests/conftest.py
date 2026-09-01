"""Rollback fixture for domain handler tests — no leftover CRM rows."""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest


@pytest.fixture
def db_tx(monkeypatch: pytest.MonkeyPatch):
    """Route ``db.engine.begin()`` / ``connect()`` through one outer transaction.

    Domain handlers open their own ``engine.begin()`` blocks; wrapping them in
    nested savepoints lets the fixture roll everything back at teardown.
    """
    import db

    connection = db.engine.connect()
    outer = connection.begin()

    @contextmanager
    def _begin():
        nested = connection.begin_nested()
        try:
            yield connection
            nested.commit()
        except Exception:
            nested.rollback()
            raise

    class _ConnectCM:
        def __enter__(self):
            return connection

        def __exit__(self, *_exc):
            # Do not close the shared fixture connection.
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
