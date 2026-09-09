"""Evaluate the real 14-day W6 gates; never synthesize missing evidence."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def evaluate(conn, *, tenant_id: str, days: int, declared_book_scale: int) -> list[str]:
    failures: list[str] = []
    finish = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    start = finish - timedelta(days=days - 1)
    pit = conn.execute(
        text(
            """
            SELECT (started_at AT TIME ZONE 'Asia/Kolkata')::date AS day,
                   count(*) AS runs,
                   sum(mismatch_count) AS mismatches,
                   bool_and(state = 'green') AS green
              FROM feature_pit_skew_runs
             WHERE tenant_id = :tid
               AND (started_at AT TIME ZONE 'Asia/Kolkata')::date
                   BETWEEN :start AND :finish
             GROUP BY day
            """
        ),
        {"tid": tenant_id, "start": start, "finish": finish},
    ).mappings().all()
    pit_by_day = {row["day"]: row for row in pit}
    sweeps = conn.execute(
        text(
            """
            SELECT local_date AS day,
                   bool_and(state = 'complete') AS complete,
                   sum(eligible_count)::bigint AS eligible,
                   sum(decided_count)::bigint AS decided,
                   bool_and(
                     completed_at IS NOT NULL
                     AND (completed_at AT TIME ZONE 'Asia/Kolkata')::time <= time '08:00'
                   ) AS by_eight
              FROM treatment_sweep_runs
             WHERE tenant_id = :tid AND local_date BETWEEN :start AND :finish
             GROUP BY local_date
            """
        ),
        {"tid": tenant_id, "start": start, "finish": finish},
    ).mappings().all()
    sweep_by_day = {row["day"]: row for row in sweeps}
    for offset in range(days):
        day = start + timedelta(days=offset)
        pit_day = pit_by_day.get(day)
        if (
            pit_day is None
            or not pit_day["green"]
            or int(pit_day["mismatches"] or 0) != 0
        ):
            failures.append(f"{day}:pit")
        sweep_day = sweep_by_day.get(day)
        if sweep_day is None:
            failures.append(f"{day}:sweep_missing")
            continue
        eligible = int(sweep_day["eligible"] or 0)
        decided = int(sweep_day["decided"] or 0)
        coverage = decided / eligible if eligible else 0.0
        if not sweep_day["complete"]:
            failures.append(f"{day}:shard_incomplete")
        if not sweep_day["by_eight"]:
            failures.append(f"{day}:after_0800")
        if eligible < declared_book_scale:
            failures.append(f"{day}:below_declared_scale")
        if coverage < 0.995:
            failures.append(f"{day}:coverage={coverage:.6f}")
    return failures


def main() -> int:
    days_raw = (os.getenv("W6_SOAK_DAYS") or "").strip()
    scale_raw = (os.getenv("W6_DECLARED_BOOK_SCALE") or "").strip()
    if not days_raw or not scale_raw:
        print("W6 soak: not yet measured (set W6_SOAK_DAYS and W6_DECLARED_BOOK_SCALE)")
        return 2
    days = int(days_raw)
    scale = int(scale_raw)
    if days < 14:
        print(f"W6 soak: not yet measured ({days}/14 consecutive days)")
        return 2
    import db

    with db.engine.connect() as conn:
        failures = evaluate(
            conn,
            tenant_id=db.current_tenant(),
            days=14,
            declared_book_scale=scale,
        )
    if failures:
        print("W6 soak: FAILED " + ", ".join(failures))
        return 1
    print(f"W6 soak: PASS 14/14 days at declared book scale {scale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
