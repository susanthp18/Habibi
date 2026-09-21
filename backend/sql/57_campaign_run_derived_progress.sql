-- Campaign progress is counted from campaign_targets, never stored on the run.
--
-- targets_total and targets_done were copies of what campaign_targets.state
-- already says. targets_done was bumped when a call was *placed*, so a run
-- whose dials all rang out read as done; targets_total was updated after create
-- had already returned the row, so a new run read as empty. Every endpoint now
-- counts the targets in the same query.
--
-- cadence was written on create and read by nothing: retries follow the card's
-- ladder for the objective (`card.outbound.cadence_for`). A column that looks
-- like a knob and is not one is dropped, not documented (see 37).
ALTER TABLE campaign_runs
  DROP COLUMN IF EXISTS targets_total,
  DROP COLUMN IF EXISTS targets_done,
  DROP COLUMN IF EXISTS cadence;
