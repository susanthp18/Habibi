"""Alembic demo-seed gate.

Schema migrations must always run. Demo/synthetic row inserts run only when
``ALEMBIC_SEED_DEMO`` is truthy (1/true/yes/on). Default OFF so
``alembic upgrade head`` against a real customer DB never injects fake tenants.

Prefer ``scripts/seed_demo.py`` for local demo data going forward.
"""

from __future__ import annotations

import os


def seed_demo_enabled() -> bool:
    return (os.getenv("ALEMBIC_SEED_DEMO") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
