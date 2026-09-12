"""Prove the migration chain from an empty database equals the sql/ build.

Two scratch databases on the same server:

* ``<name>_chain`` -- provision the application role, then ``alembic upgrade
  head`` from nothing (revision 0001 applies ``alembic/baseline/``, the rest
  replay with the additive steps idempotent -- ``alembic/replay.py``).
* ``<name>_sql``   -- provision the role, then ``sql/*.sql`` in order and
  ``alembic stamp head``, which is what CI and a fresh laptop do today.

Both are dumped schema-only, normalised (no OIDs, comments, ownership, or the
alembic bookkeeping) and diffed. An empty diff means the chain is the schema;
a non-empty one names the drift, and that is the failure. Data is not
compared: the chain seeds the default tenant and the catalogue rows the
schema files seed, and nothing else.

    python scripts/migrate_from_empty.py            # against MIGRATION_DATABASE_URL's server
    python scripts/migrate_from_empty.py --keep     # leave the scratch databases behind
    python scripts/migrate_from_empty.py --diff-only  # only dump and diff the kept databases

Needs the owner DSN (MIGRATION_DATABASE_URL), ``alembic`` and ``pg_dump`` on
PATH. On the dev stack the voice container has no pg_dump and the host has no
route to the database, so build in the container with ``--keep`` and diff on
the host with ``PG_DUMP="docker exec collections_db pg_dump"`` and
``PG_DUMP_HOST=localhost``. Exit 0 on parity, 1 on drift, 2 on a step that
failed.
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

BACKEND = Path(__file__).resolve().parents[1]
APP_ROLE = os.getenv("APP_DB_USER") or "collections_app"
APP_PASSWORD = os.getenv("APP_DB_PASSWORD") or "collections_app"


def _owner_url() -> str:
    url = (os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("MIGRATION_DATABASE_URL is required")
    return url


def _with_db(url: str, name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment))


def _libpq(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _sql(url: str, statement: str) -> None:
    import psycopg

    with psycopg.connect(_libpq(url), autocommit=True) as conn:
        conn.execute(statement)


def _run(cmd: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(cmd, cwd=BACKEND, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stdout[-4000:] + result.stderr[-4000:])
        raise SystemExit(2)


def _provision(url: str) -> None:
    sys.path.insert(0, str(BACKEND))
    import rls
    from sqlalchemy import create_engine

    engine = create_engine(url)
    with engine.begin() as conn:
        rls.provision_role(conn, APP_ROLE, APP_PASSWORD)
    engine.dispose()


def _build_chain(url: str, env: dict[str, str]) -> None:
    _sql(url, "CREATE EXTENSION IF NOT EXISTS vector")
    _provision(url)
    _run(["alembic", "upgrade", "head"], {**env, "MIGRATION_DATABASE_URL": url, "DATABASE_URL": url, "ALEMBIC_SEED_DEMO": ""})


def _build_sql(url: str, env: dict[str, str]) -> None:
    import psycopg

    sys.path.insert(0, str(BACKEND))
    import pii_key

    _sql(url, "CREATE EXTENSION IF NOT EXISTS vector")
    _provision(url)
    # The PII functions refuse to run without the key on the connection.
    with psycopg.connect(_libpq(url), options=pii_key.connect_option()) as conn:
        for path in sorted((BACKEND / "sql").glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.commit()
    _run(["alembic", "stamp", "head"], {**env, "MIGRATION_DATABASE_URL": url, "DATABASE_URL": url, "ALEMBIC_SEED_DEMO": ""})
    # A fresh install turns row-level security on after the schema
    # (`scripts/rls.py enable`); the chain does it in 0126. Same policies,
    # derived from the same foreign keys, so both dumps carry them.
    import rls
    import tenant_context
    from sqlalchemy import create_engine, text

    engine = create_engine(url, connect_args={"options": pii_key.connect_option()} if pii_key.connect_option() else {})
    with engine.begin() as conn:
        conn.execute(text(f"SET LOCAL {tenant_context.GUC} = '{tenant_context.validate(tenant_context.current_tenant())}'"))
        rls.apply(conn)
        rls.enable(conn, verify_as=APP_ROLE)
    engine.dispose()


_NOISE = (
    re.compile(r"^--.*$"),
    re.compile(r"^SET .*$"),
    re.compile(r"^SELECT pg_catalog\..*$"),
    re.compile(r"^\\restrict .*$|^\\unrestrict .*$"),
    re.compile(r"^(ALTER|CREATE) (TABLE|SEQUENCE|VIEW|FUNCTION|TYPE|INDEX|SCHEMA) .* OWNER TO .*$"),
    re.compile(r"^ALTER .* OWNER TO .*$"),
    re.compile(r"^COMMENT ON .*$"),
)


def _dump(url: str) -> list[str]:
    import shlex

    dsn = _libpq(url)
    if os.getenv("PG_DUMP_HOST"):
        parts = urlsplit(dsn)
        netloc = parts.netloc.rsplit("@", 1)
        hostport = netloc[-1].split(":", 1)
        netloc[-1] = os.environ["PG_DUMP_HOST"] + (":" + hostport[1] if len(hostport) > 1 else "")
        dsn = urlunsplit((parts.scheme, "@".join(netloc), parts.path, parts.query, parts.fragment))
    result = subprocess.run(
        [*shlex.split(os.getenv("PG_DUMP") or "pg_dump"), "--schema-only", "--no-owner", "--no-privileges", "--no-comments", dsn],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr[-4000:])
        raise SystemExit(2)
    out: list[str] = []
    skip_block = False
    for line in result.stdout.splitlines():
        if any(p.match(line) for p in _NOISE) or not line.strip():
            continue
        # alembic's own bookkeeping table is the one thing the two builds differ on by design
        if line.startswith("CREATE TABLE public.alembic_version"):
            skip_block = True
        if skip_block:
            if line.strip() == ");":
                skip_block = False
            continue
        if "alembic_version" in line:
            continue
        out.append(line.rstrip())
    return _sorted_columns(out)


def _sorted_columns(lines: list[str]) -> list[str]:
    """CREATE TABLE bodies with their column lines sorted.

    A column a migration adds sits last in the table; the schema file places
    it where it reads best. Column order is not schema, so it is not diffed.
    """
    out: list[str] = []
    block: list[str] | None = None
    for line in lines:
        if line.startswith("CREATE TABLE ") and line.rstrip().endswith("("):
            out.append(line)
            block = []
            continue
        if block is not None:
            if line.strip() == ");":
                out.extend(sorted(item.rstrip(",") for item in block))
                out.append(line)
                block = None
            else:
                block.append(line)
            continue
        out.append(line)
    return out


def main() -> int:
    keep = "--keep" in sys.argv
    diff_only = "--diff-only" in sys.argv
    owner = _owner_url()
    base = os.getenv("MIGRATE_FROM_EMPTY_DB") or "collections_migrate"
    admin = _with_db(owner, urlsplit(owner).path.lstrip("/") or "postgres")
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    names = {"chain": f"{base}_chain", "sql": f"{base}_sql"}
    if diff_only:
        chain = _dump(_with_db(owner, names["chain"]))
        fresh = _dump(_with_db(owner, names["sql"]))
    else:
        for name in names.values():
            _sql(admin, f'DROP DATABASE IF EXISTS "{name}"')
            _sql(admin, f'CREATE DATABASE "{name}"')
        try:
            _build_chain(_with_db(owner, names["chain"]), env)
            _build_sql(_with_db(owner, names["sql"]), env)
            if keep:
                print("built", ", ".join(names.values()))
                return 0
            chain = _dump(_with_db(owner, names["chain"]))
            fresh = _dump(_with_db(owner, names["sql"]))
        finally:
            if not keep:
                for name in names.values():
                    _sql(admin, f'DROP DATABASE IF EXISTS "{name}"')
    diff = list(difflib.unified_diff(fresh, chain, fromfile="sql/ build", tofile="alembic upgrade head", lineterm="", n=1))
    if diff:
        sys.stdout.write("\n".join(diff) + "\n")
        print(f"\nschema drift: the chain and the sql/ build differ ({sum(1 for d in diff if d[:1] in '+-' and d[:3] not in ('+++', '---'))} lines)")
        return 1
    print(f"migrate-from-empty: parity ({len(chain)} schema lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
