"""W1 soak / W5 five-day gates. Real duration unless SOAK_HOURS is set.

Default prints "not yet measured" rather than claiming success. Set
SOAK_HOURS to a positive number to wait that long before sampling.
Never places a call or sends a message.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

MIN_HOURS = 72.0
MIN_PLANS = 10_000


def main() -> int:
    hours = float(os.getenv("SOAK_HOURS") or "0")
    killed_worker = (os.getenv("SOAK_KILLED_WORKER_RUN") or "") == "1"
    if hours < MIN_HOURS or not killed_worker:
        print("honest-engines soak: not yet measured")
        print(
            "set SOAK_HOURS>=72 and SOAK_KILLED_WORKER_RUN=1 to run the "
            "real-duration cancelled/duplicate/lease gates"
        )
        return 2
    started = datetime.now(timezone.utc)
    print(f"soaking {hours} hours (no carrier I/O)")
    time.sleep(hours * 3600)
    metrics = _measure(started)
    print(json.dumps(metrics, sort_keys=True))
    passed = (
        metrics["due_plans"] >= MIN_PLANS
        and metrics["cancelled_share"] < 0.01
        and metrics["duplicate_sends"] == 0
        and metrics["lease_expiry_while_working"] == 0
    )
    print("honest-engines soak: passed" if passed else "honest-engines soak: failed")
    return 0 if passed else 1


def _measure(started: datetime) -> dict[str, object]:
    import db

    cutoff = started - timedelta(minutes=2)
    with db.engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT count(*) FILTER (
                         WHERE scheduled_at <= now()
                       )::int AS due_plans,
                       count(*) FILTER (
                         WHERE scheduled_at <= now() AND outcome = 'cancelled'
                       )::int AS cancelled
                  FROM treatment_decisions
                 WHERE created_at >= :started AND mode = 'live'
                """
            ),
            {"started": started},
        ).mappings().one()
        duplicate_sends = conn.execute(
            text(
                """
                SELECT count(*)::int FROM (
                  SELECT tenant_id, decision_id, channel
                    FROM enactment_attempts
                   WHERE created_at >= :started
                     AND state IN ('sent','reconciled','awaiting_settlement')
                   GROUP BY tenant_id, decision_id, channel
                  HAVING count(*) > 1
                ) duplicates
                """
            ),
            {"started": started},
        ).scalar()
        lease_expiry = conn.execute(
            text(
                """
                SELECT count(*)::int
                  FROM treatment_decisions
                 WHERE claimed_at IS NOT NULL
                   AND claimed_at >= :started
                   AND lease_until < :cutoff
                   AND enacted IS FALSE
                   AND outcome IS NULL
                """
            ),
            {"started": started, "cutoff": cutoff},
        ).scalar()
    due = int(row["due_plans"] or 0)
    cancelled = int(row["cancelled"] or 0)
    return {
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "due_plans": due,
        "cancelled": cancelled,
        "cancelled_share": cancelled / due if due else 1.0,
        "duplicate_sends": int(duplicate_sends or 0),
        "lease_expiry_while_working": int(lease_expiry or 0),
        "killed_worker_run": True,
    }


if __name__ == "__main__":
    raise SystemExit(main())
