-- Which way a sandbox scenario's call goes (sim_persona.direction / .objective).
--
-- Sandbox Live ran every rehearsal as an inbound call, so an agent that had
-- just rung an overdue borrower asked "how can I help you today?". The seeded
-- scenarios are all calls we place; seed_postgres.py writes the fields on a
-- fresh install, this sets them on a database seeded before it did. A scenario
-- that already says which way it goes is left alone. Re-runnable.
UPDATE sandbox_scenarios
SET sim_persona = sim_persona || '{"direction": "outbound", "objective": "dpd_reminder"}'::jsonb,
    updated_at = now()
WHERE id IN ('angry-waiver', 'hardship', 'pay-today', 'legal-threat')
  AND NOT (sim_persona ? 'direction');
