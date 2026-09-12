-- The delta sql/24 gained after its migration shipped, as one replayable
-- step (migration 20260912_0136). A fresh build reads sql/24 directly and
-- never needs this file; an upgraded database needs exactly this.
--
-- 1. btree_gist: the W6 substrate's exclusion constraints need it, and the
--    fresh build now creates it in sql/00.
-- 2. bank_inbound_manifests is unique per payload hash: the same source_ref
--    re-sent with different bytes is a second manifest (hash mismatch is
--    persisted as rejected, test_hash_mismatch_persists_rejected_manifest),
--    not a silent overwrite of the first.
-- 3. The evaluation schema has an owner that is not the app role. F9 says
--    the protected attributes are never readable by the process that makes
--    decisions; a grant the app role holds by ownership is not a grant the
--    database can withhold. evaluation_owner owns; evaluation_role reads and
--    writes; the app role keeps SELECT on fairness_readiness only.

CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE bank_inbound_manifests
  DROP CONSTRAINT IF EXISTS uq_bank_inbound_manifests;
ALTER TABLE bank_inbound_manifests
  ADD CONSTRAINT uq_bank_inbound_manifests UNIQUE (
    tenant_id, source, business_date, schema_version, source_ref, payload_hash
  );

DO $$
BEGIN
  CREATE ROLE evaluation_owner NOLOGIN NOSUPERUSER NOBYPASSRLS;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$
BEGIN
  CREATE ROLE evaluation_role NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER SCHEMA evaluation OWNER TO evaluation_owner;
ALTER TABLE evaluation.protected_attributes OWNER TO evaluation_owner;
ALTER TABLE evaluation.fairness_readiness OWNER TO evaluation_owner;
REVOKE ALL ON evaluation.protected_attributes FROM CURRENT_USER;
REVOKE ALL ON evaluation.protected_attributes FROM PUBLIC;
REVOKE INSERT, UPDATE ON evaluation.fairness_readiness FROM CURRENT_USER;
GRANT SELECT ON evaluation.fairness_readiness TO CURRENT_USER;
GRANT USAGE ON SCHEMA evaluation TO evaluation_role;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON evaluation.protected_attributes TO evaluation_role;
GRANT SELECT, INSERT, UPDATE
  ON evaluation.fairness_readiness TO evaluation_role;
