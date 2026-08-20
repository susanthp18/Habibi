"""``sql/*.sql`` and the migrated database must describe the same schema.

This repository keeps two sources of schema truth: ``sql/*.sql`` is the
authoritative current shape (CI applies it and then *stamps* Alembic), while
``alembic/versions/`` carries deltas for databases that already exist. Nothing
checked that the two agreed, and they have drifted — in both directions:

* ``prompt_versions.tuning`` exists in the migrated database (added by revision
  ``20260723_0029``) and is absent from ``sql/``, so a fresh install does not
  get a column the code writes to;
* ``calibration_sessions.name``, ``calibration_sessions.target_scores`` and
  ``coaching_actions.category`` are declared in ``sql/`` and created by no
  migration, so an *existing* deployment never gets them.

The second kind is the dangerous one: it cannot be found by running the app
against a fresh database, which is exactly what a developer does.

Opt-in, following the convention of ``test_migrations.py``: set
``SCHEMA_PARITY_DATABASE_URL`` to a scratch database. The test drops and
rebuilds that database's public schema, so it refuses to run against anything
whose name does not say it is disposable.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

BACKEND = Path(__file__).resolve().parents[1]

_SCRATCH_DB_MARKERS = frozenset({"test", "scratch", "ci", "parity"})


def _looks_like_scratch_db(db_name: str) -> bool:
    """Whole-word match — a bare substring test accepts ``contest``."""
    return any(
        re.search(rf"(?:^|[^0-9a-z]){re.escape(marker)}(?:$|[^0-9a-z])", db_name)
        for marker in _SCRATCH_DB_MARKERS
    )


_COLUMNS_SQL = """
SELECT table_name, column_name, is_nullable, data_type
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name <> 'alembic_version'
 ORDER BY table_name, column_name
"""

# Indexes and constraints are compared by *definition*, not by name.
#
# Both sources describe the same rules under different names as a matter of
# course: an inline ``REFERENCES`` in sql/ auto-names the key
# ``<table>_<column>_fkey``, while ``op.create_foreign_key`` gives it an
# explicit ``fk_<table>_<parent>``. 26 constraints differ that way and every one
# of them is the same constraint. Comparing names would drown three real
# findings in twenty-six false ones; renaming them all in sql/ would be churn
# with real risk and no behavioural gain.
#
# What this does not catch, therefore, is a migration that drops a constraint by
# a name a fresh database does not use. That is a narrower hazard than a
# constraint which simply is not there, and it fails loudly when it happens.
_INDEXES_SQL = """
SELECT t.relname, substring(pg_get_indexdef(i.oid) from ' ON .*$')
  FROM pg_index ix
  JOIN pg_class i ON i.oid = ix.indexrelid
  JOIN pg_class t ON t.oid = ix.indrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
 WHERE n.nspname = 'public' AND t.relname <> 'alembic_version'
"""

_CONSTRAINTS_SQL = """
SELECT t.relname, c.contype, pg_get_constraintdef(c.oid)
  FROM pg_constraint c
  JOIN pg_class t ON t.oid = c.conrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
 WHERE n.nspname = 'public' AND t.relname <> 'alembic_version'
"""


def _snapshot(dsn: str) -> dict[tuple[str, str], tuple[str, str]]:
    import psycopg

    with psycopg.connect(dsn) as conn:
        return {(r[0], r[1]): (r[2], r[3]) for r in conn.execute(_COLUMNS_SQL)}


def _rows(dsn: str, sql: str) -> set[tuple]:
    import psycopg

    with psycopg.connect(dsn) as conn:
        return {tuple(r) for r in conn.execute(sql)}


def _pg_dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


requires_scratch_db = pytest.mark.skipif(
    not (os.getenv("SCHEMA_PARITY_DATABASE_URL") or "").strip(),
    reason="set SCHEMA_PARITY_DATABASE_URL to a scratch database to check schema parity",
)


@pytest.fixture(scope="module")
def dsns() -> dict[str, str]:
    """Rebuild the scratch database from ``sql/*.sql`` alone, once."""
    import psycopg

    scratch = _pg_dsn((os.getenv("SCHEMA_PARITY_DATABASE_URL") or "").strip())
    db_name = urlsplit(scratch).path.lstrip("/").lower()
    if not _looks_like_scratch_db(db_name):
        pytest.fail(
            f"SCHEMA_PARITY_DATABASE_URL database {db_name!r} is not a recognised "
            f"scratch database (name must contain one of "
            f"{sorted(_SCRATCH_DB_MARKERS)} as a delimiter-bounded word); "
            "refusing to drop its public schema"
        )

    with psycopg.connect(scratch) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for path in sorted((BACKEND / "sql").glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()

    import db as db_module

    return {"fresh": scratch, "migrated": _pg_dsn(db_module.DATABASE_URL)}


def _compare(fresh: set, migrated: set, noun: str) -> None:
    """Both directions, each with the consequence spelled out."""
    problems: list[str] = []
    only_migrated = sorted(migrated - fresh)
    only_fresh = sorted(fresh - migrated)
    if only_migrated:
        problems.append(
            f"{noun} in the migrated database but NOT in sql/ — a fresh install "
            f"will be missing these: {only_migrated}"
        )
    if only_fresh:
        problems.append(
            f"{noun} declared in sql/ but created by no migration — an EXISTING "
            f"deployment will never get these: {only_fresh}"
        )
    assert not problems, "sql/*.sql has drifted from the migration chain:\n  " + (
        "\n  ".join(problems)
    )


@requires_scratch_db
def test_indexes_match(dsns) -> None:
    """Missed by the column comparison: 0062 created two ``tenant_id`` indexes
    in the migration and only two of the four in ``sql/``."""
    _compare(
        _rows(dsns["fresh"], _INDEXES_SQL),
        _rows(dsns["migrated"], _INDEXES_SQL),
        "indexes",
    )


@requires_scratch_db
def test_constraints_match(dsns) -> None:
    """Checks, uniques and foreign keys, compared by definition.

    Found two status CHECKs that existed only in fresh databases — exactly the
    asymmetry a developer cannot see, because a developer runs against a fresh
    database.
    """
    _compare(
        _rows(dsns["fresh"], _CONSTRAINTS_SQL),
        _rows(dsns["migrated"], _CONSTRAINTS_SQL),
        "constraints",
    )


@requires_scratch_db
def test_sql_schema_matches_the_migrated_database(dsns) -> None:
    fresh = _snapshot(dsns["fresh"])
    migrated = _snapshot(dsns["migrated"])

    only_migrated = sorted(set(migrated) - set(fresh))
    only_fresh = sorted(set(fresh) - set(migrated))
    differing = sorted(
        k for k in set(migrated) & set(fresh) if migrated[k] != fresh[k]
    )

    problems: list[str] = []
    if only_migrated:
        problems.append(
            "in the migrated database but NOT in sql/ — a fresh install will be "
            f"missing these: {only_migrated}"
        )
    if only_fresh:
        problems.append(
            "declared in sql/ but created by no migration — an EXISTING "
            f"deployment will never get these: {only_fresh}"
        )
    if differing:
        problems.append(f"same column, different type or nullability: {differing}")

    assert not problems, "sql/*.sql has drifted from the migration chain:\n  " + "\n  ".join(
        problems
    )
