"""Rollback fixture for domain handler tests — no leftover CRM rows."""

from __future__ import annotations

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
        def begin(self):
            return _begin()

        def connect(self):
            return _ConnectCM()

    monkeypatch.setattr(db, "engine", _EngineProxy())
    try:
        yield connection
    finally:
        outer.rollback()
        connection.close()
