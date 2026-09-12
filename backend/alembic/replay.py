"""Make the chain replayable from the baseline schema.

``alembic/baseline/*.sql`` is the schema the first commit shipped; revision
0001 applies it on an empty database. That schema was authored *ahead* of
the chain -- columns, tables and indexes that migrations 0002 onward add
were already in it -- so a literal replay collides on the first
``add_column``. Rather than rewrite 137 migrations, the additive operations
are made idempotent here: an ``add_column`` on a column that exists, a
``create_table`` on a table that exists, a ``create_index`` on an index that
exists, or a named constraint that exists, is a no-op. Nothing else is
softened: a migration that alters a type or drops a column still runs as
written, and ``scripts/migrate_from_empty.py`` diffs the replayed schema
against the ``sql/`` build so a softened step that mattered shows up as a
difference.
"""

from __future__ import annotations

import re
from typing import Any

import sqlalchemy as sa
from alembic import op


def _inspector():
    return sa.inspect(op.get_bind())


def _has_table(name: str, schema: str | None) -> bool:
    return _inspector().has_table(name, schema=schema)


def _has_column(table: str, column: str, schema: str | None) -> bool:
    if not _has_table(table, schema):
        return False
    return any(c["name"] == column for c in _inspector().get_columns(table, schema=schema))


def _has_index(table: str, name: str, schema: str | None) -> bool:
    if not _has_table(table, schema):
        return False
    return any(i["name"] == name for i in _inspector().get_indexes(table, schema=schema))


def _has_constraint(table: str, name: str, schema: str | None) -> bool:
    if not _has_table(table, schema):
        return False
    insp = _inspector()
    names: set[str | None] = set()
    names |= {c["name"] for c in insp.get_unique_constraints(table, schema=schema)}
    names |= {c["name"] for c in insp.get_foreign_keys(table, schema=schema)}
    names |= {c["name"] for c in insp.get_check_constraints(table, schema=schema)}
    pk = insp.get_pk_constraint(table, schema=schema)
    names.add(pk.get("name") if pk else None)
    return name in names


_ADD_CONSTRAINT = re.compile(r"^\s*ALTER\s+TABLE\s+(?:ONLY\s+)?\"?(\w+)\"?\s+ADD\s+CONSTRAINT\s+\"?(\w+)\"?(?=\s|$)", re.I | re.S)
_ADD_COLUMN = re.compile(r"^\s*ALTER\s+TABLE\s+(?:ONLY\s+)?\"?(\w+)\"?\s+ADD\s+(?:COLUMN\s+)?(?!IF\s)\"?(\w+)\"?\s", re.I | re.S)
_CREATE_TABLE = re.compile(r"^\s*CREATE\s+TABLE\s+(?!IF\s)\"?(\w+)\"?\s*\(", re.I | re.S)
_CREATE_INDEX = re.compile(r"^\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?!IF\s)\"?(\w+)\"?\s+ON(?=\s)", re.I | re.S)
_CREATE_TYPE = re.compile(r"^\s*CREATE\s+TYPE\s+\"?(\w+)\"?\s+AS(?=\s)", re.I | re.S)


def _has_type(name: str) -> bool:
    row = op.get_bind().execute(sa.text("SELECT 1 FROM pg_type WHERE typname = :n"), {"n": name}).first()
    return row is not None


def _raw_ddl_already_applied(sql: str) -> bool:
    """Whether one raw additive DDL statement has nothing left to do."""
    body = sql.strip().rstrip(";").strip()
    if ";" in body:
        return False  # several statements: run as written
    m = _ADD_CONSTRAINT.match(body)
    if m:
        return _has_constraint(m.group(1), m.group(2), None)
    m = _ADD_COLUMN.match(body)
    if m:
        return _has_column(m.group(1), m.group(2), None)
    m = _CREATE_TABLE.match(body)
    if m:
        return _has_table(m.group(1), None)
    m = _CREATE_INDEX.match(body)
    if m:
        row = op.get_bind().execute(sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :n"), {"n": m.group(1)}).first()
        return row is not None
    m = _CREATE_TYPE.match(body)
    if m:
        return _has_type(m.group(1))
    return False


def apply_sql(path: Any, *, translate_pii: bool = True) -> None:
    """Apply one ``sql/*.sql`` file as the migration that mirrors it.

    The file is read as it is *today*, and `%` is literal (plpgsql format()).
    Before 0138 the customer base table was `customers`, and the files that
    now say `customers_pii` meant that table when this migration shipped;
    0138 itself, which renames it, passes ``translate_pii=False``.
    """
    from pathlib import Path

    sql = Path(path).read_text(encoding="utf-8").replace("%", "%%")
    if translate_pii and "customers_pii" in sql and not _has_table("customers_pii", None):
        sql = sql.replace("customers_pii", "customers")
    op.get_bind().exec_driver_sql(sql)


def install() -> None:
    """Wrap the additive ``op`` functions once per process."""
    if getattr(op, "_habibi_replay", False):
        return
    real_execute = op.execute
    real_add_column = op.add_column
    real_create_table = op.create_table
    real_create_index = op.create_index
    real_create_unique = op.create_unique_constraint
    real_create_fk = op.create_foreign_key
    real_create_check = op.create_check_constraint

    def add_column(table_name: str, column: Any, *, schema: str | None = None, **kw: Any):
        if _has_column(table_name, column.name, schema):
            return None
        return real_add_column(table_name, column, schema=schema, **kw)

    def create_table(table_name: str, *columns: Any, **kw: Any):
        if _has_table(table_name, kw.get("schema")):
            return None
        return real_create_table(table_name, *columns, **kw)

    def create_index(index_name: str | None, table_name: str, columns: Any, *, schema: str | None = None, **kw: Any):
        if index_name and _has_index(table_name, index_name, schema):
            return None
        return real_create_index(index_name, table_name, columns, schema=schema, **kw)

    def create_unique_constraint(constraint_name: str | None, table_name: str, columns: Any, *, schema: str | None = None, **kw: Any):
        if constraint_name and _has_constraint(table_name, constraint_name, schema):
            return None
        return real_create_unique(constraint_name, table_name, columns, schema=schema, **kw)

    def create_foreign_key(constraint_name: str | None, source_table: str, referent_table: str, local_cols: Any, remote_cols: Any, *, source_schema: str | None = None, **kw: Any):
        if constraint_name and _has_constraint(source_table, constraint_name, source_schema):
            return None
        return real_create_fk(constraint_name, source_table, referent_table, local_cols, remote_cols, source_schema=source_schema, **kw)

    def create_check_constraint(constraint_name: str | None, table_name: str, condition: Any, *, schema: str | None = None, **kw: Any):
        if constraint_name and _has_constraint(table_name, constraint_name, schema):
            return None
        return real_create_check(constraint_name, table_name, condition, schema=schema, **kw)

    def execute(sqltext: Any, *args: Any, **kw: Any):
        if isinstance(sqltext, str):
            if _raw_ddl_already_applied(sqltext):
                return None
            # Migrations that apply sql/*.sql read the file as it is today, and
            # since 0138 those files reference customers_pii -- the base table
            # `customers` became in 0138. Before that revision the same
            # reference means the table that existed then.
            if "customers_pii" in sqltext and not _has_table("customers_pii", None):
                sqltext = sqltext.replace("customers_pii", "customers")
        return real_execute(sqltext, *args, **kw)

    op.execute = execute  # type: ignore[assignment]
    op.add_column = add_column  # type: ignore[assignment]
    op.create_table = create_table  # type: ignore[assignment]
    op.create_index = create_index  # type: ignore[assignment]
    op.create_unique_constraint = create_unique_constraint  # type: ignore[assignment]
    op.create_foreign_key = create_foreign_key  # type: ignore[assignment]
    op.create_check_constraint = create_check_constraint  # type: ignore[assignment]
    op._habibi_replay = True  # type: ignore[attr-defined]
