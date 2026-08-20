"""Tenant rooting of the configuration tables.

The tenancy survey walked the foreign-key graph and found 24 tables with no path
to a tenant at all. Ten are genuinely global; the rest held per-tenant business
configuration — a bank's product catalog, its QA rubric, its compliance rules —
with nothing to write a row-level-security policy against.

Migration 20260812_0060 roots the nine cluster *roots*, which turns the thirteen
remaining orphans into rooted-or-one-hop tables. These tests hold that shape in
place: the schema half (every root carries the column) and the behaviour half
(a second tenant's configuration is invisible).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

import db


#: Cluster roots. Their children (qa_rubric_sections/criteria,
#: product_eligibility_rules, product_relations) inherit via FK and deliberately
#: do NOT carry the column — see the migration docstring.
ROOTED_CONFIG_TABLES = [
    "compliance_rules",
    "qa_rubrics",
    "products",
    "document_templates",
    "persona_presets",
    "sandbox_scenarios",
    "kb_snapshots",
    "tts_voices",
    "voice_sandbox_sessions",
    # Rooted later, by 20260812_0062. These were not orphans by the survey's
    # rule — each had a foreign key to `users` — but the key was an
    # ON DELETE SET NULL audit column, which records who touched a row rather
    # than whose row it is. Deriving RLS policies from the same graph is what
    # exposed the difference: 20 of 21 kb_documents rows had a NULL editor and
    # so belonged to no tenant at all. See the migration for the full argument.
    "kb_documents",
    "prompt_versions",
    "export_jobs",
    "retrieval_logs",
]

#: Tables that legitimately have no tenant dimension. Asserting this is as
#: valuable as asserting the opposite: it records that each was considered and
#: found global, rather than missed.
GLOBAL_BY_DESIGN = [
    "tenants",
    "permissions",
    "event_types",
    "providers",
    "provider_fields",
    "billing_services",
    # The Azure voice catalog and its sync bookkeeping: a provider-side
    # inventory, identical for every tenant. `tts_voices` — the shortlist a
    # tenant actually configures — IS rooted, and that is the meaningful split.
    "tts_voice_catalog",
    "tts_voice_sync_runs",
    # Azure's published TTS pricing bands, same shape as billing_services. A
    # tenant with negotiated rates would need this rooted; none has one today,
    # and pretending otherwise would add a column nothing sets correctly.
    "tts_price_tiers",
    "alembic_version",
]


def _columns(conn, table: str) -> set[str]:
    return set(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                " WHERE table_schema = 'public' AND table_name = :t"
            ),
            {"t": table},
        ).scalars()
    )


# ---------------------------------------------------------------------------
# Schema shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", ROOTED_CONFIG_TABLES)
def test_config_table_is_rooted_in_a_tenant(db_tx, table: str) -> None:
    assert "tenant_id" in _columns(db_tx, table)


@pytest.mark.parametrize("table", ROOTED_CONFIG_TABLES)
def test_tenant_column_is_not_nullable(db_tx, table: str) -> None:
    """A nullable tenant is a row no policy can classify."""
    nullable = db_tx.execute(
        text(
            "SELECT is_nullable FROM information_schema.columns "
            " WHERE table_schema='public' AND table_name=:t AND column_name='tenant_id'"
        ),
        {"t": table},
    ).scalar()
    assert nullable == "NO", f"{table}.tenant_id is nullable"


@pytest.mark.parametrize("table", ROOTED_CONFIG_TABLES)
def test_tenant_column_has_an_index(db_tx, table: str) -> None:
    """Every scoped read and every future RLS policy filters on this first."""
    indexed = db_tx.execute(
        text(
            """
            SELECT count(*) FROM pg_indexes
             WHERE schemaname = 'public' AND tablename = :t
               AND indexdef LIKE '%tenant_id%'
            """
        ),
        {"t": table},
    ).scalar()
    assert indexed >= 1, f"{table} has no index leading with tenant_id"


@pytest.mark.parametrize("table", GLOBAL_BY_DESIGN)
def test_global_table_stays_global(db_tx, table: str) -> None:
    assert "tenant_id" not in _columns(db_tx, table), (
        f"{table} gained a tenant column — either that is a mistake, or the "
        "classification in this test needs updating"
    )


def test_no_config_table_was_missed(db_tx) -> None:
    """The survey's headline claim, held in place.

    Every table must now be rooted, reachable from a rooted table by foreign
    key, or explicitly listed as global. A new orphan is a table nobody can
    write a tenancy policy for.
    """
    tables = set(
        db_tx.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                " WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        ).scalars()
    )
    rooted = set(
        db_tx.execute(
            text(
                "SELECT table_name FROM information_schema.columns "
                " WHERE table_schema='public' AND column_name='tenant_id'"
            )
        ).scalars()
    )
    fks = db_tx.execute(
        text(
            """
            SELECT tc.table_name AS src, ccu.table_name AS dst
              FROM information_schema.table_constraints tc
              JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
               AND ccu.table_schema = tc.table_schema
             WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
            """
        )
    ).all()

    edges: dict[str, set[str]] = {}
    for src, dst in fks:
        if src != dst:
            edges.setdefault(src, set()).add(dst)

    def reaches_tenant(start: str) -> bool:
        seen, stack = {start}, [start]
        while stack:
            for nxt in edges.get(stack.pop(), ()):
                if nxt in rooted:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    orphans = sorted(
        t
        for t in tables
        if t not in rooted and t not in GLOBAL_BY_DESIGN and not reaches_tenant(t)
    )
    assert not orphans, (
        "tables with no path to a tenant — add tenant_id, give them an FK to "
        f"something rooted, or list them in GLOBAL_BY_DESIGN: {orphans}"
    )


# ---------------------------------------------------------------------------
# Behaviour — a second tenant's configuration must be invisible
# ---------------------------------------------------------------------------


def _other_tenant(conn) -> str:
    conn.execute(
        text("INSERT INTO tenants (id, name) VALUES ('rival.bank', 'Rival Bank')")
    )
    return "rival.bank"


def test_product_catalog_is_tenant_scoped(db_tx) -> None:
    other = _other_tenant(db_tx)
    db_tx.execute(
        text(
            "INSERT INTO products (id, tenant_id, name, type, is_active) "
            "VALUES ('prod-rival', :t, 'Rival Gold Card', 'card', true)"
        ),
        {"t": other},
    )
    ids = {p["id"] for p in db.list_products()}
    assert "prod-rival" not in ids


def test_inactive_filter_does_not_widen_across_tenants(db_tx) -> None:
    """include_inactive used to make is_active the only predicate."""
    other = _other_tenant(db_tx)
    db_tx.execute(
        text(
            "INSERT INTO products (id, tenant_id, name, type, is_active) "
            "VALUES ('prod-rival-off', :t, 'Rival Retired', 'card', false)"
        ),
        {"t": other},
    )
    ids = {p["id"] for p in db.list_products(include_inactive=True)}
    assert "prod-rival-off" not in ids


def test_sandbox_scenarios_are_tenant_scoped(db_tx) -> None:
    other = _other_tenant(db_tx)
    db_tx.execute(
        text(
            "INSERT INTO sandbox_scenarios (id, tenant_id, name, sim_persona, turns) "
            "VALUES ('sc-rival', :t, 'Rival Scenario', "
            "        CAST(:p AS jsonb), CAST(:x AS jsonb))"
        ),
        {"t": other, "p": json.dumps({}), "x": json.dumps([])},
    )
    ids = {s["id"] for s in db.list_sandbox_scenarios()}
    assert "sc-rival" not in ids


def test_persona_presets_are_tenant_scoped(db_tx) -> None:
    other = _other_tenant(db_tx)
    db_tx.execute(
        text(
            "INSERT INTO persona_presets (id, tenant_id, name, config) "
            "VALUES ('persona-rival', :t, 'Rival Persona', CAST(:c AS jsonb))"
        ),
        {"t": other, "c": json.dumps({})},
    )
    ids = {p["id"] for p in db.list_persona_presets()}
    assert "persona-rival" not in ids


def test_seed_injects_tenant_id_for_every_rooted_config_table() -> None:
    """Demo seed must stamp tenant_id on every rooted config table.

    `upsert` only auto-fills tables in TENANT_SCOPED_SEED_TABLES. Missing an
    entry (prompt_versions, kb_documents, …) aborts seed_demo mid-transaction
    and leaves the UI talking to an empty live API.
    """
    from seed_postgres import TENANT_SCOPED_SEED_TABLES

    missing = sorted(set(ROOTED_CONFIG_TABLES) - TENANT_SCOPED_SEED_TABLES)
    assert missing == []


def test_tts_voices_are_tenant_scoped(db_tx) -> None:
    other = _other_tenant(db_tx)
    db_tx.execute(
        text(
            "INSERT INTO tts_voices (id, tenant_id, provider, name, config, enabled) "
            "VALUES ('voice-rival', :t, 'azure', 'Rival Voice', CAST(:c AS jsonb), true)"
        ),
        {"t": other, "c": json.dumps({"gender": "Female"})},
    )
    ids = {v["id"] for v in db.list_tts_voices()}
    assert "voice-rival" not in ids
