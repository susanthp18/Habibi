-- Break-glass self-approval of a rule set, carried on the row it published.
-- Mirrors alembic/versions/20260925_0159_policy_self_approval.py.
--
-- ck_policy_rule_sets_maker_checker refused approver = submitter outright. The
-- break-glass path (policy_rules.self_approval_allowed: a server setting, never
-- a grant) lets a named operator approve their own set; the database still
-- refuses it unless the reason is stored beside it, so no code path can waive
-- four eyes without saying why on the row itself.

ALTER TABLE policy_rule_sets ADD COLUMN IF NOT EXISTS self_approval_reason TEXT;

ALTER TABLE policy_rule_sets DROP CONSTRAINT IF EXISTS ck_policy_rule_sets_maker_checker;
ALTER TABLE policy_rule_sets ADD CONSTRAINT ck_policy_rule_sets_maker_checker CHECK (
  published_by_user_id IS NULL
  OR approved_by_user_id IS NULL
  OR published_by_user_id <> approved_by_user_id
  OR length(btrim(coalesce(self_approval_reason, ''))) >= 20
);
