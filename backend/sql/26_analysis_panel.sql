-- W7 · the analysis panel.
--
-- One row per CASE, not per decision. §8.7 of engines-production-design.md:
-- "the unit of analysis is the *case*, not the decision", and the design effect
-- `1 + (m-1)*ICC` is computed from `cases_per_customer`, never from a decision
-- count. Measured on the live corpus 2026-09-09: 268 dpd_tick day-cases across
-- 21 customers collapse to 40 delinquency spells -- m falls from 12.8 to 1.9 and
-- the design effect at ICC 0.2 from 3.36 to 1.18, which is a factor of 1.7 on
-- the minimum detectable effect.
--
-- `spell_ref` is the derived case key and lives only here. `treatment_decisions.trigger_ref`
-- stays the borrower's local date because it is also the sweep's daily dedupe key
-- ("one decision per account per local day", sweep.py); moving it to fix an
-- analysis-unit problem would break serving.

CREATE TABLE IF NOT EXISTS analysis_panel (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE CASCADE,
  account_id TEXT,
  trigger_kind TEXT NOT NULL,
  -- The case key. For dpd_tick this is the local date of the first tick in the
  -- current delinquency spell; for every other trigger it is trigger_ref
  -- unchanged, because those triggers are already one case per event.
  spell_ref TEXT NOT NULL,

  -- Arm. Randomisation is per customer x epoch (§8.7); `randomised_at` is the
  -- first decision on the case, which is what freezes the arm for it.
  variant TEXT,
  randomised_at timestamptz NOT NULL,

  -- Analysis.
  decisions INTEGER NOT NULL DEFAULT 0,
  enacted_decisions INTEGER NOT NULL DEFAULT 0,
  reach_outcome TEXT,
  cure_outcome TEXT,
  reward_inr numeric(14,2),
  observed_days INTEGER,
  mature BOOLEAN NOT NULL DEFAULT FALSE,
  censored BOOLEAN NOT NULL DEFAULT FALSE,
  censor_reason TEXT,
  first_decision_at timestamptz NOT NULL,
  last_decision_at timestamptz NOT NULL,

  -- Provenance. A panel row built under one label definition is not comparable
  -- with one built under another, and `logging_contract_version` is what §15.2
  -- W2 uses to exclude the pre-cutover fused-propensity rows from OPE forever.
  label_definition_version TEXT,
  logging_contract_version INTEGER,
  modes TEXT[] NOT NULL DEFAULT ARRAY[]::text[],
  built_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT uq_analysis_panel_case UNIQUE (
    tenant_id, customer_id, account_id, trigger_kind, spell_ref
  ),
  CONSTRAINT ck_analysis_panel_observed CHECK (
    observed_days IS NULL OR observed_days >= 0
  ),
  CONSTRAINT ck_analysis_panel_censor CHECK (
    censored IS FALSE OR censor_reason IS NOT NULL
  )
);

-- The cluster bootstrap resamples customers, so every read is "all cases for
-- this set of customers in this window in this arm".
CREATE INDEX IF NOT EXISTS idx_analysis_panel_cluster
  ON analysis_panel (tenant_id, variant, customer_id, randomised_at);
CREATE INDEX IF NOT EXISTS idx_analysis_panel_window
  ON analysis_panel (tenant_id, randomised_at DESC)
  WHERE mature IS TRUE;
