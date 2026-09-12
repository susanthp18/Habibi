-- W13 · the allocator, and the price nobody is allowed to believe yet.
--
-- §10 of docs/design/engines-production-design.md. The optimiser is not the hard part and
-- the design note says so: Lagrangian decomposition prices each scarce resource,
-- subtracts price x usage, and eighteen million account x action variables fall
-- apart into independent per-account argmaxes. What this file is for is the part
-- that is hard -- making the price REFUSABLE.
--
-- Four columns here exist because of one row measured on `collections` on
-- 2026-09-11, which is the whole wave in miniature:
--
--     plan_date  | resource              | capacity | demand | dual_price | converged
--     2026-08-22 | mandate_presentations |     0.00 | 486.00 |     0.0000 | t
--
-- Read literally that says: four hundred and eighty-six mandate presentations
-- are planned against a budget of zero, and the solver declares it converged.
-- It is not what happened. `capacity_plan()` drops any resource whose
-- environment variable is unset, and `persist` wrote `capacity.get(resource,
-- 0.0)` -- so "nobody configured this" and "the budget is nothing" arrive in
-- the table as the same number. `capacity` therefore becomes NULLABLE and
-- `capacity_source` says which of the three states produced it: a C9 feed, an
-- environment variable, or nothing at all. A configured zero is now a real
-- constraint and the solve refuses against it, which is the correct answer to
-- presenting 486 mandates against a budget of nothing.
--
-- The other three columns are §10.1's defects 3 and 4. The old `converged` meant
-- "no resource is over capacity and no price hit the ceiling", measured at the
-- final prices of a coordinate descent with no dual bound -- so nothing in the
-- system could say how far from optimal the answer was, and §10.4's gate ("the
-- allocator's objective within 0.1% and its lambda within 1e-3 of the LP duals")
-- had nothing to compare. `dual_bound`, `primal_value` and `duality_gap` are
-- that comparison. `feasible` is §10.1 defect 2 as a column: the prototype
-- terminated at two million accounts with a capacity overshoot still present,
-- and an allocator that silently over-books the field team is worse than none.
--
-- `dual_price_raw` beside `dual_price` is §10.1 defect 3. lambda is more weakly
-- identified than the objective -- at tol 1e-4 the dual objective sat within
-- 0.002% of optimal while individual lambda_r drifted by up to 1.4 on prices of
-- Rs 11-19 -- and §10.3 publishes lambda as a business-facing price. So the
-- served number is damped day over day and the solver's own number is kept
-- beside it, because a stability claim measured on a damped series is a claim
-- about the damping.
--
-- NO BACKFILL. The four legacy rows keep `capacity_source = 'unset'` and
-- `feasible = false`, which is honest: they were never checked for feasibility
-- by any code that existed when they were written.

-- `capacity` becomes nullable: unconfigured is not zero. DROP NOT NULL is a
-- catalog write under ACCESS EXCLUSIVE held for microseconds -- no scan, no
-- rewrite -- so it needs no NOT VALID treatment.
ALTER TABLE capacity_duals ALTER COLUMN capacity DROP NOT NULL;

-- Every ADD COLUMN below is either nullable or carries a non-volatile DEFAULT,
-- which PG11+ stores in pg_attribute.attmissingval and reads back for rows that
-- predate the column. Catalog-only; no table rewrite.
ALTER TABLE capacity_duals
  ADD COLUMN IF NOT EXISTS capacity_source TEXT NOT NULL DEFAULT 'unset';
ALTER TABLE capacity_duals
  ADD COLUMN IF NOT EXISTS dual_price_raw numeric(14,4);
ALTER TABLE capacity_duals
  ADD COLUMN IF NOT EXISTS dual_bound numeric(18,2);
ALTER TABLE capacity_duals
  ADD COLUMN IF NOT EXISTS primal_value numeric(18,2);
ALTER TABLE capacity_duals
  ADD COLUMN IF NOT EXISTS duality_gap numeric(12,10);
ALTER TABLE capacity_duals
  ADD COLUMN IF NOT EXISTS feasible boolean NOT NULL DEFAULT false;
ALTER TABLE capacity_duals
  ADD COLUMN IF NOT EXISTS damping numeric(4,3);

-- The CHECK is added NOT VALID and validated separately: the ADD takes ACCESS
-- EXCLUSIVE for the catalog write only, and the scan that follows runs under
-- SHARE UPDATE EXCLUSIVE, which no reader blocks on. This is W0's online-DDL
-- standard and the same spelling sql/27 and sql/32 use.
ALTER TABLE capacity_duals DROP CONSTRAINT IF EXISTS ck_capacity_duals_source;
ALTER TABLE capacity_duals
  ADD CONSTRAINT ck_capacity_duals_source
  CHECK (capacity_source IN ('feed', 'env', 'unset')) NOT VALID;
ALTER TABLE capacity_duals VALIDATE CONSTRAINT ck_capacity_duals_source;

-- A price is served only when the solve that produced it converged AND the
-- primal repair reached feasibility. Indexing that predicate rather than
-- filtering it in Python is what stops a later reader forgetting the clause:
-- `allocate._todays_prices` is on the path that decides whether a borrower is
-- contacted at all.
CREATE INDEX IF NOT EXISTS idx_capacity_duals_servable
  ON capacity_duals (tenant_id, plan_date, resource)
  WHERE converged AND feasible;

COMMENT ON COLUMN capacity_duals.capacity IS
  'Units available. NULL means no capacity was configured for this resource, '
  'which prices at zero and reports as unpriced. A configured 0 is a real '
  'constraint and the solve refuses against it.';
COMMENT ON COLUMN capacity_duals.capacity_source IS
  'feed = the C9 bank_capacity feed; env = TREATMENT_CAPACITY_*, the documented '
  'fallback; unset = nobody configured it.';
COMMENT ON COLUMN capacity_duals.dual_price IS
  'Rupees forgone by giving up one unit, damped day over day. This is the '
  'number served into costs.for_action and published as a business price.';
COMMENT ON COLUMN capacity_duals.dual_price_raw IS
  'What this day''s solve alone said, before damping. A stability claim '
  'measured on dual_price is a claim about the damping.';
COMMENT ON COLUMN capacity_duals.duality_gap IS
  '(dual_bound - primal_value) / |dual_bound|. The honest distance from '
  'optimal; converged means this cleared the tolerance, not that a bisection '
  'stopped moving.';
COMMENT ON COLUMN capacity_duals.feasible IS
  'The primal repair reached usage_r <= K_r for every configured resource. '
  'False refuses to serve.';
