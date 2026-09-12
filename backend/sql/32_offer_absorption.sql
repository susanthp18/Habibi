-- W12 · the offer family, absorbed.
--
-- §9.7 and §15.4 of docs/design/engines-production-design.md: the upsell engine is absorbed
-- at the INFRASTRUCTURE layer -- one log, one propensity contract, one
-- exploration mechanism, one registry, one promotion gate, one OPE panel, one
-- retention policy -- while the ESTIMATOR stays separate, because in-call
-- cross-sell is a different causal problem on a doubly selected population.
--
-- `offer_decisions` was created by migration 0051 and never given the three
-- columns 0085 added to `treatment_decisions` the same fortnight: propensity,
-- policy version, explore kind. 0085's own docstring explains why that omission
-- is terminal -- you can retrain a model on old data forever, but you can never
-- go back and record what the odds were. Measured on `collections` on
-- 2026-09-10: 16 offer decisions, ALL on logging contract 1, NONE carrying a
-- propensity, and ZERO recording a response in the log's entire history. So the
-- corpus is simultaneously unevaluable and unlabelled, and every day the engine
-- runs adds one more row of both.
--
-- This file is where the absorption lands. It does not drop `offer_decisions`:
-- the write is dual for one window (see agent_core/reco/decisions.py) and §14.5
-- wants a historical decision reproducible from a restore.
--
-- THE INVARIANT THAT MAKES THE ABSORPTION LAWFUL, restated here because the
-- schema is what enforces half of it: the offer is scored on the call and it is
-- NEVER SPOKEN ON IT. A promotional utterance inside a recorded collections
-- call reclassifies the entire communication as Promotional -- which then
-- subjects the collections call itself to the borrower's DND -- markets without
-- a suitability finding, and, on a delinquent borrower, is the textbook
-- mis-selling fact pattern carrying refund plus compensation. So a scored offer
-- is written with chosen_channel = 'deferred_promotional' and delivered later
-- on the promotional series. That value existing in the CHECK is what makes the
-- state representable; `agent_core/reco/` is what makes it the only one.

-- ---------------------------------------------------------------------------
-- 1. The family discriminator, and the offer columns
-- ---------------------------------------------------------------------------

-- A non-volatile DEFAULT on PG11+ is a catalog write, not a heap rewrite: the
-- existing rows keep reading the default from pg_attribute until they are next
-- updated. `treatment_decisions` holds 278 rows on `collections` and is not
-- partitioned, so there is nothing here for CONCURRENTLY to defer either way.
ALTER TABLE treatment_decisions
  ADD COLUMN IF NOT EXISTS action_family TEXT NOT NULL DEFAULT 'treatment';

ALTER TABLE treatment_decisions
  ADD COLUMN IF NOT EXISTS product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS suggested_amount numeric(14,2),
  -- Named `offer_response` rather than `response`: `outcome` on this table is
  -- the collections label and the two must never be read for each other. An
  -- offer's response is what the borrower said about a product; an outcome is
  -- what happened to the arrears.
  ADD COLUMN IF NOT EXISTS offer_response TEXT,
  ADD COLUMN IF NOT EXISTS responded_at timestamptz,
  ADD COLUMN IF NOT EXISTS lead_id TEXT REFERENCES leads(id) ON DELETE SET NULL,
  -- `presented` stops meaning "the bot said it on the call" the moment this
  -- wave lands -- see §9.7. It means "delivered on the promotional series".
  ADD COLUMN IF NOT EXISTS presented boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS presented_at timestamptz;

DO $$
BEGIN
  ALTER TABLE treatment_decisions
    ADD CONSTRAINT ck_treatment_decisions_action_family
    CHECK (action_family IN ('treatment','offer')) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER TABLE treatment_decisions VALIDATE CONSTRAINT ck_treatment_decisions_action_family;

DO $$
BEGIN
  ALTER TABLE treatment_decisions
    ADD CONSTRAINT ck_treatment_decisions_offer_response
    CHECK (
      offer_response IS NULL
      OR offer_response IN ('interested','declined','deferred','not_reached')
    ) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER TABLE treatment_decisions VALIDATE CONSTRAINT ck_treatment_decisions_offer_response;

-- An offer row must name a product and a treatment row must not. Without this
-- the family column is a label somebody sets rather than a fact the table
-- holds, and the first mis-set row is invisible until an estimator averages
-- across two action spaces.
DO $$
BEGIN
  ALTER TABLE treatment_decisions
    ADD CONSTRAINT ck_treatment_decisions_family_shape
    CHECK (
      (action_family = 'offer' AND chosen_action IN ('offer','wait'))
      OR (action_family = 'treatment' AND product_id IS NULL
          AND suggested_amount IS NULL AND offer_response IS NULL
          AND lead_id IS NULL)
    ) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER TABLE treatment_decisions VALIDATE CONSTRAINT ck_treatment_decisions_family_shape;

-- ---------------------------------------------------------------------------
-- 2. The two CHECK repairs, under W0's online-DDL standard
-- ---------------------------------------------------------------------------
--
-- Both constraints exist under two spellings in the wild: sql/05_collections.sql
-- writes them inline, which auto-names them `treatment_decisions_<col>_check`,
-- while the migrations that touched them since named their own. Dropping both
-- names is not belt-and-braces -- it is the only way this file produces the same
-- schema on a fresh install and on a database built by migration.
--
-- Re-added NOT VALID and validated separately, per §15.2 W0: "0 migrations in
-- the repo take ACCESS EXCLUSIVE without NOT VALID or CONCURRENTLY". The ADD
-- takes the lock for a catalog write; the VALIDATE takes only SHARE UPDATE
-- EXCLUSIVE while it scans.

ALTER TABLE treatment_decisions DROP CONSTRAINT IF EXISTS treatment_decisions_chosen_action_check;
ALTER TABLE treatment_decisions DROP CONSTRAINT IF EXISTS ck_treatment_decisions_action;
ALTER TABLE treatment_decisions
  ADD CONSTRAINT ck_treatment_decisions_action CHECK (
    chosen_action IS NULL OR chosen_action IN (
      'wait','sms','whatsapp','voice_bot','human_call','field_visit','legal_notice',
      'represent_mandate','emi_date_change','self_service_plan',
      -- W12: the absorbed family's one action. Scoring an offer IS the action;
      -- what varies is the product, which is `product_id`.
      'offer'
    )
  ) NOT VALID;
ALTER TABLE treatment_decisions VALIDATE CONSTRAINT ck_treatment_decisions_action;

ALTER TABLE treatment_decisions DROP CONSTRAINT IF EXISTS treatment_decisions_chosen_channel_check;
ALTER TABLE treatment_decisions DROP CONSTRAINT IF EXISTS ck_treatment_decisions_channel;
ALTER TABLE treatment_decisions
  ADD CONSTRAINT ck_treatment_decisions_channel CHECK (
    chosen_channel IS NULL OR chosen_channel IN (
      'voice','whatsapp','sms','email','chat','field',
      -- W12 / §9.7. Not a channel a message goes out on: a state meaning
      -- "scored during a servicing contact, held for the promotional series".
      -- The collections channels above are exactly the ones it may not become
      -- without a fresh, consented, suitability-gated decision.
      'deferred_promotional'
    )
  ) NOT VALID;
ALTER TABLE treatment_decisions VALIDATE CONSTRAINT ck_treatment_decisions_channel;

-- Replaces idx_offer_decisions_cooldown. Partial because the offer family is
-- ~5% of the table and indexing the rest is write cost for nothing.
CREATE INDEX IF NOT EXISTS idx_treatment_decisions_offer_cooldown
  ON treatment_decisions (tenant_id, customer_id, product_id, created_at DESC)
  WHERE action_family = 'offer';

-- ---------------------------------------------------------------------------
-- 3. `suitability_assessments` -- the mis-selling audit trail
-- ---------------------------------------------------------------------------
--
-- §9.7 names the columns. `expires_at` is added because §9.7 says an offer
-- decision "refuses to enact without a CURRENT row", and `current` has no
-- meaning without an end. NULL means open-ended, which is a decision the
-- assessor makes rather than a default the schema smuggles in.
--
-- `evidence_ref` is NOT NULL and non-empty on the same rule
-- sql/31_promotion_gate.sql applies to a pre-registration: an audit trail whose
-- evidence pointer is optional is a note. `capture.evaluate_product_eligibility`
-- already answers "is this borrower eligible for this product" from the catalog;
-- this table answers the different question a supervisor is asked, which is
-- whether the product was SUITABLE for them and who says so.
CREATE TABLE IF NOT EXISTS suitability_assessments (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers_pii(id) ON DELETE CASCADE,
  -- RESTRICT, not CASCADE: deleting a product must not delete the record that
  -- it was once assessed and sold.
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
  assessed_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz,
  assessor TEXT NOT NULL,
  -- Which rulebook the finding was made under, so a finding made in March is
  -- readable against March's policy rather than today's.
  policy_version INTEGER,
  verdict TEXT NOT NULL,
  evidence_ref TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ck_suitability_verdict CHECK (verdict IN ('suitable','unsuitable')),
  CONSTRAINT ck_suitability_assessor CHECK (btrim(assessor) <> ''),
  CONSTRAINT ck_suitability_evidence CHECK (btrim(evidence_ref) <> ''),
  CONSTRAINT ck_suitability_window CHECK (expires_at IS NULL OR expires_at > assessed_at)
);

-- The engine's hot read: the current finding for one borrower and one product.
CREATE INDEX IF NOT EXISTS idx_suitability_current
  ON suitability_assessments (tenant_id, customer_id, product_id, assessed_at DESC);
