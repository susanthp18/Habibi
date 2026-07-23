"""QA coaching + calibration: schema polish + demo seed volume.

Adds screen-shaped columns the FE already expects (category / name /
target_scores), remaps legacy statuses, and seeds enough coaching +
calibration rows that the tabs aren't a one-row demo.

Revision ID: 20260722_0022
Revises: 20260722_0021
"""

from __future__ import annotations

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260722_0022"
down_revision: Union[str, Sequence[str], None] = "20260722_0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # --- columns ---
    conn.execute(
        sa.text(
            """
            ALTER TABLE coaching_actions
              ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT 'General'
            """
        )
    )
    conn.execute(
        sa.text(
            """
            ALTER TABLE calibration_sessions
              ADD COLUMN IF NOT EXISTS name TEXT,
              ADD COLUMN IF NOT EXISTS target_scores jsonb NOT NULL DEFAULT '{}'::jsonb
            """
        )
    )

    # Legacy status vocabulary → screen vocabulary
    conn.execute(
        sa.text(
            """
            UPDATE coaching_actions
            SET status = 'assigned'
            WHERE lower(status) IN ('open', 'pending', 'new')
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE calibration_sessions
            SET status = 'active'
            WHERE lower(status) IN ('open', 'pending', 'new')
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE calibration_sessions
            SET name = coalesce(nullif(name, ''), 'Calibration · ' || interaction_id)
            WHERE name IS NULL OR name = ''
            """
        )
    )

    # Enrich the single existing coaching row if still sparse
    conn.execute(
        sa.text(
            """
            UPDATE coaching_actions
            SET category = 'Compliance',
                action = CASE
                  WHEN action = 'Review disclosure phrasing'
                    THEN 'Read mini-Miranda before discussing dues'
                  ELSE action
                END,
                status = CASE WHEN status = 'open' THEN 'assigned' ELSE status END
            WHERE id = 'coach-1'
            """
        )
    )

    # Pull real scorecard / interaction anchors for additional seed rows
    rows = conn.execute(
        sa.text(
            """
            SELECT s.id AS scorecard_id,
                   s.interaction_id,
                   s.subject_user_id,
                   s.subject_bot_id
            FROM qa_scorecards s
            ORDER BY s.created_at DESC NULLS LAST, s.id
            LIMIT 8
            """
        )
    ).mappings().all()
    if not rows:
        return

    def pick(i: int):
        return rows[i % len(rows)]

    coaching = [
        {
            "id": "coach-2",
            "subject_user_id": "priya-nair",
            "subject_bot_id": None,
            "scorecard_id": pick(1)["scorecard_id"],
            "interaction_id": pick(1)["interaction_id"],
            "action": "Slow down on EMI recalculation explanation",
            "category": "Resolution",
            "status": "in_progress",
            "due_at": "2026-07-27T10:00:00Z",
        },
        {
            "id": "coach-3",
            "subject_user_id": "sara-khan",
            "subject_bot_id": None,
            "scorecard_id": pick(2)["scorecard_id"],
            "interaction_id": pick(2)["interaction_id"],
            "action": "Confirm PTP date + amount before wrap-up",
            "category": "Script Adherence",
            "status": "assigned",
            "due_at": "2026-07-25T10:00:00Z",
        },
        {
            "id": "coach-4",
            "subject_user_id": "arjun-mehta",
            "subject_bot_id": None,
            "scorecard_id": pick(3)["scorecard_id"],
            "interaction_id": pick(3)["interaction_id"],
            "action": "Acknowledge frustration before pitching top-up",
            "category": "Empathy",
            "status": "in_progress",
            "due_at": "2026-07-29T10:00:00Z",
        },
        {
            "id": "coach-5",
            "subject_user_id": "anita-rao",
            "subject_bot_id": None,
            "scorecard_id": None,
            "interaction_id": pick(4)["interaction_id"],
            "action": "Upsell only after resolving primary query",
            "category": "Upsell",
            "status": "done",
            "due_at": "2026-07-20T10:00:00Z",
        },
        {
            "id": "coach-6",
            "subject_user_id": None,
            "subject_bot_id": "kaia-v2-4",
            "scorecard_id": pick(0)["scorecard_id"],
            "interaction_id": pick(0)["interaction_id"],
            "action": "Prompt tune: reduce over-apology in dispute flow",
            "category": "Empathy",
            "status": "assigned",
            "due_at": "2026-07-26T10:00:00Z",
        },
    ]

    for row in coaching:
        # Skip if subject FK would fail
        if row["subject_user_id"]:
            exists = conn.execute(
                sa.text("SELECT 1 FROM users WHERE id = :id"),
                {"id": row["subject_user_id"]},
            ).fetchone()
            if not exists:
                continue
        if row["subject_bot_id"]:
            exists = conn.execute(
                sa.text("SELECT 1 FROM bots WHERE id = :id"),
                {"id": row["subject_bot_id"]},
            ).fetchone()
            if not exists:
                continue
        if row["scorecard_id"]:
            exists = conn.execute(
                sa.text("SELECT 1 FROM qa_scorecards WHERE id = :id"),
                {"id": row["scorecard_id"]},
            ).fetchone()
            if not exists:
                row = {**row, "scorecard_id": None}
        conn.execute(
            sa.text(
                """
                INSERT INTO coaching_actions (
                  id, subject_user_id, subject_bot_id, scorecard_id, interaction_id,
                  action, category, status, due_at
                ) VALUES (
                  :id, :subject_user_id, :subject_bot_id, :scorecard_id, :interaction_id,
                  :action, :category, :status, CAST(:due_at AS timestamptz)
                )
                ON CONFLICT (id) DO UPDATE SET
                  action = EXCLUDED.action,
                  category = EXCLUDED.category,
                  status = EXCLUDED.status,
                  due_at = EXCLUDED.due_at,
                  subject_user_id = EXCLUDED.subject_user_id,
                  subject_bot_id = EXCLUDED.subject_bot_id,
                  scorecard_id = EXCLUDED.scorecard_id,
                  interaction_id = EXCLUDED.interaction_id,
                  updated_at = now()
                """
            ),
            row,
        )

    # Notes via activity_events (same pattern as disputes / violations)
    notes = [
        ("coach-1", "Missed on 3 of last 10 calls."),
        ("coach-2", "Customer confused twice — walk through worked example."),
        ("coach-4", "Role-play scheduled Thursday."),
        ("coach-5", "Signed off — improvement visible on last 8 calls."),
        ("coach-6", "Route to Prompt Studio owner."),
    ]
    for entity_id, note in notes:
        exists = conn.execute(
            sa.text("SELECT 1 FROM coaching_actions WHERE id = :id"),
            {"id": entity_id},
        ).fetchone()
        if not exists:
            continue
        already = conn.execute(
            sa.text(
                """
                SELECT 1 FROM activity_events
                WHERE entity_type = 'coaching_action' AND entity_id = :eid
                  AND kind = 'note_added' AND note = :note
                LIMIT 1
                """
            ),
            {"eid": entity_id, "note": note},
        ).fetchone()
        if already:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO activity_events
                  (id, tenant_id, entity_type, entity_id, actor_kind, actor_user_id, kind, label, note)
                VALUES
                  (:id, 'hdfc.retail', 'coaching_action', :eid, 'human', 'priya-nair',
                   'note_added', 'Coaching note', :note)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": f"ACT-COACH-{entity_id}",
                "eid": entity_id,
                "note": note,
            },
        )

    # Calibration sessions — ensure at least 2 with reviewer scores
    criteria = [
        r[0]
        for r in conn.execute(
            sa.text(
                """
                SELECT c.id
                FROM qa_rubric_criteria c
                JOIN qa_rubric_sections s ON s.id = c.section_id
                WHERE s.rubric_id = 'rubric-v1'
                ORDER BY s.weight DESC, c.id
                """
            )
        ).fetchall()
    ]
    if not criteria:
        return

    def scores(base: float, jitter: float, seed: int) -> dict[str, float]:
        out: dict[str, float] = {}
        for i, cid in enumerate(criteria):
            # deterministic 0..5
            v = base + (((seed * 17 + i * 13) % 11) - 5) * (jitter / 5)
            out[cid] = max(0, min(5, round(v)))
        return out

    ix0 = pick(0)["interaction_id"]
    ix1 = pick(min(1, len(rows) - 1))["interaction_id"]

    sessions = [
        {
            "id": "cal-1",
            "interaction_id": ix0,
            "rubric_id": "rubric-v1",
            "status": "active",
            "name": "Weekly calibration — Dispute flow",
            "target_scores": scores(4.0, 0.6, 11),
        },
        {
            "id": "cal-2",
            "interaction_id": ix1,
            "rubric_id": "rubric-v1",
            "status": "active",
            "name": "Bot-vs-Human upsell handoff",
            "target_scores": scores(3.6, 0.8, 22),
        },
    ]

    # Retarget legacy calibration-1 → cal-1 shape if present
    conn.execute(
        sa.text(
            """
            UPDATE calibration_sessions
            SET id = id  -- no-op keep
            WHERE id = 'calibration-1'
            """
        )
    )
    legacy = conn.execute(
        sa.text("SELECT id FROM calibration_sessions WHERE id = 'calibration-1'")
    ).fetchone()
    if legacy:
        conn.execute(
            sa.text(
                """
                UPDATE calibration_sessions
                SET name = 'Weekly calibration — Dispute flow',
                    status = 'active',
                    target_scores = CAST(:ts AS jsonb),
                    interaction_id = :ix,
                    rubric_id = 'rubric-v1',
                    updated_at = now()
                WHERE id = 'calibration-1'
                """
            ),
            {"ts": json.dumps(sessions[0]["target_scores"]), "ix": ix0},
        )
        # Rename id is painful with FKs — keep calibration-1, also upsert cal-2
        sessions = [sessions[1]]

    for s in sessions:
        exists_ix = conn.execute(
            sa.text("SELECT 1 FROM interactions WHERE id = :id"),
            {"id": s["interaction_id"]},
        ).fetchone()
        if not exists_ix:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO calibration_sessions (
                  id, interaction_id, rubric_id, status, name, target_scores
                ) VALUES (
                  :id, :interaction_id, :rubric_id, :status, :name, CAST(:target_scores AS jsonb)
                )
                ON CONFLICT (id) DO UPDATE SET
                  interaction_id = EXCLUDED.interaction_id,
                  rubric_id = EXCLUDED.rubric_id,
                  status = EXCLUDED.status,
                  name = EXCLUDED.name,
                  target_scores = EXCLUDED.target_scores,
                  updated_at = now()
                """
            ),
            {
                **s,
                "target_scores": json.dumps(s["target_scores"]),
            },
        )

    # Reviewer scores
    reviewers = [
        ("cal-1", "priya-nair", scores(4.0, 1.2, 31), "Aligned on disclosure"),
        ("cal-1", "arjun-mehta", scores(3.4, 1.6, 32), None),
        ("cal-1", "sara-khan", scores(4.2, 1.0, 33), None),
        ("cal-2", "priya-nair", scores(3.6, 1.4, 41), None),
        ("cal-2", "anita-rao", scores(4.1, 1.6, 42), "Bot softer than human"),
        ("calibration-1", "priya-nair", scores(4.0, 1.0, 51), "Aligned"),
    ]

    for session_id, reviewer_id, sc, note in reviewers:
        sess_ok = conn.execute(
            sa.text("SELECT 1 FROM calibration_sessions WHERE id = :id"),
            {"id": session_id},
        ).fetchone()
        user_ok = conn.execute(
            sa.text("SELECT 1 FROM users WHERE id = :id"),
            {"id": reviewer_id},
        ).fetchone()
        if not sess_ok or not user_ok:
            continue
        rid = f"{session_id}-{reviewer_id}"
        # variance = mean abs delta vs target
        target_row = conn.execute(
            sa.text("SELECT target_scores FROM calibration_sessions WHERE id = :id"),
            {"id": session_id},
        ).fetchone()
        target = target_row[0] if target_row else {}
        if isinstance(target, str):
            target = json.loads(target)
        deltas = []
        for cid, val in sc.items():
            if cid in target:
                deltas.append(abs(float(val) - float(target[cid])))
        variance = round(sum(deltas) / len(deltas), 2) if deltas else 0.0
        conn.execute(
            sa.text(
                """
                INSERT INTO calibration_reviewer_scores (
                  id, session_id, reviewer_user_id, scores, notes, variance_from_target
                ) VALUES (
                  :id, :session_id, :reviewer_user_id, CAST(:scores AS jsonb), :notes, :variance
                )
                ON CONFLICT (id) DO UPDATE SET
                  scores = EXCLUDED.scores,
                  notes = EXCLUDED.notes,
                  variance_from_target = EXCLUDED.variance_from_target,
                  updated_at = now()
                """
            ),
            {
                "id": rid,
                "session_id": session_id,
                "reviewer_user_id": reviewer_id,
                "scores": json.dumps(sc),
                "notes": note,
                "variance": variance,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    for cid in ("coach-2", "coach-3", "coach-4", "coach-5", "coach-6"):
        conn.execute(sa.text("DELETE FROM coaching_actions WHERE id = :id"), {"id": cid})
    for sid in ("cal-1", "cal-2"):
        conn.execute(
            sa.text("DELETE FROM calibration_reviewer_scores WHERE session_id = :id"),
            {"id": sid},
        )
        conn.execute(sa.text("DELETE FROM calibration_sessions WHERE id = :id"), {"id": sid})
    conn.execute(
        sa.text("ALTER TABLE coaching_actions DROP COLUMN IF EXISTS category")
    )
    conn.execute(
        sa.text("ALTER TABLE calibration_sessions DROP COLUMN IF EXISTS name")
    )
    conn.execute(
        sa.text(
            "ALTER TABLE calibration_sessions DROP COLUMN IF EXISTS target_scores"
        )
    )
