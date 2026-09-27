-- Tamper-evident call evidence: a per-tenant hash chain (evidence_chain.py).
-- Mirrors alembic/versions/20260927_0169_evidence_chain.py.
--
-- Each filed call appends one link: sha256 of the words as spoken (the
-- engine's transcript, before masking), the recording's sha256, and the
-- previous link's hash. Editing a call's evidence, or deleting or reordering
-- links, breaks every hash after it. No foreign key to interactions: a
-- retention purge must not rewrite the chain; the link outlives the call and
-- says so on verification.

CREATE TABLE IF NOT EXISTS interaction_evidence_chain (
  seq BIGSERIAL PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  interaction_id TEXT NOT NULL UNIQUE,
  transcript_sha256 TEXT NOT NULL,
  recording_sha256 TEXT,
  prev_hash TEXT NOT NULL,
  hash TEXT NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_interaction_evidence_chain_tenant_seq
  ON interaction_evidence_chain(tenant_id, seq);
