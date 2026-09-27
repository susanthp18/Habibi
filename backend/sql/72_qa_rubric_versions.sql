-- QA rubric versions: which criteria in different rubric versions ask the same thing.
-- Mirrors alembic/versions/20260927_0168_qa_rubric_versions.py.
--
-- A rubric edit is a new qa_rubrics row, never an in-place update: scorecards
-- and calibration sessions point at the version they were scored against, so
-- editing that row would silently re-mean every past score (db_qa.
-- create_rubric_version). The active version of a rubric is the newest enabled
-- row with the same tenant, channel and name -- no column needed for that.
--
-- Criterion ids are primary keys owned by one section of one version, so every
-- criterion in a new version gets a new id. lineage_id is what carries across:
-- a criterion whose label and description are unchanged keeps its
-- predecessor's lineage; a reworded or new one starts its own. NULL means the
-- criterion is the first of its lineage (lineage = id), which is every seeded
-- criterion, so the rule-keyed scorers ("cmp-recording", ...) keep matching.

ALTER TABLE qa_rubric_criteria ADD COLUMN IF NOT EXISTS lineage_id TEXT;
