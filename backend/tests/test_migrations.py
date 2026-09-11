"""Alembic integrity — single head; optional upgrade/downgrade on scratch DB."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest

BACKEND = Path(__file__).resolve().parents[1]

# A destructive downgrade may only run against a database whose name says it is
# disposable. Keep in sync with the scratch DBs CI creates.
_SCRATCH_DB_MARKERS = frozenset({"test", "scratch", "ci"})


def _looks_like_scratch_db(db_name: str) -> bool:
    """True when a marker appears as a whole delimiter-bounded word.

    A bare substring test accepts ``contest``, ``financial`` and ``precise``.
    This guard exists to refuse a destructive downgrade, so it must not be the
    permissive kind of match.
    """
    return any(
        re.search(rf"(?:^|[^0-9a-z]){re.escape(marker)}(?:$|[^0-9a-z])", db_name)
        for marker in _SCRATCH_DB_MARKERS
    )


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
    # Filter noise — keep lines that look like revision ids
    rev_lines = [ln for ln in lines if "head" in ln.lower()]
    assert len(rev_lines) == 1, f"expected 1 alembic head, got: {lines}"


@pytest.mark.skipif(
    (os.getenv("RUN_ALEMBIC_ROUNDTRIP") or "").strip().lower()
    not in {"1", "true", "yes"},
    reason="set RUN_ALEMBIC_ROUNDTRIP=1 to exercise upgrade/downgrade on DB",
)
def test_alembic_upgrade_downgrade_roundtrip() -> None:
    """upgrade head then downgrade -1 against a dedicated scratch database.

    Deliberately does NOT inherit DATABASE_URL: this replays a destructive
    downgrade, and a developer with RUN_ALEMBIC_ROUNDTRIP=1 exported in their
    shell would otherwise point it at whatever their app database happens to be.
    TEST_DATABASE_URL must be set and must name a scratch database.
    """
    scratch = (os.getenv("TEST_DATABASE_URL") or "").strip()
    if not scratch:
        pytest.skip("set TEST_DATABASE_URL to a scratch database to run the roundtrip")
    db_name = urlsplit(scratch).path.lstrip("/").lower()
    if not _looks_like_scratch_db(db_name):
        pytest.fail(
            f"TEST_DATABASE_URL database {db_name!r} is not a recognised scratch "
            f"database (name must contain one of {sorted(_SCRATCH_DB_MARKERS)} as a "
            "delimiter-bounded word, e.g. collections_test); "
            "refusing to run a destructive downgrade against it"
        )

    env = {**os.environ, "ALEMBIC_SEED_DEMO": "", "DATABASE_URL": scratch}

    def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr + up.stdout

    down = _alembic("downgrade", "-1")
    try:
        assert down.returncode == 0, down.stderr + down.stdout
    finally:
        # Restore head even when the downgrade failed — leaving the scratch DB
        # one revision behind breaks every later test in the session.
        restore = _alembic("upgrade", "head")
        assert restore.returncode == 0, restore.stderr + restore.stdout


def test_every_mirrored_sql_file_has_exactly_one_migration() -> None:
    """The chain cannot be replayed from any recorded base -- the initial
    commit's ``sql/`` already carried what migration 0003 adds -- so drift is
    caught by the mirror convention instead: from ``sql/24_*`` on, a migration
    reads its DDL from the sql file it names. A deleted migration leaves its
    mirror unreferenced; a deleted mirror leaves a migration dangling; both
    fail here.
    """
    import re
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    refs: dict[str, list[str]] = {}
    for path in sorted((backend / "alembic" / "versions").glob("*.py")):
        for name in re.findall(r'"sql"\s*/\s*"([^"]+\.sql)"', path.read_text(encoding="utf-8")):
            refs.setdefault(name, []).append(path.name)
    mirrored = sorted(
        p.name for p in (backend / "sql").glob("*.sql") if 24 <= int(p.name.split("_")[0]) < 90
    )
    assert mirrored, "no mirrored sql files found"
    unreferenced = [m for m in mirrored if m not in refs]
    assert unreferenced == [], f"sql mirrors with no migration: {unreferenced}"
    dangling = [n for n in refs if not (backend / "sql" / n).exists()]
    assert dangling == [], f"migrations naming a missing sql mirror: {dangling}"
    doubled = {n: v for n, v in refs.items() if len(v) > 1}
    assert doubled == {}, f"sql mirror read by more than one migration: {doubled}"
