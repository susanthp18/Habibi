DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_teams_supervisor') THEN
    ALTER TABLE teams
      ADD CONSTRAINT fk_teams_supervisor
      FOREIGN KEY (supervisor_user_id) REFERENCES users(id) ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_agent_presence_interaction') THEN
    ALTER TABLE agent_presence
      ADD CONSTRAINT fk_agent_presence_interaction
      FOREIGN KEY (interaction_id) REFERENCES interactions(id) ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_customer_notes_interaction') THEN
    ALTER TABLE customer_notes
      ADD CONSTRAINT fk_customer_notes_interaction
      FOREIGN KEY (interaction_id) REFERENCES interactions(id) ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_interactions_deployment') THEN
    ALTER TABLE interactions
      ADD CONSTRAINT fk_interactions_deployment
      FOREIGN KEY (deployment_id) REFERENCES bot_deployments(id) ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_interaction_disclosures_rule') THEN
    ALTER TABLE interaction_disclosures
      ADD CONSTRAINT fk_interaction_disclosures_rule
      FOREIGN KEY (rule_id) REFERENCES compliance_rules(id) ON DELETE SET NULL;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_followups_lead') THEN
    ALTER TABLE followups
      ADD CONSTRAINT fk_followups_lead
      FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE;
  END IF;
END $$;

