"""Routers validate and return; persistence owns the transaction and the SQL.

A handler that opens ``engine.begin()`` and authors ``text(...)`` is a
persistence module with a URL on it. Every router is walked; there is no
baseline to ratchet.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

_ROUTERS = sorted(p.relative_to(BACKEND).as_posix() for p in (BACKEND / "routers").glob("*.py"))


def _offences(tree: ast.Module) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "sqlalchemy":
            for alias in node.names:
                if alias.name == "text":
                    found.append(f"line {node.lineno}: from sqlalchemy import text")
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in {"text", "_text"}:
            found.append(f"line {node.lineno}: {fn.id}(...)")
        if (
            isinstance(fn, ast.Attribute)
            and fn.attr in {"begin", "connect"}
            and isinstance(fn.value, ast.Attribute)
            and fn.value.attr == "engine"
        ):
            found.append(f"line {node.lineno}: engine.{fn.attr}(")
    return found


@pytest.mark.parametrize("rel", _ROUTERS)
def test_routers_own_no_transactions_and_no_sql(rel: str) -> None:
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
    assert _offences(tree) == [], rel


def test_the_walker_sees_an_offending_router() -> None:
    src = (
        "from sqlalchemy import text as _text\n"
        "def h():\n"
        "    with db.engine.begin() as conn:\n"
        "        conn.execute(_text('SELECT 1'))\n"
    )
    assert len(_offences(ast.parse(src))) == 3


def test_db_py_is_the_crm_kernel() -> None:
    """WP-036: db.py holds engine/readiness/users/roles, Customer 360, promises,
    disputes, payment plans, interactions and the re-export shim -- ~3,000
    lines. Everything else lives in a db_*.py peel."""
    lines = (BACKEND / "db.py").read_text(encoding="utf-8").count("\n")
    assert lines <= 3_200, f"db.py is {lines} lines; peel, do not grow"


def test_peels_reach_the_engine_through_db() -> None:
    """A ``db_*.py`` that binds ``engine`` from ``db_core`` bypasses the
    ``db_tx`` savepoint proxy the tests wrap around ``db.engine``."""
    bad: list[str] = []
    for path in sorted(BACKEND.glob("db_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "db_core":
                if any(alias.name == "engine" for alias in node.names):
                    bad.append(path.name)
    assert bad == [], bad


def test_peels_import_db_core_helpers_instead_of_reaching_through_db() -> None:
    """``_mod = _db(); _rows = _mod._rows`` pulled db_core's helpers through the
    kernel module 488 times. Only ``engine`` goes through ``_db()`` (the
    ``db_tx`` proxy hazard above); every other helper is imported from db_core."""
    bad: list[str] = []
    for path in sorted(BACKEND.glob("db_*.py")):
        if path.name == "db_core.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            base = node.value
            reaches = (isinstance(base, ast.Call) and isinstance(base.func, ast.Name) and base.func.id == "_db") or (
                isinstance(base, ast.Name) and base.id == "_mod"
            )
            if reaches and node.attr.startswith("_"):
                bad.append(f"{path.name}:{node.lineno} {node.attr}")
    assert bad == [], bad
