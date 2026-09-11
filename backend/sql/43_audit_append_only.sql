-- audit_log is append-only for everyone but the schema owner.
--
-- The hash chain detects an altered or deleted entry after the fact; nothing
-- prevented it. The application role could UPDATE or DELETE any row, so the
-- "append-only audit tables" control the hardening gate listed as deferred
-- was a promise the schema did not keep. Migrations and operator maintenance
-- run as the owner (MIGRATION_DATABASE_URL) and are the only writers of a
-- correction; the application appends.
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
  owner_name text;
BEGIN
  SELECT r.rolname INTO owner_name
    FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner
   WHERE c.oid = TG_RELID;
  IF pg_has_role(current_user, owner_name, 'MEMBER') THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'audit_log is append-only (% by %)', TG_OP, current_user
    USING ERRCODE = 'insufficient_privilege';
END $$;

DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
CREATE TRIGGER audit_log_append_only
  BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
