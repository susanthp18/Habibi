-- Dashboard export jobs share export_jobs with redaction ZIPs but have no
-- export_job_records rows. kind discriminates them so ANALYTICS_READ can
-- create a CSV without inventing a redaction id.
ALTER TABLE export_jobs
  ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'redaction';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'export_jobs_kind_check'
  ) THEN
    ALTER TABLE export_jobs
      ADD CONSTRAINT export_jobs_kind_check
      CHECK (kind IN ('redaction','dashboard'));
  END IF;
END $$;
