CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
DECLARE
  table_name TEXT;
  mutable_tables TEXT[] := ARRAY[
    'tenants',
    'teams',
    'users',
    'bots',
    'agent_presence',
    'roles',
    'permissions',
    'products',
    'product_eligibility_rules',
    'customers',
    'customer_notes',
    'accounts',
    'emi_installments',
    'consent_records',
    'channel_consents',
    'interactions',
    'interaction_media',
    'identity_verifications',
    'conversations',
    'canned_responses',
    'payment_plans',
    'promises',
    'promise_reminders',
    'promise_installments',
    'disputes',
    'document_templates',
    'document_requests',
    'callbacks',
    'redaction_rule_configs',
    'redaction_records',
    'export_jobs',
    'kb_documents',
    'kb_chunks',
    'kb_index_jobs',
    'faq_pairs',
    'prompt_versions',
    'tts_voices',
    'persona_presets',
    'bot_deployments',
    'routing_rules',
    'sandbox_scenarios',
    'sandbox_runs',
    'providers',
    'provider_fields',
    'provider_configs',
    'webhook_endpoints',
    'webhook_retry_policies',
    'event_types',
    'webhook_deliveries',
    'billing_services',
    'invoices',
    'budgets',
    'budget_rules',
    'analytics_daily',
    'intent_aggregates',
    'escalation_reasons',
    'unanswered_questions',
    'qa_rubrics',
    'qa_rubric_sections',
    'qa_rubric_criteria',
    'qa_scorecards',
    'qa_scorecard_entries',
    'coaching_actions',
    'calibration_sessions',
    'calibration_reviewer_scores'
  ];
BEGIN
  FOREACH table_name IN ARRAY mutable_tables LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I', table_name, table_name);
    EXECUTE format(
      'CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
      table_name,
      table_name
    );
  END LOOP;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS ux_prompt_versions_one_published
  ON prompt_versions ((status))
  WHERE status = 'published';

