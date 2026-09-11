"""Row-level-security policies derived from the foreign-key graph.

Two halves. The first runs everywhere and checks the *derivation*: that every
table reachable from a tenant gets a policy, that the policies are valid SQL,
and that the graph walk follows ownership rather than attribution. It applies
policies inside the rolled-back ``db_tx`` transaction, so it exercises the real
DDL against the real schema without leaving anything behind.

The second is opt-in and checks the thing that actually matters: that with
policies enforcing, a connection carrying one tenant's ``app.tenant_id`` cannot
see or write another tenant's rows. That needs a role which does not bypass RLS
and a database it is safe to enable FORCE ROW LEVEL SECURITY on, so it wants a
scratch database — set ``RLS_DATABASE_URL``. Enforcement walks every derived
policy table, not a two-table sample: a hop-2 policy that follows the wrong
parent would leave ``customers`` and ``accounts`` green.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import text

import rls

BACKEND = Path(__file__).resolve().parents[1]

#: The 10 tables with no tenant dimension. Kept in step with
#: ``test_tenant_scoping.GLOBAL_BY_DESIGN`` — the two lists are derived
#: independently (that one walks information_schema, this one comes out of the
#: policy planner), so agreement between them is a real cross-check.
GLOBAL_BY_DESIGN = {
    "alembic_version",
    "billing_services",
    # One counter, bumped on every engine_config write. engine_config
    # itself is tenant-scoped; the epoch it stamps is not.
    "config_epoch",
    "event_types",
    "permissions",
    "provider_fields",
    # The capability matrix, not a tenant's config: "Nova-3 supports
    # streaming" is a fact about the vendor's model. The tenant-scoped
    # halves are provider_configs (credentials) and
    # agent_provider_bindings (which model serves which slot), and both
    # carry tenant_id.
    "provider_models",
    "providers",
    "tenants",
    "tts_price_tiers",
    "tts_voice_catalog",
    "tts_voice_sync_runs",
    # The bank-boundary vocabularies: which contract codes exist and which
    # schema versions of them are active, the LMS's account status codes and
    # the payment rails' return codes with their normalised meanings, and the
    # kinds of policy rule a rule set may carry. Every one is a fact about a
    # standard, not about a tenant -- a tenant *binds* to a contract in
    # `bank_contract_bindings`, which is rooted.
    "bank_contract_versions",
    "bank_contracts",
    "lms_account_status",
    "policy_rule_kinds",
    "rail_return_codes",
    # A log of the policy sweeps this *process* ran, keyed by job name and
    # idempotency key. What each sweep touched is on the tenant-scoped rows it
    # wrote; the run itself belongs to the deployment.
    "policy_job_runs",
}

#: Tables that reach their tenant only through nullable columns. Every one is a
#: judgement call worth re-reading if this list changes: a row with all of those
#: columns NULL belongs to no tenant, and
#: :func:`test_no_table_has_rows_that_belong_to_no_tenant` is what keeps that
#: from silently hiding data.
KNOWN_WEAK = {
    "ai_response_suggestions",
    "bot_tool_calls",
    # faq_pairs left this set on 2026-09-11: it carries its own tenant_id
    # now (sql/36_tenant_columns.sql), filled from the linked document.
    "routing_rule_executions",
    "sandbox_runs",
}


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------


def _policy_for(conn, table: str) -> rls.TablePolicy:
    return next(p for p in rls.plan(conn) if p.table == table)


def test_every_tenant_reachable_table_has_a_policy(db_tx) -> None:
    uncovered = set(rls.unscoped_tables(db_tx))
    assert uncovered == GLOBAL_BY_DESIGN, (
        "a table is not covered by any tenancy policy. Either it is genuinely "
        "global (add it to GLOBAL_BY_DESIGN, here and in test_tenant_scoping), "
        "or it needs a tenant_id or a foreign key to something that has one. "
        f"Unexpected: {sorted(uncovered - GLOBAL_BY_DESIGN)}"
    )


def test_policy_sql_is_valid(db_tx) -> None:
    """Create all ~112 policies for real, inside a transaction that rolls back.

    Predicates are assembled by string surgery — inlining a parent's predicate
    under a fresh alias — so "it parses" is not something to take on faith.
    Postgres is the only authority worth asking.
    """
    from tests.conftest import require_owner

    require_owner(db_tx, "CREATE POLICY is DDL")
    executed = rls.apply(db_tx)
    assert executed, "no policies were created"

    installed = set(
        db_tx.execute(
            text(
                "SELECT tablename FROM pg_policies "
                " WHERE schemaname='public' AND policyname=:n"
            ),
            {"n": rls.POLICY_NAME},
        ).scalars()
    )
    assert installed == {p.table for p in rls.plan(db_tx)}


def test_rooted_tables_compare_the_column_directly(db_tx) -> None:
    rooted = [p for p in rls.plan(db_tx) if p.depth == 0]
    assert len(rooted) >= 39
    for policy in rooted:
        own = f'"{policy.table}".tenant_id ' f"= current_setting('app.tenant_id', true)"
        if policy.table in rls.GLOBAL_WHEN_NULL:
            assert policy.predicate == f'("{policy.table}".tenant_id IS NULL OR {own})'
            assert policy.check_predicate == own
        else:
            assert policy.predicate == own
        assert policy.parents == ()


def test_ownership_links_are_preferred_over_attribution_links(db_tx) -> None:
    """``dispute_evidence`` must scope through ``disputes``, not ``users``.

    It has both: ``dispute_id NOT NULL`` (what the evidence belongs to) and
    ``uploaded_by_user_id`` (who uploaded it, nullable, ON DELETE SET NULL). A
    single-pass graph walk picked ``users``, because ``users`` carries
    ``tenant_id`` and so was resolved first — which would have scoped evidence
    by its uploader's employer and orphaned it when that user was deleted.
    """
    policy = _policy_for(db_tx, "dispute_evidence")
    assert policy.parents == ("disputes",)
    assert not policy.weak


def test_no_table_has_rows_that_belong_to_no_tenant(db_tx) -> None:
    """The check that catches a policy following the wrong foreign key.

    Comparing a policy against itself always agrees; this asks a different
    question — whether any row fails the predicate for *every* tenant. When
    ``kb_documents`` was scoped through ``updated_by_user_id``, 20 of its 21
    rows landed here, along with 634 more in the KB cluster hanging off it.
    """
    orphans = rls.orphan_rows(db_tx)
    assert orphans == {}, (
        "these rows are reachable from no tenant, so enabling RLS would hide "
        f"them from everyone rather than scope them: {orphans}"
    )


def test_weakly_scoped_tables_are_the_known_set(db_tx) -> None:
    weak = {p.table for p in rls.plan(db_tx) if p.weak}
    assert weak == KNOWN_WEAK, (
        "the set of tables reaching a tenant only through nullable columns has "
        "changed. A new entry means a table whose rows can become unattributable"
        f" — review it rather than updating this list reflexively. Added: "
        f"{sorted(weak - KNOWN_WEAK)}; removed: {sorted(KNOWN_WEAK - weak)}"
    )


def test_plan_is_deterministic(db_tx) -> None:
    """Same schema, same policies — or `apply` churns the database every run."""
    first = rls.plan(db_tx)
    second = rls.plan(db_tx)
    assert [(p.table, p.predicate) for p in first] == [
        (p.table, p.predicate) for p in second
    ]


def test_subquery_aliases_never_collide(db_tx) -> None:
    """Nested predicates inline their parent's SQL verbatim.

    Naming an alias after the table's depth looked fine until a table OR-ed
    together parents at different depths, at which point the outer alias could
    repeat one already used inside an inlined predicate.
    """
    for policy in rls.plan(db_tx):
        # Declarations only (``FROM "parent" _rls_N``). An alias is referenced
        # several times per subquery, which is not a collision.
        declared = re.findall(r'FROM\s+"[^"]+"\s+(_rls_\d+)', policy.predicate)
        assert len(declared) == len(set(declared)), f"{policy.table}: {declared}"


def test_enable_refuses_when_the_role_bypasses_rls(db_tx) -> None:
    """The quiet failure this whole module exists to prevent.

    The application connects as the schema owner, which in this deployment is a
    superuser. Enabling RLS as that role changes nothing whatsoever, and nothing
    about it looks wrong afterwards.
    """
    if not rls.role_bypasses_rls(db_tx):
        pytest.skip("connected role does not bypass RLS")
    with pytest.raises(rls.EnableRefused, match="BYPASSRLS|superuser"):
        rls.enable(db_tx)


def test_provision_role_creates_a_login_that_cannot_bypass_rls(db_tx) -> None:
    """The role policies will actually constrain — without enabling them.

    ``provision_role`` is the half that is safe to run against any database:
    it creates a login with DML rights and ``NOBYPASSRLS``. Pointing
    ``DATABASE_URL`` at it, and ``enable``, are the maintenance-window half
    and are not exercised here. The transaction rolls the role back.
    """
    from tests.conftest import require_owner

    require_owner(db_tx, "CREATE ROLE needs CREATEROLE")
    name = "rls_app_rw_probe"
    rls.provision_role(db_tx, name, "not-echoed")
    assert rls.role_bypasses_rls(db_tx, name) is False
    row = db_tx.execute(
        text(
            "SELECT rolcanlogin, rolsuper, rolbypassrls "
            "  FROM pg_roles WHERE rolname = :n"
        ),
        {"n": name},
    ).one()
    assert row == (True, False, False)


# ---------------------------------------------------------------------------
# Enforcement — opt-in, needs a scratch database
# ---------------------------------------------------------------------------

_SCRATCH_MARKERS = ("rls", "test", "scratch", "ci")
_PROBE_ROLE = "rls_probe"
_PROBE_PW = "rls-probe-password"
_SCRATCH_REASON = "set RLS_DATABASE_URL to a scratch database to test RLS enforcement"

#: Seeded tables spanning rooted / hop-1 / hop-2, so a policy that only
#: happens to be right for ``customers`` cannot hide a wrong parent further
#: down the FK graph. Values are (acme.bank, rival.bank) row counts.
_SEEDED_COUNTS = {
    "products": (1, 1),  # rooted
    "customers": (3, 5),  # rooted
    "accounts": (3, 5),  # hop-1 through customers
    "customer_notes": (3, 5),  # hop-1 through customers
    "consent_records": (3, 5),  # hop-1, regulated
    "channel_consents": (3, 5),  # hop-2 through consent_records
    "ledger_entries": (3, 5),  # hop-2 through accounts
}


def _scratch_url() -> str:
    return (os.getenv("RLS_DATABASE_URL") or "").strip()


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@pytest.fixture(scope="module")
def enforcing_db():
    """A two-tenant database with policies installed and enforcing.

    Built from ``sql/*.sql`` rather than the dev database: this enables FORCE
    ROW LEVEL SECURITY, which must never be pointed at anything real.
    """
    import psycopg
    from sqlalchemy import create_engine

    url = _scratch_url()
    if not url:
        pytest.skip(_SCRATCH_REASON)
    url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    name = urlsplit(url).path.lstrip("/").lower()
    if not any(m in name for m in _SCRATCH_MARKERS):
        pytest.fail(
            f"RLS_DATABASE_URL database {name!r} is not a recognised scratch "
            f"database (name must contain one of {list(_SCRATCH_MARKERS)}); "
            "refusing to enable FORCE ROW LEVEL SECURITY on it"
        )

    with psycopg.connect(url) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        for path in sorted((BACKEND / "sql").glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO tenants (id, name) VALUES ('acme.bank','Acme'),('rival.bank','Rival')"
        )
        for tenant, count in (("acme.bank", 3), ("rival.bank", 5)):
            conn.execute(
                "INSERT INTO products (id, tenant_id, name, type, is_active) "
                "VALUES (%s,%s,'Card','card',true)",
                (f"{tenant}-prod", tenant),
            )
            for i in range(count):
                cust = f"{tenant}-cust-{i}"
                acct = f"{tenant}-acct-{i}"
                consent = f"{tenant}-consent-{i}"
                conn.execute(
                    "INSERT INTO customers (id, tenant_id, name, risk) "
                    "VALUES (%s,%s,%s,'low')",
                    (cust, tenant, f"Customer {i}"),
                )
                conn.execute(
                    "INSERT INTO accounts (id, customer_id, product_id, status) "
                    "VALUES (%s,%s,%s,'active')",
                    (acct, cust, f"{tenant}-prod"),
                )
                conn.execute(
                    "INSERT INTO customer_notes (id, customer_id, text) "
                    "VALUES (%s,%s,'note')",
                    (f"{tenant}-note-{i}", cust),
                )
                conn.execute(
                    "INSERT INTO consent_records (id, customer_id) VALUES (%s,%s)",
                    (consent, cust),
                )
                conn.execute(
                    "INSERT INTO channel_consents (id, consent_id, channel, status) "
                    "VALUES (%s,%s,'voice','opted_in')",
                    (f"{tenant}-chconsent-{i}", consent),
                )
                conn.execute(
                    "INSERT INTO ledger_entries "
                    "(id, account_id, type, amount, posted_at) "
                    "VALUES (%s,%s,'charge',100,now())",
                    (f"{tenant}-ledger-{i}", acct),
                )
        conn.commit()

    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.begin() as conn:
        rls.apply(conn)
        rls.provision_role(conn, _PROBE_ROLE, _PROBE_PW)
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL app.tenant_id = 'acme.bank'"))
        rls.enable(conn, verify_as=_PROBE_ROLE)

    split = urlsplit(url)
    probe = f"postgresql://{_PROBE_ROLE}:{_PROBE_PW}@{split.hostname}:{split.port or 5432}{split.path}"
    try:
        yield {"owner_url": url, "probe_url": probe, "engine": engine}
    finally:
        engine.dispose()


def _as_probe(enforcing_db, tenant: str):
    import psycopg

    return psycopg.connect(
        enforcing_db["probe_url"], options=f"-c app.tenant_id={tenant}"
    )


def _owned_counts(conn, policies, tenant: str) -> dict[str, int]:
    conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
    return {
        p.table: int(
            conn.execute(
                text(
                    f"SELECT count(*) FROM {_ident(p.table)} WHERE {p.predicate}"
                )
            ).scalar()
            or 0
        )
        for p in policies
    }


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
def test_every_derived_policy_is_installed_enabled_and_forced(enforcing_db) -> None:
    with enforcing_db["engine"].connect() as conn:
        status = rls.status(conn)
    assert status["installed"] == status["derived"]
    assert status["enforcing"] == status["derived"]
    assert status["forced"] == status["derived"], (
        "ENABLE without FORCE leaves the table owner exempt, and the "
        "application connects as the owner"
    )


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
def test_the_probe_role_does_not_bypass_rls(enforcing_db) -> None:
    """``provision_role`` is what makes enable mean anything at all."""
    import psycopg

    with psycopg.connect(enforcing_db["probe_url"]) as conn:
        row = conn.execute(
            "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
    assert row == (False,)


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
@pytest.mark.parametrize(
    "tenant,index", [("acme.bank", 0), ("rival.bank", 1)]
)
def test_a_tenant_sees_only_its_own_rows(
    enforcing_db, tenant: str, index: int
) -> None:
    """No WHERE clause anywhere — the scoping is entirely the GUC."""
    with _as_probe(enforcing_db, tenant) as conn:
        for table, pair in _SEEDED_COUNTS.items():
            got = conn.execute(f"SELECT count(*) FROM {_ident(table)}").fetchone()[0]
            assert got == pair[index], (
                f"{table}: {got} visible to {tenant}, expected {pair[index]}"
            )


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
def test_every_covered_table_is_scoped_to_the_guc(enforcing_db) -> None:
    """Bare ``SELECT count(*)`` as the probe role, every derived policy table.

    A two-table sample stays green while a hop-2 policy follows the wrong
    parent. Walking the plan makes a new table a failure rather than a gap.
    Empty tables assert 0=0, which still proves the policy executes.
    """
    with enforcing_db["engine"].begin() as owner:
        policies = rls.plan(owner)
        expected = {
            tenant: _owned_counts(owner, policies, tenant)
            for tenant in ("acme.bank", "rival.bank")
        }

    mismatches: list[str] = []
    for tenant, counts in expected.items():
        with _as_probe(enforcing_db, tenant) as conn:
            for table, want in counts.items():
                got = conn.execute(f"SELECT count(*) FROM {_ident(table)}").fetchone()[0]
                if got != want:
                    mismatches.append(
                        f"{table} as {tenant}: {got} visible, {want} owned"
                    )
    assert mismatches == [], (
        "probe role saw a different row count than the tenant predicate "
        "on the owner connection:\n  " + "\n  ".join(mismatches)
    )


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
def test_a_write_into_another_tenant_is_rejected(enforcing_db) -> None:
    """``WITH CHECK`` — reading is not the only way to cross a tenant boundary."""
    import psycopg

    with _as_probe(enforcing_db, "acme.bank") as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO customers (id, tenant_id, name, risk) "
                "VALUES ('sneak','rival.bank','Sneak','low')"
            )
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(
                "INSERT INTO ledger_entries "
                "(id, account_id, type, amount, posted_at) "
                "VALUES ('sneak-ledger','rival.bank-acct-0','charge',1,now())"
            )


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
def test_an_unknown_tenant_sees_nothing(enforcing_db) -> None:
    with _as_probe(enforcing_db, "nobody.bank") as conn:
        for table in _SEEDED_COUNTS:
            got = conn.execute(f"SELECT count(*) FROM {_ident(table)}").fetchone()[0]
            assert got == 0, f"{table}: unknown tenant saw {got} rows"


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
def test_the_owner_still_bypasses_every_policy(enforcing_db) -> None:
    """Not a wart to fix here — the reason ``verify_as`` exists.

    FORCE makes the owner subject to policies, but a *superuser* is exempt from
    RLS unconditionally, and this deployment's owner is one. Verifying an enable
    from this connection would have proved nothing at all.
    """
    import psycopg

    with psycopg.connect(
        enforcing_db["owner_url"], options="-c app.tenant_id=acme.bank"
    ) as conn:
        assert conn.execute("SELECT count(*) FROM customers").fetchone()[0] == 8
        assert conn.execute("SELECT count(*) FROM ledger_entries").fetchone()[0] == 8


@pytest.mark.skipif(not _scratch_url(), reason=_SCRATCH_REASON)
def test_enable_rolls_back_when_a_policy_hides_rows(enforcing_db) -> None:
    """The safety net, exercised against a deliberately broken policy.

    A policy comparing against a tenant nobody owns makes every row invisible —
    the exact shape of the outage that makes RLS frightening to switch on. It
    must be caught by the count check and never reach a commit.
    """
    engine = enforcing_db["engine"]
    with engine.begin() as conn:
        rls.disable(conn)

    try:
        with pytest.raises(rls.EnableVerificationFailed, match="customers"):
            with engine.begin() as conn:
                conn.execute(text("SET LOCAL app.tenant_id = 'acme.bank'"))
                broken = [
                    rls.TablePolicy(
                        table=p.table,
                        depth=p.depth,
                        predicate="FALSE" if p.table == "customers" else p.predicate,
                        orphan_predicate=p.orphan_predicate,
                        parents=p.parents,
                        weak=p.weak,
                    )
                    for p in rls.plan(conn)
                ]
                rls.apply(conn, broken)
                rls.enable(conn, verify_as=_PROBE_ROLE)

        # The raise aborted the block, so nothing was committed: no table is
        # enforcing and the broken policy is gone with it.
        with engine.connect() as conn:
            assert rls.status(conn)["enforcing"] == 0
    finally:
        with engine.begin() as conn:
            rls.apply(conn)
        with engine.begin() as conn:
            conn.execute(text("SET LOCAL app.tenant_id = 'acme.bank'"))
            rls.enable(conn, verify_as=_PROBE_ROLE)


def test_global_when_null_tables_declare_what_null_means(db_tx) -> None:
    """A rooted table may keep NULL-tenant rows readable only when its schema
    says NULL is a meaning, not an omission -- a CHECK or a partial index that
    names it. Found on the dev stack: the two statutory rule sets and the
    platform budget vanished the moment policies were enforced, and the
    enable-time count could not see it because it compares the policy with
    itself."""
    for table in sorted(rls.GLOBAL_WHEN_NULL):
        nullable = db_tx.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t AND column_name = 'tenant_id'"
            ),
            {"t": table},
        ).scalar()
        assert nullable == "YES", f"{table}.tenant_id is NOT NULL; nothing is global there"
        declared = db_tx.execute(
            text(
                """
                SELECT count(*) FROM (
                  SELECT pg_get_constraintdef(c.oid) AS d
                    FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid
                   WHERE r.relname = :t AND c.contype = 'c'
                  UNION ALL
                  SELECT pg_get_indexdef(i.indexrelid)
                    FROM pg_index i JOIN pg_class r ON r.oid = i.indrelid
                   WHERE r.relname = :t
                ) defs
                WHERE d ILIKE '%tenant_id IS NULL%' OR d ILIKE '%COALESCE(tenant_id%'
                """
            ),
            {"t": table},
        ).scalar()
        assert declared, f"{table} tolerates a NULL tenant but nothing in its schema says what it means"

    for policy in rls.plan(db_tx):
        if policy.table in rls.GLOBAL_WHEN_NULL:
            assert "tenant_id IS NULL OR" in policy.predicate
            assert policy.check_predicate and "IS NULL" not in policy.check_predicate
        else:
            assert policy.check_predicate is None


def test_a_global_row_is_readable_and_not_writable_by_a_tenant(db_tx) -> None:
    """The two halves of GLOBAL_WHEN_NULL, on the live policy."""
    live = db_tx.execute(
        text(
            "SELECT qual, with_check FROM pg_policies "
            "WHERE schemaname = 'public' AND tablename = 'policy_rule_sets' AND policyname = :p"
        ),
        {"p": rls.POLICY_NAME},
    ).mappings().first()
    if live is None:
        pytest.skip("policies are not installed on this database")
    # Readable: the installed USING clause admits the NULL-tenant row.
    assert "IS NULL" in (live["qual"] or "")
    # Not writable: the installed WITH CHECK clause does not.
    assert "IS NULL" not in (live["with_check"] or "")
    if db_tx.execute(text("SELECT current_user")).scalar() == "collections":
        pytest.skip("the write-side refusal applies to the application role, not the owner")
    with pytest.raises(Exception) as excinfo:
        with db_tx.begin_nested():
            db_tx.execute(
                text(
                    """
                    INSERT INTO policy_rule_sets (id, tenant_id, scope, version, label, effective_from)
                    VALUES ('PRS-global-probe', NULL, 'statutory', 999, 'probe', now())
                    """
                )
            )
    assert "row-level security" in str(excinfo.value)
