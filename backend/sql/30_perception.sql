-- W9a · the perception store: what was said, who said the model said it, and
-- what it is allowed to touch.
--
-- §12.3 of engines-production-design.md. Today `analyze_turn` classifies every
-- customer turn — intent, sentiment, abuse, legal, language — and the result
-- survives as three untyped columns on `interaction_transcript`: `intent`,
-- `intent_score`, `sentiment_delta`. Which model produced them, with what
-- confidence, whether it abstained, whether a guard passed it, and what the
-- inputs were: none of that is recorded anywhere, so the DPO's question —
-- *which borrower's data went to which model, when, and for what purpose* —
-- has no query.
--
-- Two properties are load-bearing and both are here.
--
--   PROVENANCE IS A COLUMN, not a convention. §12.3's table has four classes
--   and they permit different things: `system_of_record` and `operator_input`
--   may enter the expected-value arithmetic, `borrower_utterance` and any
--   speech-derived `model_inference` may only ever reach the veto stack, as a
--   flag, in the suppressive direction. `agent_core/feature_provenance.py`
--   enforces the EV half at artifact load; this column is what makes the
--   distinction exist at all.
--
--   TENANT LEADS THE KEY. §12.3 says it and §13.1 makes it a CI assertion:
--   every index on a tenant-scoped table leads with `tenant_id`, or a
--   cross-tenant scan is one planner decision away.
--
-- What is NOT here, stated so the gap is a decision rather than a silence: the
-- GPU plane. No mmBERT, no Qwen3.5-4B extractor, no adapter, no weights bundle
-- and no sha to assert at startup — the cards have an 8-16 week lead time and
-- none of them exist. `source_model` therefore reads `keyword` or the Azure
-- deployment name today, and the columns that describe an adapter and a
-- quantisation are present and NULL, because they are what a run row must
-- carry the day one is loaded and adding them later means backfilling the
-- audit trail of a model-risk artefact.

-- ---------------------------------------------------------------------------
-- The facts
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS perception_facts (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  id TEXT NOT NULL,
  customer_id TEXT REFERENCES customers_pii(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE CASCADE,
  turn_index INTEGER NOT NULL DEFAULT 0,

  fact_key TEXT NOT NULL,
  -- An enum, a band or a boolean. Never a sentence: §12.3 requires these to be
  -- recorded "as codes and bands, never free text", because this table is
  -- retained for training and a transcript in it is a second copy of the
  -- customer record with a different retention class.
  fact_value jsonb NOT NULL DEFAULT 'null'::jsonb,

  provenance TEXT NOT NULL CHECK (provenance IN (
    'system_of_record', 'operator_input', 'borrower_utterance', 'model_inference'
  )),
  -- The provenance classes of every input the producing model consumed. A
  -- `model_inference` fact whose own inputs included speech is speech-derived
  -- however many classifiers wrapped it, and this array is how that is known
  -- rather than assumed.
  input_provenance TEXT[] NOT NULL DEFAULT '{}',

  confidence numeric(5,4),
  -- A first-class metric, not an error state. §12.6: a model that never says
  -- "I don't know" will invent a promise-to-pay.
  abstained BOOLEAN NOT NULL DEFAULT FALSE,

  source_model TEXT NOT NULL,
  source_adapter TEXT,
  schema_version TEXT NOT NULL DEFAULT 'p1',
  guard_verdict TEXT,
  -- ASR error is upstream of everything. Below the floor no `borrower_utterance`
  -- fact is written at all -- silence beats a fabricated promise date.
  asr_confidence_band TEXT,

  observed_at timestamptz NOT NULL DEFAULT now(),
  valid_at tstzrange NOT NULL DEFAULT tstzrange(now(), NULL),
  recorded_at timestamptz NOT NULL DEFAULT now(),
  -- Append-only, so a correction is a second row and this closes the first.
  --
  -- The correction is not hypothetical: `crm_sink._handle_understanding`
  -- persists the keyword baseline first and then overwrites it when the LLM
  -- answers. Overwriting destroys the baseline, and the baseline is exactly
  -- what a model-risk reviewer needs in order to ask whether the model
  -- improved on it. Two rows keep both answers and the order they arrived in.
  superseded_at timestamptz,
  superseded_by TEXT,

  CONSTRAINT pk_perception_facts PRIMARY KEY (tenant_id, id),
  CONSTRAINT ck_perception_facts_valid_nonempty CHECK (NOT isempty(valid_at)),
  -- A fact belongs to a turn or to a customer. One with neither is unattached
  -- to anything a subject-access request could find.
  CONSTRAINT ck_perception_facts_subject CHECK (
    customer_id IS NOT NULL OR interaction_id IS NOT NULL
  )
);

-- One live value per key per turn. Superseded rows are unconstrained, which is
-- what lets the history accumulate underneath.
CREATE UNIQUE INDEX IF NOT EXISTS uq_perception_facts_current
  ON perception_facts (tenant_id, interaction_id, turn_index, fact_key)
  WHERE superseded_at IS NULL;

-- The read `features._perception` makes: this borrower, up to this instant.
CREATE INDEX IF NOT EXISTS idx_perception_facts_pit
  ON perception_facts (tenant_id, customer_id, observed_at DESC)
  WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_perception_facts_interaction
  ON perception_facts (tenant_id, interaction_id, turn_index);

-- Append-only, enforced. `w6_guard_fact_mutation` is not reused: it is written
-- against the substrate's `known_from`/`known_to` shape, which these rows do
-- not have. Same rule, four fewer columns.
CREATE OR REPLACE FUNCTION w9_guard_perception_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'perception facts are append-only';
  END IF;
  IF (to_jsonb(NEW) - ARRAY['superseded_at','superseded_by'])
       IS DISTINCT FROM
     (to_jsonb(OLD) - ARRAY['superseded_at','superseded_by']) THEN
    RAISE EXCEPTION 'perception fact values and provenance are immutable';
  END IF;
  IF OLD.superseded_at IS NOT NULL THEN
    RAISE EXCEPTION 'a superseded perception fact may not be superseded again';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_perception_facts_guard ON perception_facts;
CREATE TRIGGER trg_perception_facts_guard
  BEFORE UPDATE OR DELETE ON perception_facts
  FOR EACH ROW EXECUTE FUNCTION w9_guard_perception_mutation();

-- ---------------------------------------------------------------------------
-- The runs
-- ---------------------------------------------------------------------------

-- One row per invocation. This is what makes the engine's own LLM spend a line
-- in the cost model rather than an unattributed platform overhead (§8's
-- denominator), and it is the answer to the DPO's question.
CREATE TABLE IF NOT EXISTS perception_runs (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
  id TEXT NOT NULL,
  customer_id TEXT REFERENCES customers_pii(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE CASCADE,
  turn_index INTEGER NOT NULL DEFAULT 0,

  model TEXT NOT NULL,
  adapter TEXT,
  quantisation TEXT,
  -- The prompt's hash, never the prompt. A prompt carries the borrower's own
  -- words by definition.
  prompt_hash TEXT,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  latency_ms INTEGER,
  -- Priced by `usage_meter`, which already converts every Azure unit to INR.
  -- NULL on the keyword path: a keyword pass costs nothing, and a zero would
  -- claim that had been measured.
  cost_inr numeric(12,4),
  guard_verdict TEXT,
  -- 'ok', 'abstained', 'shed', 'timeout', 'error' -- open on purpose, because
  -- a new degradation mode must be recordable the day it is discovered.
  outcome TEXT NOT NULL DEFAULT 'ok',
  created_at timestamptz NOT NULL DEFAULT now(),

  CONSTRAINT pk_perception_runs PRIMARY KEY (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS idx_perception_runs_recent
  ON perception_runs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_perception_runs_interaction
  ON perception_runs (tenant_id, interaction_id, turn_index);
