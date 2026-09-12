-- The `customers` view over customers_pii (sql/02) and its INSTEAD OF
-- triggers. Its own file so the migration (0138 / sql/48) can apply the
-- identical definition after renaming the live table.

-- The relation the application reads and writes. Decrypts on read, encrypts
-- on write; security_invoker so the base table's RLS policy applies to the
-- caller. The *_hmac columns are exposed so an equality lookup can use the
-- index without decrypting (db_inbox.find_customer_by_phone).
CREATE OR REPLACE VIEW customers WITH (security_invoker = true) AS
  SELECT id, tenant_id, assigned_user_id, name,
         pii_decrypt(phone_primary_enc) AS phone_primary,
         pii_decrypt(phone_alt_enc)     AS phone_alt,
         pii_decrypt(email_enc)         AS email,
         pii_decrypt(address_enc)       AS address,
         phone_primary_hmac, phone_alt_hmac, email_hmac,
         timezone, language, preferred_window, dnd, segment, risk, risk_score,
         last_contact_at, created_at, updated_at
    FROM customers_pii;

CREATE OR REPLACE FUNCTION customers_view_insert() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO customers_pii (
    id, tenant_id, assigned_user_id, name,
    phone_primary_enc, phone_alt_enc, email_enc, address_enc,
    phone_primary_hmac, phone_alt_hmac, email_hmac,
    timezone, language, preferred_window, dnd, segment, risk, risk_score,
    last_contact_at, created_at, updated_at
  ) VALUES (
    NEW.id, NEW.tenant_id, NEW.assigned_user_id, NEW.name,
    pii_encrypt(NEW.phone_primary), pii_encrypt(NEW.phone_alt),
    pii_encrypt(NEW.email), pii_encrypt(NEW.address),
    pii_phone_hmac(NEW.phone_primary), pii_phone_hmac(NEW.phone_alt),
    pii_text_hmac(NEW.email),
    NEW.timezone, NEW.language, NEW.preferred_window,
    COALESCE(NEW.dnd, false), NEW.segment, NEW.risk, NEW.risk_score,
    NEW.last_contact_at, COALESCE(NEW.created_at, now()), COALESCE(NEW.updated_at, now())
  );
  NEW.dnd := COALESCE(NEW.dnd, false);
  NEW.created_at := COALESCE(NEW.created_at, now());
  NEW.updated_at := COALESCE(NEW.updated_at, now());
  NEW.phone_primary_hmac := pii_phone_hmac(NEW.phone_primary);
  NEW.phone_alt_hmac := pii_phone_hmac(NEW.phone_alt);
  NEW.email_hmac := pii_text_hmac(NEW.email);
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION customers_view_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  -- Re-encrypt only what changed: pgp_sym_encrypt is randomised, so a blind
  -- rewrite would churn every row an unrelated UPDATE touched.
  UPDATE customers_pii SET
    tenant_id = NEW.tenant_id,
    assigned_user_id = NEW.assigned_user_id,
    name = NEW.name,
    phone_primary_enc = CASE WHEN NEW.phone_primary IS DISTINCT FROM OLD.phone_primary
                             THEN pii_encrypt(NEW.phone_primary) ELSE phone_primary_enc END,
    phone_alt_enc = CASE WHEN NEW.phone_alt IS DISTINCT FROM OLD.phone_alt
                         THEN pii_encrypt(NEW.phone_alt) ELSE phone_alt_enc END,
    email_enc = CASE WHEN NEW.email IS DISTINCT FROM OLD.email
                     THEN pii_encrypt(NEW.email) ELSE email_enc END,
    address_enc = CASE WHEN NEW.address IS DISTINCT FROM OLD.address
                       THEN pii_encrypt(NEW.address) ELSE address_enc END,
    phone_primary_hmac = pii_phone_hmac(NEW.phone_primary),
    phone_alt_hmac = pii_phone_hmac(NEW.phone_alt),
    email_hmac = pii_text_hmac(NEW.email),
    timezone = NEW.timezone,
    language = NEW.language,
    preferred_window = NEW.preferred_window,
    dnd = NEW.dnd,
    segment = NEW.segment,
    risk = NEW.risk,
    risk_score = NEW.risk_score,
    last_contact_at = NEW.last_contact_at,
    created_at = NEW.created_at,
    updated_at = NEW.updated_at
  WHERE id = OLD.id;
  NEW.phone_primary_hmac := pii_phone_hmac(NEW.phone_primary);
  NEW.phone_alt_hmac := pii_phone_hmac(NEW.phone_alt);
  NEW.email_hmac := pii_text_hmac(NEW.email);
  RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION customers_view_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM customers_pii WHERE id = OLD.id;
  RETURN OLD;
END $$;

DROP TRIGGER IF EXISTS customers_view_insert ON customers;
CREATE TRIGGER customers_view_insert INSTEAD OF INSERT ON customers
  FOR EACH ROW EXECUTE FUNCTION customers_view_insert();
DROP TRIGGER IF EXISTS customers_view_update ON customers;
CREATE TRIGGER customers_view_update INSTEAD OF UPDATE ON customers
  FOR EACH ROW EXECUTE FUNCTION customers_view_update();
DROP TRIGGER IF EXISTS customers_view_delete ON customers;
CREATE TRIGGER customers_view_delete INSTEAD OF DELETE ON customers
  FOR EACH ROW EXECUTE FUNCTION customers_view_delete();
