-- One chain head per (tenant, entity).
--
-- The chain only ever covered entity_type = 'bot' (the Agent Studio's
-- history); consent edits, opt-outs and ledger postings -- the records a
-- regulator actually asks about -- sat outside every chain, so a consent
-- window or a waiver could be edited in place under a green "chain intact"
-- banner. change_log now keeps a chain per entity; the head table follows.
ALTER TABLE audit_chain_heads
  ADD COLUMN IF NOT EXISTS entity_type TEXT NOT NULL DEFAULT 'bot';
ALTER TABLE audit_chain_heads DROP CONSTRAINT IF EXISTS audit_chain_heads_pkey;
ALTER TABLE audit_chain_heads ADD PRIMARY KEY (tenant_id, entity_type);
