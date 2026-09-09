"""Compare fresh SQL with Alembic-to-head on one explicitly disposable DB."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

BACKEND = Path(__file__).resolve().parents[1]
W6_TABLES = (
    "decision_cost_rollup_daily",
    "fct_consent",
    "fct_contact",
    "fct_installment",
    "fct_loan_state",
    "fct_mandate",
    "fct_payment",
    "fct_perception",
    "fct_presentation",
    "fct_protection",
    "fct_return",
    "feature_pit_skew_mismatches",
    "feature_pit_skew_runs",
    "feature_snapshot_builds",
    "feature_snapshot_daily",
    "feature_snapshot_daily_default",
    "treatment_sweep_claims",
    "treatment_sweep_runs",
)


def _scratch(url: str) -> bool:
    name = urlsplit(url.replace("postgresql+psycopg://", "postgresql://", 1)).path
    return re.search(r"(?:^|[-_])(scratch|test|ci)(?:$|[-_])", name.lstrip("/")) is not None


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _reset(conn) -> None:
    conn.execute("DROP SCHEMA IF EXISTS evaluation CASCADE")
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.commit()


def _snapshot(conn) -> tuple[set[tuple], set[tuple], set[tuple]]:
    tables = list(W6_TABLES)
    columns = {
        tuple(row)
        for row in conn.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = ANY(%s)
            """,
            (tables,),
        )
    }
    indexes = {
        tuple(row)
        for row in conn.execute(
            """
            SELECT tablename, indexdef
              FROM pg_indexes
             WHERE schemaname = 'public' AND tablename = ANY(%s)
            """,
            (tables,),
        )
    }
    constraints = {
        tuple(row)
        for row in conn.execute(
            """
            SELECT c.relname, pg_get_constraintdef(k.oid)
              FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
             WHERE c.relname = ANY(%s)
            """,
            (tables,),
        )
    }
    return columns, indexes, constraints


def main() -> int:
    url = (os.getenv("W6_SCHEMA_SCRATCH_DATABASE_URL") or "").strip()
    if not url:
        print("W6 schema parity: not measured (set W6_SCHEMA_SCRATCH_DATABASE_URL)")
        return 2
    if not _scratch(url):
        print("W6 schema parity: refused non-scratch database name")
        return 2
    import psycopg

    dsn = _dsn(url)
    with psycopg.connect(dsn) as conn:
        _reset(conn)
        for path in sorted((BACKEND / "sql").glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()
        fresh = _snapshot(conn)
        _reset(conn)

    env = {
        **os.environ,
        "DATABASE_URL": url,
        "ALEMBIC_SEED_DEMO": "",
    }
    upgraded = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if upgraded.returncode:
        print("W6 schema parity: Alembic upgrade failed")
        print(upgraded.stderr)
        return 1
    with psycopg.connect(dsn) as conn:
        migrated = _snapshot(conn)
    labels = ("columns", "indexes", "constraints")
    differences = [
        label for label, left, right in zip(labels, fresh, migrated) if left != right
    ]
    if differences:
        print("W6 schema parity: FAILED " + ", ".join(differences))
        return 1
    print("W6 schema parity: PASS fresh SQL == Alembic head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
