"""WP-035: engine, begin-listener and row helpers live in ``db_core``.

``db.py`` re-exports them so ``import db`` call sites keep resolving. The
engine and its listener must be the same object, created once. Carved
modules must reach the engine through ``db_core._db().engine``: the
``db_tx`` fixture wraps ``db.engine``, and a ``from db_core import engine``
binding bypasses that proxy.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine

import db
import db_core

BACKEND = Path(__file__).resolve().parents[1]

_SHIMMED = (
    "ACTOR_USER_ID",
    "DATABASE_URL",
    "DB_MAX_OVERFLOW",
    "DB_POOL_RECYCLE",
    "DB_POOL_SIZE",
    "DB_STATEMENT_TIMEOUT_MS",
    "DEFAULT_DATABASE_URL",
    "DEFAULT_LIST_LIMIT",
    "MAX_LIST_LIMIT",
    "TENANT_ID",
    "_IST",
    "_account_tail",
    "_activity",
    "_actor_user_id",
    "_as_dict",
    "_as_utc",
    "_assert_tenant_owns",
    "_bind_tenant_for_transaction",
    "_dump",
    "_id",
    "_jsonb",
    "_one",
    "_rows",
    "_speaker_screen",
    "_sql",
    "_tenant",
    "_vis_params",
    "clamp_list_limit",
    "clamp_offset",
    "current_tenant",
    "engine",
)


def test_create_engine_ran_once_and_the_listener_is_on_that_object() -> None:
    """Moving the engine and the begin hook in separate commits is the failure mode."""
    assert isinstance(db_core.engine, Engine)
    assert db.engine is db_core.engine
    assert event.contains(db_core.engine, "begin", db_core._bind_tenant_for_transaction)
    assert db._bind_tenant_for_transaction is db_core._bind_tenant_for_transaction


def test_db_reexports_db_core_helpers_as_the_same_objects() -> None:
    """Zero call-site edits: ``import db; db._rows`` is still the helper."""
    for name in _SHIMMED:
        assert getattr(db, name) is getattr(db_core, name), name


def test_db_tx_proxy_wraps_db_engine_not_db_core_engine(db_tx) -> None:
    """The hazard this commit must pin, not discover on peel #3.

    ``monkeypatch.setattr(db, "engine", _EngineProxy(db.engine))`` replaces
    the name on the ``db`` module. ``db_core.engine`` stays the raw Engine.
    A carved module that binds ``from db_core import engine`` bypasses the
    savepoint wrapper; ``outer.rollback()`` rolls back nothing it wrote.
    """
    assert db.engine is not db_core.engine
    assert type(db.engine).__name__ == "_EngineProxy"


def test_carved_modules_must_reach_the_engine_through_db(db_tx) -> None:
    """``_db().engine`` is the wrapped name; ``db_core.engine`` is not."""
    assert db_core._db() is db
    assert db_core._db().engine is db.engine
    assert db_core._db().engine is not db_core.engine


def test_no_production_module_binds_engine_from_db_core() -> None:
    """``db.py`` is the shim. Every other module must use ``_db().engine``."""
    bind_from = re.compile(r"from\s+db_core\s+import\s+\(?([^)]+)\)?", re.S)
    attr_engine = re.compile(r"\bdb_core\.engine\b")
    skip_dirs = {".venv", "tests", "__pycache__", ".pytest_cache", "htmlcov"}
    offenders: list[str] = []
    for dirpath, dirnames, filenames in os.walk(BACKEND):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            if path.name in {"db.py", "db_core.py"}:
                continue
            source = path.read_text(encoding="utf-8")
            if attr_engine.search(source):
                offenders.append(f"{path.relative_to(BACKEND)}: db_core.engine")
                continue
            for match in bind_from.finditer(source):
                names = [n.strip().split(" as ")[0].strip() for n in match.group(1).split(",")]
                if "engine" in names:
                    offenders.append(f"{path.relative_to(BACKEND)}: from db_core import engine")
    assert offenders == []


def test_db_py_does_not_call_create_engine() -> None:
    """The engine is created in db_core. A second create_engine here is the bug."""
    tree = ast.parse((BACKEND / "db.py").read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "create_engine")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "create_engine"
            )
        )
    ]
    assert calls == []
