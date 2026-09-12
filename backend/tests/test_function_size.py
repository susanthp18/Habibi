"""No production function is longer than 300 lines; the ones that still are may only shrink.

A function that runs to 800 lines is a module without a name: its locals are
its globals, its early returns are its exits, and a move inside it is a
rewrite. Pass 5 took the 859-line text turn, the 588-line sandbox turn, the
639-line retrieval and the four screen readers apart under behaviour
snapshots (``tests/snapshots/*.json``). What is left over the ceiling is
listed here with its measured length; a split lowers the number or removes
the name, and nothing may join the list.

Seeds are data and are not measured; tests, migrations and scripts are not
production modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
CEILING = 300
SKIP_DIRS = {
    "tests",
    "alembic",
    ".venv",
    "node_modules",
    "scripts",
    "seeds",
    "sql",
    "docs",
    "__pycache__",
}

#: ``path::qualname`` -> measured lines on 2026-09-12. Shrink or delete; never add.
BASELINE: dict[str, int] = {
    "voice/bot_handlers_connect.py::build": 360,
    "voice/bot_handlers_connect.py::build.on_client_connected": 325,
}


def _functions(path: Path):
    tree = ast.parse(path.read_bytes())
    stack: list[str] = []

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                stack.append(child.name)
                if not isinstance(child, ast.ClassDef):
                    yield ".".join(stack), child.end_lineno - child.lineno + 1
                yield from walk(child)
                stack.pop()
            else:
                yield from walk(child)

    yield from walk(tree)


def _over_ceiling() -> dict[str, int]:
    out: dict[str, int] = {}
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND)
        if any(part in SKIP_DIRS for part in rel.parts) or rel.name.startswith("seed_"):
            continue
        for qualname, length in _functions(path):
            if length > CEILING:
                out[f"{rel.as_posix()}::{qualname}"] = length
    return out


def test_no_new_function_is_over_the_ceiling() -> None:
    over = _over_ceiling()
    new = {k: v for k, v in over.items() if k not in BASELINE}
    assert (
        not new
    ), f"functions over {CEILING} lines that are not in the baseline: {new}"
    grown = {
        k: (BASELINE[k], v)
        for k, v in over.items()
        if k in BASELINE and v > BASELINE[k]
    }
    assert not grown, f"baselined functions that grew (baseline, now): {grown}"


def test_the_baseline_is_current() -> None:
    """A split lowers the number or removes the name; keep the list honest."""
    over = _over_ceiling()
    stale = {k: v for k, v in BASELINE.items() if over.get(k) != v}
    assert not stale, f"BASELINE entries that no longer match (set to the measured value, or delete): {stale}"
