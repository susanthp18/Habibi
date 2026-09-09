"""Dry-run-first, chunked W6 account shard backfill."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import db  # noqa: E402
from bank_boundary.facts import SHARD_COUNT, SHARD_VERSION, shard_key  # noqa: E402


def run(*, apply: bool, chunk_size: int) -> dict[str, int]:
    scanned = 0
    changed = 0
    after = ""
    while True:
        with db.engine.begin() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT a.id, c.tenant_id
                      FROM accounts a
                      JOIN customers c ON c.id = a.customer_id
                     WHERE a.id > :after
                       AND (a.shard_key IS NULL OR a.shard_version IS DISTINCT FROM :version)
                     ORDER BY a.id
                     LIMIT :limit
                    """
                ),
                {"after": after, "version": SHARD_VERSION, "limit": chunk_size},
            ).mappings().all()
            if not rows:
                break
            scanned += len(rows)
            after = str(rows[-1]["id"])
            if apply:
                conn.execute(
                    text(
                        """
                        UPDATE accounts
                           SET shard_key = :shard_key, shard_version = :shard_version
                         WHERE id = :account_id
                        """
                    ),
                    [
                        {
                            "account_id": str(row["id"]),
                            "shard_key": shard_key(
                                str(row["tenant_id"]),
                                str(row["id"]),
                                shard_count=SHARD_COUNT,
                            ),
                            "shard_version": SHARD_VERSION,
                        }
                        for row in rows
                    ],
                )
                changed += len(rows)
    return {"scanned": scanned, "changed": changed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the measured rows; absent means dry-run",
    )
    parser.add_argument("--chunk-size", type=int, default=500)
    args = parser.parse_args()
    result = run(apply=args.apply, chunk_size=max(1, args.chunk_size))
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(
        f"{mode} shard_version={SHARD_VERSION} shard_count={SHARD_COUNT} "
        f"scanned={result['scanned']} changed={result['changed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
