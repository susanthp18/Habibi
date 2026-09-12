-- W11a · the gate that can be evaluated: gates 14 and 15 get somewhere to live.
--
-- §8.12 of docs/design/engines-production-design.md lists fifteen gates. Two of them are
-- not statistics and cannot be computed from an artifact, and until this file
-- existed there was nowhere in the schema to put either:
--
--   Gate 14, PRE-REGISTRATION: "threshold, primary endpoint and horizon,
--   estimator, family size, alpha-spending schedule and stopping rule written
--   to the registry BEFORE the challenger ran."
--
--   Gate 15, HUMAN SIGN-OFF: "an independent validator who is not the model's
--   author, with a written record; then maker-checker."
--
-- Both are answers to the same failure. A promotion gate evaluated after the
-- fact is a gate whose threshold can be chosen to fit the number it is being
-- shown, and a family size decided after the looks is not multiplicity control.
-- W10a bound the evaluation to its artifact under an HMAC; this binds the
-- artifact to a claim somebody filed before they had seen the result.
--
-- W10a's promotion notes recorded Gate 15 as deferred because "no artifact
-- records an author". That was true. The pre-registration is where an author is
-- recorded, which is why the two gates arrive together.
--
-- EVERY FIELD IS NOT NULL, deliberately. A pre-registration whose fields are
-- optional is a note. If the estimator was not decided in advance, the
-- pre-registration has not happened, and a row that admits saying so is a row
-- that will be filed empty on the afternoon somebody wants to ship.

CREATE TABLE IF NOT EXISTS treatment_pre_registrations (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  target TEXT NOT NULL CHECK (target IN ('reach','timing','uplift')),

  -- §8.12 gate 14's contents, one column each.
  --
  -- `primary_endpoint` and `horizon_days` together are the estimand: "cure
  -- within 90 days" and "cure within 30" are different claims and a corpus
  -- cannot answer both at one alpha. `estimator` is named because §8.9 makes
  -- selecting the estimator on the promotion data and then reporting that
  -- estimator's concentration bound a way of voiding the bound.
  primary_endpoint TEXT NOT NULL CHECK (length(btrim(primary_endpoint)) > 0),
  horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
  estimator TEXT NOT NULL CHECK (length(btrim(estimator)) > 0),
  -- The margin the lower bound must clear, in the endpoint's own units. §8.12
  -- gate 7 makes it a multiple of a MEASURED per-borrower recovery SD, so this
  -- column holds the resolved number and `threshold_basis` holds the sentence
  -- that produced it -- because a bare 0.05 in a year's time is unreadable.
  threshold double precision NOT NULL,
  threshold_basis TEXT NOT NULL CHECK (length(btrim(threshold_basis)) > 0),
  -- §8.12 gate 9: "family DECLARED IN THE PRE-REGISTRATION = challengers x
  -- gates x horizons x estimators x looks x segments". Declared here or the
  -- BH adjustment is computed against a denominator chosen after the fact.
  family_size INTEGER NOT NULL CHECK (family_size > 0),
  alpha_spending TEXT NOT NULL CHECK (length(btrim(alpha_spending)) > 0),
  stopping_rule TEXT NOT NULL CHECK (length(btrim(stopping_rule)) > 0),

  -- §8.12 gate 15. `author` is whoever built the challenger; `validator` is
  -- whoever signed it off, and the two may not be the same person. Enforced by
  -- the database rather than by the promotion code remembering to check, which
  -- is the same choice `engine_config` and `retention_rules` already made.
  author TEXT NOT NULL CHECK (length(btrim(author)) > 0),
  validator TEXT,
  validated_at timestamptz,
  validation_note TEXT,

  -- The instant Gate 14 is about. An evaluation whose `computed_at` is not
  -- strictly after this was not pre-registered; it was described afterwards.
  filed_at timestamptz NOT NULL DEFAULT now(),
  filed_by TEXT NOT NULL CHECK (length(btrim(filed_by)) > 0),
  superseded_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT ck_treatment_prereg_maker_checker
    CHECK (validator IS NULL OR btrim(validator) <> btrim(author)),
  -- A validator without a signing instant, or an instant without a validator,
  -- is half a signature. Neither half is evidence.
  CONSTRAINT ck_treatment_prereg_signature
    CHECK ((validator IS NULL) = (validated_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_treatment_prereg_tenant_id
  ON treatment_pre_registrations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_treatment_prereg_target
  ON treatment_pre_registrations(tenant_id, target, filed_at DESC);

-- Which pre-registration licensed this promotion. Nullable because every row
-- already in the registry predates the gate, and backdating them would be
-- fabricating exactly the record the gate exists to require.
--
-- A nullable ADD COLUMN with no default is catalog-only on PG11+: it takes a
-- brief ACCESS EXCLUSIVE lock to update the catalog and rewrites no rows.
ALTER TABLE treatment_model_registry
  ADD COLUMN IF NOT EXISTS pre_registration_id TEXT
    REFERENCES treatment_pre_registrations(id) ON DELETE SET NULL;
