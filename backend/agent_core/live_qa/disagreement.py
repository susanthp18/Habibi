"""Disagreement mining: live QA verdict vs human scorecard. Rubric tweaks only."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text


def disagreements(*, limit: int = 50) -> dict[str, Any]:
    """Read-only. QA lead copies a rubric tweak; this never writes the rubric."""
    import db

    with db.engine.connect() as conn:
        rows = db._rows(
            conn.execute(
                text(
                    """
                    SELECT
                      lq.id AS live_id,
                      lq.interaction_id,
                      lq.verdict AS live_verdict,
                      lq.reason AS live_reason,
                      sc.id AS scorecard_id,
                      sc.band AS human_band,
                      sc.total_score AS human_score
                    FROM live_qa_decisions lq
                    JOIN qa_scorecards sc ON sc.interaction_id = lq.interaction_id
                    WHERE lq.tenant_id = :t
                      AND sc.status = 'final'
                      AND (
                        (lq.verdict = 'pass' AND sc.band = 'red')
                        OR (lq.verdict = 'fail_critical' AND sc.band = 'green')
                      )
                    ORDER BY lq.created_at DESC
                    LIMIT :n
                    """
                ),
                {"t": db._tenant(), "n": max(1, min(int(limit), 200))},
            )
        )
    items = []
    for row in rows:
        live = str(row.get("live_verdict") or "")
        band = str(row.get("human_band") or "")
        if live == "pass" and band == "red":
            tweak = "Tighten the live-QA pass bar — humans scored this call red."
        else:
            tweak = "Live QA barged a call humans scored green — review the fail_critical cell."
        items.append(
            {
                "interactionId": row.get("interaction_id"),
                "liveVerdict": live,
                "humanBand": band,
                "humanScore": float(row["human_score"]) if row.get("human_score") is not None else None,
                "suggestedRubricTweak": tweak,
                "applied": False,
            }
        )
    return {"applied": False, "count": len(items), "items": items}
