"""Who may open a tenant-less row to writes.

Row security admits a write to a statutory rule set or the platform budget only
inside platform scope. ``enter`` checks the signed-in actor; ``enter_unattended``
checks nothing, so it is held to the bootstrap that has no actor.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import platform_scope

BACKEND = Path(__file__).resolve().parents[1]
SKIP = {".venv", "tests", "node_modules", "__pycache__"}
UNATTENDED_CALLERS = {"scripts/seed_policy_rules.py"}


def _callers(name: str) -> set[str]:
    found: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if SKIP & set(rel.parts) or rel.as_posix() == "platform_scope.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == name:
                found.add(rel.as_posix())
    return found


def test_only_the_seeder_opens_platform_scope_without_an_actor() -> None:
    assert _callers("enter_unattended") == UNATTENDED_CALLERS


def test_platform_scope_needs_the_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    import authz

    monkeypatch.setattr(authz, "has_permission", lambda _uid, _perm: False)
    executed: list[str] = []

    class Conn:
        def execute(self, *a, **k):
            executed.append("sql")

    with pytest.raises(PermissionError, match="platform_write_required"):
        platform_scope.enter(Conn(), actor_user_id="u-1", reason="test")
    with pytest.raises(PermissionError):
        platform_scope.enter(Conn(), actor_user_id=None, reason="test")
    assert executed == [], "the scope must not open before the check"
