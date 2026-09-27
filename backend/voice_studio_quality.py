"""How each released version of a Voice Studio agent performs on real calls.

Every filed call records the release that handled it
(``interactions.source_payload.voiceStudio.versionNumber``); the call
intelligence pass scores it (QA cascade), measures the customer's mood and
finds any PII the agent itself spoke. This rolls that up per version, so a
release is judged on its calls and a regression shows beside the version that
caused it -- in Releases and before the next publish.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

#: What the agent must never say aloud (it may read the account's last four).
_AGENT_LEAK_TYPES = ("card", "aadhaar", "pan", "phone", "account", "dob", "secret", "upi", "passport")

_BY_VERSION = """
    WITH calls AS (
      SELECT i.id,
             (i.source_payload->'voiceStudio'->>'versionNumber')::int AS version,
             i.avg_sentiment,
             EXISTS (SELECT 1 FROM interaction_handoffs h WHERE h.interaction_id = i.id) AS handed_off
        FROM interactions i
       WHERE i.handler_bot_id = :bot
         AND i.source_payload ? 'voiceStudio'
         AND i.started_at >= now() - make_interval(days => :days)
    )
    SELECT c.version,
           count(*) AS calls,
           count(q.id) AS scored,
           round(avg(q.total_score), 1) AS qa_avg,
           count(*) FILTER (WHERE EXISTS (
             SELECT 1 FROM qa_scorecard_entries e JOIN qa_rubric_criteria r ON r.id = e.criterion_id
              WHERE e.scorecard_id = q.id AND r.critical_fail AND e.final_score = 0)) AS critical_fails,
           (SELECT count(*) FROM violations v WHERE v.interaction_id = ANY(array_agg(c.id))) AS violations,
           count(*) FILTER (WHERE EXISTS (
             SELECT 1 FROM redaction_records rr JOIN pii_findings f ON f.redaction_id = rr.id
               JOIN interaction_transcript t ON t.id = f.transcript_turn_id
              WHERE rr.interaction_id = c.id AND t.speaker = 'bot' AND f.accepted
                AND f.type = ANY(:leak_types))) AS agent_pii_calls,
           round(avg(CASE WHEN c.handed_off THEN 0 ELSE 1 END) * 100, 1) AS containment_pct,
           round(avg(c.avg_sentiment), 3) AS avg_sentiment
      FROM calls c
      LEFT JOIN qa_scorecards q ON q.interaction_id = c.id
     GROUP BY c.version
     ORDER BY c.version DESC NULLS LAST
"""


def by_version(workflow_id: int, *, days: int = 90) -> list[dict[str, Any]]:
    import db
    import voice_studio

    with db.engine.connect() as conn:
        rows = conn.execute(
            text(_BY_VERSION),
            {"bot": voice_studio.bot_id_for(workflow_id), "days": int(days),
             "leak_types": list(_AGENT_LEAK_TYPES)},
        ).mappings().all()
    out = []
    for r in rows:
        calls = int(r["calls"] or 0)
        out.append({
            "version": r["version"],  # None: calls on a draft (editor, before publish)
            "calls": calls,
            "scored": int(r["scored"] or 0),
            "qaAvg": float(r["qa_avg"]) if r["qa_avg"] is not None else None,
            "criticalFailPct": round(100 * int(r["critical_fails"] or 0) / calls, 1) if calls else None,
            "violationsPer100": round(100 * int(r["violations"] or 0) / calls, 1) if calls else None,
            "agentPiiCalls": int(r["agent_pii_calls"] or 0),
            "containmentPct": float(r["containment_pct"]) if r["containment_pct"] is not None else None,
            "avgSentiment": float(r["avg_sentiment"]) if r["avg_sentiment"] is not None else None,
        })
    return out
