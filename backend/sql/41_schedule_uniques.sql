-- Uniqueness the writers assumed and the schema did not hold.
--
-- An EMI schedule slot and a payment-plan instalment slot are one row each by
-- construction (the writers number them 1..n); nothing stopped a re-run of a
-- seed or an import from filing a second row for the same slot, after which
-- "the third instalment" was two amounts. One presence row per user is the
-- same shape. Each is live data with zero duplicates, so these are the honest
-- constraints, not a cleanup.
-- The EMI and instalment slot indexes live in sql/49 under the migration's
-- names (uq_emi_installments_account_index, uq_promise_installments_plan_index);
-- this file created them a second time under other names until sql/52.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_presence_user
  ON agent_presence (user_id);
