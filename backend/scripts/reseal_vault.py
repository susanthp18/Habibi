"""Re-seal every vault secret under the current master-key derivation.

The vault used to derive its key as a bare SHA-256 of VAULT_MASTER_KEY; it is
scrypt now (agent_core/vault/seal.py). Tokens sealed under the old key stay
readable, so nothing breaks at boot -- this rewrites them so the old
derivation can eventually be deleted. Idempotent: a token already in the new
format is left alone.

    python scripts/reseal_vault.py            # every tenant, reports counts
    python scripts/reseal_vault.py --dry-run  # count only

Runs as the schema owner (MIGRATION_DATABASE_URL), like rotate_pii_key.py,
because vault_refs is row-level secured for the application role.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text  # noqa: E402

from importlib import import_module  # noqa: E402

vault = import_module("agent_core.vault.seal")


def main() -> int:
    dry = "--dry-run" in sys.argv
    url = (os.getenv("MIGRATION_DATABASE_URL") or os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise SystemExit("MIGRATION_DATABASE_URL is required")
    engine = create_engine(url)
    resealed = kept = 0
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, ciphertext FROM vault_refs WHERE ciphertext IS NOT NULL")).mappings().all()
        for row in rows:
            if not vault.is_legacy(str(row["ciphertext"])):
                kept += 1
                continue
            plaintext = vault.open_sealed(str(row["ciphertext"]))
            if not dry:
                conn.execute(
                    text("UPDATE vault_refs SET ciphertext = :c, updated_at = now() WHERE id = :id"),
                    {"c": vault.seal(plaintext), "id": row["id"]},
                )
            resealed += 1
    engine.dispose()
    print(f"vault: {resealed} resealed, {kept} already current{' (dry run)' if dry else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
