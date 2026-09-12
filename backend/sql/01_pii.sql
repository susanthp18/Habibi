-- PII column encryption: the functions and the one seam.
--
-- The contact endpoints and address of a borrower are stored encrypted
-- (pgcrypto, symmetric) in `customers_pii`; every reader and writer in the
-- application keeps using a relation named `customers`, which is a view that
-- decrypts on read and encrypts on write through INSTEAD OF triggers. The key
-- travels on the connection as the `app.pii_key` GUC -- a startup parameter,
-- the same way the tenant does (db_core.py) -- and is never interpolated into
-- SQL text. No key on the session means NULL on read and a refused write:
-- fail closed, like an unset tenant.
--
-- Lookups by phone go through an HMAC of the normalised digits so the index
-- still answers "which customer has this number" without decrypting the book.
-- The substring fallbacks (a legacy 10-digit row, the last-4 verification)
-- run over the decrypted column and scan.
-- ponytail: tail-4 verification decrypts per row; a masked-grade
-- phone_tail4 column would index it if the book grows past what a scan bears.
--
-- Owned here so sql/02 (fresh build) and sql/48 (the migration) create the
-- same objects. Future DDL must reference customers_pii(id), not the view.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION pii_key() RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.pii_key', true), '')
$$;

CREATE OR REPLACE FUNCTION pii_encrypt(plain text) RETURNS bytea
LANGUAGE plpgsql STABLE AS $$
BEGIN
  IF plain IS NULL THEN
    RETURN NULL;
  END IF;
  IF pii_key() IS NULL THEN
    RAISE EXCEPTION 'pii_key_unset: this session carries no app.pii_key; refusing to store plaintext'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN pgp_sym_encrypt(plain, pii_key());
END $$;

CREATE OR REPLACE FUNCTION pii_decrypt(cipher bytea) RETURNS text
LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN cipher IS NULL OR pii_key() IS NULL THEN NULL
    ELSE pgp_sym_decrypt(cipher, pii_key())
  END
$$;

-- HMAC of the normalised digits (or the lowercased address), for equality
-- lookups without decryption. NULL in, NULL out; no key, NULL out.
CREATE OR REPLACE FUNCTION pii_phone_hmac(plain text) RETURNS bytea
LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN plain IS NULL OR pii_key() IS NULL THEN NULL
    ELSE hmac(regexp_replace(plain, '[^0-9]', '', 'g'), pii_key(), 'sha256')
  END
$$;

CREATE OR REPLACE FUNCTION pii_text_hmac(plain text) RETURNS bytea
LANGUAGE sql STABLE AS $$
  SELECT CASE
    WHEN plain IS NULL OR pii_key() IS NULL THEN NULL
    ELSE hmac(lower(btrim(plain)), pii_key(), 'sha256')
  END
$$;
