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
  transcript_snippet TEXT,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_leads_customer_id ON leads(customer_id);
CREATE INDEX IF NOT EXISTS idx_leads_interaction_id ON leads(interaction_id);
CREATE INDEX IF NOT EXISTS idx_leads_stage ON leads(stage);

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

