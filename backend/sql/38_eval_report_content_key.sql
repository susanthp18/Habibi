-- The identity of what a suite judged: sha256 over card, flow, prompt,
-- persona, guardrails, voice, tuning, attached pack hashes and the grader
-- version (agent_core/eval/provenance.py). NULL on rows filed before it
-- existed; those never open a gate by content.
ALTER TABLE eval_reports ADD COLUMN IF NOT EXISTS content_key TEXT;
CREATE INDEX IF NOT EXISTS idx_eval_reports_content_key
  ON eval_reports (tenant_id, bot_id, content_key) WHERE content_key IS NOT NULL;
