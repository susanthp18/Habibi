-- One dial per key. `outbound.reserve(idempotency_key=...)` inserts with
-- ON CONFLICT on this index and hands back the row that already exists, so a
-- retried worker job, a double-clicked operator button, or a replayed webhook
-- cannot reserve -- and therefore cannot place -- the same call twice.
--
-- Partial and nullable on purpose: every attempt written before this column
-- existed carries NULL, and an attempt whose caller has no natural key (an
-- ad-hoc dial from a script) may still leave it NULL. Uniqueness only applies
-- to rows that asked for it.
--
-- Catalog-only: a nullable ADD COLUMN with no default, and a partial unique
-- index over a table that is small on every deployment this repo has. On a book
-- where it is not, build the index CONCURRENTLY by hand before running this.

ALTER TABLE call_attempts ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS ux_call_attempts_idempotency
  ON call_attempts (tenant_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
