#!/usr/bin/env python3
"""Load demo/synthetic data into Postgres.

Runs ``seed_postgres.main()`` after refusing production. Prefer this over
``ALEMBIC_SEED_DEMO=1 alembic upgrade head`` for local demo graphs.

Usage (from backend/):
  .venv/Scripts/python scripts/seed_demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Load .env the same way the API does when available.
try:
    from env_loader import load_env

    load_env()
except Exception:
    pass


def _is_prod() -> bool:
    return (os.getenv("APP_ENV") or "dev").strip().lower() in {"prod", "production"}


def main() -> int:
    if _is_prod():
        raise SystemExit(
            "Refusing to seed demo data when APP_ENV=production|prod. "
            "Unset APP_ENV or set APP_ENV=dev for local demos."
        )
    # Allow alembic seed blocks if any tooling still uses them during seed.
    os.environ.setdefault("ALEMBIC_SEED_DEMO", "1")
    import seed_postgres

    seed_postgres.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
