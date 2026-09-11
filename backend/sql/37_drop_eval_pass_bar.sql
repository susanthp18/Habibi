-- EVALS-20: eval_tasks.pass_bar was written 'all' by every seeder and read by
-- nothing. A column that looks like a knob and is not one is dropped, not
-- documented.
ALTER TABLE eval_tasks DROP COLUMN IF EXISTS pass_bar;
