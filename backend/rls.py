"""Row-level-security policies derived from the foreign-key graph.

Every tenant predicate in this codebase is written by hand in Python. That works
until one is forgotten, and a forgotten predicate is not a crash — it is one
tenant reading another's rows, returned with a 200. Row-level security moves the
last line of defence into Postgres, where a query that forgets its predicate
returns nothing instead of everything.

Three things make that safe to switch on, and all three are enforced here.

**The GUC can never be unset.** Policies compare ``tenant_id`` against
``current_setting('app.tenant_id')``. If that is unset the comparison is NULL,
NULL is not true, and *every* query in the application returns zero rows — a
total outage that looks like an empty database rather than an error. ``db``
therefore passes the tenant as a libpq *startup parameter*, so it is set before
the connection can execute anything and no ROLLBACK can revert it.

**The connecting role must not bypass RLS.** Superusers and roles with
BYPASSRLS ignore policies entirely, and the application currently connects as
one. Enabling RLS as that role changes nothing at all while looking like it
worked, which is worse than not enabling it — so :func:`enable` refuses, and
:func:`status` leads with it.

**Enabling is verified inside the transaction that does it.** DDL is
transactional in Postgres, so :func:`enable` counts rows, turns policies on,
counts again, and rolls the whole thing back if any table's visible row count
does not match what the tenant should be able to see. The failure mode this is
designed against — everything silently returning zero rows — cannot survive a
commit.

Policies are derived rather than hand-written. The FK graph already encodes
which tenant a row belongs to: 35 tables carry ``tenant_id`` and the rest reach
it through a parent. Writing 90 policies by hand would mean re-deriving that
graph by eye and re-doing it for every new table; deriving them means a new
table is covered the moment it has a foreign key, and
``tests/test_rls.py::test_every_tenant_reachable_table_has_a_policy`` fails when
one does not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import tenant_context

logger = logging.getLogger(__name__)

#: One policy name everywhere, so ``apply`` can replace its own work idempotently
#: without touching a policy some DBA added by hand.
POLICY_NAME = "tenant_isolation"

#: ``current_setting(..., true)`` — the ``true`` means "return NULL if unset"
#: rather than raising. Raising would be a louder failure, but it would also
#: make every query error during the window between connect and set; the startup
#: parameter closes that window, and :func:`enable` proves the value is present
#: before it commits.
_GUC_EXPR = f"current_setting('{tenant_context.GUC}', true)"


@dataclass(frozen=True)
class TablePolicy:
    """The policy one table gets, and why it gets that one."""

    table: str
    #: Hops from a table carrying ``tenant_id``. 0 = carries it itself.
    depth: int
    predicate: str
    #: The same shape with every tenant comparison replaced by TRUE, so a row
    #: failing it belongs to *no* tenant and would be invisible to everyone.
    #: :func:`orphan_rows` uses this to check the semantics of a derivation,
    #: which the enable-time count check cannot: that compares the policy
    #: against itself, and a wrong policy agrees with itself perfectly.
    orphan_predicate: str
    parents: tuple[str, ...]
    #: True when the tenant is reached only through nullable columns. Rows with
    #: all of them NULL belong to no tenant and are visible to none.
    weak: bool

    @property
    def kind(self) -> str:
        return "rooted" if self.depth == 0 else f"hop-{self.depth}"

    @property
    def parent(self) -> str | None:
        return self.parents[0] if self.parents else None


# ---------------------------------------------------------------------------
# Catalog introspection
# ---------------------------------------------------------------------------

_TABLES_SQL = """
SELECT c.relname
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind = 'r'
"""

_ROOTED_SQL = """
SELECT table_name FROM information_schema.columns
 WHERE table_schema = 'public' AND column_name = 'tenant_id'
"""

# Composite foreign keys are ordered by their position in the constraint so the
# local and referenced column lists line up pairwise.
_FK_SQL = """
SELECT
    con.conname                                       AS name,
    src.relname                                       AS src_table,
    dst.relname                                       AS dst_table,
    (SELECT array_agg(a.attname ORDER BY k.ord)
       FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
       JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum)
                                                      AS src_cols,
    (SELECT array_agg(a.attname ORDER BY k.ord)
       FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
       JOIN pg_attribute a ON a.attrelid = con.confrelid AND a.attnum = k.attnum)
                                                      AS dst_cols,
    (SELECT bool_and(a.attnotnull)
       FROM unnest(con.conkey) AS k(attnum)
       JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum)
                                                      AS src_not_null
  FROM pg_constraint con
  JOIN pg_class src ON src.oid = con.conrelid
  JOIN pg_class dst ON dst.oid = con.confrelid
  JOIN pg_namespace n ON n.oid = src.relnamespace
 WHERE con.contype = 'f' AND n.nspname = 'public'
"""


def _scalars(conn: Any, sql: str) -> list[str]:
    from sqlalchemy import text

    return [r[0] for r in conn.execute(text(sql))]


def _quote(identifier: str) -> str:
    """Double-quote an identifier, doubling any embedded quote."""
    return '"' + identifier.replace('"', '""') + '"'


def plan(conn: Any) -> list[TablePolicy]:
    """Derive one policy per tenant-reachable table, in dependency order.

    Outward from the tables that carry ``tenant_id``. A table's predicate is its
    parent's predicate, inlined into an ``EXISTS`` over the foreign key. Inlining
    rather than leaning on the parent's own policy keeps each predicate
    self-contained, so a table stays correctly scoped even if RLS is somehow
    enabled on it and not on its parent.

    Resolved in **two passes**, and the order matters more than it looks. A
    foreign key can mean two different things: ``dispute_evidence.dispute_id``
    says which dispute this evidence *belongs to*, while
    ``kb_documents.updated_by_user_id`` merely says who last touched it. Only
    the first is an ownership link, and only ownership determines tenancy.

    Nullability is the available proxy — an ownership link is NOT NULL because a
    row cannot exist without its owner, whereas attribution is nullable because
    nobody may have acted yet. So pass one resolves the graph using NOT NULL
    links alone, and pass two admits nullable ones only for tables pass one
    could not reach. A single-pass version picked ``users`` for
    ``dispute_evidence`` — the nullable ``uploaded_by_user_id`` — purely because
    ``users`` was rooted and ``disputes`` had not been resolved yet.
    """
    from sqlalchemy import text

    tables = set(_scalars(conn, _TABLES_SQL))
    rooted = set(_scalars(conn, _ROOTED_SQL)) & tables

    edges: dict[str, list[dict[str, Any]]] = {}
    for row in conn.execute(text(_FK_SQL)).mappings():
        if row["src_table"] == row["dst_table"]:
            continue  # self-reference carries no tenant information
        edges.setdefault(row["src_table"], []).append(dict(row))

    policies: dict[str, TablePolicy] = {}
    for table in sorted(rooted):
        policies[table] = TablePolicy(
            table=table,
            depth=0,
            predicate=f"{_quote(table)}.tenant_id = {_GUC_EXPR}",
            orphan_predicate="TRUE",
            parents=(),
            weak=False,
        )

    counter = _AliasCounter()
    _resolve(tables, edges, policies, counter, ownership_only=True)
    _resolve(tables, edges, policies, counter, ownership_only=False)

    return sorted(policies.values(), key=lambda p: (p.depth, p.table))


class _AliasCounter:
    """Monotonic subquery aliases, unique within one :func:`plan` call.

    Parent predicates are inlined verbatim and carry the aliases they were built
    with. Because this only ever counts up, an alias minted for a child can
    never collide with one already embedded in an ancestor's predicate — which a
    depth-derived name would, whenever a table OR-ed together parents sitting at
    different depths.
    """

    def __init__(self) -> None:
        self._n = 0

    def next(self) -> str:
        self._n += 1
        return f"_rls_{self._n}"


def _resolve(
    tables: set[str],
    edges: dict[str, list[dict[str, Any]]],
    policies: dict[str, TablePolicy],
    counter: _AliasCounter,
    *,
    ownership_only: bool,
) -> None:
    """Widen the resolved set until it stops growing."""
    while True:
        progressed = False
        for table in sorted(tables - set(policies)):
            usable = [fk for fk in edges.get(table, ()) if fk["dst_table"] in policies]
            if ownership_only:
                usable = [fk for fk in usable if fk["src_not_null"]]
            if not usable:
                continue
            policies[table] = _build_policy(table, usable, policies, counter)
            progressed = True
        if not progressed:
            return


def _build_policy(
    table: str,
    usable: list[dict[str, Any]],
    policies: dict[str, TablePolicy],
    counter: _AliasCounter,
) -> TablePolicy:
    """One ownership link if there is one, else every optional link OR-ed."""
    strong = [fk for fk in usable if fk["src_not_null"]]
    if strong:
        chosen = [min(strong, key=lambda fk: (policies[fk["dst_table"]].depth, fk["name"]))]
    else:
        # No owning link: the row belongs to whichever optional parent is set.
        # OR rather than pick-one, so a row reachable through *any* of its links
        # stays visible; a row with all of them NULL belongs to no tenant and is
        # reported by orphan_rows() instead of being quietly shown to everybody.
        chosen = sorted(usable, key=lambda fk: fk["name"])

    predicate = " OR ".join(
        _exists(table, fk, policies[fk["dst_table"]], counter, tenant_scoped=True)
        for fk in chosen
    )
    orphan_predicate = " OR ".join(
        _exists(table, fk, policies[fk["dst_table"]], counter, tenant_scoped=False)
        for fk in chosen
    )
    if len(chosen) > 1:
        predicate = f"({predicate})"
        orphan_predicate = f"({orphan_predicate})"

    return TablePolicy(
        table=table,
        depth=max(policies[fk["dst_table"]].depth for fk in chosen) + 1,
        predicate=predicate,
        orphan_predicate=orphan_predicate,
        parents=tuple(fk["dst_table"] for fk in chosen),
        weak=not strong,
    )


def _exists(
    table: str,
    fk: dict[str, Any],
    parent: TablePolicy,
    counter: _AliasCounter,
    *,
    tenant_scoped: bool,
) -> str:
    """``EXISTS (SELECT 1 FROM parent alias WHERE <join> AND <parent predicate>)``."""
    alias = counter.next()
    joins = " AND ".join(
        f"{alias}.{_quote(dst)} = {_quote(table)}.{_quote(src)}"
        for src, dst in zip(fk["src_cols"], fk["dst_cols"])
    )
    inner_source = parent.predicate if tenant_scoped else parent.orphan_predicate
    inner = inner_source.replace(f"{_quote(parent.table)}.", f"{alias}.")
    return f"EXISTS (SELECT 1 FROM {_quote(parent.table)} {alias} WHERE {joins} AND {inner})"


def orphan_rows(conn: Any, policies: list[TablePolicy] | None = None) -> dict[str, int]:
    """Rows that belong to no tenant, per table.

    These are the rows a policy would hide from everyone. Non-zero here is the
    signal that a derivation is following an attribution link rather than an
    ownership one: 20 of 21 ``kb_documents`` rows landed here when the only
    foreign key out of that table was ``updated_by_user_id``.
    """
    from sqlalchemy import text

    policies = policies if policies is not None else plan(conn)
    out: dict[str, int] = {}
    for policy in policies:
        if policy.depth == 0:
            continue  # a NOT NULL tenant_id with a foreign key cannot be orphaned
        count = conn.execute(
            text(
                f"SELECT count(*) FROM {_quote(policy.table)} "
                f"WHERE NOT ({policy.orphan_predicate})"
            )
        ).scalar()
        if count:
            out[policy.table] = int(count)
    return out


def unscoped_tables(conn: Any) -> list[str]:
    """Tables no policy covers — global by design, or a new orphan."""
    tables = set(_scalars(conn, _TABLES_SQL))
    covered = {p.table for p in plan(conn)}
    return sorted(tables - covered)


def weak_policies(conn_or_plan: Any) -> list[TablePolicy]:
    """Policies whose link to the tenant is nullable.

    Worth reviewing individually: each is a table where a row with no parent is
    visible to every tenant.
    """
    policies = conn_or_plan if isinstance(conn_or_plan, list) else plan(conn_or_plan)
    return [p for p in policies if p.weak]


# ---------------------------------------------------------------------------
# Role capability
# ---------------------------------------------------------------------------


def role_bypasses_rls(conn: Any, role: str | None = None) -> bool:
    """True when policies would be ignored for this role.

    The single most important check here. RLS is invisible when it is not
    working: no error, no warning, just the same rows as before.
    """
    from sqlalchemy import text

    row = conn.execute(
        text(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles "
            " WHERE rolname = COALESCE(:role, current_user)"
        ),
        {"role": role},
    ).scalar()
    return bool(row)


# ---------------------------------------------------------------------------
# Apply / enable / disable
# ---------------------------------------------------------------------------


def apply(conn: Any, policies: list[TablePolicy] | None = None) -> list[str]:
    """Create (or replace) the derived policies. Does **not** enable them.

    Creating a policy on a table without row security enabled is inert — the
    policy exists and is ignored. That is deliberately the whole "behind a flag"
    mechanism: the definitions ship and can be reviewed in ``pg_policies``,
    while :func:`enable` is the separate, verified switch.
    """
    from sqlalchemy import text

    policies = policies if policies is not None else plan(conn)
    executed: list[str] = []
    for policy in policies:
        table = _quote(policy.table)
        drop = f"DROP POLICY IF EXISTS {POLICY_NAME} ON {table}"
        create = (
            f"CREATE POLICY {POLICY_NAME} ON {table} "
            f"FOR ALL USING ({policy.predicate}) WITH CHECK ({policy.predicate})"
        )
        conn.execute(text(drop))
        conn.execute(text(create))
        executed.extend([drop, create])
    return executed


def drop(conn: Any) -> list[str]:
    """Remove every policy this module manages."""
    from sqlalchemy import text

    executed: list[str] = []
    rows = conn.execute(
        text(
            "SELECT tablename FROM pg_policies "
            " WHERE schemaname = 'public' AND policyname = :name ORDER BY tablename"
        ),
        {"name": POLICY_NAME},
    ).scalars()
    for table in list(rows):
        stmt = f"DROP POLICY IF EXISTS {POLICY_NAME} ON {_quote(table)}"
        conn.execute(text(stmt))
        executed.append(stmt)
    return executed


class EnableRefused(RuntimeError):
    """Enabling would not have done what it looks like it does."""


class EnableVerificationFailed(RuntimeError):
    """Row counts changed in a way that says the policies are wrong."""


def enable(
    conn: Any, *, verify_as: str | None = None, allow_bypassing_role: bool = False
) -> dict[str, Any]:
    """Turn on row security for every covered table, verifying as it goes.

    Must be called inside a transaction the caller can roll back — on
    verification failure this raises, and the caller's rollback is what undoes
    the ALTERs. Postgres makes that possible by keeping DDL transactional, so
    the state this is designed to prevent cannot reach a committed database.

    Verification: for each table, the number of rows visible *after* enabling
    must equal the number that belonged to this tenant *before*. A policy that
    is too strict shows up as a shortfall — the zero-rows outage, caught before
    commit — and one that is too loose shows up as a surplus.

    ``verify_as`` is the role to count as, and it matters more than it looks.
    Enabling requires ALTER TABLE, so this runs as the table owner, and the
    owner is usually exempt from RLS; counting as the owner would compare the
    policy against a connection the policy does not apply to and pass no matter
    what. ``SET LOCAL ROLE`` switches to the application's role for the count
    phase only, inside the same transaction, so the numbers come from a
    connection the policies genuinely constrain. The caller must be a member of
    that role (or a superuser) for the switch to be permitted.
    """
    from sqlalchemy import text

    checked_role = verify_as or conn.execute(text("SELECT current_user")).scalar()
    if role_bypasses_rls(conn, verify_as) and not allow_bypassing_role:
        raise EnableRefused(
            f"role {checked_role!r} is a superuser or has BYPASSRLS, so policies "
            "would be ignored for it. Enabling now would look like it worked and "
            "protect nothing. Point the application at a role without those "
            "attributes first (scripts/rls.py provision-role) and pass it as "
            "verify_as, or pass allow_bypassing_role=True if you are knowingly "
            "installing policies for some other role."
        )

    tenant = conn.execute(text(f"SELECT {_GUC_EXPR}")).scalar()
    if not tenant:
        raise EnableRefused(
            f"{tenant_context.GUC} is not set on this connection. Every policy "
            "would match zero rows. Check that db.engine passes it as a libpq "
            "startup parameter."
        )

    policies = plan(conn)
    orphans = orphan_rows(conn, policies)
    if orphans:
        raise EnableRefused(
            "these rows belong to no tenant under the derived policies, so "
            "enabling would hide them from every user rather than scope them:\n  "
            + "\n  ".join(f"{t}: {n} rows" for t, n in sorted(orphans.items()))
            + "\nThey usually mean a table reaches its tenant only through an "
            "optional column. Give it its own tenant_id."
        )

    expected = {p.table: _tenant_row_count(conn, p) for p in policies}

    for policy in policies:
        table = _quote(policy.table)
        conn.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        # Without FORCE, the table's *owner* bypasses its own policies — and the
        # application connects as the owner in most single-database deployments.
        conn.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))

    if verify_as:
        conn.execute(text(f"SET LOCAL ROLE {_quote(verify_as)}"))
    try:
        visible = {
            p.table: conn.execute(text(f"SELECT count(*) FROM {_quote(p.table)}")).scalar()
            for p in policies
        }
    finally:
        if verify_as:
            conn.execute(text("RESET ROLE"))

    mismatches = [
        f"{p.table}: {expected[p.table]} rows belong to {tenant!r} but "
        f"{visible[p.table]} are visible with the policy on ({p.kind})"
        for p in policies
        if visible[p.table] != expected[p.table]
    ]
    if mismatches:
        raise EnableVerificationFailed(
            "row-level security was NOT enabled — roll back this transaction. "
            f"Counted as {checked_role!r}, visible row counts disagree with "
            "tenant ownership:\n  " + "\n  ".join(mismatches)
        )

    return {
        "tenant": tenant,
        "verified_as": checked_role,
        "tables": len(policies),
        "verified_rows": sum(expected.values()),
    }


def _tenant_row_count(conn: Any, policy: TablePolicy) -> int:
    """Rows that *should* be visible, counted before policies take effect."""
    from sqlalchemy import text

    return int(
        conn.execute(
            text(f"SELECT count(*) FROM {_quote(policy.table)} WHERE {policy.predicate}")
        ).scalar()
        or 0
    )


def disable(conn: Any) -> list[str]:
    """Turn row security off everywhere, leaving the policies in place."""
    from sqlalchemy import text

    executed: list[str] = []
    rows = conn.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity "
            " ORDER BY c.relname"
        )
    ).scalars()
    for table in list(rows):
        stmt = f"ALTER TABLE {_quote(table)} DISABLE ROW LEVEL SECURITY"
        conn.execute(text(stmt))
        executed.append(stmt)
    return executed


def status(conn: Any) -> dict[str, Any]:
    """What is derived, what is installed, what is enforcing, and for whom."""
    from sqlalchemy import text

    policies = plan(conn)
    installed = set(
        conn.execute(
            text(
                "SELECT tablename FROM pg_policies "
                " WHERE schemaname = 'public' AND policyname = :name"
            ),
            {"name": POLICY_NAME},
        ).scalars()
    )
    enforcing = set(
        conn.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                " WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity"
            )
        ).scalars()
    )
    forced = set(
        conn.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                " WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity"
            )
        ).scalars()
    )
    role = conn.execute(text("SELECT current_user")).scalar()
    by_depth: dict[str, int] = {}
    for policy in policies:
        by_depth[policy.kind] = by_depth.get(policy.kind, 0) + 1

    return {
        "role": role,
        "role_bypasses_rls": role_bypasses_rls(conn),
        "tenant_guc": conn.execute(text(f"SELECT {_GUC_EXPR}")).scalar(),
        "derived": len(policies),
        "by_depth": by_depth,
        "installed": len(installed),
        "enforcing": len(enforcing),
        "forced": len(forced),
        "missing_policy": sorted({p.table for p in policies} - installed),
        "unscoped": unscoped_tables(conn),
        "weak": [p.table for p in policies if p.weak],
    }


# ---------------------------------------------------------------------------
# Application role
# ---------------------------------------------------------------------------


def provision_role(conn: Any, role: str, password: str) -> list[str]:
    """Create/refresh a login role that policies actually apply to.

    The application currently connects as the schema owner, which is a superuser
    here. RLS is meaningless for such a role. This creates an ordinary role with
    DML rights and no ownership, which is what the application should use once
    policies are enforcing.

    Does not alter ``DATABASE_URL`` — pointing the application at this role is a
    deployment change, and doing it implicitly from a helper would be a way to
    lose access to your own database.
    """
    from sqlalchemy import text

    ident = _quote(role)
    literal = "'" + password.replace("'", "''") + "'"
    role_literal = "'" + role.replace("'", "''") + "'"
    statements = [
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {role_literal}) "
        f"THEN CREATE ROLE {ident} LOGIN; END IF; END $$",
        f"ALTER ROLE {ident} WITH LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {literal}",
        f"GRANT USAGE ON SCHEMA public TO {ident}",
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ident}",
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ident}",
        # Tables created later must not silently fall outside the grant.
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ident}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {ident}",
    ]
    for stmt in statements:
        conn.execute(text(stmt))
    # Never echo the password back to a log or a terminal.
    return [s for s in statements if literal not in s]
