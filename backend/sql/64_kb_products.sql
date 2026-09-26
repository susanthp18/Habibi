-- What each knowledge-base product is about, and how callers ask for it.
-- Mirrors alembic/versions/20260925_0160_kb_products.py.
--
-- Product routing used to be six hand-typed keyword lists that disagreed with
-- each other and with the way people actually talk (VS-7956F27B36: "something
-- for my travel to Singapore" matched none of them for travel insurance). It
-- is now semantic: agent_core/product_resolver.py compares the embedded
-- question against these phrasings and scopes retrieval only on a clear winner.
--
-- Nothing here is hand-typed. kb_products.py has the analysis model read each
-- product's own documents and write a summary plus the ways a caller would ask
-- about it without naming it; source_hash records which documents it read, so
-- a changed document regenerates them. Operators can add phrasings of their
-- own (origin 'operator'), which a regeneration keeps.

CREATE TABLE IF NOT EXISTS kb_products (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  product_key TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready','failed')),
  error TEXT,
  source_hash TEXT,
  model TEXT,
  generated_at timestamptz,
  updated_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, product_key)
);
CREATE INDEX IF NOT EXISTS idx_kb_products_tenant_id ON kb_products(tenant_id);

CREATE TABLE IF NOT EXISTS kb_product_utterances (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  product_key TEXT NOT NULL,
  text TEXT NOT NULL CHECK (length(btrim(text)) BETWEEN 2 AND 300),
  -- title: a name the product goes by (its title, or another the documents
  -- use), matched exactly; document: a question its own FAQ answers, verbatim;
  -- generated: written by the model from the documents; operator: added on the
  -- Knowledge Base screen, never regenerated.
  origin TEXT NOT NULL CHECK (origin IN ('title','document','generated','operator')),
  embedding vector(1536),
  created_by_user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (tenant_id, product_key)
    REFERENCES kb_products(tenant_id, product_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_kb_product_utterances_product
  ON kb_product_utterances(tenant_id, product_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_product_utterances_text
  ON kb_product_utterances(tenant_id, product_key, lower(btrim(text)));

-- Restated so a database that ran the first version of this file (which had
-- no 'document' origin) is brought up to date; a no-op on a fresh one.
ALTER TABLE kb_product_utterances DROP CONSTRAINT IF EXISTS kb_product_utterances_origin_check;
ALTER TABLE kb_product_utterances ADD CONSTRAINT kb_product_utterances_origin_check
  CHECK (origin IN ('title','document','generated','operator'));
