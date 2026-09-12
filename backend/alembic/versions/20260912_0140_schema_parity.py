"""Schema parity: every deployment carries the schema files' names and defaults.

Revision ID: 20260912_0140
Revises: 20260912_0139

``scripts/migrate_from_empty.py`` diffs the chain against the ``sql/`` build.
Three defaults and one index had drifted, and 75 constraints carried the
name the migration gave them where the schema files let Postgres name them.
A name is schema: a later ``DROP CONSTRAINT`` by name works on one build and
fails on the other. The schema files are what every fresh database is built
from, so the migrated databases move to their names.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "20260912_0140"
down_revision: Union[str, None] = "20260912_0139"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (name the migration gave it, name the schema file gives it)
RENAMES: tuple[tuple[str, str], ...] = (
    ("customers_pkey", "customers_pii_pkey"),
    ("customers_assigned_user_id_fkey", "customers_pii_assigned_user_id_fkey"),
    ("customers_tenant_id_fkey", "customers_pii_tenant_id_fkey"),
    ("fk_kb_documents_tenant", "kb_documents_tenant_id_fkey"),
    ("ck_agent_obligations_kind", "agent_obligations_kind_check"),
    ("ck_agent_obligations_state", "agent_obligations_state_check"),
    ("ck_bot_deployments_traffic_pct", "bot_deployments_traffic_pct_check"),
    ("ck_call_attempts_answered_by", "call_attempts_answered_by_check"),
    ("ck_call_attempts_attempt_no", "call_attempts_attempt_no_check"),
    ("ck_call_attempts_purpose", "call_attempts_purpose_check"),
    ("ck_call_attempts_state", "call_attempts_state_check"),
    ("ck_call_cadence_state_state", "call_cadence_state_state_check"),
    ("ck_call_outcomes_business", "call_outcomes_business_check"),
    ("ck_call_outcomes_connection", "call_outcomes_connection_check"),
    ("ck_call_outcomes_escalation", "call_outcomes_escalation_check"),
    ("ck_call_outcomes_reason", "call_outcomes_nonpayment_reason_check"),
    ("ck_call_outcomes_summary_source", "call_outcomes_summary_source_check"),
    ("ck_campaign_runs_source", "campaign_runs_source_check"),
    ("ck_campaign_runs_status", "campaign_runs_status_check"),
    ("ck_campaign_targets_state", "campaign_targets_state_check"),
    ("ck_channel_consents_purpose", "channel_consents_purpose_check"),
    ("ck_contact_events_actor_kind", "contact_events_actor_kind_check"),
    ("ck_contact_events_channel", "contact_events_channel_check"),
    ("ck_contact_events_direction", "contact_events_direction_check"),
    ("ck_contact_events_outcome", "contact_events_outcome_check"),
    ("ck_contact_events_purpose", "contact_events_purpose_check"),
    ("ck_followups_channel", "followups_channel_check"),
    ("ck_ledger_entries_type", "ledger_entries_type_check"),
    ("ck_number_pools_kind", "number_pools_kind_check"),
    ("ck_payment_events_first_touch_channel", "payment_events_first_touch_channel_check"),
    ("ck_payment_events_kind", "payment_events_kind_check"),
    ("ck_payment_events_reason", "payment_events_reason_check"),
    ("ck_payment_events_source", "payment_events_source_check"),
    ("ck_payment_events_status", "payment_events_status_check"),
    ("ck_payment_intents_confirm_channel", "payment_intents_confirm_channel_check"),
    ("ck_payment_intents_provider", "payment_intents_provider_check"),
    ("ck_payment_intents_status", "payment_intents_status_check"),
    ("ck_policy_rule_sets_publication_state", "policy_rule_sets_publication_state_check"),
    ("ck_policy_rules_citation", "policy_rules_citation_check"),
    ("ck_pool_numbers_state", "pool_numbers_state_check"),
    ("ck_product_relations_relation", "product_relations_relation_check"),
    ("ck_promise_reminders_kind", "promise_reminders_kind_check"),
    ("ck_treatment_decisions_mode", "treatment_decisions_mode_check"),
    ("ck_treatment_decisions_outcome", "treatment_decisions_outcome_check"),
    ("ck_treatment_decisions_trigger", "treatment_decisions_trigger_kind_check"),
    ("ck_treatment_holds_confirmation", "treatment_holds_confirmation_state_check"),
    ("ck_treatment_holds_kind", "treatment_holds_kind_check"),
    ("ck_treatment_holds_source", "treatment_holds_source_check"),
    ("ck_webhook_deliveries_mode", "webhook_deliveries_delivery_mode_check"),
    ("contact_delivery_events_message_id_fkey", "fk_contact_delivery_events_message"),
    ("customers_risk_check", "customers_pii_risk_check"),
    ("fk_bot_tool_calls_conversation", "bot_tool_calls_conversation_id_fkey"),
    ("fk_bot_tool_calls_interaction", "bot_tool_calls_interaction_id_fkey"),
    ("fk_bot_tool_calls_job", "bot_tool_calls_job_id_fkey"),
    ("fk_bot_tool_calls_turn", "bot_tool_calls_transcript_turn_id_fkey"),
    ("fk_bot_turn_jobs_conversation", "bot_turn_jobs_conversation_id_fkey"),
    ("fk_coaching_actions_tenant", "coaching_actions_tenant_id_fkey"),
    ("fk_compliance_rules_tenant", "compliance_rules_tenant_id_fkey"),
    ("fk_document_templates_tenant", "document_templates_tenant_id_fkey"),
    ("fk_export_jobs_tenant", "export_jobs_tenant_id_fkey"),
    ("fk_idempotency_keys_tenant", "idempotency_keys_tenant_id_fkey"),
    ("fk_kb_snapshots_tenant", "kb_snapshots_tenant_id_fkey"),
    ("fk_persona_presets_tenant", "persona_presets_tenant_id_fkey"),
    ("fk_products_tenant", "products_tenant_id_fkey"),
    ("fk_prompt_versions_bot", "prompt_versions_bot_id_fkey"),
    ("fk_prompt_versions_tenant", "prompt_versions_tenant_id_fkey"),
    ("fk_qa_rubrics_tenant", "qa_rubrics_tenant_id_fkey"),
    ("fk_retrieval_logs_tenant", "retrieval_logs_tenant_id_fkey"),
    ("fk_retrieval_logs_turn", "retrieval_logs_transcript_turn_id_fkey"),
    ("fk_sandbox_scenarios_tenant", "sandbox_scenarios_tenant_id_fkey"),
    ("fk_tts_voices_tenant", "tts_voices_tenant_id_fkey"),
    ("fk_usage_events_interaction", "usage_events_interaction_id_fkey"),
    ("fk_voice_sandbox_sessions_tenant", "voice_sandbox_sessions_tenant_id_fkey"),
    ("fk_whatsapp_outbound_jobs_conversation", "whatsapp_outbound_jobs_conversation_id_fkey"),
    ("tts_voice_catalog_provider_id_fkey", "fk_tts_voice_catalog_provider"),
)


def _rename(conn, old: str, new: str) -> None:
    row = conn.execute(
        text(
            "SELECT c.conrelid::regclass::text FROM pg_constraint c"
            " WHERE c.conname = :old AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = :new)"
        ),
        {"old": old, "new": new},
    ).first()
    if row:
        conn.execute(text(f'ALTER TABLE {row[0]} RENAME CONSTRAINT "{old}" TO "{new}"'))


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("ALTER TABLE qa_scorecards ALTER COLUMN status SET DEFAULT 'unscored'"))
    conn.execute(text("ALTER TABLE routing_rules ALTER COLUMN conditions SET DEFAULT '[]'::jsonb"))
    conn.execute(text("ALTER TABLE routing_rules ALTER COLUMN name SET DEFAULT ''"))
    for old, new in RENAMES:
        _rename(conn, old, new)


def downgrade() -> None:
    conn = op.get_bind()
    for old, new in RENAMES:
        _rename(conn, new, old)
