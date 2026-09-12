-- PII column encryption, the migration form (migration 20260912_0138).
-- A fresh build gets the same end state from sql/01_pii.sql + sql/02.
--
-- Runs on the owner's connection with app.pii_key set (alembic/env.py passes
-- it as a startup parameter; the migration refuses without one). Steps:
--   1. functions + extension (sql/01_pii.sql, applied verbatim)
--   2. customers -> customers_pii; encrypted and HMAC columns added
--   3. backfill from the plaintext columns
--   4. plaintext columns dropped
--   5. the `customers` view + INSTEAD OF triggers (identical to sql/02)
-- Foreign keys follow the table's OID through the rename; the sql/ mirrors
-- were rewritten to name customers_pii(id) for a fresh build.

DO $$
BEGIN
  IF pii_key() IS NULL THEN
    RAISE EXCEPTION 'pii_key_unset: set PII_ENCRYPTION_KEY before running migration 0138';
  END IF;
END $$;

ALTER TABLE customers RENAME TO customers_pii;

ALTER TABLE customers_pii
  ADD COLUMN IF NOT EXISTS phone_primary_enc BYTEA,
  ADD COLUMN IF NOT EXISTS phone_alt_enc BYTEA,
  ADD COLUMN IF NOT EXISTS email_enc BYTEA,
  ADD COLUMN IF NOT EXISTS address_enc BYTEA,
  ADD COLUMN IF NOT EXISTS phone_primary_hmac BYTEA,
  ADD COLUMN IF NOT EXISTS phone_alt_hmac BYTEA,
  ADD COLUMN IF NOT EXISTS email_hmac BYTEA;

UPDATE customers_pii SET
  phone_primary_enc  = pii_encrypt(phone_primary),
  phone_alt_enc      = pii_encrypt(phone_alt),
  email_enc          = pii_encrypt(email),
  address_enc        = pii_encrypt(address),
  phone_primary_hmac = pii_phone_hmac(phone_primary),
  phone_alt_hmac     = pii_phone_hmac(phone_alt),
  email_hmac         = pii_text_hmac(email);

ALTER TABLE customers_pii
  DROP COLUMN phone_primary,
  DROP COLUMN phone_alt,
  DROP COLUMN email,
  DROP COLUMN address;

CREATE INDEX IF NOT EXISTS idx_customers_phone_primary_hmac ON customers_pii(phone_primary_hmac)
  WHERE phone_primary_hmac IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_customers_phone_alt_hmac ON customers_pii(phone_alt_hmac)
  WHERE phone_alt_hmac IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_customers_email_hmac ON customers_pii(email_hmac)
  WHERE email_hmac IS NOT NULL;
