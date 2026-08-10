CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  product_id TEXT REFERENCES products(id),
  owner_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  team_id TEXT REFERENCES teams(id) ON DELETE SET NULL,
  stage TEXT NOT NULL CHECK (stage IN ('interested','contacted','qualified','won','lost')),
  source TEXT,
  sentiment_at_capture TEXT CHECK (sentiment_at_capture IN ('positive','neutral','negative')),
  sentiment_score numeric(5,3),
  estimated_value numeric(14,2),
  won_amount numeric(14,2),
  loss_reason TEXT,
  offer_amount numeric(14,2),
  offer_roi TEXT,
  priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
  captured_at timestamptz,
  -- Stamped when stage moves to won/lost. Without it "won this week" and
  -- "average time to close" cannot be computed at all — the UI derived both
  -- from a field the API never populated, so both read zero forever.
  closed_at timestamptz,
  transcript_snippet TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_leads_customer_id ON leads(customer_id);
CREATE INDEX IF NOT EXISTS idx_leads_interaction_id ON leads(interaction_id);
CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);
CREATE INDEX IF NOT EXISTS idx_leads_closed_at ON leads(closed_at);
-- Backs the duplicate-lead guard in db.create_lead. Deliberately NOT a unique
-- index: re-engaging a lost lead and capturing a second, larger offer are both
-- legitimate, and a supervisor must be able to force one through. The race
-- between the two concurrent writers (voice tool + WhatsApp worker) is closed
-- with a transaction-scoped advisory lock instead, the same way
-- _idempotent_response serialises replays.
CREATE INDEX IF NOT EXISTS idx_leads_customer_product_stage
  ON leads(customer_id, product_id, stage);

CREATE TABLE IF NOT EXISTS lead_eligibility (
  id TEXT PRIMARY KEY,
  lead_id TEXT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
  rule_id TEXT REFERENCES product_eligibility_rules(id) ON DELETE SET NULL,
  label TEXT NOT NULL,
  passed boolean NOT NULL,
  reason TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lead_eligibility_lead_id ON lead_eligibility(lead_id);

-- ---------------------------------------------------------------------------
-- Next-Best-Offer engine (agent_core/reco)
--
-- The recommender is deliberately NOT the LLM. These three tables are what let
-- deterministic code choose the product and let the model choose only the
-- words: `product_relations` is the complementarity/conflict graph,
-- `product_campaigns` is the marketing switchboard, and `offer_decisions` is
-- the append-only log that makes the whole thing auditable and — later —
-- trainable. Log first, recommend second: without the decision log there is no
-- offline evaluation and no labelled data for a propensity model.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS product_relations (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  related_product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  -- complements: holding A raises affinity for B.  requires: B needs A.
  -- excludes: never offer B to a holder of A.  upgrades: B supersedes A.
  relation TEXT NOT NULL CHECK (relation IN ('complements','requires','excludes','upgrades')),
  affinity numeric(4,3) NOT NULL DEFAULT 0.500,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_product_relations_triple
  ON product_relations(product_id, related_product_id, relation);
CREATE INDEX IF NOT EXISTS idx_product_relations_related ON product_relations(related_product_id);

CREATE TABLE IF NOT EXISTS product_campaigns (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  -- NULL means "no restriction"; an empty array would mean "matches nothing",
  -- which is a very different and much easier mistake to make by accident.
  segment_in TEXT[],
  risk_not_in TEXT[],
  priority numeric(4,3) NOT NULL DEFAULT 0.500,
  quota_total INTEGER,
  quota_used INTEGER NOT NULL DEFAULT 0,
  starts_at timestamptz,
  ends_at timestamptz,
  enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_product_campaigns_product ON product_campaigns(product_id);
CREATE INDEX IF NOT EXISTS idx_product_campaigns_enabled ON product_campaigns(enabled);

CREATE TABLE IF NOT EXISTS offer_decisions (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  interaction_id TEXT REFERENCES interactions(id) ON DELETE SET NULL,
  channel TEXT NOT NULL,
  -- shadow rows are scored but never spoken. They are the counterfactual half
  -- of the training set, so they must be kept, not filtered out at write time.
  -- 'simulated' is synthetic traffic from scripts/simulate_offer_decisions.py:
  -- a first-class provenance value so every dashboard, the trainer and the
  -- replay harness can exclude it with one predicate instead of each inventing
  -- its own heuristic for "is this real".
  mode TEXT NOT NULL DEFAULT 'live' CHECK (mode IN ('live','shadow','simulated')),
  -- A/B arm (RECO_AB_SPLIT, or session.extra.recoVariant). NULL when no
  -- experiment is running. Recorded per decision because two arms can share a
  -- recommender — a mode holdout runs the same scorer and says nothing — and
  -- without this they are indistinguishable after the fact.
  variant TEXT,
  recommender TEXT NOT NULL,
  recommender_version TEXT NOT NULL,
  feature_schema_version TEXT NOT NULL,
  features jsonb NOT NULL DEFAULT '{}'::jsonb,
  candidates jsonb NOT NULL DEFAULT '[]'::jsonb,
  excluded jsonb NOT NULL DEFAULT '{}'::jsonb,
  chosen_product_id TEXT REFERENCES products(id) ON DELETE SET NULL,
  suggested_amount numeric(14,2),
  score numeric(6,4),
  presented boolean NOT NULL DEFAULT false,
  presented_at timestamptz,
  response TEXT CHECK (response IN ('interested','declined','deferred','not_reached')),
  responded_at timestamptz,
  lead_id TEXT REFERENCES leads(id) ON DELETE SET NULL,
  suppression_reason TEXT,
  latency_ms INTEGER,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_offer_decisions_customer ON offer_decisions(customer_id);
CREATE INDEX IF NOT EXISTS idx_offer_decisions_interaction ON offer_decisions(interaction_id);
CREATE INDEX IF NOT EXISTS idx_offer_decisions_lead ON offer_decisions(lead_id);
-- Backs the per-customer frequency cap and the per-product cool-down.
CREATE INDEX IF NOT EXISTS idx_offer_decisions_cooldown
  ON offer_decisions(customer_id, chosen_product_id, created_at DESC);
-- Partial: most rows carry no variant, and indexing those is write cost for
-- nothing.
CREATE INDEX IF NOT EXISTS idx_offer_decisions_variant
  ON offer_decisions(variant, created_at) WHERE variant IS NOT NULL;

