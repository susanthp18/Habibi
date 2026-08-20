"""Decision Intelligence P0 — the corpus generator's data model.

Revision ID: 20260820_0085
Revises: 20260819_0084
Create Date: 2026-08-20

Mirrors sql/02_customer_account.sql, sql/03_consent.sql, sql/05_collections.sql
and sql/13_triggers.sql. SQL is inlined so alembic does not depend on a sibling
Path read at upgrade time.

The treatment engine has decided four times in its life, all in shadow, all off
one trigger. What is missing is not the pipeline — that is built and tested —
but the **data-generating process** the pipeline was designed to feed:

* **Propensity.** A deterministic argmax assigns every action it took a
  probability of 1.0, which makes the log unusable for off-policy estimation:
  every importance weight is 1 and the estimate is just the logged average. One
  column, and it cannot be added retroactively — you can retrain a model on old
  data forever, but you can never go back and record what the odds were.

* **Policy version.** ``contact_policy`` hard-codes its calling window as two
  module constants with no effective date, so "why did you dial at 19:15 last
  March?" can only be answered "our current code says we wouldn't have", which
  is not an answer. Rules become rows with a validity window, and a rule change
  becomes a backfill rather than a fresh start.

* **Mandates.** In Indian retail lending the highest-yield early-bucket action
  is frequently not a contact at all — it is re-presenting the mandate against
  the borrower's salary credit. ``payment_events.reason`` has carried the four
  diagnostic return codes since the schema was written and nothing has ever
  branched on them, because there was nowhere to record a presentation.

``mandate_presentations.decision_id`` is the load-bearing column in that last
group: without it a re-presentment that cures cannot be credited to the decision
that caused it, and ``represent_mandate`` becomes an action the learning loop can
never evaluate — which would make it exactly the kind of unmeasurable
"intelligence" this whole engine exists to avoid.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "20260820_0085"
down_revision: Union[str, Sequence[str], None] = "20260819_0084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # treatment_decisions: propensity, policy version, how the pick was made
    # ------------------------------------------------------------------
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS propensity double precision"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS policy_version integer"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD COLUMN IF NOT EXISTS explore_kind TEXT"
    )

    # Strictly greater than zero. An action the logging policy assigned zero
    # probability is an action it could not have taken, and IPS divides by this
    # number — a stored zero is a division by zero in every downstream estimate.
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS ck_treatment_decisions_propensity"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT ck_treatment_decisions_propensity"
        " CHECK (propensity IS NULL OR (propensity > 0 AND propensity <= 1))"
    )

    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS ck_treatment_decisions_explore_kind"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT ck_treatment_decisions_explore_kind"
        " CHECK (explore_kind IS NULL OR explore_kind IN"
        " ('greedy','ranked','control_arm'))"
    )

    # 'simulated' joins the modes so a synthetic corpus can live in the real
    # table and be excluded everywhere by one predicate — the convention
    # scripts/simulate_offer_decisions.py already set for offer_decisions.
    op.execute(
        "ALTER TABLE treatment_decisions DROP CONSTRAINT IF EXISTS treatment_decisions_mode_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD CONSTRAINT treatment_decisions_mode_check"
        " CHECK (mode IN ('off','shadow','live','simulated'))"
    )

    # The action space stops being contact-or-silence. All three additions have
    # channel=None or a digital channel already in use, so none of them widens
    # what the contact-frequency cap governs.
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS treatment_decisions_chosen_action_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT treatment_decisions_chosen_action_check"
        " CHECK (chosen_action IS NULL OR chosen_action IN ("
        "'wait','sms','whatsapp','voice_bot','human_call','field_visit','legal_notice',"
        "'represent_mandate','emi_date_change'))"
    )

    # The sweep's "have we already decided this account today?" lookup.
    #
    # Deliberately NOT unique, though it started that way. A day's sweep is one
    # decision per account, but the case it opens is re-decided by the ladder
    # every time an attempt fails to resolve it — that is what makes it a
    # ladder rather than a single suggestion. A unique index here forbids the
    # second rung, and it fails as an IntegrityError inside whatever
    # transaction the engine was lent, so a borrower who ignored the first
    # WhatsApp goes silent for the rest of the day.
    #
    # Concurrency is handled where it belongs: the sweep claims the account row
    # with SELECT ... FOR UPDATE SKIP LOCKED, so only one worker can be
    # deciding a given account at a time, and it reads this index to see
    # whether the day's decision already exists.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_treatment_decisions_sweep"
        " ON treatment_decisions (customer_id, trigger_ref)"
        " WHERE trigger_kind = 'dpd_tick' AND trigger_ref IS NOT NULL"
    )

    # Off-policy evaluation reads the corpus by mode and arm; without this it is
    # a sequential scan over every decision ever made.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_treatment_decisions_ope"
        " ON treatment_decisions (mode, variant, created_at)"
        " WHERE propensity IS NOT NULL"
    )

    # ------------------------------------------------------------------
    # The sweep's claim predicate
    # ------------------------------------------------------------------
    # No index supported "active and delinquent" before this. The sweep walks
    # the book by id so it can resume from a cursor, so id is the ordering
    # column and the delinquency test is the partial predicate.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_accounts_delinquent"
        " ON accounts (id) WHERE status = 'active' AND dpd > 0"
    )

    # ------------------------------------------------------------------
    # Mandates
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mandates (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
          account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          rail TEXT NOT NULL CHECK (rail IN ('nach','enach','upi_autopay','ecs')),
          -- The Unique Mandate Reference Number. Null while registration is
          -- pending: the rail assigns it, we do not.
          umrn TEXT,
          status TEXT NOT NULL DEFAULT 'pending' CHECK (
            status IN ('pending','active','suspended','cancelled','expired')
          ),
          max_amount numeric(14,2),
          -- The presentment calendar, in one column. Everything else about
          -- when to present is derived from the salary credit rather than
          -- from a calendar rule, which is the entire point of the action.
          debit_day smallint CHECK (debit_day IS NULL OR debit_day BETWEEN 1 AND 31),
          first_collection_on date,
          final_collection_on date,
          bank_name TEXT,
          account_last4 TEXT,
          registered_at timestamptz,
          cancelled_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # Partial: a mandate awaiting registration has no UMRN, and two of those
    # are two different mandates rather than a collision.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mandates_umrn"
        " ON mandates (tenant_id, umrn) WHERE umrn IS NOT NULL"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_mandates_tenant_id ON mandates(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_mandates_customer_id ON mandates(customer_id)")
    # The engine's hot read: is there a presentable mandate on this account?
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mandates_account_active"
        " ON mandates (account_id) WHERE status = 'active'"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS mandate_presentations (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          mandate_id TEXT NOT NULL REFERENCES mandates(id) ON DELETE CASCADE,
          account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
          emi_installment_id TEXT REFERENCES emi_installments(id) ON DELETE SET NULL,
          amount numeric(14,2) NOT NULL,
          -- The cycle this settles, not the day we asked for it. Two
          -- presentations of the same cycle are a retry and count against the
          -- presentation limit; two of different cycles are ordinary
          -- collection and do not.
          presented_for date NOT NULL,
          attempt_no smallint NOT NULL DEFAULT 1,
          scheduled_at timestamptz,
          presented_at timestamptz,
          settled_at timestamptz,
          status TEXT NOT NULL DEFAULT 'scheduled' CHECK (
            status IN ('scheduled','submitted','success','returned','cancelled')
          ),
          -- Kept verbatim. The normalised reason below is a lossy projection
          -- and a chargeback is argued from the original code.
          return_code TEXT,
          return_reason TEXT CHECK (return_reason IS NULL OR return_reason IN (
            'insufficient_funds','account_closed','mandate_expired','technical','unknown'
          )),
          -- 'lms' means we recommended and the lender presented. The
          -- distinction decides whether a presentation with no outcome is our
          -- bug or theirs.
          executor TEXT NOT NULL DEFAULT 'rail' CHECK (executor IN ('rail','lms')),
          -- The attribution edge. Without it a re-presentment that cures
          -- cannot be credited to the decision that caused it.
          decision_id TEXT REFERENCES treatment_decisions(id) ON DELETE SET NULL,
          payment_event_id TEXT REFERENCES payment_events(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    # One row per attempt at a cycle. Makes a retried executor idempotent and
    # makes the presentation limit a countable thing rather than a guess.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mandate_presentations_attempt"
        " ON mandate_presentations (mandate_id, presented_for, attempt_no)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mandate_presentations_tenant_id"
        " ON mandate_presentations(tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mandate_presentations_account"
        " ON mandate_presentations (account_id, presented_for DESC)"
    )
    # The settlement poller's claim: submitted and not yet resolved.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mandate_presentations_open"
        " ON mandate_presentations (status, scheduled_at)"
        " WHERE status IN ('scheduled','submitted')"
    )
    # Attribution joins back the other way, from decision to what it produced.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_mandate_presentations_decision"
        " ON mandate_presentations (decision_id) WHERE decision_id IS NOT NULL"
    )

    # ------------------------------------------------------------------
    # Policy as versioned rows
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_rule_sets (
          id TEXT PRIMARY KEY,
          -- Null means statutory: it binds every tenant and no tenant may edit
          -- it. A client rule set may only ever be stricter.
          tenant_id TEXT REFERENCES tenants(id) ON DELETE CASCADE,
          scope TEXT NOT NULL CHECK (scope IN ('statutory','client','product')),
          product_id TEXT REFERENCES products(id) ON DELETE CASCADE,
          version INTEGER NOT NULL,
          -- What a regulator would call it. 'RBI/2026-27/230', not 'v7'.
          label TEXT NOT NULL,
          effective_from timestamptz NOT NULL,
          -- Null means in force. A rule set is never edited once effective; it
          -- is superseded, and the superseded row keeps answering "what was in
          -- force in March".
          effective_to timestamptz,
          notes TEXT,
          published_at timestamptz NOT NULL DEFAULT now(),
          published_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_policy_rule_sets_window CHECK (
            effective_to IS NULL OR effective_to > effective_from
          ),
          CONSTRAINT ck_policy_rule_sets_statutory CHECK (
            (scope = 'statutory') = (tenant_id IS NULL)
          ),
          CONSTRAINT ck_policy_rule_sets_product CHECK (
            (scope = 'product') = (product_id IS NOT NULL)
          )
        )
        """
    )
    # COALESCE because a null tenant is "everyone" and a null product is "all
    # products", and Postgres would otherwise treat two statutory v1 rows as
    # distinct.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_rule_sets_version"
        " ON policy_rule_sets"
        " (COALESCE(tenant_id,''), scope, COALESCE(product_id,''), version)"
    )
    # The resolver's only read: every set that could be in force at an instant.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_policy_rule_sets_effective"
        " ON policy_rule_sets (scope, effective_from DESC)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS policy_rules (
          id TEXT PRIMARY KEY,
          rule_set_id TEXT NOT NULL REFERENCES policy_rule_sets(id) ON DELETE CASCADE,
          kind TEXT NOT NULL CHECK (kind IN (
            'calling_window','daily_cap','weekly_cap','cooling_off','bucket_actions',
            'mandate_presentation_limit','mandate_return_action','field_prerequisites',
            'recording_retention','visit_intimation'
          )),
          -- Null means every channel. A calling window is per-channel; a daily
          -- cap is across all of them, and saying that with null rather than a
          -- sentinel keeps the resolver from having to know which is which.
          channel TEXT CHECK (channel IS NULL OR channel IN (
            'voice','whatsapp','sms','email','chat','field'
          )),
          params jsonb NOT NULL DEFAULT '{}'::jsonb,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_policy_rules_kind"
        " ON policy_rules (rule_set_id, kind, COALESCE(channel,''))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_policy_rules_set ON policy_rules (rule_set_id)"
    )

    # ------------------------------------------------------------------
    # updated_at triggers for the four new mutable tables
    # ------------------------------------------------------------------
    for table in (
        "mandates",
        "mandate_presentations",
        "policy_rule_sets",
        "policy_rules",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table}"
            " FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade() -> None:
    for table in (
        "policy_rules",
        "policy_rule_sets",
        "mandate_presentations",
        "mandates",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP TABLE IF EXISTS policy_rules")
    op.execute("DROP TABLE IF EXISTS policy_rule_sets")
    op.execute("DROP TABLE IF EXISTS mandate_presentations")
    op.execute("DROP TABLE IF EXISTS mandates")

    op.execute("DROP INDEX IF EXISTS idx_accounts_delinquent")
    op.execute("DROP INDEX IF EXISTS idx_treatment_decisions_ope")
    op.execute("DROP INDEX IF EXISTS idx_treatment_decisions_sweep")

    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS treatment_decisions_chosen_action_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " ADD CONSTRAINT treatment_decisions_chosen_action_check"
        " CHECK (chosen_action IS NULL OR chosen_action IN ("
        "'wait','sms','whatsapp','voice_bot','human_call','field_visit','legal_notice'))"
    )
    op.execute(
        "ALTER TABLE treatment_decisions DROP CONSTRAINT IF EXISTS treatment_decisions_mode_check"
    )
    op.execute(
        "ALTER TABLE treatment_decisions ADD CONSTRAINT treatment_decisions_mode_check"
        " CHECK (mode IN ('off','shadow','live'))"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS ck_treatment_decisions_explore_kind"
    )
    op.execute(
        "ALTER TABLE treatment_decisions"
        " DROP CONSTRAINT IF EXISTS ck_treatment_decisions_propensity"
    )
    op.execute("ALTER TABLE treatment_decisions DROP COLUMN IF EXISTS explore_kind")
    op.execute("ALTER TABLE treatment_decisions DROP COLUMN IF EXISTS policy_version")
    op.execute("ALTER TABLE treatment_decisions DROP COLUMN IF EXISTS propensity")
