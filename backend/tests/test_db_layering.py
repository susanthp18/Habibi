"""Routers validate and return; persistence owns the transaction and the SQL.

A handler that opens ``engine.begin()`` and authors ``text(...)`` is a
persistence module with a URL on it. The peeled routers are listed here; the
rest join as they are peeled.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

_PEELED_ROUTERS = (
    "routers/outbound.py",
    "routers/compliance.py",
    "routers/crm.py",
    "routers/evals.py",
    "routers/agent_studio.py",
    "routers/platform.py",
    "routers/payments.py",
    "routers/webhooks.py",
    "routers/telephony.py",
    "routers/integrations.py",
)


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


@pytest.mark.parametrize("rel", _PEELED_ROUTERS)
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
