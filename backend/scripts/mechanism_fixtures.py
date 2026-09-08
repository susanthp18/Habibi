"""Deterministic mechanism fixtures. Simulated only. Cannot train or enact.

    TREATMENT_SIMULATION_OK=1 python scripts/mechanism_fixtures.py
    TREATMENT_SIMULATION_OK=1 python scripts/mechanism_fixtures.py --purge

Every row carries mode='simulated', a fixed seed, a source tag, and a cleanup
key. Executors, trainers, and dashboards exclude them with ``mode <> 'simulated'``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text

import db

logger = logging.getLogger("mechanism_fixtures")
GUARD_ENV = "TREATMENT_SIMULATION_OK"
CLEANUP_KEY = "mechanism-fixtures-w3"
SEED = 20260906
MANIFEST = Path("models") / "mechanism_fixtures_manifest.json"


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid5(uuid.NAMESPACE_URL, prefix + CLEANUP_KEY).hex[:10].upper()}"


def purge(conn) -> dict[str, int]:
    counts = {}
    for table, clause in (
        ("treatment_decisions", "mode = 'simulated' AND trigger_ref LIKE :k || '%'"),
        ("promises", "id LIKE 'MF-%'"),
        ("ledger_entries", "id LIKE 'MF-%'"),
    ):
        try:
            counts[table] = conn.execute(
                text(f"DELETE FROM {table} WHERE {clause}"),
                {"k": CLEANUP_KEY},
            ).rowcount or 0
        except Exception:
            counts[table] = 0
    return counts


def seed(conn) -> dict[str, str]:
    """Insert a handful of named scenarios. The engine is not invoked."""
    tenant = db.current_tenant()
    row = conn.execute(
        text(
            """
            SELECT a.id AS account_id, a.customer_id
            FROM accounts a JOIN customers c ON c.id = a.customer_id
            WHERE c.tenant_id = :t
            ORDER BY a.id LIMIT 1
            """
        ),
        {"t": tenant},
    ).mappings().first()
    if row is None:
        raise SystemExit("no account to attach fixtures to")
    scenarios = {
        "active_mandate": "mandate active, unpaid instalment",
        "expired_mandate": "mandate expired",
        "self_cure": "dpd_tick wait, later paid without contact",
        "receipt_delivered": "whatsapp delivered receipt",
        "dnd_hold": "contact gated",
        "payment_reversal": "₹1 against ₹50000 then reversed",
        "worker_failure": "queued whatsapp never sent",
    }
    now = datetime.now(timezone.utc)
    for name in scenarios:
        conn.execute(
            text(
                """
                INSERT INTO treatment_decisions (
                  id, tenant_id, customer_id, account_id, trigger_kind, trigger_ref,
                  mode, recommender, recommender_version, feature_schema_version,
                  chosen_action, suppression_reason, created_at
                ) VALUES (
                  :id, :t, :c, :a, 'manual', :ref,
                  'simulated', 'fixture', '0', 'fixture',
                  'wait', NULL, :now
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": _id("TD" + name[:8]),
                "t": tenant,
                "c": row["customer_id"],
                "a": row["account_id"],
                "ref": f"{CLEANUP_KEY}:{name}",
                "now": now - timedelta(days=1),
            },
        )
    manifest = {
        "seed": SEED,
        "cleanupKey": CLEANUP_KEY,
        "mode": "simulated",
        "scenarios": scenarios,
        "writtenAt": now.isoformat(),
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return scenarios


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purge", action="store_true")
    args = parser.parse_args()
    if (os.getenv(GUARD_ENV) or "").strip() != "1":
        raise SystemExit(f"refusing to run without {GUARD_ENV}=1")
    with db.engine.begin() as conn:
        if args.purge:
            logger.info("purged %s", purge(conn))
            return
        names = seed(conn)
        logger.info("seeded %s", list(names))


if __name__ == "__main__":
    main()
