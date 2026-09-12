-- What the writers assume, stated in the schema (migration 20260912_0141).
--
-- Three uniquenesses every writer derives its ids from and no constraint
-- held: a conversation is one interaction (`_id("IX")` per thread), an EMI
-- schedule has one row per (account, index) and a plan one per (plan, index)
-- (`"{plan_id}-{idx}"`). Counted on the dev database before writing: zero
-- duplicates on all three. `conversations(customer_id, channel)` is NOT
-- unique and is not made so: the WhatsApp thread lookup takes the newest of
-- several by design, and four customers carry several today.
--
-- Four indexes the sweeps and the scrape predicate on and never had:
-- followups by (status, due_at) for the escalation sweep and by lead_id for
-- the work_items LATERAL; ledger_entries by (account_id, type, posted_at)
-- for the authority and follow-through reads; kb_index_jobs by status for
-- /metrics; usage_events by (source_ref, occurred_at) for the LLM gateway's
-- shared spend cap. Six prefix-redundant ones go: each was the leading
-- column of an index that exists or is created here.

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversations_interaction_id
  ON conversations(interaction_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_emi_installments_account_index
  ON emi_installments(account_id, installment_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_promise_installments_plan_index
  ON promise_installments(plan_id, installment_index);

CREATE INDEX IF NOT EXISTS idx_followups_status_due_at ON followups(status, due_at);
CREATE INDEX IF NOT EXISTS idx_followups_lead_id ON followups(lead_id);
CREATE INDEX IF NOT EXISTS idx_ledger_entries_account_type_posted
  ON ledger_entries(account_id, type, posted_at);
CREATE INDEX IF NOT EXISTS idx_kb_index_jobs_status ON kb_index_jobs(status);
CREATE INDEX IF NOT EXISTS idx_usage_events_source_occurred
  ON usage_events(source_ref, occurred_at) WHERE source_ref IS NOT NULL;

DROP INDEX IF EXISTS idx_leads_customer_id;             -- prefix of idx_leads_customer_product_stage
DROP INDEX IF EXISTS idx_webhook_deliveries_status;     -- prefix of idx_webhook_deliveries_claim
DROP INDEX IF EXISTS idx_kb_chunks_document_id;         -- prefix of uq_kb_chunks_document_id_chunk_index
DROP INDEX IF EXISTS idx_conversations_interaction_id;  -- replaced by the unique index above
DROP INDEX IF EXISTS idx_interaction_transcript_interaction_id;  -- prefix of the (interaction_id, turn_index) unique
DROP INDEX IF EXISTS idx_emi_installments_account_id;   -- prefix of uq_emi_installments_account_index
DROP INDEX IF EXISTS idx_promise_installments_plan_id;  -- prefix of uq_promise_installments_plan_index
