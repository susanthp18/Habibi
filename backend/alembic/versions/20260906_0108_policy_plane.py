"""W4 Layer P and DPDP rights: catalogue, bindings, consent, rights.

Revision ID: 20260906_0108
Revises: 20260906_0107
Create Date: 2026-09-06

Expand/contract only. Historical decision rows stay unbound. Seed rule sets
keep NULL maker/checker identities — those values are not invented.

NOT applied to the running database by this work package. Mirror:
sql/03_consent.sql, sql/05_collections.sql, sql/06_sales.sql,
sql/12_crosscutting.sql.

Measured on collections (2026-09-06, alembic 20260905_0106):
  policy_rule_sets=2, policy_rules=6, treatment_decisions=244,
  offer_decisions=16, authority_decisions=18, treatment_holds=1,
  contact_events=176, consent_records=19, channel_consents=76.
  Statutory ids PRS-STATUTORY-V1/V2; published_by_user_id is NULL on both.
  Windows abut at 2027-01-01 and do not overlap.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260906_0108"
down_revision: Union[str, None] = "20260906_0107"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = (
    "calling_window",
    "daily_cap",
    "weekly_cap",
    "cooling_off",
    "bucket_actions",
    "mandate_presentation_limit",
    "mandate_return_action",
    "field_prerequisites",
    "recording_retention",
    "visit_intimation",
    "suppression_state",
    "ratio_ceiling",
    "assignment_check",
    "channel_scrub",
    "non_discretionary_notice",
)


def _add_not_valid(table: str, name: str, expr: str) -> None:
    op.execute(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID"
    )


def _validate(table: str, name: str) -> None:
    op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def _replace_customer_fk(table: str) -> None:
    """Online-safe CASCADE → RESTRICT on the four evidence tables only."""
    op.execute(
        f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_customer_id_fkey"
    )
    op.execute(
        f"""
        ALTER TABLE {table}
          ADD CONSTRAINT {table}_customer_id_fkey
          FOREIGN KEY (customer_id) REFERENCES customers(id)
          ON DELETE RESTRICT
          NOT VALID
        """
    )
    _validate(table, f"{table}_customer_id_fkey")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_rule_kinds (
          kind TEXT PRIMARY KEY,
          params_schema TEXT NOT NULL,
          tighten TEXT NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    for kind in _KINDS:
        op.execute(
            f"""
            INSERT INTO policy_rule_kinds (kind, params_schema, tighten)
            VALUES ('{kind}', '{kind}.v1', 'strict_only')
            ON CONFLICT (kind) DO NOTHING
            """
        )

    # -- publication envelope ------------------------------------------------
    op.execute(
        "ALTER TABLE policy_rule_sets ADD COLUMN IF NOT EXISTS "
        "approved_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE policy_rule_sets ADD COLUMN IF NOT EXISTS "
        "publication_state TEXT"
    )
    op.execute(
        "ALTER TABLE policy_rule_sets ADD COLUMN IF NOT EXISTS "
        "changed_rules TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]"
    )
    op.execute(
        """
        UPDATE policy_rule_sets
        SET publication_state = 'published'
        WHERE publication_state IS NULL
        """
    )
    op.execute(
        """
        UPDATE policy_rule_sets s
        SET changed_rules = COALESCE((
          SELECT array_agg(DISTINCT r.kind ORDER BY r.kind)
          FROM policy_rules r WHERE r.rule_set_id = s.id
        ), ARRAY[]::TEXT[])
        WHERE changed_rules = ARRAY[]::TEXT[]
        """
    )
    op.execute(
        "ALTER TABLE policy_rule_sets ALTER COLUMN publication_state SET DEFAULT 'draft'"
    )
    op.execute(
        "ALTER TABLE policy_rule_sets ALTER COLUMN publication_state SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE policy_rule_sets DROP CONSTRAINT IF EXISTS "
        "ck_policy_rule_sets_publication_state"
    )
    _add_not_valid(
        "policy_rule_sets",
        "ck_policy_rule_sets_publication_state",
        "publication_state IN ('draft','pending_approval','published','rejected')",
    )
    _validate("policy_rule_sets", "ck_policy_rule_sets_publication_state")
    op.execute(
        "ALTER TABLE policy_rule_sets DROP CONSTRAINT IF EXISTS "
        "ck_policy_rule_sets_maker_checker"
    )
    # NULL identities are allowed so historical seed rows are not given a
    # fabricated approver. Application publication still requires both.
    _add_not_valid(
        "policy_rule_sets",
        "ck_policy_rule_sets_maker_checker",
        "published_by_user_id IS NULL OR approved_by_user_id IS NULL "
        "OR published_by_user_id <> approved_by_user_id",
    )
    _validate("policy_rule_sets", "ck_policy_rule_sets_maker_checker")

    # -- per-rule identity and effective range -------------------------------
    op.execute("ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS rule_id TEXT")
    op.execute(
        "ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS rule_version INTEGER"
    )
    op.execute("ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS citation TEXT")
    op.execute(
        "ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS params_schema TEXT"
    )
    op.execute(
        "ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS effective tstzrange"
    )
    op.execute("ALTER TABLE policy_rules ADD COLUMN IF NOT EXISTS scope_key TEXT")

    op.execute(
        """
        UPDATE policy_rules r
        SET rule_id = r.kind || ':' || COALESCE(r.channel, 'all'),
            rule_version = s.version,
            citation = s.label,
            params_schema = r.kind || '.v1',
            effective = tstzrange(s.effective_from, s.effective_to, '[)'),
            scope_key = CASE s.scope
              WHEN 'statutory' THEN 'statutory'
              WHEN 'client' THEN 'client:' || COALESCE(s.tenant_id, '')
              WHEN 'product' THEN 'product:' || COALESCE(s.tenant_id, '')
                || ':' || COALESCE(s.product_id, '')
              ELSE s.scope
            END
        FROM policy_rule_sets s
        WHERE r.rule_set_id = s.id
          AND (r.rule_id IS NULL OR r.effective IS NULL OR r.scope_key IS NULL)
        """
    )

    op.execute("ALTER TABLE policy_rules ALTER COLUMN rule_id SET NOT NULL")
    op.execute("ALTER TABLE policy_rules ALTER COLUMN rule_version SET NOT NULL")
    op.execute("ALTER TABLE policy_rules ALTER COLUMN citation SET NOT NULL")
    op.execute("ALTER TABLE policy_rules ALTER COLUMN params_schema SET NOT NULL")
    op.execute("ALTER TABLE policy_rules ALTER COLUMN effective SET NOT NULL")
    op.execute("ALTER TABLE policy_rules ALTER COLUMN scope_key SET NOT NULL")

    op.execute(
        "ALTER TABLE policy_rules DROP CONSTRAINT IF EXISTS policy_rules_kind_check"
    )
    op.execute(
        "ALTER TABLE policy_rules DROP CONSTRAINT IF EXISTS ck_policy_rules_kind"
    )
    op.execute(
        """
        ALTER TABLE policy_rules
          ADD CONSTRAINT policy_rules_kind_fkey
          FOREIGN KEY (kind) REFERENCES policy_rule_kinds(kind)
          NOT VALID
        """
    )
    _validate("policy_rules", "policy_rules_kind_fkey")

    op.execute(
        "ALTER TABLE policy_rules DROP CONSTRAINT IF EXISTS ck_policy_rules_citation"
    )
    _add_not_valid(
        "policy_rules",
        "ck_policy_rules_citation",
        "length(btrim(citation)) > 0",
    )
    _validate("policy_rules", "ck_policy_rules_citation")

    op.execute(
        "ALTER TABLE policy_rules DROP CONSTRAINT IF EXISTS "
        "excl_policy_rules_scope_rule_effective"
    )
    op.execute(
        """
        ALTER TABLE policy_rules
          ADD CONSTRAINT excl_policy_rules_scope_rule_effective
          EXCLUDE USING gist (
            scope_key WITH =,
            rule_id WITH =,
            effective WITH &&
          )
        """
    )

    # -- bindings on decision and contact logs -------------------------------
    for table in ("treatment_decisions", "offer_decisions", "contact_events"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
            "policy_binding jsonb"
        )
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
            "policy_binding_hash TEXT"
        )

    # -- consent overlay, endpoint ownership, window authorisations ----------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS consent_events (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
          endpoint TEXT,
          channel TEXT NOT NULL CHECK (channel IN (
            'voice','whatsapp','sms','email','chat','field','all'
          )),
          purpose TEXT NOT NULL CHECK (purpose IN (
            'servicing','promotional','all'
          )),
          verb TEXT NOT NULL CHECK (verb IN (
            'withdraw','restrict','expire','opt_out'
          )),
          source TEXT NOT NULL,
          evidence_ref TEXT,
          captured_at timestamptz NOT NULL DEFAULT now(),
          actor_kind TEXT NOT NULL CHECK (actor_kind IN (
            'human','bot','customer','system','regulator'
          )),
          actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_consent_events_customer "
        "ON consent_events (customer_id, captured_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS endpoint_ownership (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
          endpoint TEXT NOT NULL,
          channel TEXT NOT NULL CHECK (channel IN (
            'voice','whatsapp','sms','email','chat'
          )),
          slot TEXT NOT NULL CHECK (slot IN ('primary','alt','other')),
          state TEXT NOT NULL CHECK (state IN (
            'unverified','verified','revoked'
          )),
          source TEXT NOT NULL DEFAULT 'system',
          evidence_ref TEXT,
          verified_at timestamptz,
          revoked_at timestamptz,
          revoked_reason TEXT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_endpoint_ownership UNIQUE (tenant_id, endpoint, channel)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_endpoint_ownership_customer "
        "ON endpoint_ownership (customer_id, state)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS window_authorisations (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
          channel TEXT NOT NULL CHECK (channel IN (
            'voice','whatsapp','sms','email','chat','field'
          )),
          start_hour INTEGER NOT NULL,
          end_hour INTEGER NOT NULL,
          source TEXT NOT NULL,
          citation TEXT,
          expires_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_window_authorisations_hours CHECK (
            start_hour >= 0 AND start_hour < 24
            AND end_hour > start_hour AND end_hour <= 24
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_window_authorisations_customer "
        "ON window_authorisations (customer_id, channel)"
    )

    # -- suppression owner: evolve treatment_holds ---------------------------
    op.execute(
        "ALTER TABLE treatment_holds ADD COLUMN IF NOT EXISTS "
        "confirmation_state TEXT NOT NULL DEFAULT 'confirmed'"
    )
    op.execute(
        "ALTER TABLE treatment_holds ADD COLUMN IF NOT EXISTS "
        "writer TEXT NOT NULL DEFAULT 'manual'"
    )
    op.execute(
        "ALTER TABLE treatment_holds ADD COLUMN IF NOT EXISTS "
        "release_approver_user_id TEXT REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE treatment_holds DROP CONSTRAINT IF EXISTS "
        "treatment_holds_kind_check"
    )
    op.execute(
        "ALTER TABLE treatment_holds DROP CONSTRAINT IF EXISTS "
        "ck_treatment_holds_kind"
    )
    _add_not_valid(
        "treatment_holds",
        "ck_treatment_holds_kind",
        "kind IN ('hardship','dispute','complaint','bereavement','legal',"
        "'cease_and_desist','deceased')",
    )
    _validate("treatment_holds", "ck_treatment_holds_kind")
    op.execute(
        "ALTER TABLE treatment_holds DROP CONSTRAINT IF EXISTS "
        "ck_treatment_holds_confirmation"
    )
    _add_not_valid(
        "treatment_holds",
        "ck_treatment_holds_confirmation",
        "confirmation_state IN ('pending','confirmed')",
    )
    _validate("treatment_holds", "ck_treatment_holds_confirmation")
    op.execute(
        "ALTER TABLE treatment_holds DROP CONSTRAINT IF EXISTS "
        "treatment_holds_source_check"
    )
    op.execute(
        "ALTER TABLE treatment_holds DROP CONSTRAINT IF EXISTS "
        "ck_treatment_holds_source"
    )
    _add_not_valid(
        "treatment_holds",
        "ck_treatment_holds_source",
        "source IN ('manual','bot','system','regulator','feedback','consent_event')",
    )
    _validate("treatment_holds", "ck_treatment_holds_source")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS decision_feedback (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          decision_id TEXT NOT NULL,
          actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          actor_role TEXT,
          verdict TEXT NOT NULL CHECK (verdict IN (
            'wrong_number','stop_contact','deceased','other'
          )),
          reason_code TEXT,
          corrected_outcome TEXT,
          note_redacted TEXT,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_decision_feedback_decision "
        "ON decision_feedback (decision_id, created_at)"
    )

    # -- DPDP rights ---------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subject_requests (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
          kind TEXT NOT NULL CHECK (kind IN (
            'access','correction','erasure','grievance'
          )),
          state TEXT NOT NULL CHECK (state IN (
            'received','verified','in_progress','fulfilled','refused','escalated'
          )),
          received_at timestamptz NOT NULL DEFAULT now(),
          verified_at timestamptz,
          due_at timestamptz NOT NULL,
          fulfilled_at timestamptz,
          evidence_ref TEXT,
          owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          escalated_to_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          note TEXT,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_subject_requests_slo CHECK (
            due_at <= received_at + interval '90 days'
          )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_requests_due "
        "ON subject_requests (tenant_id, due_at) "
        "WHERE state NOT IN ('fulfilled','refused')"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS subject_request_events (
          id TEXT PRIMARY KEY,
          request_id TEXT NOT NULL REFERENCES subject_requests(id) ON DELETE CASCADE,
          state TEXT NOT NULL,
          actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          note TEXT,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_subject_request_events_request "
        "ON subject_request_events (request_id, created_at)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS erasure_events (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
          request_id TEXT NOT NULL REFERENCES subject_requests(id) ON DELETE RESTRICT,
          cancelled_plans INTEGER NOT NULL DEFAULT 0,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_incidents (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          severity TEXT NOT NULL CHECK (severity IN (
            'low','medium','high','critical'
          )),
          state TEXT NOT NULL CHECK (state IN (
            'open','contained','notified','closed'
          )),
          summary TEXT NOT NULL,
          evidence_ref TEXT,
          detected_at timestamptz NOT NULL DEFAULT now(),
          notified_at timestamptz,
          closed_at timestamptz,
          actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS security_incident_events (
          id TEXT PRIMARY KEY,
          incident_id TEXT NOT NULL REFERENCES security_incidents(id) ON DELETE CASCADE,
          state TEXT NOT NULL,
          actor_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          note TEXT,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_replay_results (
          id TEXT PRIMARY KEY,
          tenant_id TEXT,
          window_start timestamptz NOT NULL,
          window_end timestamptz NOT NULL,
          requested_digest TEXT NOT NULL,
          evaluator_digest TEXT NOT NULL,
          veto_stack_version TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN (
            'completed','refused','partial'
          )),
          refusal_reason TEXT,
          compared INTEGER NOT NULL DEFAULT 0,
          mismatched INTEGER NOT NULL DEFAULT 0,
          result jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_job_runs (
          id TEXT PRIMARY KEY,
          job_name TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          state TEXT NOT NULL CHECK (state IN (
            'started','completed','failed','skipped'
          )),
          result jsonb NOT NULL DEFAULT '{}'::jsonb,
          started_at timestamptz NOT NULL DEFAULT now(),
          finished_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_policy_job_runs_key UNIQUE (idempotency_key)
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_horizon_findings (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT,
          decision_id TEXT,
          rule_id TEXT NOT NULL,
          kind TEXT NOT NULL CHECK (kind IN (
            'cancel','reschedule','prerequisite_gap'
          )),
          owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          detail jsonb NOT NULL DEFAULT '{}'::jsonb,
          state TEXT NOT NULL DEFAULT 'open' CHECK (state IN (
            'open','done','dismissed'
          )),
          created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_policy_horizon_findings_open "
        "ON policy_horizon_findings (tenant_id, state, created_at)"
    )

    _replace_customer_fk("treatment_decisions")
    _replace_customer_fk("offer_decisions")
    _replace_customer_fk("authority_decisions")
    _replace_customer_fk("treatment_holds")

    # Catalog + stock grants. Admin's ROLE_DEFAULTS is ALL_PERMISSIONS, so a
    # new catalogue row without a grant leaves the grants table lagging.
    import authz
    from sqlalchemy import text

    conn = op.get_bind()
    for permission_id, module, action, description in authz.PERMISSION_CATALOG:
        conn.execute(
            text(
                "INSERT INTO permissions (id, module, action, description)"
                " VALUES (:id, :module, :action, :description)"
                " ON CONFLICT (id) DO UPDATE SET module = EXCLUDED.module,"
                " action = EXCLUDED.action, description = EXCLUDED.description"
            ),
            {
                "id": permission_id,
                "module": module,
                "action": action,
                "description": description,
            },
        )
    stock = {
        "role-agent": "agent",
        "role-supervisor": "supervisor",
        "role-admin": "admin",
        "role-qa": "qa_reviewer",
    }
    for role_id, role_key in stock.items():
        exists = conn.execute(
            text("SELECT 1 FROM roles WHERE id = :id"), {"id": role_id}
        ).fetchone()
        if not exists:
            continue
        for permission_id in sorted(authz.ROLE_DEFAULTS.get(role_key, ())):
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id)"
                    " VALUES (:role_id, :permission_id) ON CONFLICT DO NOTHING"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            )


def downgrade() -> None:
    # Forward-only. A downgrade would drop evidence.
    return
