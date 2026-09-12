-- W8a · configuration is data.
--
-- §13.2 of docs/design/engines-production-design.md. Until this table exists,
-- `logging_contract.config_version()` returns a sha over four environment
-- variables -- a string that names nothing, so "what was the cost book when
-- this decision was made?" has no answer a week later. W2 shipped that
-- placeholder deliberately and said so in its own docstring; this is the row
-- it was waiting for.
--
-- WHAT LIVES HERE IS A COMPLIANCE QUESTION, NOT A TIDINESS QUESTION.
-- `engine_config` keeps only genuinely economic knobs: unit costs, batch
-- sizes, shard counts, poll intervals, the arm split, the engine mode. The
-- contact caps, LADDER.BUCKET_ACTIONS, LADDER.MAX_RUNG_ADVANCE,
-- FIELD.MIN_EXPOSURE and VALUE.FLOOR are NOT here -- they are `policy_rules`
-- rows with citations, because the cap is the harassment control and
-- VALUE.FLOOR decides whether a borrower is serviced at all. Asked *why did
-- you escalate this borrower to a field visit*, the answer must be a cited
-- rule, not a config version.

CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS engine_config (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  -- '' is the tenant-wide layer. A non-empty portfolio overrides it, which is
  -- what "per-portfolio mode" in §15.2 W8 amounts to.
  portfolio_id TEXT NOT NULL DEFAULT '',
  key TEXT NOT NULL,
  value_json JSONB NOT NULL,

  -- Bitemporal in the only sense that earns its keep here: a key has one
  -- value in one scope at one instant, enforced by the database rather than
  -- by whoever writes the UPDATE.
  effective tstzrange NOT NULL DEFAULT tstzrange(now(), NULL),
  effective_from timestamptz GENERATED ALWAYS AS (lower(effective)) STORED,
  effective_to timestamptz GENERATED ALWAYS AS (upper(effective)) STORED,

  -- The epoch this row was written at. `config_version` on a decision row is
  -- 'cfg:<version>', so resolving a historical decision's configuration is
  -- "every row whose effective range covers that epoch's bump".
  version BIGINT NOT NULL,

  changed_by TEXT NOT NULL,
  approved_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ck_engine_config_nonempty CHECK (NOT isempty(effective)),
  CONSTRAINT ck_engine_config_reason CHECK (length(btrim(reason)) > 0),
  -- §13.4: maker-checker is structural or it is discipline. A parameter change
  -- is same-day, and same-day is not same-person.
  CONSTRAINT ck_engine_config_maker_checker CHECK (changed_by <> approved_by),
  -- tenant_id leads, per §13.1's CI assertion: an index without it turns every
  -- tenant-scoped read into a scan with a filter.
  CONSTRAINT ex_engine_config_current EXCLUDE USING gist (
    tenant_id WITH =, portfolio_id WITH =, key WITH =, effective WITH &&
  )
);

-- The resolver reads every key for one scope at once, so the useful index is
-- the scope, not the key.
CREATE INDEX IF NOT EXISTS idx_engine_config_scope
  ON engine_config (tenant_id, portfolio_id, effective_from DESC);

-- One row, forever. Bumped on every config write; every process reads it to
-- decide whether its cached snapshot is stale, and its value is what the
-- decision row's `config_version` names.
CREATE TABLE IF NOT EXISTS config_epoch (
  one BOOLEAN PRIMARY KEY DEFAULT TRUE,
  version BIGINT NOT NULL DEFAULT 1,
  bumped_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ck_config_epoch_singleton CHECK (one)
);
INSERT INTO config_epoch (one, version) VALUES (TRUE, 1)
  ON CONFLICT (one) DO NOTHING;
