"""The production modules, without walking what is not ours.

``Path.rglob`` enumerates ``.venv`` and ``node_modules`` before a filter can
drop them -- tens of thousands of files, and over the container's bind mount
that is minutes per test. This prunes the walk instead, so the three
tree-wide pins (function size, environment reads, one clock) cost seconds.
"""

from __future__ import annotations

import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PRUNE = {"tests", "scripts", "alembic", ".venv", "node_modules", "__pycache__", "seeds", ".cache", ".git"}


def production_modules(*, prune: set[str] | None = None) -> list[Path]:
    """Every ``*.py`` under the backend outside the pruned directories, sorted."""
    skip = PRUNE if prune is None else prune
    out: list[Path] = []
    for root, dirs, files in os.walk(BACKEND):
        dirs[:] = sorted(d for d in dirs if d not in skip)
        for name in files:
            if name.endswith(".py"):
                out.append(Path(root) / name)
    return sorted(out)
