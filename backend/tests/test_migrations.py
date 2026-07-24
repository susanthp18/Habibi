"""Alembic integrity — single head; optional upgrade/downgrade on scratch DB."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_alembic_has_exactly_one_head() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    # alembic heads prints one line per head like: "<rev> (head)"
    heads = [ln for ln in lines if "(head)" in ln or ln]
    # Filter noise — keep lines that look like revision ids
    rev_lines = [ln for ln in lines if "head" in ln.lower()]
    assert len(rev_lines) == 1, f"expected 1 alembic head, got: {lines}"


@pytest.mark.skipif(
    (os.getenv("RUN_ALEMBIC_ROUNDTRIP") or "").strip().lower()
    not in {"1", "true", "yes"},
    reason="set RUN_ALEMBIC_ROUNDTRIP=1 to exercise upgrade/downgrade on DB",
)
def test_alembic_upgrade_downgrade_roundtrip() -> None:
    """upgrade head then downgrade -1 on the configured DATABASE_URL.

    Destructive against the connected DB — only enable in CI scratch DBs.
    """
    up = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ALEMBIC_SEED_DEMO": ""},
    )
    assert up.returncode == 0, up.stderr + up.stdout

    down = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "-1"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ALEMBIC_SEED_DEMO": ""},
    )
    assert down.returncode == 0, down.stderr + down.stdout

    # Restore head so local/CI DB stays at tip for other tests.
    restore = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "ALEMBIC_SEED_DEMO": ""},
    )
    assert restore.returncode == 0, restore.stderr + restore.stdout
