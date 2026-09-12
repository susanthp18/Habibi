"""Re-encrypt the PII columns under a new key.

    docker compose exec -T api python scripts/rotate_pii_key.py --new-key <key>

Runs as the schema owner (MIGRATION_DATABASE_URL) with the *current* key on
the connection (PII_ENCRYPTION_KEY) and the new one as an argument. One
transaction: every row of customers_pii is decrypted with the old key and
encrypted and re-HMACed with the new one; then every process must be
restarted with PII_ENCRYPTION_KEY set to the new value. Nothing is written
to disk or logged.

Deliberately not automated: a key rotation is an operator's act with a
restart on the other side of it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SAFE = re.compile(r"^[A-Za-z0-9_\-]{32,256}$")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--new-key", required=True, help="32-256 chars of [A-Za-z0-9_-]")
    ap.add_argument("--dry-run", action="store_true", help="count rows, write nothing")
    args = ap.parse_args()
    if not _SAFE.fullmatch(args.new_key):
        print("new key must be 32-256 characters of [A-Za-z0-9_-]", file=sys.stderr)
        return 2

    import pii_key
    from sqlalchemy import create_engine, text

    if not pii_key.configured():
        print("PII_ENCRYPTION_KEY (the current key) is not set", file=sys.stderr)
        return 2
    url = (os.getenv("MIGRATION_DATABASE_URL") or "").strip()
    if not url:
        print("MIGRATION_DATABASE_URL (the owner) is required", file=sys.stderr)
        return 2
    engine = create_engine(url, connect_args={"options": pii_key.connect_option()})
    with engine.begin() as conn:
        total = conn.execute(text("SELECT count(*) FROM customers_pii")).scalar()
        if args.dry_run:
            print(f"would re-encrypt {total} rows")
            return 0
        rewritten = conn.execute(
            text(
                """
                UPDATE customers_pii SET
                  phone_primary_enc  = pgp_sym_encrypt(pii_decrypt(phone_primary_enc), :k),
                  phone_alt_enc      = pgp_sym_encrypt(pii_decrypt(phone_alt_enc), :k),
                  email_enc          = pgp_sym_encrypt(pii_decrypt(email_enc), :k),
                  address_enc        = pgp_sym_encrypt(pii_decrypt(address_enc), :k),
                  phone_primary_hmac = hmac(regexp_replace(pii_decrypt(phone_primary_enc), '[^0-9]', '', 'g'), :k, 'sha256'),
                  phone_alt_hmac     = hmac(regexp_replace(pii_decrypt(phone_alt_enc), '[^0-9]', '', 'g'), :k, 'sha256'),
                  email_hmac         = hmac(lower(btrim(pii_decrypt(email_enc))), :k, 'sha256')
                """
            ),
            {"k": args.new_key},
        ).rowcount
    print(f"re-encrypted {rewritten} of {total} rows; restart every process with the new PII_ENCRYPTION_KEY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
